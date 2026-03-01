# ravenSDR
### Real-time RF Signal Transcription Pipeline
*RTL-SDR → Edge AI Inference (Hailo-8L NPU) → Live Web Interface*

## Implementation Plan

---

## Project Overview

A web application that tunes an RTL-SDR dongle (RTL-SDR Blog V4) to preset emergency/monitoring frequencies, streams demodulated audio to the browser, and transcribes radio chatter to text in real time using the Raspberry Pi AI Hat (Hailo-8L NPU) running OpenAI Whisper.

When the RTL-SDR dongle is not connected, ravenSDR automatically falls back to **Web Stream Mode** — pulling live audio from public internet streams (LiveATC for aviation, NOAA Weather Radio streams) through the same transcription pipeline. This allows the full stack — Whisper inference, audio streaming, WebSocket transcript delivery, and UI — to be developed and tested without any SDR hardware present.

**Target Hardware:**
- Raspberry Pi 5
- Hailo AI Hat (Hailo-8L, 13 TOPS)
- RTL-SDR Blog V4 (R828D tuner, RTL2832U, 1PPM TCXO, Bias Tee, SMA, USB)

**Target OS:** Raspberry Pi OS (Bookworm, 64-bit)

---

## Architecture Overview

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

---

## Tech Stack

| Layer | Technology |
|---|---|
| SDR demodulation (Mode A) | `rtl_fm` (part of `rtl-sdr` package) |
| Web stream ingest (Mode B) | `ffmpeg` subprocess — decodes MP3/AAC → raw PCM |
| Input abstraction | `InputSource` class — unified PCM queue for both modes |
| SDR auto-detection | `rtl_test` subprocess on startup; falls back to Mode B if exit code != 0 |
| NPU inference | Hailo-8L via `hailo-apps` Python SDK |
| Speech-to-text model | Whisper `tiny` or `base` (.hef compiled for Hailo) |
| Backend | Python 3.11+, Flask, Flask-SocketIO |
| Audio routing | ALSA loopback (`snd-aloop` kernel module) |
| Audio streaming | HTTP chunked response (WAV/PCM over HTTP) |
| Frontend | Single-file HTML + Vanilla JS + Web Audio API |
| Real-time comms | Socket.IO (WebSocket) |
| Process management | Python `subprocess` with threading |

---

## Project Directory Structure

```
ravensdr/
├── app.py                  # Flask app, routes, Socket.IO events
├── input_source.py         # InputSource abstraction — SDR or web stream
├── tuner.py                # RTL-FM process manager (Mode A)
├── stream_source.py        # Web stream ingest via ffmpeg (Mode B)
├── transcriber.py          # Hailo Whisper wrapper + audio chunking
├── audio_router.py         # ALSA loopback setup + PCM pipe management
├── presets.py              # Frequency preset definitions (SDR + stream URLs)
├── requirements.txt
├── setup.sh                # One-shot system dependency installer
├── static/
│   ├── ravensdr.js          # Frontend logic (Socket.IO, Web Audio, UI state)
│   └── ravensdr.css         # UI stylesheet
└── templates/
    └── index.html          # ravenSDR Console single-page app
```

---

## Phase 1 — System Dependencies & Environment Setup

### 1.1 System Packages
Install via `setup.sh`:
```bash
sudo apt update
sudo apt install -y \
  rtl-sdr librtlsdr-dev \
  sox alsa-utils \
  python3-pip python3-venv \
  ffmpeg
sudo modprobe snd-aloop
echo "snd-aloop" | sudo tee -a /etc/modules   # persist across reboots
```

### 1.2 Python Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install flask flask-socketio numpy pyaudio
```

### 1.3 Hailo SDK
Follow Hailo's official Raspberry Pi setup:
- Install `hailort` driver and Python bindings per [Hailo Developer Zone](https://hailo.ai/developer-zone/)
- Clone `hailo-apps` repo
- Download the Whisper `.hef` model file compiled for Hailo-8L (not Hailo-8)
- Confirm with `hailortcli fw-control identify`

### 1.4 RTL-SDR Driver (blacklist DVB kernel module)
```bash
echo "blacklist dvb_usb_rtl28xxu" | sudo tee /etc/modprobe.d/rtlsdr.conf
sudo rmmod dvb_usb_rtl28xxu 2>/dev/null || true
```
Verify SDR is detected: `rtl_test -t`

Expected output for V4:
```
Found 1 device(s):
  0:  Realtek, RTL2832U OEM, SN: 00000001
