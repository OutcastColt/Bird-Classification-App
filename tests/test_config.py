import os
import tempfile
import pytest
from birdwatch.config import load_config

VALID_YAML = """
server:
  host: 0.0.0.0
  port: 8080
location:
  lat: 38.8977
  lon: -77.0365
birdnet:
  min_confidence: 0.70
  overlap: 1.5
  use_gpu: false
inference:
  workers: 4
  queue_max: 100
cameras:
  - id: front-yard
    name: Front Yard
    stream_url: rtsp://192.168.1.10:554/stream1
    enabled: true
alerts:
  retention_days: 90
logging:
  level: INFO
"""

def _tmp_cfg(content: str) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    f.write(content)
    f.close()
    return f.name

def test_load_valid_config():
    path = _tmp_cfg(VALID_YAML)
    try:
        cfg = load_config(path)
        assert cfg.location.lat == 38.8977
        assert cfg.location.lon == -77.0365
        assert cfg.birdnet.min_confidence == 0.70
        assert cfg.inference.workers == 4
        assert len(cfg.cameras) == 1
        assert cfg.cameras[0].id == "front-yard"
    finally:
        os.unlink(path)

def test_camera_enabled_default():
    path = _tmp_cfg(VALID_YAML)
    try:
        cfg = load_config(path)
        assert cfg.cameras[0].enabled is True
    finally:
        os.unlink(path)

def test_invalid_confidence_raises():
    path = _tmp_cfg(VALID_YAML.replace("min_confidence: 0.70", "min_confidence: 1.5"))
    try:
        with pytest.raises(Exception):
            load_config(path)
    finally:
        os.unlink(path)

def test_invalid_log_level_raises():
    path = _tmp_cfg(VALID_YAML.replace("level: INFO", "level: VERBOSE"))
    try:
        with pytest.raises(Exception):
            load_config(path)
    finally:
        os.unlink(path)

def test_missing_location_raises():
    yaml = "server:\n  host: 0.0.0.0\n  port: 8080\n"
    path = _tmp_cfg(yaml)
    try:
        with pytest.raises(Exception):
            load_config(path)
    finally:
        os.unlink(path)
