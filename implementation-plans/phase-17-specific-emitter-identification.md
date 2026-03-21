# Phase 17 — Specific Emitter Identification (SEI)

## Overview

Every radio transmitter has unique hardware fingerprints embedded in its RF emissions — oscillator phase noise patterns, power amplifier nonlinearities, I/Q imbalance, switching transients, frequency drift characteristics. These fingerprints are consistent across transmissions and detectable in raw IQ data even when content is encrypted, frequency-hopped, or otherwise unidentifiable. A CNN trained on raw IQ samples (not spectrograms) learns these fingerprints and can re-identify a specific physical transmitter across sessions. ravenSDR implements SEI as a passive identification layer on top of the signal classification pipeline — first classify modulation type, then attempt emitter fingerprint matching against a local database of known emitters.

## Why This Matters

SEI is an active area of defense and intelligence research. Applications include:
- Identifying specific radio devices even when they change frequency or encryption keys
- Detecting spoofed or cloned transmitters (fingerprint won't match)
- Tracking movement of a specific device across geographic coverage areas
- Attribution of anonymous transmissions to known hardware

The Hailo-8L running SEI inference on raw IQ is a legitimate edge implementation of a capability that normally requires rack-mounted signal processing hardware. This system operates in passive receive-only mode only.

## Technical Approach

Two-stage pipeline:
1. Signal classification (phase 16) identifies modulation type and segments individual transmissions
2. SEI model processes raw IQ of each transmission and produces an embedding vector (fingerprint)
3. Embedding compared against database of known emitter fingerprints via cosine similarity
4. Match above threshold: known emitter, log re-identification event
5. No match: new emitter, store fingerprint, assign anonymous ID (EMITTER-001 etc)

## Model Architecture

- Not a standard ImageNet classifier — raw IQ input, not spectrogram
- **Input:** complex IQ samples as 2-channel float32 tensor (I on channel 0, Q on channel 1), 1024 samples per window
- **Architecture:** 1D CNN + attention mechanism → 128-dimensional embedding vector
- **Training objective:** metric learning (triplet loss or contrastive loss) — same emitter embeddings cluster together, different emitters push apart
- **Reference architecture:** RF fingerprinting literature (Merchant et al. 2019, Riyaz et al. 2018)
- **Hailo-8L compatibility:** 1D CNN with attention compiles to HEF via DFC v3.x — document layer constraints

## Training Data

- Requires captures from multiple known transmitters of the same type (e.g. 5 different RTL-SDR dongles, 3 different ADS-B transponders)
- Each transmission from a known device is a labeled sample
- Minimum viable dataset: 10 transmitters × 1000 transmissions each
- **ravenSDR self-collection:** log raw IQ segments for every ADS-B transmission with ICAO hex as emitter label — aircraft transponders are perfect SEI training targets since ICAO hex provides ground truth identity
- **ADS-B ground truth:** ICAO hex code IS the emitter identity. Collect IQ, label with hex, train. Then test if model re-identifies aircraft from IQ alone without decoding the ADS-B frame.

## Emitter Database

- New file: `code/ravensdr/data/emitter_db.json` — stores emitter records
- Each record: emitter_id, first_seen, last_seen, frequency_history, embedding_centroid (mean of all observed embeddings), observation_count, label (user-assigned or ICAO hex for ADS-B)
- Embedding centroid updated with exponential moving average on each new observation
- Database grows passively — every new unmatched emitter gets enrolled automatically

## New Files
| File | Purpose |
|------|---------|
| `code/ravensdr/sei_model.py` | Hailo inference wrapper for SEI embedding model, cosine similarity matcher, emitter database manager |
| `code/ravensdr/iq_segmenter.py` | Transmission boundary detector (squelch-based), segments individual transmissions from continuous IQ stream |
| `code/ml/sei/train.py` | Triplet loss training script, PyTorch |
| `code/ml/sei/export_onnx.py` | ONNX export |
| `code/ml/sei/compile_hef.py` | Hailo DFC compilation for HAILO8L |
| `code/ml/sei/collect.py` | ADS-B-labeled IQ collection script for training data generation |
| `code/ml/sei/evaluate.py` | Equal error rate, ROC curve, rank-1 identification accuracy |
| `code/static/sei.js` | Emitter tracking panel UI |
| `code/static/sei.css` | Panel styles |
| `code/ravensdr/data/emitter_db.json` | Emitter database (initially empty) |

## Modified Files
| File | Changes |
|------|---------|
| `code/ravensdr/app.py` | `/api/emitters` route (database), `/api/emitters/<id>` route (specific emitter history), `emitter_identified` and `new_emitter` Socket.IO events |
| `code/ravensdr/signal_classifier.py` | Pipe classified transmission segments to SEI pipeline |
| `code/templates/index.html` | Emitter tracking panel |
| `code/static/ravensdr.js` | Emitter panel integration |
| `code/setup.sh` | No new Pi dependencies beyond phase 16 |

## UI Emitter Tracking Panel

- **Known emitters list:** emitter ID, label, first seen, last seen, observation count, frequency history
- **Recent identifications:** scrolling feed of re-identification events with timestamp and confidence
- **New emitter alerts:** flag when previously unseen fingerprint enrolled
- **ADS-B correlation:** if emitter_id matches an ICAO hex in ADS-B database, show aircraft details alongside fingerprint data
- **Emitter labeling:** allow user to assign human-readable label to any emitter ID

## ADS-B Bootstrap Experiment

Getting started guide for validating the SEI pipeline end-to-end:
1. Run ravenSDR with ADS-B active
2. Enable IQ logging with ICAO hex labels via `collect.py`
3. Collect 24 hours of labeled ADS-B IQ data (dozens of aircraft, thousands of transmissions)
4. Train SEI model on collected data
5. Test: does the model re-identify a specific aircraft from IQ alone, without decoding the ADS-B frame?
6. This validates the entire SEI pipeline end-to-end with ground truth before applying to unknown emitters

## Operational Security Note

ravenSDR SEI operates in passive receive-only mode. No transmission occurs. All monitored signals are from third-party transmitters in publicly accessible spectrum. Users are responsible for compliance with applicable laws regarding signal intelligence collection in their jurisdiction. The system does not decrypt encrypted signals — it identifies hardware characteristics only.

## Known Limitations

- SEI accuracy degrades with low SNR — minimum ~15 dB SNR recommended for reliable fingerprinting
- Transmitter fingerprints can drift with temperature — embeddings collected in cold conditions may not match summer captures from same device
- ADS-B transponder replacement or repair changes the fingerprint — database entry becomes stale
- 1D CNN + attention may require architectural adjustment to compile cleanly to Hailo-8L HEF — document known DFC constraints for non-standard layer types
- Training requires x86 machine with GPU strongly recommended (CPU training is very slow for metric learning)
- False positive rate increases as emitter database grows — document recommended database size limits and pruning strategy
- This is research-grade capability, not production-grade. Accuracy claims should be validated on local data before operational use.

---

## Tasks

### T121 — Create ADS-B-labeled IQ collection script
**File:** `code/ml/sei/collect.py`
**Status:** Not started

Create the training data collection script for SEI:

- **ADS-B integration:** hook into existing ADS-B decoder to get ICAO hex codes with timestamps
- **IQ capture:** capture raw IQ segment (1024 samples) for each decoded ADS-B transmission
- **Labeling:** associate each IQ segment with the ICAO hex code of the transmitting aircraft
- **Storage:** save labeled IQ segments to `code/ml/sei/data/collected/` organized by ICAO hex:
  ```
  data/collected/
  ├── A1B2C3/
  │   ├── 2026-03-16T14_22_01_001.npy
  │   ├── 2026-03-16T14_22_01_234.npy
  │   └── ...
  ├── D4E5F6/
  │   └── ...
  ```
- **Metadata log:** JSON file mapping each sample to ICAO hex, timestamp, frequency, SNR estimate
- **Collection statistics:** log total samples, unique emitters, samples per emitter
- **Minimum samples alert:** warn when any emitter has fewer than 100 samples (insufficient for training)
- **CLI interface:** `python collect.py --duration 24h --output_dir data/collected/ --min_snr 15`

**Acceptance criteria:**
- IQ segments captured and labeled with correct ICAO hex codes
- Directory structure organized by emitter ID
- Metadata log tracks all samples with timestamps and SNR
- Collection runs unattended for specified duration
- Statistics reported on completion

---

### T122 — Create IQ transmission segmenter
**File:** `code/ravensdr/iq_segmenter.py`
**Status:** Not started

Create the transmission boundary detection module:

- **Squelch-based segmentation:** monitor IQ power level, detect transmission start (power rises above threshold) and end (power drops below threshold)
- **Minimum transmission length:** 50 ms (ignore shorter bursts as noise)
- **Maximum transmission length:** 30 seconds (cap to prevent stuck-on-transmit from filling memory)
- **Hysteresis:** require power to stay below threshold for 100 ms before declaring end-of-transmission (prevents splitting on brief dropouts)
- **Output:** for each detected transmission, emit a segment containing:
  - Raw IQ samples (numpy array of complex64)
  - Start timestamp
  - Duration in milliseconds
  - Center frequency
  - Estimated SNR (signal power minus noise floor)
- **Integration with signal_classifier.py:** each segment is first classified by modulation type (phase 16), then passed to SEI for fingerprinting
- **Buffer management:** ring buffer of last 10 seconds of IQ data, segments extracted from buffer on transmission end

**Acceptance criteria:**
- Transmission boundaries detected accurately from power thresholds
- Hysteresis prevents false splits on brief signal dropouts
- Duration limits enforced (50 ms minimum, 30 s maximum)
- SNR estimated correctly from signal vs noise floor power
- Segments emitted with all required metadata

---

### T123 — Create triplet loss training script for SEI model
**File:** `code/ml/sei/train.py`
**Status:** Not started

Create the SEI model training script:

- **Model architecture:**
  - Input: 2-channel float32 tensor (I, Q), 1024 samples per window
  - 1D CNN: 4 convolutional layers (32, 64, 128, 256 filters), kernel size 7, ReLU, batch norm
  - Attention: self-attention layer after final conv layer
  - Embedding head: global average pooling → FC 256 → FC 128 (embedding dimension)
  - L2 normalize output embedding
- **Training objective:** triplet loss with semi-hard negative mining
  - Anchor: IQ segment from emitter A
  - Positive: different IQ segment from same emitter A
  - Negative: IQ segment from different emitter B
  - Margin: 0.3 (tunable)
- **Batch construction:** P emitters × K samples per emitter per batch (P=8, K=4 default)
- **Optimizer:** Adam, lr=1e-3
- **Schedule:** step decay, halve lr every 20 epochs
- **Epochs:** 100 (configurable)
- **Validation:** rank-1 identification accuracy on held-out set (for each query, find nearest embedding in gallery, check if same emitter)
- **Output:** `sei_model.pth` saved to `code/ml/sei/checkpoints/`
- **CLI args:** `--data_dir`, `--epochs`, `--embedding_dim`, `--margin`, `--output_dir`

**Acceptance criteria:**
- Triplet loss decreases over training
- Rank-1 identification accuracy improves on validation set
- Embeddings from same emitter cluster tightly (visualize with t-SNE)
- Model checkpoint saved at best validation accuracy
- Training reproducible with fixed random seed

---

### T124 — Create ONNX export script for SEI model
**File:** `code/ml/sei/export_onnx.py`
**Status:** Not started

Export trained SEI PyTorch model to ONNX:

- Load `sei_model.pth` from checkpoints directory
- Export with fixed input shape: (1, 2, 1024) float32
- ONNX opset version 13 (compatible with Hailo DFC v3.x)
- Verify ONNX model with `onnxruntime` inference on sample input
- Compare ONNX output embeddings to PyTorch output — max absolute difference < 1e-5
- Save to `code/ml/sei/exports/sei_model.onnx`

**Acceptance criteria:**
- ONNX model exported successfully
- Embedding outputs match PyTorch within tolerance
- Input/output shapes documented in export metadata
- 1D CNN + attention layers export cleanly to ONNX

---

### T125 — Create Hailo DFC compilation script for SEI model
**File:** `code/ml/sei/compile_hef.py`
**Status:** Not started

Compile SEI ONNX model to Hailo HEF:

- Load ONNX model from exports directory
- Use Hailo Dataflow Compiler (DFC) v3.31+ Python API
- Target: HAILO8L (not HAILO8 or HAILO10H)
- **Special considerations for 1D CNN:**
  - 1D convolutions may need reshaping to 2D for Hailo compatibility (1×1024 → 1D, or reshape to 2D equivalent)
  - Attention layer: verify self-attention compiles to HEF — may need to replace with channel attention (SE block) if full self-attention unsupported
  - Document any required architectural modifications for Hailo compatibility
- Quantization: post-training quantization using calibration dataset (100 random IQ segments)
- Output: `sei_model.hef` saved to `code/ml/sei/exports/`
- Log compilation metrics: model size, estimated FPS, layer allocation
- **Requirement:** must run on x86 Ubuntu 22 with DFC installed

**Acceptance criteria:**
- HEF compiled for HAILO8L target
- 1D CNN layers handled correctly (document any reshaping needed)
- Attention layer compiles or is replaced with compatible alternative
- Quantization calibration uses representative IQ data
- Output HEF file size and estimated performance logged

---

### T126 — Create SEI evaluation script
**File:** `code/ml/sei/evaluate.py`
**Status:** Not started

Evaluate SEI model performance:

- Load model (PyTorch .pth, ONNX, or HEF — selectable via CLI arg)
- Run inference on held-out test set of labeled IQ segments
- **Metrics:**
  - Rank-1 identification accuracy (correct emitter identified as top match)
  - Rank-5 identification accuracy
  - Equal error rate (EER) — threshold where false accept rate equals false reject rate
  - ROC curve (false accept rate vs true accept rate, saved as PNG)
  - Cosine similarity distribution: same-emitter pairs vs different-emitter pairs (histogram, saved as PNG)
  - t-SNE visualization of embedding space colored by emitter (saved as PNG)
- **Output:** JSON report with all metrics, ROC curve PNG, similarity histogram PNG, t-SNE PNG
- Save to `code/ml/sei/reports/`
- Print summary table to stdout

**Acceptance criteria:**
- All metrics computed and saved
- ROC curve shows separation between same-emitter and different-emitter pairs
- t-SNE visualization shows emitter clustering
- Target: >85% rank-1 identification accuracy on held-out ADS-B test set

---

### T127 — Create Hailo SEI inference wrapper and emitter database manager
**File:** `code/ravensdr/sei_model.py`
**Status:** Not started

Create the SEI inference and emitter management module:

- **Hailo inference:**
  - Load HEF via HailoRT VDevice + InferModel API
  - Input: 2-channel float32 tensor (I, Q), 1024 samples
  - Output: 128-dimensional L2-normalized embedding vector
- **Cosine similarity matching:**
  - Compare embedding against all centroids in emitter database
  - Match threshold: cosine similarity > 0.85 (tunable)
  - If multiple matches above threshold, select highest similarity
- **Emitter database operations:**
  - `load_db()` — load `emitter_db.json` into memory
  - `save_db()` — persist to disk (atomic write with temp file + rename)
  - `match_emitter(embedding)` — find best matching emitter or return None
  - `enroll_emitter(embedding, label=None)` — create new emitter record with auto-assigned ID (EMITTER-001, etc)
  - `update_emitter(emitter_id, embedding)` — update centroid with exponential moving average (alpha=0.1)
  - `get_emitter(emitter_id)` — return full emitter record
  - `list_emitters()` — return all emitter records sorted by last_seen
  - `label_emitter(emitter_id, label)` — assign human-readable label
- **Event emission:**
  - `emitter_identified` Socket.IO event when known emitter re-identified:
    ```json
    {
        "emitter_id": "EMITTER-042",
        "label": "ASA355 (A1B2C3)",
        "confidence": 0.92,
        "frequency_hz": 1090000000,
        "timestamp": "2026-03-16T14:22:01Z",
        "observation_count": 347
    }
    ```
  - `new_emitter` Socket.IO event when new fingerprint enrolled
- **CPU fallback:** skip SEI when Hailo unavailable (log warning, no crash)

**Acceptance criteria:**
- Hailo inference returns 128-dimensional embedding from IQ input
- Cosine similarity matching identifies known emitters above threshold
- New emitters enrolled automatically with sequential IDs
- Centroid updated with EMA on re-identification
- Database persists to disk atomically
- Socket.IO events emitted for identification and enrollment
- CPU fallback degrades gracefully

---

### T128 — Add emitter API routes and Socket.IO events to Flask app
**File:** `code/ravensdr/app.py` (modify)
**Status:** Not started

Add emitter tracking endpoints and events:

**REST endpoints:**
- `GET /api/emitters` — paginated list of known emitters, sorted by last_seen descending. Query params: `?limit=50&offset=0`
  ```json
  {
      "emitters": [
          {
              "emitter_id": "EMITTER-042",
              "label": "ASA355 (A1B2C3)",
              "first_seen": "2026-03-14T08:12:00Z",
              "last_seen": "2026-03-16T14:22:01Z",
              "observation_count": 347,
              "frequencies": [1090000000]
          }
      ],
      "total": 142
  }
  ```
- `GET /api/emitters/<id>` — full emitter record with frequency history and observation timeline
- `POST /api/emitters/<id>/label` — assign human-readable label to emitter (JSON body: `{"label": "My RTL-SDR"}`)

**Socket.IO events (server → client):**
- `emitter_identified` — emitted on re-identification of known emitter
- `new_emitter` — emitted on enrollment of new fingerprint

Initialize SEI model on app startup (after signal classifier). Wire iq_segmenter output through signal_classifier then to SEI pipeline.

**Acceptance criteria:**
- `/api/emitters` returns paginated emitter list
- `/api/emitters/<id>` returns full emitter record
- Label assignment persists to emitter database
- Socket.IO events emitted for identification and enrollment
- SEI pipeline initializes after signal classifier

---

### T129 — Create emitter tracking panel JavaScript module
**File:** `code/static/sei.js`
**Status:** Not started

Create the emitter tracking panel frontend module:

1. **Known emitters table** — sortable table showing emitter ID, label, first seen, last seen, observation count, frequency list. Click row to expand detail view.
2. **Recent identifications feed** — scrolling list of re-identification events with timestamp, emitter ID/label, confidence. Most recent at top. Cap at 100 visible entries.
3. **New emitter alerts** — highlighted notification when previously unseen emitter enrolled, showing assigned ID and frequency
4. **ADS-B correlation** — when emitter has an ICAO hex label, show aircraft type, callsign, and last known position alongside fingerprint data
5. **Emitter labeling** — inline edit field to assign human-readable label to any emitter (POST to `/api/emitters/<id>/label`)
6. **Database statistics** — total emitters, identifications today, new enrollments today, average confidence

Listen for Socket.IO events:
- `emitter_identified` — update feed, flash matching row in table
- `new_emitter` — show alert, add to table

Fetch initial state on page load:
- `/api/emitters?limit=50` for known emitters

**Acceptance criteria:**
- Emitter table renders and sorts correctly
- Re-identification feed updates in real time
- New emitter alerts visible and distinct
- Label editing works via inline field
- ADS-B correlation displays when available

---

### T130 — Create emitter tracking panel CSS styles
**File:** `code/static/sei.css`
**Status:** Not started

Style the emitter tracking panel consistent with existing ravenSDR UI:

- Emitter table: sortable columns, row hover highlight, expandable detail rows
- Identification feed: monospace timestamps, confidence badge (color-coded)
- New emitter alert: distinct highlight animation (brief pulse)
- ADS-B correlation: aircraft icon or badge when ICAO hex linked
- Label edit field: inline edit with save/cancel on blur/enter
- Database statistics: compact summary bar at panel top
- Match existing color scheme and font choices from ravensdr.css

**Acceptance criteria:**
- Styles consistent with existing ravenSDR panels
- Table sortable and readable
- Alerts and identifications visually distinct
- Label editing UI clean and intuitive

---

### T131 — Integrate emitter tracking panel into main UI
**Files:** `code/templates/index.html` (modify), `code/static/ravensdr.js` (modify)
**Status:** Not started

Add emitter tracking panel to the main ravenSDR interface:

**index.html:**
- Add emitter tracking panel section with container divs for emitter table, identification feed, new emitter alerts, and database statistics
- Include `<script src="/static/sei.js"></script>` and `<link rel="stylesheet" href="/static/sei.css">`

**ravensdr.js:**
- Initialize emitter tracking panel on page load
- Add emitter tab/section toggle if using tabbed layout
- Show SEI status indicator (active/inactive, emitter count)

**Acceptance criteria:**
- Emitter tracking panel visible in main UI
- Panel initializes correctly on page load
- No conflicts with existing UI panels

---

### T132 — Wire signal classifier output to SEI pipeline
**File:** `code/ravensdr/signal_classifier.py` (modify)
**Status:** Not started

Connect signal classification to SEI fingerprinting:

- After classifying a transmission segment's modulation type, pass the raw IQ segment to `sei_model.py` for fingerprinting
- Only send segments to SEI that meet minimum requirements:
  - Classification confidence > 0.7 (known modulation type)
  - Estimated SNR > 15 dB (sufficient for fingerprinting)
  - Duration > 100 ms (enough IQ data for meaningful embedding)
- Pass modulation type as context to SEI (helps interpret results)
- Handle SEI being unavailable gracefully (Hailo busy, model not loaded) — classification still works independently

**Acceptance criteria:**
- Classified segments forwarded to SEI pipeline
- SNR and duration filtering applied before SEI
- SEI unavailability does not block signal classification
- Modulation context passed with IQ segment

---

### T133 — Create initial empty emitter database
**File:** `code/ravensdr/data/emitter_db.json`
**Status:** Not started

Create the initial empty emitter database file:

```json
{
    "version": 1,
    "created": "2026-03-17T00:00:00Z",
    "emitters": [],
    "next_id": 1
}
```

**Acceptance criteria:**
- Valid JSON file
- Schema documented in comments or README
- next_id starts at 1 for EMITTER-001 assignment

---

### T134 — Write unit tests for IQ segmenter
**File:** `code/tests/unit/test_iq_segmenter.py`
**Status:** Not started

Test the transmission boundary detection module:

**Boundary detection tests:**
- Synthetic signal with clear on/off transitions detected at correct timestamps
- Minimum duration filter: 30 ms burst rejected, 60 ms burst accepted
- Maximum duration filter: 35 second transmission capped at 30 seconds
- Hysteresis: 80 ms gap within transmission does not split it, 120 ms gap does split

**SNR estimation tests:**
- Known signal power and noise floor produce correct SNR estimate
- SNR calculated correctly for varying noise levels

**Segment output tests:**
- Emitted segment contains correct IQ samples (not shifted or truncated)
- Start timestamp accurate to within 10 ms
- Duration matches expected value

**Test fixture:**
- Synthetic IQ data with 3 transmissions of known duration and power levels, with noise floor between them

**Acceptance criteria:**
- All boundary detection tests pass
- SNR estimation accurate to within 1 dB
- Segments contain correct IQ data
- Hysteresis prevents false splits

---

### T135 — Write unit tests for SEI model and emitter database
**File:** `code/tests/unit/test_sei_model.py`
**Status:** Not started

Test the SEI inference and database module:

**Cosine similarity tests:**
- Identical embeddings produce similarity of 1.0
- Orthogonal embeddings produce similarity of 0.0
- Known similar embeddings (cosine > 0.85) match correctly
- Known dissimilar embeddings (cosine < 0.85) do not match

**Emitter database tests:**
- `enroll_emitter()` creates record with correct auto-assigned ID
- `match_emitter()` returns correct emitter for known embedding
- `match_emitter()` returns None for unknown embedding
- `update_emitter()` applies EMA correctly to centroid
- `label_emitter()` persists label to record
- `list_emitters()` sorted by last_seen descending
- Database save/load round-trips correctly (atomic write verified)

**EMA centroid update tests:**
- After 10 updates with alpha=0.1, centroid has shifted appropriately from initial value
- Centroid remains L2-normalized after updates

**Acceptance criteria:**
- Cosine similarity matching tested for match/no-match cases
- Database CRUD operations all tested
- EMA update verified mathematically
- Atomic save verified (temp file + rename pattern)

---

### T136 — Integration test for end-to-end SEI pipeline
**File:** `code/tests/integration/test_sei_pipeline.py`
**Status:** Not started

Integration test for the full SEI pipeline:

- Feed synthetic IQ data with 3 distinct emitter fingerprints through iq_segmenter → signal_classifier → sei_model → database → API → Socket.IO event chain
- **Enrollment test:** first observation of each emitter triggers `new_emitter` event and database enrollment
- **Re-identification test:** second observation of same emitter triggers `emitter_identified` event with correct ID
- **Database persistence:** verify emitter records saved to disk after enrollment and re-identification
- **API verification:**
  - `/api/emitters` returns all 3 enrolled emitters
  - `/api/emitters/EMITTER-001` returns correct record
  - Label assignment via POST persists
- **Socket.IO verification:** correct events emitted for enrollment and re-identification

**ADS-B integration test:**
- Simulate ADS-B decoder output with ICAO hex codes
- Verify IQ segments labeled with hex codes
- Verify emitter enrolled with ICAO hex as label
- Verify re-identification matches correct ICAO hex

Mark with `@pytest.mark.integration`.

**Acceptance criteria:**
- Enrollment and re-identification work end-to-end
- Database persistence verified
- API endpoints return correct data
- Socket.IO events emitted with correct payloads
- ADS-B labeling integration verified

---

## Dependency Chain
```
Phase 16 (signal classifier) → T122 (segmenter) → T132 (wire classifier to SEI)
T121 (ADS-B collection) → T123 (training) → T124 (ONNX export) → T125 (HEF compilation)
T123 → T126 (evaluation)
T122 → T127 (SEI inference + database)
T133 (empty database) → T127
T127 → T128 (API routes)
T128 → T129 (SEI UI) → T130 (CSS) → T131 (layout integration)
T132 → T127
T122 → T134 (segmenter tests)
T127 → T135 (SEI model tests)
T122 + T127 + T128 + T132 → T136 (integration test)
```

## Success Criteria
- Individual radio transmitters re-identified by hardware fingerprint across sessions
- ADS-B transponders identified by IQ fingerprint alone, validated against ICAO hex ground truth
- >85% rank-1 identification accuracy on held-out ADS-B test set
- New emitters enrolled automatically with sequential IDs
- Emitter database grows passively during normal operation
- Cosine similarity matching runs at inference speed on Hailo-8L NPU
- Emitter tracking panel displays known emitters, re-identifications, and new enrollments in real time
- User can assign labels to emitters via UI
- SEI operates as passive layer on top of signal classification — does not block or slow classification pipeline
- All unit and mocked integration tests pass
