# Phase 14 — WEFAX (Weather Fax) HF Reception and Decoding

## Overview

NOAA and US Coast Guard transmit synoptic weather charts (surface analysis, pressure forecasts, wave height, wind fields) as WEFAX audio-encoded greyscale images on fixed HF frequencies. The RTL-SDR Blog V4 supports HF direct sampling via the `-D 2` flag, enabling reception from 500 kHz to 25 MHz without any upconverter hardware. ravenSDR receives, decodes, and displays these charts alongside APT satellite imagery to give a full Pacific Northwest weather picture — orbital observation from APT, forecast model from WEFAX.

## Hardware Context

- **RTL-SDR Blog V4 direct sampling:** pass `-D 2` flag to rtl_fm (Q-branch direct sampling, correct for R828D tuner). `-D 1` (I-branch) does **not** work correctly on the V4 — this is a common source of confusion.
- **No upconverter needed** — the V4 supports HF direct sampling natively. The V4 has a hardware modification vs older RTL-SDR dongles that improves HF direct sampling performance.
- **Antenna:** the included dipole is functional but a simple long wire (5–10m) significantly improves HF reception. Document this as strongly recommended.
- **Single dongle constraint:** WEFAX reception pauses other monitoring during scheduled broadcast windows. Priority order: APT satellite pass > WEFAX broadcast > normal VHF/UHF scanning.

## Target Stations (Pacific Northwest)

**NMC Point Reyes CA (NMC):**
- Frequencies: 4346.0 kHz, 8682.0 kHz, 12786.0 kHz, 17151.2 kHz
- Broadcasts: surface analysis, 24/48/96/144hr forecasts, North Pacific wave charts
- Schedule: fixed UTC times, published at https://www.weather.gov/marine/radiofax

**NOJ Kodiak AK (NOJ):**
- Frequencies: 2054.0 kHz, 4298.0 kHz, 8459.0 kHz, 12412.0 kHz
- Coverage: Alaska and North Pacific
- Stronger signal from Redmond WA than NMC on lower frequencies at night

## Reception Mode

- **USB (upper sideband)** demodulation, tune 1.9 kHz below the listed frequency (standard WEFAX convention)
- **IOC 576** standard (576 lines per minute rotation speed) for NMC/NOJ
- **Image width:** 1809 pixels standard
- rtl_fm command: `rtl_fm -D 2 -f <freq> -M usb -s 12k -r 11025 | decode_wefax`

## New Files
| File | Purpose |
|------|---------|
| `code/ravensdr/wefax_receiver.py` | rtl_fm HF direct sampling manager, fldigi subprocess wrapper, image output handler |
| `code/ravensdr/wefax_scheduler.py` | Broadcast schedule parser and job scheduler |
| `code/static/wefax.js` | WEFAX panel UI, chart display, chart type selector, history thumbnails |
| `code/static/wefax.css` | WEFAX panel styles |

## Modified Files
| File | Changes |
|------|---------|
| `code/ravensdr/app.py` | `/api/wefax/latest` route, `/api/wefax/schedule` route, `wefax_image_ready` Socket.IO event |
| `code/ravensdr/input_source.py` | WEFAX recording mode switches SDR to HF direct sampling, resumes normal VHF/UHF after broadcast window |
| `code/templates/index.html` | WEFAX panel section |
| `code/static/ravensdr.js` | WEFAX panel integration |
| `code/setup.sh` | Install fldigi (`sudo apt install fldigi -y`) |

## Known Limitations

- HF reception quality is highly dependent on antenna — long wire antenna setup strongly recommended
- Direct sampling has lower sensitivity than a proper HF receiver or upconverter. Some frequencies may be marginal.
- Single dongle: WEFAX windows conflict with APT satellite passes and normal VHF monitoring. Dual dongle resolves this. Priority: APT pass > WEFAX > normal scanning.
- fldigi requires a display or virtual framebuffer on headless Pi (`Xvfb`). Document this workaround.
- NMC/NOJ schedules are fixed but NOAA occasionally changes them. Schedule should be refreshable.
- Images are greyscale only — this is a format limitation of the WEFAX standard, not a software limitation.

---

## Tasks

### T084 — Create WEFAX broadcast schedule parser and job scheduler
**File:** `code/ravensdr/wefax_scheduler.py`
**Status:** Done

Create the WEFAX scheduler module:

