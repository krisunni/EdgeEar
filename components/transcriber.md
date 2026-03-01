# Transcriber (Hailo Whisper)

## Overview
Reads PCM from whisper queue, accumulates 2-5 second chunks, runs silence detection, performs Whisper inference on Hailo-8L NPU (or faster-whisper CPU fallback).

## Status
`planned` — See [.state/components.json](../.state/components.json)

## Technology
Python, numpy, hailo-apps SDK, faster-whisper

## Interfaces
- **Input:** PCM chunks from `whisper_pipe` queue
- **Output:** Transcript segments to `transcript_queue` with timestamp, freq, label, text, rms

## Configuration
- Silence threshold: RMS 500
- Chunk size: 48,000 samples (3 seconds at 16kHz)
- Whisper model: `tiny` or `base` (.hef for Hailo)

## Dependencies
- `input-source` component
- Hailo SDK (optional — falls back to faster-whisper)

## Notes
See [architecture/design.md](../architecture/design.md) §3.4 for full specification.
