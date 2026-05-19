# BirdWatch — RTSP + BirdNET Real-Time Bird Detection System
**Date:** 2026-05-18
**Status:** Approved

---

## Overview

BirdWatch is a 24/7 bird audio detection system that pulls RTSP audio streams from an arbitrary number of cameras (UniFi or otherwise), runs detections through BirdNET-Analyzer locally, stores results, and exposes a local web dashboard for live monitoring, history review, audio clip playback, and full configuration management.

---

## Hardware & Environment

| Item | Spec |
|------|------|
| CPU | Intel Core i7-4910MQ (4 cores / 8 threads) |
| RAM | 32 GB |
| GPU | NVIDIA Quadro K2100M — 2 GB GDDR5 VRAM (Kepler, CUDA compute 3.0) |
| OS | Ubuntu Server (no GUI) |
| Access | Web dashboard from another machine on the LAN |

**GPU note:** The Quadro K2100M is Kepler architecture (compute 3.0). Modern TensorFlow 2.x requires compute >= 3.5, so TF GPU mode is unsupported. BirdNET-Analyzer's TFLite path can use the OpenCL GPU delegate, which Kepler supports. In practice, CPU mode with 4 workers is the recommended default for reliability. GPU is enabled by a single config flag.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Main Process (FastAPI)                  │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │  REST API   │  │  WebSocket   │  │   Alert Manager   │  │
│  │ (config/    │  │  (live push) │  │ (rules + dispatch)│  │
│  │  history)   │  │              │  │                   │  │
│  └─────────────┘  └──────────────┘  └───────────────────┘  │
│           │               ▲                               │
│           ▼               │                               │
│       SQLite DB ◄─── Result Queue ───► Alert Manager     │
└───────────────────────────┼────────────────────────────────┘
                            │
          ┌─────────────────┘
          │
┌─────────▼──────────┐              ┌───────────┴──────────┐
│  Inference Workers │              │   Camera Workers     │
│  (pool of N procs) │◄─────────────│  (1 proc per stream) │
│                    │  Infer Queue │                      │
│  BirdNET-Analyzer  │              │  FFmpeg → PCM chunks │
│  GPU or CPU mode   │              │  + metadata          │
└────────────────────┘              └──────────────────────┘
                                             ▲
                                    RTSP Streams (N cameras)
```

**Process layout:**
- **1 main process** — FastAPI web server, SQLite writes, WebSocket broadcasts, alert dispatch, process supervision
- **N camera worker processes** — one per enabled camera; each runs FFmpeg as a subprocess to pull RTSP audio, chunks it into 3-second segments, pushes chunks to the inference queue
- **M inference worker processes** — configurable pool (default 4 CPU); each loads one BirdNET model instance, pulls from inference queue, writes results to result queue

**IPC:** Two shared `multiprocessing.Queue` instances:
- `infer_queue` — camera workers → inference workers (audio chunks + metadata)
- `result_queue` — inference workers → main process (detection results); the main process reads this single queue to handle both SQLite writes and alert rule evaluation

---

## Audio Pipeline

Each camera worker process:

1. Spawns FFmpeg as a subprocess. Supports both `rtsp://` and `rtsps://` (RTSP over TLS) URLs. RTSPS is the default for UniFi cameras (port 7441). For RTSPS, `-tls_verify 0` is added automatically since UniFi uses self-signed certificates.
2. Resamples audio to **48 kHz mono PCM 16-bit** (BirdNET required format)
3. Reads raw bytes into a rolling buffer
4. Every **3 seconds** of audio (configurable overlap, default 1.5s), packages a chunk:
   ```
   { camera_id, stream_url, timestamp, raw_pcm_bytes }
   ```
5. Puts the chunk onto `infer_queue`

**Overlap:** Configurable seconds of overlap between consecutive chunks (default 1.5s) to prevent detections at chunk boundaries from being missed. Each camera produces one inference job per `(3 - overlap)` seconds.

**Protocol support:** Both `rtsp://` and `rtsps://` URLs are supported. When the URL starts with `rtsps://`, FFmpeg is invoked with `-tls_verify 0` to accept self-signed TLS certificates (standard for UniFi cameras on port 7441). No config flag is needed — protocol is inferred from the URL scheme.

