from __future__ import annotations
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from birdwatch.config import CameraConfig
import birdwatch.database as dbmod

router = APIRouter(prefix="/api", tags=["cameras"])


class CameraBody(BaseModel):
    id: str
    name: str
    stream_url: str
    enabled: bool = True


def _camera_config(body: CameraBody) -> CameraConfig:
    return CameraConfig(id=body.id, name=body.name,
                        stream_url=body.stream_url, enabled=body.enabled)


@router.get("/cameras")
def get_cameras(request: Request):
    cameras = dbmod.list_cameras(db_path=dbmod.DB_PATH)
    pm = getattr(request.app.state, "process_manager", None)
    statuses = pm.get_camera_statuses() if pm else {}
    for cam in cameras:
        if not cam["enabled"]:
            cam["status"] = "disabled"
        else:
            cam["status"] = statuses.get(cam["id"], "starting")
    return cameras


@router.post("/cameras", status_code=201)
def add_camera(body: CameraBody, request: Request):
    dbmod.upsert_camera(body.id, body.name, body.stream_url, body.enabled, dbmod.DB_PATH)
    pm = getattr(request.app.state, "process_manager", None)
    if pm:
        pm.add_camera_worker(_camera_config(body))
    return {"ok": True}


@router.put("/cameras/{camera_id}")
def update_camera(camera_id: str, body: CameraBody, request: Request):
    if body.id != camera_id:
        raise HTTPException(
            status_code=422,
            detail=f"Body id '{body.id}' does not match path camera_id '{camera_id}'",
        )
    dbmod.upsert_camera(camera_id, body.name, body.stream_url, body.enabled, dbmod.DB_PATH)
    pm = getattr(request.app.state, "process_manager", None)
    if pm:
        pm.add_camera_worker(_camera_config(body))
    return {"ok": True}


@router.delete("/cameras/{camera_id}")
def remove_camera(camera_id: str, request: Request):
    if not dbmod.delete_camera(camera_id, dbmod.DB_PATH):
        raise HTTPException(status_code=404, detail="Camera not found")
    pm = getattr(request.app.state, "process_manager", None)
    if pm:
        pm.remove_camera_worker(camera_id)
    return {"ok": True}
