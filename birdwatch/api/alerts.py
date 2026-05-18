from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import birdwatch.database as dbmod
from birdwatch.database import AlertRule

router = APIRouter(prefix="/api", tags=["alerts"])


class AlertRuleBody(BaseModel):
    species_filter: Optional[str] = None
    min_confidence: float = 0.70
    method: str
    config: dict
    cooldown_mins: int = 10
    enabled: bool = True


@router.get("/alerts/rules")
def get_rules():
    return dbmod.list_alert_rules(db_path=dbmod.DB_PATH)


@router.post("/alerts/rules", status_code=201)
def create_rule(body: AlertRuleBody):
    rule = AlertRule(
        species_filter=body.species_filter,
        min_confidence=body.min_confidence,
        method=body.method,
        config=body.config,
        cooldown_mins=body.cooldown_mins,
        enabled=body.enabled,
    )
    rule_id = dbmod.insert_alert_rule(rule, db_path=dbmod.DB_PATH)
    return {"id": rule_id}


@router.put("/alerts/rules/{rule_id}")
def update_rule(rule_id: int, body: AlertRuleBody):
    if not dbmod.update_alert_rule(rule_id, body.model_dump(), db_path=dbmod.DB_PATH):
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"ok": True}


@router.delete("/alerts/rules/{rule_id}")
def delete_rule(rule_id: int):
    if not dbmod.delete_alert_rule(rule_id, db_path=dbmod.DB_PATH):
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"ok": True}
