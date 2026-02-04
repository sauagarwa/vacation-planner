from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, TypedDict, Tuple

import requests
import yaml
from langgraph.graph import END, StateGraph
from openai import OpenAI


logger = logging.getLogger("langgraph_planner")


class PlannerState(TypedDict, total=False):
    inputs: Dict[str, Any]
    outputs: Dict[str, str]
    tasks_output: List[Dict[str, Any]]


_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::([^}]*))?\}")
_MCP_SESSIONS: Dict[str, str] = {}

# ✅ Cache tool schemas per (url, tool_name) so we don't call tools/list repeatedly
_TOOL_SCHEMAS: Dict[Tuple[str, str], Dict[str, Any]] = {}


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):

        def repl(m: re.Match) -> str:
            var = m.group(1)
            default = m.group(2) if m.group(2) is not None else ""
            return os.getenv(var, default)

        return _ENV_PATTERN.sub(repl, value)

    if isinstance(value, list):
        return [_expand_env(v) for v in value]

    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}

    return value


def _load_graph_config(path: str | os.PathLike) -> dict:
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"LangGraph config not found: {cfg_path}")
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("LangGraph config must be a mapping")
    return _expand_env(data)


class _DotDict(dict):
    def __getattr__(self, name: str) -> Any:
        return self.get(name, "")

    def __getitem__(self, key: str) -> Any:
        return self.get(key, "")


def _render_template(value: Any, context: Dict[str, Any]) -> Any:
    if isinstance(value, str):
        try:
            return value.format_map(context)
        except KeyError:
            return value
    if isinstance(value, list):
        return [_render_template(v, context) for v in value]
    if isinstance(value, dict):
        return {k: _render_template(v, context) for k, v in value.items()}
    return value


def _summarize_output(text: str) -> str:
    if not text:
        return "No output"
    first_line = text.splitlines()[0].strip()
    return first_line if first_line else "Output generated"


def _normalize_arg(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.lower() in ("true", "false"):
            return stripped.lower() == "true"
        if re.fullmatch(r"-?\d+", stripped):
            return int(stripped)
        if re.fullmatch(r"-?\d+\.\d+", stripped):
            return float(stripped)
        return stripped
    if isinstance(value, list):
        return [_normalize_arg(v) for v in value]
    if isinstance(value, dict):
        return {k: _normalize_arg(v) for k, v in value.items()}
    return value


def _sanitize_args(value: Any) -> Any:
    normalized = _normalize_arg(value)
    if isinstance(normalized, dict):
        return {k: v for k, v in normalized.items() if v not in ("", None)}
    return normalized


def _get_path(data: Dict[str, Any], path: str) -> Any:
    if not path:
        return ""
    parts = path.split(".")
    cursor: Any = data
    for part in parts:
        if isinstance(cursor, dict) and part in cursor:
            cursor = cursor[part]
        else:
            return ""
    return cursor


def _coerce_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(v).strip() for v in parsed if str(v).strip()]
        except json.JSONDecodeError:
            pass
        if "\n" in raw:
            return [line.strip("- ").strip() for line in raw.splitlines() if line.strip()]
        return [item.strip() for item in raw.split(",") if item.strip()]
    if value is None:
        return []
    return [str(value).strip()]




def _build_router(step: dict) -> Dict[str, Any]:
    route_on = str(step.get("route_on", "")).strip()
    routes = step.get("routes") or {}
    if not route_on or not isinstance(routes, dict):
        raise ValueError("Router node requires 'route_on' and 'routes' mapping")

    def _route(state: PlannerState) -> str:
        inputs = state.get("inputs") or {}
        outputs = state.get("outputs") or {}
        value = _get_path({"inputs": inputs, "outputs": outputs}, route_on)
        value_str = str(value)
        if value_str in routes:
            return str(routes[value_str])
        return str(routes.get("default", ""))

    return {"fn": _route, "routes": routes}


