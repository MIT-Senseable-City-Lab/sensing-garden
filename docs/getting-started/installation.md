# Installation

## Clone the repository

Clone the repository on your Raspberry Pi 5:
```bash
git clone https://github.com/MIT-Senseable-City-Lab/sensing-garden.git
cd sensing-garden
```

## Utilizing Raspberry Pi AI HAT+

The pipeline we run in the sensing garden project will be using [Hailo Apps Infra](https://github.com/hailo-ai/hailo-apps-infra) repo as a dependency.

**Requirements**
- numpy < 2.0.0
- setproctitle
- opencv-python

```bash
sudo apt install hailo-all
```

## Setting up the Hailo AI accelerator on the Raspberry Pi 5

*Assuming you have physically connected the AI HAT like shown in the Raspberry Pi documentation: https://www.raspberrypi.com/documentation/accessories/ai-hat-plus.html*

### Installation Script

Run the following script to automate the installation process:

```bash
./install.sh
```

### Manual Installation with Poetry

For development or advanced setups:

```bash
# Install bugcam with poetry
poetry install

# Install with pipx for isolated CLI usage
pipx install .
```

## Running examples

When opening a new terminal session, ensure you have sourced the environment setup script:

```bash
source setup_env.sh
```

To run a full detection example, you need to specify the Raspberry Pi camera as input, and the HEF model you want to run:
```bash
python basic_pipelines/detection.py --input rpi --hef-path resources/yolov8m.hef
```
Make sure to have the HEF model available and the correct path.

## Using the BugCam CLI

After installation, the `bugcam` command is available:

```bash
# Preview camera with detection overlay
bugcam preview

# Start continuous detection
bugcam detect start

# Enable autostart on boot (uses systemd)
bugcam autostart enable
```

See the [CLI Reference](../cli-reference.md) for detailed command documentation.
