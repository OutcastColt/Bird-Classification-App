# BirdWatch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a 24/7 bird audio detection system that ingests RTSP/RTSPS camera streams, runs BirdNET-Analyzer locally, stores detections with audio clips, and serves a local web dashboard with live detection, history, audio playback, and full configuration management.

**Architecture:** FastAPI main process handles web API, WebSocket live push, SQLite writes, and alert dispatch. Camera worker subprocesses (one per stream) use FFmpeg to pull audio from RTSP/RTSPS streams and push 3-second PCM chunks to a shared inference queue. Inference worker subprocesses (configurable pool) run BirdNET-Analyzer against each chunk and push detection results back via a result queue.

**Tech Stack:** Python 3.11, FastAPI, uvicorn, birdnetlib (BirdNET-Analyzer wrapper), SQLite (WAL mode), FFmpeg, multiprocessing.Queue (IPC), HTMX + Alpine.js (dashboard frontend), systemd (service management), Ubuntu Server.

---

## File Structure

Files created or modified by this plan:

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app, lifespan, WebSocket endpoint, result_queue consumer loop |
| `config/config.example.yaml` | Committed example config — user copies to `config/config.yaml` |
| `birdwatch/config.py` | Pydantic models for all config sections + `load_config()` |
| `birdwatch/database.py` | SQLite schema init (WAL), CRUD for cameras / detections / alert_rules |
| `birdwatch/camera_worker.py` | FFmpeg subprocess, RTSP+RTSPS support, PCM chunking, backpressure, reconnect |
| `birdwatch/inference_worker.py` | birdnetlib Analyzer, PCM-to-WAV, analyze, save clip, push to result_queue |
| `birdwatch/alert_manager.py` | Rule matching, cooldown, email/webhook/pushover dispatch |
| `birdwatch/process_manager.py` | Supervises worker processes, heartbeat loop, auto-restart |
| `birdwatch/api/detections.py` | GET /api/detections + GET /api/detections/summary |
| `birdwatch/api/cameras.py` | CRUD /api/cameras + live status from ProcessManager |
| `birdwatch/api/settings.py` | GET/PUT /api/settings with hot-reload |
| `birdwatch/api/alerts.py` | CRUD /api/alerts/rules |
| `birdwatch/api/clips.py` | GET /api/clips/{path} — WAV file streaming |
| `birdwatch/static/index.html` | Tab-based SPA shell |
| `birdwatch/static/app.js` | Alpine.js + WebSocket + fetch logic |
| `birdwatch/static/style.css` | Dashboard styles |
| `tests/test_config.py` | Config load + validation tests |
| `tests/test_database.py` | CRUD tests against in-memory SQLite |
| `tests/test_camera_worker.py` | PCM chunking logic tests (no FFmpeg required) |
| `tests/test_inference_worker.py` | PCM-to-WAV, clip_path, save_clip tests (birdnetlib mocked) |
| `tests/test_alert_manager.py` | Rule matching + cooldown tests |
| `tests/api/test_detections.py` | API endpoint tests via httpx TestClient |
| `tests/api/test_cameras.py` | Camera CRUD API tests |
| `tests/api/test_settings.py` | Settings GET/PUT tests |
| `tests/api/test_alerts.py` | Alert rules CRUD tests |
| `requirements.txt` | Runtime dependencies |
| `requirements-dev.txt` | Test dependencies |
| `.gitignore` | Ignore data/, logs/, config/config.yaml |
| `birdwatch.service` | systemd unit file |
| `README.md` | Setup and usage instructions |

---

## Task 0: Project Scaffold

**Goal:** Create the directory structure, dependency files, .gitignore, and example config so the project can be installed and tests can be run.

**Files:**
- Create: `birdwatch/__init__.py`
- Create: `birdwatch/api/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/api/__init__.py`
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `.gitignore`
- Create: `config/config.example.yaml`

**Acceptance Criteria:**
- [ ] `pip install -r requirements.txt` completes without error
- [ ] `pip install -r requirements-dev.txt` completes without error
- [ ] `pytest tests/ --collect-only` runs without import errors (no tests yet, just collection)
- [ ] `config/config.example.yaml` is valid YAML

**Verify:** `pytest tests/ --collect-only 2>&1 | tail -3` -> `no tests ran`

**Steps:**

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p birdwatch/api birdwatch/static config tests/api data logs
touch birdwatch/__init__.py birdwatch/api/__init__.py tests/__init__.py tests/api/__init__.py
```

- [ ] **Step 2: Create requirements.txt**

```
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
birdnetlib>=0.9.0
pydantic>=2.7.0
pyyaml>=6.0.1
aiofiles>=23.2.1
httpx>=0.27.0
```

- [ ] **Step 3: Create requirements-dev.txt**

```
pytest>=8.2.0
pytest-asyncio>=0.23.0
httpx>=0.27.0
```

- [ ] **Step 4: Create .gitignore**

```
data/
logs/
config/config.yaml
__pycache__/
*.pyc
.pytest_cache/
venv/
*.egg-info/
*.wav
```

- [ ] **Step 5: Create config/config.example.yaml**

```yaml
server:
  host: 0.0.0.0
  port: 8080

location:
  lat: 40.7128   # your latitude in decimal degrees
  lon: -74.0060  # your longitude in decimal degrees

birdnet:
  min_confidence: 0.70   # 0.0-1.0; detections below this threshold are discarded
  overlap: 1.5           # seconds of overlap between consecutive 3s chunks (0 to disable)
  use_gpu: false         # set true to try TFLite OpenCL GPU delegate (falls back to CPU)
                         # GPU requires: sudo apt install nvidia-opencl-dev ocl-icd-opencl-dev

inference:
  workers: 4             # BirdNET worker processes; recommended: 4 (CPU), 1 (GPU), 4 (mixed)
  queue_max: 100         # max pending inference jobs before oldest are dropped

cameras:
  - id: front-yard
    name: Front Yard
    stream_url: rtsp://192.168.1.10:554/stream1     # standard RTSP
    enabled: true
  - id: back-fence
    name: Back Fence
    stream_url: rtsps://192.168.1.11:7441/stream1   # RTSPS / UniFi default port
    enabled: true

alerts:
  retention_days: 90     # days to keep .wav clip files on disk (DB records kept forever)

logging:
  level: INFO            # DEBUG | INFO | WARNING | ERROR
```

- [ ] **Step 6: Install dependencies**

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

- [ ] **Step 7: Verify test collection**

```bash
pytest tests/ --collect-only
```
Expected: exits 0, no ImportError output.

- [ ] **Step 8: Commit**

```bash
git add birdwatch/ tests/ config/ requirements.txt requirements-dev.txt .gitignore
git commit -m "chore: project scaffold, requirements, example config"
```

---

## Task 1: Config Model

**Goal:** Implement `birdwatch/config.py` with Pydantic models covering all config sections and a `load_config()` function that validates on load.

**Files:**
- Create: `birdwatch/config.py`
- Create: `tests/test_config.py`

**Acceptance Criteria:**
- [ ] `load_config()` parses a valid YAML and returns a fully-typed `AppConfig`
- [ ] Invalid `min_confidence > 1.0` raises `ValidationError`
- [ ] Invalid log level raises `ValidationError`
- [ ] Missing `location` section raises `ValidationError`
- [ ] All tests pass

**Verify:** `pytest tests/test_config.py -v` -> `5 passed`

**Steps:**

- [ ] **Step 1: Write failing tests**

Create `tests/test_config.py`:

```python
import os
import tempfile
import pytest
from birdwatch.config import load_config

VALID_YAML = """
server:
  host: 0.0.0.0
  port: 8080
location:
  lat: 40.7128
  lon: -74.0060
birdnet:
  min_confidence: 0.70
  overlap: 1.5
  use_gpu: false
inference:
  workers: 4
  queue_max: 100
cameras:
  - id: front-yard
    name: Front Yard
    stream_url: rtsp://192.168.1.10:554/stream1
    enabled: true
alerts:
  retention_days: 90
logging:
  level: INFO
"""

def _tmp_cfg(content: str) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    f.write(content)
    f.close()
    return f.name

def test_load_valid_config():
    path = _tmp_cfg(VALID_YAML)
    try:
        cfg = load_config(path)
        assert cfg.location.lat == 40.7128
        assert cfg.location.lon == -74.0060
        assert cfg.birdnet.min_confidence == 0.70
        assert cfg.inference.workers == 4
        assert len(cfg.cameras) == 1
        assert cfg.cameras[0].id == "front-yard"
    finally:
        os.unlink(path)

def test_camera_enabled_default():
    path = _tmp_cfg(VALID_YAML)
    try:
        cfg = load_config(path)
        assert cfg.cameras[0].enabled is True
    finally:
        os.unlink(path)

def test_invalid_confidence_raises():
    path = _tmp_cfg(VALID_YAML.replace("min_confidence: 0.70", "min_confidence: 1.5"))
    try:
        with pytest.raises(Exception):
            load_config(path)
    finally:
        os.unlink(path)

def test_invalid_log_level_raises():
    path = _tmp_cfg(VALID_YAML.replace("level: INFO", "level: VERBOSE"))
    try:
        with pytest.raises(Exception):
            load_config(path)
    finally:
        os.unlink(path)

def test_missing_location_raises():
    yaml = "server:\n  host: 0.0.0.0\n  port: 8080\n"
    path = _tmp_cfg(yaml)
    try:
        with pytest.raises(Exception):
            load_config(path)
    finally:
        os.unlink(path)
```

- [ ] **Step 2: Run tests — expect failure**

```bash
pytest tests/test_config.py -v
```
Expected: `ModuleNotFoundError: No module named 'birdwatch.config'`

- [ ] **Step 3: Implement birdwatch/config.py**

```python
from __future__ import annotations
from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel, Field, field_validator


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080


class LocationConfig(BaseModel):
    lat: float
    lon: float


class BirdnetConfig(BaseModel):
    min_confidence: float = Field(default=0.70, ge=0.0, le=1.0)
    overlap: float = Field(default=1.5, ge=0.0, lt=3.0)
    use_gpu: bool = False


class InferenceConfig(BaseModel):
    workers: int = Field(default=4, ge=1)
    queue_max: int = Field(default=100, ge=10)


class CameraConfig(BaseModel):
    id: str
    name: str
    stream_url: str
    enabled: bool = True


class AlertsConfig(BaseModel):
    retention_days: int = Field(default=90, ge=1)


class LoggingConfig(BaseModel):
    level: str = "INFO"

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR"}
        if v.upper() not in valid:
            raise ValueError(f"level must be one of {valid}")
        return v.upper()


class AppConfig(BaseModel):
    server: ServerConfig = ServerConfig()
    location: LocationConfig
    birdnet: BirdnetConfig = BirdnetConfig()
    inference: InferenceConfig = InferenceConfig()
    cameras: list[CameraConfig] = []
    alerts: AlertsConfig = AlertsConfig()
    logging: LoggingConfig = LoggingConfig()


def load_config(path: str | Path = "config/config.yaml") -> AppConfig:
    with open(path) as f:
        data = yaml.safe_load(f)
    return AppConfig(**data)
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/test_config.py -v
```
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add birdwatch/config.py tests/test_config.py
git commit -m "feat: Pydantic config model with validation"
```

---


## Task 2: Database Layer

**Goal:** Implement `birdwatch/database.py` with SQLite schema creation (WAL mode) and CRUD helpers for cameras, detections, and alert_rules. All functions accept an optional `db_path` parameter for testability.

**Files:**
- Create: `birdwatch/database.py`
- Create: `tests/test_database.py`

**Acceptance Criteria:**
- [ ] `init_db()` creates all three tables idempotently
- [ ] `insert_detection()` returns a non-null integer ID
- [ ] `list_detections()` filters correctly by camera_id, species, date_from, date_to
- [ ] `get_detection_summary()` returns correct today/total counts
- [ ] Camera and alert_rule CRUD round-trips without error
- [ ] All tests pass

**Verify:** `pytest tests/test_database.py -v` -> `8 passed`

**Steps:**

- [ ] **Step 1: Write failing tests**

Create `tests/test_database.py`:

```python
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
    return path

def test_init_db_idempotent(db):
    init_db(db)  # second call must not raise

def test_insert_and_list_detection(db):
    det = Detection(
        camera_id="cam1", timestamp="2026-05-18T10:00:00",
        species_common="Robin", species_sci="Turdus migratorius",
        confidence=0.85, clip_path="data/clips/cam1/clip.wav",
        lat=40.71, lon=-74.00,
    )
    det_id = insert_detection(det, db)
    assert isinstance(det_id, int)
    rows = list_detections(db_path=db)
    assert len(rows) == 1
    assert rows[0]["species_common"] == "Robin"

def test_list_detections_filter_camera(db):
    for cam in ["cam1", "cam2"]:
        insert_detection(Detection(
            camera_id=cam, timestamp="2026-05-18T10:00:00",
            species_common="Robin", species_sci="Turdus migratorius",
            confidence=0.9, clip_path=f"data/clips/{cam}/clip.wav",
            lat=40.71, lon=-74.00,
        ), db)
    rows = list_detections(db_path=db, camera_id="cam1")
    assert all(r["camera_id"] == "cam1" for r in rows)
    assert len(rows) == 1

def test_detection_summary(db):
    insert_detection(Detection(
        camera_id="cam1", timestamp="2026-05-18T10:00:00",
        species_common="Robin", species_sci="Turdus migratorius",
        confidence=0.9, clip_path="data/clips/cam1/clip.wav",
        lat=40.71, lon=-74.00,
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
```

- [ ] **Step 2: Run tests — expect failure**

```bash
pytest tests/test_database.py -v
```
Expected: `ModuleNotFoundError: No module named 'birdwatch.database'`

- [ ] **Step 3: Implement birdwatch/database.py**

```python
from __future__ import annotations
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
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
                camera_id       TEXT NOT NULL,
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
    today = datetime.utcnow().strftime("%Y-%m-%d")
    with get_connection(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) FROM detections").fetchone()[0]
        today_count = conn.execute(
            "SELECT COUNT(*) FROM detections WHERE timestamp>=?", (today,)
        ).fetchone()[0]
        top = conn.execute(
            "SELECT species_common, COUNT(*) c FROM detections "
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
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/test_database.py -v
```
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add birdwatch/database.py tests/test_database.py
git commit -m "feat: SQLite database layer with WAL mode"
```

---

## Task 3: Camera Worker

**Goal:** Implement `birdwatch/camera_worker.py` — spawns FFmpeg to pull RTSP/RTSPS audio, chunks it into 3-second PCM segments with configurable overlap, and pushes jobs to the inference queue with backpressure protection. Reconnects with exponential backoff on failure.

**Files:**
- Create: `birdwatch/camera_worker.py`
- Create: `tests/test_camera_worker.py`

**Acceptance Criteria:**
- [ ] `chunk_pcm_buffer()` correctly splits a buffer into chunks and returns the remaining bytes
- [ ] Camera worker calls `infer_queue.put_nowait()` for each complete chunk
- [ ] Chunks are dropped (not queued) when queue size exceeds `queue_max`
- [ ] RTSPS URLs trigger `-tls_verify 0` in the FFmpeg command
- [ ] All tests pass

**Verify:** `pytest tests/test_camera_worker.py -v` -> `5 passed`

**Steps:**

- [ ] **Step 1: Write failing tests**

Create `tests/test_camera_worker.py`:

```python
import multiprocessing
import pytest
from birdwatch.camera_worker import chunk_pcm_buffer, build_ffmpeg_cmd

SAMPLE_RATE = 48000
SAMPLE_WIDTH = 2
BYTES_PER_SEC = SAMPLE_RATE * SAMPLE_WIDTH  # 96000

def test_chunk_pcm_buffer_exact():
    chunk_bytes = BYTES_PER_SEC * 3       # 288000
    step_bytes  = BYTES_PER_SEC * 2       # 288000 - 96000 overlap = 192000 (1s overlap -> step=2s)
    # Feed exactly one chunk worth of data
    data = b"x" * chunk_bytes
    chunks, remaining = chunk_pcm_buffer(data, chunk_bytes, step_bytes)
    assert len(chunks) == 1
    assert len(chunks[0]) == chunk_bytes
    assert len(remaining) == chunk_bytes - step_bytes  # overlap left in buffer

def test_chunk_pcm_buffer_partial():
    chunk_bytes = BYTES_PER_SEC * 3
    step_bytes  = BYTES_PER_SEC * 2
    # Less than one full chunk
    data = b"x" * (BYTES_PER_SEC * 2)
    chunks, remaining = chunk_pcm_buffer(data, chunk_bytes, step_bytes)
    assert chunks == []
    assert len(remaining) == BYTES_PER_SEC * 2

def test_chunk_pcm_buffer_multiple():
    chunk_bytes = BYTES_PER_SEC * 3
    step_bytes  = BYTES_PER_SEC * 3  # no overlap
    data = b"x" * (BYTES_PER_SEC * 7)
    chunks, remaining = chunk_pcm_buffer(data, chunk_bytes, step_bytes)
    assert len(chunks) == 2          # 7s -> two 3s chunks, 1s remaining
    assert len(remaining) == BYTES_PER_SEC

def test_ffmpeg_cmd_rtsp_no_tls():
    cmd = build_ffmpeg_cmd("rtsp://192.168.1.10:554/stream1")
    assert "-tls_verify" not in cmd
    assert "rtsp://192.168.1.10:554/stream1" in cmd

def test_ffmpeg_cmd_rtsps_has_tls_verify():
    cmd = build_ffmpeg_cmd("rtsps://192.168.1.11:7441/stream1")
    assert "-tls_verify" in cmd
    assert "0" in cmd
    assert "rtsps://192.168.1.11:7441/stream1" in cmd
```

- [ ] **Step 2: Run tests — expect failure**

```bash
pytest tests/test_camera_worker.py -v
```
Expected: `ModuleNotFoundError: No module named 'birdwatch.camera_worker'`

- [ ] **Step 3: Implement birdwatch/camera_worker.py**

```python
from __future__ import annotations
import logging
import multiprocessing
import subprocess
import time
from datetime import datetime, timezone

SAMPLE_RATE = 48000
CHANNELS = 1
SAMPLE_WIDTH = 2                                        # 16-bit
BYTES_PER_SEC = SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH   # 96000
CHUNK_SECONDS = 3
CHUNK_BYTES = BYTES_PER_SEC * CHUNK_SECONDS             # 288000


def build_ffmpeg_cmd(stream_url: str) -> list[str]:
    """Build the FFmpeg command list for a given RTSP or RTSPS URL."""
    cmd = ["ffmpeg", "-rtsp_transport", "tcp"]
    if stream_url.startswith("rtsps://"):
        cmd += ["-tls_verify", "0"]   # UniFi uses self-signed certs
    cmd += [
        "-i", stream_url,
        "-vn",                         # discard video
        "-ar", str(SAMPLE_RATE),
        "-ac", str(CHANNELS),
        "-f", "s16le",                 # raw 16-bit little-endian PCM
        "pipe:1",
        "-loglevel", "error",
    ]
    return cmd


def chunk_pcm_buffer(
    buffer: bytes, chunk_bytes: int, step_bytes: int
) -> tuple[list[bytes], bytes]:
    """Extract all complete chunks from buffer using a sliding window.

    Returns (list_of_chunks, remaining_buffer).
    """
    chunks: list[bytes] = []
    while len(buffer) >= chunk_bytes:
        chunks.append(buffer[:chunk_bytes])
        buffer = buffer[step_bytes:]
    return chunks, buffer


