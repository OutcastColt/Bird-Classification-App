from __future__ import annotations
from fastapi import APIRouter, Query
import birdwatch.database as dbmod

router = APIRouter(prefix="/api", tags=["taxonomy"])


@router.get("/detections/taxonomy")
def get_taxonomy_hierarchy(
    hours:          int       = Query(default=24, ge=1, le=168),
    camera_id:      str | None = Query(default=None),
    min_confidence: float     = Query(default=0.0, ge=0.0, le=1.0),
):
    """Return BirdNET detections as a D3-ready hierarchy for circle-packing."""
    return dbmod.get_taxonomy_hierarchy(
        hours=hours, camera_id=camera_id,
        min_confidence=min_confidence, db_path=dbmod.DB_PATH
    )
