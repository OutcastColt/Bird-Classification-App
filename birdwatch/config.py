from __future__ import annotations
from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel, Field, field_validator


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080


class LocationConfig(BaseModel):
    lat: float
    lon: float


class BirdnetConfig(BaseModel):
    min_confidence: float = Field(default=0.70, ge=0.0, le=1.0)
    overlap: float = Field(default=1.5, ge=0.0, lt=3.0)
    use_gpu: bool = False


class InferenceConfig(BaseModel):
    workers: int = Field(default=4, ge=1)
    queue_max: int = Field(default=100, ge=10)


class CameraConfig(BaseModel):
    id: str
    name: str
    stream_url: str
    enabled: bool = True


class AlertsConfig(BaseModel):
    retention_days: int = Field(default=90, ge=1)


class LoggingConfig(BaseModel):
    level: str = "INFO"

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR"}
        if v.upper() not in valid:
            raise ValueError(f"level must be one of {valid}")
        return v.upper()


class AppConfig(BaseModel):
    server: ServerConfig = ServerConfig()
    location: LocationConfig
    birdnet: BirdnetConfig = BirdnetConfig()
    inference: InferenceConfig = InferenceConfig()
    cameras: list[CameraConfig] = []
    alerts: AlertsConfig = AlertsConfig()
    logging: LoggingConfig = LoggingConfig()


def load_config(path: str | Path = "config/config.yaml") -> AppConfig:
    with open(path) as f:
        data = yaml.safe_load(f)
    return AppConfig(**data)
