from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from app.config import Settings
from app.models.schemas import CostItem, ItineraryDay, ItineraryStop, ReplanRequest, ToolEvent, TripPlan, TripRequest
from app.services import GemmaPlanner, TravelTools, distance_ordered


class TripPlanningAgent:
    """Tool-first agent workflow with Gemma 4 constrained to selection decisions."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def plan(self, request: TripRequest, replan_context: ReplanRequest | None = None) -> TripPlan:
        tools = TravelTools(self.settings)
        origin, destination = await asyncio.gather(tools.geocode(request.origin), tools.geocode(request.destination))
        places_task = tools.nearby_places(destination, request.destination, request.preferences)
        accommodations_task = tools.accommodations(destination, request.destination)
        route_task = tools.route(origin, destination, request)
        weather_task = tools.weather(destination, request.departure_date)
        candidates, accommodations, route, weather = await asyncio.gather(
            places_task, accommodations_task, route_task, weather_task
        )

        if replan_context:
            candidates = [p for p in candidates if p.id not in set(replan_context.unavailable_place_ids)]

        gemma = GemmaPlanner(self.settings)
        candidate_limit = 4 if self._trip_days(request) > 1 else 3
        selected_ids, gemma_detail = await gemma.select_places(request, candidates, candidate_limit)
        if gemma_detail:
            tools.events.append(ToolEvent(tool="gemma-4", status="ok" if selected_ids else "fallback", detail=gemma_detail))

        selected = self._select_candidates(candidates, destination, request, selected_ids, candidate_limit)
        itinerary, scheduling_warnings = self._schedule(request, selected, route.duration_minutes or 0)
        stop_count = sum(len(day.stops) for day in itinerary)
        costs, cost_warnings = self._estimate_costs(request, route, self._trip_days(request))
        total_cost = round(sum(item.amount for item in costs), 2)
        warnings = [
            "Attraction admission and operating hours are omitted unless supplied by a source. Confirm directly before booking.",
            *scheduling_warnings,
            *cost_warnings,
        ]
        if route.duration_minutes and request.max_travel_hours and route.duration_minutes / 60 > request.max_travel_hours:
            warnings.append("The one-way route estimate exceeds the maximum travel time you selected.")
        if replan_context:
            warnings.append(f"Replanned for: {replan_context.change_request}")
            if replan_context.unavailable_place_ids:
                warnings.append("Unavailable stops were removed before the new itinerary was generated.")

        ai_mode = "gemma-4" if selected_ids else ("deterministic-demo" if self.settings.demo_mode else "deterministic-tool-plan")
        if self.settings.demo_mode:
            warnings.insert(0, "Demo mode is on: maps, routes, places, and costs marked as demo are not live travel data.")
        return TripPlan(
            status="limited" if any(event.status in {"failed", "fallback"} for event in tools.events) else "ready",
            title=f"{request.origin} -> {request.destination}",
            summary=self._summary(request, stop_count, total_cost, route.duration_minutes),
            request=request, origin=origin, destination=destination,
            itinerary=itinerary,
            route=route, cost_items=costs, total_cost=total_cost, currency=request.currency,
            ticket_booking_options=tools.ticket_booking_options(request, route),
            accommodation_suggestions=accommodations,
            warnings=warnings, weather=weather, tool_events=tools.events, ai_mode=ai_mode,
        )

    @staticmethod
    def _trip_days(request: TripRequest) -> int:
        return ((request.return_date or request.departure_date) - request.departure_date).days + 1

    @staticmethod
    def _select_candidates(candidates, anchor, request: TripRequest, selected_ids: list[str] | None, limit: int):
        if selected_ids:
            lookup = {place.id: place for place in candidates}
            chosen = [lookup[ident] for ident in selected_ids if ident in lookup]
        else:
            # Public OSM results have no relevance ordering.  Selecting the
            # first matching results could therefore create an itinerary made
            # entirely of nearby cafes even when the traveller asked for
            # heritage or nature.  Select a varied set of sights first, then
            # add one dining stop only when food was requested.
            text = " ".join([*request.preferences, *request.optional_stops, request.requirements or ""]).casefold()
            requested = []
            category_aliases = {
                "historical": "historical", "history": "historical", "museum": "historical",
                "nature": "nature", "outdoor": "nature", "adventure": "attraction",
                "food": "food", "restaurant": "food", "shopping": "shopping",
                "family-friendly": "attraction", "family": "attraction",
            }
            for token, category in category_aliases.items():
                if token in text and category not in requested:
                    requested.append(category)

            # Attractions are worthwhile defaults when the requested category
            # is sparse.  Food is deliberately last and is limited to one.
            priority = [category for category in requested if category != "food"]
            for category in ("historical", "nature", "attraction", "shopping"):
                if category not in priority:
                    priority.append(category)
            if "food" in requested:
                priority.append("food")

            pools = {
                category: distance_ordered(
                    [place for place in candidates if place.category.casefold() == category], anchor
                ) for category in priority
            }
            chosen = []
            # First take one nearby place from each suitable category for a
            # balanced itinerary, then fill unused capacity with more sights.
            for category in priority:
                if pools[category] and len(chosen) < limit:
                    chosen.append(pools[category].pop(0))
            for category in [item for item in priority if item != "food"] + (["food"] if "food" in requested else []):
                while pools[category] and len(chosen) < limit:
                    chosen.append(pools[category].pop(0))
            if not chosen:
                chosen = distance_ordered(candidates, anchor)[:limit]
        return distance_ordered(chosen[:limit], anchor)

    def _schedule(self, request: TripRequest, selected, one_way_minutes: int) -> tuple[list[ItineraryDay], list[str]]:
        total_days = self._trip_days(request)
        selected_by_day = [selected[index::total_days] for index in range(total_days)]
        days: list[ItineraryDay] = []
        warnings: list[str] = []
        for day_index, day_places in enumerate(selected_by_day):
            current_date = request.departure_date + timedelta(days=day_index)
            starts_at = datetime.combine(current_date, request.preferred_start_time)
            current = starts_at + timedelta(minutes=one_way_minutes if day_index == 0 else 0)
            return_at = datetime.combine(current_date, request.preferred_return_time or request.preferred_start_time)
            if return_at <= starts_at:
                return_at += timedelta(days=1)
            day_stops: list[ItineraryStop] = []
            for place in day_places:
                travel_minutes = 15 if day_stops else 0
                arrival = current + timedelta(minutes=travel_minutes)
                departure = arrival + timedelta(minutes=75)
                final_return = one_way_minutes + 30 if day_index == total_days - 1 else 30
                if departure + timedelta(minutes=final_return) > return_at:
                    warnings.append(f"{place.name} was excluded because it would compromise the selected return time.")
                    continue
                day_stops.append(ItineraryStop(
                    order=len(day_stops) + 1, place=place, arrival_time=arrival.strftime("%H:%M"),
                    departure_time=departure.strftime("%H:%M"), visit_minutes=75,
                    travel_from_previous_minutes=travel_minutes,
                    reason="Matches your selected interests and fits the currently estimated schedule.",
                ))
                current = departure
            days.append(ItineraryDay(
                date=current_date, title=f"Day {day_index + 1} · {request.destination}", stops=day_stops,
                meal_breaks=["Allow a 45-minute meal break near your chosen stop."], buffer_minutes=30,
            ))
        if not any(day.stops for day in days):
            warnings.append("There is not enough confirmed planning time for a destination stop; consider an earlier start, later return, or shorter route.")
        return days, warnings

    @staticmethod
    def _estimate_costs(request: TripRequest, route, trip_days: int) -> tuple[list[CostItem], list[str]]:
        """Allocate known planning allowances without ever exceeding the budget.

        Provider fares and hotel prices are not assumed to be available.  The
        values here are therefore budget caps, not a claim that a ticket or
        room costs the displayed amount.  This prevents an impossible plan
        from being presented as affordable.
        """
        distance = route.distance_km or 0
        if request.currency == "INR":
            meal_baseline = request.travelers * max(1, trip_days) * 300
            distance_rate = 5.5 if request.transport_mode.value == "car" else 2.5
        else:
            meal_baseline = request.travelers * max(1, trip_days) * 25
            distance_rate = 0.45 if request.transport_mode.value == "car" else 0.20

        transport_baseline = distance * 2 * distance_rate if distance else request.budget * 0.40
        transport_cap = round(request.budget * 0.55, 2)
        meals_cap = round(request.budget * 0.30, 2)
        transport = round(min(transport_baseline, transport_cap), 2)
        meals = round(min(meal_baseline, meals_cap, request.budget - transport), 2)
        total = transport + meals
        warnings = [
            "Accommodation, attraction tickets, and provider booking fees are not included until a provider returns a price.",
            f"The displayed plan uses {request.currency} {total:,.0f} of your {request.currency} {request.budget:,.0f} budget; the remainder is protected as a booking buffer.",
        ]
        if transport_baseline > transport_cap:
            warnings.append("The route-based transport estimate was capped to keep the plan within budget; check live fares before booking.")
        if meal_baseline > meals:
            warnings.append("Meals were limited to the selected budget; choose lower-cost dining options if needed.")
        costs = [
            CostItem(label="Transport allocation (round trip)", amount=transport, source=f"Budget-capped route allowance · {route.source}", estimated=True),
            CostItem(label="Meals allocation", amount=meals, source="Budget-capped TripMate planning allowance", estimated=True),
        ]
        return costs, warnings

    @staticmethod
    def _summary(request: TripRequest, stops: int, cost: float, minutes: int | None) -> str:
        return f"A tool-informed {stops}-stop itinerary for {request.travelers} traveler(s), with a {minutes or 'not available'} minute route estimate and a {request.currency} {cost:,.0f} budget-capped allowance."

    async def replan(self, change: ReplanRequest) -> TripPlan:
        request = change.trip.request.model_copy(deep=True)
        if change.revised_budget:
            request.budget = change.revised_budget
        message = change.change_request.casefold()
        if "nature" in message and "nature" not in request.preferences:
            request.preferences.append("nature")
        if "history" in message or "historical" in message:
            request.preferences.append("historical")
        return await self.plan(request, replan_context=change)


