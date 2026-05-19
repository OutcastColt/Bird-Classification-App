from __future__ import annotations
import asyncio
import logging
import multiprocessing
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from birdwatch.config import AppConfig, CameraConfig


class WorkerStatus(str, Enum):
    STARTING = "starting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"
    DISABLED = "disabled"


@dataclass
class _WorkerEntry:
    key: str                            # "camera:<id>" or "inference:<index>"
    process: multiprocessing.Process
    stop_event: multiprocessing.Event
    restart_count: int = 0
    status: WorkerStatus = WorkerStatus.STARTING


class ProcessManager:
    MAX_RESTARTS = 10
    HEARTBEAT_INTERVAL = 5.0

    def __init__(
        self,
        cfg: AppConfig,
        infer_queue: multiprocessing.Queue,
        result_queue: multiprocessing.Queue,
    ) -> None:
        self.cfg = cfg
        self.infer_queue = infer_queue
        self.result_queue = result_queue
        self._workers: dict[str, _WorkerEntry] = {}
        self._heartbeat_task: Optional[asyncio.Task] = None
        self.logger = logging.getLogger("process_manager")

    def _spawn_camera(self, camera: CameraConfig) -> _WorkerEntry:
        from birdwatch.camera_worker import run_camera_worker
        stop = multiprocessing.Event()
        # Signature: run_camera_worker(camera_id, stream_url, infer_queue,
        #   overlap_seconds, lat, lon, min_confidence, stop_event)
        # Note: queue_max was removed in Task 3; backpressure is handled via
        # queue.Full on a queue created with maxsize by the caller.
        proc = multiprocessing.Process(
            target=run_camera_worker,
            args=(
                camera.id,
                camera.stream_url,
                self.infer_queue,
                self.cfg.birdnet.overlap,
                self.cfg.location.lat,
                self.cfg.location.lon,
                self.cfg.birdnet.min_confidence,
                stop,
            ),
            daemon=True,
            name=f"camera-{camera.id}",
        )
        proc.start()
        return _WorkerEntry(key=f"camera:{camera.id}", process=proc, stop_event=stop)

    def _spawn_inference(self, index: int) -> _WorkerEntry:
        from birdwatch.inference_worker import run_inference_worker
        stop = multiprocessing.Event()
        proc = multiprocessing.Process(
            target=run_inference_worker,
            args=(index, self.infer_queue, self.result_queue,
                  self.cfg.birdnet.use_gpu, stop),
            daemon=True,
            name=f"inference-{index}",
        )
        proc.start()
        return _WorkerEntry(key=f"inference:{index}", process=proc, stop_event=stop)

    def start_all(self) -> None:
        for cam in self.cfg.cameras:
            if cam.enabled:
                entry = self._spawn_camera(cam)
                self._workers[entry.key] = entry
                self.logger.info("Started camera worker: %s", cam.id)

        for i in range(self.cfg.inference.workers):
            entry = self._spawn_inference(i)
            self._workers[entry.key] = entry
            self.logger.info("Started inference worker: %d", i)

    def stop_all(self) -> None:
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
        for entry in self._workers.values():
            entry.stop_event.set()
        for entry in self._workers.values():
            entry.process.join(timeout=10)
            if entry.process.is_alive():
                entry.process.terminate()
                self.logger.warning("Force-killed worker: %s", entry.key)
        self._workers.clear()
        self.logger.info("All workers stopped")

    async def start_heartbeat(self) -> None:
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(self.HEARTBEAT_INTERVAL)
            for key, entry in list(self._workers.items()):
                if entry.process.is_alive():
                    continue
                if entry.restart_count >= self.MAX_RESTARTS:
                    if entry.status != WorkerStatus.ERROR:
                        entry.status = WorkerStatus.ERROR
                        self.logger.error(
                            "Worker %s exceeded max restarts — marked failed", key
                        )
                    continue
                if key.startswith("camera:"):
                    cam_id = key.split(":", 1)[1]
                    cam = next(
                        (c for c in self.cfg.cameras if c.id == cam_id), None
                    )
                    if cam and cam.enabled:
                        entry.restart_count += 1
                        self.logger.warning(
                            "Worker %s died; restarting (attempt %d)", key, entry.restart_count
                        )
                        new = self._spawn_camera(cam)
                        new.restart_count = entry.restart_count
                        self._workers[key] = new
                    else:
                        self.logger.info("Camera worker %s died but is disabled — not restarting", key)
                elif key.startswith("inference:"):
                    entry.restart_count += 1
                    self.logger.warning(
                        "Worker %s died; restarting (attempt %d)", key, entry.restart_count
                    )
                    idx = int(key.split(":", 1)[1])
                    new = self._spawn_inference(idx)
                    new.restart_count = entry.restart_count
                    self._workers[key] = new

    def add_camera_worker(self, camera: CameraConfig) -> None:
        """Start a worker for a camera, stopping any existing one first."""
        self.remove_camera_worker(camera.id)
        if camera.enabled:
            entry = self._spawn_camera(camera)
            self._workers[entry.key] = entry
            self.logger.info("Started camera worker: %s", camera.id)

    def remove_camera_worker(self, camera_id: str) -> None:
        """Stop and remove a camera worker if it is running."""
        key = f"camera:{camera_id}"
        entry = self._workers.pop(key, None)
        if entry is None:
            return
        entry.stop_event.set()
        entry.process.terminate()   # non-blocking — heartbeat cleans up any zombie
        self.logger.info("Stopped camera worker: %s", camera_id)

    def get_camera_statuses(self) -> dict[str, str]:
        statuses: dict[str, str] = {}
        for key, entry in self._workers.items():
            if not key.startswith("camera:"):
                continue
            cam_id = key.split(":", 1)[1]
            if entry.status == WorkerStatus.ERROR:
                statuses[cam_id] = "error"
            elif not entry.process.is_alive():
                statuses[cam_id] = "reconnecting"
            else:
                statuses[cam_id] = "connected"
        return statuses
