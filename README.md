# bugcam

Raspberry Pi insect detection CLI using Hailo AI accelerator and the edge26 processing pipeline.
Records video, detects and classifies insects on-device, and uploads results to S3.

Default API endpoint: `https://api.sensinggarden.com/v1`

## Prerequisites (Raspberry Pi with Hailo AI)

bugcam requires system-level Hailo packages that are not available via PyPI. Install them before running setup:

```bash
sudo apt update && sudo apt install python3-hailo-tappas hailo-tappas-core
```

If you encounter sudo password prompts during setup, enable passwordless sudo:
```bash
echo "$USER ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/$USER
```

## Quick Start

```bash
curl -sSL https://raw.githubusercontent.com/MIT-Senseable-City-Lab/sensing-garden/main/install.sh | bash
bugcam setup
bugcam models list
bugcam models download <model-name>
bugcam run
```

## Commands

| Command | Description |
|---------|-------------|
| `bugcam run` | Full pipeline: record + process + upload + heartbeat + receiver |
| `bugcam run --no-receiver` | Run without DOT receiver server |
| `bugcam receive start` | Start DOT receiver server standalone |
| `bugcam record single` | Record a single video |
| `bugcam process` | Process existing videos with edge26 |
| `bugcam upload` | Upload processed output to S3 |
| `bugcam heartbeat` | Write a heartbeat snapshot |
| `bugcam environment` | Collect one environmental sensor reading |
| `bugcam dot-info` | Show DOT sensor setup instructions |
| `bugcam models list` | List available and installed models |
| `bugcam models download <name>` | Download a model bundle |
| `bugcam models info <name>` | Show model details |
| `bugcam models delete <name>` | Delete a model bundle |
| `bugcam status` | System diagnostics (hardware, deps, camera, Hailo) |
| `bugcam setup` | Device registration + Hailo installation |
| `bugcam autostart enable` | Enable systemd service for boot |
| `bugcam autostart disable` | Disable systemd service |
| `bugcam autostart status` | Show service status |
| `bugcam autostart logs` | View service logs |
| `bugcam update` | Update to latest version |
| `bugcam --version` | Show installed version |

### `bugcam run` Options

| Option | Default | Description |
|--------|---------|-------------|
| `--with-receiver/--no-receiver` | `True` | Start DOT receiver alongside pipeline |
| `--receiver-port` | `5001` | DOT receiver HTTP port |
| `--receiver-host` | `0.0.0.0` | DOT receiver bind address |
| `--mode` | `continuous` | Recording mode: continuous or interval |
| `--interval` | `5` | Minutes between recordings (interval mode) |
| `--chunk-duration` | `60` | Length of each recorded chunk in seconds |
| `--model` | (from config) | Model bundle name or model.hef path |
| `--detection-config` | (bundled) | Path to custom detection config YAML |

## Architecture

- **edge26 pipeline** lives in `bugcam/edge26/` (vendored from the edge26 repo). Handles recording, processing, and output formatting.
- **BugSpot** library handles motion detection and insect tracking.
- **Hailo accelerator** runs classification on detected insects.
- **DOT Receiver** (`bugcam/receiver/`) is an HTTP server that receives insect track data from iOS devices (DOTs) and saves it in edge26-compatible format. Automatically started with `bugcam run` (can be disabled with `--no-receiver`). Can also run standalone via `bugcam receive start`.
- **Upload** sends results to S3 via presigned URLs obtained from the backend API. No AWS credentials are stored on-device -- only a per-device API key issued during `bugcam setup`.
- **S3 trigger Lambda** indexes uploaded results into DynamoDB.

## Configuration

Config file: `~/.config/bugcam/config.json`

| Field | Description |
|-------|-------------|
| `api_url` | Backend API endpoint |
| `api_key` | Per-device API key (from registration) |
| `flick_id` | FLICK device identifier |
| `dot_ids` | List of DOT device identifiers |
| `s3_bucket` | Output S3 bucket name |
| `input_dir` | DOT receiver input directory |
| `output_dir` | Processed video output directory |
| `state_dir` | State/pending directory |
| `pending_dir` | Classification queue directory |

Models are stored in `~/.cache/bugcam/models/<bundle>/` (each bundle contains `model.hef` + `labels.txt`).

## Detection Configuration

bugcam ships with default detection parameters in `bugcam/detection.yaml` (bundled with the package). These values control motion detection, blob filtering, and insect tracking behavior.

### Using Custom Detection Config
```bash
# Use custom config with run command
bugcam run --detection-config /path/to/custom.yaml

# Use custom config with process command
bugcam process --detection-config /path/to/custom.yaml
```

If no `--detection-config` is specified, the bundled default is used.

