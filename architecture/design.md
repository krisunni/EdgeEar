# ravenSDR — Technical Design Document

## 1. Overview

ravenSDR is a real-time RF signal transcription pipeline that tunes an RTL-SDR dongle to preset emergency/monitoring frequencies, streams demodulated audio to the browser, and transcribes radio chatter to text using the Raspberry Pi AI Hat (Hailo-8L NPU) running OpenAI Whisper.

When no SDR hardware is present, ravenSDR falls back to **Web Stream Mode** — pulling live audio from public internet streams through the same transcription pipeline.

### Target Hardware
- **SBC:** Raspberry Pi 5
- **NPU:** Hailo AI Hat (Hailo-8L, 13 TOPS)
- **SDR:** RTL-SDR Blog V4 (R828D tuner, RTL2832U, 1PPM TCXO, Bias Tee, SMA, USB)

### Target OS
Raspberry Pi OS (Bookworm, 64-bit)

---

## 2. Tech Stack

| Layer | Technology |
|---|---|
| SDR demodulation (Mode A) | `rtl_fm` (part of `rtl-sdr` package) |
| Web stream ingest (Mode B) | `ffmpeg` subprocess — decodes MP3/AAC → raw PCM |
| Input abstraction | `InputSource` class — unified PCM queue for both modes |
| SDR auto-detection | `rtl_test` subprocess on startup; fallback to Mode B |
| NPU inference | Hailo-8L via `hailo-apps` Python SDK |
| Speech-to-text model | Whisper `tiny` or `base` (.hef compiled for Hailo) |
| CPU fallback | `faster-whisper` (CTranslate2-based) |
| Backend | Python 3.11+, Flask, Flask-SocketIO |
| Audio routing | ALSA loopback (`snd-aloop` kernel module) |
| Audio streaming | HTTP chunked response (WAV/PCM over HTTP) |
| Frontend | Single-file HTML + Vanilla JS + Web Audio API |
| Real-time comms | Socket.IO (WebSocket) |
| Process management | Python `subprocess` with threading |

---

## 3. Component Design

### 3.1 Tuner (`tuner.py`)

RTL-FM process manager for SDR mode.

**Properties:**
- `current_freq` — active frequency string (e.g. `"162.550M"`)
- `current_mode` — demodulation mode: `"fm"`, `"am"`, `"wbfm"`, `"usb"`, `"lsb"`
- `squelch` — integer 0–100 (maps to rtl_fm `-l` flag)
- `gain` — integer or `"auto"` (maps to rtl_fm `-g` flag)
- `is_running` — bool

**Methods:**
- `tune(freq, mode)` — kills existing process, starts new rtl_fm
- `stop()` — SIGTERM, then SIGKILL after 1s
- `set_squelch(level)` — updates and retunes
- `set_gain(value)` — updates and retunes
- `_read_loop()` — background thread; reads 4096-byte chunks from stdout, pushes to both queues

**rtl_fm command:**
```bash
rtl_fm -f {freq} -M {mode} -s 200k -r 16k -l {squelch} -g {gain} -
```

### 3.2 StreamSource (`stream_source.py`)

Web stream ingest via ffmpeg for Mode B.

**ffmpeg command:**
```bash
ffmpeg -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 \
  -i {stream_url} -vn -acodec pcm_s16le -ar 16000 -ac 1 -f s16le pipe:1
```

- Output: raw 16kHz mono 16-bit PCM to stdout (identical format to rtl_fm)
- `_read_loop()` reads 4096-byte chunks into shared `pcm_queue`
- Reconnect flags handle stream drops; after 3 retries, emit Socket.IO error event

### 3.3 InputSource (`input_source.py`)

Unified abstraction over Tuner and StreamSource.

```python
class InputSource:
    def __init__(self, mode: str):   # "SDR" or "WEBSTREAM"
        self.mode = mode
        self.pcm_queue = queue.Queue(maxsize=200)
        self._source = Tuner() if mode == "SDR" else StreamSource()

    def tune(self, preset: dict): ...
    def stop(self): ...
    @property
    def is_running(self) -> bool: ...
```

**Auto-detection:**
```python
def detect_sdr() -> bool:
    result = subprocess.run(["rtl_test", "-t"], capture_output=True, timeout=5)
    return result.returncode == 0
```

### 3.4 Transcriber (`transcriber.py`)

Hailo Whisper wrapper with silence detection and CPU fallback.

**Whisper input requirements:**
- Sample rate: 16,000 Hz
- Bit depth: 16-bit signed PCM
- Channels: mono
- Chunk size: ~32,000 samples (2 seconds) minimum

**Silence detection:**
```python
SILENCE_THRESHOLD = 500   # RMS value
CHUNK_SAMPLES = 48000     # 3 seconds at 16kHz

def is_signal_present(pcm_bytes):
    samples = np.frombuffer(pcm_bytes, dtype=np.int16)
    rms = np.sqrt(np.mean(samples.astype(np.float32)**2))
    return rms > SILENCE_THRESHOLD
```

