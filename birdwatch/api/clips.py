from __future__ import annotations
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path

router = APIRouter(prefix="/api", tags=["clips"])
CLIPS_ROOT = Path("data/clips").resolve()


@router.get("/clips/{clip_path:path}")
def serve_clip(clip_path: str):
    full = Path(clip_path)
    if not full.is_absolute():
        full = CLIPS_ROOT / clip_path
    resolved = full.resolve()
    try:
        resolved.relative_to(CLIPS_ROOT)
    except ValueError:
        raise HTTPException(status_code=403, detail="Forbidden")
    if not resolved.exists():
        raise HTTPException(status_code=404, detail="Clip not found")
    if resolved.suffix.lower() != ".wav":
        raise HTTPException(status_code=400, detail="Not a WAV file")
    return FileResponse(str(resolved), media_type="audio/wav")
