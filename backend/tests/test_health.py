"""Tests for the /health endpoint."""


async def test_health_returns_ok(client):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"


async def test_health_reports_degraded_when_db_unreachable(client, monkeypatch):
    """If the database is down, /health should still return 200
    but report degraded status instead of crashing."""

    async def broken_db():
        raise ConnectionRefusedError("cannot connect")

    monkeypatch.setattr("app.api.health.check_db", broken_db)

    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert "cannot connect" in data["database"]