Using device 0: Generic RTL2832U OEM
Found Rafael Micro R828D tuner    ← confirms V4 tuner
```

### 1.5 RTL-SDR Blog V4 — Specific Notes

**Bias Tee:** The V4 has a software-activatable bias tee (4.5V on the SMA port) for powering external LNAs. It is **off by default** — no action needed for ravenSDR. If you ever attach an active antenna or LNA, enable it with:
```bash
rtl_biast -b 1   # ON
rtl_biast -b 0   # OFF — always off before disconnecting
```
Never enable the bias tee with a passive antenna connected — it won't damage the dongle (there's protection) but it wastes power and can cause interference.

**HF Direct Sampling (below 25 MHz):** The V4 includes a built-in upconverter path for HF reception down to 500 kHz. Not used by ravenSDR's emergency presets (all VHF/UHF) but useful for future shortwave additions. Activate in `rtl_fm` with `-D` flag if needed.

**R828D vs R820T2:** The V4's R828D tuner has better sensitivity and lower noise floor than the R820T2 in competing dongles, particularly noticeable on weak aviation signals. No software changes needed — `rtl_fm` detects it automatically.

---

## Phase 2 — Input Source Abstraction

### 2.0 — Auto-Detection on Startup (`input_source.py`)

On every startup, ravenSDR checks for the RTL-SDR dongle before choosing an input mode:

```python
def detect_sdr() -> bool:
  result = subprocess.run(["rtl_test", "-t"], capture_output=True, timeout=5)
  return result.returncode == 0

INPUT_MODE = "SDR" if detect_sdr() else "WEBSTREAM"
```

The `InputSource` class wraps both modes behind a unified interface so `transcriber.py` and `audio_router.py` never need to know which source is active:

```python
class InputSource:
  def __init__(self, mode: str):   # "SDR" or "WEBSTREAM"
    self.mode = mode
    self.pcm_queue = queue.Queue(maxsize=200)
    self._source = Tuner() if mode == "SDR" else StreamSource()

  def tune(self, preset: dict):
    self._source.tune(preset)

  def stop(self):
    self._source.stop()

  @property
  def is_running(self) -> bool:
    return self._source.is_running
```

Mode is broadcast to all browser clients via Socket.IO:
```python
socketio.emit("mode", {"mode": INPUT_MODE, "sdr_available": detect_sdr()})
```

---

### 2.1 — Web Stream Mode: `stream_source.py`

When no SDR is present, `stream_source.py` replaces `tuner.py` as the audio producer. It uses `ffmpeg` to pull a public internet stream and convert it to the same 16kHz mono PCM format the rest of the pipeline expects — making the downstream pipeline completely unaware of the source.

**ffmpeg command for stream ingest:**
```bash
ffmpeg -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 \
  -i {stream_url} -vn -acodec pcm_s16le -ar 16000 -ac 1 -f s16le pipe:1
```

Output is raw 16kHz mono 16-bit PCM to stdout — identical to `rtl_fm`. The `_read_loop()` thread reads 4096-byte chunks into the shared `pcm_queue`.

**Why ffmpeg:** Handles reconnection, Icecast/SHOUTcast/HTTP protocol negotiation, and format conversion in a single command. Already available on Pi OS and any Linux/Mac laptop.

**Stream switching:** Kill ffmpeg subprocess, drain queue, respawn with new URL.

**Reconnect behaviour:** `-reconnect` flags handle stream drops automatically. After 3 failed retries, emit `error` Socket.IO event to browser.

---

### 2.2 — Available Public Web Streams (Redmond/Seattle)

These confirmed live streams are bundled as presets in web stream mode:

| Label | URL | Notes |
|---|---|---|
| NOAA Seattle (KEC74) | `https://wxradio.org/WA-Seattle-KHB60` | ⚠️ Check live status — may not have an active feeder |
| NOAA Monterey (KEC49) | `https://wxradio.org/CA-Monterey-KEC49` | ✅ Confirmed live — best fallback for dev testing |
| NOAA Monterey Marine (WWF64) | `https://wxradio.org/CA-MontereyMarine-WWF64` | ✅ Confirmed live, marine weather |
| SeaTac Approach (LiveATC) | `http://d.liveatc.net/ksea_app` | ✅ Live ATC — personal/local use only |
| SeaTac Tower (LiveATC) | `http://d.liveatc.net/ksea3_app_e` | ✅ Live tower/departure — personal/local use only |

