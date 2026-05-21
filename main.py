from __future__ import annotations
import asyncio
import logging
import multiprocessing
import shutil
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, time as dt_time, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from birdwatch.alert_manager import AlertManager
from birdwatch.config import AppConfig, load_config
from birdwatch.database import Detection, init_db, insert_detection
import birdwatch.database as dbmod
from birdwatch.process_manager import ProcessManager
from birdwatch.api.detections import router as det_router
from birdwatch.api.cameras import router as cam_router
from birdwatch.api.settings import router as set_router
from birdwatch.api.alerts import router as alert_router
from birdwatch.api.clips import router as clip_router
from birdwatch.api.rare      import router as rare_router
from birdwatch.api.taxonomy  import router as taxonomy_router


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


# ── Background tasks ──────────────────────────────────────────────────────

async def _result_consumer(
    result_queue: multiprocessing.Queue,
    alert_mgr: AlertManager,
    ws_manager: ConnectionManager,
    cfg: AppConfig,
) -> None:
    """Read detection results from inference workers and fan out to DB/alerts/WS."""
    logger = logging.getLogger("result_consumer")
    loop = asyncio.get_running_loop()
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
            det_id = insert_detection(det)
            raw["id"] = det_id   # include DB id in WS payload for dedup
        except Exception as exc:
            logger.error("DB write failed: %s", exc)

        # Lazily fetch taxonomy from GBIF for new species (fire-and-forget)
        if raw.get("species_sci") and not dbmod.get_taxonomy(raw["species_sci"], db_path=dbmod.DB_PATH):
            asyncio.create_task(_fetch_taxonomy(raw["species_sci"]))

        # Check rare-species watchlist and flag if matched
        try:
            rare_map = dbmod.get_rare_species_map(db_path=dbmod.DB_PATH)
            threshold = rare_map.get(raw["species_common"])
            if threshold is not None and raw["confidence"] >= threshold:
                raw["rare"] = True
                logger.warning(
                    "RARE DETECTION  %-30s  conf=%.0f%%  camera=%s",
                    raw["species_common"], raw["confidence"] * 100, raw["camera_id"],
                )
        except Exception as exc:
            logger.error("Rare-species check failed: %s", exc)

        # Log detection to journald / birdwatch.log
        logger.info(
            "DETECTION  %-30s  %-25s  conf=%.0f%%  camera=%s",
            raw["species_common"],
            raw["species_sci"],
            raw["confidence"] * 100,
            raw["camera_id"],
        )

        # Check alert rules
        try:
            rules = dbmod.list_alert_rules(db_path=dbmod.DB_PATH)
            camera_names = {c["id"]: c["name"] for c in dbmod.list_cameras(db_path=dbmod.DB_PATH)}
            camera_name = camera_names.get(raw["camera_id"], raw["camera_id"])
            await alert_mgr.check_and_dispatch(raw, rules, camera_name, base_url)
        except Exception as exc:
            logger.error("Alert check failed: %s", exc)

        # Broadcast via WebSocket (exclude raw PCM bytes)
        payload = {k: v for k, v in raw.items() if k != "pcm_bytes"}
        await ws_manager.broadcast(payload)


async def _clip_cleanup(retention_days: int) -> None:
    """Run at 02:00 UTC daily — delete clip dirs older than retention_days."""
    logger = logging.getLogger("clip_cleanup")
    while True:
        now = datetime.now(timezone.utc)
        next_run = datetime.combine(now.date(), dt_time(2, 0), tzinfo=timezone.utc)
        if next_run <= now:
            next_run += timedelta(days=1)
        await asyncio.sleep((next_run - now).total_seconds())

        clips_dir = Path("data/clips")
        if not clips_dir.exists():
            continue
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).strftime("%Y-%m-%d")
        for date_dir in clips_dir.rglob("????-??-??"):
            if date_dir.is_dir() and date_dir.name < cutoff:
                shutil.rmtree(date_dir, ignore_errors=True)
                logger.info("Removed old clips: %s", date_dir)


