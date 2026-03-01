# Stream Source (Web Stream Ingest)

## Overview
Pulls live audio from public internet streams (LiveATC, NOAA) via ffmpeg subprocess, converts to 16kHz mono PCM for the pipeline.

## Status
`planned` — See [.state/components.json](../.state/components.json)

## Technology
Python, subprocess, ffmpeg

## Interfaces
- **Input:** Stream URL from preset definition
- **Output:** 16kHz mono PCM chunks to shared `pcm_queue`

## Configuration
- ffmpeg command: `ffmpeg -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -i {url} -vn -acodec pcm_s16le -ar 16000 -ac 1 -f s16le pipe:1`
- Chunk size: 4096 bytes

## Dependencies
- `ffmpeg` system package

## Notes
See [architecture/design.md](../architecture/design.md) §3.2 for full specification.
