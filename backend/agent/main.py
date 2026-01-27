#!/usr/bin/env python
import sys
import warnings

from datetime import datetime

from .crew import AgenticAi

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

# This main file is intended to be a way for you to run your
# crew locally, so refrain from adding unnecessary logic into this file.
# Replace with inputs you want to test with, it will automatically
# interpolate any tasks and agents information

def run():
    """
    Run the crew.
    """
    inputs = {
        "destination": "Brazil",
        "start_date": "2026-03-10",
        "end_date": "2026-03-17",
        "num_days": 7,
        "origin": "SFO",
        "budget": "mid-range",
        "preferences": "beach access, walkable neighborhoods",
        "current_year": str(datetime.now().year),
    }

    try:
        AgenticAi().crew().kickoff(inputs=inputs)
    except Exception as e:
        raise Exception(f"An error occurred while running the crew: {e}")


def train():
    """
    Train the crew for a given number of iterations.
    """
    inputs = {
        "destination": "Yellowstone National Park",
        "start_date": "2026-06-01",
        "end_date": "2026-06-05",
        "num_days": 4,
        "origin": "DEN",
        "budget": "mid-range",
        "preferences": "family-friendly, near park entrance",
        "current_year": str(datetime.now().year),
    }
    try:
        AgenticAi().crew().train(n_iterations=int(sys.argv[1]), filename=sys.argv[2], inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}")

def replay():
    """
    Replay the crew execution from a specific task.
    """
    try:
        AgenticAi().crew().replay(task_id=sys.argv[1])

    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")

def test():
    """
    Test the crew execution and returns the results.
    """
    inputs = {
        "destination": "Brazil",
        "start_date": "2026-03-10",
        "end_date": "2026-03-17",
        "num_days": 7,
        "origin": "SFO",
        "budget": "mid-range",
        "preferences": "beach access, walkable neighborhoods",
        "current_year": str(datetime.now().year),
    }

    try:
        AgenticAi().crew().test(n_iterations=int(sys.argv[1]), eval_llm=sys.argv[2], inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while testing the crew: {e}")

def run_with_trigger():
    """
    Run the crew with trigger payload.
    """
    import json

    if len(sys.argv) < 2:
        raise Exception("No trigger payload provided. Please provide JSON payload as argument.")

    try:
        trigger_payload = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        raise Exception("Invalid JSON payload provided as argument")

    inputs = {
        "crewai_trigger_payload": trigger_payload,
        "destination": "",
        "start_date": "",
        "end_date": "",
        "num_days": "",
        "origin": "",
        "budget": "",
        "preferences": "",
        "current_year": str(datetime.now().year),
    }

    try:
        result = AgenticAi().crew().kickoff(inputs=inputs)
        return result
    except Exception as e:
        raise Exception(f"An error occurred while running the crew with trigger: {e}")
