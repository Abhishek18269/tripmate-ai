from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.agent import TripPlanningAgent
from app.config import get_settings
from app.database import TripRepository
from app.models.schemas import HealthResponse, Place, ReplanRequest, SavedTripSummary, TripPlan, TripRequest
from app.services import TravelTools

settings = get_settings()
repository = TripRepository(settings.database_url)


@asynccontextmanager
async def lifespan(_: FastAPI):
    repository.initialize()
    yield


app = FastAPI(title="TripMate AI API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=False, allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", demo_mode=settings.demo_mode, gemma_available=bool(settings.gemini_api_key and not settings.demo_mode))


@app.post("/api/trips/plan", response_model=TripPlan, status_code=201)
async def plan_trip(request: TripRequest) -> TripPlan:
    trip = await TripPlanningAgent(settings).plan(request)
    return repository.save(trip)


@app.post("/api/trips/replan", response_model=TripPlan, status_code=201)
async def replan_trip(request: ReplanRequest) -> TripPlan:
    trip = await TripPlanningAgent(settings).replan(request)
    return repository.save(trip)


@app.get("/api/trips", response_model=list[SavedTripSummary])
async def list_trips() -> list[SavedTripSummary]:
    return repository.list()


@app.get("/api/trips/{trip_id}", response_model=TripPlan)
async def get_trip(trip_id: UUID) -> TripPlan:
    trip = repository.get(trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found.")
    return trip


@app.delete("/api/trips/{trip_id}", status_code=204)
async def delete_trip(trip_id: UUID) -> Response:
    if not repository.delete(trip_id):
        raise HTTPException(status_code=404, detail="Trip not found.")
    return Response(status_code=204)


@app.get("/api/places/search", response_model=list[Place])
async def search_places(query: str = Query(min_length=2, max_length=160)) -> list[Place]:
    tools = TravelTools(settings)
    location = await tools.geocode(query)
    return await tools.nearby_places(location, query)


@app.get("/api/places/{place_id}", response_model=Place)
async def get_place(place_id: str) -> Place:
    tools = TravelTools(settings)
    location = await tools.geocode("Mysuru")
    for place in await tools.nearby_places(location, "Mysuru"):
        if place.id == place_id:
            return place
    raise HTTPException(status_code=404, detail="Place not found in the current data source.")


static_dir = Path(__file__).parent / "static"
asset_dir = static_dir / "assets"
if asset_dir.exists():
    app.mount("/assets", StaticFiles(directory=asset_dir), name="assets")


@app.get("/", include_in_schema=False)
async def web_app():
    index = static_dir / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Frontend has not been built. Run npm run build in frontend.")
    return FileResponse(index)

