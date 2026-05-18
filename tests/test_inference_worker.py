import os
import wave
import pytest
from pathlib import Path
from birdwatch.inference_worker import (
    pcm_to_wav_file, build_clip_path, save_clip, slug,
)

SAMPLE_RATE = 48000
SAMPLE_WIDTH = 2
CHUNK_BYTES = SAMPLE_RATE * SAMPLE_WIDTH * 3  # 3 seconds of audio

def test_slug_basic():
    assert slug("Northern Cardinal") == "northern_cardinal"

def test_slug_apostrophe():
    assert slug("Bewick's Wren") == "bewick_s_wren"

def test_pcm_to_wav_file_creates_valid_wav(tmp_path):
    pcm = b"\x00\x01" * (CHUNK_BYTES // 2)
    path = pcm_to_wav_file(pcm, str(tmp_path))
    assert os.path.exists(path)
    with wave.open(path, "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == SAMPLE_RATE
        assert wf.getnframes() == len(pcm) // 2
    os.unlink(path)

def test_build_clip_path():
    path = build_clip_path("front-yard", "2026-05-18T14:32:10", "Northern Cardinal", 0.87)
    assert path == "data/clips/front-yard/2026-05-18/14-32-10_northern_cardinal_0.87.wav"

def test_save_clip_creates_file(tmp_path):
    pcm = b"\x00\x00" * CHUNK_BYTES
    dest = str(tmp_path / "cam" / "2026-05-18" / "clip.wav")
    save_clip(pcm, dest)
    assert os.path.exists(dest)
    with wave.open(dest, "rb") as wf:
        assert wf.getframerate() == SAMPLE_RATE