> **wxradio.org URL format changed:** Old `http://wxradio.org:8000/KEC74` style URLs are dead. Current format is `https://wxradio.org/STATE-City-CallSign`. No Seattle WA feeder was found active at time of writing — if a local volunteer adds one, the URL would be `https://wxradio.org/WA-Seattle-KHB60`. Check `https://wxradio.org/status.xsl` for current live streams.
>
> **LiveATC terms:** Personal listening only. Do not expose beyond localhost or embed in public deployments.
>
> **wxradio.org terms:** Direct end-user listening only — no stream harvesting or relaying.
>
> **Recommended dev approach:** Use `https://wxradio.org/CA-Monterey-KEC49` (confirmed live 24/7) to validate the full pipeline, then switch to local SDR when hardware arrives.

---

### 2.3 — Updated Preset Schema

Add `stream_url` to every preset that has a web stream equivalent:

```python
{
  "id":          "noaa1",
  "label":       "NOAA Seattle",
  "freq":        "162.550M",                       # SDR mode
  "mode":        "fm",
  "category":    "weather",
  "stream_url":  "http://wxradio.org:8000/KEC74",  # WebStream mode
  "stream_note": "wxradio.org community Icecast stream",
}
```

Presets without a `stream_url` are greyed out in the UI when in WebStream mode with a "SDR required" badge.

---

## Phase 2B — Backend: `tuner.py` (RTL-FM Process Manager)

### Responsibilities
- Start/stop/restart `rtl_fm` subprocess
- Accept frequency, demodulation mode, squelch, and gain parameters
- Read raw PCM stdout from `rtl_fm` in a background thread
- Write PCM chunks to two consumers simultaneously:
  1. `audio_pipe` — byte queue for HTTP audio streaming
  2. `whisper_pipe` — byte queue for Hailo transcription

### Class: `Tuner`

**Properties:**
- `current_freq` — active frequency string (e.g. `"162.550M"`)
- `current_mode` — demodulation mode: `"fm"`, `"am"`, `"wbfm"`, `"usb"`, `"lsb"`
- `squelch` — integer 0–100 (maps to rtl_fm `-l` flag)
- `gain` — integer or `"auto"` (maps to rtl_fm `-g` flag)
- `is_running` — bool

**Methods:**
- `tune(freq, mode)` — kills existing process, starts new `rtl_fm` with given params
- `stop()` — terminates `rtl_fm` process cleanly (SIGTERM, then SIGKILL after 1s)
- `set_squelch(level)` — updates squelch and retunes
- `set_gain(value)` — updates gain and retunes
- `_read_loop()` — background thread; reads 4096-byte chunks from `rtl_fm.stdout`, pushes to both queues

**rtl_fm command template:**
```bash
rtl_fm -f {freq} -M {mode} -s 200k -r 16k -l {squelch} -g {gain} -
```
For `wbfm` (broadcast FM), use `-s 200k -r 48k` instead and convert to 16k for Whisper separately.

**Important:** When switching frequencies, drain both queues before starting the new process to prevent stale audio reaching Whisper.

---

## Phase 3 — Backend: `transcriber.py` (Hailo Whisper Integration)

