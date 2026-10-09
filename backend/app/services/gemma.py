from __future__ import annotations

import json
import re

from app.config import Settings
from app.models.schemas import Place, TripRequest


class GemmaPlanner:
    """Uses the verified Gemini API Gemma 4 model only for constrained choices.

    Tool data remains authoritative: the model can select only supplied IDs and never
    generates opening times, prices, routes, or booking claims.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self.settings.gemini_api_key) and not self.settings.demo_mode

    async def select_places(self, request: TripRequest, candidates: list[Place], limit: int) -> tuple[list[str] | None, str | None]:
        if not self.enabled:
            return None, None
        prompt = {
            "task": "Select attraction IDs that best match the request. Do not infer facts not present. Return only JSON.",
            "request": {"preferences": request.preferences, "optional_stops": request.optional_stops, "requirements": request.requirements, "max_stops": limit},
            "candidates": [{"id": p.id, "name": p.name, "category": p.category, "description": p.description} for p in candidates],
            "schema": {"selected_ids": ["string"], "reason": "brief string"},
        }
        try:
            from google import genai
            client = genai.Client(api_key=self.settings.gemini_api_key)
            response = await client.aio.models.generate_content(model=self.settings.gemma_model, contents=json.dumps(prompt))
            match = re.search(r"\{.*\}", response.text or "", re.S)
            parsed = json.loads(match.group(0) if match else "{}")
            valid_ids = {place.id for place in candidates}
            chosen = [ident for ident in parsed.get("selected_ids", []) if ident in valid_ids][:limit]
            return chosen or None, "Gemma 4 selected stops from tool-returned candidates."
        except Exception:
            return None, "Gemma 4 request failed; deterministic selection kept the plan usable."