### Detection Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `gmm_history` | 500 | Background subtractor history length |
| `gmm_var_threshold` | 16 | GMM variance threshold |
| `morph_kernel_size` | 5 | Morphological filter kernel size (pixels) |
| `min_area` | 0.00012 | Min detection area (fraction of 4K frame, ~995 px²) |
| `max_area` | 0.0015 | Max detection area (fraction of 4K frame, ~12,440 px²) |
| `min_density` | 3.0 | Min blob density (area/perimeter) |
| `min_solidity` | 0.55 | Min convex hull fill ratio |
| `min_largest_blob_ratio` | 0.85 | Min ratio of largest blob to total motion |
| `max_num_blobs` | 3 | Max number of motion blobs to consider |
| `min_motion_ratio` | 0.20 | Min ratio of motion pixels to frame |
| `min_displacement` | 0.25 | Min net path displacement (fraction of frame width) |
| `min_path_points` | 10 | Min number of path points for valid track |
| `max_frame_jump` | 0.06 | Max single-step centroid jump (fraction of frame width) |
| `max_lost_frames` | 45 | Max frames a track can be lost before finalizing |
| `max_area_change_ratio` | 3.0 | Max allowed area change between frames |
| `tracker_w_dist` | 0.6 | Distance weight for Hungarian tracker matching |
| `tracker_w_area` | 0.4 | Area weight for Hungarian tracker matching |
| `tracker_cost_threshold` | 0.25 | Max cost threshold for tracker matching |
| `revisit_radius` | 0.025 | Radius for detecting path revisits (fraction of frame width) |
| `max_revisit_ratio` | 0.30 | Max ratio of path points that are revisits |
| `min_progression_ratio` | 0.70 | Min ratio of path moving forward vs backward |
| `max_directional_variance` | 0.85 | Max variance in path direction |

For more details on these parameters, see the comments in `bugcam/detection.yaml`.

## Storage Configuration

By default, bugcam stores data on the SD card. For better performance (avoid "frame queue full" errors), use an external USB drive.

| Storage Type | Write Speed | Sustained Performance |
|--------------|-------------------|----------------------|
| SD Card (Class 10) | 10-40 MB/s | Degrades as it fills up |
| USB 3.0 Flash Drive | 20-100 MB/s | More consistent |
| USB 3.0 SSD | 200-500+ MB/s | Very stable |

### Configuration Methods (in order of precedence):

1. **CLI options** (per run):
   ```bash
   bugcam run --input-dir /media/pi/4549-BC23/bugcam/incoming \
                 --output-dir /media/pi/4549-BC23/bugcam/outputs
   ```

2. **Config file** (persistent, set during `bugcam setup`):
   ```json
   {
     "input_dir": "/media/pi/4549-BC23/bugcam/incoming",
     "output_dir": "/media/pi/4549-BC23/bugcam/outputs",
     "state_dir": "/media/pi/4549-BC23/bugcam/state"
   }
   ```

3. **Environment variables** (persistent in shell):
   ```bash
   export BUGCAM_INPUT_DIR="/media/pi/4549-BC23/bugcam/incoming"
   export BUGCAM_OUTPUT_DIR="/media/pi/4549-BC23/bugcam/outputs"
   export BUGCAM_STATE_DIR="/media/pi/4549-BC23/bugcam/state"
   ```

During `bugcam setup`, external drives are automatically detected and offered as storage locations.

## Requirements

- Raspberry Pi 5 with 8GB RAM
- Raspberry Pi AI HAT+ (Hailo-8L or Hailo-8)
- Pi Camera (HQ Camera recommended)
- Optional SEN55 environmental sensor on I2C for `bugcam environment` and periodic environment uploads
- Python 3.11+
- Raspberry Pi OS Bookworm 64-bit
- `build-essential` and `libcjson-dev` for building the bundled SEN55 reader

## DOT Sensors

DOTs are mobile devices (iPhones) that detect insects and send data to a FLICK (Raspberry Pi) for classification. Run `bugcam dot-info` on the FLICK to see full setup instructions.

The FLICK runs a **DOT Receiver** server (started by default with `bugcam run`) that accepts HTTP uploads from iOS devices on port 5001.

### DOT Receiver Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/upload_crops` | POST | Receive crop images for a track |
| `/upload_labels` | POST | Receive bounding box labels |
| `/upload_done` | POST | Signal track completion |
| `/upload_background` | POST | Receive reference background image |
| `/upload_video` | POST | Receive video file |
| `/api/track` | POST | Alternative track telemetry endpoint |
| `/api/heartbeat` | GET/POST | Connection test |
| `/api/health` | GET | Health check |

### Data Structure

Each DOT puts files in the FLICK's input folder using this structure:

```
{dot_id}_{YYYYMMDD}/
├── crops/{track_id}_{HHMMSS}/
│   ├── frame_000001.jpg
│   └── done.txt                ← signals track is ready to process
├── labels/{track_id}.json      ← bounding boxes per frame
├── videos/{dot_id}_{YYYYMMDD}_{HHMMSS}.mp4
└── {HHMMSS}_background.jpg     ← reference frame without insects
```

DOTs also write heartbeat and environment data to the output folder:

```
{dot_id}/
├── heartbeats/{YYYYMMDD_HHMMSS}.json
└── environment/{YYYYMMDD_HHMMSS}.json
```

DOT IDs are auto-generated during `bugcam setup` (e.g. `garden-london-1-dot01`). The receiver automatically assigns DOT IDs to connecting iOS devices from the configured `dot_ids` list.

## Development

```bash
git clone https://github.com/MIT-Senseable-City-Lab/sensing-garden.git
cd sensing-garden
poetry install
poetry run bugcam --help
```

## License

MIT
