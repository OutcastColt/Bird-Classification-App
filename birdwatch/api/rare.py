from __future__ import annotations
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
import birdwatch.database as dbmod

router = APIRouter(prefix="/api", tags=["rare"])


class RareSpeciesBody(BaseModel):
    species_common: str
    min_confidence: float = Field(default=0.75, ge=0.0, le=1.0)

    @classmethod
    def validate_species(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("species_common must not be empty")
        return v.strip()


@router.get("/rare-species")
def get_watchlist():
    return dbmod.list_rare_species(db_path=dbmod.DB_PATH)


@router.post("/rare-species", status_code=201)
def add_to_watchlist(body: RareSpeciesBody):
    species = body.species_common.strip()
    if not species:
        raise HTTPException(status_code=422, detail="species_common must not be empty")
    dbmod.upsert_rare_species(species, body.min_confidence, db_path=dbmod.DB_PATH)
    return {"ok": True}


@router.delete("/rare-species/{species}")
def remove_from_watchlist(species: str):
    if not dbmod.delete_rare_species(species, db_path=dbmod.DB_PATH):
        raise HTTPException(status_code=404, detail="Species not on watchlist")
    return {"ok": True}


@router.get("/rare-alerts")
def get_rare_alerts(
    hours: int = Query(default=24, ge=1, le=168),
    limit: int = Query(default=100, ge=1, le=500),
):
    return dbmod.get_rare_alerts(hours=hours, limit=limit, db_path=dbmod.DB_PATH)
