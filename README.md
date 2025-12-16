# bugcam - Raspberry Pi Insect Detection

CLI for running insect detection on Raspberry Pi with Hailo AI HAT+.

## Requirements

### Hardware
- **Raspberry Pi**: Raspberry Pi 5 (required - Pi 4 not supported due to PCIe requirement)
- **RAM**: 8GB recommended
- **Storage**: 32GB microSD minimum (64GB recommended for multiple models)
- **AI Accelerator**: Raspberry Pi AI HAT+ with Hailo-8L (13 TOPS) or Hailo-8 (26 TOPS)
- **Camera**: Any official Raspberry Pi camera (Camera Module 3 recommended, High Quality Camera also supported)
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
bugcam models download yolov8m

# 4. Run detection
bugcam preview
```

## Commands

### `bugcam setup`
Initialize bugcam by installing dependencies and downloading hailo-rpi5-examples.

```bash
bugcam setup
```

### `bugcam preview`
Run live camera preview with detection overlay.

```bash
bugcam preview [--model yolov8m]
```

### `bugcam detect`
Run continuous detection and save results.

```bash
bugcam detect start [--output detections.jsonl] [--duration 30] [--quiet]
```

Output format (JSONL):
```json
{"timestamp": "2025-12-14T10:30:45", "class": "insect", "confidence": 0.92, "bbox": [100, 200, 150, 250]}
```

### `bugcam doctor`
Run system diagnostics to check dependencies, hardware, and configuration.

```bash
bugcam doctor
```

### `bugcam check`
Test hardware connections before running detection.

```bash
bugcam check all      # Run all checks
bugcam check hailo    # Test Hailo AI accelerator
bugcam check camera   # Test camera connection
bugcam check sensor   # Test I2C sensors
```

**Checks performed:**

| Check | What it tests | How |
|-------|---------------|-----|
| `hailo` | Hailo AI accelerator is detected | Runs `hailortcli scan` |
| `camera` | RPi camera is accessible | Imports picamera2 and initializes |
| `sensor` | I2C sensors are connected | Scans I2C bus for known addresses (SCD30, SCD40, BME280) |

### `bugcam models`
Manage detection models.

```bash
# Download a model (yolov8s or yolov8m)
bugcam models download yolov8m

# List installed models
bugcam models list

# Show model details
bugcam models info yolov8m
```

### `bugcam autostart`
Manage systemd service for automatic detection on boot.

```bash
bugcam autostart enable
bugcam autostart disable
bugcam autostart status
bugcam autostart logs [--follow]
```

## Environment Variables

Optional configuration:

- `HAILO_EXAMPLES_PATH` - Custom path for hailo-rpi5-examples (default: `~/hailo-rpi5-examples`)
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
# Run diagnostics
bugcam doctor

# Verify system readiness
bugcam check

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