**Reconnect logic:** On FFmpeg subprocess death (network blip, camera reboot), the worker catches the error and retries with exponential backoff: 2s → 4s → 8s → 16s → 60s (max). Dashboard shows camera status as `reconnecting` during this time.

**Backpressure:** If `infer_queue` exceeds a configurable max size (default 100), oldest items are dropped with a warning logged. Prevents memory bloat when inference is slower than capture.

---

## Inference Pipeline

Each inference worker process:

1. On startup, loads one BirdNET-Analyzer model instance via `birdnetlib`
2. Checks GPU availability; uses TFLite OpenCL delegate if `use_gpu: true` and OpenCL is available; falls back to CPU automatically with a logged warning if not
3. Loops pulling jobs from `infer_queue`, runs analysis, pushes results to `result_queue`

**Per-job processing:**
```
receive job from infer_queue
  → wrap PCM bytes as io.BytesIO (no temp disk I/O)
  → run birdnetlib Analyzer with configured lat/lon + min_confidence
  → for each detection above threshold:
      build detection record { camera_id, timestamp, species_common,
        species_scientific, confidence, clip_path, lat, lon }
  → push all detections to result_queue
  → if detections found: save audio chunk to permanent clip path
  → if no detections: discard audio bytes
```

**Permanent clip path:**
```
data/clips/{camera_id}/{YYYY-MM-DD}/{HH-MM-SS}_{species_slug}_{confidence}.wav
```
Example: `data/clips/front-yard/2026-05-18/14-32-10_northern_cardinal_0.87.wav`

**Worker pool configuration:**

| Mode | Config | Notes |
|------|--------|-------|
| CPU (default) | `use_gpu: false`, `workers: 4` | Matches i7-4910MQ physical cores; ~1–2 GB RAM per worker |
| GPU only | `use_gpu: true`, `workers: 1` | TFLite OpenCL on K2100M; falls back to CPU if OpenCL unavailable |
| Mixed | `use_gpu: true`, `workers: 4` | Worker 0 loads with GPU delegate; workers 1–3 load CPU-only. Best throughput if GPU delegate initialises successfully. |

`birdnetlib` is used as the Python wrapper around BirdNET-Analyzer, providing the `Analyzer` and `Recording` classes. This avoids manual TFLite session management.

---

## Storage

### SQLite Database
Location: `data/birdwatch.db`
WAL mode enabled to prevent corruption on unclean shutdown.

```sql
-- Configured RTSP streams
cameras (
  id          TEXT PRIMARY KEY,   -- e.g. "front-yard"
  name        TEXT NOT NULL,      -- display name
  stream_url  TEXT NOT NULL,      -- rtsp://...
  enabled     BOOLEAN NOT NULL DEFAULT 1,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
)

-- Every bird detection
detections (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  camera_id       TEXT NOT NULL,
  timestamp       DATETIME NOT NULL,
  species_common  TEXT NOT NULL,
  species_sci     TEXT NOT NULL,
  confidence      REAL NOT NULL,
  clip_path       TEXT NOT NULL,
  lat             REAL,
  lon             REAL
)

-- Configurable alert rules
alert_rules (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  species_filter  TEXT,           -- NULL = all species
  min_confidence  REAL NOT NULL DEFAULT 0.70,
  method          TEXT NOT NULL,  -- "email" | "webhook" | "pushover"
  config          TEXT NOT NULL,  -- JSON: method-specific settings
  cooldown_mins   INTEGER NOT NULL DEFAULT 10,
  enabled         BOOLEAN NOT NULL DEFAULT 1
)
```

### File Layout
```
birdwatch/
├── main.py
├── config/
│   └── config.yaml
├── birdwatch/
│   ├── config.py            # Pydantic config loader + validator
│   ├── process_manager.py   # Supervises camera + inference workers
│   ├── camera_worker.py     # RTSP → audio chunks (subprocess)
│   ├── inference_worker.py  # BirdNET analysis (subprocess)
│   ├── alert_manager.py     # Rule matching + notification dispatch
│   ├── database.py          # SQLite schema + query helpers
│   ├── api/
│   │   ├── detections.py
│   │   ├── cameras.py
│   │   ├── settings.py
│   │   └── alerts.py
│   └── static/
│       ├── index.html
│       ├── app.js
│       └── style.css
├── data/                    # gitignored — created at runtime
│   ├── birdwatch.db
│   └── clips/
│       └── {camera_id}/
│           └── {YYYY-MM-DD}/
│               └── {HH-MM-SS}_{species}_{confidence}.wav
├── logs/                    # gitignored
│   └── birdwatch.log
├── requirements.txt
├── birdwatch.service        # systemd unit file
└── README.md
```

