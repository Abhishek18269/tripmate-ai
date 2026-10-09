from datetime import date

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
    "transport_mode": "car",
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
        assert trip["route"]["distance_km"] is not None
        assert trip["itinerary"][0]["stops"]
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
        assert any(place["name"] == "Mysore Palace" for place in places.json())