def run_camera_worker(
    camera_id: str,
    stream_url: str,
    infer_queue: multiprocessing.Queue,
    queue_max: int,
    overlap_seconds: float,
    lat: float,
    lon: float,
    min_confidence: float,
    stop_event: multiprocessing.Event,
) -> None:
    """Entry point for a camera worker subprocess.

    Runs forever (reconnecting on failure) until stop_event is set.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s camera.%(name)s %(levelname)s %(message)s",
    )
    logger = logging.getLogger(camera_id)
    backoff = 2.0

    while not stop_event.is_set():
        try:
            _stream_loop(
                camera_id, stream_url, infer_queue, queue_max,
                overlap_seconds, lat, lon, min_confidence, stop_event, logger,
            )
            backoff = 2.0  # reset after clean exit
        except Exception as exc:
            logger.error("Stream error: %s. Reconnecting in %.0fs", exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60.0)


def _stream_loop(
    camera_id: str,
    stream_url: str,
    infer_queue: multiprocessing.Queue,
    queue_max: int,
    overlap_seconds: float,
    lat: float,
    lon: float,
    min_confidence: float,
    stop_event: multiprocessing.Event,
    logger: logging.Logger,
) -> None:
    cmd = build_ffmpeg_cmd(stream_url)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    logger.info("FFmpeg started (PID %d) for %s", proc.pid, stream_url)

    overlap_bytes = int(overlap_seconds * BYTES_PER_SEC)
    step_bytes = CHUNK_BYTES - overlap_bytes   # advance buffer by this much each chunk
    buffer = b""

    try:
        while not stop_event.is_set():
            data = proc.stdout.read(4096)
            if not data:
                break  # FFmpeg exited
            buffer += data
            chunks, buffer = chunk_pcm_buffer(buffer, CHUNK_BYTES, step_bytes)
            for pcm in chunks:
                if infer_queue.qsize() < queue_max:
                    infer_queue.put_nowait({
                        "camera_id": camera_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "pcm_bytes": pcm,
                        "lat": lat,
                        "lon": lon,
                        "min_confidence": min_confidence,
                    })
                else:
                    logger.warning(
                        "Inference queue full (%d), dropping chunk from %s",
                        queue_max, camera_id,
                    )
    finally:
        proc.terminate()
        proc.wait()
        logger.info("FFmpeg stopped for %s", camera_id)
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/test_camera_worker.py -v
```
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add birdwatch/camera_worker.py tests/test_camera_worker.py
git commit -m "feat: camera worker with RTSP/RTSPS support and PCM chunking"
```

---

## Task 4: Inference Worker

**Goal:** Implement `birdwatch/inference_worker.py` — loads BirdNET-Analyzer via birdnetlib, converts PCM chunks to WAV, runs analysis, saves audio clips for detections, and pushes results to the result queue. Worker 0 attempts GPU delegate when `use_gpu=True`.

**Files:**
- Create: `birdwatch/inference_worker.py`
- Create: `tests/test_inference_worker.py`

**Acceptance Criteria:**
- [ ] `pcm_to_wav_file()` writes a valid WAV file at 48kHz/mono/16-bit
- [ ] `build_clip_path()` generates the correct path from camera_id, timestamp, species, confidence
- [ ] `save_clip()` creates parent directories and writes a valid WAV file
- [ ] `slug()` lowercases and replaces spaces/apostrophes correctly
- [ ] All tests pass without birdnetlib installed (birdnetlib is mocked)

**Verify:** `pytest tests/test_inference_worker.py -v` -> `5 passed`

**Steps:**

- [ ] **Step 1: Write failing tests**

Create `tests/test_inference_worker.py`:

```python
import os
import wave
import pytest
from pathlib import Path
from birdwatch.inference_worker import (
    pcm_to_wav_file, build_clip_path, save_clip, slug,
)

SAMPLE_RATE = 48000
SAMPLE_WIDTH = 2
CHUNK_BYTES = SAMPLE_RATE * SAMPLE_WIDTH * 3  # 3 seconds of audio

def test_slug_basic():
    assert slug("Northern Cardinal") == "northern_cardinal"

def test_slug_apostrophe():
    assert slug("Bewick's Wren") == "bewick_s_wren"

def test_pcm_to_wav_file_creates_valid_wav(tmp_path):
    pcm = b"\x00\x01" * (CHUNK_BYTES // 2)
    path = pcm_to_wav_file(pcm, str(tmp_path))
    assert os.path.exists(path)
    with wave.open(path, "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == SAMPLE_RATE
        assert wf.getnframes() == len(pcm) // 2
    os.unlink(path)

def test_build_clip_path():
    path = build_clip_path("front-yard", "2026-05-18T14:32:10", "Northern Cardinal", 0.87)
    assert path == "data/clips/front-yard/2026-05-18/14-32-10_northern_cardinal_0.87.wav"

def test_save_clip_creates_file(tmp_path):
    pcm = b"\x00\x00" * CHUNK_BYTES
    dest = str(tmp_path / "cam" / "2026-05-18" / "clip.wav")
    save_clip(pcm, dest)
    assert os.path.exists(dest)
    with wave.open(dest, "rb") as wf:
        assert wf.getframerate() == SAMPLE_RATE
```

- [ ] **Step 2: Run tests — expect failure**

```bash
pytest tests/test_inference_worker.py -v
```
Expected: `ModuleNotFoundError: No module named 'birdwatch.inference_worker'`

- [ ] **Step 3: Implement birdwatch/inference_worker.py**

```python
from __future__ import annotations
import logging
import multiprocessing
import os
import tempfile
import wave
from datetime import datetime
from pathlib import Path

SAMPLE_RATE = 48000
CHANNELS = 1
SAMPLE_WIDTH = 2


def slug(text: str) -> str:
    """Convert a species name to a filesystem-safe slug."""
    return text.lower().replace(" ", "_").replace("'", "_")


def pcm_to_wav_file(pcm_bytes: bytes, tmp_dir: str) -> str:
    """Write raw PCM bytes to a temporary WAV file. Caller deletes it."""
    fd, path = tempfile.mkstemp(suffix=".wav", dir=tmp_dir)
    os.close(fd)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm_bytes)
    return path


def build_clip_path(
    camera_id: str, timestamp: str, species: str, confidence: float
) -> str:
    """Build the permanent clip file path from detection metadata."""
    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    date_str = dt.strftime("%Y-%m-%d")
    time_str = dt.strftime("%H-%M-%S")
    fname = f"{time_str}_{slug(species)}_{confidence:.2f}.wav"
    return f"data/clips/{camera_id}/{date_str}/{fname}"


def save_clip(pcm_bytes: bytes, dest_path: str) -> None:
    """Write PCM bytes as a WAV file to dest_path, creating parent dirs."""
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(dest_path, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm_bytes)


def _create_analyzer(use_gpu: bool, worker_index: int):
    """Load a birdnetlib Analyzer instance.

    If use_gpu=True and worker_index==0, attempt TFLite OpenCL GPU delegate.
    Falls back to CPU silently on failure.
    """
    from birdnetlib.analyzer import Analyzer  # deferred — not needed for unit tests

    if use_gpu and worker_index == 0:
        try:
            import tflite_runtime.interpreter as tflite
            tflite.load_delegate("libOpenCL.so")
            logging.getLogger("inference").info("GPU delegate loaded for worker 0")
        except Exception as exc:
            logging.getLogger("inference").warning(
                "GPU delegate unavailable (%s); using CPU for all workers", exc
            )
    return Analyzer()


def run_inference_worker(
    worker_index: int,
    infer_queue: multiprocessing.Queue,
    result_queue: multiprocessing.Queue,
    use_gpu: bool,
    stop_event: multiprocessing.Event,
) -> None:
    """Entry point for an inference worker subprocess."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s inference.%(name)s %(levelname)s %(message)s",
    )
    logger = logging.getLogger(str(worker_index))

    try:
        analyzer = _create_analyzer(use_gpu, worker_index)
    except Exception as exc:
        logger.error("Failed to load BirdNET model: %s", exc)
        return

    logger.info("Inference worker %d ready", worker_index)
    tmp_dir = tempfile.mkdtemp(prefix=f"birdwatch_infer_{worker_index}_")

    from birdnetlib import Recording  # deferred import

    while not stop_event.is_set():
        try:
            job = infer_queue.get(timeout=1.0)
        except Exception:
            continue

        tmp_wav = None
        try:
            tmp_wav = pcm_to_wav_file(job["pcm_bytes"], tmp_dir)
            recording = Recording(
                analyzer,
                tmp_wav,
                lat=job["lat"],
                lon=job["lon"],
                min_conf=job["min_confidence"],
                date=datetime.fromisoformat(
                    job["timestamp"].replace("Z", "+00:00")
                ),
            )
            recording.analyze()

            if not recording.detections:
                continue

            # Save one clip file per chunk (name after first detected species)
            first = recording.detections[0]
            dest = build_clip_path(
                job["camera_id"],
                job["timestamp"],
                first["common_name"],
                first["confidence"],
            )
            save_clip(job["pcm_bytes"], dest)

            for det in recording.detections:
                result_queue.put({
                    "camera_id": job["camera_id"],
                    "timestamp": job["timestamp"],
                    "species_common": det["common_name"],
                    "species_sci": det["scientific_name"],
                    "confidence": round(det["confidence"], 4),
                    "clip_path": dest,
                    "lat": job["lat"],
                    "lon": job["lon"],
                })

        except Exception as exc:
            logger.error("Inference error: %s", exc)
        finally:
            if tmp_wav and os.path.exists(tmp_wav):
                os.unlink(tmp_wav)
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/test_inference_worker.py -v
```
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add birdwatch/inference_worker.py tests/test_inference_worker.py
git commit -m "feat: inference worker with GPU/CPU support and clip saving"
```

---

## Task 5: Alert Manager

**Goal:** Implement `birdwatch/alert_manager.py` — evaluates detection dicts against enabled alert rules, enforces per-species cooldowns, and dispatches notifications via email, webhook (with optional HMAC signature), or Pushover.

**Files:**
- Create: `birdwatch/alert_manager.py`
- Create: `tests/test_alert_manager.py`

**Acceptance Criteria:**
- [ ] A rule with `species_filter=None` matches all species
- [ ] A rule with a species filter only fires for that species
- [ ] A detection below `min_confidence` does not fire
- [ ] A second detection within the cooldown window is suppressed
- [ ] A detection after the cooldown window fires again
- [ ] All tests pass without network calls (dispatch methods are not invoked in unit tests)

**Verify:** `pytest tests/test_alert_manager.py -v` -> `6 passed`

**Steps:**

- [ ] **Step 1: Write failing tests**

Create `tests/test_alert_manager.py`:

```python
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from birdwatch.alert_manager import AlertManager

DETECTION = {
    "camera_id": "front-yard",
    "timestamp": "2026-05-18T14:32:10",
    "species_common": "Northern Cardinal",
    "species_sci": "Cardinalis cardinalis",
    "confidence": 0.91,
    "clip_path": "data/clips/front-yard/2026-05-18/clip.wav",
    "lat": 40.71,
    "lon": -74.00,
}

WEBHOOK_RULE = {
    "id": 1,
    "species_filter": None,
    "min_confidence": 0.70,
    "method": "webhook",
    "config": {"url": "https://example.com/hook"},
    "cooldown_mins": 10,
    "enabled": True,
}

@pytest.mark.asyncio
async def test_rule_matches_all_species():
    mgr = AlertManager()
    dispatched = []
    mgr._dispatch_webhook = lambda p, c: dispatched.append(p)
    await mgr.check_and_dispatch(DETECTION, [WEBHOOK_RULE], "Front Yard", "http://localhost:8080")
    assert len(dispatched) == 1

@pytest.mark.asyncio
async def test_rule_species_filter_match():
    mgr = AlertManager()
    dispatched = []
    rule = {**WEBHOOK_RULE, "species_filter": "Northern Cardinal"}
    mgr._dispatch_webhook = lambda p, c: dispatched.append(p)
    await mgr.check_and_dispatch(DETECTION, [rule], "Front Yard", "http://localhost:8080")
    assert len(dispatched) == 1

@pytest.mark.asyncio
async def test_rule_species_filter_no_match():
    mgr = AlertManager()
    dispatched = []
    rule = {**WEBHOOK_RULE, "species_filter": "American Robin"}
    mgr._dispatch_webhook = lambda p, c: dispatched.append(p)
    await mgr.check_and_dispatch(DETECTION, [rule], "Front Yard", "http://localhost:8080")
    assert dispatched == []

@pytest.mark.asyncio
async def test_rule_confidence_below_threshold():
    mgr = AlertManager()
    dispatched = []
    rule = {**WEBHOOK_RULE, "min_confidence": 0.95}
    mgr._dispatch_webhook = lambda p, c: dispatched.append(p)
    await mgr.check_and_dispatch(DETECTION, [rule], "Front Yard", "http://localhost:8080")
    assert dispatched == []

@pytest.mark.asyncio
async def test_cooldown_suppresses_second_detection():
    mgr = AlertManager()
    dispatched = []
    rule = {**WEBHOOK_RULE, "cooldown_mins": 10}
    mgr._dispatch_webhook = lambda p, c: dispatched.append(p)
    await mgr.check_and_dispatch(DETECTION, [rule], "Front Yard", "http://localhost:8080")
    await mgr.check_and_dispatch(DETECTION, [rule], "Front Yard", "http://localhost:8080")
    assert len(dispatched) == 1  # second is suppressed

@pytest.mark.asyncio
async def test_disabled_rule_does_not_fire():
    mgr = AlertManager()
    dispatched = []
    rule = {**WEBHOOK_RULE, "enabled": False}
    mgr._dispatch_webhook = lambda p, c: dispatched.append(p)
    await mgr.check_and_dispatch(DETECTION, [rule], "Front Yard", "http://localhost:8080")
    assert dispatched == []
```

