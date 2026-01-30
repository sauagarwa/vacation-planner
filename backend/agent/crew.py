import os
from typing import List

from crewai import Agent, Crew, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.mcp import MCPServerHTTP, MCPServerSSE
from crewai.mcp.filters import create_static_tool_filter
from crewai.project import CrewBase, agent, crew, task


def make_mcp_server(env_var: str, default_base_url: str, allowed_tools: list[str]):
    """
    Prefer Streamable HTTP (recommended) to avoid SSE client crashes in some CrewAI versions.
    Fallback to SSE if MCP_TRANSPORT=sse is set.

    - Default: streamable-http -> expects {base_url}/mcp
    - SSE: expects {base_url}/sse
    """
    transport = os.getenv("MCP_TRANSPORT", "streamable-http").lower().strip()

    if transport in ("streamable-http", "http", "streamable"):
        url = os.getenv(env_var, f"{default_base_url}/mcp")
        return MCPServerHTTP(
            url=url,
            streamable=True,
            tool_filter=create_static_tool_filter(allowed_tool_names=allowed_tools),
            cache_tools_list=False,
        )

    url = os.getenv(env_var, f"{default_base_url}/sse")
    return MCPServerSSE(
        url=url,
        tool_filter=create_static_tool_filter(allowed_tool_names=allowed_tools),
        cache_tools_list=False,
    )


@CrewBase
class AgenticAi:
    """AgenticAi crew"""

    agents: List[BaseAgent]
    tasks: List[Task]

    @agent
    def destination_researcher(self) -> Agent:
        return Agent(
            config=self.agents_config["destination_researcher"],  # type: ignore[index]
            mcps=[
                make_mcp_server(
                    "TRAVEL_RESEARCH_MCP_URL",
                    "http://localhost:7001",
                    ["tavily_travel_search"],
                )
            ],
            verbose=True,
        )

    @agent
    def hotel_researcher(self) -> Agent:
        return Agent(
            config=self.agents_config["hotel_researcher"],  # type: ignore[index]
            mcps=[
                make_mcp_server(
                    "HOTEL_MCP_URL",
                    "http://localhost:7002",
                    ["google_hotels_search"],
                )
            ],
            verbose=True,
        )

    @agent
    def flight_researcher(self) -> Agent:
        return Agent(
            config=self.agents_config["flight_researcher"],  # type: ignore[index]
            mcps=[
                make_mcp_server(
                    "FLIGHT_MCP_URL",
                    "http://localhost:7003",
                    ["google_flights_search"],
                )
            ],
            verbose=True,
        )

    @task
    def destination_research_task(self) -> Task:
        return Task(
            config=self.tasks_config["destination_research_task"],  # type: ignore[index]
        )

    @task
    def itinerary_options_task(self) -> Task:
        return Task(
            config=self.tasks_config["itinerary_options_task"],  # type: ignore[index]
        )

    @task
    def hotel_research_task(self) -> Task:
        return Task(
            config=self.tasks_config["hotel_research_task"],  # type: ignore[index]
        )

    @task
    def flight_research_task(self) -> Task:
        return Task(
            config=self.tasks_config["flight_research_task"],  # type: ignore[index]
            output_file="travel_plan.md",
        )

    @crew
    def crew(self) -> Crew:
        """Creates the AgenticAi crew"""
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )
