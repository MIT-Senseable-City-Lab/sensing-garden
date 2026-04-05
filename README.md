# bugcam

Raspberry Pi insect detection CLI using Hailo AI accelerator and the edge26 processing pipeline.
Records video, detects and classifies insects on-device, and uploads results to S3.

Default API endpoint: `https://api.sensinggarden.com/v1`

## Quick Start

```bash
curl -sSL https://raw.githubusercontent.com/MIT-Senseable-City-Lab/sensing-garden/main/install.sh | bash
bugcam setup
bugcam run
```

## Commands

| Command | Description |
|---------|-------------|
| `bugcam run` | Full pipeline: record + process + upload + heartbeat |
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

## Architecture

- **edge26 pipeline** lives in `bugcam/edge26/` (vendored from the edge26 repo). Handles recording, processing, and output formatting.
- **BugSpot** library handles motion detection and insect tracking.
- **Hailo accelerator** runs classification on detected insects.
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

Models are stored in `~/.cache/bugcam/models/<bundle>/` (each bundle contains `model.hef` + `labels.txt`).

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

DOT IDs are auto-generated during `bugcam setup` (e.g. `garden-london-1-dot01`).

## Development

```bash
git clone https://github.com/MIT-Senseable-City-Lab/sensing-garden.git
cd sensing-garden
poetry install
poetry run bugcam --help
```

## License

MIT
