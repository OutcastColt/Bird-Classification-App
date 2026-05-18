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
            insert_detection(det)
        except Exception as exc:
            logger.error("DB write failed: %s", exc)

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
        init_db()

        # Seed cameras from config.yaml into the database so they appear in the UI
        for cam in cfg.cameras:
            dbmod.upsert_camera(cam.id, cam.name, cam.stream_url, cam.enabled,
                                db_path=dbmod.DB_PATH)

        ws_manager = ConnectionManager()
        alert_mgr = AlertManager()
        infer_queue: multiprocessing.Queue = multiprocessing.Queue(
            maxsize=cfg.inference.queue_max
        )
        result_queue: multiprocessing.Queue = multiprocessing.Queue()

        proc_mgr = ProcessManager(cfg, infer_queue, result_queue)
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

        yield  # ── app is running ──

        consumer_task.cancel()
        cleanup_task.cancel()
        await asyncio.gather(consumer_task, cleanup_task, return_exceptions=True)
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
                await websocket.receive_text()
        except (WebSocketDisconnect, Exception):
            pass
        finally:
            mgr.disconnect(websocket)

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
