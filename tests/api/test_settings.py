import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from birdwatch.config import AppConfig, LocationConfig, BirdnetConfig, InferenceConfig
from birdwatch.config import AlertsConfig, LoggingConfig, ServerConfig
from birdwatch.api.settings import router


def make_cfg():
    return AppConfig(
        server=ServerConfig(),
        location=LocationConfig(lat=38.89, lon=-77.03),
        birdnet=BirdnetConfig(),
        inference=InferenceConfig(),
        alerts=AlertsConfig(),
        logging=LoggingConfig(),
    )

@pytest.fixture
def app():
    a = FastAPI()
    a.state.cfg = make_cfg()
    a.include_router(router)
    return a

def test_get_settings(app):
    r = TestClient(app).get("/api/settings")
    assert r.status_code == 200
    data = r.json()
    assert data["lat"] == 38.89
    assert data["lon"] == -77.03
    assert "min_confidence" in data
    assert "use_gpu" in data

def test_update_settings(app):
    client = TestClient(app)
    r = client.put("/api/settings", json={"lat": 51.5, "lon": -0.1})
    assert r.status_code == 200
    settings = client.get("/api/settings").json()
    assert settings["lat"] == 51.5

def test_partial_update_does_not_reset_other_fields(app):
    client = TestClient(app)
    client.put("/api/settings", json={"min_confidence": 0.80})
    r = client.get("/api/settings")
    assert r.json()["lat"] == 38.89   # unchanged
    assert r.json()["min_confidence"] == 0.80
