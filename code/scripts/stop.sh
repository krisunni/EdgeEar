#!/bin/bash
# Stop ravenSDR background process

cd "$(dirname "$0")/.." || exit 1

PIDFILE="ravensdr.pid"

if [ ! -f "$PIDFILE" ]; then
    echo "No PID file found. Searching for running process..."
    PID=$(pgrep -f "python3 -m ravensdr.app" | head -1)
    if [ -n "$PID" ]; then
        echo "Found ravenSDR (PID $PID)"
        kill "$PID"
        echo "Sent SIGTERM to $PID"
    else
        echo "ravenSDR is not running"
    fi
    exit 0
fi

PID=$(cat "$PIDFILE")

if kill -0 "$PID" 2>/dev/null; then
    echo "Stopping ravenSDR (PID $PID)..."
    kill "$PID"
    # Wait up to 10 seconds for graceful shutdown
    for i in $(seq 1 10); do
        if ! kill -0 "$PID" 2>/dev/null; then
            echo "ravenSDR stopped"
            rm -f "$PIDFILE"
            exit 0
        fi
        sleep 1
    done
    echo "Force killing..."
    kill -9 "$PID" 2>/dev/null
    rm -f "$PIDFILE"
    echo "ravenSDR killed"
else
    echo "ravenSDR not running (stale PID $PID)"
    rm -f "$PIDFILE"
fi
