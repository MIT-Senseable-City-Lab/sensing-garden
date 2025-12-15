# BugCam - Raspberry Pi Insect Detection

CLI for running insect detection on Raspberry Pi with Hailo AI HAT+.

## Quick Start

### 1. Hardware Requirements
- Raspberry Pi 4/5
- Raspberry Pi Camera Module 3
- Raspberry Pi AI HAT+ (Hailo8/Hailo8L)
- Active cooler recommended

See [Hardware Setup Guide](docs/getting-started/hardware-setup.md) for detailed assembly instructions.

### 2. Install BugCam

```bash
# Install system dependencies
sudo apt install hailo-all

# Install bugcam CLI
pip install .
# OR with pipx for isolated install
pipx install .
```

See [Installation Guide](docs/getting-started/installation.md) for detailed setup instructions.

### 3. Run Detection

```bash
# Preview camera with detection overlay
bugcam preview

# Start continuous detection
bugcam detect start

# Save detections to file
bugcam detect start --output detections.jsonl

# Enable autostart on boot
bugcam autostart enable
```

See [CLI Reference](docs/cli-reference.md) for complete command documentation.

## Pre-compiled Models

Insect detection models are included in `resources/`:
- `yolov8m.hef` - Medium model (31MB) - Higher accuracy
- `yolov8s.hef` - Small model (11MB) - Faster inference

## Documentation

### Getting Started
- [Hardware Setup](docs/getting-started/hardware-setup.md) - Raspberry Pi and camera assembly
- [Installation](docs/getting-started/installation.md) - Software installation and configuration
- [Hotspot Setup](docs/getting-started/hotspot-setup.md) - Configure wireless access point

### Reference
- [CLI Reference](docs/cli-reference.md) - Complete command documentation

### Advanced
- [Monitoring](docs/advanced/monitoring.md) - Performance monitoring and debugging
- [TensorFlow Lite Alternative](docs/advanced/tensorflow-alternative.md) - Running without AI HAT

## Development

```bash
# Install with dev dependencies
poetry install

# Run tests
poetry run pytest tests/ -v

# Run CLI from source
poetry run bugcam --help
```

## License

MIT
