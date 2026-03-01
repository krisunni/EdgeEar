# Frontend (Console UI)

## Overview
Single-page web interface — preset selector, signal meter, audio player, transcript feed, squelch/gain controls. Vanilla JS + Web Audio API + Socket.IO client.

## Status
`planned` — See [.state/components.json](../.state/components.json)

## Technology
HTML, CSS, Vanilla JS, Web Audio API, Socket.IO client

## Interfaces
- **Input:** Socket.IO events from Flask backend
- **Output:** REST API calls for tuning/control, audio element for `/audio-stream`

## Sub-components
- PresetSelector — category tabs, preset buttons
- SignalMeter — canvas-based bar (green/yellow/red)
- AudioPlayer — hidden `<audio>` with custom controls
- TranscriptFeed — scrolling div with auto-scroll
- ControlBar — squelch slider, gain selector, stop button

## Dependencies
- `flask-app` component

## Notes
See [architecture/design.md](../architecture/design.md) §3.7 for full specification.