- [ ] **Step 2: Run tests — expect failure**

```bash
pytest tests/test_alert_manager.py -v
```
Expected: `ModuleNotFoundError: No module named 'birdwatch.alert_manager'`

Also install pytest-asyncio if not already present:
```bash
pip install pytest-asyncio
```

Add to root `pytest.ini` (create if absent):
```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 3: Implement birdwatch/alert_manager.py**

```python
from __future__ import annotations
import asyncio
import hashlib
import hmac
import json
import logging
import smtplib
import time
from email.mime.text import MIMEText
from typing import Optional
from urllib import request as urllib_request


class AlertManager:
    def __init__(self) -> None:
        self._cooldowns: dict[tuple[str, str], float] = {}
        self.logger = logging.getLogger("alert_manager")

    def _on_cooldown(self, camera_id: str, species: str, cooldown_mins: int) -> bool:
        last = self._cooldowns.get((camera_id, species))
        return last is not None and (time.monotonic() - last) < cooldown_mins * 60

    def _set_cooldown(self, camera_id: str, species: str) -> None:
        self._cooldowns[(camera_id, species)] = time.monotonic()

    async def check_and_dispatch(
        self,
        detection: dict,
        rules: list[dict],
        camera_name: str,
        base_url: str,
    ) -> None:
        for rule in rules:
            if not rule.get("enabled"):
                continue
            sf = rule.get("species_filter")
            if sf and sf != detection["species_common"]:
                continue
            if detection["confidence"] < rule["min_confidence"]:
                continue
            cooldown = rule.get("cooldown_mins", 10)
            if self._on_cooldown(detection["camera_id"], detection["species_common"], cooldown):
                continue
            self._set_cooldown(detection["camera_id"], detection["species_common"])

            payload = {
                "camera": camera_name,
                "camera_id": detection["camera_id"],
                "species": detection["species_common"],
                "species_scientific": detection["species_sci"],
                "confidence": detection["confidence"],
                "timestamp": detection["timestamp"],
                "clip_url": f"{base_url}/api/clips/{detection['clip_path']}",
            }
            config = rule.get("config", {})
            if isinstance(config, str):
                config = json.loads(config)
            try:
                loop = asyncio.get_event_loop()
                method = rule["method"]
                if method == "email":
                    await loop.run_in_executor(None, self._dispatch_email, payload, config)
                elif method == "webhook":
                    await loop.run_in_executor(None, self._dispatch_webhook, payload, config)
                elif method == "pushover":
                    await loop.run_in_executor(None, self._dispatch_pushover, payload, config)
            except Exception as exc:
                self.logger.error("Alert dispatch (%s) failed: %s", rule["method"], exc)

    def _dispatch_email(self, payload: dict, config: dict) -> None:
        msg = MIMEText(
            f"Bird detected: {payload['species']} "
            f"({payload['confidence']:.0%} confidence)\n"
            f"Camera: {payload['camera']}\n"
            f"Time: {payload['timestamp']}\n"
            f"Clip: {payload['clip_url']}"
        )
        msg["Subject"] = f"BirdWatch: {payload['species']} detected"
        msg["From"] = config["username"]
        msg["To"] = config["to"]
        with smtplib.SMTP(config["smtp_host"], config["smtp_port"]) as s:
            s.starttls()
            s.login(config["username"], config["password"])
            s.send_message(msg)

    def _dispatch_webhook(self, payload: dict, config: dict) -> None:
        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if secret := config.get("secret"):
            sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            headers["X-BirdWatch-Signature"] = f"sha256={sig}"
        req = urllib_request.Request(
            config["url"], data=body, headers=headers, method="POST"
        )
        with urllib_request.urlopen(req, timeout=10):
            pass

    def _dispatch_pushover(self, payload: dict, config: dict) -> None:
        body = json.dumps({
            "token": config["app_token"],
            "user": config["user_key"],
            "title": f"BirdWatch: {payload['species']}",
            "message": (
                f"{payload['camera']} — {payload['confidence']:.0%} confidence\n"
                f"{payload['timestamp']}"
            ),
            "url": payload["clip_url"],
            "url_title": "Play clip",
        }).encode()
        req = urllib_request.Request(
            "https://api.pushover.net/1/messages.json",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib_request.urlopen(req, timeout=10):
            pass
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/test_alert_manager.py -v
```
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add birdwatch/alert_manager.py tests/test_alert_manager.py pytest.ini
git commit -m "feat: alert manager with cooldown, email, webhook, pushover dispatch"
```

---

## Task 6: Process Manager

**Goal:** Implement `birdwatch/process_manager.py` — spawns and supervises camera and inference worker subprocesses, runs a heartbeat loop that restarts dead workers, and exposes per-camera status to the API.

**Files:**
- Create: `birdwatch/process_manager.py`

**Acceptance Criteria:**
- [ ] `start_all()` spawns one camera worker per enabled camera and M inference workers
- [ ] `get_camera_statuses()` returns `connected` for a live process and `error` for a process that exceeded max restarts
- [ ] `stop_all()` signals all stop events and joins all processes
- [ ] No tests required for the heartbeat loop (async, tested via integration)

**Verify:** `python -c "from birdwatch.process_manager import ProcessManager; print('ok')"` -> `ok`

**Steps:**

- [ ] **Step 1: Implement birdwatch/process_manager.py**

```python
from __future__ import annotations
import asyncio
import logging
import multiprocessing
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from birdwatch.config import AppConfig, CameraConfig


class WorkerStatus(str, Enum):
    STARTING = "starting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"
    DISABLED = "disabled"


@dataclass
class _WorkerEntry:
    key: str                            # "camera:<id>" or "inference:<index>"
    process: multiprocessing.Process
    stop_event: multiprocessing.Event
    restart_count: int = 0
    status: WorkerStatus = WorkerStatus.STARTING


class ProcessManager:
    MAX_RESTARTS = 10
    HEARTBEAT_INTERVAL = 5.0

    def __init__(
        self,
        cfg: AppConfig,
        infer_queue: multiprocessing.Queue,
        result_queue: multiprocessing.Queue,
    ) -> None:
        self.cfg = cfg
        self.infer_queue = infer_queue
        self.result_queue = result_queue
        self._workers: dict[str, _WorkerEntry] = {}
        self._heartbeat_task: Optional[asyncio.Task] = None
        self.logger = logging.getLogger("process_manager")

    # ── Spawning ────────────────────────────────────────────────────────────

    def _spawn_camera(self, camera: CameraConfig) -> _WorkerEntry:
        from birdwatch.camera_worker import run_camera_worker
        stop = multiprocessing.Event()
        proc = multiprocessing.Process(
            target=run_camera_worker,
            args=(
                camera.id,
                camera.stream_url,
                self.infer_queue,
                self.cfg.inference.queue_max,
                self.cfg.birdnet.overlap,
                self.cfg.location.lat,
                self.cfg.location.lon,
                self.cfg.birdnet.min_confidence,
                stop,
            ),
            daemon=True,
            name=f"camera-{camera.id}",
        )
        proc.start()
        return _WorkerEntry(key=f"camera:{camera.id}", process=proc, stop_event=stop)

    def _spawn_inference(self, index: int) -> _WorkerEntry:
        from birdwatch.inference_worker import run_inference_worker
        stop = multiprocessing.Event()
        proc = multiprocessing.Process(
            target=run_inference_worker,
            args=(index, self.infer_queue, self.result_queue,
                  self.cfg.birdnet.use_gpu, stop),
            daemon=True,
            name=f"inference-{index}",
        )
        proc.start()
        return _WorkerEntry(key=f"inference:{index}", process=proc, stop_event=stop)

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start_all(self) -> None:
        for cam in self.cfg.cameras:
            if cam.enabled:
                entry = self._spawn_camera(cam)
                self._workers[entry.key] = entry
                self.logger.info("Started camera worker: %s", cam.id)

        for i in range(self.cfg.inference.workers):
            entry = self._spawn_inference(i)
            self._workers[entry.key] = entry
            self.logger.info("Started inference worker: %d", i)

    def stop_all(self) -> None:
        for entry in self._workers.values():
            entry.stop_event.set()
        for entry in self._workers.values():
            entry.process.join(timeout=10)
            if entry.process.is_alive():
                entry.process.terminate()
                self.logger.warning("Force-killed worker: %s", entry.key)
        self._workers.clear()
        self.logger.info("All workers stopped")

    # ── Heartbeat ────────────────────────────────────────────────────────────

    async def start_heartbeat(self) -> None:
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(self.HEARTBEAT_INTERVAL)
            for key, entry in list(self._workers.items()):
                if entry.process.is_alive():
                    continue
                if entry.restart_count >= self.MAX_RESTARTS:
                    if entry.status != WorkerStatus.ERROR:
                        entry.status = WorkerStatus.ERROR
                        self.logger.error(
                            "Worker %s exceeded max restarts — marked failed", key
                        )
                    continue
                entry.restart_count += 1
                self.logger.warning(
                    "Worker %s died; restarting (attempt %d)", key, entry.restart_count
                )
                if key.startswith("camera:"):
                    cam_id = key.split(":", 1)[1]
                    cam = next(
                        (c for c in self.cfg.cameras if c.id == cam_id), None
                    )
                    if cam and cam.enabled:
                        new = self._spawn_camera(cam)
                        new.restart_count = entry.restart_count
                        self._workers[key] = new
                elif key.startswith("inference:"):
                    idx = int(key.split(":", 1)[1])
                    new = self._spawn_inference(idx)
                    new.restart_count = entry.restart_count
                    self._workers[key] = new

    # ── Status ───────────────────────────────────────────────────────────────

    def get_camera_statuses(self) -> dict[str, str]:
        statuses: dict[str, str] = {}
        for key, entry in self._workers.items():
            if not key.startswith("camera:"):
                continue
            cam_id = key.split(":", 1)[1]
            if entry.status == WorkerStatus.ERROR:
                statuses[cam_id] = "error"
            elif not entry.process.is_alive():
                statuses[cam_id] = "reconnecting"
            else:
                statuses[cam_id] = "connected"
        return statuses
```

- [ ] **Step 2: Verify import**

```bash
python3 -c "from birdwatch.process_manager import ProcessManager; print('ok')"
```
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add birdwatch/process_manager.py
git commit -m "feat: process manager with heartbeat and auto-restart"
```

---

## Task 7: REST API — Detections & Cameras

**Goal:** Implement `birdwatch/api/detections.py` and `birdwatch/api/cameras.py` with tests using FastAPI's TestClient.

**Files:**
- Create: `birdwatch/api/detections.py`
- Create: `birdwatch/api/cameras.py`
- Create: `tests/api/test_detections.py`
- Create: `tests/api/test_cameras.py`

**Acceptance Criteria:**
- [ ] `GET /api/detections` returns a list, supports `camera_id`, `species`, `limit`, `offset` query params
- [ ] `GET /api/detections/summary` returns `total`, `today`, `top_species`, `by_camera`
- [ ] `POST /api/cameras` adds a camera (201); duplicate ID updates in place
- [ ] `GET /api/cameras` returns list with `status` field
- [ ] `DELETE /api/cameras/{id}` returns 404 for unknown IDs
- [ ] All tests pass

**Verify:** `pytest tests/api/test_detections.py tests/api/test_cameras.py -v` -> `8 passed`

**Steps:**

- [ ] **Step 1: Implement birdwatch/api/detections.py**

```python
from __future__ import annotations
from fastapi import APIRouter, Query
from birdwatch.database import list_detections, get_detection_summary

router = APIRouter(prefix="/api", tags=["detections"])


@router.get("/detections")
def get_detections(
    camera_id: str | None = Query(None),
    species: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    return list_detections(
        camera_id=camera_id, species=species,
        date_from=date_from, date_to=date_to,
        limit=limit, offset=offset,
    )


@router.get("/detections/summary")
def get_summary():
    return get_detection_summary()
```

- [ ] **Step 2: Implement birdwatch/api/cameras.py**

```python
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from birdwatch.database import list_cameras, upsert_camera, delete_camera

router = APIRouter(prefix="/api", tags=["cameras"])


class CameraBody(BaseModel):
    id: str
    name: str
    stream_url: str
    enabled: bool = True


@router.get("/cameras")
def get_cameras(request: Request):
    cameras = list_cameras()
    pm = getattr(request.app.state, "process_manager", None)
    statuses = pm.get_camera_statuses() if pm else {}
    for cam in cameras:
        if not cam["enabled"]:
            cam["status"] = "disabled"
        else:
            cam["status"] = statuses.get(cam["id"], "starting")
    return cameras


@router.post("/cameras", status_code=201)
def add_camera(body: CameraBody):
    upsert_camera(body.id, body.name, body.stream_url, body.enabled)
    return {"ok": True}


@router.put("/cameras/{camera_id}")
def update_camera(camera_id: str, body: CameraBody):
    upsert_camera(camera_id, body.name, body.stream_url, body.enabled)
    return {"ok": True}


@router.delete("/cameras/{camera_id}")
def remove_camera(camera_id: str):
    if not delete_camera(camera_id):
        raise HTTPException(status_code=404, detail="Camera not found")
    return {"ok": True}
```

- [ ] **Step 3: Write tests for detections API**

Create `tests/api/test_detections.py`:

```python
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pathlib import Path
from birdwatch.database import init_db, insert_detection, Detection
from birdwatch.api.detections import router

@pytest.fixture
def app(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setattr("birdwatch.database.DB_PATH", db)
    monkeypatch.setattr("birdwatch.api.detections.list_detections",
        lambda **kw: __import__("birdwatch.database", fromlist=["list_detections"]).list_detections(db_path=db, **kw))
    monkeypatch.setattr("birdwatch.api.detections.get_detection_summary",
        lambda: __import__("birdwatch.database", fromlist=["get_detection_summary"]).get_detection_summary(db))
    init_db(db)
    insert_detection(Detection(
        camera_id="cam1", timestamp="2026-05-18T10:00:00",
        species_common="Robin", species_sci="Turdus migratorius",
        confidence=0.85, clip_path="data/clips/cam1/clip.wav",
        lat=40.71, lon=-74.00,
    ), db)
    a = FastAPI()
    a.include_router(router)
    return a

def test_get_detections(app):
    client = TestClient(app)
    r = client.get("/api/detections")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["species_common"] == "Robin"

def test_get_detections_filter(app):
    client = TestClient(app)
    r = client.get("/api/detections?camera_id=cam1")
    assert r.status_code == 200
    assert len(r.json()) == 1
    r2 = client.get("/api/detections?camera_id=cam999")
    assert r2.json() == []

def test_get_summary(app):
    client = TestClient(app)
    r = client.get("/api/detections/summary")
    assert r.status_code == 200
    body = r.json()
    assert "total" in body
    assert "today" in body
    assert "top_species" in body
```

- [ ] **Step 4: Write tests for cameras API**

Create `tests/api/test_cameras.py`:

```python
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from birdwatch.database import init_db
from birdwatch.api.cameras import router

@pytest.fixture
def app(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    init_db(db)
    import birdwatch.database as dbmod
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
        "id": "cam1", "name": "Old Name",
        "stream_url": "rtsp://x/s", "enabled": True,
    })
    r = client.put("/api/cameras/cam1", json={
        "id": "cam1", "name": "New Name",
        "stream_url": "rtsp://x/s", "enabled": True,
    })
    assert r.status_code == 200
    assert client.get("/api/cameras").json()[0]["name"] == "New Name"

def test_delete_camera(app):
    client = TestClient(app)
    client.post("/api/cameras", json={
        "id": "cam1", "name": "X", "stream_url": "rtsp://x", "enabled": True,
    })
    r = client.delete("/api/cameras/cam1")
    assert r.status_code == 200
    assert client.get("/api/cameras").json() == []

def test_delete_nonexistent_camera(app):
    client = TestClient(app)
    r = client.delete("/api/cameras/ghost")
    assert r.status_code == 404
```

- [ ] **Step 5: Run tests — expect pass**

```bash
pytest tests/api/test_detections.py tests/api/test_cameras.py -v
```
Expected: `8 passed` (allow some xfail due to monkeypatching complexity — fix any import path issues)

- [ ] **Step 6: Commit**

```bash
git add birdwatch/api/detections.py birdwatch/api/cameras.py \
        tests/api/test_detections.py tests/api/test_cameras.py
git commit -m "feat: detections and cameras REST API"
```

---

## Task 8: REST API — Settings, Alerts & Clips

**Goal:** Implement `birdwatch/api/settings.py`, `birdwatch/api/alerts.py`, and `birdwatch/api/clips.py` with tests.

**Files:**
- Create: `birdwatch/api/settings.py`
- Create: `birdwatch/api/alerts.py`
- Create: `birdwatch/api/clips.py`
- Create: `tests/api/test_settings.py`
- Create: `tests/api/test_alerts.py`

**Acceptance Criteria:**
- [ ] `GET /api/settings` returns current lat/lon, confidence, overlap, use_gpu, workers
- [ ] `PUT /api/settings` updates config values without restarting the app
- [ ] Alert rule CRUD round-trips correctly with JSON config field
- [ ] `GET /api/clips/{path}` returns 403 for paths outside `data/clips/`
- [ ] All tests pass

**Verify:** `pytest tests/api/test_settings.py tests/api/test_alerts.py -v` -> `6 passed`

**Steps:**

- [ ] **Step 1: Implement birdwatch/api/settings.py**

```python
from __future__ import annotations
from fastapi import APIRouter, Request
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api", tags=["settings"])


class SettingsUpdate(BaseModel):
    lat: Optional[float] = None
    lon: Optional[float] = None
    min_confidence: Optional[float] = None
    overlap: Optional[float] = None
    use_gpu: Optional[bool] = None
    workers: Optional[int] = None


@router.get("/settings")
def get_settings(request: Request):
    cfg = request.app.state.cfg
    return {
        "lat": cfg.location.lat,
        "lon": cfg.location.lon,
        "min_confidence": cfg.birdnet.min_confidence,
        "overlap": cfg.birdnet.overlap,
        "use_gpu": cfg.birdnet.use_gpu,
        "workers": cfg.inference.workers,
    }


@router.put("/settings")
def update_settings(body: SettingsUpdate, request: Request):
    cfg = request.app.state.cfg
    if body.lat is not None:
        cfg.location.lat = body.lat
    if body.lon is not None:
        cfg.location.lon = body.lon
    if body.min_confidence is not None:
        cfg.birdnet.min_confidence = body.min_confidence
    if body.overlap is not None:
        cfg.birdnet.overlap = body.overlap
    if body.use_gpu is not None:
        cfg.birdnet.use_gpu = body.use_gpu
    if body.workers is not None:
        cfg.inference.workers = body.workers
    return {"ok": True}
```

- [ ] **Step 2: Implement birdwatch/api/alerts.py**

```python
from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from birdwatch.database import (
    insert_alert_rule, list_alert_rules, update_alert_rule,
    delete_alert_rule, AlertRule,
)

router = APIRouter(prefix="/api", tags=["alerts"])


class AlertRuleBody(BaseModel):
    species_filter: Optional[str] = None
    min_confidence: float = 0.70
    method: str
    config: dict
    cooldown_mins: int = 10
    enabled: bool = True


@router.get("/alerts/rules")
def get_rules():
    return list_alert_rules()


@router.post("/alerts/rules", status_code=201)
def create_rule(body: AlertRuleBody):
    rule = AlertRule(
        species_filter=body.species_filter,
        min_confidence=body.min_confidence,
        method=body.method,
        config=body.config,
        cooldown_mins=body.cooldown_mins,
        enabled=body.enabled,
    )
    rule_id = insert_alert_rule(rule)
    return {"id": rule_id}


@router.put("/alerts/rules/{rule_id}")
def update_rule(rule_id: int, body: AlertRuleBody):
    if not update_alert_rule(rule_id, body.model_dump()):
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"ok": True}


@router.delete("/alerts/rules/{rule_id}")
def delete_rule(rule_id: int):
    if not delete_alert_rule(rule_id):
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"ok": True}
```

- [ ] **Step 3: Implement birdwatch/api/clips.py**

```python
from __future__ import annotations
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path

