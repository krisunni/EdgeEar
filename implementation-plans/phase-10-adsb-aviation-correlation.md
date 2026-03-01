# Phase 10 — ADS-B Aviation Correlation & Voice-Activity Segmentation

## Objective
Add real-time ADS-B flight tracking correlated with Whisper aviation transcriptions, highlighting aircraft on a live map when their callsigns are spoken on tower/approach frequencies. Replace fixed-length audio chunking with silence-based segmentation to avoid cutting words mid-utterance.

## Scope
- Voice-activity audio segmentation (silence-boundary chunking replaces fixed 10s chunks)
- adsb_decoder process management (start/stop, JSON polling)
- Single-dongle (time-sharing) and dual-dongle (dedicated ADS-B receiver) modes
- Callsign extraction from Whisper transcripts via regex
- Callsign-to-flight matching against live adsb_decoder flight list
- Leaflet.js map panel with directional aircraft markers
- Visual correlation: matched aircraft highlighted on map, transcript lines linked to markers
- Socket.IO events for real-time ADS-B updates and callsign matches

---

## Sub-Phase 10.1 — ADS-B Receiver (adsb_decoder Manager)

### Tasks

| ID | Task | Status |
|---|---|---|
| T029 | Implement adsb_decoder process manager | planned |
| T030 | Implement adsb_decoder JSON poller (aircraft.json) | planned |
| T031 | Add single-dongle scan mode (time-sharing with rtl_fm) | planned |
| T032 | Add dual-dongle mode (dedicated device_index=1) | planned |

### Files to Create

| File | Purpose |
|---|---|
| `code/ravensdr/adsb_receiver.py` | adsb_decoder process manager + JSON flight poller |

### Key Implementation

```python
# adsb_receiver.py — core structure

import subprocess, requests, threading, logging

log = logging.getLogger(__name__)

ADSB_DECODER_JSON = "http://localhost:8080/data/aircraft.json"

class AdsbReceiver:
    """Manages adsb_decoder process and polls aircraft JSON."""

    def __init__(self, device_index=0, dual_dongle=False):
        self.device_index = device_index
        self.dual_dongle = dual_dongle
        self.process = None
        self.flights = []        # latest aircraft list
        self._poll_thread = None
        self._running = False

    def start(self):
        """Start adsb_decoder subprocess on configured device index."""
        cmd = [
            "dump1090-mutability",
            "--device-index", str(self.device_index),
            "--net",
            "--quiet",
        ]
        self.process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL)
        self._running = True
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()
        log.info("adsb_decoder started on device %d", self.device_index)

    def stop(self):
        """Stop adsb_decoder and polling."""
        self._running = False
        if self.process:
            self.process.terminate()
            self.process.wait(timeout=5)
            self.process = None
        log.info("adsb_decoder stopped")

    def _poll_loop(self):
        """Poll adsb_decoder JSON endpoint every 2 seconds."""
        import time
        while self._running:
            try:
                resp = requests.get(ADSB_DECODER_JSON, timeout=2)
                data = resp.json()
                self.flights = data.get("aircraft", [])
            except Exception as e:
                log.debug("adsb_decoder poll error: %s", e)
            time.sleep(2)

    def get_flights(self):
        """Return current flight list."""
        return self.flights
```

**Single-dongle scan mode:** When `dual_dongle=False`, the receiver coordinates with `Tuner` — rtl_fm pauses every 60s for a 30s ADS-B scan window. The `InputSource` manages the scheduling via a scan timer. During the scan window, adsb_decoder starts on device 0, collects aircraft data, then stops so rtl_fm can resume.

**Dual-dongle mode:** When `dual_dongle=True`, adsb_decoder runs continuously on device_index=1 while rtl_fm uses device_index=0. No scheduling needed.

### Verification
- adsb_decoder starts and produces `aircraft.json` on localhost:8080
- Poller retrieves and parses flight list correctly
- `stop()` kills adsb_decoder cleanly (no orphaned processes)
- Single-dongle mode pauses/resumes rtl_fm on schedule
- Dual-dongle mode runs both processes concurrently

