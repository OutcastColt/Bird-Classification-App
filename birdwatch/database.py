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
            CREATE TABLE IF NOT EXISTS species_taxonomy (
                species_sci    TEXT PRIMARY KEY,
                genus          TEXT NOT NULL DEFAULT '',
                family         TEXT NOT NULL DEFAULT '',
                taxon_order    TEXT NOT NULL DEFAULT '',
                updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS settings (
                key        TEXT PRIMARY KEY,
                value      TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS rare_species (
                species_common  TEXT PRIMARY KEY,
                min_confidence  REAL NOT NULL DEFAULT 0.75,
                added_at        TEXT NOT NULL DEFAULT (datetime('now'))
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


def get_detection_summary(db_path: Path = DB_PATH,
                          local_date: str | None = None) -> dict:
    # Use the date supplied by the browser (local timezone); fall back to UTC
    today = local_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
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


# ── Rare species watchlist ────────────────────────────────────────────────

def list_rare_species(db_path: Path = DB_PATH) -> list[dict]:
    with get_connection(db_path) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM rare_species ORDER BY species_common"
        ).fetchall()]


def upsert_rare_species(species: str, min_confidence: float,
                        db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO rare_species (species_common, min_confidence) VALUES (?,?) "
            "ON CONFLICT(species_common) DO UPDATE SET min_confidence=excluded.min_confidence",
            (species, min_confidence),
        )


def delete_rare_species(species: str, db_path: Path = DB_PATH) -> bool:
    with get_connection(db_path) as conn:
        return conn.execute(
            "DELETE FROM rare_species WHERE species_common=?", (species,)
        ).rowcount > 0


def get_rare_species_map(db_path: Path = DB_PATH) -> dict[str, float]:
    """Return {species_common: min_confidence} for the full watchlist."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT species_common, min_confidence FROM rare_species"
        ).fetchall()
    return {r["species_common"]: r["min_confidence"] for r in rows}


def get_rare_alerts(hours: int = 24, limit: int = 100,
                    db_path: Path = DB_PATH) -> list[dict]:
    """Recent detections that match the rare-species watchlist."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT d.*, r.min_confidence AS rare_threshold
            FROM detections d
            JOIN rare_species r ON d.species_common = r.species_common
            WHERE d.confidence >= r.min_confidence
              AND d.timestamp >= datetime('now', ? || ' hours')
            ORDER BY d.timestamp DESC
            LIMIT ?
            """,
            (f"-{hours}", limit),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Species taxonomy cache (populated lazily via GBIF) ───────────────────

def get_taxonomy(species_sci: str, db_path: Path = DB_PATH) -> dict | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM species_taxonomy WHERE species_sci=?", (species_sci,)
        ).fetchone()
    return dict(row) if row else None


def upsert_taxonomy(species_sci: str, genus: str, family: str,
                    order: str, db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO species_taxonomy (species_sci,genus,family,taxon_order) "
            "VALUES (?,?,?,?) ON CONFLICT(species_sci) DO UPDATE SET "
            "genus=excluded.genus, family=excluded.family, "
            "taxon_order=excluded.taxon_order, updated_at=datetime('now')",
            (species_sci, genus, family, order),
        )


def get_taxonomy_map(db_path: Path = DB_PATH) -> dict[str, dict]:
    """Return {species_sci: {genus, family, taxon_order}} for all cached species."""
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM species_taxonomy").fetchall()
    return {r["species_sci"]: dict(r) for r in rows}


def get_taxonomy_hierarchy(hours: int = 24, camera_id: str | None = None,
                            min_confidence: float = 0.0,
                            db_path: Path = DB_PATH) -> dict:
    """Return BirdNET detections aggregated as a D3-ready hierarchy JSON.

    Structure: {name:"Birds", children:[{name:order, children:[{family...}]}]}
    """
    from datetime import timedelta
    date_from = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    with get_connection(db_path) as conn:
        q = (
            "SELECT d.species_common, d.species_sci, "
            "COUNT(*) c, AVG(d.confidence) avg_conf, "
            "t.genus, t.family, t.taxon_order "
            "FROM detections d "
            "LEFT JOIN species_taxonomy t ON d.species_sci = t.species_sci "
            "WHERE d.timestamp >= ?"
        )
        params: list = [date_from]
        if min_confidence > 0:
            q += " AND d.confidence >= ?"
            params.append(min_confidence)
        if camera_id:
            q += " AND d.camera_id = ?"
            params.append(camera_id)
        q += " GROUP BY d.species_common ORDER BY c DESC"
        rows = [dict(r) for r in conn.execute(q, params).fetchall()]

    # Build hierarchy dict
    tree: dict = {}  # order -> family -> genus -> [species leaf]
    for r in rows:
        order  = r["taxon_order"] or "Unknown Order"
        family = r["family"]      or "Unknown Family"
        genus  = r["genus"]       or (r["species_sci"].split()[0] if r["species_sci"] else "Unknown")

        tree.setdefault(order, {}).setdefault(family, {}).setdefault(genus, []).append({
            "name":        r["species_common"],
            "species_sci": r["species_sci"] or "",
            "value":       r["c"],
            "avg_conf":    round(r["avg_conf"] or 0, 3),
        })

    # Convert to D3 hierarchy format
    def _genus_node(genus, leaves):
        if len(leaves) == 1:
            return leaves[0]          # flatten single-species genus
        return {"name": genus, "children": leaves}

    root: dict = {"name": "Birds", "children": []}
    for order, families in sorted(tree.items()):
        ord_node: dict = {"name": order, "children": []}
        for family, genera in sorted(families.items()):
            fam_node: dict = {"name": family, "children": [
                _genus_node(genus, leaves)
                for genus, leaves in sorted(genera.items())
            ]}
            ord_node["children"].append(fam_node)
        root["children"].append(ord_node)
    return root


# ── Runtime settings (survives restarts, overrides config.yaml defaults) ──

def get_setting(key: str, db_path: Path = DB_PATH) -> str | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ).fetchone()
    return row["value"] if row else None


def set_setting(key: str, value: str, db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "updated_at=datetime('now')",
            (key, value),
        )


def get_all_settings(db_path: Path = DB_PATH) -> dict[str, str]:
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}
