#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Installing system packages for Arch Linux..."
if ! command -v pacman >/dev/null 2>&1; then
  echo "pacman not found. Are you on Arch Linux? Aborting."
  exit 1
fi

sudo pacman -Syu --needed --noconfirm \
  python python-pip python-virtualenv python-pyserial python-pyqt5 python-pyqtgraph

echo "Creating virtual environment and installing Python dependencies..."
cd "$ROOT_DIR"
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "Installation complete. Activate the venv with: source .venv/bin/activate"

echo "If your user needs permission to read USB devices, consider installing the udev rule in 'udev/99-emgplusimu.rules' and reloading udev:"
echo "  sudo cp udev/99-emgplusimu.rules /etc/udev/rules.d/"
echo "  sudo udevadm control --reload"

exit 0
