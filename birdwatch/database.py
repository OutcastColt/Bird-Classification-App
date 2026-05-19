from __future__ import annotations
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DB_PATH = Path("data/birdwatch.db")


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS cameras (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                stream_url  TEXT NOT NULL,
                enabled     INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS detections (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                camera_id       TEXT NOT NULL REFERENCES cameras(id),
                timestamp       TEXT NOT NULL,
                species_common  TEXT NOT NULL,
                species_sci     TEXT NOT NULL,
                confidence      REAL NOT NULL,
                clip_path       TEXT NOT NULL,
                lat             REAL,
                lon             REAL
            );
            CREATE INDEX IF NOT EXISTS idx_det_camera    ON detections(camera_id);
            CREATE INDEX IF NOT EXISTS idx_det_timestamp ON detections(timestamp);
            CREATE INDEX IF NOT EXISTS idx_det_species   ON detections(species_common);
            CREATE TABLE IF NOT EXISTS alert_rules (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                species_filter  TEXT,
                min_confidence  REAL NOT NULL DEFAULT 0.70,
                method          TEXT NOT NULL,
                config          TEXT NOT NULL,
                cooldown_mins   INTEGER NOT NULL DEFAULT 10,
                enabled         INTEGER NOT NULL DEFAULT 1
            );
        """)


@dataclass
class Detection:
    camera_id: str
    timestamp: str
    species_common: str
    species_sci: str
    confidence: float
    clip_path: str
    lat: Optional[float]
    lon: Optional[float]
    id: Optional[int] = None


@dataclass
class AlertRule:
    method: str
    config: dict
    species_filter: Optional[str] = None
    min_confidence: float = 0.70
    cooldown_mins: int = 10
    enabled: bool = True
    id: Optional[int] = None


def insert_detection(det: Detection, db_path: Path = DB_PATH) -> int:
    with get_connection(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO detections "
            "(camera_id,timestamp,species_common,species_sci,confidence,clip_path,lat,lon) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (det.camera_id, det.timestamp, det.species_common, det.species_sci,
             det.confidence, det.clip_path, det.lat, det.lon),
        )
        return cur.lastrowid


def list_detections(
    db_path: Path = DB_PATH,
    camera_id: Optional[str] = None,
    species: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    q = "SELECT * FROM detections WHERE 1=1"
    params: list = []
    if camera_id:
        q += " AND camera_id=?"; params.append(camera_id)
    if species:
        q += " AND species_common LIKE ?"; params.append(f"%{species}%")
    if date_from:
        q += " AND timestamp>=?"; params.append(date_from)
    if date_to:
        q += " AND timestamp<=?"; params.append(date_to)
    q += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    with get_connection(db_path) as conn:
        return [dict(r) for r in conn.execute(q, params).fetchall()]


def get_detection_summary(db_path: Path = DB_PATH) -> dict:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with get_connection(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) FROM detections").fetchone()[0]
        today_count = conn.execute(
            "SELECT COUNT(*) FROM detections WHERE timestamp>=?", (today,)
        ).fetchone()[0]
        top = conn.execute(
            "SELECT species_common, species_sci, COUNT(*) c FROM detections "
            "GROUP BY species_common ORDER BY c DESC LIMIT 10"
        ).fetchall()
        by_cam = conn.execute(
            "SELECT camera_id, COUNT(*) c FROM detections GROUP BY camera_id"
        ).fetchall()
    return {"total": total, "today": today_count,
            "top_species": [dict(r) for r in top],
            "by_camera": [dict(r) for r in by_cam]}


def upsert_camera(camera_id: str, name: str, stream_url: str,
                  enabled: bool, db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO cameras (id,name,stream_url,enabled) VALUES (?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name,"
            "stream_url=excluded.stream_url,enabled=excluded.enabled",
            (camera_id, name, stream_url, int(enabled)),
        )


def list_cameras(db_path: Path = DB_PATH) -> list[dict]:
    with get_connection(db_path) as conn:
        return [dict(r) for r in
                conn.execute("SELECT * FROM cameras ORDER BY created_at").fetchall()]


def delete_camera(camera_id: str, db_path: Path = DB_PATH) -> bool:
    with get_connection(db_path) as conn:
        return conn.execute(
            "DELETE FROM cameras WHERE id=?", (camera_id,)
        ).rowcount > 0


def insert_alert_rule(rule: AlertRule, db_path: Path = DB_PATH) -> int:
    with get_connection(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO alert_rules "
            "(species_filter,min_confidence,method,config,cooldown_mins,enabled) "
            "VALUES (?,?,?,?,?,?)",
            (rule.species_filter, rule.min_confidence, rule.method,
             json.dumps(rule.config), rule.cooldown_mins, int(rule.enabled)),
        )
        return cur.lastrowid


def list_alert_rules(db_path: Path = DB_PATH) -> list[dict]:
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM alert_rules").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["config"] = json.loads(d["config"])
        result.append(d)
    return result


def update_alert_rule(rule_id: int, updates: dict, db_path: Path = DB_PATH) -> bool:
    allowed = {"species_filter", "min_confidence", "method", "config",
               "cooldown_mins", "enabled"}
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return False
    if "config" in fields:
        fields["config"] = json.dumps(fields["config"])
    set_clause = ", ".join(f"{k}=?" for k in fields)
    with get_connection(db_path) as conn:
        return conn.execute(
            f"UPDATE alert_rules SET {set_clause} WHERE id=?",
            list(fields.values()) + [rule_id],
        ).rowcount > 0


def delete_alert_rule(rule_id: int, db_path: Path = DB_PATH) -> bool:
    with get_connection(db_path) as conn:
        return conn.execute(
            "DELETE FROM alert_rules WHERE id=?", (rule_id,)
        ).rowcount > 0
