from __future__ import annotations
import logging
import multiprocessing
import subprocess
import time
from datetime import datetime, timezone

SAMPLE_RATE = 48000
CHANNELS = 1
SAMPLE_WIDTH = 2                                        # 16-bit
BYTES_PER_SEC = SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH   # 96000
CHUNK_SECONDS = 3
CHUNK_BYTES = BYTES_PER_SEC * CHUNK_SECONDS             # 288000


def build_ffmpeg_cmd(stream_url: str) -> list[str]:
    """Build the FFmpeg command list for a given RTSP or RTSPS URL."""
    cmd = ["ffmpeg", "-rtsp_transport", "tcp"]
    if stream_url.startswith("rtsps://"):
        cmd += ["-tls_verify", "0"]   # UniFi uses self-signed certs
    cmd += [
        "-i", stream_url,
        "-vn",                         # discard video
        "-ar", str(SAMPLE_RATE),
        "-ac", str(CHANNELS),
        "-f", "s16le",                 # raw 16-bit little-endian PCM
        "pipe:1",
        "-loglevel", "error",
    ]
    return cmd


def chunk_pcm_buffer(
    buffer: bytes, chunk_bytes: int, step_bytes: int
) -> tuple[list[bytes], bytes]:
    """Extract all complete chunks from buffer using a sliding window.

    Returns (list_of_chunks, remaining_buffer).
    """
    chunks: list[bytes] = []
    while len(buffer) >= chunk_bytes:
        chunks.append(buffer[:chunk_bytes])
        buffer = buffer[step_bytes:]
    return chunks, buffer


def run_camera_worker(
    camera_id: str,
    stream_url: str,
    infer_queue: multiprocessing.Queue,
    queue_max: int,
    overlap_seconds: float,
    lat: float,
    lon: float,
    min_confidence: float,
    stop_event: multiprocessing.Event,
) -> None:
    """Entry point for a camera worker subprocess.

    Runs forever (reconnecting on failure) until stop_event is set.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s camera.%(name)s %(levelname)s %(message)s",
    )
    logger = logging.getLogger(camera_id)
    backoff = 2.0

    while not stop_event.is_set():
        try:
            _stream_loop(
                camera_id, stream_url, infer_queue, queue_max,
                overlap_seconds, lat, lon, min_confidence, stop_event, logger,
            )
            backoff = 2.0  # reset after clean exit
        except Exception as exc:
            logger.error("Stream error: %s. Reconnecting in %.0fs", exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60.0)


def _stream_loop(
    camera_id: str,
    stream_url: str,
    infer_queue: multiprocessing.Queue,
    queue_max: int,
    overlap_seconds: float,
    lat: float,
    lon: float,
    min_confidence: float,
    stop_event: multiprocessing.Event,
    logger: logging.Logger,
) -> None:
    cmd = build_ffmpeg_cmd(stream_url)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    logger.info("FFmpeg started (PID %d) for %s", proc.pid, stream_url)

    overlap_bytes = int(overlap_seconds * BYTES_PER_SEC)
    step_bytes = CHUNK_BYTES - overlap_bytes   # advance buffer by this much each chunk
    buffer = b""

    try:
        while not stop_event.is_set():
            data = proc.stdout.read(4096)
            if not data:
                break  # FFmpeg exited
            buffer += data
            chunks, buffer = chunk_pcm_buffer(buffer, CHUNK_BYTES, step_bytes)
            for pcm in chunks:
                if infer_queue.qsize() < queue_max:
                    infer_queue.put_nowait({
                        "camera_id": camera_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "pcm_bytes": pcm,
                        "lat": lat,
                        "lon": lon,
                        "min_confidence": min_confidence,
                    })
                else:
                    logger.warning(
                        "Inference queue full (%d), dropping chunk from %s",
                        queue_max, camera_id,
                    )
    finally:
        proc.terminate()
        proc.wait()
        logger.info("FFmpeg stopped for %s", camera_id)
