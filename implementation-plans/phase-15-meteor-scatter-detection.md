# Phase 15 — Passive Meteor Scatter Detection

## Overview

When a meteor enters the atmosphere at 11–72 km/s it creates a column of ionized plasma at 80–120 km altitude that briefly reflects radio signals in the 50–500 MHz range. By tuning to a carrier from a distant FM station normally below the radio horizon (800–2000 km away), ravenSDR detects the brief signal bursts caused by meteor trail reflections. Each burst is logged as a meteor detection event with timestamp, duration, peak power, and frequency offset. Detection rate over time directly measures meteor flux — background sporadic rate vs shower peaks (Perseids, Leonids, Geminids). This runs as a passive background mode on a fixed frequency, no conflict with voice monitoring on other frequencies if a second dongle is available.

## The Physics

- **Underdense trails:** thin ionization column, coherent reflection, exponential power decay, duration 0.05–0.5 seconds
- **Overdense trails:** dense column, plateau then decay, duration 1–10 seconds, may show amplitude oscillations from trail rotation and winds
- **Forward scatter geometry:** meteor trail must be roughly equidistant between transmitter and receiver at ~90–100 km altitude
- **Detection window:** the trail exists only while free electrons haven't recombined with ions — temperature and atmospheric density at 90 km determine this
- **Diurnal variation:** detection rates peak in pre-dawn hours as Earth's leading hemisphere sweeps up more debris

## Target Frequencies (Redmond WA)

Primary detection frequencies:
- **83.400 MHz** — CJVB Vancouver BC (deliberate meteor scatter beacon frequency used by amateur community, ~230 km — may be too close for ideal forward scatter geometry, document this)
- **108.000 MHz** — use a distant station 800–1500 km away, identify strongest candidate from initial spectrum scan
- **143.050 MHz** — dedicated amateur meteor scatter calling frequency, strongest community use
- **216.980 MHz** — NOAA Weather Radio alt band, strong carriers

**Finding the best local carrier:**
1. Run `rtl_power` sweep across 88–108 MHz
2. Identify stations with no local match (unknown callsign = distant station)
3. Use these as detection targets — the ideal carrier is strong enough to detect via scatter but not receivable under normal propagation

## Trail Type Classification

- **Underdense:** duration < 0.5s, exponential decay shape, caused by sub-millimeter particles
- **Overdense:** duration > 0.5s, plateau shape, caused by larger meteoroids
- Bursts > 30 seconds flagged as interference, not meteors

## Dual Dongle Mode

- `METEOR_DUAL_DONGLE=true`: meteor detector runs on `device_index=1` 24/7, completely independent of main pipeline
- Single dongle: meteor detection runs during gaps in voice monitoring (between squelch events), background priority
- During Perseid peak (Aug 11–13) consider dedicating the dongle to meteor detection overnight as it runs unattended

## New Files
| File | Purpose |
|------|---------|
| `code/ravensdr/meteor_detector.py` | IQ power monitor, threshold detector, trail classifier, event logger |
| `code/ravensdr/meteor_analyzer.py` | Shower calendar, flux rate calculator, hourly/daily statistics aggregator |
| `code/ravensdr/data/meteor_showers.json` | Annual shower calendar with peak dates, radiant coordinates, expected ZHR |
| `code/static/meteor.js` | Meteor panel UI, real-time event feed, rate chart, shower calendar |
| `code/static/meteor.css` | Panel styles |

## Modified Files
| File | Changes |
|------|---------|
| `code/ravensdr/app.py` | `/api/meteor/events` route (paginated), `/api/meteor/stats` route (hourly rate, daily count, shower context), `meteor_detection` Socket.IO event |
| `code/ravensdr/input_source.py` | Meteor detection mode on second dongle (`device_index=1`) if `METEOR_DUAL_DONGLE=true`, otherwise time-slices with main pipeline |
| `code/templates/index.html` | Meteor panel section |
| `code/static/ravensdr.js` | Meteor panel integration |
| `code/setup.sh` | No new dependencies — uses existing rtl_fm and numpy |

## Known Limitations

