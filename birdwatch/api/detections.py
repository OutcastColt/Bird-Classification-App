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
    limit: int = Query(50, ge=1, le=2000),
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
def get_summary(local_date: str | None = Query(default=None)):
    """local_date: YYYY-MM-DD in the browser's timezone, used for the 'today' count."""
    return dbmod.get_detection_summary(db_path=dbmod.DB_PATH, local_date=local_date)


@router.get("/detections/species")
def get_detected_species():
    """All distinct species seen, ordered by detection count descending."""
    with dbmod.get_connection(dbmod.DB_PATH) as conn:
        rows = conn.execute(
            "SELECT species_common, species_sci, COUNT(*) c "
            "FROM detections GROUP BY species_common ORDER BY c DESC"
        ).fetchall()
    return [dict(r) for r in rows]