---

## Sub-Phase 10.2 — Voice-Activity Audio Segmentation

### Tasks

| ID | Task | Status |
|---|---|---|
| T051 | Implement silence detector with RMS + holdoff timer | planned |
| T052 | Replace fixed CHUNK_SAMPLES accumulation with silence-boundary splitting | planned |
| T053 | Add configurable VAD parameters (threshold, min/max duration, holdoff) | planned |
| T054 | Pad or trim final segment to match Hailo encoder input size | planned |

### Files to Modify

| File | Change |
|---|---|
| `code/ravensdr/transcriber.py` | Replace fixed 10s chunking with VAD-based segmentation in both CPU and Hailo paths |

### Key Implementation

```python
# Voice-activity segmentation constants
VAD_SILENCE_THRESHOLD = 400   # RMS below this = silence
VAD_HOLDOFF_MS = 300          # silence must last this long to trigger a split
VAD_MIN_SEGMENT_S = 1.0       # don't send segments shorter than this
VAD_MAX_SEGMENT_S = 15.0      # force-split if speech runs longer than this
SAMPLE_RATE = 16000
FRAME_SIZE = 1600              # 100ms frames at 16kHz

class VoiceActivitySegmenter:
    """Accumulates PCM and splits on silence boundaries."""

    def __init__(self):
        self.buffer = b""
        self._silence_frames = 0
        self._holdoff_frames = int(VAD_HOLDOFF_MS / 100)

    def feed(self, pcm: bytes) -> list[bytes]:
        """Feed PCM data, return list of complete segments (may be empty)."""
        self.buffer += pcm
        segments = []

        while len(self.buffer) >= FRAME_SIZE * 2:
            frame = self.buffer[:FRAME_SIZE * 2]
            self.buffer = self.buffer[FRAME_SIZE * 2:]
            rms = compute_rms(frame)
            buf_seconds = len(self._pending) / (SAMPLE_RATE * 2)

            if rms < VAD_SILENCE_THRESHOLD:
                self._silence_frames += 1
            else:
                self._silence_frames = 0

            self._pending += frame

            # Split on silence boundary (if enough silence and min length met)
            if (self._silence_frames >= self._holdoff_frames
                    and buf_seconds >= VAD_MIN_SEGMENT_S):
                segments.append(self._flush())

            # Force-split at max duration to avoid unbounded buffers
            if buf_seconds >= VAD_MAX_SEGMENT_S:
                segments.append(self._flush())

        return segments

    def _flush(self) -> bytes:
        seg = self._pending
        self._pending = b""
        self._silence_frames = 0
        return seg
```

**How it integrates with the existing transcriber:** The `_transcribe_loop` currently accumulates a byte buffer and slices at fixed `chunk_bytes = CHUNK_SAMPLES * 2` (10s). Replace that accumulation with `VoiceActivitySegmenter.feed()` calls. Each returned segment gets padded/trimmed to `CHUNK_SAMPLES` via the existing `pad_or_trim()` before inference — Hailo encoder still receives its expected 160,000 samples, but the actual speech content is no longer arbitrarily cut.

**Max segment cap:** `VAD_MAX_SEGMENT_S = 15.0` ensures a force-split even during continuous speech (e.g. ATIS broadcasts), keeping latency bounded. Segments shorter than `VAD_MIN_SEGMENT_S` are held until more speech arrives, avoiding tiny fragments.

### Verification
- Continuous speech is not split mid-word — segments end during silence gaps
- Short pauses (<300ms) within a sentence do not trigger a split
- Long unbroken speech force-splits at 15s max
- Silence-only audio produces no segments (existing `is_signal_present` check still applies)
- Hailo encoder receives correctly sized input (pad_or_trim still works)
- Transcription quality improves vs fixed 10s chunks on aviation radio test audio

---

