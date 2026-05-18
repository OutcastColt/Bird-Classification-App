from __future__ import annotations
import asyncio
import hashlib
import hmac
import json
import logging
import smtplib
import time
from email.mime.text import MIMEText
from typing import Optional
from urllib import request as urllib_request


class AlertManager:
    def __init__(self) -> None:
        self._cooldowns: dict[tuple[str, str], float] = {}
        self.logger = logging.getLogger("alert_manager")

    def _on_cooldown(self, camera_id: str, species: str, cooldown_mins: int) -> bool:
        last = self._cooldowns.get((camera_id, species))
        return last is not None and (time.monotonic() - last) < cooldown_mins * 60

    def _set_cooldown(self, camera_id: str, species: str) -> None:
        self._cooldowns[(camera_id, species)] = time.monotonic()

    async def check_and_dispatch(
        self,
        detection: dict,
        rules: list[dict],
        camera_name: str,
        base_url: str,
    ) -> None:
        for rule in rules:
            if not rule.get("enabled"):
                continue
            sf = rule.get("species_filter")
            if sf and sf != detection["species_common"]:
                continue
            if detection["confidence"] < rule["min_confidence"]:
                continue
            cooldown = rule.get("cooldown_mins", 10)
            if self._on_cooldown(detection["camera_id"], detection["species_common"], cooldown):
                continue
            self._set_cooldown(detection["camera_id"], detection["species_common"])

            payload = {
                "camera": camera_name,
                "camera_id": detection["camera_id"],
                "species": detection["species_common"],
                "species_scientific": detection["species_sci"],
                "confidence": detection["confidence"],
                "timestamp": detection["timestamp"],
                "clip_url": f"{base_url}/api/clips/{detection['clip_path']}",
            }
            config = rule.get("config", {})
            if isinstance(config, str):
                config = json.loads(config)
            try:
                loop = asyncio.get_event_loop()
                method = rule["method"]
                if method == "email":
                    await loop.run_in_executor(None, self._dispatch_email, payload, config)
                elif method == "webhook":
                    await loop.run_in_executor(None, self._dispatch_webhook, payload, config)
                elif method == "pushover":
                    await loop.run_in_executor(None, self._dispatch_pushover, payload, config)
            except Exception as exc:
                self.logger.error("Alert dispatch (%s) failed: %s", rule["method"], exc)

    def _dispatch_email(self, payload: dict, config: dict) -> None:
        msg = MIMEText(
            f"Bird detected: {payload['species']} "
            f"({payload['confidence']:.0%} confidence)\n"
            f"Camera: {payload['camera']}\n"
            f"Time: {payload['timestamp']}\n"
            f"Clip: {payload['clip_url']}"
        )
        msg["Subject"] = f"BirdWatch: {payload['species']} detected"
        msg["From"] = config["username"]
        msg["To"] = config["to"]
        with smtplib.SMTP(config["smtp_host"], config["smtp_port"]) as s:
            s.starttls()
            s.login(config["username"], config["password"])
            s.send_message(msg)

    def _dispatch_webhook(self, payload: dict, config: dict) -> None:
        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if secret := config.get("secret"):
            sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            headers["X-BirdWatch-Signature"] = f"sha256={sig}"
        req = urllib_request.Request(
            config["url"], data=body, headers=headers, method="POST"
        )
        with urllib_request.urlopen(req, timeout=10):
            pass

    def _dispatch_pushover(self, payload: dict, config: dict) -> None:
        body = json.dumps({
            "token": config["app_token"],
            "user": config["user_key"],
            "title": f"BirdWatch: {payload['species']}",
            "message": (
                f"{payload['camera']} — {payload['confidence']:.0%} confidence\n"
                f"{payload['timestamp']}"
            ),
            "url": payload["clip_url"],
            "url_title": "Play clip",
        }).encode()
        req = urllib_request.Request(
            "https://api.pushover.net/1/messages.json",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib_request.urlopen(req, timeout=10):
            pass
