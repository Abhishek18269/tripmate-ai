from __future__ import annotations

import hashlib
import math
from datetime import date
from typing import Iterable
from urllib.parse import quote_plus

import httpx

from app.config import Settings
from app.models.schemas import (
    AccommodationSuggestion,
    BookingSuggestion,
    GeoPoint,
    Place,
    RouteSummary,
    ToolEvent,
    TransportMode,
    TripRequest,
    WeatherSummary,
)


DEMO_COORDINATES: dict[str, tuple[float, float, str]] = {
    "bengaluru": (12.9716, 77.5946, "Bengaluru, Karnataka"),
    "bangalore": (12.9716, 77.5946, "Bengaluru, Karnataka"),
    "mysuru": (12.2958, 76.6394, "Mysuru, Karnataka"),
    "mysore": (12.2958, 76.6394, "Mysuru, Karnataka"),
    "delhi": (28.6139, 77.2090, "New Delhi, Delhi"),
    "mumbai": (19.0760, 72.8777, "Mumbai, Maharashtra"),
    "chennai": (13.0827, 80.2707, "Chennai, Tamil Nadu"),
}


def _demo_point(query: str) -> GeoPoint:
    lowered = query.casefold()
    for key, (lat, lon, label) in DEMO_COORDINATES.items():
        if key in lowered:
            return GeoPoint(lat=lat, lon=lon, label=label, source="TripMate demo dataset", verified=False)
    digest = hashlib.sha256(query.encode("utf-8")).digest()
    return GeoPoint(
        lat=-55 + digest[0] / 255 * 125,
        lon=-170 + digest[1] / 255 * 340,
        label=f"{query} (demo pin)",
        source="TripMate demo dataset",
        verified=False,
    )


def _demo_places(center: GeoPoint, destination: str) -> list[Place]:
    # These are intentionally destination-neutral examples used only when live
    # geocoding or POI search is unavailable; they never masquerade as real venues.
    entries = [
        ("heritage-walk", f"{destination} heritage walk", "historical", center.lat + .012, center.lon + .009, "Demo heritage-planning stop", None),
        ("city-park", f"{destination} city park", "nature", center.lat - .008, center.lon + .011, "Demo outdoor-planning stop", None),
        ("local-food", f"{destination} local food area", "food", center.lat + .006, center.lon - .009, "Demo local-food planning stop", None),
        ("city-museum", f"{destination} museum district", "historical", center.lat - .004, center.lon - .005, "Demo museum-planning stop", None),
    ]
    return [
        Place(
            id=ident, name=name, category=category,
            location=GeoPoint(lat=lat, lon=lon, label=name, source="TripMate demo dataset", verified=False),
            description=description, official_url=url, source="TripMate demo dataset", verified=False,
        ) for ident, name, category, lat, lon, description, url in entries
    ]


def _safe_http_url(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if value.startswith(("https://", "http://")):
        return value
    if "://" in value:
        return None
    return f"https://{value}"


def _maps_search_url(query: str) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(query)}"


def _maps_directions_url(origin: str, destination: str, mode: TransportMode) -> str:
    travelmode = {TransportMode.car: "driving", TransportMode.walk: "walking", TransportMode.transit: "transit"}.get(mode)
    mode_part = f"&travelmode={travelmode}" if travelmode else ""
    return (
        "https://www.google.com/maps/dir/?api=1"
        f"&origin={quote_plus(origin)}&destination={quote_plus(destination)}{mode_part}"
    )


def _demo_accommodations(center: GeoPoint, destination: str) -> list[AccommodationSuggestion]:
    return [
        AccommodationSuggestion(
            id="stay-search-hotels", name=f"Hotels in {destination}", kind="hotel search",
            location=center,
            description="Compare current prices, accessibility details, cancellation terms, and guest reviews before reserving.",
            booking_url=_maps_search_url(f"hotels in {destination}"), booking_action="search",
            source="Google Maps search link", verified=False,
        ),
        AccommodationSuggestion(
            id="stay-search-hostels", name=f"Hostels and guest houses in {destination}", kind="budget stay search",
            location=center,
            description="Search local hostels and guest houses; contact the property or a trusted provider to confirm availability.",
            booking_url=_maps_search_url(f"hostels and guest houses in {destination}"), booking_action="search",
            source="Google Maps search link", verified=False,
        ),
    ]


