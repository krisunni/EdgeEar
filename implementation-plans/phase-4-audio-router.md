# Phase 4 — Audio Router (HTTP Streaming)

## Objective
Implement HTTP chunked audio streaming so the browser can play live radio audio.

## Scope
- WAV header construction (streaming format)
- Flask `/audio-stream` route with chunked response
- Optional volume/gain normalization

---

## Sub-Phase 4.1 — WAV Streaming

### Tasks

| ID | Task | Status |
|---|---|---|
| T011 | Implement audio_router.py | planned |
| T012 | Implement /audio-stream Flask route | planned |

### Files to Create

| File | Purpose |
|---|---|
| `code/ravensdr/audio_router.py` | WAV header + HTTP streaming |

### Verification
- `curl http://localhost:5000/audio-stream | file -` identifies WAV format
- Browser `<audio>` element plays the stream
- No memory leak on long-running streams
- Cache-Control and X-Accel-Buffering headers set

---

## Exit Criteria
- [ ] WAV header with 0xFFFFFFFF streaming size
- [ ] Browser plays live audio
- [ ] Stream recovers from queue timeout
- [ ] No proxy buffering issues

## Risks

| Risk | Mitigation |
|---|---|
| Browser audio element compatibility | Test Chrome, Firefox; fallback to Web Audio API |
| Proxy buffering | X-Accel-Buffering: no header |
