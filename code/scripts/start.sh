#!/bin/bash
# Start ravenSDR in background with PID tracking and log file
#
# Usage:
#   ./scripts/start.sh          # start
#   ./scripts/stop.sh           # stop (see stop.sh)
#   tail -f ravensdr.log        # follow logs

cd "$(dirname "$0")/.." || exit 1

PIDFILE="ravensdr.pid"
LOGFILE="ravensdr.log"

# Check if already running
if [ -f "$PIDFILE" ]; then
    PID=$(cat "$PIDFILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "ravenSDR already running (PID $PID)"
        echo "  Stop with: ./scripts/stop.sh"
        echo "  Logs:      tail -f $LOGFILE"
        exit 1
    else
        echo "Stale PID file (process $PID not running), removing"
        rm -f "$PIDFILE"
    fi
fi

# Activate venv if present
if [ -f "../.venv/bin/activate" ]; then
    source "../.venv/bin/activate"
elif [ -f ".venv/bin/activate" ]; then
    source ".venv/bin/activate"
fi

echo "Starting ravenSDR..."
nohup python3 -m ravensdr.app >> "$LOGFILE" 2>&1 &
PID=$!
echo "$PID" > "$PIDFILE"

echo "ravenSDR started (PID $PID)"
echo "  Logs: tail -f $LOGFILE"
echo "  Stop: ./scripts/stop.sh"