- Parse NMC and NOJ broadcast schedules from https://www.weather.gov/marine/radiofax
- Support both scraping the schedule table and a hardcoded fallback for when the site is unreachable
- Hardcode the fixed NMC schedule table (surface analysis, 24/48/96/144hr forecasts, wave charts) with UTC times, frequencies, and chart types
- Hardcode the fixed NOJ schedule table similarly
- Provide `get_upcoming_broadcasts(hours=6)` returning list of broadcast dicts:
  ```python
  {
      "station": "NMC",
      "frequency_khz": 8682.0,
      "chart_type": "surface_analysis",
      "start_utc": "2026-03-16T12:30:00Z",
      "duration_minutes": 10,
      "description": "North Pacific Surface Analysis"
  }
  ```
- Prioritize surface analysis and 24hr forecast windows (most useful charts)
- Background thread that checks for upcoming broadcasts and triggers recording jobs
- Select optimal frequency based on time of day — lower frequencies (4 MHz) better at night, higher (8–12 MHz) better during day
- Emit `wefax_broadcast_upcoming` Socket.IO event 5 minutes before a broadcast
- Provide `refresh_schedule()` to re-scrape the NOAA site on demand

**Acceptance criteria:**
- Schedule parsed for both NMC and NOJ stations
- Upcoming broadcasts returned sorted by start time
- Hardcoded fallback works when NOAA site is unreachable
- Frequency selection adapts to time of day
- Upcoming broadcast event emitted before scheduled windows

---

### T085 — Create WEFAX receiver with HF direct sampling and fldigi decode
**File:** `code/ravensdr/wefax_receiver.py`
**Status:** Done

Create the WEFAX recording and decoding module:

- Start rtl_fm in HF direct sampling mode:
  ```
  rtl_fm -D 2 -f <freq_hz> -M usb -s 12k -r 11025
  ```
- `-D 2` enables Q-branch direct sampling (correct for V4 R828D tuner)
- Tune 1.9 kHz below the listed frequency (WEFAX convention)
- Pipe rtl_fm audio output to fldigi for WEFAX decoding:
  - fldigi supports WEFAX decode and outputs PNG
  - Run fldigi in headless mode with `--wefax-only` if available, or use Xvfb virtual framebuffer
  - Alternative: pipe through a virtual audio cable to fldigi
- Output decoded PNG to `code/static/images/wefax/` with structured filename:
  ```
  NMC_8682kHz_surface_analysis_2026-03-16T1230Z.png
  ```
- Parse filename components: station, frequency, chart type, timestamp
- Recording duration based on scheduled broadcast length (typically 8–15 minutes per chart)
- Emit `wefax_image_ready` Socket.IO event with image URL and metadata:
  ```python
  {
      "url": "/static/images/wefax/NMC_8682kHz_surface_analysis_2026-03-16T1230Z.png",
      "station": "NMC",
      "frequency_khz": 8682.0,
      "chart_type": "surface_analysis",
      "decoded_at": "2026-03-16T12:42:00Z",
      "image_width": 1809,
      "ioc": 576
  }
  ```
- Clean up intermediate audio files after successful decode
- Log decode success/failure with signal quality notes

**Acceptance criteria:**
- rtl_fm starts with correct `-D 2` flag and USB demodulation
- Frequency offset of -1.9 kHz applied correctly
- fldigi subprocess invoked for WEFAX decoding
- Decoded PNG saved to correct directory with structured filename
- Socket.IO event emitted with full metadata on decode completion

---

### T086 — Add WEFAX recording mode to SDR input source
**File:** `code/ravensdr/input_source.py` (modify)
**Status:** Done

Add WEFAX recording mode to the input source abstraction:

- `enter_wefax_mode(frequency_khz)` — pause normal VHF/UHF scanning, switch SDR to HF direct sampling mode
- `exit_wefax_mode()` — disable direct sampling, resume normal VHF/UHF monitoring
- Lock mechanism to prevent frequency changes during WEFAX recording
- Coordinate with tuner.py to cleanly stop/restart rtl_fm with WEFAX-specific parameters:
  - `-D 2` (direct sampling Q-branch)
  - `-M usb` (upper sideband)
  - `-s 12k` (sample rate)
  - `-r 11025` (output rate)
- Respect priority ordering: if an APT satellite pass is imminent, do not enter WEFAX mode
- Emit status events so UI shows SDR is in WEFAX recording mode

**Acceptance criteria:**
- Normal scanning pauses cleanly when WEFAX mode engaged
- SDR switches to HF direct sampling with correct parameters
- Normal VHF/UHF scanning resumes after WEFAX mode exits
- APT pass priority respected — WEFAX defers to satellite passes
- No orphaned rtl_fm processes

---

### T087 — Add WEFAX API routes and Socket.IO events to Flask app
**File:** `code/ravensdr/app.py` (modify)
**Status:** Done

Add WEFAX endpoints and events:

