# Audio Router (HTTP Streaming)

## Overview
Reads PCM from audio queue, wraps in streaming WAV headers, serves as chunked HTTP response for browser audio playback.

## Status
`planned` — See [.state/components.json](../.state/components.json)

## Technology
Python, Flask, WAV

## Interfaces
- **Input:** PCM chunks from `audio_pipe` queue
- **Output:** Chunked HTTP response at `/audio-stream` with `audio/wav` mimetype

## Configuration
- WAV header: streaming convention with `0xFFFFFFFF` size
- Sample rate: 16,000 Hz, 16-bit, mono

## Dependencies
- `input-source` component

## Notes
See [architecture/design.md](../architecture/design.md) §3.5 for full specification.
