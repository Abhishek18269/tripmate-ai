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
        places_task = tools.nearby_places(destination, request.destination)
        route_task = tools.route(origin, destination, request.transport_mode)
        weather_task = tools.weather(destination, request.departure_date)
        candidates, route, weather = await asyncio.gather(places_task, route_task, weather_task)

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
        costs, cost_warnings = self._estimate_costs(request, route)
        total_cost = round(sum(item.amount for item in costs), 2)
        warnings = [
            "Attraction admission and operating hours are omitted unless supplied by a source. Confirm directly before booking.",
            *scheduling_warnings,
            *cost_warnings,
        ]
        if route.duration_minutes and request.max_travel_hours and route.duration_minutes / 60 > request.max_travel_hours:
            warnings.append("The one-way route estimate exceeds the maximum travel time you selected.")
        if total_cost > request.budget:
            warnings.append("The current estimated plan exceeds your stated budget; use Replan for a lower-cost version.")
        if replan_context:
            warnings.append(f"Replanned for: {replan_context.change_request}")
            if replan_context.unavailable_place_ids:
                warnings.append("Unavailable stops were removed before the new itinerary was generated.")

        ai_mode = "gemma-4" if selected_ids else "deterministic-demo"
        if self.settings.demo_mode:
            warnings.insert(0, "Demo mode is on: maps, routes, places, and costs marked as demo are not live travel data.")
        return TripPlan(
            status="limited" if any(event.status in {"failed", "fallback"} for event in tools.events) else "ready",
            title=f"{request.origin} -> {request.destination}",
            summary=self._summary(request, stop_count, total_cost, route.duration_minutes),
            request=request, origin=origin, destination=destination,
            itinerary=itinerary,
            route=route, cost_items=costs, total_cost=total_cost, currency=request.currency,
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
            interests = " ".join([*request.preferences, *request.optional_stops, request.requirements or ""]).casefold()
            matching = [place for place in candidates if place.category.casefold() in interests or place.name.casefold() in interests]
            chosen = matching + [place for place in candidates if place not in matching]
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
    def _estimate_costs(request: TripRequest, route) -> tuple[list[CostItem], list[str]]:
        # These are transparent planning allowances, never reported as live fares or ticket prices.
        distance = route.distance_km or 0
        if request.currency == "INR":
            transport = round(distance * 2 * (5.5 if request.transport_mode == "car" else 2.5), 2)
            meals = round(request.travelers * 300, 2)
        else:
            transport = round(request.budget * 0.3, 2)
            meals = round(request.budget * 0.18, 2)
        costs = [
            CostItem(label="Transport planning allowance (round trip)", amount=transport, source=route.source, estimated=True),
            CostItem(label="Meals planning allowance", amount=meals, source="TripMate budget heuristic", estimated=True),
        ]
        return costs, ["No admission fees are included because a reliable source did not supply them."]

    @staticmethod
    def _summary(request: TripRequest, stops: int, cost: float, minutes: int | None) -> str:
        return f"A tool-informed {stops}-stop itinerary for {request.travelers} traveler(s), with a {minutes or 'not available'} minute one-way route estimate and {request.currency} {cost:,.0f} planning allowance."

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


