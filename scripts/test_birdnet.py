#!/usr/bin/env python3
"""
BirdNET installation test script.

Downloads a short public-domain bird recording and runs it through
birdnetlib to confirm the model loads and detections work correctly.

Usage:
    source venv/bin/activate
    python scripts/test_birdnet.py

Optional arguments:
    --audio <path>   Use a local audio file instead of downloading a sample
    --lat <float>    Latitude for species filtering (default: 38.89)
    --lon <float>    Longitude for species filtering (default: -77.03)
    --conf <float>   Minimum confidence threshold (default: 0.10)
"""

import argparse
import os
import sys
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path

# Candidate URLs tried in order until one succeeds.
# Wikimedia requires a User-Agent; BirdNET-Analyzer example is a reliable fallback.
SAMPLE_URLS = [
    (
        "https://upload.wikimedia.org/wikipedia/commons/0/0b/Turdus-merula-singing.ogg",
        "test_blackbird.ogg",
    ),
    (
        "https://github.com/kahst/BirdNET-Analyzer/raw/main/example/soundscape.wav",
        "test_soundscape.wav",
    ),
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; BirdWatch-test/1.0; "
        "+https://github.com/OutcastColt/Bird-Classification-App)"
    )
}


def download_sample(dest: str) -> None:
    last_err = None
    for url, label in SAMPLE_URLS:
        print(f"Downloading test audio: {label} ...")
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp, open(dest, "wb") as f:
                f.write(resp.read())
            size_kb = Path(dest).stat().st_size // 1024
            print(f"Downloaded {size_kb} KB -> {dest}")
            return
        except Exception as exc:
            print(f"  Failed ({exc}), trying next source...")
            last_err = exc
    raise RuntimeError(f"All download sources failed. Last error: {last_err}")


def run_test(audio_path: str, lat: float, lon: float, min_conf: float) -> bool:
    print("\n--- Step 1: Load BirdNET model ---")
    try:
        from birdnetlib.analyzer import Analyzer
        analyzer = Analyzer()
        print("Model loaded OK")
    except Exception as exc:
        print(f"FAILED to load model: {exc}")
        print("\nTroubleshooting:")
        print("  1. Ensure you are in the venv: source venv/bin/activate")
        print("  2. Install dependencies:       pip install -r requirements.txt")
        print("  3. Check internet access (model downloads on first run)")
        return False

    print("\n--- Step 2: Analyse audio ---")
    print(f"  File      : {audio_path}")
    print(f"  Location  : {lat}, {lon}")
    print(f"  Min conf  : {min_conf:.0%}")
    print(f"  Date      : {datetime.now().strftime('%Y-%m-%d')}")

    try:
        from birdnetlib import Recording
        recording = Recording(
            analyzer,
            audio_path,
            lat=lat,
            lon=lon,
            min_conf=min_conf,
            date=datetime.now(),
        )
        recording.analyze()
    except Exception as exc:
        print(f"FAILED to analyse audio: {exc}")
        return False

    print("\n--- Step 3: Results ---")
    if not recording.detections:
        print("No detections above threshold.")
        print("Try a lower --conf value or a different audio file.")
        return True

    print(f"{'Species':<30} {'Scientific name':<35} {'Confidence':>10}")
    print("-" * 77)
    for d in sorted(recording.detections, key=lambda x: x["confidence"], reverse=True):
        print(f"{d['common_name']:<30} {d['scientific_name']:<35} {d['confidence']:>9.0%}")

    print(f"\n{len(recording.detections)} detection(s) found — BirdNET is working correctly.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Test BirdNET installation")
    parser.add_argument("--audio", help="Path to a local audio file")
    parser.add_argument("--lat",  type=float, default=38.89, help="Latitude")
    parser.add_argument("--lon",  type=float, default=-77.03, help="Longitude")
    parser.add_argument("--conf", type=float, default=0.10,  help="Min confidence (0–1)")
    args = parser.parse_args()

    if args.audio:
        audio_path = args.audio
        if not Path(audio_path).exists():
            print(f"File not found: {audio_path}")
            sys.exit(1)
        tmp = None
    else:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        audio_path = tmp.name
        try:
            download_sample(audio_path)
        except Exception as exc:
            print(f"Download failed: {exc}")
            print(f"Provide a local file with --audio <path>")
            os.unlink(audio_path)
            sys.exit(1)

    try:
        success = run_test(audio_path, args.lat, args.lon, args.conf)
    finally:
        if tmp:
            os.unlink(audio_path)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