### Responsibilities
- Read PCM audio from `whisper_pipe` queue
- Accumulate audio into chunks suitable for Whisper inference (2–5 second windows)
- Detect silence/squelch using RMS energy — only send audio to NPU when signal is present
- Run Whisper inference on Hailo-8L
- Push transcript segments to a `transcript_queue` with timestamps and frequency metadata

### Class: `Transcriber`

**Whisper Input Requirements:**
- Sample rate: 16,000 Hz
- Bit depth: 16-bit signed PCM
- Channels: mono
- Chunk size: ~32,000 samples (2 seconds) minimum for reasonable accuracy

**Silence Detection:**
```python
SILENCE_THRESHOLD = 500   # RMS value — tune empirically
CHUNK_SAMPLES = 48000     # 3 seconds at 16kHz

def is_signal_present(pcm_bytes):
  samples = np.frombuffer(pcm_bytes, dtype=np.int16)
  rms = np.sqrt(np.mean(samples.astype(np.float32)**2))
  return rms > SILENCE_THRESHOLD
```

**Transcript Output Format:**
```python
{
  "timestamp": "14:32:01",
  "freq": "162.550 MHz",
  "label": "NOAA Seattle",
  "text": "...wind northwest at 12 knots...",
  "rms": 1842.3   # signal strength indicator
}
```

**Fallback:** If `HAILO_AVAILABLE = False` (running on laptop for dev), fall back to `faster-whisper` CPU inference using the same `tiny` model. This lets you develop and test the full pipeline without the Pi hardware.

---

## Phase 4 — Backend: `audio_router.py` (HTTP Audio Streaming)

### Responsibilities
- Read raw PCM from `audio_pipe` queue
- Wrap in WAV container headers for browser compatibility
- Serve as a chunked HTTP response the browser's `<audio>` tag can consume

### WAV Header Construction
The browser needs a valid WAV header. Since length is unknown for a live stream, write the RIFF header with `0xFFFFFFFF` as the size (streaming WAV convention), followed by continuous PCM data chunks.

```python
def make_wav_header(sample_rate=16000, channels=1, bits=16):
# Returns 44-byte WAV header with streaming-friendly size fields
```

### Flask Route: `/audio-stream`
```python
@app.route("/audio-stream")
def audio_stream():
  def generate():
    yield make_wav_header()
    while True:
      chunk = audio_pipe.get(timeout=5)
      yield chunk
  return Response(
    stream_with_context(generate()),
    mimetype="audio/wav",
    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
  )
```

**Volume/gain normalization:** Optionally apply a simple peak normalize on each PCM chunk before sending to the browser so quiet signals aren't inaudible. Use numpy for this.

---

## Phase 5 — Backend: `app.py` (Flask Application)

### Routes

| Method | Route | Purpose |
|---|---|---|
| GET | `/` | Serve the single-page UI |
| GET | `/api/presets` | Return JSON list of all frequency presets |
| POST | `/api/tune` | Switch to a frequency `{preset_id}` or `{freq, mode}` |
| POST | `/api/stop` | Stop rtl_fm, silence audio stream |
| POST | `/api/squelch` | Update squelch level `{level: 0-100}` |
| POST | `/api/gain` | Update gain `{gain: "auto" or 0-50}` |
| GET | `/api/status` | Return current state JSON |
| GET | `/audio-stream` | Chunked WAV audio stream |

### Socket.IO Events (Server → Client)

| Event | Payload | Description |
|---|---|---|
| `transcript` | `{timestamp, freq, label, text, rms}` | New transcription segment |
| `status` | `{running, freq, label, mode, squelch, gain}` | State change broadcast |
| `signal_level` | `{rms, freq}` | Emitted every 500ms for signal meter UI |
| `mode` | `{mode: "SDR"\|"WEBSTREAM", sdr_available: bool}` | Input mode on connect or change |
| `error` | `{message}` | SDR errors (device not found, stream offline, etc.) |

### Thread Model
The app runs four concurrent threads:
1. Flask/SocketIO main thread (HTTP + WebSocket)
2. `tuner._read_loop()` — reads rtl_fm stdout
3. `transcriber._inference_loop()` — runs Whisper on PCM chunks
4. `signal_meter_loop()` — samples RMS every 500ms and emits `signal_level`

