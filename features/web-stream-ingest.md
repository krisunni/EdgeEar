# Web Stream Ingest

## Overview
Pull live audio from public internet streams (LiveATC, NOAA via wxradio.org) using ffmpeg subprocess when no SDR hardware is present.

## Status
`planned` — See [.state/features.json](../.state/features.json)

## Components
- [stream-source](../components/stream-source.md)
- [input-source](../components/input-source.md)

## Requirements
- `ffmpeg` installed
- Internet connectivity
- Valid stream URLs in presets

## Implementation Notes
See [implementation-plans/phase-2-input-source.md](../implementation-plans/phase-2-input-source.md)

## Exit Criteria
- [ ] ffmpeg connects to stream and produces PCM output
- [ ] Stream switching works (kill + restart subprocess)
- [ ] Reconnect on stream drop (3 retries)
