# TripMate AI

TripMate AI is a tool-first travel-planning agent for Hacktoberfest Hack Day. It turns a starting point, destination, budget, interests, travel-time window, and return deadline into a saved itinerary that can be replanned when constraints change.

## What it demonstrates

- A responsive React + Vite + Tailwind interface with Leaflet / OpenStreetMap route visualization.
- FastAPI API with Pydantic validation, documented endpoints at `/docs`, and SQLite persistence.
- Agent workflow: geocode → fetch places → fetch route/weather → constrained stop selection → time/budget checks → structured itinerary.
- Optional hosted **Gemma 4** integration. The verified [Gemini API provider](https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api) uses `google-genai` and `gemma-4-26b-a4b-it` (or `gemma-4-31b-it`). Gemma is strictly constrained to select IDs from tool-returned candidates; it cannot invent routes, prices, opening hours, or booking availability.
- Live worldwide public-data lookups are enabled by default. An honest demo mode is also available; every demo/fallback result is visible in the tool trace and warnings.

```text
React + Leaflet  ──► FastAPI planning agent ──► Gemma 4 (optional, constrained)
                         │       │       │
                      Nominatim Overpass OSRM / Open-Meteo
                         │
                      SQLite saved trips
```

## Run locally on Windows

Prerequisites: Python 3.12+ and Node.js 20+.

```powershell
Copy-Item .env.example .env
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

In another PowerShell window:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. API docs are at `http://localhost:8000/docs`. The frontend proxies `/api` to the backend in development.

## Build and deploy as one service

The Docker image builds the React app and serves it from FastAPI, so it is suitable for a Docker-capable host such as Railway, Render, Fly.io, Azure Container Apps, or a VM.

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Then open `http://localhost:8000`. Do not commit `.env`. To deploy to a cloud provider, set the variables from `.env.example` in that provider's secret manager and expose port `8000`; a provider account/project is required, so TripMate deliberately does not guess or create a cloud deployment target.

## Configuration

`TRIPMATE_DEMO_MODE=false` enables live public data. Set it to `true` for a clearly marked, destination-neutral offline demo. Nominatim, Overpass, OSRM, and Open-Meteo use bounded timeouts and fail back to labelled demo data. Follow each provider's usage policy before production traffic.

### Exact routes and live bus/train schedules

Set `GOOGLE_MAPS_API_KEY` to a Google Cloud key with the **Routes API** enabled to use Google Maps provider route distances, traffic-aware road times, and live public-transit segments (departure/arrival time, stops, line, headsign, and fare when supplied). The app sends the browser's selected local departure time when it is within Google's live transit window. Without the key, car/walking routes use OSRM/OpenStreetMap; rail/transit distances and schedules are intentionally left blank rather than guessed, while Google Maps, IRCTC, and bus-search booking links remain available.

For Railway, add `GOOGLE_MAPS_API_KEY` under the service's Variables, then redeploy. The key is server-only and is never sent to the browser.

To enable Gemma, set `GEMINI_API_KEY` and keep `GEMMA_MODEL=gemma-4-26b-a4b-it`. It uses Google's current `google-genai` request pattern:

```python
from google import genai
client = genai.Client(api_key="...")
response = await client.aio.models.generate_content(
    model="gemma-4-26b-a4b-it", contents=prompt
)
```

The model is optional: failure, timeout, missing key, or invalid output switches safely to deterministic selection and records it in the returned tool trace.

## Tests

```powershell
cd backend
python -m pytest -q
```

Tests use demo mode and do not call paid services. They cover input validation, demo route/budget planning, save/retrieve/delete lifecycle, place search, and replanning.

## API

- `GET /api/health`
- `POST /api/trips/plan`
- `POST /api/trips/replan`
- `GET /api/trips`, `GET /api/trips/{trip_id}`, `DELETE /api/trips/{trip_id}`
- `GET /api/places/search`, `GET /api/places/{place_id}`

## Limitations and attribution

OpenStreetMap/Nominatim, Overpass, OSRM, and Open-Meteo are third-party/public services, not commercial booking systems. Ticket prices and operating hours are shown only if a source supplies them; unknown values are not guessed. The app links to an official website where an available source provides one, and never buys tickets. Public endpoints have respectful short timeouts; production deployments should use dedicated, policy-compliant provider plans and caching.

## Hackathon presentation outline

1. **Problem:** Trip planning requires switching among routes, attractions, time windows, and budgets.
2. **Solution:** A transparent agent that turns constraints into an actionable plan, not a generic chat response.
3. **Architecture:** React map UI → FastAPI agent → modular data tools / optional Gemma 4 → SQLite.
4. **Live demo:** Plan Bengaluru → Mysuru, inspect the data-source trace, then replan for nature or a tighter budget.
5. **Novelty and impact:** Gemma makes constrained decisions from retrieved choices, while deterministic checks keep claims grounded and improve trust.
6. **Next steps:** verified attraction partners, transit providers, authenticated profiles, provider-side caching, and confirmation-based booking.

## License

MIT. See [LICENSE](LICENSE).

