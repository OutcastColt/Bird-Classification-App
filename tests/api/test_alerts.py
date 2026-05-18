import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from birdwatch.database import init_db
from birdwatch.api.alerts import router
import birdwatch.database as dbmod

@pytest.fixture
def app(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    init_db(db)
    monkeypatch.setattr(dbmod, "DB_PATH", db)
    a = FastAPI()
    a.include_router(router)
    return a

def test_alert_rule_crud(app):
    client = TestClient(app)
    r = client.post("/api/alerts/rules", json={
        "method": "webhook",
        "config": {"url": "https://example.com"},
        "min_confidence": 0.80,
        "cooldown_mins": 5,
        "enabled": True,
    })
    assert r.status_code == 201
    rule_id = r.json()["id"]
    rules = client.get("/api/alerts/rules").json()
    assert len(rules) == 1
    assert rules[0]["method"] == "webhook"
    assert isinstance(rules[0]["config"], dict)  # not a JSON string
    r2 = client.put(f"/api/alerts/rules/{rule_id}", json={
        "method": "webhook",
        "config": {"url": "https://example.com"},
        "min_confidence": 0.90,
        "cooldown_mins": 5,
        "enabled": True,
    })
    assert r2.status_code == 200
    r3 = client.delete(f"/api/alerts/rules/{rule_id}")
    assert r3.status_code == 200
    assert client.get("/api/alerts/rules").json() == []

def test_delete_nonexistent_rule(app):
    r = TestClient(app).delete("/api/alerts/rules/9999")
    assert r.status_code == 404

def test_update_nonexistent_rule(app):
    r = TestClient(app).put("/api/alerts/rules/9999", json={
        "method": "webhook",
        "config": {"url": "https://example.com"},
        "min_confidence": 0.70,
        "cooldown_mins": 10,
        "enabled": True,
    })
    assert r.status_code == 404