def _parse_mcp_result(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        content = payload.get("content")
        if isinstance(content, list):
            texts = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            joined = "\n".join([t for t in texts if t])
            if joined:
                return joined
        for key in ("output", "result", "raw"):
            if key in payload and isinstance(payload[key], str):
                return payload[key]
        return json.dumps(payload, indent=2)
    return str(payload)


def _parse_sse_json(text: str) -> Dict[str, Any]:
    data_payloads = []
    for line in text.splitlines():
        if line.startswith("data:"):
            data = line[len("data:") :].strip()
            if data:
                data_payloads.append(data)
    if not data_payloads:
        raise ValueError("No JSON data found in SSE response")
    return json.loads(data_payloads[-1])


def _parse_mcp_response(response: requests.Response) -> Dict[str, Any]:
    content_type = response.headers.get("Content-Type", "")
    if "text/event-stream" in content_type:
        return _parse_sse_json(response.text)
    return response.json()


def _extract_session_id(response: requests.Response) -> str:
    for key, value in response.headers.items():
        if key.lower() == "mcp-session-id":
            return value
    try:
        data = response.json()
    except ValueError:
        return ""
    if isinstance(data, dict):
        result = data.get("result") or {}
        if isinstance(result, dict):
            return str(result.get("sessionId") or "")
    return ""


def _initialize_mcp_session(url: str) -> str:
    """
    ✅ Spec-correct initialize: include protocolVersion to avoid downstream issues.
    """
    logger.info("Initializing MCP session: %s", url)
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "clientInfo": {"name": "langgraph-planner", "version": "1.0"},
            "capabilities": {},
        },
    }
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    response = requests.post(url, json=payload, headers=headers, timeout=30)
    if response.status_code >= 400:
        logger.warning("MCP initialize failed %s: %s", response.status_code, response.text)
        return ""
    return _extract_session_id(response)


def _get_mcp_session(url: str) -> str:
    if url in _MCP_SESSIONS:
        return _MCP_SESSIONS[url]
    session_id = _initialize_mcp_session(url)
    if session_id:
        _MCP_SESSIONS[url] = session_id
        logger.info("MCP session established: %s", session_id)
    else:
        logger.warning("MCP session not established for %s", url)
    return session_id


def _refresh_mcp_session(url: str) -> str:
    _MCP_SESSIONS.pop(url, None)
    _TOOL_SCHEMAS.clear()  # schema cache may be session-bound; clear to be safe
    return _get_mcp_session(url)


def _list_mcp_tools(url: str) -> Dict[str, Any]:
    """
    ✅ tools/list to discover inputSchema so we can filter args for strict servers.
    """
    session_id = _get_mcp_session(url)
    payload = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id

    resp = requests.post(url, json=payload, headers=headers, timeout=30)
    if resp.status_code >= 400:
        logger.warning("tools/list failed %s: %s", resp.status_code, resp.text)
        return {}
    data = _parse_mcp_response(resp)
    return data.get("result", {}) if isinstance(data, dict) else {}


def _get_tool_input_schema(url: str, tool_name: str) -> Dict[str, Any]:
    key = (url, tool_name)
    if key in _TOOL_SCHEMAS:
        return _TOOL_SCHEMAS[key]

    result = _list_mcp_tools(url)
    tools = result.get("tools", []) if isinstance(result, dict) else []
    for tool in tools:
        if isinstance(tool, dict) and tool.get("name") == tool_name:
            schema = tool.get("inputSchema") or {}
            if isinstance(schema, dict):
                _TOOL_SCHEMAS[key] = schema
                return schema

    _TOOL_SCHEMAS[key] = {}
    return {}


def _filter_args_to_schema(url: str, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """
    ✅ Drop unknown keys if server validates strict JSON schema.
    """
    schema = _get_tool_input_schema(url, tool_name)
    props = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(props, dict) or not props:
        return args  # best-effort when schema unavailable

    allowed = set(props.keys())
    filtered = {k: v for k, v in args.items() if k in allowed}

    dropped = sorted([k for k in args.keys() if k not in allowed])
    if dropped:
        logger.info("Filtered MCP args for %s (dropped: %s)", tool_name, dropped)

    return filtered


def _call_mcp_tool(url: str, tool_name: str, arguments: Dict[str, Any]) -> str:
    if not url:
        return "MCP server URL is missing."

    # Helpful debug:
    logger.info("MCP tool call: %s -> %s args=%s", url, tool_name, arguments)

    session_id = _get_mcp_session(url)
    payload = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id

    response = requests.post(url, json=payload, headers=headers, timeout=60)

    # If session id invalid, refresh once
    if response.status_code >= 400 and response.status_code == 400 and "session id" in response.text.lower():
        logger.warning("MCP session missing/invalid, retrying with refresh: %s", url)
        session_id = _refresh_mcp_session(url)
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        response = requests.post(url, json=payload, headers=headers, timeout=60)

    if response.status_code >= 400:
        logger.warning("MCP tool call failed %s: %s", response.status_code, response.text)
        return f"MCP error {response.status_code}: {response.text}"

    data = _parse_mcp_response(response)
    if isinstance(data, dict) and "error" in data:
        logger.error("MCP tool error: %s", data["error"])
        return f"MCP tool error: {data['error']}"

    if isinstance(data, dict):
        return _parse_mcp_result(data.get("result", ""))

    return _parse_mcp_result(data)


def _llm_prompt(prompt: str, inputs: Dict[str, Any], outputs: Dict[str, Any]) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return "OPENAI_API_KEY is not set. Provide it to generate LLM output."

    client = OpenAI(
        api_key=api_key,
        base_url=os.getenv("OPENAI_BASE_URL"),
    )
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    context = {
        "inputs": _DotDict(inputs),
        "outputs": _DotDict(outputs),
    }
    rendered_prompt = _render_template(prompt, context)
    content = (
        f"{rendered_prompt}\n\n"
        f"Inputs:\n{json.dumps(inputs, indent=2)}\n\n"
        f"Outputs so far:\n{json.dumps(outputs, indent=2)}\n"
    )
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
    )
    message = response.choices[0].message.content if response.choices else ""
    return message or "No LLM output generated."


