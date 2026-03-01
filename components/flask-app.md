# Flask Application (Backend API)

## Overview
Flask + Flask-SocketIO server — REST API routes for tuning/control, WebSocket events for real-time transcript/status/signal delivery, thread orchestration.

## Status
`planned` — See [.state/components.json](../.state/components.json)

## Technology
Python, Flask, Flask-SocketIO, eventlet

## Interfaces
- **REST:** GET `/`, `/api/presets`, `/api/status`; POST `/api/tune`, `/api/stop`, `/api/squelch`, `/api/gain`
- **WebSocket:** `transcript`, `status`, `signal_level`, `mode`, `error` events
- **Audio:** GET `/audio-stream` (chunked WAV)

## Configuration
- Port: 5000
- 4 threads: Flask main, _read_loop, _inference_loop, signal_meter_loop

## Dependencies
- `input-source`, `transcriber`, `audio-router`, `presets` components

## Notes
See [architecture/design.md](../architecture/design.md) §3.6 for full specification.
