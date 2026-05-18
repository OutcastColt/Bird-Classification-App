import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import birdwatch.database as dbmod
from birdwatch.database import init_db, insert_detection, Detection, upsert_camera
from birdwatch.api.detections import router


@pytest.fixture
def app(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setattr(dbmod, "DB_PATH", db)
    init_db(db)
    upsert_camera("cam1", "Cam One", "rtsp://x/s", True, db)
    insert_detection(Detection(
        camera_id="cam1", timestamp="2026-05-18T10:00:00",
        species_common="Robin", species_sci="Turdus migratorius",
        confidence=0.85, clip_path="data/clips/cam1/clip.wav",
        lat=38.89, lon=-77.03,
    ), db)
    a = FastAPI()
    a.include_router(router)
    return a


def test_get_detections(app):
    r = TestClient(app).get("/api/detections")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["species_common"] == "Robin"


def test_get_detections_filter_camera(app):
    r = TestClient(app).get("/api/detections?camera_id=cam1")
    assert r.status_code == 200
    assert len(r.json()) == 1
    r2 = TestClient(app).get("/api/detections?camera_id=cam999")
    assert r2.json() == []


def test_get_summary(app):
    r = TestClient(app).get("/api/detections/summary")
    assert r.status_code == 200
    body = r.json()
    assert "total" in body
    assert "today" in body
    assert "top_species" in body


def test_get_detections_filter_date(app):
    # The fixture inserts a detection at 2026-05-18T10:00:00
    # Querying with date_from after that timestamp should return nothing
    r = TestClient(app).get("/api/detections?date_from=2026-05-19T00:00:00")
    assert r.status_code == 200
    assert r.json() == []
    # Querying with date_to before that timestamp should return nothing
    r2 = TestClient(app).get("/api/detections?date_to=2026-05-17T23:59:59")
    assert r2.status_code == 200
    assert r2.json() == []
    # Querying within the date range should return the detection
    r3 = TestClient(app).get("/api/detections?date_from=2026-05-18T00:00:00&date_to=2026-05-18T23:59:59")
    assert r3.status_code == 200
    assert len(r3.json()) == 1
