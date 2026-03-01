# Phase 8 — Error Handling & Edge Cases

## Objective
Implement graceful error handling and auto-recovery for all failure scenarios.

## Scope
- SDR disconnect detection and recovery
- rtl_fm process crash handling
- Browser audio stream reconnection
- ALSA loopback verification
- Hailo NPU absence fallback

---

## Sub-Phase 8.1 — SDR & Process Recovery

### Tasks

| ID | Task | Status |
|---|---|---|
| T021 | Implement SDR disconnect recovery | planned |
| T022 | Implement rtl_fm crash recovery | planned |

### Verification
- Unplugging SDR shows error banner within 10s
- Re-plugging SDR auto-recovers
- rtl_fm crash detected via process.poll()
- Error event emitted to all clients

---

## Sub-Phase 8.2 — Browser & Hardware Fallbacks

### Tasks

| ID | Task | Status |
|---|---|---|
| T023 | Implement browser audio reconnect | planned |
| T024 | Implement Hailo NPU fallback detection | planned |

### Verification
- Audio element reconnects after stream drop (2s delay)
- "Reconnecting audio..." indicator shown
- Hailo import failure falls back to faster-whisper
- "CPU mode" badge shown in UI

---

## Exit Criteria
- [ ] SDR disconnect → banner → auto-recover
- [ ] rtl_fm crash → error event → retry button
- [ ] Audio stream drop → auto-reconnect
- [ ] Hailo absent → CPU fallback → badge update
- [ ] ALSA missing → startup warning

## Risks

| Risk | Mitigation |
|---|---|
| Rapid SDR connect/disconnect | Debounce detection, don't poll faster than 10s |
| Zombie rtl_fm processes | SIGTERM + SIGKILL fallback in stop() |