## Sub-Phase 10.3 — Callsign Correlator

### Tasks

| ID | Task | Status |
|---|---|---|
| T033 | Implement callsign regex extractor | planned |
| T034 | Implement flight list matcher | planned |
| T035 | Define ICAO airline code lookup table | planned |

### Files to Create

| File | Purpose |
|---|---|
| `code/ravensdr/adsb_correlator.py` | Callsign extraction + flight matching |

### Key Implementation

```python
# adsb_correlator.py — core structure

import re, logging

log = logging.getLogger(__name__)

# Common ICAO airline designators → callsign prefixes
AIRLINE_CODES = {
    "alaska": "ASA", "united": "UAL", "delta": "DAL",
    "american": "AAL", "southwest": "SWA", "jetblue": "JBU",
    "horizon": "QXE", "skywest": "SKW", "frontier": "FFT",
    "spirit": "NKS", "hawaiian": "HAL",
}

# Patterns: "Alaska 412", "UAL 732", "Delta 89", "N12345"
CALLSIGN_PATTERNS = [
    # Airline name + flight number: "Alaska four twelve"
    re.compile(
        r'\b(' + '|'.join(AIRLINE_CODES.keys()) + r')\s+(\d{1,4})\b',
        re.IGNORECASE
    ),
    # ICAO code + flight number: "UAL 732"
    re.compile(
        r'\b([A-Z]{3})\s*(\d{1,4})\b'
    ),
    # N-number: "N12345" or "November 1 2 3 4 5"
    re.compile(
        r'\b(N\d{1,5}[A-Z]{0,2})\b', re.IGNORECASE
    ),
]


def extract_callsigns(transcript: str) -> list[str]:
    """Extract potential callsigns from a Whisper transcript line.

    Returns normalized ICAO-style callsigns (e.g. "ASA412", "N12345").
    """
    matches = []
    for pattern in CALLSIGN_PATTERNS:
        for m in pattern.finditer(transcript):
            groups = m.groups()
            if len(groups) == 2:
                airline, number = groups
                code = AIRLINE_CODES.get(airline.lower(), airline.upper())
                matches.append(f"{code}{number}")
            else:
                matches.append(groups[0].upper())
    return matches


def match_flights(callsigns: list[str], flights: list[dict]) -> list[dict]:
    """Match extracted callsigns against adsb_decoder flight list.

    Returns list of matched flight dicts with added 'matched_callsign' key.
    """
    matched = []
    for flight in flights:
        flight_cs = flight.get("flight", "").strip().upper()
        if not flight_cs:
            continue
        for cs in callsigns:
            if cs in flight_cs or flight_cs in cs:
                matched.append({**flight, "matched_callsign": cs})
                break
    return matched
```

### Verification
- "Alaska 412 cleared to land" → extracts `ASA412`
- "UAL 732 turn left heading 270" → extracts `UAL732`
- "November 1 2 3 4 5" → extracts `N12345`
- Extracted callsigns match against adsb_decoder flight entries
- No false positives on non-aviation transcripts

---

## Sub-Phase 10.4 — Backend Integration

### Tasks

| ID | Task | Status |
|---|---|---|
| T036 | Add `/api/adsb/flights` REST endpoint | planned |
| T037 | Add `adsb_update` Socket.IO event (periodic flight list push) | planned |
| T038 | Add `callsign_match` Socket.IO event (on transcript correlation) | planned |
| T039 | Add ADS-B config flags to app config | planned |
| T040 | Add ADS-B preset to presets.py | planned |

### Files to Modify

| File | Change |
|---|---|
| `code/ravensdr/app.py` | Add ADS-B routes, Socket.IO events, receiver lifecycle |
| `code/ravensdr/presets.py` | Add ADS-B 1090 MHz preset entry |

### Key Implementation

**app.py additions:**

