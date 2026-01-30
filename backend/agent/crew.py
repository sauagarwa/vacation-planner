from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List

import yaml
from crewai import Agent, Crew, Process, Task
from crewai.mcp import MCPServerHTTP, MCPServerSSE
from crewai.mcp.filters import create_static_tool_filter


_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::([^}]*))?\}")


def _expand_env(value: Any) -> Any:
    """Recursively expand ${ENV:default} patterns."""
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


def _load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"YAML file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML must be a mapping/object: {path}")
    return _expand_env(data)


def _parse_process(value: str) -> Process:
    v = (value or "").strip().lower()
    if v == "sequential":
        return Process.sequential
    if v == "hierarchical":
        return Process.hierarchical
    raise ValueError(f"Unsupported process '{value}'. Use 'sequential' or 'hierarchical'.")


def _make_mcp_server(url: str, transport: str, allowed_tools: List[str]):
    tool_filter = create_static_tool_filter(allowed_tool_names=allowed_tools)
    transport = (transport or "").strip().lower()

    if transport in ("streamable-http", "http", "streamable"):
        return MCPServerHTTP(
            url=url,
            streamable=True,
            tool_filter=tool_filter,
            cache_tools_list=False,
        )

    if transport == "sse":
        return MCPServerSSE(
            url=url,
            tool_filter=tool_filter,
            cache_tools_list=False,
        )

    raise ValueError(f"Unsupported MCP transport '{transport}'")


class AgenticAi:
    """
    Loads config/crew.yaml (relative to this file),
    then loads config/agents.yaml and config/tasks.yaml (via includes),
    builds CrewAI Agents/Tasks, and returns a Crew.
    """

    def __init__(self, config_path: str | os.PathLike | None = None):
        base_dir = Path(__file__).resolve().parent
        self.config_dir = base_dir / "config"

        self.crew_yaml_path = Path(config_path) if config_path else (self.config_dir / "crew.yaml")
        self.crew_cfg = _load_yaml(self.crew_yaml_path)

        includes = self.crew_cfg.get("includes") or {}
        if not isinstance(includes, dict):
            raise ValueError("config: 'includes' must be a mapping")

        agents_path = self.config_dir / str(includes.get("agents", "agents.yaml"))
        tasks_path = self.config_dir / str(includes.get("tasks", "tasks.yaml"))

        self.agents_cfg = _load_yaml(agents_path)
        self.tasks_cfg = _load_yaml(tasks_path)

        self._agents: Dict[str, Agent] = {}
        self._tasks: List[Task] = []

    def _build_mcp_for_agent(self, agent_name: str):
        mcp_cfg = self.crew_cfg.get("mcp") or {}
        if not isinstance(mcp_cfg, dict):
            return []

        transport = str(mcp_cfg.get("transport") or "streamable-http")
        servers = mcp_cfg.get("servers") or {}
        bindings = mcp_cfg.get("agent_bindings") or {}

        if not isinstance(servers, dict) or not isinstance(bindings, dict):
            return []

        server_names = bindings.get(agent_name) or []
        if not isinstance(server_names, list):
            raise ValueError(f"mcp.agent_bindings.{agent_name} must be a list")

        mcps = []
        for server_name in server_names:
            server = servers.get(server_name)
            if not isinstance(server, dict):
                raise ValueError(f"mcp.servers.{server_name} must be a mapping")

            url = str(server.get("url") or "").strip()
            if not url:
                raise ValueError(f"mcp.servers.{server_name}.url is required")

            allowed_tools = server.get("allowed_tools") or []
            if not isinstance(allowed_tools, list):
                raise ValueError(f"mcp.servers.{server_name}.allowed_tools must be a list")

            mcps.append(_make_mcp_server(url=url, transport=transport, allowed_tools=allowed_tools))

        return mcps

    def _build_agents(self) -> Dict[str, Agent]:
        crew_verbose = bool((self.crew_cfg.get("crew") or {}).get("verbose", True))

        for name, cfg in self.agents_cfg.items():
            if not isinstance(cfg, dict):
                raise ValueError(f"agents.yaml: agent '{name}' must be a mapping")

            role = cfg.get("role", name)
            goal = cfg.get("goal", "")
            backstory = cfg.get("backstory", "")

            # MCP wiring comes from crew.yaml (not agents.yaml)
            mcps = self._build_mcp_for_agent(name)

            self._agents[name] = Agent(
                role=str(role),
                goal=str(goal),
                backstory=str(backstory),
                mcps=mcps,
                verbose=crew_verbose,
            )

        return self._agents

    def _build_tasks(self, agents: Dict[str, Agent]) -> List[Task]:
        tasks: List[Task] = []

        for name, cfg in self.tasks_cfg.items():
            if not isinstance(cfg, dict):
                raise ValueError(f"tasks.yaml: task '{name}' must be a mapping")

            agent_name = cfg.get("agent")
            if not agent_name or agent_name not in agents:
                raise ValueError(
                    f"tasks.yaml: task '{name}' has unknown agent '{agent_name}'. "
                    f"Known agents: {list(agents.keys())}"
                )

            description = str(cfg.get("description", ""))
            expected_output = str(cfg.get("expected_output", ""))

            t = Task(
                description=description,
                expected_output=expected_output,
                agent=agents[agent_name],
            )
            tasks.append(t)

        self._tasks = tasks
        return tasks

    def crew(self) -> Crew:
        crew_block = self.crew_cfg.get("crew") or {}
        if not isinstance(crew_block, dict):
            raise ValueError("crew.yaml: 'crew' must be a mapping")

        process = _parse_process(str(crew_block.get("process", "sequential")))
        verbose = bool(crew_block.get("verbose", True))

        agents = self._build_agents()
        tasks = self._build_tasks(agents)

        return Crew(
            agents=list(agents.values()),
            tasks=tasks,
            process=process,
            verbose=verbose,
        )