class LangGraphPlanner:
    def __init__(
        self,
        config_path: str | os.PathLike | None = None,
        on_node_complete=None,
    ) -> None:
        base_dir = Path(__file__).resolve().parent
        cfg_path = config_path or base_dir / "config" / "graph.yaml"
        cfg = _load_graph_config(cfg_path)
        self.mcp_cfg = cfg.get("mcp") or {}
        self.on_node_complete = on_node_complete
        nodes = cfg.get("nodes") or cfg.get("steps") or []
        if not isinstance(nodes, list) or not nodes:
            raise ValueError("LangGraph config must define a non-empty nodes list")
        self.nodes = nodes
        self.edges = cfg.get("edges") or []
        self.entry_id = cfg.get("entry")
        self.graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(PlannerState)
        previous = None
        node_defs: Dict[str, dict] = {}

        for step in self.nodes:
            if not isinstance(step, dict) or "id" not in step:
                raise ValueError("Each step must be a mapping with an id")
            step_id = str(step["id"])
            node_defs[step_id] = step
            graph.add_node(step_id, self._make_step_fn(step))
            if not self.entry_id and step.get("entry"):
                self.entry_id = step_id
            if not self.edges:
                if previous:
                    graph.add_edge(previous, step_id)
                else:
                    graph.set_entry_point(step_id)
                previous = step_id

        if self.edges:
            if not isinstance(self.edges, list):
                raise ValueError("graph.yaml 'edges' must be a list")
            for edge in self.edges:
                if not isinstance(edge, dict):
                    raise ValueError("Each edge must be a mapping")
                src = str(edge.get("from", "")).strip()
                dst = str(edge.get("to", "")).strip()
                if not src or not dst:
                    raise ValueError("Each edge must define 'from' and 'to'")
                src_def = node_defs.get(src, {})
                if str(src_def.get("type", "")).strip().lower() == "router":
                    continue
                graph.add_edge(src, dst)
        elif previous:
            graph.add_edge(previous, END)

        if self.edges:
            for step_id, step in node_defs.items():
                if str(step.get("type", "")).strip().lower() != "router":
                    continue
                router = _build_router(step)
                routes = router["routes"]
                graph.add_conditional_edges(step_id, router["fn"], routes)

        entry_id = self.entry_id or (self.nodes[0]["id"] if self.nodes else None)
        if entry_id:
            graph.set_entry_point(str(entry_id))
        return graph.compile()

    def _make_step_fn(self, step: dict):
        step_id = str(step["id"])
        step_type = str(step.get("type", "")).strip().lower()
        mcp_servers = self.mcp_cfg.get("servers") or {}
        mcp_transport = str(self.mcp_cfg.get("transport") or "streamable-http").lower()

        def _run(state: PlannerState) -> PlannerState:
            inputs = state.get("inputs") or {}
            outputs = state.setdefault("outputs", {})
            tasks_output = state.setdefault("tasks_output", [])

            logger.info("LangGraph node started: %s (%s)", step_id, step_type)

            result = ""
            if step_type in ("mcp_tool", "mcp"):
                server_name = step.get("server", "")
                tool_name = step.get("tool", "")
                server_cfg = mcp_servers.get(server_name, {}) if server_name else {}
                url = str(server_cfg.get("url", "")).strip()
                transport = str(server_cfg.get("transport", mcp_transport)).lower()
                if transport not in ("streamable-http", "http", "streamable"):
                    result = f"Unsupported MCP transport for LangGraph: {transport}"
                elif not tool_name:
                    result = "Missing tool name for MCP node."
                else:
                    context = {
                        "inputs": _DotDict(inputs),
                        "outputs": _DotDict(outputs),
                    }
                    raw_args = step.get("args") or {}
                    args = _render_template(raw_args, context)

                    # Fill blank args from inputs if key exists
                    if isinstance(args, dict):
                        for key, value in list(args.items()):
                            if value in ("", None) and key in inputs:
                                args[key] = inputs.get(key)

                    args = _sanitize_args(args)

                    # ✅ Filter args to the tool schema (prevents -32602 on strict servers)
                    if isinstance(args, dict):
                        args = _filter_args_to_schema(url, str(tool_name), args)

                    logger.info("FINAL MCP ARGS for %s: %s", tool_name, args)
                    result = _call_mcp_tool(url, str(tool_name), args if isinstance(args, dict) else {})
            elif step_type in ("mcp_tool_map", "mcp_map"):
                server_name = step.get("server", "")
                tool_name = step.get("tool", "")
                server_cfg = mcp_servers.get(server_name, {}) if server_name else {}
                url = str(server_cfg.get("url", "")).strip()
                transport = str(server_cfg.get("transport", mcp_transport)).lower()
                if transport not in ("streamable-http", "http", "streamable"):
                    result = f"Unsupported MCP transport for LangGraph: {transport}"
                elif not tool_name:
                    result = "Missing tool name for MCP map node."
                else:
                    items_path = str(step.get("items_path", "")).strip()
                    items_value = _get_path({"inputs": inputs, "outputs": outputs}, items_path)
                    items = _coerce_list(items_value)
                    max_items = int(step.get("max_items", 5) or 5)
                    items = items[:max_items]
                    if not items:
                        result = "No items to iterate for MCP map node."
                    else:
                        results = []
                        for idx, item in enumerate(items, start=1):
                            context = {
                                "inputs": _DotDict(inputs),
                                "outputs": _DotDict(outputs),
                                "item": item,
                                "item_index": idx,
                            }
                            query_template = step.get("query_template")
                            if query_template:
                                raw_args = {
                                    "query": query_template,
                                    "max_results": step.get("max_results", 5),
                                }
                            else:
                                raw_args = step.get("args") or {}
                            args = _render_template(raw_args, context)
                            if isinstance(args, dict):
                                for key, value in list(args.items()):
                                    if value in ("", None) and key in inputs:
                                        args[key] = inputs.get(key)
                            args = _sanitize_args(args)
                            if isinstance(args, dict):
                                args = _filter_args_to_schema(url, str(tool_name), args)
                            logger.info("FINAL MCP ARGS for %s[%s]: %s", tool_name, idx, args)
                            item_result = _call_mcp_tool(
                                url, str(tool_name), args if isinstance(args, dict) else {}
                            )
                            results.append(f"#{idx} {item}\n{item_result}")
                        result = "\n\n".join(results)

            elif step_type in ("llm", "prompt"):
                prompt = step.get("prompt", "Provide a response.")
                result = _llm_prompt(str(prompt), inputs, outputs)
            elif step_type == "router":
                result = "Router node evaluated."
            else:
                result = f"Unsupported step type: {step_type}"

            outputs[step_id] = result
            tasks_output.append(
                {
                    "name": step_id,
                    "summary": _summarize_output(result),
                    "raw": result,
                }
            )
            if self.on_node_complete:
                try:
                    self.on_node_complete(step_id, result, outputs, tasks_output)
                except Exception:
                    logger.exception("LangGraph on_node_complete failed for %s", step_id)
            logger.info("LangGraph node completed: %s", step_id)
            return state

        return _run

    def run(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        state: PlannerState = {"inputs": inputs, "outputs": {}, "tasks_output": []}
        result_state = self.graph.invoke(state)
        tasks_output = result_state.get("tasks_output", [])
        summary = "LangGraph plan completed."
        return {
            "summary": summary,
            "raw": summary,
            "tasks_output": tasks_output,
            "outputs": result_state.get("outputs", {}),
        }
