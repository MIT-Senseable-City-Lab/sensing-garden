# CLI Reference

Complete reference for the `bugcam` command-line interface.

## Models

Manage and inspect detection models. Models must be downloaded before use.

### Download a model
```bash
bugcam models download <model_name>
```
Download a model from S3 and cache it locally in `~/.cache/bugcam/models/`.

**Available models:**
- `yolov8s` - Small model (~11MB) - Faster inference
- `yolov8m` - Medium model (~31MB) - Higher accuracy

**Example:**
```bash
bugcam models download yolov8s
```

### List installed models
```bash
bugcam models list
```
Shows all downloaded models in the cache directory.

### Show model details
```bash
bugcam models info <model_name>
```
Display detailed information about a specific model (size, path, download status, etc.).

**Example:**
```bash
bugcam models info yolov8s
```

## Preview

Run live camera preview with detection overlay.

### Basic preview
```bash
bugcam preview
```
Opens a camera preview window with real-time detection visualization.

### Preview with specific model
```bash
bugcam preview --model yolov8m
```
Use a specific model from the available models.

**Options:**
- `--model <name>` - Specify which model to use (default: yolov8m)

## Detection

Run continuous detection and save results.

### Start detection
```bash
bugcam detect start
```
Start continuous detection, printing results to console.

### Save detections to file
```bash
bugcam detect start --output detections.jsonl
```
Save detection results to a JSONL file (one detection per line).

### Run for specific duration
```bash
bugcam detect start --duration 30
```
Run detection for 30 minutes, then stop automatically.

### Quiet mode
```bash
bugcam detect start --quiet
```
Suppress console output (useful when saving to file).

### Combined options
```bash
bugcam detect start --model yolov8s --output results.jsonl --duration 60 --quiet
```

**Options:**
- `--model <name>` - Specify which model to use (default: yolov8m)
- `--output <file>` - Save detections to file (JSONL format)
- `--duration <minutes>` - Run for specified minutes (default: run indefinitely)
- `--quiet` - Suppress console output

## Autostart (systemd)

Manage automatic detection on system boot using systemd services.

### Enable autostart
```bash
bugcam autostart enable
```
Creates and enables a systemd service that runs detection on boot.

### Disable autostart
```bash
bugcam autostart disable
```
Stops and disables the systemd service.

### Check status
```bash
bugcam autostart status
```
Shows the current status of the autostart service.

### View logs
```bash
bugcam autostart logs
```
Display recent logs from the autostart service.

### Follow logs in real-time
```bash
bugcam autostart logs --follow
```
Stream live logs from the running service (like `tail -f`).

**Options:**
- `--follow` / `-f` - Follow log output in real-time

## Configuration

### Model Storage

Models are downloaded from S3 and cached locally:
- **Cache directory**: `~/.cache/bugcam/models/`
- **Available models**: `yolov8s.hef` (~11MB) and `yolov8m.hef` (~31MB)

Download models with `bugcam models download <model_name>` before running detection.

**Note**: The `resources/` directory contains models for development use only and is not included in package installations.

## Output Format

Detection results are saved in JSONL (JSON Lines) format:

```json
{"timestamp": "2025-12-14T10:30:45", "class": "insect", "confidence": 0.92, "bbox": [100, 200, 150, 250]}
{"timestamp": "2025-12-14T10:30:46", "class": "insect", "confidence": 0.88, "bbox": [120, 210, 170, 260]}
```

Each line is a valid JSON object representing one detection event.

## Environment Variables

### HAILO_MONITOR
Enable Hailo hardware monitoring:
```bash
export HAILO_MONITOR=1
bugcam detect start
```

See [Monitoring](advanced/monitoring.md) for more details.

## Troubleshooting

### Camera not detected
```bash
# Verify camera is working
rpicam-hello

# Check picamera2 installation
sudo apt install -y python3-picamera2
```

### Hailo not detected
```bash
# Verify Hailo installation
sudo apt install hailo-all

# Check if Hailo device is available
hailortcli scan
```

### Service not starting
```bash
# Check service logs
bugcam autostart logs

# Verify systemd service status
systemctl status bugcam-detect.service
```