```python
# New route
@app.route("/api/adsb/flights")
def adsb_flights():
    if adsb_receiver:
        return jsonify(adsb_receiver.get_flights())
    return jsonify([])

# Socket.IO: push flight updates every 2s
def adsb_broadcast_loop():
    while adsb_receiver and adsb_receiver._running:
        socketio.emit("adsb_update", adsb_receiver.get_flights())
        socketio.sleep(2)

# On new transcript, check for callsign matches
def on_transcript(text):
    callsigns = extract_callsigns(text)
    if callsigns:
        matches = match_flights(callsigns, adsb_receiver.get_flights())
        if matches:
            socketio.emit("callsign_match", {
                "transcript": text,
                "matches": matches,
            })
```

**presets.py addition:**

```python
{
    "id": "adsb-1090",
    "name": "ADS-B 1090 MHz",
    "freq": "1090M",
    "mode": "adsb",
    "category": "Aviation",
    "description": "ADS-B aircraft tracking (adsb_decoder)",
    "device_index": 1,
}
```

**Config flags (environment variables):**
- `ADSB_ENABLED` — enable ADS-B receiver (default: `false`)
- `ADSB_DUAL_DONGLE` — use dedicated dongle on device 1 (default: `false`)
- `ADSB_SCAN_INTERVAL` — seconds between scan windows in single-dongle mode (default: `60`)
- `ADSB_SCAN_DURATION` — seconds per scan window (default: `30`)

### Verification
- `GET /api/adsb/flights` returns current aircraft list
- `adsb_update` events received by Socket.IO clients every 2s
- `callsign_match` event fires when transcript contains a known callsign
- ADS-B preset appears in `GET /api/presets`
- Config flags control receiver behavior

---

## Sub-Phase 10.5 — Map Panel (Frontend)

### Tasks

| ID | Task | Status |
|---|---|---|
| T041 | Add Leaflet.js map container to index.html | planned |
| T042 | Implement aircraft marker rendering (map.js) | planned |
| T043 | Implement callsign match highlighting | planned |
| T044 | Style map panel (map.css) | planned |
| T045 | Integrate map toggle into ravensdr.js | planned |

### Files to Create

| File | Purpose |
|---|---|
| `code/static/map.js` | Leaflet.js map, aircraft markers, highlight logic |
| `code/static/map.css` | Map panel styles |

### Files to Modify

| File | Change |
|---|---|
| `code/templates/index.html` | Add map panel section, Leaflet CDN links |
| `code/static/ravensdr.js` | Map panel toggle, callsign highlight in transcript |

### Key Implementation

**map.js:**

```javascript
// map.js — Leaflet aircraft map

const SEATAC = [47.4502, -122.3088];
let map, markers = {};

function initMap() {
    map = L.map("adsb-map").setView(SEATAC, 10);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);
}

function updateAircraft(flights) {
    const seen = new Set();
    flights.forEach(f => {
        if (!f.lat || !f.lon) return;
        const id = f.hex || f.flight;
        seen.add(id);
        if (markers[id]) {
            markers[id].setLatLng([f.lat, f.lon]);
            markers[id].setRotationAngle(f.track || 0);
        } else {
            markers[id] = L.marker([f.lat, f.lon], {
                icon: aircraftIcon(),
                rotationAngle: f.track || 0,
            }).addTo(map);
        }
        markers[id].bindTooltip(
            (f.flight || f.hex || "???").trim(),
            { permanent: false }
        );
    });
    // Remove stale markers
    Object.keys(markers).forEach(id => {
        if (!seen.has(id)) {
            map.removeLayer(markers[id]);
            delete markers[id];
        }
    });
}

function highlightAircraft(matches) {
    matches.forEach(m => {
        const id = m.hex || m.flight;
        if (markers[id]) {
            markers[id].setIcon(highlightedIcon());
            setTimeout(() => markers[id].setIcon(aircraftIcon()), 8000);
        }
    });
}
```

**index.html additions:**

```html
<!-- Leaflet CDN -->
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet-rotatedmarker@0.2.0/leaflet.rotatedMarker.js"></script>

<!-- Map panel -->
<div id="adsb-panel" class="panel hidden">
    <div id="adsb-map" style="height: 400px;"></div>
</div>
```

