# Error Handling & Auto-Recovery

## Overview
Graceful handling of SDR disconnect, rtl_fm crash, stream drops, ALSA issues, and Hailo NPU absence.

## Status
`planned` — See [.state/features.json](../.state/features.json)

## Components
- [flask-app](../components/flask-app.md)
- [tuner](../components/tuner.md)
- [stream-source](../components/stream-source.md)
- [transcriber](../components/transcriber.md)

## Requirements
- SDR polling every 10 seconds
- Subprocess crash detection via process.poll()
- Browser audio reconnect logic
- Hailo import fallback

## Implementation Notes
See [implementation-plans/phase-8-error-handling.md](../implementation-plans/phase-8-error-handling.md)

## Exit Criteria
- [ ] SDR disconnect shows banner, auto-recovers
- [ ] rtl_fm crash detected and reported
- [ ] Browser audio reconnects after drop
- [ ] Hailo absence falls back to CPU gracefully
