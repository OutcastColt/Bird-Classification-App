from __future__ import annotations
from fastapi import APIRouter, Query
import birdwatch.database as dbmod

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
    return dbmod.list_detections(
        db_path=dbmod.DB_PATH,
        camera_id=camera_id,
        species=species,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )


@router.get("/detections/summary")
def get_summary():
    return dbmod.get_detection_summary(db_path=dbmod.DB_PATH)