def _apply_db_settings(cfg) -> None:
    """Override config values with any settings the user saved via the dashboard.

    config.yaml provides initial defaults; the database is the source of truth
    for any values changed at runtime so they survive service restarts.
    """
    log = logging.getLogger("startup")
    try:
        saved = dbmod.get_all_settings(db_path=dbmod.DB_PATH)
        if not saved:
            return
        if "location.lat"           in saved: cfg.location.lat           = float(saved["location.lat"])
        if "location.lon"           in saved: cfg.location.lon           = float(saved["location.lon"])
        if "birdnet.min_confidence" in saved: cfg.birdnet.min_confidence = float(saved["birdnet.min_confidence"])
        if "birdnet.overlap"        in saved: cfg.birdnet.overlap        = float(saved["birdnet.overlap"])
        if "birdnet.use_gpu"        in saved: cfg.birdnet.use_gpu        = saved["birdnet.use_gpu"] == "true"
        if "inference.workers"      in saved: cfg.inference.workers      = int(saved["inference.workers"])
        log.info("Applied %d runtime setting(s) from database", len(saved))
    except Exception as exc:
        log.warning("Could not apply DB settings overrides: %s", exc)


_taxonomy_pending: set[str] = set()   # species_sci currently being fetched


async def _fetch_taxonomy(species_sci: str) -> None:
    """Fetch Order/Family for a species from GBIF and cache in DB.
    Fire-and-forget — never blocks the detection pipeline.
    """
    if not species_sci or species_sci in _taxonomy_pending:
        return
    _taxonomy_pending.add(species_sci)
    try:
        import httpx
        genus = species_sci.split()[0]
        url   = (
            "https://api.gbif.org/v1/species/match"
            f"?name={species_sci.replace(' ', '+')}&class=Aves&verbose=false"
        )
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(url)
        if r.status_code == 200:
            d = r.json()
            if d.get("matchType") not in ("NONE", None):
                dbmod.upsert_taxonomy(
                    species_sci=species_sci,
                    genus=d.get("genus",  genus),
                    family=d.get("family", ""),
                    order=d.get("order",  ""),
                    db_path=dbmod.DB_PATH,
                )
                return
        # Fallback: store genus only so it appears in the chart
        dbmod.upsert_taxonomy(species_sci, genus, "", "", db_path=dbmod.DB_PATH)
    except Exception as exc:
        logging.getLogger("taxonomy").debug(
            "GBIF lookup failed for %s: %s", species_sci, exc
        )
        try:
            dbmod.upsert_taxonomy(
                species_sci, species_sci.split()[0], "", "",
                db_path=dbmod.DB_PATH,
            )
        except Exception:
            pass
    finally:
        _taxonomy_pending.discard(species_sci)


