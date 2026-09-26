from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SAMPLE = Path(__file__).resolve().parents[2] / "monitoring_checks_9d_seed101.csv"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app import config, db

    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    db.get_engine.cache_clear()
    from app.main import app

    yield TestClient(app)
    db.get_engine.cache_clear()


def upload(client, content: bytes, name="data.csv"):
    return client.post("/api/uploads", files={"file": (name, content, "text/csv")})


def test_rejects_non_monitoring_csv(client):
    resp = upload(client, b"a,b\n1,2\n")
    assert resp.status_code == 422
    assert "Missing required column" in resp.json()["detail"]


def test_unknown_upload_404(client):
    assert client.get("/api/uploads/nope/stats").status_code == 404


@pytest.mark.skipif(not SAMPLE.exists(), reason="sample CSV not present")
def test_full_flow_with_sample_file(client):
    resp = upload(client, SAMPLE.read_bytes(), SAMPLE.name)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    upload_id = body["id"]
    assert body["report"]["days"] == 9
    assert body["report"]["services"] == ["svc-auth", "svc-notify", "svc-payments", "svc-reports", "svc-search"]

    assert [u["id"] for u in client.get("/api/uploads").json()] == [upload_id]

    stats = client.get(f"/api/uploads/{upload_id}/stats").json()
    assert stats["overview"]["services"] == 5
    assert any(i["service_id"] == "svc-reports" and i["start"].startswith("2025-05-13T16:00") for i in stats["incidents"])
    assert {m["month"] for m in stats["monthly"]} == {"2025-05"}

    # Single day filter
    day = client.get(f"/api/uploads/{upload_id}/checks", params={"start": "2025-05-13", "end": "2025-05-13"}).json()
    assert day["total"] > 5 * 96  # 5 services x 96 slots + second-agent readings
    assert all(i["ts"].startswith("2025-05-13") for i in day["items"])

    # Range + outcome filter
    down = client.get(
        f"/api/uploads/{upload_id}/checks",
        params={"start": "2025-05-13", "end": "2025-05-14", "outcome": "down", "service_id": "svc-reports"},
    ).json()
    assert down["total"] > 0
    assert {i["outcome"] for i in down["items"]} == {"down"}

    bad = client.get(f"/api/uploads/{upload_id}/checks", params={"start": "2025-05-14", "end": "2025-05-13"})
    assert bad.status_code == 422

    assert client.delete(f"/api/uploads/{upload_id}").status_code == 204
    assert client.get("/api/uploads").json() == []
