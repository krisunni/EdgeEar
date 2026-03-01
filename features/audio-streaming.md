# Live Audio Streaming

## Overview
HTTP chunked WAV stream from backend to browser for live radio audio playback.

## Status
`planned` — See [.state/features.json](../.state/features.json)

## Components
- [audio-router](../components/audio-router.md)

## Requirements
- Flask streaming response support
- WAV header construction for streaming

## Implementation Notes
See [implementation-plans/phase-4-audio-router.md](../implementation-plans/phase-4-audio-router.md)

## Exit Criteria
- [ ] Browser `<audio>` element plays live stream
- [ ] Stream reconnects on drop
- [ ] No buffering issues or memory leaks
