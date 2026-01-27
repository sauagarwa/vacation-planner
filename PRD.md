# Vacation Planner PRD

## Overview
Build a vacation planner that lets users describe a trip in natural language, then uses CrewAI agents to research destinations, hotels, and flights. The system outputs itinerary options and asks the user for changes. The frontend is a chatbot (React), and the backend is Python (FastAPI) with CrewAI orchestration.

## Goals
- Allow users to describe trips in natural language (dates, destination, interests, origin).
- Parse user input with an LLM into structured trip details.
- Use multiple CrewAI agents to research attractions, hotels, and flights.
- Present itinerary options and ask for changes.
- Use Google Flights via SerpApi and Google Hotel Prices API for travel research.

## Non-Goals
- Booking or payments.
- User accounts or saved trips.
- Real-time availability guarantees.

## User Stories
- As a user, I can describe my trip in plain language and get a structured plan.
- As a user, I can ask for Brazil (or Yellowstone) with dates and get itinerary options.
- As a user, I can get hotel options for my dates and destination.
- As a user, I can get flight options from my origin airport.
- As a user, I can request changes after seeing options.

## Functional Requirements
### Chatbot UX (Frontend)
- Show a greeting: “Welcome to the vacation planner. I can help you plan your dream vacation.”
- Prompt for a natural language description.
- Accept multi-turn input and resend the full context for parsing.
- If required fields are missing, prompt the user to provide them.
- Display the final plan output.

### LLM Parsing
- Parse user text into:
  - `destination`
  - `start_date` (YYYY-MM-DD)
  - `end_date` (YYYY-MM-DD)
  - `origin` (airport code or city)
  - `interests` (places/themes)
  - `num_days` (if explicitly stated)
- Return missing fields to the frontend for follow-up.

### CrewAI Agents
Create 3 agents:
1. **Destination Researcher**
   - Uses Tavily web search to find attractions, seasonal notes, and logistics.
   - Proposes 2–3 itinerary options and asks for changes.
2. **Hotel Researcher**
   - Uses Google Hotel Prices API to find hotel options for the dates.
3. **Flight Researcher**
   - Uses SerpApi Google Flights API to find flight options for the dates.

### Task Outputs
- Destination research: 10–15 findings with sources.
- Itinerary options: 2–3 plans with daily breakdowns + change request.
- Hotels: 5–8 options with location, price range, amenities.
- Flights: 3–6 options with duration, stops, price range.

## Integration Requirements
- **Tavily** for destination research (`TAVILY_API_KEY`).
- **SerpApi Google Flights API** for flights (`SERPAPI_API_KEY`).
  - Endpoint: `https://serpapi.com/search.json`
  - Engine: `google_flights`
  - Docs: https://serpapi.com/google-flights-api?gad_source=1&gad_campaignid=21503919763&gbraid=0AAAAADD8kqOq8owWCxzoPhGaW477iMpyC&gclid=EAIaIQobChMI0YrL_aSekgMVAUxHAR27xjcAEAAYASAAEgLyl_D_BwE
- **Google Hotel Prices API** for hotels
  - Docs: https://developers.google.com/hotels/hotel-prices
  - Env: `HOTEL_PRICES_API_URL`, `HOTEL_PRICES_API_KEY`

## Technical Architecture
### Backend (Python + FastAPI)
- `POST /parse`: Accepts natural language text, returns parsed fields + missing list.
- `POST /plan`: Accepts structured trip data, runs CrewAI, returns result.
- CrewAI sources live in `backend/agent`.

### Frontend (React)
- Single chatbot interface.
- Sends conversation text to `/parse`.
- If parsing is complete, calls `/plan`.

## Data Model (Parsed Trip)
```json
{
  "destination": "Brazil",
  "start_date": "2026-03-10",
  "end_date": "2026-03-17",
  "origin": "SFO",
  "interests": "beach access, walkable neighborhoods",
  "num_days": 7
}
```

## Milestones
1. Chatbot UX + parsing endpoint.
2. CrewAI agents wired to Tavily + travel tools.
3. Flight + hotel API integrations.
4. End-to-end itinerary generation + change requests.

## Open Questions
- Should origin accept city names only or require IATA codes?
- Should budget, passengers, or cabin class be collected in the chat?
- What output format do you want for itinerary options (Markdown vs JSON)?