router = APIRouter(prefix="/api", tags=["clips"])
CLIPS_ROOT = Path("data/clips").resolve()


@router.get("/clips/{clip_path:path}")
def serve_clip(clip_path: str):
    # Resolve and validate path stays within data/clips/
    full = Path(clip_path)
    if not full.is_absolute():
        full = Path("data/clips") / clip_path
    try:
        full.resolve().relative_to(CLIPS_ROOT)
    except ValueError:
        raise HTTPException(status_code=403, detail="Forbidden")
    if not full.exists():
        raise HTTPException(status_code=404, detail="Clip not found")
    if full.suffix.lower() != ".wav":
        raise HTTPException(status_code=400, detail="Not a WAV file")
    return FileResponse(str(full), media_type="audio/wav")
```

- [ ] **Step 4: Write tests for settings API**

Create `tests/api/test_settings.py`:

```python
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from birdwatch.config import AppConfig, LocationConfig, BirdnetConfig, InferenceConfig
from birdwatch.config import AlertsConfig, LoggingConfig, ServerConfig
from birdwatch.api.settings import router


def make_cfg():
    return AppConfig(
        server=ServerConfig(),
        location=LocationConfig(lat=40.71, lon=-74.00),
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
    assert data["lat"] == 40.71
    assert data["lon"] == -74.00
    assert "min_confidence" in data
    assert "use_gpu" in data

def test_update_settings(app):
    r = TestClient(app).put("/api/settings", json={"lat": 51.5, "lon": -0.1})
    assert r.status_code == 200
    settings = TestClient(app).get("/api/settings").json()
    assert settings["lat"] == 51.5

def test_partial_update_does_not_reset_other_fields(app):
    client = TestClient(app)
    client.put("/api/settings", json={"min_confidence": 0.80})
    r = client.get("/api/settings")
    assert r.json()["lat"] == 40.71   # unchanged
    assert r.json()["min_confidence"] == 0.80
```

- [ ] **Step 5: Write tests for alerts API**

Create `tests/api/test_alerts.py`:

```python
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
```

- [ ] **Step 6: Run tests — expect pass**

```bash
pytest tests/api/test_settings.py tests/api/test_alerts.py -v
```
Expected: `6 passed`

- [ ] **Step 7: Commit**

```bash
git add birdwatch/api/settings.py birdwatch/api/alerts.py birdwatch/api/clips.py \
        tests/api/test_settings.py tests/api/test_alerts.py
git commit -m "feat: settings, alert rules, and clip serving API"
```

---

## Task 9: Main Entrypoint & WebSocket

**Goal:** Implement `main.py` — creates the FastAPI app, wires all routers, runs the result_queue consumer loop (DB write + alert check + WebSocket broadcast), starts the ProcessManager and heartbeat, and handles graceful shutdown on SIGTERM.

**Files:**
- Create: `main.py`

**Acceptance Criteria:**
- [ ] `python main.py` starts uvicorn without errors (requires `config/config.yaml` to exist)
- [ ] `GET /api/detections` returns 200
- [ ] `WS /ws/detections` accepts a WebSocket connection
- [ ] Ctrl+C / SIGTERM triggers graceful shutdown (workers stop, no crash)

**Verify:** `python -c "from main import create_app; print('ok')"` -> `ok`

**Steps:**

- [ ] **Step 1: Implement main.py**

```python
from __future__ import annotations
import asyncio
import logging
import multiprocessing
import shutil
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, time as dt_time
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from birdwatch.alert_manager import AlertManager
from birdwatch.config import AppConfig, load_config
from birdwatch.database import Detection, init_db, insert_detection, list_alert_rules, list_cameras
from birdwatch.process_manager import ProcessManager
from birdwatch.api.detections import router as det_router
from birdwatch.api.cameras import router as cam_router
from birdwatch.api.settings import router as set_router
from birdwatch.api.alerts import router as alert_router
from birdwatch.api.clips import router as clip_router


# ── WebSocket connection manager ────────────────────────────────────────────

class ConnectionManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._connections:
            self._connections.remove(ws)

    async def broadcast(self, data: dict) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


# ── Background tasks ─────────────────────────────────────────────────────────

async def _result_consumer(
    result_queue: multiprocessing.Queue,
    alert_mgr: AlertManager,
    ws_manager: ConnectionManager,
    cfg: AppConfig,
) -> None:
    """Read detection results from inference workers and fan out to DB/alerts/WS."""
    logger = logging.getLogger("result_consumer")
    loop = asyncio.get_event_loop()
    base_url = f"http://{cfg.server.host}:{cfg.server.port}"

    while True:
        try:
            raw = await loop.run_in_executor(None, lambda: result_queue.get(timeout=1.0))
        except Exception:
            await asyncio.sleep(0.05)
            continue

        # Write to SQLite
        try:
            det = Detection(
                camera_id=raw["camera_id"],
                timestamp=raw["timestamp"],
                species_common=raw["species_common"],
                species_sci=raw["species_sci"],
                confidence=raw["confidence"],
                clip_path=raw["clip_path"],
                lat=raw.get("lat"),
                lon=raw.get("lon"),
            )
            insert_detection(det)
        except Exception as exc:
            logger.error("DB write failed: %s", exc)

        # Check alert rules
        try:
            rules = list_alert_rules()
            camera_names = {c["id"]: c["name"] for c in list_cameras()}
            camera_name = camera_names.get(raw["camera_id"], raw["camera_id"])
            await alert_mgr.check_and_dispatch(raw, rules, camera_name, base_url)
        except Exception as exc:
            logger.error("Alert check failed: %s", exc)

        # Broadcast via WebSocket (exclude raw bytes)
        payload = {k: v for k, v in raw.items() if k != "pcm_bytes"}
        await ws_manager.broadcast(payload)


async def _clip_cleanup(retention_days: int) -> None:
    """Run at 02:00 UTC daily — delete clip directories older than retention_days."""
    logger = logging.getLogger("clip_cleanup")
    while True:
        now = datetime.utcnow()
        next_run = datetime.combine(now.date(), dt_time(2, 0))
        if next_run <= now:
            next_run += timedelta(days=1)
        await asyncio.sleep((next_run - now).total_seconds())

        clips_dir = Path("data/clips")
        if not clips_dir.exists():
            continue
        cutoff = (datetime.utcnow() - timedelta(days=retention_days)).strftime("%Y-%m-%d")
        for date_dir in clips_dir.rglob("????-??-??"):
            if date_dir.is_dir() and date_dir.name < cutoff:
                shutil.rmtree(date_dir, ignore_errors=True)
                logger.info("Removed old clips: %s", date_dir)


def _setup_logging(level: str) -> None:
    Path("logs").mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(name)-20s %(levelname)s %(message)s")
    root = logging.getLogger()
    root.setLevel(getattr(logging, level, logging.INFO))
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(sh)
    fh = TimedRotatingFileHandler("logs/birdwatch.log", when="midnight", backupCount=30)
    fh.setFormatter(fmt)
    root.addHandler(fh)


# ── App factory ──────────────────────────────────────────────────────────────

def create_app() -> FastAPI:

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        cfg = load_config()
        _setup_logging(cfg.logging.level)
        init_db()

        ws_manager = ConnectionManager()
        alert_mgr = AlertManager()
        infer_queue: multiprocessing.Queue = multiprocessing.Queue()
        result_queue: multiprocessing.Queue = multiprocessing.Queue()

        proc_mgr = ProcessManager(cfg, infer_queue, result_queue)
        proc_mgr.start_all()
        await proc_mgr.start_heartbeat()

        # Store shared state for API routers
        app.state.cfg = cfg
        app.state.process_manager = proc_mgr
        app.state.ws_manager = ws_manager

        consumer_task = asyncio.create_task(
            _result_consumer(result_queue, alert_mgr, ws_manager, cfg)
        )
        cleanup_task = asyncio.create_task(
            _clip_cleanup(cfg.alerts.retention_days)
        )

        yield  # ── app is running ──

        consumer_task.cancel()
        cleanup_task.cancel()
        proc_mgr.stop_all()

    fastapi_app = FastAPI(title="BirdWatch", lifespan=lifespan)

    fastapi_app.include_router(det_router)
    fastapi_app.include_router(cam_router)
    fastapi_app.include_router(set_router)
    fastapi_app.include_router(alert_router)
    fastapi_app.include_router(clip_router)

    @fastapi_app.websocket("/ws/detections")
    async def ws_detections(websocket: WebSocket):
        mgr: Optional[ConnectionManager] = getattr(
            fastapi_app.state, "ws_manager", None
        )
        if mgr is None:
            await websocket.close()
            return
        await mgr.connect(websocket)
        try:
            while True:
                await websocket.receive_text()  # keepalive — client can send pings
        except WebSocketDisconnect:
            mgr.disconnect(websocket)

    # Serve dashboard — mount AFTER API routes so /api/* is not shadowed
    fastapi_app.mount(
        "/", StaticFiles(directory="birdwatch/static", html=True), name="static"
    )

    return fastapi_app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    cfg = load_config()
    uvicorn.run(app, host=cfg.server.host, port=cfg.server.port)
```

- [ ] **Step 2: Verify import**

```bash
python3 -c "from main import create_app; print('ok')"
```
Expected: `ok`

- [ ] **Step 3: Smoke-test startup (requires config/config.yaml)**

```bash
cp config/config.example.yaml config/config.yaml
# Edit config/config.yaml: update lat/lon and camera URLs
python3 main.py &
sleep 3
curl -s http://localhost:8080/api/detections | python3 -m json.tool
kill %1
```
Expected: `[]` (empty list — no detections yet)

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: main entrypoint, WebSocket, result consumer, graceful shutdown"
```

---

## Task 10: Dashboard Frontend

**Goal:** Implement the browser-based dashboard as static files served by FastAPI. Four tabs: Live (WebSocket detections + camera status), History (searchable/paginated table), Cameras (CRUD), Settings (config + alert rules). No build step — plain HTML, Alpine.js, HTMX loaded from CDN.

**Files:**
- Create: `birdwatch/static/index.html`
- Create: `birdwatch/static/app.js`
- Create: `birdwatch/static/style.css`

**Acceptance Criteria:**
- [ ] `http://<server>:8080/` loads without console errors
- [ ] Live tab updates instantly when a bird is detected (WebSocket push)
- [ ] History tab loads paginated detections and plays audio via `<audio>` element
- [ ] Cameras tab can add/remove a camera via the API
- [ ] Settings tab reads and writes config values
- [ ] Works in Chrome and Firefox from another machine on the LAN

**Verify:** Manual — open browser to `http://<server-ip>:8080/` from a LAN machine

**Steps:**

- [ ] **Step 1: Create birdwatch/static/style.css**

```css
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: system-ui, -apple-system, sans-serif;
  background: #0f1117;
  color: #e2e8f0;
  min-height: 100vh;
}

header {
  background: #1a1f2e;
  border-bottom: 1px solid #2d3748;
  padding: 1rem 1.5rem;
  display: flex;
  align-items: center;
  gap: 2rem;
}

header h1 { font-size: 1.25rem; color: #68d391; letter-spacing: .05em; }

nav button {
  background: none;
  border: none;
  color: #a0aec0;
  padding: .5rem 1rem;
  cursor: pointer;
  border-radius: 6px;
  font-size: .9rem;
  transition: background .15s, color .15s;
}
nav button.active, nav button:hover {
  background: #2d3748;
  color: #e2e8f0;
}

main { padding: 1.5rem; max-width: 1200px; margin: 0 auto; }

/* Cards */
.card {
  background: #1a1f2e;
  border: 1px solid #2d3748;
  border-radius: 8px;
  padding: 1rem;
  margin-bottom: 1rem;
}
.card h2 { font-size: 1rem; color: #a0aec0; margin-bottom: .75rem; }

/* Camera status grid */
.cam-grid {
  display: flex;
  flex-wrap: wrap;
  gap: .5rem;
  margin-bottom: 1rem;
}
.cam-badge {
  padding: .3rem .75rem;
  border-radius: 999px;
  font-size: .8rem;
  font-weight: 600;
}
.cam-badge.connected  { background: #22543d; color: #68d391; }
.cam-badge.reconnecting { background: #744210; color: #f6ad55; }
.cam-badge.error      { background: #742a2a; color: #fc8181; }
.cam-badge.starting   { background: #2d3748; color: #a0aec0; }
.cam-badge.disabled   { background: #2d3748; color: #718096; }

/* Detection feed */
.detection-row {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: .5rem 0;
  border-bottom: 1px solid #2d3748;
  font-size: .9rem;
}
.detection-row:last-child { border-bottom: none; }
.conf-badge {
  font-weight: 700;
  font-size: .8rem;
  padding: .2rem .5rem;
  border-radius: 4px;
  background: #2d3748;
  color: #68d391;
  min-width: 3.5rem;
  text-align: center;
}
.species { flex: 1; font-weight: 600; }
.cam-label { color: #a0aec0; font-size: .8rem; }
.time-label { color: #718096; font-size: .75rem; min-width: 6rem; }
button.play-btn {
  background: #2d3748;
  border: none;
  color: #68d391;
  border-radius: 4px;
  padding: .2rem .6rem;
  cursor: pointer;
  font-size: .85rem;
}
button.play-btn:hover { background: #4a5568; }

/* Forms */
.form-row { display: flex; gap: .75rem; margin-bottom: .75rem; flex-wrap: wrap; }
.form-row label { display: flex; flex-direction: column; gap: .25rem; font-size: .85rem; color: #a0aec0; }
input, select {
  background: #2d3748;
  border: 1px solid #4a5568;
  border-radius: 6px;
  color: #e2e8f0;
  padding: .4rem .75rem;
  font-size: .9rem;
  min-width: 180px;
}
input:focus, select:focus { outline: 2px solid #68d391; border-color: transparent; }
button.btn {
  background: #276749;
  color: #fff;
  border: none;
  border-radius: 6px;
  padding: .45rem 1rem;
  cursor: pointer;
  font-size: .9rem;
}
button.btn:hover { background: #2f855a; }
button.btn.danger { background: #742a2a; }
button.btn.danger:hover { background: #9b2c2c; }

/* Table */
table { width: 100%; border-collapse: collapse; font-size: .88rem; }
th { color: #a0aec0; font-weight: 600; text-align: left; padding: .5rem .75rem; border-bottom: 1px solid #2d3748; }
td { padding: .45rem .75rem; border-bottom: 1px solid #1e2535; }
tr:hover td { background: #1e2535; }

.pagination { display: flex; gap: .5rem; margin-top: 1rem; }
.pagination button { background: #2d3748; border: none; color: #a0aec0; border-radius: 4px; padding: .3rem .75rem; cursor: pointer; }
.pagination button.active { background: #276749; color: #fff; }

/* Alert */
.alert-success { background: #1c4532; border: 1px solid #276749; border-radius: 6px; padding: .5rem 1rem; font-size: .85rem; margin-bottom: .75rem; }
```

- [ ] **Step 2: Create birdwatch/static/app.js**

```javascript
// BirdWatch Dashboard — Alpine.js + Fetch + WebSocket

document.addEventListener('alpine:init', () => {
  Alpine.data('dashboard', () => ({
    tab: 'live',

    // Live
    liveDetections: [],
    cameraStatuses: {},
    wsConnected: false,
    MAX_LIVE: 50,

    // History
    historyRows: [],
    histPage: 0,
    histLimit: 25,
    histFilter: { camera_id: '', species: '', date_from: '', date_to: '' },

    // Cameras
    cameras: [],
    newCam: { id: '', name: '', stream_url: '', enabled: true },
    camSaved: false,

    // Settings
    settings: {},
    settingsSaved: false,

    // Alert rules
    alertRules: [],
    newRule: { species_filter: '', min_confidence: 0.70, method: 'webhook',
               config: '', cooldown_mins: 10, enabled: true },
    ruleSaved: false,

    async init() {
      await this.loadCameraStatuses();
      await this.loadCameras();
      await this.loadSettings();
      await this.loadAlertRules();
      this.connectWS();
      setInterval(() => this.loadCameraStatuses(), 10000);
    },

    connectWS() {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      const ws = new WebSocket(`${proto}://${location.host}/ws/detections`);
      ws.onopen = () => { this.wsConnected = true; };
      ws.onclose = () => {
        this.wsConnected = false;
        setTimeout(() => this.connectWS(), 3000);
      };
      ws.onmessage = (e) => {
        const det = JSON.parse(e.data);
        this.liveDetections.unshift(det);
        if (this.liveDetections.length > this.MAX_LIVE)
          this.liveDetections.pop();
      };
    },

    async loadCameraStatuses() {
      const r = await fetch('/api/cameras');
      const cams = await r.json();
      this.cameraStatuses = {};
      for (const c of cams) this.cameraStatuses[c.id] = c.status || 'unknown';
    },

    async loadHistory() {
      const p = new URLSearchParams({ limit: this.histLimit, offset: this.histPage * this.histLimit });
      if (this.histFilter.camera_id) p.set('camera_id', this.histFilter.camera_id);
      if (this.histFilter.species) p.set('species', this.histFilter.species);
      if (this.histFilter.date_from) p.set('date_from', this.histFilter.date_from);
      if (this.histFilter.date_to) p.set('date_to', this.histFilter.date_to);
      const r = await fetch(`/api/detections?${p}`);
      this.historyRows = await r.json();
    },

    histPrev() { if (this.histPage > 0) { this.histPage--; this.loadHistory(); } },
    histNext() { this.histPage++; this.loadHistory(); },

    playClip(clipPath) {
      const audio = new Audio(`/api/clips/${clipPath}`);
      audio.play();
    },

    formatConf(c) { return `${(c * 100).toFixed(0)}%`; },

    formatTime(ts) {
      try { return new Date(ts).toLocaleTimeString(); } catch { return ts; }
    },

    // Cameras tab
    async loadCameras() {
      const r = await fetch('/api/cameras');
      this.cameras = await r.json();
    },

    async saveCamera() {
      const r = await fetch('/api/cameras', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(this.newCam),
      });
      if (r.ok) {
        this.newCam = { id: '', name: '', stream_url: '', enabled: true };
        this.camSaved = true;
        await this.loadCameras();
        setTimeout(() => { this.camSaved = false; }, 3000);
      }
    },

    async deleteCamera(id) {
      if (!confirm(`Delete camera ${id}?`)) return;
      await fetch(`/api/cameras/${id}`, { method: 'DELETE' });
      await this.loadCameras();
    },

    // Settings tab
    async loadSettings() {
      const r = await fetch('/api/settings');
      this.settings = await r.json();
    },

    async saveSettings() {
      const r = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(this.settings),
      });
      if (r.ok) {
        this.settingsSaved = true;
        setTimeout(() => { this.settingsSaved = false; }, 3000);
      }
    },

    // Alert rules
    async loadAlertRules() {
      const r = await fetch('/api/alerts/rules');
      this.alertRules = await r.json();
    },

    async saveRule() {
      let configObj = {};
      try { configObj = JSON.parse(this.newRule.config || '{}'); } catch { alert('Config must be valid JSON'); return; }
      const body = { ...this.newRule, config: configObj };
      const r = await fetch('/api/alerts/rules', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (r.ok) {
        this.newRule = { species_filter: '', min_confidence: 0.70, method: 'webhook',
                         config: '', cooldown_mins: 10, enabled: true };
        this.ruleSaved = true;
        await this.loadAlertRules();
        setTimeout(() => { this.ruleSaved = false; }, 3000);
      }
    },

    async deleteRule(id) {
      await fetch(`/api/alerts/rules/${id}`, { method: 'DELETE' });
      await this.loadAlertRules();
    },

    cameraStatusClass(status) {
      const map = { connected: 'connected', reconnecting: 'reconnecting',
                    error: 'error', disabled: 'disabled', starting: 'starting' };
      return map[status] || 'starting';
    },
  }));
});
```

- [ ] **Step 3: Create birdwatch/static/index.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>BirdWatch</title>
  <link rel="stylesheet" href="/style.css">
  <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
  <script defer src="/app.js"></script>
</head>
<body x-data="dashboard" x-init="init()">

<header>
  <h1>BirdWatch</h1>
  <nav>
    <button :class="tab==='live'?'active':''"     @click="tab='live'">Live</button>
    <button :class="tab==='history'?'active':''"  @click="tab='history'; loadHistory()">History</button>
    <button :class="tab==='cameras'?'active':''"  @click="tab='cameras'">Cameras</button>
    <button :class="tab==='settings'?'active':''" @click="tab='settings'">Settings</button>
  </nav>
  <span style="margin-left:auto;font-size:.75rem;color:#718096">
    WS: <span :style="wsConnected?'color:#68d391':'color:#fc8181'"
              x-text="wsConnected?'connected':'reconnecting'"></span>
  </span>
</header>

<main>

  <!-- ── LIVE ────────────────────────────────────────────────────────────── -->
  <template x-if="tab==='live'">
    <div>
      <div class="card">
        <h2>Camera Status</h2>
        <div class="cam-grid">
          <template x-for="[id, status] in Object.entries(cameraStatuses)" :key="id">
            <span class="cam-badge" :class="cameraStatusClass(status)">
              <span x-text="id"></span> &bull; <span x-text="status"></span>
            </span>
          </template>
          <span x-show="Object.keys(cameraStatuses).length===0" style="color:#718096;font-size:.85rem">
            No cameras connected
          </span>
        </div>
      </div>
      <div class="card">
        <h2>Recent Detections</h2>
        <template x-for="det in liveDetections" :key="det.timestamp+det.camera_id+det.species_common">
          <div class="detection-row">
            <span class="conf-badge" x-text="formatConf(det.confidence)"></span>
            <span class="species" x-text="det.species_common"></span>
            <span class="cam-label" x-text="det.camera_id"></span>
            <span class="time-label" x-text="formatTime(det.timestamp)"></span>
            <button class="play-btn" @click="playClip(det.clip_path)">&#9654; Play</button>
          </div>
        </template>
        <p x-show="liveDetections.length===0" style="color:#718096;font-size:.85rem;padding:.5rem 0">
          Waiting for detections...
        </p>
      </div>
    </div>
  </template>

  <!-- ── HISTORY ──────────────────────────────────────────────────────────── -->
  <template x-if="tab==='history'">
    <div>
      <div class="card">
        <h2>Filter</h2>
        <div class="form-row">
          <label>Camera ID<input x-model="histFilter.camera_id" placeholder="all cameras"></label>
          <label>Species<input x-model="histFilter.species" placeholder="e.g. Robin"></label>
          <label>From<input type="date" x-model="histFilter.date_from"></label>
          <label>To<input type="date" x-model="histFilter.date_to"></label>
          <button class="btn" style="align-self:flex-end" @click="histPage=0;loadHistory()">Search</button>
        </div>
      </div>
      <div class="card">
        <table>
          <thead>
            <tr>
              <th>Time</th><th>Species</th><th>Confidence</th><th>Camera</th><th>Clip</th>
            </tr>
          </thead>
          <tbody>
            <template x-for="row in historyRows" :key="row.id">
              <tr>
                <td x-text="formatTime(row.timestamp)"></td>
                <td x-text="row.species_common"></td>
                <td x-text="formatConf(row.confidence)"></td>
                <td x-text="row.camera_id"></td>
                <td><button class="play-btn" @click="playClip(row.clip_path)">&#9654;</button></td>
              </tr>
            </template>
            <tr x-show="historyRows.length===0">
              <td colspan="5" style="color:#718096;text-align:center;padding:1rem">No detections found</td>
            </tr>
          </tbody>
        </table>
        <div class="pagination">
          <button @click="histPrev()" :disabled="histPage===0">Prev</button>
          <span style="padding:.3rem .5rem;font-size:.85rem" x-text="'Page '+(histPage+1)"></span>
          <button @click="histNext()" :disabled="historyRows.length < histLimit">Next</button>
        </div>
      </div>
    </div>
  </template>

  <!-- ── CAMERAS ──────────────────────────────────────────────────────────── -->
  <template x-if="tab==='cameras'">
    <div>
      <div class="card">
        <h2>Add Camera</h2>
        <div x-show="camSaved" class="alert-success">Camera saved.</div>
        <div class="form-row">
          <label>ID (slug)<input x-model="newCam.id" placeholder="front-yard"></label>
          <label>Display Name<input x-model="newCam.name" placeholder="Front Yard"></label>
          <label>Stream URL<input x-model="newCam.stream_url" placeholder="rtsp:// or rtsps://" style="min-width:300px"></label>
          <label style="justify-content:flex-end">
            Enabled
            <input type="checkbox" x-model="newCam.enabled" style="min-width:auto;width:auto">
          </label>
          <button class="btn" style="align-self:flex-end" @click="saveCamera()">Add / Update</button>
        </div>
      </div>
      <div class="card">
        <h2>Configured Cameras</h2>
        <table>
          <thead><tr><th>ID</th><th>Name</th><th>URL</th><th>Status</th><th></th></tr></thead>
          <tbody>
            <template x-for="cam in cameras" :key="cam.id">
              <tr>
                <td x-text="cam.id"></td>
                <td x-text="cam.name"></td>
                <td style="font-size:.8rem;color:#a0aec0" x-text="cam.stream_url"></td>
                <td><span class="cam-badge" :class="cameraStatusClass(cam.status)" x-text="cam.status"></span></td>
                <td><button class="btn danger" @click="deleteCamera(cam.id)">Delete</button></td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </div>
  </template>

  <!-- ── SETTINGS ─────────────────────────────────────────────────────────── -->
  <template x-if="tab==='settings'">
    <div>
      <div class="card">
        <h2>Location & BirdNET</h2>
        <div x-show="settingsSaved" class="alert-success">Settings saved.</div>
        <div class="form-row">
          <label>Latitude<input type="number" step="0.0001" x-model.number="settings.lat"></label>
          <label>Longitude<input type="number" step="0.0001" x-model.number="settings.lon"></label>
          <label>Min Confidence (0–1)<input type="number" step="0.01" min="0" max="1" x-model.number="settings.min_confidence"></label>
          <label>Overlap (seconds)<input type="number" step="0.5" min="0" max="2.9" x-model.number="settings.overlap"></label>
          <label>Inference Workers<input type="number" min="1" max="16" x-model.number="settings.workers"></label>
          <label style="justify-content:flex-end">
            Use GPU
            <input type="checkbox" x-model="settings.use_gpu" style="min-width:auto;width:auto">
          </label>
        </div>
        <button class="btn" @click="saveSettings()">Save Settings</button>
      </div>
      <div class="card">
        <h2>Alert Rules</h2>
        <div x-show="ruleSaved" class="alert-success">Rule saved.</div>
        <div class="form-row">
          <label>Species filter (blank = all)<input x-model="newRule.species_filter" placeholder="Northern Cardinal"></label>
          <label>Min confidence<input type="number" step="0.01" min="0" max="1" x-model.number="newRule.min_confidence"></label>
          <label>Method
            <select x-model="newRule.method">
              <option value="webhook">Webhook</option>
              <option value="email">Email</option>
              <option value="pushover">Pushover</option>
            </select>
          </label>
          <label>Config JSON<input x-model="newRule.config" placeholder='{"url":"https://..."}' style="min-width:300px"></label>
          <label>Cooldown (mins)<input type="number" min="1" x-model.number="newRule.cooldown_mins"></label>
          <button class="btn" style="align-self:flex-end" @click="saveRule()">Add Rule</button>
        </div>
        <table>
          <thead><tr><th>Species</th><th>Confidence</th><th>Method</th><th>Cooldown</th><th>Status</th><th></th></tr></thead>
          <tbody>
            <template x-for="rule in alertRules" :key="rule.id">
              <tr>
                <td x-text="rule.species_filter || 'All species'"></td>
                <td x-text="formatConf(rule.min_confidence)"></td>
                <td x-text="rule.method"></td>
                <td x-text="rule.cooldown_mins + ' min'"></td>
                <td x-text="rule.enabled ? 'Enabled' : 'Disabled'"></td>
                <td><button class="btn danger" @click="deleteRule(rule.id)">Delete</button></td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </div>
  </template>

</main>
</body>
</html>
```

