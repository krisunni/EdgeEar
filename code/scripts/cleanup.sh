#!/bin/bash
# Kill orphaned ravenSDR-related processes (rtl_fm, dump1090, ffmpeg)

echo "Checking for orphaned processes..."

found=0
for proc in rtl_fm dump1090 ffmpeg; do
    pids=$(pgrep -f "$proc" 2>/dev/null)
    if [ -n "$pids" ]; then
        echo "  Killing $proc: $pids"
        pkill -f "$proc"
        found=1
    fi
done

if [ "$found" -eq 0 ]; then
    echo "  No orphaned processes found."
else
    sleep 1
    # Force-kill any survivors
    for proc in rtl_fm dump1090 ffmpeg; do
        pids=$(pgrep -f "$proc" 2>/dev/null)
        if [ -n "$pids" ]; then
            echo "  Force-killing $proc: $pids"
            pkill -9 -f "$proc"
        fi
    done
    echo "Done."
fi
