[![PyPI version](https://img.shields.io/pypi/v/bugcam.svg)](https://pypi.org/project/bugcam/)
[![Python versions](https://img.shields.io/pypi/pyversions/bugcam.svg)](https://pypi.org/project/bugcam/)
[![License](https://img.shields.io/pypi/l/bugcam.svg)](https://pypi.org/project/bugcam/)
[![Downloads](https://static.pepy.tech/badge/bugcam)](https://pepy.tech/project/bugcam)
[![Downloads](https://static.pepy.tech/badge/bugcam/month)](https://pepy.tech/project/bugcam)
[![Downloads](https://static.pepy.tech/badge/bugcam/week)](https://pepy.tech/project/bugcam)

# bugcam - Raspberry Pi Insect Detection

CLI for running insect detection on Raspberry Pi with Hailo AI HAT+.

## Feature Status

**Legend:** ✓ Tested & working on device | ⚠️ In development (not yet verified on device)

## Requirements

### Hardware
- **Raspberry Pi**: Raspberry Pi 5 (required - Pi 4 not supported due to PCIe requirement)
- **RAM**: 8GB recommended
- **Storage**: 32GB microSD minimum (64GB recommended for multiple models)
- **AI Accelerator**: Raspberry Pi AI HAT+ with Hailo-8L (13 TOPS) or Hailo-8 (26 TOPS)
- **Camera**: Raspberry Pi High Quality Camera (recommended, tested) or Raspberry Pi Camera Module 3 (likely supported, not yet tested)
- **Cooling**: Active Cooler required (thermal management essential under AI workload)
- **Power Supply**: Official 27W USB-C power supply recommended

### Software
- **OS**: Raspberry Pi OS Bookworm 64-bit (latest version)
- **Kernel**: 6.6.31 or newer (run `sudo apt full-upgrade` if needed)
- **PCIe**: Gen 3 enabled via `raspi-config` (required for optimal performance)


## Quick Start

```bash
# 1. Install system dependencies
sudo apt update && sudo apt install hailo-all

# 2. Install bugcam
pipx install bugcam

# 3. Download detection model
bugcam models download london_141-multitask

# 4. Run detection
bugcam preview
```

## Commands

### `bugcam setup` ✓
Initialize bugcam by installing Hailo dependencies and creating the virtual environment.

```bash
bugcam setup
```

This clones hailo-rpi5-examples to `/tmp` during setup, runs the installation, then moves only the virtual environment to `~/.local/share/bugcam/hailo-venv`.

### `bugcam preview` ⚠️
Run live camera preview with detection overlay.

```bash
bugcam preview [--model london_141-multitask]
```

### `bugcam detect` ⚠️
Run continuous detection and save results.

```bash
bugcam detect start [--output detections.jsonl] [--duration 30] [--quiet]
```

Output format (JSONL):
```json
{"timestamp": "2025-12-14T10:30:45", "class": "insect", "confidence": 0.92, "bbox": [100, 200, 150, 250]}
```

### `bugcam status` ✓
Check system status, dependencies, and hardware connections.

```bash
bugcam status           # Run all checks
bugcam status deps      # Check software dependencies
bugcam status devices   # Check hardware connections
bugcam status hailo     # Check Hailo AI accelerator
bugcam status camera    # Check camera connection
bugcam status sensor    # Check I2C sensors
bugcam status models    # Check installed models
```

**Checks performed:**

| Check | What it tests | How |
|-------|---------------|-----|
| `deps` | Python packages (gi, hailo, numpy, cv2, hailo_apps) | Imports in detection Python |
| `hailo` | Hailo AI accelerator is detected | Runs `hailortcli scan` |
| `camera` | RPi camera is accessible | Imports picamera2 and initializes |
| `sensor` | I2C sensors are connected | Scans I2C bus for known addresses |
| `models` | .hef model files installed | Checks cache directory |

### `bugcam models` ✓
Manage detection models.

```bash
# Download a model
bugcam models download london_141-multitask

# List available and installed models
bugcam models list

# Show model details
bugcam models info london_141-multitask

# Delete a model
bugcam models delete london_141-multitask
```

Models are managed by the S3 backend. Run `bugcam models list` to see available models.

### `bugcam record` ✓
Record videos at intervals (without on-device detection). Useful for collecting training data or when you want to process videos later on a more powerful machine.

```bash
# Record 60s videos every 10 minutes
bugcam record start --interval 10 --length 60

# Record for 8 hours then stop
bugcam record start --duration 480 --interval 10 --length 60

# Save to custom directory
bugcam record start --output-dir /mnt/usb/videos --interval 10 --length 60

# Record a single test video
bugcam record single --length 30

# Save single video to specific path
bugcam record single --output /tmp/test.mp4 --length 10
```

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--interval`, `-i` | 10 | Minutes between recordings |
| `--length`, `-l` | 60 | Length of each video in seconds |
| `--duration`, `-d` | 0 | Total runtime in minutes (0 = run forever) |
| `--output-dir`, `-o` | `~/bugcam-videos` | Directory to save videos |
| `--quiet`, `-q` | false | Suppress console output |

Videos are saved with timestamp filenames like `video_20251216_153045.mp4`.

### `bugcam autostart`
Manage systemd service for automatic detection or recording on boot.

```bash
# Detection mode (with AI model) ⚠️
bugcam autostart enable --mode detect --model small-generic

# Recording mode (video only, no detection) ✓
bugcam autostart enable --mode record --interval 10 --length 60

# Recording to external storage ✓
bugcam autostart enable --mode record --interval 10 --length 60 --output-dir /mnt/usb/videos

# Manage service ✓
bugcam autostart disable
bugcam autostart status
bugcam autostart logs [--follow]
```

## Environment Variables

Optional configuration:

- `XDG_CACHE_HOME` - Custom cache directory location (default: `~/.cache`)

## Monitoring

```bash
# Hailo hardware monitoring
hailortcli monitor

# System temperature
vcgencmd measure_temp

# Service logs
bugcam autostart logs --follow
```

## Troubleshooting

```bash
# Run all system checks
bugcam status

# Command not found after install
pipx ensurepath  # then close and reopen terminal

# Camera not detected
rpicam-hello
sudo raspi-config  # Enable camera in Interface Options

# Hailo driver issues
sudo apt install --reinstall hailo-all
hailortcli scan

# Service logs
bugcam autostart logs
```

## Development

```bash
git clone https://github.com/MIT-Senseable-City-Lab/sensing-garden.git
cd sensing-garden
poetry install
poetry run pytest tests/ -v
poetry run bugcam --help
```

## License

MIT