- Detection is statistical — a single burst could be interference, a pattern over hours is unambiguous
- Local FM interference on target frequency will produce false positives — carrier selection process is critical
- Doppler measurement requires stable reference, RTL-SDR frequency drift (even with TCXO) may affect precision offset measurement
- Daytime detection rates are lower — meteor flux peaks in pre-dawn hours
- Second dongle strongly recommended for continuous monitoring without interrupting voice pipeline
- No audio — this is pure power detection, there is nothing to hear. Document clearly to set user expectations.
- RMOB (Radio Meteor Observation Bulletin) integration is a future enhancement — log format should be kept compatible for community science contribution

---

## Tasks

### T095 — Create meteor shower calendar data file
**File:** `code/ravensdr/data/meteor_showers.json`
**Status:** Done

Create the annual meteor shower calendar JSON file:

```json
[
    {
        "name": "Quadrantids",
        "peak_date": "01-03",
        "peak_end": "01-04",
        "active_start": "12-28",
        "active_end": "01-12",
        "zhr": 120,
        "speed_kms": 41,
        "parent_body": "2003 EH1 (asteroid)",
        "radiant_ra": 230.1,
        "radiant_dec": 48.5,
        "notes": "Sharp peak, narrow window"
    },
    {
        "name": "Eta Aquariids",
        "peak_date": "05-05",
        "peak_end": "05-06",
        "zhr": 50,
        "speed_kms": 66,
        "parent_body": "Comet 1P/Halley"
    },
    {
        "name": "Perseids",
        "peak_date": "08-11",
        "peak_end": "08-13",
        "active_start": "07-17",
        "active_end": "08-24",
        "zhr": 100,
        "speed_kms": 59,
        "parent_body": "Comet 109P/Swift-Tuttle"
    },
    {
        "name": "Orionids",
        "peak_date": "10-21",
        "peak_end": "10-22",
        "zhr": 20,
        "speed_kms": 66,
        "parent_body": "Comet 1P/Halley"
    },
    {
        "name": "Leonids",
        "peak_date": "11-17",
        "peak_end": "11-18",
        "zhr": 15,
        "speed_kms": 71,
        "parent_body": "Comet 55P/Tempel-Tuttle",
        "notes": "Storm years possible (33-year cycle)"
    },
    {
        "name": "Geminids",
        "peak_date": "12-13",
        "peak_end": "12-14",
        "active_start": "12-04",
        "active_end": "12-17",
        "zhr": 120,
        "speed_kms": 35,
        "parent_body": "Asteroid 3200 Phaethon",
        "notes": "Unusual asteroidal parent body, strongest annual shower"
    }
]
```

Include all six major showers with peak dates, active windows, ZHR, entry speed, parent body, and radiant coordinates (RA/Dec).

**Acceptance criteria:**
- All six major showers included with correct peak dates and ZHR values
- JSON is valid and parseable
- Active windows included for showers with well-defined boundaries
- Parent body documented for each shower

---

### T096 — Create meteor detection power monitor and threshold detector
**File:** `code/ravensdr/meteor_detector.py`
**Status:** Done

Create the core meteor detection module:

- **IQ power monitoring:** read IQ samples from rtl_fm on target frequency, compute power in dBm using numpy
- **Baseline tracking:** rolling average noise floor over 30-second window, continuously updated
- **Threshold detection:** signal exceeds baseline by configurable dB threshold (default 10 dB)
- **Burst capture:** when threshold crossed, record start timestamp, track power samples until signal drops below threshold
- **Duration filtering:**
  - Minimum 50 ms — ignore shorter bursts (hardware noise, RFI spikes)
  - Maximum 30 seconds — flag as interference, not meteor
- **Event data extraction:**
  - Timestamp (ISO 8601, millisecond precision)
  - Duration in milliseconds
  - Peak power in dBm
  - Mean power in dBm
  - Frequency offset in Hz (Doppler shift from carrier center)
- **Trail type classification:**
  - Underdense: duration < 0.5s, exponential decay shape (fit exponential, check R²)
  - Overdense: duration > 0.5s, plateau-then-decay shape
- **Event emission:** emit `meteor_detection` Socket.IO event with full event payload on each detection
- **Logging:** append each detection to JSON log file at `code/ravensdr/data/meteor_log.json`

RTL-SDR configuration for meteor detection:
```
rtl_fm -f <freq> -M fm -s 12k -r 11025 -g 40
```
For dual dongle: add `-d 1` for second device.

