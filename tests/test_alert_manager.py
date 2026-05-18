import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from birdwatch.alert_manager import AlertManager

DETECTION = {
    "camera_id": "front-yard",
    "timestamp": "2026-05-18T14:32:10",
    "species_common": "Northern Cardinal",
    "species_sci": "Cardinalis cardinalis",
    "confidence": 0.91,
    "clip_path": "data/clips/front-yard/2026-05-18/clip.wav",
    "lat": 38.89,
    "lon": -77.03,
}

WEBHOOK_RULE = {
    "id": 1,
    "species_filter": None,
    "min_confidence": 0.70,
    "method": "webhook",
    "config": {"url": "https://example.com/hook"},
    "cooldown_mins": 10,
    "enabled": True,
}

@pytest.mark.asyncio
async def test_rule_matches_all_species():
    mgr = AlertManager()
    dispatched = []
    mgr._dispatch_webhook = lambda p, c: dispatched.append(p)
    await mgr.check_and_dispatch(DETECTION, [WEBHOOK_RULE], "Front Yard", "http://localhost:8080")
    assert len(dispatched) == 1

@pytest.mark.asyncio
async def test_rule_species_filter_match():
    mgr = AlertManager()
    dispatched = []
    rule = {**WEBHOOK_RULE, "species_filter": "Northern Cardinal"}
    mgr._dispatch_webhook = lambda p, c: dispatched.append(p)
    await mgr.check_and_dispatch(DETECTION, [rule], "Front Yard", "http://localhost:8080")
    assert len(dispatched) == 1

@pytest.mark.asyncio
async def test_rule_species_filter_no_match():
    mgr = AlertManager()
    dispatched = []
    rule = {**WEBHOOK_RULE, "species_filter": "American Robin"}
    mgr._dispatch_webhook = lambda p, c: dispatched.append(p)
    await mgr.check_and_dispatch(DETECTION, [rule], "Front Yard", "http://localhost:8080")
    assert dispatched == []

@pytest.mark.asyncio
async def test_rule_confidence_below_threshold():
    mgr = AlertManager()
    dispatched = []
    rule = {**WEBHOOK_RULE, "min_confidence": 0.95}
    mgr._dispatch_webhook = lambda p, c: dispatched.append(p)
    await mgr.check_and_dispatch(DETECTION, [rule], "Front Yard", "http://localhost:8080")
    assert dispatched == []

@pytest.mark.asyncio
async def test_cooldown_suppresses_second_detection():
    mgr = AlertManager()
    dispatched = []
    rule = {**WEBHOOK_RULE, "cooldown_mins": 10}
    mgr._dispatch_webhook = lambda p, c: dispatched.append(p)
    await mgr.check_and_dispatch(DETECTION, [rule], "Front Yard", "http://localhost:8080")
    await mgr.check_and_dispatch(DETECTION, [rule], "Front Yard", "http://localhost:8080")
    assert len(dispatched) == 1  # second is suppressed

@pytest.mark.asyncio
async def test_disabled_rule_does_not_fire():
    mgr = AlertManager()
    dispatched = []
    rule = {**WEBHOOK_RULE, "enabled": False}
    mgr._dispatch_webhook = lambda p, c: dispatched.append(p)
    await mgr.check_and_dispatch(DETECTION, [rule], "Front Yard", "http://localhost:8080")
    assert dispatched == []