### Map Visibility Rules

The map panel is not always visible — it appears based on the selected preset and ADS-B config:

| Condition | Map Panel | Audio/Transcript | Callsign Correlation |
|---|---|---|---|
| `ADSB_ENABLED=false` (any preset) | Hidden | Active | Off |
| `ADSB_ENABLED=true` + non-Aviation preset | Hidden | Active | Off |
| `ADSB_ENABLED=true` + Aviation preset (e.g. SeaTac Tower) | Shown | Active | Active — transcripts matched against flight list |
| `ADSB_ENABLED=true` + ADS-B 1090 preset | Shown (full-width) | No audio/transcript | Off — map-only tracking mode |

**Behavior on preset change (ravensdr.js):**

```javascript
function onPresetSelected(preset) {
    const adsbEnabled = window.ADSB_ENABLED;  // injected by Flask template
    const isAviation = preset.category === "Aviation";
    const isAdsbOnly = preset.mode === "adsb";

    if (!adsbEnabled || !isAviation) {
        // Hide map, stop listening for adsb_update events
        hideMapPanel();
        socket.off("adsb_update");
        socket.off("callsign_match");
        return;
    }

    // Show map panel
    showMapPanel();
    if (!map) initMap();
    map.invalidateSize();  // recalc after unhide

    // Subscribe to ADS-B events
    socket.on("adsb_update", updateAircraft);

    if (isAdsbOnly) {
        // ADS-B 1090 preset: map-only, no transcript panel
        hideTranscriptPanel();
    } else {
        // Aviation VHF preset: show both transcript + map
        showTranscriptPanel();
        socket.on("callsign_match", (data) => {
            highlightAircraft(data.matches);
            highlightTranscriptLine(data.transcript, data.matches);
        });
    }
}
```

**Layout:** When both transcript and map are visible (Aviation VHF presets), the map panel renders below the transcript feed. When in ADS-B 1090 map-only mode, the map expands to full width/height of the main content area.

### Verification
- Map renders centered on SEA-TAC with OpenStreetMap tiles
- Aircraft appear as directional markers with callsign tooltips
- Matched aircraft get highlighted ring for 8 seconds
- Stale aircraft removed when no longer in adsb_decoder feed
- Map panel toggles on/off without breaking other UI
- Map hidden when `ADSB_ENABLED=false` regardless of preset
- Map hidden on non-Aviation presets (Weather, Marine, etc.)
- Map shown automatically when Aviation preset selected and ADS-B enabled
- ADS-B 1090 preset shows map-only mode (no transcript panel)
- Switching from Aviation to non-Aviation preset hides map and unsubscribes events
- `map.invalidateSize()` called after unhide to prevent tile rendering glitches

---

## Sub-Phase 10.6 — Setup & Dependencies

### Tasks

| ID | Task | Status |
|---|---|---|
| T046 | Add adsb_decoder install to setup.sh | planned |
| T047 | Add `requests` to requirements.txt | planned |
| T048 | Write unit tests for callsign extractor | planned |
| T049 | Write integration test for ADS-B receiver mock | planned |
| T050 | Write unit tests for VoiceActivitySegmenter | planned |

### Files to Modify

| File | Change |
|---|---|
| `code/setup.sh` | Add dump1090-mutability install section |
| `code/requirements.txt` | Add `requests` |

### Files to Create

| File | Purpose |
|---|---|
| `code/tests/unit/test_adsb_correlator.py` | Callsign extraction + matching tests |
| `code/tests/unit/test_vad_segmenter.py` | VAD segmentation boundary tests |
| `code/tests/integration/test_adsb_receiver.py` | Receiver start/stop with mocked adsb_decoder |

### Key Tests

