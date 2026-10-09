import os

os.environ["TRIPMATE_DEMO_MODE"] = "true"

from fastapi.testclient import TestClient

from app.main import app


PAYLOAD = {
    "origin": "Bengaluru",
    "destination": "Mysuru",
    "departure_date": "2026-11-14",
    "return_date": "2026-11-14",
    "travelers": 2,
    "budget": 3000,
    "currency": "INR",
    "preferences": ["historical"],
    "transport_mode": "train",
    "preferred_start_time": "07:00",
    "preferred_return_time": "21:00",
}


def test_health_and_trip_lifecycle():
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["demo_mode"] is True

        created = client.post("/api/trips/plan", json=PAYLOAD)
        assert created.status_code == 201
        trip = created.json()
        assert trip["total_cost"] > 0
        assert trip["total_cost"] <= PAYLOAD["budget"]
        assert trip["route"]["distance_km"] is not None
        assert trip["route"]["transit_segments"] == []
        assert trip["itinerary"][0]["stops"]
        assert trip["ticket_booking_options"]
        assert trip["accommodation_suggestions"]
        assert any(option["provider"] == "IRCTC" for option in trip["ticket_booking_options"])
        assert "Demo mode is on" in trip["warnings"][0]

        fetched = client.get(f"/api/trips/{trip['id']}")
        assert fetched.status_code == 200

        replanned = client.post("/api/trips/replan", json={"trip": trip, "change_request": "Make this more nature-focused", "revised_budget": 2500})
        assert replanned.status_code == 201
        assert replanned.json()["request"]["budget"] == 2500

        assert client.delete(f"/api/trips/{trip['id']}").status_code == 204


def test_request_validation_and_places():
    with TestClient(app) as client:
        invalid = client.post("/api/trips/plan", json={"origin": "A"})
        assert invalid.status_code == 422
        places = client.get("/api/places/search", params={"query": "Mysuru"})
        assert places.status_code == 200
        assert any("Mysuru" in place["name"] for place in places.json())


def test_demo_fallback_is_not_tied_to_one_city():
    payload = {**PAYLOAD, "origin": "Jaipur", "destination": "Jaipur"}
    with TestClient(app) as client:
        created = client.post("/api/trips/plan", json=payload)
        assert created.status_code == 201
        trip = created.json()
        assert any("Jaipur" in stop["place"]["name"] for stop in trip["itinerary"][0]["stops"])
        assert any("Jaipur" in stay["name"] for stay in trip["accommodation_suggestions"])

