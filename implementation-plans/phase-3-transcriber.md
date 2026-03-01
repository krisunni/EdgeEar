# Phase 3 — Transcriber (Hailo Whisper)

## Objective
Implement Whisper speech-to-text with Hailo-8L NPU acceleration, silence detection, and automatic CPU fallback.

## Scope
- PCM chunk accumulation (2-5 second windows)
- RMS-based silence/squelch detection
- Hailo Whisper inference via hailo-apps SDK
- faster-whisper CPU fallback
- Transcript segment output with metadata

---

## Sub-Phase 3.1 — Silence Detection & Chunking

### Tasks

| ID | Task | Status |
|---|---|---|
| T010 | Implement silence/squelch detection | planned |

### Verification
- RMS calculation matches expected values
- Silent chunks are skipped
- Signal chunks are passed to inference

---

## Sub-Phase 3.2 — Whisper Inference

### Tasks

| ID | Task | Status |
|---|---|---|
| T008 | Implement Transcriber class | planned |
| T009 | Implement faster-whisper CPU fallback | planned |

### Files to Create

| File | Purpose |
|---|---|
| `code/ravensdr/transcriber.py` | Hailo Whisper wrapper + CPU fallback |

### Verification
- Hailo inference produces transcript text
- CPU fallback produces same format output
- Transcript segments include timestamp, freq, label, text, rms
- No crash on empty/noisy audio

---

## Exit Criteria
- [ ] Transcriber produces text from radio audio
- [ ] Silence detection prevents wasted inference cycles
- [ ] CPU fallback works transparently
- [ ] Transcript format matches Socket.IO event schema

## Risks

| Risk | Mitigation |
|---|---|
| Whisper .hef model not available for Hailo-8L | Use faster-whisper CPU mode for development |
| Poor accuracy on noisy radio | Tune SILENCE_THRESHOLD, consider RNNoise pre-filter |
| Hailo SDK API changes | Pin SDK version in setup.sh |