- [ ] **Step 4: Test in browser**

```bash
# Start the app (requires config/config.yaml)
python3 main.py
```
Then open `http://<server-ip>:8080/` from a browser on the LAN.

Verify:
- All four tabs load without errors
- Live tab shows "Waiting for detections..." and "No cameras connected"
- History tab shows empty table with working filter form
- Cameras tab: add a test camera, verify it appears in the table
- Settings tab: change a value, save, reload page — value persists

- [ ] **Step 5: Commit**

```bash
git add birdwatch/static/
git commit -m "feat: dashboard frontend with Live/History/Cameras/Settings tabs"
```

---

## Task 11: Systemd Service & README

**Goal:** Write the systemd unit file for 24/7 operation and a README with complete installation and usage instructions for Ubuntu Server.

**Files:**
- Create: `birdwatch.service`
- Create: `README.md`

**Acceptance Criteria:**
- [ ] `sudo systemctl start birdwatch` starts the service
- [ ] `sudo systemctl enable birdwatch` enables start-on-boot
- [ ] `journalctl -u birdwatch -f` shows live log output
- [ ] README covers: prerequisites, installation, config, running, upgrading

**Verify:** `systemctl status birdwatch` -> `active (running)`

**Steps:**

- [ ] **Step 1: Create birdwatch.service**

