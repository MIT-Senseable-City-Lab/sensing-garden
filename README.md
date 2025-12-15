# bugcam - Raspberry Pi Insect Detection

CLI for running insect detection on Raspberry Pi with Hailo AI HAT+.

## Hardware Requirements
- Raspberry Pi 4/5
- Raspberry Pi Camera Module 3
- Raspberry Pi AI HAT+ (Hailo8/Hailo8L)
- Active cooler recommended

## Installation

### 1. System Setup

**Update system packages:**
```bash
sudo apt update && sudo apt upgrade -y
```

**Install Hailo hardware drivers (required for AI HAT+):**
```bash
sudo apt install hailo-all
```

**Verify camera is detected:**
```bash
rpicam-hello
```
If this fails, enable the camera interface in `raspi-config`:
```bash
sudo raspi-config
# Navigate to: Interface Options > Camera > Enable
# Reboot when prompted
```

### 2. Install bugcam

**Option A: System-wide install (simplest)**
```bash
pip install bugcam
```

**Option B: Isolated install with pipx (recommended)**
```bash
# Install pipx
sudo apt install pipx

# Add pipx binaries to PATH
pipx ensurepath

# IMPORTANT: Close and reopen your terminal for PATH changes to take effect
# Then install bugcam
pipx install bugcam
```

### 3. Download Detection Model

```bash
# Download the small model (11MB, faster)
bugcam models download yolov8s

# OR download the medium model (31MB, more accurate)
bugcam models download yolov8m

# List installed models
bugcam models list
```

Models are downloaded from S3 and cached in `~/.cache/bugcam/models/`.

### 4. Run Detection

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

## CLI Reference

### Models

Manage and inspect detection models.

**Download a model:**
```bash
bugcam models download <model_name>
```
Available models: `yolov8s` (11MB, faster), `yolov8m` (31MB, more accurate)

**List installed models:**
```bash
bugcam models list
```

**Show model details:**
```bash
bugcam models info <model_name>
```

### Preview

Run live camera preview with detection overlay.

```bash
# Basic preview
bugcam preview

# Preview with specific model
bugcam preview --model yolov8m
```

Options:
- `--model <name>` - Specify which model to use (default: yolov8m)

### Detection

Run continuous detection and save results.

```bash
# Start detection
bugcam detect start

# Save detections to file
bugcam detect start --output detections.jsonl

# Run for specific duration (in minutes)
bugcam detect start --duration 30

# Quiet mode (suppress console output)
bugcam detect start --quiet

# Combined options
bugcam detect start --model yolov8s --output results.jsonl --duration 60 --quiet
```

Options:
- `--model <name>` - Specify which model to use (default: yolov8m)
- `--output <file>` - Save detections to file (JSONL format)
- `--duration <minutes>` - Run for specified minutes (default: run indefinitely)
- `--quiet` - Suppress console output

**Detection output format (JSONL):**
```json
{"timestamp": "2025-12-14T10:30:45", "class": "insect", "confidence": 0.92, "bbox": [100, 200, 150, 250]}
```

### Autostart (systemd)

Manage automatic detection on system boot.

```bash
# Enable autostart
bugcam autostart enable

# Disable autostart
bugcam autostart disable

# Check status
bugcam autostart status

# View logs
bugcam autostart logs

# Follow logs in real-time
bugcam autostart logs --follow
```

Options:
- `--follow` / `-f` - Follow log output in real-time

## Hotspot Setup

Configure the Raspberry Pi as a wireless access point for field deployments.

### Create hotspot
```bash
# Create hotspot connection
sudo nmcli connection add con-name wlan-sg1 type wifi ifname wlan0 autoconnect yes ssid wlan-sg1 802-11-wireless.mode ap 802-11-wireless.band bg ipv4.method shared

# Secure with password (min 8 characters)
sudo nmcli connection modify wlan-sg1 wifi-sec.key-mgmt wpa-psk
sudo nmcli connection modify wlan-sg1 wifi-sec.psk "yourpassword"

# Activate hotspot
sudo nmcli connection up wlan-sg1
```

### Connect to hotspot
Scan for the network SSID (e.g., wlan-sg1) and use the password to connect. Access via SSH:
```bash
ssh username@hostname.local
```

### Additional commands
```bash
# Stop hotspot
sudo nmcli connection down wlan-sg1

# Enable autostart on boot
sudo nmcli connection modify wlan-sg1 connection.autoconnect yes
```

## Monitoring

### Hailo hardware monitoring
```bash
# In terminal 1: start Hailo monitor
hailortcli monitor

# In terminal 2: enable monitoring and run detection
export HAILO_MONITOR=1
bugcam detect start
```

### System monitoring
```bash
# CPU and memory
top  # or: btop, htop

# Temperature
vcgencmd measure_temp

# Continuous temperature monitoring
watch -n 1 vcgencmd measure_temp

# Service logs
bugcam autostart logs --follow
```

### Performance tips
- Use `yolov8s` for faster inference if accuracy allows
- Use active cooling to prevent thermal throttling
- Use official Raspberry Pi power supply (5V 5A for Pi 5 + AI HAT+)

## Troubleshooting

### Command not found after installation

**For pip install:**
```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

**For pipx install:**
```bash
pipx ensurepath
# Close and reopen terminal
```

### Camera not detected
```bash
# Test camera
rpicam-hello

# If fails, enable in raspi-config
sudo raspi-config
# Interface Options > Camera > Enable
sudo reboot
```

### Hailo driver errors
```bash
# Verify Hailo installation
dpkg -l | grep hailo

# Reinstall if needed
sudo apt install --reinstall hailo-all

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

### Models not found
```bash
# Verify models are downloaded
bugcam models list

# Download if needed
bugcam models download yolov8m

# Check cache directory
ls -lh ~/.cache/bugcam/models/
```

## Development

For contributors who want to modify bugcam:

```bash
# Clone the repository
git clone https://github.com/MIT-Senseable-City-Lab/sensing-garden.git
cd sensing-garden

# Install with dev dependencies
poetry install

# Run tests
poetry run pytest tests/ -v

# Run CLI from source
poetry run bugcam --help
```

**Note:** Models in `resources/` directory are for development only and not included in package installations.

## License

MIT