**REST endpoints:**
- `GET /api/wefax/latest` — returns URL and metadata for most recently decoded WEFAX chart. Optional `?chart_type=surface_analysis` query parameter to filter by chart type. Returns 404 if no charts decoded yet.
- `GET /api/wefax/schedule` — returns next 6 hours of scheduled broadcasts with station, frequency, chart type, UTC time
- `GET /api/wefax/history` — returns last 10 decoded charts as list of metadata dicts

**Socket.IO events (server → client):**
- `wefax_broadcast_upcoming` — emitted 5 min before broadcast (station, frequency, chart type, start time)
- `wefax_image_ready` — emitted when decode completes (image URL, station, chart type, timestamp)

Initialize WEFAX scheduler on app startup. Wire up receiver to emit events on decode completion.

**Acceptance criteria:**
- `/api/wefax/latest` returns valid JSON with image URL and metadata
- `/api/wefax/schedule` returns upcoming broadcasts sorted by time
- `/api/wefax/history` returns last 10 decoded charts
- Socket.IO events emitted at correct times
- Scheduler starts with app and runs in background

---

### T088 — Create WEFAX panel JavaScript module
**File:** `code/static/wefax.js`
**Status:** Done

Create the WEFAX panel frontend module:

1. **Broadcast schedule** — next 5 upcoming transmissions with station, frequency, chart type, UTC time. Countdown to next broadcast.
2. **Active reception** — progress indicator during live decode, "Receiving WEFAX" state with station and chart type
3. **Latest chart** — decoded greyscale PNG displayed inline with station, chart type, timestamp. Full-width display for readability.
4. **Chart history** — last 10 decoded charts as thumbnails, filterable by chart type (surface analysis, forecast, wave chart). Click to expand.
5. **Frequency info** — show which station and frequency is being used, with note about direct sampling mode

Listen for Socket.IO events:
- `wefax_broadcast_upcoming` — show notification, start countdown
- `wefax_image_ready` — display new decoded chart, add to history

Fetch initial state on page load:
- `/api/wefax/schedule` for upcoming broadcasts
- `/api/wefax/latest` for most recent chart
- `/api/wefax/history` for thumbnail gallery

**Acceptance criteria:**
- Broadcast schedule renders with correct data and countdown
- Active reception state displays during live decode
- Decoded charts display inline at full width
- History thumbnails filterable by chart type
- Real-time updates via Socket.IO events

---

### T089 — Create WEFAX panel CSS styles
**File:** `code/static/wefax.css`
**Status:** Done

Style the WEFAX panel consistent with existing ravenSDR UI:

- Broadcast schedule list styling with station/frequency badges
- Countdown timer prominent display
- Active reception progress indicator with animation
- Chart image display: responsive, maintains aspect ratio, greyscale optimized (no color processing needed)
- Thumbnail grid for chart history with chart type labels
- Chart type filter buttons (surface analysis, forecast, wave chart)
- Status indicators for upcoming/active/completed broadcasts
- Match existing color scheme and font choices from ravensdr.css

**Acceptance criteria:**
- Styles consistent with existing ravenSDR panels
- Responsive layout for decoded WEFAX charts
- Thumbnail grid displays cleanly for chart history
- Visual distinction between broadcast states (upcoming, active, completed)

---

### T090 — Integrate WEFAX panel into main UI
**Files:** `code/templates/index.html` (modify), `code/static/ravensdr.js` (modify)
**Status:** Done

Add WEFAX panel to the main ravenSDR interface:

**index.html:**
- Add WEFAX panel section with container divs for broadcast schedule, active reception, decoded chart display, and chart history
- Include `<script src="/static/wefax.js"></script>` and `<link rel="stylesheet" href="/static/wefax.css">`
- Place alongside APT satellite panel — both are weather imagery panels

**ravensdr.js:**
- Initialize WEFAX panel on page load
- Add WEFAX tab/section toggle if using tabbed layout
- Coordinate with APT satellite panel — when either is actively recording, show combined "SDR busy" indicator

**Acceptance criteria:**
- WEFAX panel visible in main UI
- Panel initializes correctly on page load
- No conflicts with existing UI panels (weather, satellite, ADS-B)
- SDR busy state visible when WEFAX or APT recording is active

---

### T091 — Update setup script for WEFAX dependencies
**File:** `code/setup.sh` (modify)
**Status:** Done

Add WEFAX dependencies to the setup script:

- Install fldigi: `sudo apt install fldigi -y`
- Install Xvfb for headless fldigi operation: `sudo apt install xvfb -y`
- Create `code/static/images/wefax/` directory for decoded charts
- Create `/tmp/ravensdr/wefax/` directory for intermediate audio files
- Document in setup output:
  - fldigi requires Xvfb on headless Raspberry Pi
  - Long wire antenna (5–10m) strongly recommended for HF reception
  - `-D 2` is Q-branch direct sampling, correct for RTL-SDR Blog V4

