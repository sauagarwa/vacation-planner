import json
import os
from datetime import datetime
from typing import Any, Dict, Tuple

from openai import OpenAI


def _openai_client() -> OpenAI:
    return OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL"),
    )


def parse_trip_request(text: str) -> Tuple[Dict[str, Any], list[str]]:
    client = _openai_client()
    today = datetime.now().strftime("%Y-%m-%d")
    system_prompt = (
        "You extract structured trip details from user text. "
        "Return only valid JSON. Dates must be YYYY-MM-DD. "
        "If a field is not present, use an empty string. "
        "For cabin, return one of: economy, premium_economy, business, first."
    )
    user_prompt = (
        "Extract the following fields from the trip request:\n"
        "- destination (place or region)\n"
        "- start_date (YYYY-MM-DD)\n"
        "- end_date (YYYY-MM-DD)\n"
        "- origin (airport code or city)\n"
        "- interests (user's places of interest)\n"
        "- num_days (integer if explicitly stated)\n"
        "- cabin (one of economy, premium_economy, business, first)\n\n"
        f"Today is {today}.\n"
        f"User text: {text}"
    )

    response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    content = response.choices[0].message.content or "{}"
    data = json.loads(content)

    result: Dict[str, Any] = {
        "destination": str(data.get("destination", "")).strip(),
        "start_date": str(data.get("start_date", "")).strip(),
        "end_date": str(data.get("end_date", "")).strip(),
        "origin": str(data.get("origin", "")).strip(),
        "interests": str(data.get("interests", "")).strip(),
        "num_days": data.get("num_days"),
        "cabin": str(data.get("cabin", "")).strip(),
    }

    cabin = result.get("cabin", "").lower()
    if cabin in {"preferred economy", "preferred_economy", "premium economy"}:
        cabin = "premium_economy"
    if cabin in {"economy", "premium_economy", "business", "first"}:
        result["cabin"] = cabin
    else:
        result["cabin"] = ""

    missing = [
        key
        for key in ("destination", "start_date", "end_date", "origin", "cabin")
        if not result.get(key)
    ]
    return result, missing