---

## Phase 6 — Frontend: `index.html` + `static/ravensdr.js`

### UI Layout (Single Page)

```
┌─────────────────────────────────────────────────────┐
│  ◉ RAVENSDR          [● SDR MODE]   [STATUS: LIVE]   │
│                  or [◎ WEB STREAM] when no dongle    │
├─────────────────────────────────────────────────────┤
│  FREQUENCY PRESETS                                  │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐  │
│  │ WEATHER │ │AVIATION │ │ MARINE  │ │  PUBLIC │  │
│  │  (3)    │ │  (4)    │ │  (2)    │ │  (2)    │  │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘  │
│                                                     │
│  ┌── NOAA Seattle ────────────────── 162.550 MHz ─┐ │
│  │ ● ACTIVE  [web stream: wxradio.org]            │ │
│  └────────────────────────────────────────────────┘ │
│  ┌── SeaTac Tower ─────────────────── 119.900 MHz ┐ │
│  │ [web stream: liveatc.net]                      │ │
│  └────────────────────────────────────────────────┘ │
│  ┌── KC Interop ───────────────────── 155.340 MHz ┐ │
│  │ [SDR required]  ← greyed out in web stream mode│ │
│  └────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────┤
│  SIGNAL  ▓▓▓▓▓▓▓▓░░░░  SQUELCH ──●────  GAIN auto  │
│                        (hidden in web stream mode)   │
├─────────────────────────────────────────────────────┤
│  ▶ AUDIO  ████████████████████  🔊  ──●──────────  │
├─────────────────────────────────────────────────────┤
│  TRANSCRIPT                          [CLEAR] [COPY] │
│  14:32:01  NOAA SEATTLE                             │
│  "...wind northwest at 12 knots, gusts to 22..."    │
└─────────────────────────────────────────────────────┘
```

### Frontend Components (Vanilla JS, no framework)

**`PresetSelector`**
- Renders category tabs (Weather, Aviation, Marine, Public Safety, Broadcast)
- Each preset is a button; clicking calls `POST /api/tune`
- Active preset highlighted; shows spinner during tune operation
- Custom frequency input field for manual entry

**`SignalMeter`**
- Canvas-based horizontal bar
- Updated by `signal_level` Socket.IO events
- Color: green (strong) → yellow (moderate) → red (weak/noise)
- Shows "SQUELCH" label when signal is below threshold

**`AudioPlayer`**
- Hidden `<audio>` element with `src="/audio-stream"`
- Custom play/pause/volume controls (styled, not browser default)
- Reconnect logic: if stream drops, retry after 2 seconds
- Volume slider controls `<audio>.volume` property

**`TranscriptFeed`**
- Scrolling `<div>` with transcript entries
- Each entry: timestamp badge + frequency label + text
- New entries slide in from bottom with CSS animation
- Auto-scroll to bottom (pauses if user scrolls up manually)
- Clear button empties display; Copy button copies full session to clipboard
- Empty state: "Waiting for signal..." with subtle pulse animation

**`ControlBar`**
- Squelch slider: 0–100, calls `POST /api/squelch` on change (debounced 500ms)
- Gain selector: "auto" + values 0, 10, 20, 30, 40 dB — calls `POST /api/gain`
- Stop button: calls `POST /api/stop`

### Socket.IO Client Events
```javascript
socket.on("transcript", (data) => appendTranscript(data));
socket.on("signal_level", (data) => updateSignalMeter(data.rms));
socket.on("status", (data) => syncUIState(data));
socket.on("error", (data) => showErrorToast(data.message));
socket.on("connect", () => fetchStatusAndSync());
socket.on("disconnect", () => showConnectionBanner("Reconnecting..."));
```

---

## Phase 7 — Frequency Presets: `presets.py`

### Preset Schema
```python
{
  "id":       str,   # unique slug, e.g. "noaa1"
  "label":    str,   # display name, e.g. "NOAA Seattle"
  "freq":     str,   # rtl_fm format, e.g. "162.550M"
  "mode":     str,   # "fm", "am", "wbfm", "usb", "lsb"
  "category": str,   # "weather", "aviation", "marine", "public_safety", "broadcast"
  "squelch":  int,   # preset-specific squelch override (optional)
  "note":     str,   # display note, e.g. "Unencrypted" (optional)
}
```