**Acceptance criteria:**
- fldigi installed and on PATH
- Xvfb installed for headless operation
- Required directories created
- Setup script remains idempotent
- Antenna and direct sampling guidance printed during setup

---

### T092 — Write unit tests for WEFAX scheduler
**File:** `code/tests/unit/test_wefax_scheduler.py`
**Status:** Done

Test the WEFAX scheduler module:

- NMC schedule parsing returns correct number of daily broadcasts
- NOJ schedule parsing returns correct frequencies
- `get_upcoming_broadcasts()` returns broadcasts sorted by start time
- Broadcasts outside the requested time window are excluded
- Frequency selection prefers lower frequencies at night (UTC 06:00–18:00 → high freq, else low freq)
- Surface analysis and 24hr forecast windows are marked as priority
- Hardcoded fallback schedule matches expected NMC/NOJ broadcast times
- Empty/unreachable schedule URL falls back to hardcoded schedule gracefully
- `refresh_schedule()` updates cached schedule data

**Acceptance criteria:**
- All unit tests pass
- Schedule parsing tested against known NMC broadcast table
- Frequency selection logic verified for day/night conditions
- Fallback behavior tested for unreachable schedule source

---

### T093 — Write unit tests for WEFAX receiver
**File:** `code/tests/unit/test_wefax_receiver.py`
**Status:** Done

Test the WEFAX receiver module:

- rtl_fm command constructed with `-D 2` flag for direct sampling
- USB demodulation mode set correctly (`-M usb`)
- Frequency offset of -1.9 kHz applied (e.g., 8682.0 kHz listed → 8680.1 kHz tuned)
- Sample rate and output rate correct (`-s 12k -r 11025`)
- fldigi command constructed correctly for WEFAX decode
- Output filename follows expected naming convention (station, frequency, chart type, timestamp)
- Socket.IO event payload contains all required metadata fields
- Intermediate audio files cleaned up after successful decode

**Test fixture:**
- Include a sample WEFAX audio WAV in `code/tests/fixtures/` for offline decode testing (or mock the fldigi call)

**Acceptance criteria:**
- All unit tests pass
- CLI command construction verified for both rtl_fm and fldigi
- Frequency offset calculation verified
- Filename generation tested for all chart types

---

### T094 — Integration test for end-to-end WEFAX pipeline
**File:** `code/tests/integration/test_wefax_pipeline.py`
**Status:** Done

Integration test for the full WEFAX pipeline:

- Test scheduler → receiver → decoder → UI event chain with mocked hardware
- Verify SDR enters and exits WEFAX mode correctly (direct sampling on/off)
- Verify decoded image file is created in correct location with correct filename
- Verify Socket.IO events emitted with correct payloads
- Verify APT priority: if APT pass is scheduled during WEFAX window, WEFAX defers
- Test frequency offset calculation for multiple stations and frequencies

**Live test (manual):**
- Tune to NMC on 8682 kHz during a known broadcast window and verify decode pipeline produces a PNG
- Document expected signal levels: NMC on 8682 kHz should be receivable from Redmond WA with a basic antenna during daytime
- NOJ on 4298 kHz is stronger at night from Redmond

Mark with `@pytest.mark.integration`. Include manual test procedure for live broadcast validation.

**Acceptance criteria:**
- Mocked pipeline test passes end-to-end
- SDR mode transitions verified (VHF → HF direct sampling → VHF)
- File output and event emission verified
- APT priority enforcement verified
- Manual test procedure documented for live broadcast validation

---

## Dependency Chain
```
T084 (scheduler) → T085 (receiver) → T086 (input source mode)
T084 → T087 (API routes)
T087 → T088 (WEFAX UI) → T089 (CSS) → T090 (layout integration)
T091 (setup) — independent, can run in parallel
T084 → T092 (scheduler tests)
T085 → T093 (receiver tests)
T086 + T087 → T094 (integration test)
```

## Success Criteria
- WEFAX charts decoded from NMC and NOJ HF broadcasts using RTL-SDR V4 direct sampling
- Broadcast schedule drives automatic recording during known transmission windows
- Decoded greyscale PNG charts displayed in dedicated UI panel alongside APT satellite imagery
- Chart history browsable and filterable by chart type
- SDR mode transitions cleanly between VHF/UHF scanning and HF direct sampling
- APT satellite passes take priority over WEFAX windows
- fldigi operates headlessly via Xvfb on Raspberry Pi
- All unit and mocked integration tests pass
