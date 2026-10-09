from __future__ import annotations

import hashlib
import math
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from urllib.parse import quote_plus

import httpx

from app.config import Settings
from app.models.schemas import (
    AccommodationSuggestion,
    BookingSuggestion,
    GeoPoint,
    Place,
    RouteSummary,
    TransitSegment,
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
    travelmode = {
        TransportMode.car: "driving",
        TransportMode.walk: "walking",
        TransportMode.transit: "transit",
        TransportMode.train: "transit",
        TransportMode.bus: "transit",
    }.get(mode)
    mode_part = f"&travelmode={travelmode}" if travelmode else ""
    return (
        "https://www.google.com/maps/dir/?api=1"
        f"&origin={quote_plus(origin)}&destination={quote_plus(destination)}{mode_part}"
    )


def _maps_point_directions_url(origin: GeoPoint, destination: GeoPoint, mode: TransportMode) -> str:
    """Google Maps route page pinned to the geocoded locations, not text guesses."""
    return _maps_directions_url(
        f"{origin.lat:.6f},{origin.lon:.6f}", f"{destination.lat:.6f},{destination.lon:.6f}", mode
    )


def _redbus_route_url(origin: str, destination: str, journey_date: date) -> str:
    def slug(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return (
        f"https://www.redbus.in/bus-tickets/{slug(origin)}-to-{slug(destination)}"
        f"?onward={journey_date.strftime('%d-%b-%Y')}"
    )


def _booking_com_search_url(destination: str, request: TripRequest) -> str:
    checkin = request.departure_date
    checkout = request.return_date or checkin
    if checkout <= checkin:
        checkout = checkin + timedelta(days=1)
    return (
        "https://www.booking.com/searchresults.html?"
        f"ss={quote_plus(destination)}&checkin={checkin.isoformat()}&checkout={checkout.isoformat()}"
        f"&group_adults={request.travelers}&no_rooms=1&group_children=0"
    )


def _google_hotels_url(destination: str, request: TripRequest) -> str:
    return _maps_search_url(
        f"hotels in {destination} check in {request.departure_date.isoformat()} "
        f"for {request.travelers} guests"
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

    async def nearby_places(self, center: GeoPoint, destination: str, interests: Iterable[str] = ()) -> list[Place]:
        if self.settings.demo_mode:
            self.events.append(ToolEvent(tool="places", status="fallback", detail="Generic demo attractions used; details need verification."))
            return _demo_places(center, destination)
        query = f"""[out:json][timeout:12];(
          nwr(around:8000,{center.lat},{center.lon})[tourism~\"attraction|museum|gallery|zoo|viewpoint\"];
          nwr(around:8000,{center.lat},{center.lon})[historic];
          nwr(around:8000,{center.lat},{center.lon})[leisure~\"park|garden\"];
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
            # Overpass can be temporarily rate-limited.  Use Nominatim's
            # indexed OSM search before resorting to generic demo stops, so a
            # traveller still receives actual destination places to visit.
            places = await self._nominatim_places(destination, interests)
            if places:
                self.events.append(ToolEvent(tool="places", status="ok", detail=f"Overpass was unavailable; found {len(places)} destination places through OpenStreetMap Nominatim."))
                return places
            self.events.append(ToolEvent(tool="places", status="fallback", detail="Live places lookup failed; demo attractions used and marked unverified."))
            return _demo_places(center, destination)

    async def _nominatim_places(self, destination: str, interests: Iterable[str]) -> list[Place]:
        """Small live POI fallback for temporary Overpass outages."""
        interest_text = " ".join(interests).casefold()
        if any(token in interest_text for token in ("historical", "history", "museum", "heritage")):
            search_term = "museums"
        elif any(token in interest_text for token in ("nature", "park", "garden", "outdoor")):
            search_term = "parks"
        elif any(token in interest_text for token in ("food", "restaurant", "cafe")):
            search_term = "restaurants"
        elif "shopping" in interest_text:
            search_term = "shopping"
        else:
            search_term = "attractions"
        try:
            async with httpx.AsyncClient(timeout=10, headers={"User-Agent": "TripMateAI/1.0 (hackathon demo)"}) as client:
                response = await client.get(
                    f"{self.settings.nominatim_base_url}/search",
                    params={"q": f"{search_term} in {destination}", "format": "jsonv2", "limit": 12, "addressdetails": 1, "accept-language": "en"},
                )
                response.raise_for_status()
                results = response.json()
            places: list[Place] = []
            seen_names: set[str] = set()
            for item in results:
                name = item.get("name") or item.get("display_name", "").split(",")[0].strip()
                if not name or "lat" not in item or "lon" not in item:
                    continue
                normalized_name = name.casefold().strip()
                if normalized_name in seen_names:
                    continue
                seen_names.add(normalized_name)
                place_type = (item.get("type") or "attraction").casefold()
                category = (
                    "historical" if place_type in {"museum", "gallery", "monument", "memorial"}
                    else "nature" if place_type in {"park", "garden", "zoo"}
                    else "attraction"
                )
                osm_type, osm_id = item.get("osm_type"), item.get("osm_id")
                map_url = f"https://www.openstreetmap.org/{osm_type}/{osm_id}" if osm_type and osm_id else None
                places.append(Place(
                    id=f"nominatim-{osm_type or 'place'}-{osm_id or len(places)}", name=name, category=category,
                    location=GeoPoint(lat=float(item["lat"]), lon=float(item["lon"]), label=name, source="OpenStreetMap Nominatim", verified=True),
                    description=item.get("display_name"), official_url=map_url,
                    source="OpenStreetMap Nominatim", verified=True,
                ))
            return places
        except Exception:
            return []

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

    def hotel_booking_options(self, request: TripRequest, destination: GeoPoint) -> list[AccommodationSuggestion]:
        """Date/traveller-aware hand-offs to hotel booking search pages.

        These links deliberately start a provider search; they do not claim a
        room, rate, or cancellation policy until the traveller sees it on the
        provider's page.
        """
        stay_dates = f"{request.departure_date.isoformat()} to {(request.return_date or request.departure_date).isoformat()}"
        return [
            AccommodationSuggestion(
                id="booking-com-hotels", name="Compare hotel rooms and prices", kind="hotel booking",
                location=destination,
                description=f"Search {request.destination} for {request.travelers} guest(s), dates {stay_dates}. Choose a room and complete payment with Booking.com.",
                booking_url=_booking_com_search_url(request.destination, request), booking_action="search",
                source="Booking.com destination search", verified=True,
            ),
            AccommodationSuggestion(
                id="google-hotels", name="Compare hotels on Google Maps", kind="hotel search",
                location=destination,
                description=f"Compare current hotel options around {request.destination}; verify total price, reviews, and cancellation terms before payment.",
                booking_url=_google_hotels_url(request.destination, request), booking_action="search",
                source="Google Maps hotel search", verified=True,
            ),
        ]

    def ticket_booking_options(self, request: TripRequest, route: RouteSummary, origin: GeoPoint, destination: GeoPoint) -> list[BookingSuggestion]:
        requested_departure = f"{request.departure_date.isoformat()} at {request.preferred_start_time.strftime('%H:%M')}"
        schedule_status = (
            f"{len(route.transit_segments)} live provider timetable segment(s) are shown above."
            if route.transit_segments
            else f"Requested departure: {requested_departure}. Open the provider to see live departures and seats."
        )
        options = [
            BookingSuggestion(
                id="map-distance", title="Verify exact route in Google Maps", provider="Google Maps",
                category="travel_search", url=_maps_point_directions_url(origin, destination, request.transport_mode),
                description=f"Opens Google Maps using the actual geocoded start and destination points for {requested_departure}. Check its current distance, route, traffic, and alternatives.",
                source="Google Maps URL", verified=True,
            )
        ]
        is_india_trip = request.currency == "INR" or "india" in f"{request.origin} {request.destination}".casefold()
        if is_india_trip and request.transport_mode in {TransportMode.train, TransportMode.transit}:
            options.append(BookingSuggestion(
                id="irctc", title="Search Indian Railways tickets", provider="IRCTC",
                category="official_ticket", url="https://www.irctc.co.in/nget/train-search",
                description=f"Journey: {request.origin} to {request.destination}, {requested_departure}, {request.travelers} traveller(s). {schedule_status} Enter station codes to check availability, fare, class, and book securely.",
                source="IRCTC official booking site", verified=True,
            ))
        if is_india_trip and request.transport_mode == TransportMode.bus:
            options.append(BookingSuggestion(
                id="redbus", title="Search bus tickets", provider="redBus",
                category="travel_search", url=_redbus_route_url(request.origin, request.destination, request.departure_date),
                description=f"Journey: {request.origin} to {request.destination}, {requested_departure}, {request.travelers} traveller(s). {schedule_status} Compare boarding points, seats, fares, and book on redBus.",
                source="redBus booking search", verified=True,
            ))
        if request.transport_mode in {TransportMode.bus, TransportMode.transit, TransportMode.train}:
            options.append(BookingSuggestion(
                id="local-operator", title="Find the local transport operator", provider="Google Maps",
                category="local_operator_search", url=_maps_search_url(f"official bus operator {request.origin} to {request.destination}"),
                description=f"Use this search to locate the relevant operator's reservation channel. {schedule_status}",
                source="Google Maps search link", verified=True,
            ))
        return options

    async def route(self, origin: GeoPoint, destination: GeoPoint, request: TripRequest) -> RouteSummary:
        mode = request.transport_mode
        if self.settings.demo_mode:
            km = round(_haversine_km(origin, destination) * 1.22, 1)
            minutes = max(25, round(km / (50 if mode in {TransportMode.car, TransportMode.bus} else 65) * 60))
            self.events.append(ToolEvent(tool="route", status="fallback", detail="Demo route estimate used; verify before travelling."))
            return RouteSummary(distance_km=km, duration_minutes=minutes, geometry=[[origin.lat, origin.lon], [destination.lat, destination.lon]], source="TripMate demo estimate", verified=False)

        live_route = await self._google_maps_route(origin, destination, request)
        if live_route:
            return live_route

        # Never pass a road distance off as a rail timetable.  A bus can use a
        # clearly-labelled road fallback; rail and generic transit stay blank
        # until a schedule provider has supplied actual route data.
        if mode in {TransportMode.train, TransportMode.transit}:
            self.events.append(ToolEvent(
                tool="route", status="skipped",
                detail="No Google Maps Routes API key is configured, so no train/transit distance or timetable was invented.",
            ))
            return RouteSummary(source="Live train/transit route unavailable; open Google Maps for current details", verified=False)

        profile = "foot" if mode == TransportMode.walk else "driving"
        try:
            coordinates = f"{origin.lon},{origin.lat};{destination.lon},{destination.lat}"
            async with httpx.AsyncClient(timeout=12) as client:
                response = await client.get(f"{self.settings.osrm_url}/route/v1/{profile}/{coordinates}", params={"overview": "full", "geometries": "geojson"})
                response.raise_for_status()
                item = response.json()["routes"][0]
            geometry = [[lat, lon] for lon, lat in item["geometry"]["coordinates"]]
            source = "OSRM / OpenStreetMap"
            verified = True
            detail = "Live OSRM road route retrieved."
            if mode == TransportMode.bus:
                source = "OSRM road distance (not a scheduled bus route)"
                verified = False
                detail = "Live road distance retrieved; configure Google Maps Routes API for a bus timetable."
            self.events.append(ToolEvent(tool="route", status="ok", detail=detail))
            return RouteSummary(distance_km=round(item["distance"] / 1000, 1), duration_minutes=round(item["duration"] / 60), geometry=geometry, source=source, verified=verified)
        except Exception:
            km = round(_haversine_km(origin, destination) * 1.22, 1)
            self.events.append(ToolEvent(tool="route", status="fallback", detail="Live routing failed; map line and time are unverified estimates."))
            return RouteSummary(distance_km=km, duration_minutes=round(km / 50 * 60), geometry=[[origin.lat, origin.lon], [destination.lat, destination.lon]], source="TripMate fallback estimate", verified=False)

    async def _google_maps_route(self, origin: GeoPoint, destination: GeoPoint, request: TripRequest) -> RouteSummary | None:
        """Fetch a provider-supplied route and timetable when a project key exists."""
        api_key = (self.settings.google_maps_api_key or "").strip()
        if not api_key:
            return None

        mode = request.transport_mode
        travel_mode = {
            TransportMode.car: "DRIVE", TransportMode.walk: "WALK", TransportMode.bus: "TRANSIT",
            TransportMode.train: "TRANSIT", TransportMode.transit: "TRANSIT",
        }[mode]
        payload: dict[str, Any] = {
            "origin": {"location": {"latLng": {"latitude": origin.lat, "longitude": origin.lon}}},
            "destination": {"location": {"latLng": {"latitude": destination.lat, "longitude": destination.lon}}},
            "travelMode": travel_mode,
            "units": "METRIC",
        }
        departure_time = _requested_departure_timestamp(request)
        if departure_time:
            payload["departureTime"] = departure_time
        if travel_mode == "DRIVE":
            payload["routingPreference"] = "TRAFFIC_AWARE"
        if mode == TransportMode.bus:
            payload["transitPreferences"] = {"allowedTravelModes": ["BUS"]}
        elif mode == TransportMode.train:
            payload["transitPreferences"] = {"allowedTravelModes": ["TRAIN"]}

        field_mask = ",".join([
            "routes.distanceMeters", "routes.duration", "routes.polyline.encodedPolyline", "routes.travelAdvisory.transitFare",
            "routes.legs.steps.travelMode", "routes.legs.steps.staticDuration", "routes.legs.steps.transitDetails.stopCount",
            "routes.legs.steps.transitDetails.headsign", "routes.legs.steps.transitDetails.departureTime",
            "routes.legs.steps.transitDetails.arrivalTime", "routes.legs.steps.transitDetails.departureStop.name",
            "routes.legs.steps.transitDetails.arrivalStop.name", "routes.legs.steps.transitDetails.transitLine.name",
            "routes.legs.steps.transitDetails.transitLine.nameShort", "routes.legs.steps.transitDetails.transitLine.vehicle.type",
        ])
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    self.settings.google_routes_url,
                    headers={"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": field_mask}, json=payload,
                )
                response.raise_for_status()
                routes = response.json().get("routes", [])
            if not routes:
                raise ValueError("No route returned")
            item = routes[0]
            encoded = item.get("polyline", {}).get("encodedPolyline")
            geometry = _decode_google_polyline(encoded) if encoded else []
            segments = _transit_segments_from_google_route(item)
            fare_amount, fare_currency = _google_transit_fare(item)
            route_kind = "timetable" if travel_mode == "TRANSIT" else "route"
            self.events.append(ToolEvent(tool="route", status="ok", detail=f"Google Maps Routes API returned a live {route_kind}."))
            return RouteSummary(
                distance_km=round(float(item.get("distanceMeters", 0)) / 1000, 1) if item.get("distanceMeters") is not None else None,
                duration_minutes=_duration_minutes(item.get("duration")), geometry=geometry,
                transit_segments=segments, fare_amount=fare_amount, fare_currency=fare_currency,
                source="Google Maps Routes API", verified=True,
            )
        except Exception:
            self.events.append(ToolEvent(tool="route", status="failed", detail="Google Maps route lookup failed; a live route or timetable is not being claimed."))
            return None

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


def _requested_departure_timestamp(request: TripRequest) -> str | None:
    """Convert the browser's intended local departure to a Routes API timestamp.

    Google only exposes future transit data for a limited window.  When the
    date is outside that window, omitting this field is more honest than
    silently asking for a different date.
    """
    try:
        timezone = ZoneInfo(request.departure_timezone or "UTC")
    except ZoneInfoNotFoundError:
        timezone = UTC
    local_departure = datetime.combine(request.departure_date, request.preferred_start_time, tzinfo=timezone)
    departure_utc = local_departure.astimezone(UTC)
    now = datetime.now(UTC)
    if now <= departure_utc <= now + timedelta(days=100):
        return departure_utc.isoformat().replace("+00:00", "Z")
    return None


def _duration_minutes(value: str | None) -> int | None:
    if not value or not value.endswith("s"):
        return None
    try:
        return max(1, round(float(value[:-1]) / 60))
    except ValueError:
        return None


def _parse_google_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _transit_segments_from_google_route(route: dict[str, Any]) -> list[TransitSegment]:
    segments: list[TransitSegment] = []
    for leg in route.get("legs", []):
        for step in leg.get("steps", []):
            details = step.get("transitDetails")
            if not details:
                continue
            line = details.get("transitLine") or {}
            vehicle = line.get("vehicle") or {}
            departure_stop = details.get("departureStop") or {}
            arrival_stop = details.get("arrivalStop") or {}
            segments.append(TransitSegment(
                mode=vehicle.get("type") or step.get("travelMode", "TRANSIT"),
                line=line.get("nameShort") or line.get("name"),
                vehicle=vehicle.get("type"), headsign=details.get("headsign"),
                departure_stop=departure_stop.get("name"), arrival_stop=arrival_stop.get("name"),
                departure_time=_parse_google_time(details.get("departureTime")),
                arrival_time=_parse_google_time(details.get("arrivalTime")),
                duration_minutes=_duration_minutes(step.get("staticDuration")),
                stop_count=details.get("stopCount"), source="Google Maps Routes API", verified=True,
            ))
    return segments


def _google_transit_fare(route: dict[str, Any]) -> tuple[float | None, str | None]:
    fare = (route.get("travelAdvisory") or {}).get("transitFare") or {}
    if not fare:
        return None, None
    try:
        amount = float(fare.get("units", 0)) + float(fare.get("nanos", 0)) / 1_000_000_000
    except (TypeError, ValueError):
        return None, None
    return round(amount, 2), fare.get("currencyCode")


def _decode_google_polyline(encoded: str) -> list[list[float]]:
    """Decode a Google encoded polyline into Leaflet's [lat, lon] points."""
    points: list[list[float]] = []
    index = lat = lon = 0
    length = len(encoded)
    try:
        while index < length:
            values: list[int] = []
            for _ in range(2):
                result = shift = 0
                while True:
                    byte = ord(encoded[index]) - 63
                    index += 1
                    result |= (byte & 0x1F) << shift
                    shift += 5
                    if byte < 0x20:
                        break
                values.append(~(result >> 1) if result & 1 else result >> 1)
            lat += values[0]
            lon += values[1]
            points.append([lat / 100000, lon / 100000])
    except (IndexError, ValueError):
        return []
    return points


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