class TravelTools:
    """Small, failure-tolerant adapters around public travel data providers."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.events: list[ToolEvent] = []

    async def geocode(self, query: str) -> GeoPoint:
        if self.settings.demo_mode:
            point = _demo_point(query)
            self.events.append(ToolEvent(tool="geocode", status="fallback", detail=f"Demo coordinate used for {query}."))
            return point
        try:
            async with httpx.AsyncClient(timeout=8, headers={"User-Agent": "TripMateAI/1.0 (hackathon demo)"}) as client:
                params = {"q": query, "format": "jsonv2", "limit": 5, "addressdetails": 1, "accept-language": "en"}
                # Prefer a settlement when the input names a city or region. A
                # normal text search can otherwise rank a nearby facility that
                # merely contains the same word above the actual destination.
                city_response = await client.get(
                    f"{self.settings.nominatim_base_url}/search",
                    params={**params, "featureType": "city"},
                )
                city_response.raise_for_status()
                data = city_response.json()
                if not data:
                    response = await client.get(f"{self.settings.nominatim_base_url}/search", params=params)
                    response.raise_for_status()
                    data = response.json()
            if not data:
                raise ValueError("No result")
            item = data[0]
            self.events.append(ToolEvent(tool="geocode", status="ok", detail=f"OpenStreetMap geocoded {query}."))
            return GeoPoint(lat=float(item["lat"]), lon=float(item["lon"]), label=item["display_name"], source="OpenStreetMap Nominatim", verified=True)
        except Exception:
            self.events.append(ToolEvent(tool="geocode", status="fallback", detail=f"Live geocoding failed for {query}; a clearly marked demo coordinate was used."))
            return _demo_point(query)

    async def nearby_places(self, center: GeoPoint, destination: str) -> list[Place]:
        if self.settings.demo_mode:
            self.events.append(ToolEvent(tool="places", status="fallback", detail="Generic demo attractions used; details need verification."))
            return _demo_places(center, destination)
        query = f"""[out:json][timeout:12];(
          nwr(around:8000,{center.lat},{center.lon})[tourism~\"attraction|museum|gallery|zoo|viewpoint\"];
          nwr(around:8000,{center.lat},{center.lon})[historic];
          nwr(around:8000,{center.lat},{center.lon})[leisure~\"park|garden\"];
          nwr(around:8000,{center.lat},{center.lon})[amenity~\"restaurant|cafe|marketplace\"];
          nwr(around:8000,{center.lat},{center.lon})[shop~\"mall|department_store\"];
        );out center tags 40;"""
        try:
            async with httpx.AsyncClient(timeout=18, headers={"User-Agent": "TripMateAI/1.0 (hackathon demo)"}) as client:
                response = await client.post(self.settings.overpass_url, data={"data": query})
                response.raise_for_status()
                elements = response.json().get("elements", [])
            places: list[Place] = []
            for element in elements:
                tags = element.get("tags", {})
                name = tags.get("name")
                loc = element.get("center", element)
                if not name or "lat" not in loc or "lon" not in loc:
                    continue
                category = (
                    "historical" if tags.get("historic") or tags.get("tourism") in {"museum", "gallery"}
                    else "nature" if tags.get("leisure") in {"park", "garden"}
                    else "food" if tags.get("amenity") in {"restaurant", "cafe", "marketplace"}
                    else "shopping" if tags.get("shop")
                    else "attraction"
                )
                url = _safe_http_url(tags.get("website") or tags.get("contact:website"))
                booking_url = _safe_http_url(tags.get("booking:website") or tags.get("reservation:website"))
                places.append(Place(
                    id=f"osm-{element['type']}-{element['id']}", name=name, category=category,
                    location=GeoPoint(lat=float(loc["lat"]), lon=float(loc["lon"]), label=name, source="OpenStreetMap / Overpass", verified=True),
                    description=tags.get("description"), opening_hours=tags.get("opening_hours"),
                    admission_note=("OSM tag: fee=" + tags["fee"]) if "fee" in tags else None,
                    official_url=url, booking_url=booking_url, source="OpenStreetMap / Overpass", verified=True,
                ))
            if not places:
                raise ValueError("No usable POIs")
            self.events.append(ToolEvent(tool="places", status="ok", detail=f"Found {len(places)} OpenStreetMap attractions."))
            return places
        except Exception:
            self.events.append(ToolEvent(tool="places", status="fallback", detail="Live places lookup failed; demo attractions used and marked unverified."))
            return _demo_places(center, destination)

    async def accommodations(self, center: GeoPoint, destination: str) -> list[AccommodationSuggestion]:
        if self.settings.demo_mode:
            self.events.append(ToolEvent(tool="accommodation", status="fallback", detail="Demo stay-search links supplied; availability is not live."))
            return _demo_accommodations(center, destination)
        query = f"""[out:json][timeout:12];
        nwr(around:10000,{center.lat},{center.lon})[tourism~\"hotel|guest_house|hostel|motel|apartment\"];
        out center tags 12;"""
        try:
            async with httpx.AsyncClient(timeout=18, headers={"User-Agent": "TripMateAI/1.0 (hackathon demo)"}) as client:
                response = await client.post(self.settings.overpass_url, data={"data": query})
                response.raise_for_status()
                elements = response.json().get("elements", [])
            stays: list[AccommodationSuggestion] = []
            for element in elements:
                tags = element.get("tags", {})
                name = tags.get("name")
                loc = element.get("center", element)
                if not name or "lat" not in loc or "lon" not in loc:
                    continue
                official_url = _safe_http_url(tags.get("website") or tags.get("contact:website"))
                reservation_url = _safe_http_url(tags.get("booking:website") or tags.get("reservation:website"))
                stays.append(AccommodationSuggestion(
                    id=f"osm-stay-{element['type']}-{element['id']}", name=name,
                    kind=tags.get("tourism", "accommodation").replace("_", " "),
                    location=GeoPoint(lat=float(loc["lat"]), lon=float(loc["lon"]), label=name, source="OpenStreetMap / Overpass", verified=True),
                    description="Check the property directly for current rooms, price, accessibility, and cancellation terms.",
                    official_url=official_url,
                    booking_url=reservation_url or _maps_search_url(f"{name} {destination}"),
                    booking_action="official_site" if reservation_url else "search",
                    source="OpenStreetMap / Overpass", verified=True,
                ))
            if not stays:
                raise ValueError("No usable accommodation POIs")
            self.events.append(ToolEvent(tool="accommodation", status="ok", detail=f"Found {len(stays)} accommodation options from OpenStreetMap."))
            return stays
        except Exception:
            self.events.append(ToolEvent(tool="accommodation", status="fallback", detail="Live accommodation lookup failed; generic search links supplied instead."))
            return _demo_accommodations(center, destination)

    def ticket_booking_options(self, request: TripRequest) -> list[BookingSuggestion]:
        options = [
            BookingSuggestion(
                id="route-directions", title="Open route and local transport options", provider="Google Maps",
                category="travel_search", url=_maps_directions_url(request.origin, request.destination, request.transport_mode),
                description="Review current route options before choosing a transport provider. This does not check or purchase a ticket.",
                source="Google Maps URL", verified=True,
            )
        ]
        is_india_trip = request.currency == "INR" or "india" in f"{request.origin} {request.destination}".casefold()
        if is_india_trip and request.transport_mode in {TransportMode.train, TransportMode.transit}:
            options.append(BookingSuggestion(
                id="irctc", title="Search Indian Railways tickets", provider="IRCTC",
                category="official_ticket", url="https://www.irctc.co.in/nget/train-search",
                description="Official Indian Railways reservation search. Confirm train availability, fare, and booking conditions on IRCTC before payment.",
                source="IRCTC official booking site", verified=True,
            ))
        if request.transport_mode in {TransportMode.bus, TransportMode.transit, TransportMode.train}:
            options.append(BookingSuggestion(
                id="local-operator", title="Find the local transport operator", provider="Google Maps",
                category="local_operator_search", url=_maps_search_url(f"official bus operator {request.origin} to {request.destination}"),
                description="Use this search to locate the relevant operator's official reservation channel; schedules and tickets are not available in TripMate.",
                source="Google Maps search link", verified=True,
            ))
        return options

    async def route(self, origin: GeoPoint, destination: GeoPoint, mode: TransportMode) -> RouteSummary:
        if self.settings.demo_mode:
            km = round(_haversine_km(origin, destination) * 1.22, 1)
            minutes = max(25, round(km / (50 if mode in {TransportMode.car, TransportMode.bus} else 65) * 60))
            self.events.append(ToolEvent(tool="route", status="fallback", detail="Demo route estimate used; verify before travelling."))
            return RouteSummary(distance_km=km, duration_minutes=minutes, geometry=[[origin.lat, origin.lon], [destination.lat, destination.lon]], source="TripMate demo estimate", verified=False)
        if mode not in {TransportMode.car, TransportMode.walk}:
            self.events.append(ToolEvent(tool="route", status="skipped", detail="Public OSRM adapter only supports driving/walking; no live transit schedule was claimed."))
            return RouteSummary(source="Unavailable for selected mode", verified=False)
        profile = "foot" if mode == TransportMode.walk else "driving"
        try:
            coordinates = f"{origin.lon},{origin.lat};{destination.lon},{destination.lat}"
            async with httpx.AsyncClient(timeout=12) as client:
                response = await client.get(f"{self.settings.osrm_url}/route/v1/{profile}/{coordinates}", params={"overview": "full", "geometries": "geojson"})
                response.raise_for_status()
                item = response.json()["routes"][0]
            geometry = [[lat, lon] for lon, lat in item["geometry"]["coordinates"]]
            self.events.append(ToolEvent(tool="route", status="ok", detail="Live OSRM route retrieved."))
            return RouteSummary(distance_km=round(item["distance"] / 1000, 1), duration_minutes=round(item["duration"] / 60), geometry=geometry, source="OSRM / OpenStreetMap", verified=True)
        except Exception:
            km = round(_haversine_km(origin, destination) * 1.22, 1)
            self.events.append(ToolEvent(tool="route", status="fallback", detail="Live routing failed; map line and time are unverified estimates."))
            return RouteSummary(distance_km=km, duration_minutes=round(km / 50 * 60), geometry=[[origin.lat, origin.lon], [destination.lat, destination.lon]], source="TripMate fallback estimate", verified=False)

    async def weather(self, point: GeoPoint, trip_date: date) -> WeatherSummary | None:
        if self.settings.demo_mode:
            self.events.append(ToolEvent(tool="weather", status="skipped", detail="Weather is unavailable in demo mode."))
            return None
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.get(self.settings.open_meteo_url, params={"latitude": point.lat, "longitude": point.lon, "daily": "weather_code,temperature_2m_max", "timezone": "auto", "start_date": trip_date.isoformat(), "end_date": trip_date.isoformat()})
                response.raise_for_status()
                daily = response.json()["daily"]
            temp = daily["temperature_2m_max"][0]
            code = daily["weather_code"][0]
            self.events.append(ToolEvent(tool="weather", status="ok", detail="Open-Meteo forecast retrieved."))
            return WeatherSummary(summary=f"Forecast code {code}; maximum {temp}°C. Check local alerts before departure.", source="Open-Meteo", verified=True)
        except Exception:
            self.events.append(ToolEvent(tool="weather", status="failed", detail="Weather lookup failed; no forecast is being shown."))
            return None


def _haversine_km(a: GeoPoint, b: GeoPoint) -> float:
    radius = 6371
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat, dlon = lat2 - lat1, math.radians(b.lon - a.lon)
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return radius * 2 * math.asin(math.sqrt(value))


def distance_ordered(places: Iterable[Place], start: GeoPoint) -> list[Place]:
    remaining = list(places)
    ordered: list[Place] = []
    current = start
    while remaining:
        next_place = min(remaining, key=lambda item: _haversine_km(current, item.location))
        ordered.append(next_place)
        remaining.remove(next_place)
        current = next_place.location
    return ordered

