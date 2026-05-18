from __future__ import annotations
from fastapi import APIRouter, Request
from pathlib import Path
from pydantic import BaseModel
from typing import Optional
import yaml

router = APIRouter(prefix="/api", tags=["settings"])
_CONFIG_PATH = Path("config/config.yaml")


def _save_config(cfg) -> None:
    """Write the current in-memory config back to config.yaml."""
    data = {
        "server": {"host": cfg.server.host, "port": cfg.server.port},
        "location": {"lat": cfg.location.lat, "lon": cfg.location.lon},
        "birdnet": {
            "min_confidence": cfg.birdnet.min_confidence,
            "overlap": cfg.birdnet.overlap,
            "use_gpu": cfg.birdnet.use_gpu,
        },
        "inference": {
            "workers": cfg.inference.workers,
            "queue_max": cfg.inference.queue_max,
        },
        "cameras": [
            {"id": c.id, "name": c.name,
             "stream_url": c.stream_url, "enabled": c.enabled}
            for c in cfg.cameras
        ],
        "alerts": {"retention_days": cfg.alerts.retention_days},
        "logging": {"level": cfg.logging.level},
    }
    with open(_CONFIG_PATH, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


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
    _save_config(cfg)
    return {"ok": True}