### Initial Presets (Redmond, WA area)

**Weather**
- NOAA Seattle Primary — 162.550 MHz FM
- NOAA Backup — 162.400 MHz FM
- NOAA Alt — 162.475 MHz FM

**Aviation (all AM)**
- SeaTac Tower — 119.900 MHz
- Seattle Center — 120.600 MHz
- Boeing Field — 118.300 MHz
- Renton Municipal — 123.000 MHz
- SeaTac Ground — 121.900 MHz

**Marine**
- Channel 16 (Distress/Calling) — 156.800 MHz FM
- Channel 22A (Coast Guard) — 157.100 MHz FM

**Public Safety (unencrypted)**
- KC Interoperability — 155.340 MHz FM
- Fire/EMS Dispatch — 154.280 MHz FM *(verify locally before use)*

**Broadcast (for testing pipeline)**
- KEXP 90.3 FM — 90.300 MHz WBFM
- KUOW 94.9 FM — 94.900 MHz WBFM

---

## Phase 8 — Error Handling & Edge Cases

### SDR Not Connected
- On startup, run `rtl_test -t` via subprocess; if exit code != 0, emit `error` event to all clients with message "SDR device not found — check USB connection"
- UI shows a persistent banner until device is detected
- Poll for device every 10 seconds and auto-recover

### rtl_fm Process Crash
- Monitor subprocess with `process.poll()` in `_read_loop`
- If unexpected exit, emit `error` event, update status to `stopped`
- Expose a "Retry" button in UI that calls `POST /api/tune` with last known preset

### Audio Stream Reconnect (Browser Side)
- If `<audio>` element fires `error` or `ended`, wait 2 seconds and reset `src` to trigger reconnect
- Show "Reconnecting audio..." indicator in UI

### ALSA Loopback Not Loaded
- In `setup.sh`, check if `snd-aloop` is loaded with `lsmod | grep snd_aloop`
- If missing, warn during startup and note that audio streaming may be affected

### Hailo NPU Not Available
- If Hailo SDK import fails, fall back to `faster-whisper` CPU inference automatically
- Log warning; UI shows "CPU mode" badge instead of "NPU" badge
- CPU inference will be slower (~2–4× real-time on Pi 5) but functional

---

## Phase 9 — `setup.sh` (One-Shot Installer)

Script should perform in order:
1. Check running on Raspberry Pi OS (warn if not)
2. `apt install` all system packages
3. `modprobe snd-aloop` + persist in `/etc/modules`
4. Blacklist `dvb_usb_rtl28xxu` kernel module
5. Create Python venv and install pip packages
6. Test SDR is detected with `rtl_test -t` — confirm R828D tuner in output
7. Verify bias tee is off: `rtl_biast -b 0`
8. Test Hailo Hat with `hailortcli fw-control identify` — warn if host/firmware version mismatch
9. Print summary: what passed, what needs manual action

**V4-specific apt package to add:**
```bash
sudo apt install -y rtl-sdr librtlsdr-dev rtl-biast
```
`rtl-biast` is the bias tee control utility, separate from `rtl-sdr` on some distros.

---

## Phase 10 — `requirements.txt`

```
flask>=3.0.0
flask-socketio>=5.3.6
numpy>=1.26.0
pyaudio>=0.2.14
faster-whisper>=1.0.0    # CPU fallback
eventlet>=0.35.0         # SocketIO async mode
```

Hailo SDK (`hailort`, `hailo-apps`) installed separately via Hailo's official installer — not pip.

---

## Development & Testing Without Pi Hardware

ravenSDR has two no-hardware test paths:

