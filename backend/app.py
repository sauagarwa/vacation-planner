import logging
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from uuid import uuid4
import threading
import contextlib

from agent.crewai.crew import AgenticAi
from agent.langgraph.runner import LangGraphPlanner
from llm_parser import parse_trip_request


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vacation_planner")

app = FastAPI(title="Vacation Planner API")


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
LANGGRAPH_JOBS: dict[str, dict] = {}


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


def _run_langgraph_job(job_id: str, inputs: dict) -> None:
    job = LANGGRAPH_JOBS[job_id]
    capture = LogCapture(job)
    try:
        logger.info("LangGraph job %s started", job_id)
        config_path = os.getenv("LANGGRAPH_CONFIG_PATH")
        with contextlib.redirect_stdout(capture), contextlib.redirect_stderr(capture):
            def _on_node_complete(name, result, outputs, tasks_output):
                job["partial_result"] = {
                    "summary": "LangGraph plan in progress.",
                    "raw": "LangGraph plan in progress.",
                    "tasks_output": list(tasks_output),
                    "outputs": dict(outputs),
                }

            planner = LangGraphPlanner(
                config_path=config_path, on_node_complete=_on_node_complete
            )
            result = planner.run(inputs)
        job["result"] = result
    except Exception as exc:
        logger.exception("LangGraph job %s failed", job_id)
        job["error"] = str(exc)
    finally:
        logger.info("LangGraph job %s completed", job_id)
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


@app.post("/langgraph/plan/start")
def start_langgraph_plan(payload: PlanRequest) -> dict:
    logger.info("Async LangGraph plan requested")
    inputs = payload.model_dump()
    if inputs.get("interests") and not inputs.get("preferences"):
        inputs["preferences"] = inputs["interests"]
    job_id = str(uuid4())
    LANGGRAPH_JOBS[job_id] = {
        "logs": [],
        "done": False,
        "result": None,
        "partial_result": None,
        "error": None,
    }
    thread = threading.Thread(
        target=_run_langgraph_job, args=(job_id, inputs), daemon=True
    )
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


@app.get("/langgraph/plan/status/{job_id}")
def langgraph_plan_status(job_id: str, from_index: int = 0) -> dict:
    job = LANGGRAPH_JOBS.get(job_id)
    if not job:
        logger.warning("LangGraph job not found: %s", job_id)
        raise HTTPException(status_code=404, detail="Job not found")
    logger.debug("LangGraph job status requested: %s (%s)", job_id, from_index)
    logs = job["logs"][from_index:]
    return {
        "logs": logs,
        "next_index": from_index + len(logs),
        "done": job["done"],
        "result": job["result"],
        "partial_result": job.get("partial_result"),
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
