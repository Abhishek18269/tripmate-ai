from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import UUID

from app.models.schemas import SavedTripSummary, TripPlan


class TripRepository:
    def __init__(self, database_url: str) -> None:
        filename = database_url.removeprefix("sqlite:///")
        self.path = Path(filename)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS trips (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, origin TEXT NOT NULL,
                    destination TEXT NOT NULL, departure_date TEXT NOT NULL,
                    total_cost REAL NOT NULL, currency TEXT NOT NULL,
                    created_at TEXT NOT NULL, payload TEXT NOT NULL
                )"""
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trips_created ON trips(created_at DESC)")

    def save(self, trip: TripPlan) -> TripPlan:
        payload = trip.model_dump_json()
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO trips
                (id,title,origin,destination,departure_date,total_cost,currency,created_at,payload)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (str(trip.id), trip.title, trip.request.origin, trip.request.destination,
                 trip.request.departure_date.isoformat(), trip.total_cost, trip.currency,
                 trip.created_at.isoformat(), payload),
            )
        return trip

    def get(self, trip_id: UUID) -> TripPlan | None:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute("SELECT payload FROM trips WHERE id = ?", (str(trip_id),)).fetchone()
        return TripPlan.model_validate_json(row[0]) if row else None

    def list(self) -> list[SavedTripSummary]:
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                "SELECT id,title,origin,destination,departure_date,total_cost,currency,created_at FROM trips ORDER BY created_at DESC"
            ).fetchall()
        return [SavedTripSummary.model_validate(dict(zip(
            ["id", "title", "origin", "destination", "departure_date", "total_cost", "currency", "created_at"], row
        ))) for row in rows]

    def delete(self, trip_id: UUID) -> bool:
        with sqlite3.connect(self.path) as conn:
            result = conn.execute("DELETE FROM trips WHERE id = ?", (str(trip_id),))
        return result.rowcount > 0

