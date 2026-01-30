import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from uuid import uuid4
import threading
import contextlib

from agent.crew import AgenticAi
from llm_parser import parse_trip_request


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vacation_planner")

app = FastAPI(title="Vacation Planner API")

# Workaround for CrewAI MCP tools_list UnboundLocalError in some versions.
# try:
#     import crewai.agent.core as _crewai_core

#     _orig_get_native_mcp_tools = _crewai_core.Agent._get_native_mcp_tools
#     _orig_get_mcp_tools = _crewai_core.Agent.get_mcp_tools

#     def _safe_get_native_mcp_tools(self, mcp_config):
#         try:
#             return _orig_get_native_mcp_tools(self, mcp_config)
#         except UnboundLocalError:
#             logger.warning("MCP tools_list bug encountered, returning no tools")
#             return [], None
#         except RuntimeError as exc:
#             message = str(exc).lower()
#             if "tools_list" in message:
#                 logger.warning("MCP tools_list runtime error encountered, returning no tools")
#                 return [], None
#             raise

#     _crewai_core.Agent._get_native_mcp_tools = _safe_get_native_mcp_tools

#     def _safe_get_mcp_tools(self, mcps):
#         try:
#             return _orig_get_mcp_tools(self, mcps)
#         except RuntimeError as exc:
#             message = str(exc).lower()
#             if "tools_list" in message:
#                 logger.warning("MCP tools_list runtime error encountered in get_mcp_tools")
#                 return []
#             raise

#     _crewai_core.Agent.get_mcp_tools = _safe_get_mcp_tools
# except Exception:
#     logger.exception("Failed to apply MCP tools_list workaround")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "*",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PlanRequest(BaseModel):
    destination: str = Field(..., description="Destination or place name.")
    start_date: str = Field(..., description="Trip start date (YYYY-MM-DD).")
    end_date: str = Field(..., description="Trip end date (YYYY-MM-DD).")
    num_days: int = Field(..., description="Number of days for the trip.")
    origin: str = Field("", description="Origin city or airport code.")
    budget: str = Field("mid-range", description="Budget preference.")
    preferences: str = Field("", description="Traveler preferences.")
    interests: str = Field("", description="Places or themes the user prefers.")
    cabin: str = Field("economy", description="Cabin class preference.")


class ParseRequest(BaseModel):
    text: str = Field(..., description="Natural language trip request.")


class ParseResponse(BaseModel):
    parsed: dict
    missing_fields: list[str]


JOBS: dict[str, dict] = {}


class LogCapture:
    def __init__(self, job: dict):
        self.job = job

    def write(self, data: str) -> int:
        if not data:
            return 0
        lines = data.splitlines()
        for line in lines:
            if line.strip():
                self.job["logs"].append(line)
        return len(data)

    def flush(self) -> None:
        return None


@app.post("/plan")
def plan_trip(payload: PlanRequest) -> dict:
    logger.info("Plan request received")
    inputs = payload.model_dump()
    if inputs.get("interests") and not inputs.get("preferences"):
        inputs["preferences"] = inputs["interests"]
    try:
        result = AgenticAi().crew().kickoff(inputs=inputs)
    except Exception as exc:
        logger.exception("Plan execution failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if hasattr(result, "model_dump"):
        return {"result": result.model_dump()}
    if isinstance(result, dict):
        return {"result": result}
    return {"result": str(result)}


def _run_job(job_id: str, inputs: dict) -> None:
    job = JOBS[job_id]
    capture = LogCapture(job)
    try:
        logger.info("Job %s started", job_id)
        with contextlib.redirect_stdout(capture), contextlib.redirect_stderr(capture):
            result = AgenticAi().crew().kickoff(inputs=inputs)
        if hasattr(result, "model_dump"):
            job["result"] = result.model_dump()
        elif isinstance(result, dict):
            job["result"] = result
        else:
            job["result"] = {"raw": str(result)}
    except Exception as exc:
        logger.exception("Job %s failed", job_id)
        job["error"] = str(exc)
    finally:
        logger.info("Job %s completed", job_id)
        job["done"] = True


@app.post("/plan/start")
def start_plan(payload: PlanRequest) -> dict:
    logger.info("Async plan requested")
    inputs = payload.model_dump()
    if inputs.get("interests") and not inputs.get("preferences"):
        inputs["preferences"] = inputs["interests"]
    job_id = str(uuid4())
    JOBS[job_id] = {"logs": [], "done": False, "result": None, "error": None}
    thread = threading.Thread(target=_run_job, args=(job_id, inputs), daemon=True)
    thread.start()
    return {"job_id": job_id}


@app.get("/plan/status/{job_id}")
def plan_status(job_id: str, from_index: int = 0) -> dict:
    job = JOBS.get(job_id)
    if not job:
        logger.warning("Job not found: %s", job_id)
        raise HTTPException(status_code=404, detail="Job not found")
    logger.debug("Job status requested: %s (%s)", job_id, from_index)
    logs = job["logs"][from_index:]
    return {
        "logs": logs,
        "next_index": from_index + len(logs),
        "done": job["done"],
        "result": job["result"],
        "error": job["error"],
    }


@app.post("/parse", response_model=ParseResponse)
def parse_trip(payload: ParseRequest) -> dict:
    logger.info("Parse request received")
    try:
        parsed, missing = parse_trip_request(payload.text)
    except Exception as exc:
        logger.exception("Parse request failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"parsed": parsed, "missing_fields": missing}
