from __future__ import annotations

import hashlib
import math
from datetime import date
from typing import Iterable

import httpx

from app.config import Settings
from app.models.schemas import GeoPoint, Place, RouteSummary, ToolEvent, TransportMode, WeatherSummary


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
        lat=8 + digest[0] / 255 * 25,
        lon=68 + digest[1] / 255 * 22,
        label=f"{query} (demo pin)",
        source="TripMate demo dataset",
        verified=False,
    )


def _demo_places(center: GeoPoint, destination: str) -> list[Place]:
    is_mysuru = "mys" in destination.casefold()
    entries = (
        [
            ("mysore-palace", "Mysore Palace", "historical", 12.3052, 76.6552, "Landmark", "https://mysorepalace.gov.in/"),
            ("chamundi-hills", "Chamundi Hills", "nature", 12.2725, 76.6707, "Scenic viewpoint", None),
            ("jaganmohan-palace", "Jaganmohan Palace", "historical", 12.3086, 76.6514, "Museum", None),
            ("devaraja-market", "Devaraja Market", "food", 12.3110, 76.6522, "Market and local food", None),
            ("krs-gardens", "Brindavan Gardens", "family", 12.4218, 76.5730, "Garden", None),
        ] if is_mysuru else [
            ("heritage-square", "Heritage Square", "historical", center.lat + .012, center.lon + .009, "Demo heritage stop", None),
            ("green-garden", "Green Garden", "nature", center.lat - .008, center.lon + .011, "Demo outdoor stop", None),
            ("local-market", "Local Market", "food", center.lat + .006, center.lon - .009, "Demo food stop", None),
            ("city-museum", "City Museum", "historical", center.lat - .004, center.lon - .005, "Demo museum", None),
        ]
    )
    return [
        Place(
            id=ident, name=name, category=category,
            location=GeoPoint(lat=lat, lon=lon, label=name, source="TripMate demo dataset", verified=False),
            description=description, official_url=url, source="TripMate demo dataset", verified=False,
        ) for ident, name, category, lat, lon, description, url in entries
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
                response = await client.get(f"{self.settings.nominatim_base_url}/search", params={"q": query, "format": "jsonv2", "limit": 1})
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
            self.events.append(ToolEvent(tool="places", status="fallback", detail="Demo attraction dataset used; details need verification."))
            return _demo_places(center, destination)
        query = f"""[out:json][timeout:12];(nwr(around:8000,{center.lat},{center.lon})[tourism~\"attraction|museum|gallery\"];nwr(around:8000,{center.lat},{center.lon})[historic];nwr(around:8000,{center.lat},{center.lon})[leisure=park];);out center tags 20;"""
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
                category = "historical" if tags.get("historic") or tags.get("tourism") in {"museum", "gallery"} else "nature" if tags.get("leisure") == "park" else "attraction"
                url = tags.get("website") or tags.get("contact:website")
                places.append(Place(
                    id=f"osm-{element['type']}-{element['id']}", name=name, category=category,
                    location=GeoPoint(lat=float(loc["lat"]), lon=float(loc["lon"]), label=name, source="OpenStreetMap / Overpass", verified=True),
                    description=tags.get("description"), opening_hours=tags.get("opening_hours"),
                    admission_note=("OSM tag: fee=" + tags["fee"]) if "fee" in tags else None,
                    official_url=url, booking_url=None, source="OpenStreetMap / Overpass", verified=True,
                ))
            if not places:
                raise ValueError("No usable POIs")
            self.events.append(ToolEvent(tool="places", status="ok", detail=f"Found {len(places)} OpenStreetMap attractions."))
            return places
        except Exception:
            self.events.append(ToolEvent(tool="places", status="fallback", detail="Live places lookup failed; demo attractions used and marked unverified."))
            return _demo_places(center, destination)

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

