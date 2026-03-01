# Phase 11 — Inference Stats Dashboard

## Objective
Surface real-time NPU/CPU inference performance metrics in the web UI so users can monitor transcription pipeline health and throughput.

## Scope
- Instrument transcriber with timing and counters
- New Socket.IO event for stats broadcast
- REST endpoint for current stats snapshot
- Stats panel in frontend UI

---

## Sub-Phase 11.1 — Transcriber Instrumentation

### Tasks

| ID | Task | Status |
|---|---|---|
| T055 | Add timing instrumentation to Hailo inference loop | planned |
| T056 | Add timing instrumentation to CPU fallback loop | planned |
| T057 | Track running counters (chunks, tokens, silence skips) | planned |
| T058 | Emit `inference_stats` Socket.IO event after each chunk | planned |

### Files to Modify

| File | Change |
|---|---|
| `code/ravensdr/transcriber.py` | Add timing around encoder/decoder runs, maintain stats dict, emit stats event |

### Key Implementation

```python
# Stats tracking — added to Transcriber class

import time

class Transcriber:
    def __init__(self, pcm_queue, emit_fn):
        # ... existing init ...
        self._stats = {
            "backend": "none",           # "hailo", "cpu", "none"
            "chunks_processed": 0,
            "chunks_skipped_silence": 0,
            "total_tokens": 0,
            "last_encoder_ms": 0,
            "last_decoder_ms": 0,
            "last_total_ms": 0,
            "last_tokens": 0,
            "last_tokens_per_sec": 0.0,
            "last_rtf": 0.0,             # real-time factor
            "last_decoder_steps": 0,
            "max_decoder_steps": DECODER_SEQUENCE_LENGTH,
            "audio_duration_s": 0.0,     # duration of last segment
        }

    @property
    def stats(self):
        return dict(self._stats)
```

**Hailo inference loop additions:**

```python
# Inside _inference_loop_hailo, around the encoder/decoder runs:

# --- Encoder ---
t_enc_start = time.monotonic()
encoder_configured.run([encoder_bindings], timeout_ms)
t_enc_end = time.monotonic()

# --- Decoder loop ---
t_dec_start = time.monotonic()
for i in range(DECODER_SEQUENCE_LENGTH - 1):
    # ... existing decoder iteration ...
    if next_token == self._tokenizer.eos_token_id:
        break
t_dec_end = time.monotonic()

# --- Stats ---
encoder_ms = (t_enc_end - t_enc_start) * 1000
decoder_ms = (t_dec_end - t_dec_start) * 1000
total_ms = encoder_ms + decoder_ms
n_tokens = len(generated_tokens)
audio_s = len(chunk) / (SAMPLE_RATE * 2)  # bytes to seconds

self._stats.update({
    "backend": "hailo",
    "chunks_processed": self._stats["chunks_processed"] + 1,
    "total_tokens": self._stats["total_tokens"] + n_tokens,
    "last_encoder_ms": round(encoder_ms, 1),
    "last_decoder_ms": round(decoder_ms, 1),
    "last_total_ms": round(total_ms, 1),
    "last_tokens": n_tokens,
    "last_tokens_per_sec": round(n_tokens / (decoder_ms / 1000), 1) if decoder_ms > 0 else 0,
    "last_rtf": round((total_ms / 1000) / audio_s, 3) if audio_s > 0 else 0,
    "last_decoder_steps": n_tokens,
    "audio_duration_s": round(audio_s, 1),
})

self.emit_fn("inference_stats", self._stats)
```

**CPU fallback:** Only total inference time is measurable (faster-whisper is a black box). `last_encoder_ms` and `last_decoder_ms` are both 0, `last_total_ms` captures the full `_transcribe_cpu()` call.

**Silence skip counting:**

```python
if not is_signal_present(chunk):
    self._stats["chunks_skipped_silence"] += 1
    continue
```

### Verification
- `inference_stats` event emitted after every non-silent chunk
- Hailo stats include separate encoder/decoder timing
- CPU stats include total inference time
- Silence skip counter increments correctly
- Stats dict is thread-safe (single writer thread)

---

## Sub-Phase 11.2 — Backend API

### Tasks

| ID | Task | Status |
|---|---|---|
| T059 | Add `GET /api/stats` endpoint | planned |
| T060 | Add periodic `inference_stats` broadcast (every 5s summary) | planned |

### Files to Modify

| File | Change |
|---|---|
| `code/ravensdr/app.py` | Add stats route and periodic broadcast |

### Key Implementation

```python
@app.route("/api/stats")
def get_stats():
    if transcriber:
        return jsonify(transcriber.stats)
    return jsonify({})
```

The per-chunk `inference_stats` event (from Sub-Phase 11.1) fires on every inference. Additionally, a periodic 5s summary broadcast ensures the UI stays updated even during silence:

```python
def stats_broadcast_loop():
    while True:
        if transcriber:
            socketio.emit("inference_stats", transcriber.stats)
        socketio.sleep(5)
```

### Verification
- `GET /api/stats` returns current stats JSON
- Stats update in real-time after each inference
- Periodic broadcast keeps UI current during silence

---

## Sub-Phase 11.3 — Frontend Stats Panel

### Tasks

| ID | Task | Status |
|---|---|---|
| T061 | Add stats panel section to index.html | planned |
| T062 | Implement stats rendering in ravensdr.js | planned |
| T063 | Style stats panel in ravensdr.css | planned |

### Files to Modify

| File | Change |
|---|---|
| `code/templates/index.html` | Add stats panel markup |
| `code/static/ravensdr.js` | Subscribe to `inference_stats`, update DOM |
| `code/static/ravensdr.css` | Stats panel styling |

### Key Implementation

**Stats panel layout:**

```html
<div id="stats-panel" class="panel">
    <div class="stats-grid">
        <div class="stat">
            <span class="stat-label">Backend</span>
            <span class="stat-value" id="stat-backend">—</span>
        </div>
        <div class="stat">
            <span class="stat-label">Inference</span>
            <span class="stat-value" id="stat-latency">— ms</span>
        </div>
        <div class="stat">
            <span class="stat-label">RTF</span>
            <span class="stat-value" id="stat-rtf">—</span>
        </div>
        <div class="stat">
            <span class="stat-label">Tokens/s</span>
            <span class="stat-value" id="stat-tps">—</span>
        </div>
        <div class="stat">
            <span class="stat-label">Decoder</span>
            <span class="stat-value" id="stat-decoder">—/32</span>
        </div>
        <div class="stat">
            <span class="stat-label">Processed</span>
            <span class="stat-value" id="stat-chunks">0</span>
        </div>
        <div class="stat">
            <span class="stat-label">Silence</span>
            <span class="stat-value" id="stat-silence">0%</span>
        </div>
    </div>
</div>
```

**Socket.IO handler:**

```javascript
socket.on("inference_stats", (stats) => {
    document.getElementById("stat-backend").textContent =
        stats.backend === "hailo" ? "Hailo NPU" :
        stats.backend === "cpu" ? "CPU" : "None";

    document.getElementById("stat-latency").textContent =
        stats.last_total_ms + " ms";

    document.getElementById("stat-rtf").textContent =
        stats.last_rtf + "x";

    document.getElementById("stat-tps").textContent =
        stats.last_tokens_per_sec;

    document.getElementById("stat-decoder").textContent =
        stats.last_decoder_steps + "/" + stats.max_decoder_steps;

    document.getElementById("stat-chunks").textContent =
        stats.chunks_processed;

    const total = stats.chunks_processed + stats.chunks_skipped_silence;
    const silencePct = total > 0
        ? Math.round((stats.chunks_skipped_silence / total) * 100)
        : 0;
    document.getElementById("stat-silence").textContent = silencePct + "%";

    // Color-code RTF: green if < 0.5, yellow if < 1.0, red if >= 1.0
    const rtfEl = document.getElementById("stat-rtf");
    rtfEl.classList.toggle("stat-good", stats.last_rtf < 0.5);
    rtfEl.classList.toggle("stat-warn", stats.last_rtf >= 0.5 && stats.last_rtf < 1.0);
    rtfEl.classList.toggle("stat-bad", stats.last_rtf >= 1.0);
});
```

**Styling:** Compact horizontal grid below the signal meter. Dark theme consistent with existing console UI. Stats flash briefly on update (CSS transition on opacity).

### Verification
- Stats panel renders below signal meter
- All 7 stat values update on each `inference_stats` event
- Backend shows "Hailo NPU" or "CPU" correctly
- RTF color-codes green/yellow/red
- Silence percentage calculates correctly
- Panel works when no backend is available (shows "None", dashes)

---

## Exit Criteria
- [ ] Encoder and decoder timing measured per-chunk on Hailo path
- [ ] CPU fallback reports total inference time
- [ ] Silence skip counter tracks filtered chunks
- [ ] `inference_stats` Socket.IO event fires per-chunk and every 5s
- [ ] `GET /api/stats` returns current stats JSON
- [ ] Frontend stats panel displays all 7 metrics
- [ ] RTF color-coding reflects real-time performance
- [ ] Stats panel does not affect existing UI layout

## Risks

| Risk | Mitigation |
|---|---|
| `time.monotonic()` overhead in hot loop | Negligible — two calls per chunk, nanosecond resolution |
| Stats emit floods Socket.IO on fast chunks | Per-chunk emit is fine; VAD segments are 1-15s apart. Periodic 5s broadcast is the fallback |
| CPU fallback has no encoder/decoder breakdown | Show total time only, set encoder/decoder fields to 0 |
| Stats panel clutters small screens | Collapsible panel, hidden by default on mobile viewports |