**Path 1 — Web Stream Mode (recommended, tests real pipeline)**
Simply run ravenSDR on your laptop without plugging in the RTL-SDR. `detect_sdr()` returns False, `InputSource` automatically initialises `StreamSource`, and the full pipeline runs against live NOAA or LiveATC audio. Hailo falls back to `faster-whisper` CPU mode automatically. This tests:
- ffmpeg stream ingest
- PCM queue and chunking
- Whisper transcription
- Flask routes and Socket.IO
- Full UI including mode badge, audio playback, transcript feed

```bash
# Just run it — no SDR needed, streams start automatically
python3 app.py
# Open http://localhost:5000 and select NOAA Seattle
```

**Path 2 — Local WAV file mock (offline, no internet)**
Replace the ffmpeg stream URL with a local file path for fully offline testing:
```bash
# ffmpeg reads a local WAV just like a stream
ffmpeg -re -i test_audio.wav -acodec pcm_s16le -ar 16k -ac 1 -f s16le pipe:1
```
Good test audio sources: NOAA weather recordings from archive.org, any spoken-word content converted with `ffmpeg -i input.mp3 -ar 16000 -ac 1 test_audio.wav`

**Path 3 — Confirm with real SDR**
Plug in the RTL-SDR Blog V4 when it arrives. `detect_sdr()` returns True, `InputSource` switches to `Tuner`, mode badge in UI flips from "WEB STREAM" to "SDR". No other code changes needed.

---

## Known Limitations & Hardware Constraints

| Limitation | Notes |
|---|---|
| One frequency at a time | RTL-SDR Blog V4 can only tune one freq — need multiple dongles for simultaneous monitoring |
| Encrypted P25 | Redmond PD, King Co Sheriff are encrypted — no workaround |
| Whisper accuracy on noisy radio | Add a denoising pass (e.g. RNNoise) before Whisper for better results on weak signals |
| Audio latency | ~3–5 second delay from transmission to transcript is normal |
| No scan mode | Frequency scanning (hop between presets, pause when squelch opens) not in v1 |
| No recording | Timestamped WAV archive not in v1 |
| Authentication | No login — add if exposing beyond localhost |
| Web stream URL volatility | Community-run Icecast streams can go offline; dynamic discovery via `wxradio.org/status.xsl` mitigates this |

### ⚠️ Critical Hailo Hardware Constraint

**Hailo-8L (Pi AI Hat) supports:** `simple_whisper_chat` — Whisper speech-to-text. This is all ravenSDR needs for v1 and it runs well.

**Hailo-8L does NOT support:** The LLM chat, VLM chat, voice assistant, and agent tools apps from the hailo-apps repo. Per the official README, these GenAI applications require Hailo-10H hardware and are not available on Hailo-8 or Hailo-8L devices.

This means if you want to use the LLM or VLM capabilities from `gen_ai_apps`, you would need to upgrade to a **Hailo AI Kit Pro** (Hailo-10H module). This is relevant to the future enhancements below.

---

## Future Enhancements

### Enhancement 1 — NOAA Weather Satellite Image Capture (SDR Required)
**Priority: High | Hardware: Hailo-8L compatible | Effort: Medium**

NOAA 15 and NOAA 19 weather satellites transmit live Earth imagery via **APT (Automatic Picture Transmission)** on 137 MHz — directly receivable with the RTL-SDR Blog V4 and a cheap V-dipole antenna (included in your kit). The V4's R828D tuner performs noticeably better at 137 MHz than older R820T2 dongles, making APT reception more reliable. This is one of the most impressive SDR projects possible and keeps it on-topic with ravenSDR's emergency monitoring theme.

**How it works:**
1. Track NOAA satellite pass times using `pypredict` or `ephem` with TLE data from Celestrak
2. At pass time, tune the SDR to 137.620 MHz (NOAA 15) or 137.9125 MHz (NOAA 19)
3. Record the ~14 minute pass with `rtl_fm`
4. Decode the APT audio signal into a visible-light + infrared image using `noaa-apt` (Rust CLI tool)
5. Display the decoded image in the ravenSDR web UI with timestamp and pass metadata

**Libraries:** `ephem` for pass prediction, `noaa-apt` CLI for decoding, `Pillow` for image processing

