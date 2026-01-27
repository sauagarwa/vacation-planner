from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from uuid import uuid4
import threading
import contextlib

from agent.crew import AgenticAi
from llm_parser import parse_trip_request


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
    inputs = payload.model_dump()
    if inputs.get("interests") and not inputs.get("preferences"):
        inputs["preferences"] = inputs["interests"]
    try:
        result = AgenticAi().crew().kickoff(inputs=inputs)
    except Exception as exc:
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
        with contextlib.redirect_stdout(capture), contextlib.redirect_stderr(capture):
            result = AgenticAi().crew().kickoff(inputs=inputs)
        if hasattr(result, "model_dump"):
            job["result"] = result.model_dump()
        elif isinstance(result, dict):
            job["result"] = result
        else:
            job["result"] = {"raw": str(result)}
    except Exception as exc:
        job["error"] = str(exc)
    finally:
        job["done"] = True


@app.post("/plan/start")
def start_plan(payload: PlanRequest) -> dict:
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
        raise HTTPException(status_code=404, detail="Job not found")
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
    try:
        parsed, missing = parse_trip_request(payload.text)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"parsed": parsed, "missing_fields": missing}
