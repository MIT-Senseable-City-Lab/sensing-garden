# bugcam - Raspberry Pi Insect Detection

CLI for running insect detection on Raspberry Pi with Hailo AI HAT+.

## Requirements

- Raspberry Pi 5
- Raspberry Pi AI HAT+ (Hailo8/Hailo8L)
- Raspberry Pi Camera Module 3
- 64-bit Raspberry Pi OS Bookworm
- Active cooler recommended

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
Verify system is ready for inference (dependencies, camera, Hailo device).

```bash
bugcam check
```

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
