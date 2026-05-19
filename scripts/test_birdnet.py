#!/usr/bin/env python3
"""
BirdNET installation test script.

Generates a synthetic audio file locally (no internet required) and runs it
through birdnetlib to confirm the model loads and inference executes correctly.

For a real detection test, pass a genuine bird recording with --audio.

Usage:
    source venv/bin/activate
    python scripts/test_birdnet.py

    # Test with a real recording for actual species detection:
    python scripts/test_birdnet.py --audio /path/to/bird.wav

Optional arguments:
    --audio <path>   Use a local audio file instead of the synthetic tone
    --lat <float>    Latitude for species filtering (default: 40.71)
    --lon <float>    Longitude for species filtering (default: -74.00)
    --conf <float>   Minimum confidence threshold (default: 0.10)
"""

import argparse
import math
import os
import struct
import sys
import tempfile
import wave
from datetime import datetime
from pathlib import Path

SAMPLE_RATE = 48000
DURATION_S  = 3


def generate_test_wav(dest: str) -> None:
    """Write a 3-second frequency sweep (2 kHz -> 8 kHz) at 48 kHz mono 16-bit.

    A rising chirp resembles a bird call and gives BirdNET something non-trivial
    to process, exercising the full inference path.
    """
    n_samples = SAMPLE_RATE * DURATION_S
    freq_start = 2000.0
    freq_end   = 8000.0
    amplitude  = 16000  # well below int16 max to avoid clipping

    samples = []
    for i in range(n_samples):
        t = i / SAMPLE_RATE
        # Linear frequency sweep
        freq = freq_start + (freq_end - freq_start) * (t / DURATION_S)
        value = int(amplitude * math.sin(2 * math.pi * freq * t))
        samples.append(value)

    with wave.open(dest, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)   # 16-bit
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(struct.pack(f"<{n_samples}h", *samples))

    size_kb = Path(dest).stat().st_size // 1024
    print(f"Generated synthetic test audio ({DURATION_S}s chirp, {size_kb} KB) -> {dest}")


def run_test(audio_path: str, lat: float, lon: float, min_conf: float,
             is_synthetic: bool) -> bool:
    print("\n--- Step 1: Load BirdNET model ---")
    try:
        from birdnetlib.analyzer import Analyzer
        analyzer = Analyzer()
        print("Model loaded OK")
    except Exception as exc:
        print(f"FAILED to load model: {exc}")
        print("\nTroubleshooting:")
        print("  1. Ensure you are in the venv:  source venv/bin/activate")
        print("  2. Install dependencies:         pip install -r requirements.txt")
        print("  3. First run downloads the model — requires internet access (~100 MB)")
        return False

    print("\n--- Step 2: Run inference ---")
    print(f"  File      : {audio_path}")
    print(f"  Location  : {lat}, {lon}")
    print(f"  Min conf  : {min_conf:.0%}")
    print(f"  Date      : {datetime.now().strftime('%Y-%m-%d')}")
    if is_synthetic:
        print("  Audio     : synthetic chirp (no real bird — testing pipeline only)")

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
        print(f"FAILED during inference: {exc}")
        return False

    print("\n--- Step 3: Results ---")
    if is_synthetic:
        print("Inference completed successfully.")
        print("No real detections expected from a synthetic tone — BirdNET is working.")
        if recording.detections:
            print(f"(Incidental matches: {', '.join(d['common_name'] for d in recording.detections)})")
        print("\nTo test with real audio:  python scripts/test_birdnet.py --audio /path/to/bird.wav")
        return True

    if not recording.detections:
        print("No detections above threshold.")
        print("Tips: use --conf 0.05, check lat/lon match the recording location,")
        print("      or try a different audio file.")
        return True

    print(f"{'Species':<30} {'Scientific name':<35} {'Confidence':>10}")
    print("-" * 77)
    for d in sorted(recording.detections, key=lambda x: x["confidence"], reverse=True):
        print(f"{d['common_name']:<30} {d['scientific_name']:<35} {d['confidence']:>9.0%}")

    print(f"\n{len(recording.detections)} detection(s) — BirdNET is working correctly.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Test BirdNET installation")
    parser.add_argument("--audio", help="Path to a local audio file for real detection test")
    parser.add_argument("--lat",  type=float, default=40.71, help="Latitude (default: 40.71)")
    parser.add_argument("--lon",  type=float, default=-74.00, help="Longitude (default: -74.00)")
    parser.add_argument("--conf", type=float, default=0.10,  help="Min confidence 0-1 (default: 0.10)")
    args = parser.parse_args()

    if args.audio:
        if not Path(args.audio).exists():
            print(f"File not found: {args.audio}")
            sys.exit(1)
        success = run_test(args.audio, args.lat, args.lon, args.conf, is_synthetic=False)
    else:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        try:
            generate_test_wav(tmp.name)
            success = run_test(tmp.name, args.lat, args.lon, args.conf, is_synthetic=True)
        finally:
            os.unlink(tmp.name)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
