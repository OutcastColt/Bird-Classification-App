# BirdWatch

24/7 bird audio detection from RTSP/RTSPS camera streams using BirdNET-Analyzer.
Detections are stored locally with audio clips and viewable via a web dashboard.

## Prerequisites

Ubuntu Server 22.04+

Install system dependencies:

    sudo apt update
    sudo apt install -y ffmpeg python3.11 python3.11-venv git

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
    sudo -u birdwatch python3.11 -m venv venv
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

## Upgrading

    cd /opt/birdwatch
    sudo git pull
    sudo -u birdwatch venv/bin/pip install -r requirements.txt
    sudo systemctl restart birdwatch