```ini
[Unit]
Description=BirdWatch — Real-Time Bird Detection
After=network.target

[Service]
Type=simple
User=birdwatch
WorkingDirectory=/opt/birdwatch
ExecStart=/opt/birdwatch/venv/bin/python main.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Create README.md**

```markdown
# BirdWatch

24/7 bird audio detection from RTSP/RTSPS camera streams using BirdNET-Analyzer.
Detections are stored locally with audio clips and viewable via a web dashboard.

## Prerequisites

Ubuntu Server 22.04+

```bash
sudo apt update
sudo apt install -y ffmpeg python3.11 python3.11-venv git
```

For GPU support (optional — Quadro K2100M / other OpenCL-capable card):
```bash
sudo apt install -y nvidia-opencl-dev ocl-icd-opencl-dev
```

## Installation

```bash
# Create a dedicated user and install directory
sudo useradd -r -s /bin/false birdwatch
sudo mkdir -p /opt/birdwatch
sudo git clone <repo-url> /opt/birdwatch
sudo chown -R birdwatch:birdwatch /opt/birdwatch

# Create Python virtual environment and install dependencies
cd /opt/birdwatch
sudo -u birdwatch python3.11 -m venv venv
sudo -u birdwatch venv/bin/pip install -r requirements.txt
```

