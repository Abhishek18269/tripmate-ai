from __future__ import annotations

from datetime import UTC, date, datetime, time
from enum import Enum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


class TransportMode(str, Enum):
    car = "car"
    transit = "transit"
    train = "train"
    bus = "bus"
    walk = "walk"


class TripRequest(BaseModel):
    origin: str = Field(min_length=2, max_length=160)
    destination: str = Field(min_length=2, max_length=160)
    departure_date: date
    return_date: date | None = None
    travelers: int = Field(default=1, ge=1, le=20)
    budget: float = Field(gt=0, le=5_000_000)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    preferences: list[str] = Field(default_factory=list, max_length=8)
    transport_mode: TransportMode = TransportMode.car
    max_travel_hours: float | None = Field(default=None, gt=0, le=72)
    preferred_start_time: time = time(8, 0)
    preferred_return_time: time | None = time(21, 0)
    optional_stops: list[str] = Field(default_factory=list, max_length=6)
    requirements: str | None = Field(default=None, max_length=600)
    request_text: str | None = Field(default=None, max_length=1800)

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def dates_are_ordered(self) -> "TripRequest":
        if self.return_date and self.return_date < self.departure_date:
            raise ValueError("Return date cannot be before departure date.")
        return self


class GeoPoint(BaseModel):
    lat: float
    lon: float
    label: str
    source: str
    verified: bool = False


class Place(BaseModel):
    id: str
    name: str
    category: str
    location: GeoPoint
    description: str | None = None
    opening_hours: str | None = None
    admission_note: str | None = None
    official_url: str | None = None
    booking_url: str | None = None
    source: str
    verified: bool = False


class RouteSummary(BaseModel):
    distance_km: float | None = None
    duration_minutes: int | None = None
    geometry: list[list[float]] = Field(default_factory=list)
    source: str
    verified: bool = False


class CostItem(BaseModel):
    label: str
    amount: float
    source: str
    estimated: bool = True


class ItineraryStop(BaseModel):
    order: int
    place: Place
    arrival_time: str
    departure_time: str
    visit_minutes: int
    travel_from_previous_minutes: int = 0
    reason: str
    status: Literal["planned", "alternative", "unavailable"] = "planned"


class ItineraryDay(BaseModel):
    date: date
    title: str
    stops: list[ItineraryStop]
    meal_breaks: list[str] = Field(default_factory=list)
    buffer_minutes: int = 0


class WeatherSummary(BaseModel):
    summary: str
    source: str
    verified: bool = False


class ToolEvent(BaseModel):
    tool: str
    status: Literal["ok", "fallback", "failed", "skipped"]
    detail: str


class TripPlan(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    status: Literal["ready", "needs_details", "limited"] = "ready"
    title: str
    summary: str
    request: TripRequest
    origin: GeoPoint
    destination: GeoPoint
    itinerary: list[ItineraryDay]
    route: RouteSummary
    cost_items: list[CostItem]
    total_cost: float
    currency: str
    warnings: list[str] = Field(default_factory=list)
    weather: WeatherSummary | None = None
    tool_events: list[ToolEvent] = Field(default_factory=list)
    ai_mode: Literal["gemma-4", "deterministic-demo"]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReplanRequest(BaseModel):
    trip: TripPlan
    change_request: str = Field(min_length=3, max_length=1000)
    revised_budget: float | None = Field(default=None, gt=0)
    unavailable_place_ids: list[str] = Field(default_factory=list)


class SavedTripSummary(BaseModel):
    id: UUID
    title: str
    origin: str
    destination: str
    departure_date: date
    total_cost: float
    currency: str
    created_at: datetime


class HealthResponse(BaseModel):
    status: str
    demo_mode: bool
    gemma_available: bool

