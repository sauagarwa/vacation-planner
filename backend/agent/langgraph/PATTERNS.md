# LangGraph Patterns via graph.yaml

## Overview

This guide shows how to express common LangGraph agentic patterns using the
declarative `graph.yaml` used by `backend/agent/langgraph/runner.py`.

### Supported Node Types

- `mcp_tool`: Calls a tool from an MCP server.
- `llm`: Runs a generic LLM prompt. The prompt can reference `{inputs.*}` and `{outputs.*}`.
- `router`: Chooses the next node based on `route_on` + `routes`.

### Common Fields

- `mcp.servers`: Named MCP servers with `url` and optional `transport`.
- `nodes`: List of nodes with `id`, `type`, and type-specific fields.
- `edges`: Optional explicit edges (if omitted, nodes run sequentially).
- `entry`: Optional node id to start the graph.

### 1) Sequential Pipeline

```yaml
name: vacation_pipeline
mcp:
  servers:
    travel_research:
      url: ${TRAVEL_RESEARCH_MCP_URL:http://localhost:7001/mcp}
nodes:
  - id: destination_research_task
    type: mcp_tool
    server: travel_research
    tool: tavily_travel_search
    args:
      query: "Things to do in {inputs.destination}."
      max_results: 5
  - id: itinerary_options_task
    type: llm
    prompt: "Create 2-3 itinerary options."
```

No `edges` means the nodes execute in order.

### 2) Router (Decision Node)

```yaml
nodes:
  - id: classify_trip
    type: llm
    prompt: "Classify the trip style as beach or city."
  - id: choose_branch
    type: router
    route_on: outputs.classify_trip
    routes:
      beach: beach_research
      city: city_research
      default: city_research
  - id: beach_research
    type: mcp_tool
    server: travel_research
    tool: tavily_travel_search
    args:
      query: "Best beaches in {inputs.destination}."
  - id: city_research
    type: mcp_tool
    server: travel_research
    tool: tavily_travel_search
    args:
      query: "Best city attractions in {inputs.destination}."

edges:
  - from: classify_trip
    to: choose_branch
```

The router decides the next node using `route_on`:
`inputs.*` or `outputs.*` paths are supported.

### 3) Fan‑Out / Fan‑In (Parallel Research then Join)

```yaml
nodes:
  - id: start
    type: llm
    prompt: "Starting research."
  - id: food_research
    type: mcp_tool
    server: travel_research
    tool: tavily_travel_search
    args:
      query: "Best food spots in {inputs.destination}."
  - id: culture_research
    type: mcp_tool
    server: travel_research
    tool: tavily_travel_search
    args:
      query: "Cultural highlights in {inputs.destination}."
  - id: join_results
    type: llm
    prompt: "Summarize the research outputs into a single plan."

edges:
  - from: start
    to: food_research
  - from: start
    to: culture_research
  - from: food_research
    to: join_results
  - from: culture_research
    to: join_results
```

Multiple incoming edges to `join_results` act as a join.

### 4) Reflection (Draft then Critique then Improve)

```yaml
nodes:
  - id: draft_itinerary
    type: llm
    prompt: "Draft an itinerary for {inputs.num_days} days."
  - id: critique_itinerary
    type: llm
    prompt: "Critique the itinerary and list improvements."
  - id: improved_itinerary
    type: llm
    prompt: |
      Improve the itinerary using the critique:
      {outputs.critique_itinerary}

edges:
  - from: draft_itinerary
    to: critique_itinerary
  - from: critique_itinerary
    to: improved_itinerary
```

### 5) Map‑Reduce (Map over list, then reduce)

```yaml
nodes:
  - id: map_prompt
    type: llm
    prompt: |
      List 3 neighborhoods in {inputs.destination} as JSON array only.
  - id: map_each
    type: mcp_tool
    server: travel_research
    tool: tavily_travel_search
    args:
      query: "Things to do in {outputs.map_prompt}."
  - id: reduce
    type: llm
    prompt: "Summarize the mapped results into a final plan."

edges:
  - from: map_prompt
    to: map_each
  - from: map_each
    to: reduce
```

This pattern works best if `map_each` is used with a list‑to‑list tool. If you
need true parallel mapping, add multiple `map_each_*` nodes and fan‑out.

### Notes

- All MCP tool calls use streamable‑http JSON‑RPC to `/mcp` URLs.
- Templates in `args` and `llm` prompts can reference `inputs.*` and `outputs.*`.
- For complex branching, add more `router` nodes.
