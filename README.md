# BirdWatch

24/7 bird audio detection from RTSP/RTSPS camera streams using BirdNET-Analyzer.
Detections are stored locally with audio clips and viewable via a web dashboard.

## Prerequisites

Ubuntu Server 22.04+

Install system dependencies:

    sudo apt update
    sudo apt install -y ffmpeg python3.12 python3.12-venv git

For GPU support (optional — Quadro K2100M / other OpenCL-capable card):

    sudo apt install -y nvidia-opencl-dev ocl-icd-opencl-dev

## Installation

    # Create a dedicated user and install directory
    sudo useradd -r -s /bin/false birdwatch
    sudo mkdir -p /opt/birdwatch
    sudo git clone <repo-url> /opt/birdwatch
    sudo chown -R birdwatch:birdwatch /opt/birdwatch

    # Create Python virtual environment and install dependencies
    cd /opt/birdwatch
    sudo -u birdwatch python3.12 -m venv venv
    sudo -u birdwatch venv/bin/pip install -r requirements.txt

Note: the first `pip install` downloads TensorFlow (~500 MB) and librosa (~300 MB).
Allow 5–15 minutes depending on connection speed.

## Configuration

    cp config/config.example.yaml config/config.yaml
    nano config/config.yaml

Key settings to update:

| Setting | Description |
|---------|-------------|
| `location.lat` / `.lon` | Your coordinates (improves species accuracy) |
| `cameras[].stream_url` | Your RTSP (`rtsp://`) or RTSPS (`rtsps://`) camera URL |
| `birdnet.min_confidence` | Detection threshold (0.70 recommended) |
| `birdnet.use_gpu` | Set `true` to enable OpenCL GPU acceleration |
| `inference.workers` | Number of BirdNET workers (4 recommended for CPU) |

### UniFi Camera URLs

UniFi cameras use RTSPS on port 7441 by default:

    rtsps://<camera-ip>:7441/<channel>

The self-signed TLS certificate is handled automatically — no extra configuration needed.

### GPU Configuration (NVIDIA Quadro K2100M or similar)

The Quadro K2100M uses Kepler architecture (CUDA compute 3.0). Modern TensorFlow does not
support Kepler, but the TFLite OpenCL delegate is available. To enable:

1. Install OpenCL packages (see Prerequisites)
2. Set `birdnet.use_gpu: true` in `config/config.yaml`
3. Set `inference.workers: 1` for GPU-only mode, or `4` for mixed CPU+GPU

BirdWatch automatically falls back to CPU if the OpenCL delegate is unavailable.

## HTTPS Setup (recommended)

Serving over HTTPS avoids browser security warnings when the dashboard makes
requests to external APIs (Wikipedia, iNaturalist). The setup script installs
**nginx** as a reverse proxy and generates a self-signed TLS certificate.

    sudo bash scripts/setup_https.sh

The script:
- Installs nginx
- Generates a 10-year self-signed certificate for the server's LAN IP
- Configures nginx to proxy HTTPS (port 443) to BirdWatch (port 8080)
- Redirects HTTP (port 80) to HTTPS automatically
- Opens ufw firewall ports 80 and 443

After running, open `https://<server-ip>/` instead of `http://<server-ip>:8080/`.

**Trusting the certificate on your LAN devices** removes the browser warning.
The script prints exact instructions for Windows, macOS, Android, and Linux,
or you can download the certificate directly from `https://<server-ip>/birdwatch-ca.crt`.

## Running

### As a systemd service (recommended for 24/7 operation)

    sudo cp birdwatch.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable birdwatch    # start on boot
    sudo systemctl start birdwatch     # start now

Useful commands:

    sudo systemctl stop birdwatch      # stop
    sudo systemctl restart birdwatch   # restart after config changes
    sudo systemctl status birdwatch    # check status
    journalctl -u birdwatch -f         # live logs

### Manually (development / testing)

    sudo -u birdwatch /opt/birdwatch/venv/bin/python main.py

Note: `source venv/bin/activate` does not work for the `birdwatch` service account
(created with `-s /bin/false`). Use the full venv path shown above.

## Dashboard

