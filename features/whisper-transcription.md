# Whisper Speech-to-Text

## Overview
Real-time Whisper inference on Hailo-8L NPU with silence detection and automatic CPU fallback via faster-whisper.

## Status
`planned` — See [.state/features.json](../.state/features.json)

## Components
- [transcriber](../components/transcriber.md)

## Requirements
- Hailo SDK installed (optional — CPU fallback available)
- Whisper .hef model for Hailo-8L
- numpy for RMS silence detection

## Implementation Notes
See [implementation-plans/phase-3-transcriber.md](../implementation-plans/phase-3-transcriber.md)

## Exit Criteria
- [ ] Whisper produces transcript text from PCM audio
- [ ] Silence detection skips quiet chunks
- [ ] CPU fallback works when Hailo is absent
