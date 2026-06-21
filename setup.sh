#!/usr/bin/env bash
# Vidcribe one-time setup: install ffmpeg + openai-whisper.
#
# Usage: ./setup.sh
#
# Creates a local virtualenv (.venv) and installs the Python deps there so the
# system stays self-contained. ffmpeg is installed via the system package
# manager (needs sudo/root the first time).
set -euo pipefail

cd "$(dirname "$0")"

# --- ffmpeg --------------------------------------------------------------- #
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo ">> ffmpeg not found, attempting to install..."
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -y && sudo apt-get install -y ffmpeg
  elif command -v brew >/dev/null 2>&1; then
    brew install ffmpeg
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y ffmpeg
  else
    echo "!! Could not auto-install ffmpeg. Please install it manually." >&2
    exit 1
  fi
else
  echo ">> ffmpeg already installed: $(ffmpeg -version | head -1)"
fi

# --- python deps ---------------------------------------------------------- #
if [ ! -d ".venv" ]; then
  echo ">> creating virtualenv at .venv"
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
echo ">> installing python requirements"
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "Setup complete. Activate the venv with:  source .venv/bin/activate"
echo "Then try:  ./transcribe.py new demo  &&  ./transcribe.py status"
