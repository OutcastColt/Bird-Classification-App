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

    source venv/bin/activate
    python main.py

## Dashboard

Open `http://<server-ip>:8080/` from any browser on your LAN.

| Tab | Description |
|-----|-------------|
| Live | Real-time detection feed + camera status indicators |
| History | Searchable/paginated detection log with audio playback |
| Cameras | Add, edit, or remove RTSP/RTSPS streams |
| Settings | Adjust location, confidence threshold, GPU mode, alert rules |

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

Verify BirdNET is installed and detecting correctly using the included test script.
It downloads a short public-domain Common Blackbird recording and runs it through
the model, printing any detections found.

    cd /opt/birdwatch
    source venv/bin/activate
    python scripts/test_birdnet.py

Expected output:

    Downloading test audio from Wikimedia Commons...
    Downloaded 124 KB -> /tmp/tmpXXXXXX.ogg

    --- Step 1: Load BirdNET model ---
    Model loaded OK

    --- Step 2: Analyse audio ---
      File      : /tmp/tmpXXXXXX.ogg
      Location  : 38.89, -77.03
      Min conf  : 10%
      Date      : 2026-05-19

    --- Step 3: Results ---
    Species                        Scientific name                     Confidence
    -----------------------------------------------------------------------------
    Common Blackbird               Turdus merula                              91%

    1 detection(s) found — BirdNET is working correctly.

**Options:**

| Flag | Description | Default |
|------|-------------|---------|
| `--audio <path>` | Use a local audio file instead of downloading | (downloads sample) |
| `--lat <float>` | Latitude for species filtering | 38.89 |
| `--lon <float>` | Longitude for species filtering | -77.03 |
| `--conf <float>` | Minimum confidence threshold | 0.10 |

Example with a local file and your own coordinates:

    python scripts/test_birdnet.py --audio /path/to/bird.wav --lat 51.5 --lon -0.1

**Troubleshooting:**

- `Failed to load model` — run `pip install -r requirements.txt` inside the venv; the model downloads automatically on first run (requires internet access)
- `No detections` — try `--conf 0.05` or use a different audio file; the sample is a European species so location filtering may suppress it outside Europe

## Upgrading

    cd /opt/birdwatch
    sudo git pull
    sudo -u birdwatch venv/bin/pip install -r requirements.txt
    sudo systemctl restart birdwatch