**Acceptance criteria:**
- Power computed correctly from IQ samples
- Rolling baseline tracks noise floor accurately
- Threshold crossing detected within 50 ms
- Duration filtering excludes noise and interference
- Trail type classified based on duration and power profile
- Events logged with all required fields

---

### T097 — Create meteor statistics analyzer and shower correlator
**File:** `code/ravensdr/meteor_analyzer.py`
**Status:** Done

Create the meteor statistics and shower analysis module:

- **Shower calendar loading:** parse `meteor_showers.json`, determine active showers for current date
- **Shower correlation:** tag detections with active shower name when detection occurs during shower active window. Background sporadic meteors tagged as `"shower": null`.
- **Rate calculation:**
  - Detections per hour (sliding 1-hour window)
  - Detections per day (calendar day UTC)
  - Peak hourly rate for current session
- **Statistics aggregation:**
  - `get_hourly_stats(hours=24)` — returns list of hourly detection counts for the last N hours
  - `get_daily_stats(days=7)` — returns list of daily detection counts
  - `get_current_shower()` — returns active or upcoming shower info, or None
  - `get_session_stats()` — total count, peak hourly rate, underdense/overdense ratio, session duration
- **Shower prediction:** determine next upcoming shower peak and days until peak
- **RMOB compatibility:** detection log format designed to be exportable to RMOB CSV format (future enhancement, document field mapping)

**Acceptance criteria:**
- Shower calendar loaded and queried by date correctly
- Detections tagged with correct active shower
- Hourly and daily rate calculations accurate
- Session statistics track correctly across detections
- Current/upcoming shower reported accurately

---

### T098 — Add meteor detection mode to SDR input source
**File:** `code/ravensdr/input_source.py` (modify)
**Status:** Done

Add meteor detection mode to the input source abstraction:

- **Dual dongle mode** (`METEOR_DUAL_DONGLE=true`):
  - Meteor detector runs on `device_index=1` independently
  - `start_meteor_monitor(frequency_hz)` — start rtl_fm on second dongle, feed to detector
  - `stop_meteor_monitor()` — stop second dongle monitoring
  - Main pipeline on `device_index=0` unaffected
- **Single dongle mode:**
  - `enter_meteor_mode(frequency_hz)` — switch SDR to meteor detection frequency during idle periods
  - `exit_meteor_mode()` — return to normal scanning
  - Meteor detection runs at background priority — any voice monitoring, APT pass, or WEFAX window takes precedence
  - Detect squelch idle gaps and run meteor monitoring during dead air
- **Priority ordering:** APT satellite pass > WEFAX broadcast > voice monitoring > meteor detection

**Acceptance criteria:**
- Dual dongle mode starts/stops meteor monitoring on second device independently
- Single dongle mode transitions cleanly between meteor monitoring and other modes
- Priority ordering enforced — higher priority modes preempt meteor detection
- No orphaned rtl_fm processes

---

### T099 — Add meteor API routes and Socket.IO events to Flask app
**File:** `code/ravensdr/app.py` (modify)
**Status:** Done

Add meteor detection endpoints and events:

**REST endpoints:**
- `GET /api/meteor/events` — paginated list of detection events, newest first. Query params: `?limit=50&offset=0&shower=Perseids&trail_type=underdense`
- `GET /api/meteor/stats` — current statistics: hourly rate, daily count, session total, peak rate, active shower, underdense/overdense ratio
- `GET /api/meteor/showers` — full shower calendar with current/next shower highlighted

**Socket.IO events (server → client):**
- `meteor_detection` — emitted in real time on each detection with full event payload:
  ```json
  {
      "timestamp": "2026-08-12T03:42:17.234Z",
      "duration_ms": 340,
      "peak_power_dbm": -67.3,
      "mean_power_dbm": -71.2,
      "frequency_hz": 143050000,
      "doppler_offset_hz": 124,
      "trail_type": "underdense",
      "shower": "Perseids",
      "shower_active": true
  }
  ```
- `meteor_stats_update` — emitted every 60 seconds with updated hourly rate and session stats

Initialize meteor detector on app startup (if meteor frequency configured). Start on second dongle if `METEOR_DUAL_DONGLE=true`.