async def _audio_streamer(
    audio_queue: multiprocessing.Queue,
    audio_subs: dict,
) -> None:
    """Read PCM chunks from camera workers and broadcast to WebSocket subscribers."""
    logger = logging.getLogger("audio_streamer")
    loop   = asyncio.get_running_loop()
    while True:
        try:
            chunk = await loop.run_in_executor(None, lambda: audio_queue.get(timeout=0.5))
        except Exception:
            await asyncio.sleep(0.02)
            continue

        cam_id  = chunk["camera_id"]
        ws_set  = audio_subs.get(cam_id, set())
        if not ws_set:
            continue

        # Binary frame: [4-byte LE uint32 timestamp-len][timestamp UTF-8][Int16 PCM]
        ts_b = chunk["timestamp"].encode("utf-8")
        msg  = len(ts_b).to_bytes(4, "little") + ts_b + chunk["pcm"]

        dead = []
        for ws in list(ws_set):
            try:
                await ws.send_bytes(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            ws_set.discard(ws)
            logger.debug("Removed dead audio subscriber for %s", cam_id)


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


# ── App factory ───────────────────────────────────────────────────────────

def create_app() -> FastAPI:

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        cfg = load_config()
        _setup_logging(cfg.logging.level)

        if not shutil.which("ffmpeg"):
            logging.getLogger("startup").error(
                "ffmpeg not found in PATH. Install it with: "
                "sudo apt install -y ffmpeg"
            )

        init_db()

        # Apply any runtime settings overrides saved by the user via the dashboard.
        # These take precedence over config.yaml so changes survive service restarts.
        _apply_db_settings(cfg)

        # Seed cameras from config.yaml into the database so they appear in the UI
        for cam in cfg.cameras:
            dbmod.upsert_camera(cam.id, cam.name, cam.stream_url, cam.enabled,
                                db_path=dbmod.DB_PATH)

        # Replace cfg.cameras with the full database list so ProcessManager spawns
        # workers for ALL cameras (including any added/edited via the dashboard),
        # not just those in config.yaml.
        from birdwatch.config import CameraConfig as _CameraConfig
        cfg.cameras = [
            _CameraConfig(id=c["id"], name=c["name"],
                          stream_url=c["stream_url"], enabled=bool(c["enabled"]))
            for c in dbmod.list_cameras(db_path=dbmod.DB_PATH)
        ]
        logging.getLogger("startup").info(
            "Starting workers for %d camera(s) from database",
            sum(1 for c in cfg.cameras if c.enabled),
        )

        ws_manager = ConnectionManager()
        alert_mgr = AlertManager()
        infer_queue: multiprocessing.Queue = multiprocessing.Queue(
            maxsize=cfg.inference.queue_max
        )
        result_queue: multiprocessing.Queue = multiprocessing.Queue()
        audio_queue: multiprocessing.Queue = multiprocessing.Queue(maxsize=200)

        # Audio subscribers: { camera_id: set[WebSocket] }
        audio_subs: dict[str, set] = {}
        app.state.audio_subs = audio_subs

        proc_mgr = ProcessManager(cfg, infer_queue, result_queue, audio_queue)
        proc_mgr.start_all()
        await proc_mgr.start_heartbeat()

        app.state.cfg = cfg
        app.state.process_manager = proc_mgr
        app.state.ws_manager = ws_manager

        consumer_task = asyncio.create_task(
            _result_consumer(result_queue, alert_mgr, ws_manager, cfg)
        )
        cleanup_task = asyncio.create_task(
            _clip_cleanup(cfg.alerts.retention_days)
        )
        audio_task = asyncio.create_task(
            _audio_streamer(audio_queue, audio_subs)
        )

        yield  # ── app is running ──

        consumer_task.cancel()
        cleanup_task.cancel()
        audio_task.cancel()
        await asyncio.gather(consumer_task, cleanup_task, audio_task, return_exceptions=True)
        proc_mgr.stop_all()

    fastapi_app = FastAPI(title="BirdWatch", lifespan=lifespan)

    fastapi_app.include_router(det_router)
    fastapi_app.include_router(cam_router)
    fastapi_app.include_router(set_router)
    fastapi_app.include_router(alert_router)
    fastapi_app.include_router(clip_router)
    fastapi_app.include_router(rare_router)
    fastapi_app.include_router(taxonomy_router)

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
                await websocket.receive_text()
        except (WebSocketDisconnect, Exception):
            pass
        finally:
            mgr.disconnect(websocket)

    @fastapi_app.websocket("/ws/audio/{camera_id}")
    async def ws_audio(websocket: WebSocket, camera_id: str):
        """Stream raw PCM audio from a camera to the browser spectrogram."""
        await websocket.accept()
        subs = fastapi_app.state.audio_subs.setdefault(camera_id, set())
        subs.add(websocket)
        try:
            while True:
                await websocket.receive_text()   # keepalive ping from client
        except Exception:
            subs.discard(websocket)

    # Mount static files AFTER API routes so /api/* is not shadowed
    fastapi_app.mount(
        "/", StaticFiles(directory="birdwatch/static", html=True), name="static"
    )

    return fastapi_app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    cfg = load_config()
    uvicorn.run(app, host=cfg.server.host, port=cfg.server.port)