**Transcript output format:**
```python
{
    "timestamp": "14:32:01",
    "freq": "162.550 MHz",
    "label": "NOAA Seattle",
    "text": "...wind northwest at 12 knots...",
    "rms": 1842.3
}
```

**Fallback:** If `HAILO_AVAILABLE = False`, use `faster-whisper` CPU inference with the same `tiny` model.

### 3.5 Audio Router (`audio_router.py`)

HTTP audio streaming endpoint.

- Reads raw PCM from `audio_pipe` queue
- Wraps in WAV container headers (streaming WAV with `0xFFFFFFFF` size)
- Serves as chunked HTTP response at `/audio-stream`

```python
@app.route("/audio-stream")
def audio_stream():
    def generate():
        yield make_wav_header()
        while True:
            chunk = audio_pipe.get(timeout=5)
            yield chunk
    return Response(stream_with_context(generate()), mimetype="audio/wav")
```

### 3.6 Flask App (`app.py`)

**REST Routes:**

| Method | Route | Purpose |
|---|---|---|
| GET | `/` | Serve the single-page UI |
| GET | `/api/presets` | Return JSON list of all frequency presets |
| POST | `/api/tune` | Switch to a frequency |
| POST | `/api/stop` | Stop audio source |
| POST | `/api/squelch` | Update squelch level |
| POST | `/api/gain` | Update gain |
| GET | `/api/status` | Return current state JSON |
| GET | `/audio-stream` | Chunked WAV audio stream |

**Socket.IO Events (Server → Client):**

| Event | Payload | Description |
|---|---|---|
| `transcript` | `{timestamp, freq, label, text, rms}` | New transcription segment |
| `status` | `{running, freq, label, mode, squelch, gain}` | State change broadcast |
| `signal_level` | `{rms, freq}` | Emitted every 500ms |
| `mode` | `{mode, sdr_available}` | Input mode on connect/change |
| `error` | `{message}` | Error notifications |

**Thread Model:**
1. Flask/SocketIO main thread (HTTP + WebSocket)
2. `tuner._read_loop()` — reads subprocess stdout
3. `transcriber._inference_loop()` — runs Whisper on PCM chunks
4. `signal_meter_loop()` — samples RMS every 500ms

### 3.7 Frontend (`index.html` + `ravensdr.js` + `ravensdr.css`)

Single-page console-style UI with:
- **PresetSelector** — category tabs, preset buttons, custom frequency input
- **SignalMeter** — canvas-based horizontal bar (green/yellow/red)
- **AudioPlayer** — hidden `<audio>` with custom controls, reconnect logic
- **TranscriptFeed** — scrolling div, auto-scroll, clear/copy buttons
- **ControlBar** — squelch slider, gain selector, stop button

### 3.8 Presets (`presets.py`)

**Schema:**
```python
{
    "id": str,           # unique slug
    "label": str,        # display name
    "freq": str,         # rtl_fm format
    "mode": str,         # "fm", "am", "wbfm", "usb", "lsb"
    "category": str,     # "weather", "aviation", "marine", "public_safety", "broadcast"
    "squelch": int,      # preset-specific override (optional)
    "stream_url": str,   # web stream URL (optional)
    "note": str,         # display note (optional)
}
```

**Categories:** Weather (3), Aviation (5), Marine (2), Public Safety (2), Broadcast (2)

---

## 4. Error Handling

| Scenario | Response |
|---|---|
| SDR not connected | Emit error event, UI banner, poll every 10s, auto-recover |
| rtl_fm crash | Monitor with process.poll(), emit error, expose retry button |
| Audio stream drop | Browser resets src after 2s delay |
| ALSA loopback missing | Warn on startup |
| Hailo NPU absent | Auto-fallback to faster-whisper CPU, show "CPU mode" badge |
| Web stream offline | ffmpeg reconnect flags, error after 3 retries |

---

## 5. Known Limitations

| Limitation | Notes |
|---|---|
| One frequency at a time | RTL-SDR can only tune one freq |
| Encrypted P25 | No workaround for encrypted channels |
| Whisper accuracy on noisy radio | Consider RNNoise denoising pass |
| Audio latency | ~3–5 second delay is normal |
| No scan mode | Not in v1 |
| No recording | Not in v1 |
| No authentication | Add if exposing beyond localhost |

---

## 6. Directory Structure

```
ravensdr/
├── app.py                  # Flask app, routes, Socket.IO events
├── input_source.py         # InputSource abstraction
├── tuner.py                # RTL-FM process manager
├── stream_source.py        # Web stream ingest via ffmpeg
├── transcriber.py          # Hailo Whisper wrapper
├── audio_router.py         # HTTP audio streaming
├── presets.py              # Frequency preset definitions
├── requirements.txt
├── setup.sh                # System dependency installer
├── static/
│   ├── ravensdr.js          # Frontend logic
│   └── ravensdr.css         # UI stylesheet
└── templates/
    └── index.html          # Console single-page app
```