Open `https://<server-ip>/` (after HTTPS setup) or `http://<server-ip>:8080/` from
any browser on your LAN.

| Tab | Description |
|-----|-------------|
| Live | Real-time detection feed, camera status, detection count, top-10 species |
| History | Filterable/paginated log — filter by camera, species, conservation status, or date range. Audio playback. |
| Cameras | Add, edit, or remove RTSP/RTSPS streams. Changes take effect immediately without restart. |
| Settings | Adjust location, confidence threshold, GPU mode, inference workers, alert rules |

**Bird images and species info** — every detected species shows a Wikipedia photo.
Click any bird image or species name to open a side panel with:

- Description, habitat, diet, migration, breeding, and conservation sections from Wikipedia
- IUCN conservation status badge (colour-coded: green = Least Concern, red = Endangered)
- Your own recorded clips of that species
- Links to Wikipedia, iNaturalist, All About Birds, and eBird

**Conservation status** is shown inline next to every species name throughout the dashboard.

## Alert Rules

Supported notification methods — configured via the Settings tab:

**Webhook** (works with ntfy.sh, Home Assistant, Slack, Discord):

    {"url": "https://ntfy.sh/my-bird-alerts"}

**Email**:

    {"smtp_host": "smtp.gmail.com", "smtp_port": 587,
     "username": "you@gmail.com", "password": "app-password", "to": "you@gmail.com"}

**Pushover**:

    {"app_token": "YOUR_APP_TOKEN", "user_key": "YOUR_USER_KEY"}

## Storage

| Location | Contents |
|----------|----------|
| `data/birdwatch.db` | All detection records (kept permanently) |
| `data/clips/` | WAV audio clips (pruned after `alerts.retention_days`) |
| `logs/birdwatch.log` | Rolling log file (30 days retained) |

## Testing BirdNET

Verify BirdNET is installed and working using the included test script.
The script generates a synthetic audio file locally (no internet required) and
runs it through the model to confirm the model loads and inference executes.

    cd /opt/birdwatch
    sudo -u birdwatch venv/bin/python scripts/test_birdnet.py

Expected output:

    Generated synthetic test audio (3s chirp, 281 KB) -> /tmp/tmpXXXXXX.wav

    --- Step 1: Load BirdNET model ---
    Model loaded OK

    --- Step 2: Run inference ---
      File      : /tmp/tmpXXXXXX.wav
      Audio     : synthetic chirp (no real bird — testing pipeline only)

    --- Step 3: Results ---
    Inference completed successfully.
    No real detections expected from a synthetic tone — BirdNET is working.

    To test with real audio:  python scripts/test_birdnet.py --audio /path/to/bird.wav

To test with a real bird recording and your own coordinates:

    sudo -u birdwatch venv/bin/python scripts/test_birdnet.py \
      --audio /path/to/bird.wav --lat 40.71 --lon -74.00

**Options:**

| Flag | Description | Default |
|------|-------------|---------|
| `--audio <path>` | Use a local audio file for real species detection | (generates synthetic tone) |
| `--lat <float>` | Latitude for species filtering | 40.71 |
| `--lon <float>` | Longitude for species filtering | -74.00 |
| `--conf <float>` | Minimum confidence threshold | 0.10 |

**Troubleshooting:**

- `No module named 'tensorflow'` — run `sudo -u birdwatch venv/bin/pip install -r requirements.txt`; TensorFlow downloads on first install (~500 MB, requires internet)
- `No module named 'librosa'` — same fix; librosa is also in `requirements.txt`
- `No detections` with real audio — try `--conf 0.05`, check that `--lat`/`--lon` match the recording location

## Upgrading

    cd /opt/birdwatch
    sudo git pull
    sudo -u birdwatch venv/bin/pip install -r requirements.txt
    sudo systemctl restart birdwatch

The nginx HTTPS configuration and self-signed certificate in `/etc/ssl/birdwatch/`
are not affected by upgrades — re-run `scripts/setup_https.sh` only if you move
to a new server or the certificate expires (default 10 years).

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/setup_https.sh` | Install nginx reverse proxy with self-signed TLS certificate |
| `scripts/test_birdnet.py` | Verify BirdNET model loads and inference runs correctly |
