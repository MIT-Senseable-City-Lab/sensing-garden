#!/bin/bash
set -euo pipefail

echo "Installing bugcam..."

if [ ! -f /etc/rpi-issue ]; then
    echo "Warning: This doesn't appear to be Raspberry Pi OS"
fi

sudo apt update
sudo apt install -y hailo-all pipx i2c-tools libcjson-dev build-essential

pipx install 'git+https://github.com/daydemir/sensing-garden.git@bugcam-cli'
pipx ensurepath

echo ""
echo "Installation complete!"
echo "Close and reopen your terminal, then run:"
echo "  bugcam setup"
