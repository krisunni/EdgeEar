# Tuner (RTL-FM Process Manager)

## Overview
Manages the `rtl_fm` subprocess lifecycle for SDR mode — start/stop/retune, reads raw PCM from stdout, distributes to audio and whisper queues.

## Status
`planned` — See [.state/components.json](../.state/components.json)

## Technology
Python, subprocess, rtl_fm, threading

## Interfaces
- **Input:** Frequency, mode, squelch, gain parameters from Flask API
- **Output:** 16kHz mono PCM chunks to `audio_pipe` and `whisper_pipe` queues

## Configuration
- rtl_fm command: `rtl_fm -f {freq} -M {mode} -s 200k -r 16k -l {squelch} -g {gain} -`
- Chunk size: 4096 bytes

## Dependencies
- `rtl-sdr` system package
- RTL-SDR Blog V4 USB dongle

## Notes
See [architecture/design.md](../architecture/design.md) §3.1 for full specification.