**ravenSDR integration:** Add a "Satellite" category in the preset list. When a pass is imminent (within 10 minutes), ravenSDR shows a countdown and auto-tunes. The decoded image appears in a new panel in the web UI alongside the transcript feed.

```
[Upcoming Pass]  NOAA-19  ↑ 14:32 UTC  Max Elevation: 67°
[Image Panel]   [decoded APT image of Pacific Northwest cloud cover]
```

**Note:** NOAA-18 was decommissioned in June 2025. NOAA-15 and NOAA-19 remain operational but are aging satellites — this feature has a finite lifespan. NOAA's JPSS satellites (NOAA-20, NOAA-21) use a different digital format (HRPT) that requires a much larger dish antenna.

---

### Enhancement 2 — Automated Local Weather Briefing (Hailo-8L compatible)
**Priority: High | Hardware: Hailo-8L | Effort: Low**

After each NOAA weather radio transcription segment (or on a timed schedule), use the transcribed text plus NWS API data to generate a condensed local weather briefing using `faster-whisper` TTS or a simple templated voice synthesis.

**Data sources (all free, no API key):**
```python
# NWS API — free, no auth, JSON
NWS_FORECAST = "https://api.weather.gov/gridpoints/SEW/{x},{y}/forecast"
NWS_ALERTS   = "https://api.weather.gov/alerts/active?zone=WAZ558"  # King County
NWS_HOURLY   = "https://api.weather.gov/gridpoints/SEW/{x},{y}/forecast/hourly"
```

**Flow:** Cron job every 30 min → fetch NWS JSON → format into spoken summary → convert to audio with `pyttsx3` (offline TTS) → serve as a new "Local Briefing" preset in ravenSDR that plays the synthesized audio and shows the transcript.

This demonstrates the full AI pipeline running entirely on-device with no cloud dependency.

---

### Enhancement 3 — ADS-B Flight Tracking Integration (SDR Required)
**Priority: Medium | Hardware: Hailo-8L | Effort: Low**

Run `dump1090` alongside ravenSDR on the same Pi 5. The RTL-SDR receives ADS-B transponder data from aircraft on 1090 MHz simultaneously with audio on other frequencies (requires frequency switching or a second dongle).

**Integration:** Add a map panel to the ravenSDR web UI that shows live aircraft positions over the Pacific Northwest, correlated with ATC audio transcripts. When Whisper transcribes a callsign like "Alaska 412", ravenSDR highlights that aircraft on the map.

**Libraries:** `dump1090` for ADS-B decoding, Leaflet.js for the map widget

---

### Enhancement 4 — Upgrade Path: Hailo-10H for LLM Context (Future Hardware)
**Priority: Low | Hardware: Hailo-10H required | Effort: High**

If upgrading to Hailo-10H (Hailo AI Kit Pro), ravenSDR could incorporate:

- **`simple_llm_chat`:** Post-process transcripts with a local LLM to extract structured data (event type, location, severity) from emergency radio chatter
- **`simple_vlm_chat`:** Pair with a Pi camera — when NOAA satellite image is captured, run VLM captioning to describe cloud cover, storm systems, etc. in natural language
- **`agent_tools_example`:** Voice-to-action agent that listens to ravenSDR transcripts and triggers automations (Home Assistant, alerts, logging) based on content

This upgrade path demonstrates a clear architectural progression from inference (8L) to generation (10H) on the same ravenSDR codebase — strong portfolio signal for edge AI work.

---

## Summary of Files to Create

| File | Lines (est.) | Complexity |
|---|---|---|
| `setup.sh` | ~60 | Low |
| `presets.py` | ~100 | Low |
| `input_source.py` | ~60 | Medium |
| `tuner.py` | ~120 | Medium |
| `stream_source.py` | ~100 | Medium |
| `audio_router.py` | ~80 | Medium |
| `transcriber.py` | ~150 | High |
| `app.py` | ~200 | Medium |
| `templates/index.html` | ~120 | Medium |
| `static/ravensdr.css` | ~320 | Medium |
| `static/ravensdr.js` | ~400 | High |
| `requirements.txt` | ~10 | Low |
| **Total** | **~1,720** | |