**Acceptance criteria:**
- `/api/meteor/events` returns paginated detection list with filtering
- `/api/meteor/stats` returns current rate and session statistics
- `/api/meteor/showers` returns full calendar with active shower flagged
- Real-time detection events emitted via Socket.IO
- Stats update emitted every 60 seconds

---

### T100 — Create meteor panel JavaScript module
**File:** `code/static/meteor.js`
**Status:** Done

Create the meteor panel frontend module:

1. **Real-time event feed** — scrolling list of detections, showing timestamp, duration, trail type (U/O badge for underdense/overdense), peak power. Most recent at top. Cap at 100 visible entries.
2. **Rate chart** — detections per hour over last 24 hours as a bar chart drawn on `<canvas>`. X-axis: hours (UTC), Y-axis: count. Highlight bars during active shower windows.
3. **Shower context** — current or upcoming shower name, peak date, expected ZHR, days until peak. "No active shower — sporadic background" when no shower is active.
4. **Statistics panel** — today's count, this hour's count, peak hourly rate today, session total, underdense/overdense ratio
5. **Target frequency display** — which carrier is being monitored, current signal baseline dBm, threshold level dBm

Listen for Socket.IO events:
- `meteor_detection` — prepend to event feed, update counts
- `meteor_stats_update` — refresh rate chart and statistics

Fetch initial state on page load:
- `/api/meteor/events?limit=50` for recent detections
- `/api/meteor/stats` for current statistics
- `/api/meteor/showers` for shower calendar

**Acceptance criteria:**
- Event feed updates in real time with each detection
- Rate chart renders 24-hour bar chart accurately
- Shower context shows correct active/upcoming shower
- Statistics update every 60 seconds
- Canvas chart redraws cleanly on new data

---

### T101 — Create meteor panel CSS styles
**File:** `code/static/meteor.css`
**Status:** Done

Style the meteor panel consistent with existing ravenSDR UI:

- Event feed: monospace timestamp, duration column, trail type badge (U green, O amber), power level
- Rate chart: canvas container with responsive sizing
- Shower context: prominent display with shower name, peak date, countdown
- Statistics: compact grid layout for count values
- Trail type badges: `U` (underdense) small green badge, `O` (overdense) small amber badge
- Target frequency info: subtle display at panel bottom
- Active detection flash: brief highlight animation on new detection in feed
- Match existing color scheme and font choices from ravensdr.css

**Acceptance criteria:**
- Styles consistent with existing ravenSDR panels
- Trail type badges visually distinct
- Rate chart readable at panel width
- Detection flash animation visible but not distracting

---

### T102 — Integrate meteor panel into main UI
**Files:** `code/templates/index.html` (modify), `code/static/ravensdr.js` (modify)
**Status:** Done

Add meteor panel to the main ravenSDR interface:

**index.html:**
- Add meteor panel section with container divs for event feed, rate chart canvas, shower context, statistics, and target frequency info
- Include `<script src="/static/meteor.js"></script>` and `<link rel="stylesheet" href="/static/meteor.css">`

**ravensdr.js:**
- Initialize meteor panel on page load
- Add meteor tab/section toggle if using tabbed layout
- Show meteor detection mode indicator when active (frequency, baseline, dual/single dongle status)

**Acceptance criteria:**
- Meteor panel visible in main UI
- Panel initializes correctly on page load
- No conflicts with existing UI panels (weather, satellite, ADS-B, WEFAX)

---

### T103 — Write unit tests for meteor detector threshold and classifier
**File:** `code/tests/unit/test_meteor_detector.py`
**Status:** Done

Test the meteor detection module against synthetic data:

**Threshold detection tests:**
- Baseline noise floor computed correctly from 30-second sample window
- Burst above threshold (10 dB default) detected with correct start timestamp
- Burst below threshold ignored
- Burst under 50 ms filtered out (hardware noise)
- Burst over 30 seconds flagged as interference, not meteor
- Multiple sequential bursts detected as separate events

**Trail classifier tests:**
- Synthetic underdense profile (exponential decay, 200 ms duration) classified as underdense
- Synthetic overdense profile (plateau + decay, 2 second duration) classified as overdense
- Borderline 0.5s burst classified correctly based on power profile shape

