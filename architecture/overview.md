# ravenSDR — Architecture Overview

## System Diagram

```
┌─────────────────────────┐     ┌──────────────────────────────┐
│  MODE A: SDR (hardware) │     │  MODE B: Web Stream (no SDR) │
│                         │     │                              │
│  [RTL-SDR Blog V4 USB]  │     │  [LiveATC / NOAA / Public    │
│           │             │     │   Icecast streams]           │
│           ▼ USB         │     │           │                  │
│  [rtl_fm subprocess]    │     │  [ffmpeg subprocess]         │
│  RF → raw 16kHz PCM     │     │  MP3/AAC stream → 16kHz PCM  │
└────────────┬────────────┘     └──────────────┬───────────────┘
             │                                 │
             └──────────────┬──────────────────┘
                            ▼
               [InputSource abstraction layer]
               (same PCM queue regardless of mode)
                            │
              ┌─────────────┴──────────────────┐
              ▼                                ▼
  [Hailo Whisper NPU /            [HTTP /audio-stream endpoint]
   faster-whisper CPU]             (browser plays live audio)
              │
              ▼
    [Transcript queue]
              │
              ▼
  [Socket.IO push → Browser]
              │
              ▼
  [ravenSDR Console — live transcript UI]
```

## Design Principles

1. **Source-agnostic pipeline** — InputSource abstraction ensures downstream components never know whether audio comes from SDR or web stream
2. **Hardware-optional development** — Full pipeline testable on any laptop via Web Stream mode and faster-whisper CPU fallback
3. **Single-page simplicity** — No build tools, no framework, vanilla JS frontend
4. **Subprocess isolation** — rtl_fm and ffmpeg run as managed subprocesses, not in-process
5. **Real-time delivery** — Socket.IO WebSocket for sub-second transcript and signal updates

## Data Flow

1. **Input** → RTL-SDR (rtl_fm) or web stream (ffmpeg) produces 16kHz mono 16-bit PCM
2. **Distribution** → InputSource reads 4096-byte chunks, pushes to `audio_pipe` and `whisper_pipe` queues
3. **Audio** → Audio Router wraps PCM in WAV headers, serves as chunked HTTP stream
4. **Transcription** → Transcriber accumulates 2-5s chunks, runs silence detection, invokes Whisper
5. **Delivery** → Flask-SocketIO pushes transcript segments, signal levels, and status to browser clients

## Key References

- Full technical design: [architecture/design.md](design.md)
- Component details: [.state/components.json](../.state/components.json)
- Implementation plans: [implementation-plans/](../implementation-plans/)
