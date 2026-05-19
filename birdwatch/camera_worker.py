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
    """Build the FFmpeg command list for a given RTSP or RTSPS URL.

    UniFi cameras expose multiple streams (AAC audio, Opus audio, H264 video).
    We explicitly select the first audio stream (0:a:0, typically AAC) and
    increase probesize/analyzeduration so FFmpeg can identify all streams before
    starting to decode.
    """
    cmd = ["ffmpeg", "-rtsp_transport", "tcp"]
    if stream_url.startswith("rtsps://"):
        cmd += ["-tls_verify", "0"]   # UniFi uses self-signed certs
    cmd += [
        "-probesize", "50M",           # allow more data for stream detection
        "-analyzeduration", "10M",     # allow more time to analyze multi-stream feeds
        "-i", stream_url,
        "-map", "0:a:0",               # explicitly select first audio stream (AAC)
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
    overlap_seconds: float,
    lat: float,
    lon: float,
    min_confidence: float,
    stop_event: multiprocessing.Event,
) -> None:
    """Entry point for a camera worker subprocess.

    Runs forever (reconnecting on failure) until stop_event is set.

    Note: ``infer_queue`` must be created with ``maxsize`` equal to the
    desired backpressure limit (e.g. ``multiprocessing.Queue(maxsize=N)``).
    Chunks are dropped when the queue is full.
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
                camera_id, stream_url, infer_queue,
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
    overlap_seconds: float,
    lat: float,
    lon: float,
    min_confidence: float,
    stop_event: multiprocessing.Event,
    logger: logging.Logger,
) -> None:
    cmd = build_ffmpeg_cmd(stream_url)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
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
                try:
                    infer_queue.put_nowait({
                        "camera_id": camera_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "pcm_bytes": pcm,
                        "lat": lat,
                        "lon": lon,
                        "min_confidence": min_confidence,
                    })
                except Exception:
                    # Queue full (requires queue created with maxsize=queue_max)
                    logger.warning(
                        "Inference queue full, dropping chunk from %s", camera_id
                    )
    finally:
        proc.terminate()
        proc.wait()
        stderr_output = proc.stderr.read().decode(errors="replace").strip()
        if stderr_output:
            logger.warning("FFmpeg stderr for %s: %s", camera_id,
                           stderr_output[:500])  # cap at 500 chars
        logger.info("FFmpeg stopped for %s", camera_id)
