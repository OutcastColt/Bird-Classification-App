import pytest
import wave
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pathlib import Path
from birdwatch.api.clips import router


@pytest.fixture
def app(tmp_path, monkeypatch):
    # Point CLIPS_ROOT to a temp directory so tests are isolated
    monkeypatch.setattr("birdwatch.api.clips.CLIPS_ROOT", tmp_path.resolve())
    a = FastAPI()
    a.include_router(router)
    return a


def make_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(48000)
        wf.writeframes(b"\x00\x00" * 100)


def test_serve_valid_clip(app, tmp_path):
    clip = tmp_path / "cam1" / "clip.wav"
    make_wav(clip)
    relative = f"cam1/clip.wav"
    r = TestClient(app).get(f"/api/clips/{relative}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"


def test_path_traversal_returns_403(app, tmp_path):
    # URL-encoded separators bypass HTTP normalisation and reach the handler
    r = TestClient(app).get("/api/clips/..%2F..%2F..%2Fetc%2Fpasswd")
    assert r.status_code == 403


def test_nonexistent_clip_returns_404(app, tmp_path):
    r = TestClient(app).get("/api/clips/cam1/does_not_exist.wav")
    assert r.status_code == 404


def test_non_wav_extension_returns_400(app, tmp_path):
    txt = tmp_path / "cam1" / "notes.txt"
    txt.parent.mkdir(parents=True, exist_ok=True)
    txt.write_text("hello")
    r = TestClient(app).get("/api/clips/cam1/notes.txt")
    assert r.status_code == 400