---

## Configuration

Single source of truth: `config/config.yaml`

```yaml
server:
  host: 0.0.0.0
  port: 8080

location:
  lat: 40.7128   # decimal degrees
  lon: -74.0060  # decimal degrees

birdnet:
  min_confidence: 0.70   # 0.0–1.0, detections below this are discarded
  overlap: 1.5           # seconds of chunk overlap (0 to disable)
  use_gpu: false         # set to true to enable TFLite OpenCL GPU delegate
                         # requires: nvidia-opencl-dev, compatible driver
                         # falls back to CPU automatically if unavailable

inference:
  workers: 4             # number of BirdNET worker processes
                         # recommended: 4 (CPU), 1 (GPU), or 1+3 (mixed)
  queue_max: 100         # max infer_queue depth before dropping old chunks

cameras:
  - id: front-yard
    name: Front Yard
    stream_url: rtsp://192.168.1.10:554/stream1   # standard RTSP
    enabled: true
  - id: back-fence
    name: Back Fence
    stream_url: rtsps://192.168.1.11:7441/stream1  # RTSPS (UniFi default, TLS, self-signed cert)
    enabled: true

alerts:
  retention_days: 90     # days to keep .wav clip files on disk

logging:
  level: INFO            # DEBUG | INFO | WARNING | ERROR
```

Config is loaded at startup via Pydantic. Settings updated via the dashboard API trigger a hot-reload for threshold/location changes; `inference.workers` changes restart the inference pool gracefully (drains in-flight jobs first).

---

## Web API & Dashboard

**Tech stack:** FastAPI + Uvicorn (backend), vanilla JS + HTMX + Alpine.js (frontend). No Node.js or npm required. Frontend served as static files by FastAPI.

### REST Endpoints

```
# Detections
GET  /api/detections          # paginated; filter: camera_id, species, date_from, date_to
GET  /api/detections/summary  # species counts (today + all-time), detections per camera

# Cameras
GET    /api/cameras           # list all + live status (connected/reconnecting/error/disabled)
POST   /api/cameras           # add camera
PUT    /api/cameras/{id}      # update camera
DELETE /api/cameras/{id}      # remove camera

# Settings
GET  /api/settings            # current config values (lat/lon, threshold, GPU, workers)
PUT  /api/settings            # update + hot-reload

# Alert rules
GET    /api/alerts/rules
POST   /api/alerts/rules
PUT    /api/alerts/rules/{id}
DELETE /api/alerts/rules/{id}

# Audio playback
GET  /api/clips/{path:path}   # stream .wav file

# Live push
WS   /ws/detections           # WebSocket — server pushes detection JSON on each event
```

### Dashboard Layout (tab-based SPA)

**Live tab:**
- Camera status grid (connected / reconnecting / error)
- Real-time detection feed — species, confidence, camera, timestamp, play button
- Updates instantly via WebSocket (no polling)

**History tab:**
- Searchable, filterable table (camera, species, date range, confidence)
- Audio clip playback inline
- Pagination

**Cameras tab:**
- Add / edit / remove RTSP streams
- Enable / disable per camera without removing
- Live connection test button

**Settings tab:**
- Location (lat/lon)
- BirdNET confidence threshold
- GPU toggle + worker count
- Alert rules (add/edit/delete rules, configure methods)

---

## Alert System

Alert Manager runs as a background asyncio task in the main process. Each detection from `result_queue` is checked against all enabled rules before database write.

**Rule matching:**
```
for each enabled rule:
  species matches if rule.species_filter is NULL (all)
                  or rule.species_filter == detection.species_common
  fires if species matches AND detection.confidence >= rule.min_confidence
        AND cooldown not active for (species, camera_id) pair
```

