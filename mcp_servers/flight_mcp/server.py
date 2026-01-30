import logging
import os
from typing import Any, Dict

import requests
from mcp.server.fastmcp import FastMCP


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("flight_mcp")

mcp = FastMCP(
    "flight_mcp",
    host=os.getenv("HOST", "0.0.0.0"),
    port=int(os.getenv("PORT", "8000")),
)


@mcp.tool()
def google_flights_search(
    origin: str,
    destination: str,
    depart_date: str,
    return_date: str,
    passengers: int = 1,
    cabin: str = "economy",
) -> str:
    """Find round-trip flight options using SerpApi Google Flights."""
    logger.info("google_flights_search origin=%s destination=%s", origin, destination)
    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        return "SERPAPI_API_KEY is not set. Provide it to enable flight research."
    if not origin or not destination:
        return "Origin and destination are required to search flights."
    if not return_date:
        return "return_date is required for round-trip searches. Provide YYYY-MM-DD."

    cabin_map = {
        "economy": 1,
        "premium_economy": 2,
        "business": 3,
        "first": 4,
    }
    travel_class = cabin_map.get(cabin.lower(), 1)

    params: Dict[str, Any] = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": depart_date,
        "return_date": return_date,
        "type": 1,
        "adults": passengers,
        "travel_class": travel_class,
        "hl": "en",
        "gl": "us",
        "api_key": api_key,
    }
    response = requests.get(
        "https://serpapi.com/search.json",
        params=params,
        timeout=30,
    )
    if response.status_code >= 400:
        return f"SerpApi error {response.status_code}: {response.text}"
    response.raise_for_status()
    data = response.json()
    flights = data.get("best_flights") or data.get("other_flights") or []
    if not flights:
        return "No flights returned from SerpApi."

    formatted = []
    for option in flights[:5]:
        price = option.get("price")
        duration = option.get("total_duration")
        segments = option.get("flights", [])
        if segments:
            first = segments[0]
            airline = first.get("airline", "Unknown airline")
            flight_num = first.get("flight_number", "")
            dep = first.get("departure_airport", {}).get("id", origin)
            arr = first.get("arrival_airport", {}).get("id", destination)
        else:
            airline = "Unknown airline"
            flight_num = ""
            dep = origin
            arr = destination
        formatted.append(
            f"- {airline} {flight_num} {dep}->{arr} | {duration} mins | ${price}"
        )

    return "\n".join(formatted)


if __name__ == "__main__":
    # Prefer streamable-http to avoid SSE-related client issues.
    mcp.run(transport="streamable-http")
