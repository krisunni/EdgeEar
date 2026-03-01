#!/usr/bin/env bash
# ravenSDR — Start the application
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -d "$SCRIPT_DIR/venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$SCRIPT_DIR/venv"
    "$SCRIPT_DIR/venv/bin/pip" install -r "$SCRIPT_DIR/code/requirements.txt"
fi

source "$SCRIPT_DIR/venv/bin/activate"
python3 "$SCRIPT_DIR/code/ravensdr/app.py"