**Cooldown:** In-memory dict keyed by `(camera_id, species_common)`. Default 10 minutes, configurable per rule. Resets on service restart.

**Notification methods:**

| Method | Required config fields |
|--------|----------------------|
| `email` | `smtp_host`, `smtp_port`, `username`, `password`, `to` |
| `webhook` | `url`, optional `secret` (HMAC-SHA256 signature header) |
| `pushover` | `app_token`, `user_key` |

**Alert payload (all methods):**
```json
{
  "camera": "Front Yard",
  "camera_id": "front-yard",
  "species": "Northern Cardinal",
  "species_scientific": "Cardinalis cardinalis",
  "confidence": 0.91,
  "timestamp": "2026-05-18T14:32:10",
  "clip_url": "http://192.168.1.x:8080/api/clips/front-yard/2026-05-18/14-32-10_northern_cardinal_0.91.wav"
}
```

Alert dispatch failures (network error, bad credentials) are logged but do not block the detection pipeline.

**Clip retention:** A background task runs at 02:00 daily, deleting `.wav` files older than `alerts.retention_days`. Detection records in SQLite are kept permanently; only files on disk are pruned.

---

## Error Handling & Reliability

| Component | Failure | Recovery |
|-----------|---------|----------|
| Camera worker | RTSP disconnect | Exponential backoff reconnect: 2s → 4s → 8s → 16s → 60s max |
| Camera worker | FFmpeg crash | ProcessManager detects via `is_alive()`, restarts immediately |
| Inference worker | Model load fail | Logs error + exits; ProcessManager spawns replacement |
| Inference worker | Inference exception | Logs + skips chunk; worker continues |
| GPU delegate | OpenCL unavailable | Logs warning, falls back to CPU automatically |
| Main process | SQLite write fail | Logs error; detection still broadcast via WebSocket |
| Alert dispatch | Network/SMTP fail | Logs error; no retry (prevents pipeline blocking) |
| Infer queue | Overflows max depth | Oldest chunks dropped; warning logged |

**ProcessManager:** Background asyncio task in main process. Checks `process.is_alive()` every 5 seconds for all workers. Restarts dead processes up to a configurable `max_restarts` (default 10) before marking as permanently failed. Failed cameras appear as `error` status in the dashboard.

**Logging:** Python `logging` to stdout (captured by journald) and `logs/birdwatch.log` with daily rotation, 30-day file retention. Level configurable in `config.yaml`.

**Graceful shutdown:** On `SIGTERM`, main process signals all workers to finish current job and exit. In-flight inference jobs complete; queue is flushed.

**SQLite WAL mode:** Prevents database corruption on unclean shutdown.

---

## Systemd Deployment

`birdwatch.service`:
```ini
[Unit]
Description=BirdWatch Bird Detection Service
After=network.target

[Service]
Type=simple
User=birdwatch
WorkingDirectory=/opt/birdwatch
ExecStart=/opt/birdwatch/venv/bin/python main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Commands:**
```bash
sudo systemctl start birdwatch      # start service
sudo systemctl stop birdwatch       # stop service
sudo systemctl enable birdwatch     # start on boot
sudo systemctl status birdwatch     # check status
journalctl -u birdwatch -f          # live logs
```

---

## Dependencies

```
fastapi
uvicorn[standard]
birdnetlib          # BirdNET-Analyzer Python wrapper
pydantic            # config validation
aiofiles            # async file serving
websockets          # WebSocket support (bundled with uvicorn[standard])
```

System packages (Ubuntu):
```
ffmpeg
python3.11
python3.11-venv
```

Optional for GPU:
```
nvidia-opencl-dev
ocl-icd-opencl-dev
```

---

## Testing Approach

- **Unit tests:** Config loader (valid/invalid YAML), alert rule matching logic, clip path generation, backpressure drop logic
- **Integration tests:** Camera worker → infer_queue flow using a pre-recorded `.wav` file as a mock RTSP source (FFmpeg can serve a file as RTSP); inference worker → result_queue flow with a known bird audio sample
- **End-to-end:** Spin up the full stack against a mock RTSP server, verify a detection appears in SQLite and is broadcast via WebSocket
- **Manual:** Dashboard UI testing from a browser on the LAN
