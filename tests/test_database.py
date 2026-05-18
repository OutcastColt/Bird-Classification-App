import pytest
from birdwatch.database import (
    init_db, insert_detection, list_detections, get_detection_summary,
    upsert_camera, list_cameras, delete_camera,
    insert_alert_rule, list_alert_rules, update_alert_rule, delete_alert_rule,
    Detection, AlertRule,
)

@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    upsert_camera("cam1", "Camera 1", "rtsp://192.168.1.10/s1", True, path)
    return path

def test_init_db_idempotent(db):
    init_db(db)  # second call must not raise

def test_insert_and_list_detection(db):
    det = Detection(
        camera_id="cam1", timestamp="2026-05-18T10:00:00",
        species_common="Robin", species_sci="Turdus migratorius",
        confidence=0.85, clip_path="data/clips/cam1/clip.wav",
        lat=38.89, lon=-77.03,
    )
    det_id = insert_detection(det, db)
    assert isinstance(det_id, int)
    rows = list_detections(db_path=db)
    assert len(rows) == 1
    assert rows[0]["species_common"] == "Robin"

def test_list_detections_filter_camera(db):
    upsert_camera("cam2", "Camera 2", "rtsp://192.168.1.11/s1", True, db)
    for cam in ["cam1", "cam2"]:
        insert_detection(Detection(
            camera_id=cam, timestamp="2026-05-18T10:00:00",
            species_common="Robin", species_sci="Turdus migratorius",
            confidence=0.9, clip_path=f"data/clips/{cam}/clip.wav",
            lat=38.89, lon=-77.03,
        ), db)
    rows = list_detections(db_path=db, camera_id="cam1")
    assert all(r["camera_id"] == "cam1" for r in rows)
    assert len(rows) == 1

def test_detection_summary(db):
    insert_detection(Detection(
        camera_id="cam1", timestamp="2026-05-18T10:00:00",
        species_common="Robin", species_sci="Turdus migratorius",
        confidence=0.9, clip_path="data/clips/cam1/clip.wav",
        lat=38.89, lon=-77.03,
    ), db)
    summary = get_detection_summary(db)
    assert summary["total"] == 1
    assert isinstance(summary["top_species"], list)

def test_camera_crud(db):
    upsert_camera("cam1", "Front Yard", "rtsp://192.168.1.10/s1", True, db)
    cameras = list_cameras(db)
    assert len(cameras) == 1
    assert cameras[0]["name"] == "Front Yard"
    upsert_camera("cam1", "Front Yard Updated", "rtsp://192.168.1.10/s1", True, db)
    assert list_cameras(db)[0]["name"] == "Front Yard Updated"
    assert delete_camera("cam1", db) is True
    assert list_cameras(db) == []

def test_alert_rule_crud(db):
    rule = AlertRule(method="webhook", config={"url": "https://example.com"})
    rule_id = insert_alert_rule(rule, db)
    rules = list_alert_rules(db)
    assert len(rules) == 1
    assert rules[0]["method"] == "webhook"
    assert isinstance(rules[0]["config"], dict)
    assert update_alert_rule(rule_id, {"min_confidence": 0.9}, db) is True
    assert delete_alert_rule(rule_id, db) is True
    assert list_alert_rules(db) == []

def test_delete_nonexistent_camera(db):
    assert delete_camera("ghost", db) is False

def test_delete_nonexistent_alert_rule(db):
    assert delete_alert_rule(9999, db) is False
