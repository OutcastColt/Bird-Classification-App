from __future__ import annotations
from fastapi import APIRouter, Query
import birdwatch.database as dbmod

router = APIRouter(prefix="/api", tags=["taxonomy"])


@router.get("/detections/taxonomy")
def get_taxonomy_hierarchy(
    hours:     int      = Query(default=24, ge=1, le=168),
    camera_id: str | None = Query(default=None),
):
    """Return BirdNET detections as a D3-ready hierarchy for circle-packing.

    Structure:
      {name:"Birds", children:[
        {name:"Passeriformes", children:[
          {name:"Cardinalidae", children:[
            {name:"Northern Cardinal", species_sci:"...", value:47, avg_conf:0.91}
          ]}
        ]}
      ]}
    """
    return dbmod.get_taxonomy_hierarchy(
        hours=hours, camera_id=camera_id, db_path=dbmod.DB_PATH
    )
