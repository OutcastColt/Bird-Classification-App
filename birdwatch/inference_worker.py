from __future__ import annotations
import logging
import multiprocessing
import os
import tempfile
import wave
from datetime import datetime
from pathlib import Path

SAMPLE_RATE = 48000
CHANNELS = 1
SAMPLE_WIDTH = 2


def slug(text: str) -> str:
    """Convert a species name to a filesystem-safe slug."""
    return text.lower().replace(" ", "_").replace("'", "_")


def pcm_to_wav_file(pcm_bytes: bytes, tmp_dir: str) -> str:
    """Write raw PCM bytes to a temporary WAV file. Caller deletes it."""
    fd, path = tempfile.mkstemp(suffix=".wav", dir=tmp_dir)
    os.close(fd)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm_bytes)
    return path


def build_clip_path(
    camera_id: str, timestamp: str, species: str, confidence: float
) -> str:
    """Build the permanent clip file path from detection metadata."""
    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    date_str = dt.strftime("%Y-%m-%d")
    time_str = dt.strftime("%H-%M-%S")
    fname = f"{time_str}_{slug(species)}_{confidence:.2f}.wav"
    return f"data/clips/{camera_id}/{date_str}/{fname}"


def save_clip(pcm_bytes: bytes, dest_path: str) -> None:
    """Write PCM bytes as a WAV file to dest_path, creating parent dirs."""
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(dest_path, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm_bytes)


def _create_analyzer(use_gpu: bool, worker_index: int):
    """Load a birdnetlib Analyzer instance.

    If use_gpu=True and worker_index==0, attempt TFLite OpenCL GPU delegate.
    Falls back to CPU silently on failure.
    """
    from birdnetlib.analyzer import Analyzer  # deferred — not needed for unit tests

    if use_gpu and worker_index == 0:
        try:
            import tflite_runtime.interpreter as tflite
            tflite.load_delegate("libOpenCL.so")
            logging.getLogger("inference").info("GPU delegate loaded for worker 0")
        except Exception as exc:
            logging.getLogger("inference").warning(
                "GPU delegate unavailable (%s); using CPU for all workers", exc
            )
    return Analyzer()


def run_inference_worker(
    worker_index: int,
    infer_queue: multiprocessing.Queue,
    result_queue: multiprocessing.Queue,
    use_gpu: bool,
    stop_event: multiprocessing.Event,
) -> None:
    """Entry point for an inference worker subprocess."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s inference.%(name)s %(levelname)s %(message)s",
    )
    logger = logging.getLogger(str(worker_index))

    try:
        analyzer = _create_analyzer(use_gpu, worker_index)
    except Exception as exc:
        logger.error("Failed to load BirdNET model: %s", exc)
        return

    logger.info("Inference worker %d ready", worker_index)
    tmp_dir = tempfile.mkdtemp(prefix=f"birdwatch_infer_{worker_index}_")

    from birdnetlib import Recording  # deferred import

    while not stop_event.is_set():
        try:
            job = infer_queue.get(timeout=1.0)
        except Exception:
            continue

        tmp_wav = None
        try:
            tmp_wav = pcm_to_wav_file(job["pcm_bytes"], tmp_dir)
            recording = Recording(
                analyzer,
                tmp_wav,
                lat=job["lat"],
                lon=job["lon"],
                min_conf=job["min_confidence"],
                date=datetime.fromisoformat(
                    job["timestamp"].replace("Z", "+00:00")
                ),
            )
            recording.analyze()

            if not recording.detections:
                continue

            # Save one clip file per chunk (named after first detected species)
            first = recording.detections[0]
            dest = build_clip_path(
                job["camera_id"],
                job["timestamp"],
                first["common_name"],
                first["confidence"],
            )
            save_clip(job["pcm_bytes"], dest)

            for det in recording.detections:
                result_queue.put({
                    "camera_id": job["camera_id"],
                    "timestamp": job["timestamp"],
                    "species_common": det["common_name"],
                    "species_sci": det["scientific_name"],
                    "confidence": round(det["confidence"], 4),
                    "clip_path": dest,
                    "lat": job["lat"],
                    "lon": job["lon"],
                })

        except Exception as exc:
            logger.error("Inference error: %s", exc)
        finally:
            if tmp_wav and os.path.exists(tmp_wav):
                os.unlink(tmp_wav)