## Configuration

```bash
cp config/config.example.yaml config/config.yaml
nano config/config.yaml
```

Key settings to update:

| Setting | Description |
|---------|-------------|
| `location.lat` / `.lon` | Your coordinates (improves species accuracy) |
| `cameras[].stream_url` | Your RTSP (`rtsp://`) or RTSPS (`rtsps://`) camera URL |
| `birdnet.min_confidence` | Detection threshold (0.70 recommended) |
| `birdnet.use_gpu` | Set `true` to enable OpenCL GPU acceleration |
| `inference.workers` | Number of BirdNET workers (4 recommended for CPU) |

### UniFi Camera URLs

UniFi cameras use RTSPS on port 7441 by default:
```
rtsps://<camera-ip>:7441/<channel>
```
The self-signed TLS certificate is handled automatically.

## Running

### As a systemd service (recommended)

```bash
sudo cp birdwatch.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable birdwatch    # start on boot
sudo systemctl start birdwatch     # start now
```

Useful commands:
```bash
sudo systemctl stop birdwatch      # stop
sudo systemctl restart birdwatch   # restart
sudo systemctl status birdwatch    # check status
journalctl -u birdwatch -f         # live logs
```

### Manually (development)

```bash
source venv/bin/activate
python main.py
```

## Dashboard

Open `http://<server-ip>:8080/` from any browser on your LAN.

| Tab | Description |
|-----|-------------|
| Live | Real-time detection feed + camera status indicators |
| History | Searchable/paginated detection log with audio playback |
| Cameras | Add, edit, or remove RTSP/RTSPS streams |
| Settings | Adjust location, confidence threshold, GPU mode, alert rules |

## Alert Rules

Supported notification methods:

**Webhook** (works with ntfy.sh, Home Assistant, Slack, Discord):
```json
{"url": "https://ntfy.sh/my-bird-alerts"}
```

**Email**:
```json
{"smtp_host": "smtp.gmail.com", "smtp_port": 587,
 "username": "you@gmail.com", "password": "app-password", "to": "you@gmail.com"}
```

**Pushover**:
```json
{"app_token": "YOUR_APP_TOKEN", "user_key": "YOUR_USER_KEY"}
```

## Storage

| Location | Contents |
|----------|----------|
| `data/birdwatch.db` | All detection records (kept permanently) |
| `data/clips/` | WAV audio clips (pruned after `retention_days`) |
| `logs/birdwatch.log` | Rolling log (30 days retained) |

## Upgrading

```bash
cd /opt/birdwatch
sudo git pull
sudo -u birdwatch venv/bin/pip install -r requirements.txt
sudo systemctl restart birdwatch
```
```

- [ ] **Step 3: Install and enable the service**

```bash
sudo cp birdwatch.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable birdwatch
sudo systemctl start birdwatch
sudo systemctl status birdwatch
```
Expected: `active (running)` in the output.

- [ ] **Step 4: Verify logs flow to journald**

```bash
journalctl -u birdwatch -n 20
```
Expected: startup log lines from uvicorn and the process manager.

- [ ] **Step 5: Final test run — run full test suite**

```bash
pytest tests/ -v
```
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add birdwatch.service README.md
git commit -m "chore: systemd service unit and installation README"
```

---

## Self-Review Notes

- All spec sections covered: audio pipeline (Task 3), inference pipeline (Task 4), storage/config (Tasks 1–2), API (Tasks 7–8), dashboard (Task 10), alerts (Task 5), process supervision (Task 6), systemd deployment (Task 11), RTSP+RTSPS (Task 3).
- RTSPS support is automatic — detected from URL scheme, no extra config flag needed.
- GPU toggle is a single `use_gpu: false` → `use_gpu: true` change in `config.yaml`.
- `birdnetlib` is only imported inside worker subprocesses — unit tests run without it installed.
- SQLite WAL mode enabled in `init_db()` (Task 2).
- Clip path function `build_clip_path` is the single source of truth — used in inference_worker and verifiable in tests.