```python
# test_adsb_correlator.py

def test_extract_airline_callsign():
    assert extract_callsigns("Alaska 412 cleared to land") == ["ASA412"]

def test_extract_icao_callsign():
    assert extract_callsigns("UAL 732 turn left heading 270") == ["UAL732"]

def test_extract_n_number():
    assert extract_callsigns("N12345 squawk 1200") == ["N12345"]

def test_no_match():
    assert extract_callsigns("wind calm altimeter 30.12") == []

def test_multiple_callsigns():
    result = extract_callsigns("Alaska 412 follow Delta 89")
    assert "ASA412" in result
    assert "DAL89" in result

def test_match_flights():
    flights = [{"flight": "ASA412 ", "lat": 47.4, "lon": -122.3}]
    matched = match_flights(["ASA412"], flights)
    assert len(matched) == 1
    assert matched[0]["matched_callsign"] == "ASA412"
```

**setup.sh addition:**

```bash
# dump1090 for ADS-B decoding (optional)
if ! command -v dump1090-mutability &>/dev/null; then
    echo "Installing dump1090-mutability..."
    sudo apt-get install -y dump1090-mutability || {
        echo "dump1090 not in apt, building from source..."
        git clone https://github.com/flightaware/dump1090.git /tmp/dump1090
        cd /tmp/dump1090 && make && sudo cp dump1090 /usr/local/bin/dump1090-mutability
    }
fi
```

### Verification
- All unit tests pass
- Integration test starts/stops mock receiver cleanly
- `requests` installs from requirements.txt
- setup.sh installs dump1090 on Raspberry Pi

---

## Exit Criteria
- [ ] Audio segments split on silence boundaries, not fixed time
- [ ] Words are not cut mid-utterance in transcription output
- [ ] VAD respects min (1s) and max (15s) segment duration
- [ ] adsb_decoder process manager starts, polls, and stops cleanly
- [ ] Single-dongle scan mode time-shares correctly with rtl_fm
- [ ] Dual-dongle mode runs both processes concurrently
- [ ] Callsign extractor handles airline names, ICAO codes, and N-numbers
- [ ] Flight matcher correlates callsigns to adsb_decoder aircraft list
- [ ] `/api/adsb/flights` returns current aircraft data
- [ ] `adsb_update` Socket.IO event pushes flight list to clients
- [ ] `callsign_match` event fires on transcript correlation
- [ ] Leaflet map renders aircraft with directional markers
- [ ] Matched aircraft highlighted on map for 8 seconds
- [ ] All unit tests pass (including VAD segmenter tests)
- [ ] ADS-B feature disabled by default (opt-in via config)

## Risks

| Risk | Mitigation |
|---|---|
| Single dongle timing gaps — 30s scan window means no audio for 30s | Configurable intervals; UI shows "scanning ADS-B" status; dual-dongle eliminates gap |
| Aircraft without ADS-B (military, older GA) | Not trackable — note in UI; ADS-B mandated for most US airspace since 2020 |
| Callsign disambiguation — multiple flights match regex | Return all matches, rank by proximity to SEA-TAC; highlight all with different colors |
| Whisper mistranscribes callsigns (e.g. "Alaska" → "a last car") | Maintain common misheard variants in AIRLINE_CODES; improve with aviation-tuned prompt |
| adsb_decoder not available on dev machine (no SDR) | Mock receiver with sample aircraft.json for development; integration tests use fixtures |
| Single RTL-SDR cannot do 1090 MHz and VHF simultaneously | Core hardware constraint — dual-dongle mode is the proper solution |
| Leaflet tile loading on offline/air-gapped Pi | Document offline tile cache option; map degrades gracefully without tiles |
| VAD threshold too aggressive — splits mid-word on noisy RF | Holdoff timer (300ms) prevents splitting on brief signal drops; threshold is configurable |
| VAD threshold too conservative — long segments increase latency | Max segment cap (15s) force-splits; tune threshold per frequency band |
| Continuous ATIS/weather broadcasts have no silence gaps | Max segment cap handles this; ATIS presets could use shorter max duration |
