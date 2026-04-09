# Installation

Complete installation guide for setting up bugcam on a fresh Raspberry Pi 5.

## Prerequisites

### Hardware
- Raspberry Pi 5 with fresh Raspbian OS installed
- Raspberry Pi Camera Module 3 physically connected
- Raspberry Pi AI HAT+ (Hailo-8 or Hailo-8L) physically attached
- Active cooler recommended for sustained operation

See [Hardware Setup Guide](hardware-setup.md) for physical assembly instructions.

### Physical Setup Verification
Ensure the AI HAT is properly connected as shown in the [Raspberry Pi AI HAT+ documentation](https://www.raspberrypi.com/documentation/accessories/ai-hat-plus.html).

## Step 1: Update System Packages

Start with a fresh system update:

```bash
sudo apt update && sudo apt upgrade -y
```

## Step 2: Install System Dependencies

### Hailo Hardware Drivers (Required)

The Hailo AI HAT+ requires the `hailo-all` package for hardware drivers and runtime:

```bash
sudo apt install hailo-all
```

This package provides:
- Hailo hardware drivers
- Runtime libraries for AI acceleration
- Required system-level dependencies

**Note:** This cannot be installed via pip - it must be installed system-wide via apt.

### Camera Setup

Verify the camera is detected:

```bash
rpicam-hello
```

You should see a camera preview window for about 5 seconds.

**If the camera test fails:**

1. Enable the camera interface in `raspi-config`:
```bash
sudo raspi-config
```

2. Navigate to: `Interface Options` > `Camera` > `Enable`

3. Reboot when prompted:
```bash
sudo reboot
```

4. After reboot, test again with `rpicam-hello`

## Step 3: Install bugcam

You have two installation options:

### Option A: System-Wide Install (Simplest)

Install bugcam directly with pip:

```bash
pip install bugcam
```

The `bugcam` command will be immediately available in your PATH.

### Option B: Isolated Install with pipx (Recommended)

For a cleaner, isolated installation:

```bash
# Install pipx
sudo apt install pipx

# Add pipx binaries to PATH
pipx ensurepath

# IMPORTANT: Close and reopen your terminal for PATH changes to take effect
# You can verify with: echo $PATH | grep pipx

# Install bugcam in isolated environment
pipx install bugcam
```

**Why pipx?**
- Installs CLI tools in isolated environments
- Prevents dependency conflicts with system packages
- Keeps your system Python clean

### Option C: Development Installation

For contributors or advanced users who want to modify the code:

```bash
# Clone the repository
git clone https://github.com/MIT-Senseable-City-Lab/sensing-garden.git
cd sensing-garden

# Install with poetry (includes dev dependencies)
poetry install

# OR install locally with pip
pip install -e .
```

## Step 4: Verify Installation

Check that bugcam is installed correctly:

```bash
bugcam --version
bugcam --help
```

You should see version information and available commands.

## Step 5: Download Detection Models

**IMPORTANT:** Detection models must be downloaded before running bugcam. They are not bundled with the installation.

Download a detection model from S3:

```bash
# Download the small model (11MB, faster inference)
bugcam models download yolov8s

# OR download the medium model (31MB, more accurate)
bugcam models download yolov8m
```

Models are cached in `~/.cache/bugcam/models/` after download.

**Verify model installation:**

```bash
# List installed models
bugcam models list

# Show model details
bugcam models info yolov8s
```

## Step 6: Test Detection

Now you're ready to run detection:

```bash
# Preview camera with detection overlay
bugcam preview

# Start continuous detection
bugcam detect start

# Save detections to file
bugcam detect start --output detections.jsonl

# Enable autostart on boot (uses systemd)
bugcam autostart enable
```

See the [CLI Reference](../cli-reference.md) for complete command documentation.

## Troubleshooting

### Command not found after installation

If `bugcam` command is not found after installation:

**For pip install:**
```bash
# Add local bin to PATH
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

**For pipx install:**
```bash
# Re-run ensurepath and restart terminal
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
```

## What Gets Installed Where

**System dependencies (via apt):**
- `hailo-all` - Hailo hardware drivers (cannot be pip installed)
- `pipx` - Tool installer (optional, for isolated install)

**Python packages (via pip/pipx):**
- `bugcam` - Main CLI tool
- All Python dependencies (typer, rich, boto3, numpy, opencv-python, etc.)

**Downloaded after install:**
- Detection models - Downloaded via `bugcam models download` to `~/.cache/bugcam/models/`

**Note:** Models in `resources/` directory are for development only and not included in package installations.

## Development Setup

For contributors who want to modify bugcam:

```bash
# Clone the repository
git clone https://github.com/MIT-Senseable-City-Lab/sensing-garden.git
cd sensing-garden

# Install with poetry (includes dev dependencies)
poetry install

# Run from source
poetry run bugcam --help

# Run development scripts (use models from resources/)
source setup_env.sh
python basic_pipelines/detection.py --input rpi --hef-path resources/yolov8m.hef
```

When using development scripts, models are loaded from `resources/` directory. For CLI usage, models must be downloaded with `bugcam models download`.
