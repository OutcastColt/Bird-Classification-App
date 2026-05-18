import multiprocessing
import pytest
from birdwatch.camera_worker import chunk_pcm_buffer, build_ffmpeg_cmd

SAMPLE_RATE = 48000
SAMPLE_WIDTH = 2
BYTES_PER_SEC = SAMPLE_RATE * SAMPLE_WIDTH  # 96000

def test_chunk_pcm_buffer_exact():
    chunk_bytes = BYTES_PER_SEC * 3       # 288000
    step_bytes  = BYTES_PER_SEC * 2       # 192000 (1s overlap -> step=2s)
    data = b"x" * chunk_bytes
    chunks, remaining = chunk_pcm_buffer(data, chunk_bytes, step_bytes)
    assert len(chunks) == 1
    assert len(chunks[0]) == chunk_bytes
    assert len(remaining) == chunk_bytes - step_bytes  # overlap left in buffer

def test_chunk_pcm_buffer_partial():
    chunk_bytes = BYTES_PER_SEC * 3
    step_bytes  = BYTES_PER_SEC * 2
    data = b"x" * (BYTES_PER_SEC * 2)
    chunks, remaining = chunk_pcm_buffer(data, chunk_bytes, step_bytes)
    assert chunks == []
    assert len(remaining) == BYTES_PER_SEC * 2

def test_chunk_pcm_buffer_multiple():
    chunk_bytes = BYTES_PER_SEC * 3
    step_bytes  = BYTES_PER_SEC * 3  # no overlap
    data = b"x" * (BYTES_PER_SEC * 7)
    chunks, remaining = chunk_pcm_buffer(data, chunk_bytes, step_bytes)
    assert len(chunks) == 2          # 7s -> two 3s chunks, 1s remaining
    assert len(remaining) == BYTES_PER_SEC

def test_ffmpeg_cmd_rtsp_no_tls():
    cmd = build_ffmpeg_cmd("rtsp://192.168.1.10:554/stream1")
    assert "-tls_verify" not in cmd
    assert "rtsp://192.168.1.10:554/stream1" in cmd

def test_ffmpeg_cmd_rtsps_has_tls_verify():
    cmd = build_ffmpeg_cmd("rtsps://192.168.1.11:7441/stream1")
    assert "-tls_verify" in cmd
    assert "0" in cmd
    assert "rtsps://192.168.1.11:7441/stream1" in cmd