**Power measurement tests:**
- Peak power extracted correctly from burst samples
- Mean power computed correctly across burst duration
- Doppler offset calculated from carrier frequency center

**Test fixture:**
- Include synthetic IQ data in `code/tests/fixtures/` simulating 3 underdense and 1 overdense burst at known timestamps and power levels

**Acceptance criteria:**
- All threshold tests pass against synthetic data
- Trail classifier correctly identifies underdense vs overdense profiles
- Power measurements accurate to within 0.1 dBm of expected values
- Synthetic fixture bursts detected at correct timestamps

---

### T104 — Write unit tests for meteor analyzer and shower calendar
**File:** `code/tests/unit/test_meteor_analyzer.py`
**Status:** Done

Test the meteor statistics and shower correlation module:

**Shower calendar tests:**
- `get_current_shower()` returns "Perseids" for date August 12
- `get_current_shower()` returns None for date March 15 (no active shower)
- `get_current_shower()` returns "Geminids" for date December 14
- Active window boundaries correct — shower starts/ends on documented dates
- Next upcoming shower calculated correctly from arbitrary date

**Rate calculation tests:**
- Hourly rate computed correctly from known event list
- Daily count aggregated correctly across UTC day boundary
- Peak hourly rate tracked correctly when rate increases then decreases
- Empty event list returns zero rates

**Shower correlation tests:**
- Detection during Perseid active window tagged with `"shower": "Perseids"`
- Detection outside any active window tagged with `"shower": null`
- Detection during overlapping shower windows (if any) tagged with closest-to-peak shower

**Acceptance criteria:**
- All shower calendar lookups return correct results for known dates
- Rate calculations accurate against known event counts
- Shower correlation tags detections correctly

---

### T105 — Integration test for end-to-end meteor detection pipeline
**File:** `code/tests/integration/test_meteor_pipeline.py`
**Status:** Done

Integration test for the full meteor detection pipeline:

- Feed synthetic IQ data (from fixtures) through detector → analyzer → API → Socket.IO event chain
- Verify 3 underdense and 1 overdense bursts detected from fixture data
- Verify trail classification correct for each burst
- Verify `/api/meteor/events` returns all 4 detections with correct metadata
- Verify `/api/meteor/stats` shows correct hourly rate and trail type ratio
- Verify `meteor_detection` Socket.IO events emitted for each burst
- Verify shower tagging correct when test date falls during active shower

**Dual dongle mode test:**
- Mock second device (`device_index=1`) and verify meteor detector starts independently
- Verify main pipeline on `device_index=0` unaffected by meteor monitoring

**Live test (manual, document procedure):**
- Run detector on 143.050 MHz for 24 hours
- Expected: 5–15 sporadic detections per hour during pre-dawn, 2–5 per hour during afternoon
- During Perseid peak: expect 30–60+ detections per hour pre-dawn
- Document that initial run may require threshold tuning based on local noise environment

Mark with `@pytest.mark.integration`.

**Acceptance criteria:**
- Synthetic pipeline test passes end-to-end
- All 4 fixture bursts detected and classified correctly
- API and Socket.IO outputs verified
- Dual dongle isolation verified
- Manual test procedure documented

---

## Dependency Chain
```
T095 (shower calendar) → T097 (analyzer)
T096 (detector) → T097 (analyzer) → T099 (API routes)
T096 → T098 (input source mode)
T099 → T100 (meteor UI) → T101 (CSS) → T102 (layout integration)
T096 → T103 (detector tests)
T095 + T097 → T104 (analyzer tests)
T096 + T097 + T098 + T099 → T105 (integration test)
```

## Success Criteria
- Meteor scatter events detected from distant FM carrier reflections using RTL-SDR V4
- Underdense and overdense trail types classified correctly based on duration and power profile
- Real-time detection feed displayed in dedicated UI panel
- Hourly rate chart shows detection rate over 24-hour window
- Active meteor showers identified and tagged on detections from shower calendar
- Dual dongle mode enables 24/7 meteor monitoring independent of voice pipeline
- Single dongle mode runs meteor detection at background priority during idle gaps
- Detection rate correlates with known shower peaks (Perseids, Geminids)
- All unit and mocked integration tests pass
