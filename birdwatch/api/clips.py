from __future__ import annotations
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path

router = APIRouter(prefix="/api", tags=["clips"])
CLIPS_ROOT = Path("data/clips").resolve()


@router.get("/clips/{clip_path:path}")
def serve_clip(clip_path: str):
    # DB stores paths as "data/clips/<camera>/..." — strip that prefix so we
    # don't double-prepend it when resolving against CLIPS_ROOT.
    clean = clip_path.removeprefix("data/clips/")
    full = Path(clean)
    if not full.is_absolute():
        full = CLIPS_ROOT / clean
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
