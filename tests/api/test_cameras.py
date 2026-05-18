import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import birdwatch.database as dbmod
from birdwatch.database import init_db
from birdwatch.api.cameras import router


@pytest.fixture
def app(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    init_db(db)
    monkeypatch.setattr(dbmod, "DB_PATH", db)
    a = FastAPI()
    a.include_router(router)
    return a


def test_add_and_list_camera(app):
    client = TestClient(app)
    r = client.post("/api/cameras", json={
        "id": "front-yard", "name": "Front Yard",
        "stream_url": "rtsp://192.168.1.10/s1", "enabled": True,
    })
    assert r.status_code == 201
    cameras = client.get("/api/cameras").json()
    assert len(cameras) == 1
    assert cameras[0]["id"] == "front-yard"
    assert "status" in cameras[0]


def test_update_camera(app):
    client = TestClient(app)
    client.post("/api/cameras", json={
        "id": "cam1", "name": "Old Name", "stream_url": "rtsp://x/s", "enabled": True,
    })
    r = client.put("/api/cameras/cam1", json={
        "id": "cam1", "name": "New Name", "stream_url": "rtsp://x/s", "enabled": True,
    })
    assert r.status_code == 200
    assert client.get("/api/cameras").json()[0]["name"] == "New Name"


def test_delete_camera(app):
    client = TestClient(app)
    client.post("/api/cameras", json={
        "id": "cam1", "name": "X", "stream_url": "rtsp://x", "enabled": True,
    })
    assert client.delete("/api/cameras/cam1").status_code == 200
    assert client.get("/api/cameras").json() == []


def test_delete_nonexistent_camera(app):
    r = TestClient(app).delete("/api/cameras/ghost")
    assert r.status_code == 404
