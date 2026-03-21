# Phase 16 — Signal Classification via Spectrogram CNN

## Overview

Convert raw IQ samples from the RTL-SDR into spectrogram images (time on X axis, frequency on Y axis, power as pixel intensity) and run a CNN classifier on the Hailo-8L NPU to identify modulation type in real time. Target classes: AM, FM, WFM, SSB, P25, DMR, ADS-B, NOAA APT, WEFAX, CW (morse), unknown. This runs continuously as a background pipeline — every chunk of IQ data gets classified before being routed to the appropriate decoder. ravenSDR stops guessing modulation from frequency presets and starts knowing from signal shape.

## IQ to Spectrogram Pipeline

- Capture raw IQ samples from rtl_fm or direct rtlsdr Python bindings (pyrtlsdr)
- FFT window: 256 or 512 point, Hann window, 50% overlap
- Output: 2D numpy array, shape (time_bins, freq_bins), values in dBm
- Normalize to 0-255 uint8 for CNN input (min-max scaling per chunk)
- Resize to model input size: 224x224 (MobileNetV2) or 260x260 (EfficientNet-B2)
- Each spectrogram image represents ~100ms of signal at 2.4MHz sample rate

## Model Selection for Hailo-8L

- **Primary:** MobileNetV2 — already in Hailo Model Zoo compiled for HAILO8L, fast inference, good accuracy on spectrogram classification
- **Alternative:** EfficientNet-B0 — higher accuracy, slightly slower, also in Model Zoo for HAILO8L
- Both support transfer learning from ImageNet weights — spectrogram classification responds well to this
- HEF files available from Hailo Model Zoo v2.x branch (HAILO8L specific, not master branch)
- Do NOT use Hailo-10H models — incompatible architecture

## Training Data

- **Dataset:** RadioML 2018.01A (DeepSig) — 24 modulation classes, 2.5M samples, industry standard benchmark. Download from https://www.deepsig.ai/datasets
- **Augmentation:** random frequency shift, SNR variation, phase rotation — improves generalization to real-world conditions
- **Custom classes to add beyond RadioML:** ADS-B (generate from dump1090 captures), NOAA APT (generate from known 137MHz recordings), WEFAX (generate from known HF recordings)
- **Self-supervised labeling:** ravenSDR auto-labels training data — when Whisper confirms voice on a known FM preset, that IQ chunk is labeled FM. When ADS-B frames decoded, label ADS-B. Passive self-supervised labeling.

## Training Pipeline (runs on x86, not Pi)

- New directory: `code/ml/signal_classifier/`
- `train.py` — PyTorch training script, MobileNetV2 fine-tuned on RadioML + custom classes
- `export_onnx.py` — export trained model to ONNX
- `compile_hef.py` — compile ONNX to HEF using Hailo Dataflow Compiler v3.x (HAILO8L target)
- `evaluate.py` — confusion matrix, per-class accuracy, SNR vs accuracy curves
- **Requirement:** compilation requires x86 Ubuntu 22 + Hailo DFC v3.31+ (same constraint as Whisper HEF compilation)

## Inference Pipeline on Pi (Hailo-8L)

- New file: `code/ravensdr/signal_classifier.py`
- Uses HailoRT VDevice + InferModel API (same pattern as Whisper pipeline)
- Input: 224x224 uint8 spectrogram image as numpy array
- Output: softmax probability vector over modulation classes
- Confidence threshold: only emit classification if top class > 0.7 confidence
- Inference rate: target 10 classifications per second (100ms chunks)
- CPU fallback: sklearn SVM or simple threshold classifier if Hailo unavailable

## New Files
| File | Purpose |
|------|---------|
| `code/ravensdr/signal_classifier.py` | Hailo inference wrapper, IQ to spectrogram converter, classification event emitter |
| `code/ravensdr/iq_capture.py` | Direct IQ capture via pyrtlsdr bypassing rtl_fm, feeds both signal_classifier and existing audio pipeline |
| `code/ml/signal_classifier/train.py` | PyTorch training script |
| `code/ml/signal_classifier/export_onnx.py` | ONNX export |
| `code/ml/signal_classifier/compile_hef.py` | Hailo DFC compilation |
| `code/ml/signal_classifier/evaluate.py` | Evaluation and confusion matrix |
| `code/ml/signal_classifier/dataset.py` | RadioML loader + custom class generator |
| `code/static/classifier.js` | Classification panel UI |
| `code/static/classifier.css` | Panel styles |

## Modified Files
| File | Changes |
|------|---------|
| `code/ravensdr/app.py` | `/api/classifier/status` route, `signal_classified` Socket.IO event |
| `code/ravensdr/input_source.py` | IQ capture mode alongside audio pipeline |
| `code/ravensdr/presets.py` | Add `expected_modulation` field to each preset for ground truth comparison |
| `code/templates/index.html` | Classification panel |
| `code/static/ravensdr.js` | Classification panel integration |
| `code/setup.sh` | `pip install pyrtlsdr`, `pip install torch` (training only, not on Pi) |

## UI Classification Panel

- **Current signal:** modulation type, confidence percentage, spectrogram image (last 2 seconds rendered as canvas)
- **Classification history:** scrolling feed of classifications with timestamp and frequency
- **Accuracy tracking:** when classification matches preset `expected_modulation`, log as correct. Display running accuracy %.
- **Confusion indicators:** flag when classifier is uncertain (top two classes within 10% of each other)

## Self-Supervised Labeling Pipeline

Feedback loop for continuous improvement:
1. ravenSDR monitors known preset frequency
2. ADS-B decoder confirms signal is ADS-B — IQ chunk auto-labeled
3. Whisper confirms voice content — IQ chunk labeled with modulation from preset
4. WEFAX decoder produces image — IQ chunk labeled WEFAX
5. Labeled chunks accumulate in `code/ml/signal_classifier/data/collected/`
6. Periodically retrain on collected data to improve real-world accuracy
7. Compile new HEF, deploy to Pi

## Known Limitations

- RadioML uses simulated channels — real-world multipath and interference degrades accuracy, expect 70-80% real-world vs 90%+ on benchmark
- P25 and DMR require higher SNR than AM/FM to classify reliably — document minimum SNR requirements
- HEF compilation requires x86 machine, cannot be done on Pi — document build/deploy workflow
- pyrtlsdr and rtl_fm cannot share the device simultaneously — IQ capture mode replaces rtl_fm, audio extracted from IQ directly
- Hailo-8L running both Whisper and signal classifier simultaneously requires multi-process service mode — document this configuration

---

## Tasks

### T106 — Create RadioML dataset loader and custom class generator
**File:** `code/ml/signal_classifier/dataset.py`
**Status:** Not started

Create the dataset module for signal classifier training:

- **RadioML 2018.01A loader:** load HDF5 dataset, extract IQ samples and modulation labels
- **IQ to spectrogram conversion:** 256 or 512 point FFT, Hann window, 50% overlap, output as 2D numpy array
- **Spectrogram normalization:** min-max scale to 0-255 uint8, resize to 224x224 (MobileNetV2 input)
- **Custom class generators:**
  - ADS-B: load raw IQ from dump1090 captures, label as ADS-B
  - NOAA APT: load IQ from known 137 MHz recordings, label as NOAA_APT
  - WEFAX: load IQ from known HF recordings, label as WEFAX
- **Data augmentation:** random frequency shift (±5% of bandwidth), SNR variation (add Gaussian noise at random levels), phase rotation (random 0-2π)
- **Train/val/test split:** 70/15/15 stratified by class
- **PyTorch Dataset class:** returns (spectrogram_tensor, label_index) pairs
- **Class mapping:** dict mapping class names to indices, saved as JSON alongside model

**Acceptance criteria:**
- RadioML HDF5 loaded and IQ samples converted to spectrograms
- Custom class samples integrated with RadioML dataset
- Augmentation applied during training, not validation/test
- Dataset class compatible with PyTorch DataLoader
- Class mapping JSON generated and saved

---

### T107 — Create PyTorch training script for MobileNetV2 signal classifier
**File:** `code/ml/signal_classifier/train.py`
**Status:** Not started

Create the training script:

- **Model:** MobileNetV2 pretrained on ImageNet, final classifier layer replaced with len(classes) outputs
- **Input:** 224x224 single-channel spectrogram (replicate to 3 channels for ImageNet-pretrained model)
- **Loss:** cross-entropy
- **Optimizer:** Adam, lr=1e-3 for new layers, lr=1e-5 for pretrained layers (differential learning rates)
- **Schedule:** cosine annealing over 50 epochs
- **Batch size:** 64 (configurable via CLI arg)
- **Logging:** per-epoch train/val loss and accuracy, best model checkpoint saved
- **Early stopping:** patience of 10 epochs on validation loss
- **Output:** `best_model.pth` saved to `code/ml/signal_classifier/checkpoints/`
- **CLI args:** `--dataset_path`, `--epochs`, `--batch_size`, `--lr`, `--output_dir`
- **GPU support:** auto-detect CUDA, fall back to CPU

**Acceptance criteria:**
- Training runs to completion on RadioML + custom classes
- Validation accuracy logged per epoch
- Best model checkpoint saved automatically
- Differential learning rates applied correctly
- Training reproducible with fixed random seed

---

### T108 — Create ONNX export script
**File:** `code/ml/signal_classifier/export_onnx.py`
**Status:** Not started

Export trained PyTorch model to ONNX:

- Load `best_model.pth` from checkpoints directory
- Export with fixed input shape: (1, 3, 224, 224) float32
- ONNX opset version 13 (compatible with Hailo DFC v3.x)
- Verify ONNX model with `onnxruntime` inference on sample input
- Compare ONNX output to PyTorch output — max absolute difference < 1e-5
- Save to `code/ml/signal_classifier/exports/signal_classifier.onnx`
- Save class mapping JSON alongside ONNX model

**Acceptance criteria:**
- ONNX model exported successfully
- Inference results match PyTorch within tolerance
- Input/output shapes documented in export metadata
- Class mapping JSON saved alongside model

---

### T109 — Create Hailo DFC compilation script
**File:** `code/ml/signal_classifier/compile_hef.py`
**Status:** Not started

Compile ONNX model to Hailo HEF:

- Load ONNX model from exports directory
- Use Hailo Dataflow Compiler (DFC) v3.31+ Python API
- Target: HAILO8L (not HAILO8 or HAILO10H)
- Quantization: post-training quantization using calibration dataset (100 random spectrograms from training set)
- Optimization: enable all HAILO8L-compatible optimizations
- Output: `signal_classifier.hef` saved to `code/ml/signal_classifier/exports/`
- Log compilation metrics: model size, estimated FPS, layer allocation
- **Requirement:** must run on x86 Ubuntu 22 with DFC installed — document this clearly

**Acceptance criteria:**
- HEF compiled for HAILO8L target
- Quantization calibration uses representative data
- Compilation completes without layer allocation errors
- Output HEF file size and estimated performance logged

---

### T110 — Create model evaluation script
**File:** `code/ml/signal_classifier/evaluate.py`
**Status:** Not started

Evaluate trained model performance:

- Load model (PyTorch .pth, ONNX, or HEF — selectable via CLI arg)
- Run inference on full test set
- **Metrics:**
  - Overall accuracy
  - Per-class precision, recall, F1
  - Confusion matrix (matplotlib heatmap, saved as PNG)
  - SNR vs accuracy curve (accuracy at each SNR level in RadioML dataset)
- **Output:** JSON report with all metrics, confusion matrix PNG, SNR curve PNG
- Save to `code/ml/signal_classifier/reports/`
- Print summary table to stdout

**Acceptance criteria:**
- All metrics computed and saved
- Confusion matrix clearly shows per-class performance
- SNR vs accuracy curve shows degradation at low SNR
- Target: >90% accuracy at SNR >10 dB on RadioML test set

---

### T111 — Create IQ capture module via pyrtlsdr
**File:** `code/ravensdr/iq_capture.py`
**Status:** Not started

Create direct IQ capture module bypassing rtl_fm:

- **pyrtlsdr integration:** open RTL-SDR device, configure center frequency, sample rate (2.4 MHz), gain
- **Streaming capture:** async callback-based IQ sample streaming
- **Audio extraction:** demodulate FM/AM/SSB from raw IQ in Python (replacing rtl_fm for this pipeline)
  - FM demodulation: frequency discriminator on complex IQ
  - AM demodulation: envelope detection (magnitude of complex IQ)
  - SSB demodulation: frequency shift + low-pass filter
- **Dual output:** raw IQ feeds signal classifier, demodulated audio feeds existing transcription pipeline
- **Device management:** mutex to prevent pyrtlsdr and rtl_fm from accessing device simultaneously
- **Configuration:** center frequency, sample rate, gain, device index — all configurable
- **Chunk size:** 2.4M samples/sec at 100ms chunks = 240K samples per chunk

**Acceptance criteria:**
- IQ samples captured via pyrtlsdr at configured sample rate
- FM/AM demodulation produces audio comparable to rtl_fm output
- Raw IQ and demodulated audio available simultaneously
- Device mutex prevents concurrent access conflicts
- Graceful fallback to rtl_fm if pyrtlsdr unavailable

---

### T112 — Create Hailo signal classifier inference wrapper
**File:** `code/ravensdr/signal_classifier.py`
**Status:** Not started

Create the signal classification inference module:

- **IQ to spectrogram conversion:**
  - Input: raw IQ chunk (240K complex samples, 100ms at 2.4 MHz)
  - FFT: 256-point, Hann window, 50% overlap
  - Output: 2D array (time_bins × freq_bins), values in dBm
  - Normalize to 0-255 uint8
  - Resize to 224x224 using numpy/scipy interpolation
- **Hailo inference:**
  - Load HEF via HailoRT VDevice + InferModel API
  - Input: 224x224 uint8 numpy array (expand to 3 channels)
  - Output: softmax probability vector
  - Parse output: map to class names via class mapping JSON
- **Confidence filtering:**
  - Emit classification only if top class confidence > 0.7
  - Flag uncertain classifications: top two classes within 10% of each other
- **Event emission:**
  - Emit `signal_classified` Socket.IO event with classification result
  - Payload: `{"modulation": "FM", "confidence": 0.94, "frequency_hz": 121500000, "timestamp": "...", "uncertain": false}`
- **CPU fallback:** simple threshold-based classifier using spectral features (bandwidth, peak-to-average ratio) if Hailo unavailable
- **Performance target:** 10 classifications per second (100ms per chunk)
- **Self-supervised logging:** when classification matches preset `expected_modulation`, log IQ chunk as confirmed training sample to `code/ml/signal_classifier/data/collected/`

**Acceptance criteria:**
- IQ to spectrogram conversion produces correct 224x224 images
- Hailo inference returns valid classification with confidence
- Confidence threshold filters low-confidence results
- CPU fallback operates when Hailo unavailable
- Socket.IO events emitted with correct payload
- Self-supervised samples logged when ground truth matches

---

### T113 — Add expected_modulation field to frequency presets
**File:** `code/ravensdr/presets.py` (modify)
**Status:** Not started

Add ground truth modulation type to each frequency preset:

- Add `expected_modulation` field to each preset dict
- Mapping:
  - VHF voice presets (air band, marine, NOAA weather): `"AM"` or `"FM"` as appropriate
  - 1090 MHz ADS-B: `"ADSB"`
  - 137 MHz NOAA APT: `"NOAA_APT"`
  - WEFAX HF frequencies: `"WEFAX"`
  - CW/morse frequencies: `"CW"`
  - P25/DMR trunked frequencies: `"P25"` or `"DMR"`
- Used by classifier accuracy tracking: compare predicted modulation to expected_modulation
- Presets without a known modulation: `"unknown"`

**Acceptance criteria:**
- All existing presets have `expected_modulation` field
- Modulation types match the target classification classes
- No breaking changes to existing preset usage

---

### T114 — Add signal classification API route and Socket.IO event to Flask app
**File:** `code/ravensdr/app.py` (modify)
**Status:** Not started

Add signal classification endpoints and events:

**REST endpoints:**
- `GET /api/classifier/status` — returns current classifier state:
  ```json
  {
      "active": true,
      "model": "mobilenetv2",
      "backend": "hailo",
      "classifications_total": 4523,
      "accuracy_vs_presets": 0.87,
      "last_classification": {
          "modulation": "FM",
          "confidence": 0.94,
          "frequency_hz": 121500000,
          "timestamp": "2026-03-16T14:22:01Z"
      }
  }
  ```

**Socket.IO events (server → client):**
- `signal_classified` — emitted on each classification above confidence threshold

Initialize signal classifier on app startup. Wire IQ capture to feed classifier pipeline.

**Acceptance criteria:**
- `/api/classifier/status` returns valid JSON with classifier state and accuracy
- `signal_classified` events emitted in real time
- Classifier initializes with app startup
- Accuracy tracking compares classifications against preset expected_modulation

---

### T115 — Create classification panel JavaScript module
**File:** `code/static/classifier.js`
**Status:** Not started

Create the signal classification panel frontend module:

1. **Current signal display** — modulation type (large text), confidence bar (0-100%), spectrogram canvas (last 2 seconds of spectrogram data rendered in real time)
2. **Classification history** — scrolling feed of classifications with timestamp, frequency, modulation type, and confidence. Most recent at top. Cap at 100 visible entries.
3. **Accuracy tracker** — running accuracy percentage comparing classifier output to preset expected_modulation. Display as percentage with correct/total counts.
4. **Uncertainty alerts** — highlight classifications where top two classes are within 10% confidence of each other

Listen for Socket.IO events:
- `signal_classified` — update current display, prepend to history, update accuracy

Fetch initial state on page load:
- `/api/classifier/status` for current state and accuracy

**Spectrogram canvas:**
- Render spectrogram as scrolling waterfall display on `<canvas>`
- X axis: time (scrolling left), Y axis: frequency, color: power intensity (blue-green-yellow-red colormap)
- Update at 10 fps matching classification rate

**Acceptance criteria:**
- Current signal updates in real time with each classification
- Spectrogram waterfall renders smoothly at 10 fps
- Classification history scrolls with new entries
- Accuracy percentage updates correctly
- Uncertainty flagged visually

---

### T116 — Create classification panel CSS styles
**File:** `code/static/classifier.css`
**Status:** Not started

Style the classification panel consistent with existing ravenSDR UI:

- Current signal: large modulation type label, confidence bar with color gradient (red < 0.7, yellow 0.7-0.85, green > 0.85)
- Spectrogram canvas: fixed height, full panel width, dark background
- Classification history: monospace feed, modulation type badges color-coded by class
- Accuracy tracker: prominent percentage display
- Uncertainty indicator: yellow border or highlight on uncertain classifications
- Match existing color scheme and font choices from ravensdr.css

**Acceptance criteria:**
- Styles consistent with existing ravenSDR panels
- Confidence bar color gradient renders correctly
- Modulation badges visually distinct per class
- Spectrogram canvas sized appropriately

---

### T117 — Integrate classification panel into main UI
**Files:** `code/templates/index.html` (modify), `code/static/ravensdr.js` (modify)
**Status:** Not started

Add classification panel to the main ravenSDR interface:

**index.html:**
- Add classification panel section with container divs for current signal, spectrogram canvas, classification history, and accuracy tracker
- Include `<script src="/static/classifier.js"></script>` and `<link rel="stylesheet" href="/static/classifier.css">`

**ravensdr.js:**
- Initialize classification panel on page load
- Add classification tab/section toggle if using tabbed layout
- Show classifier status indicator (active/inactive, backend type)

**Acceptance criteria:**
- Classification panel visible in main UI
- Panel initializes correctly on page load
- No conflicts with existing UI panels

---

### T118 — Update setup script for signal classification dependencies
**File:** `code/setup.sh` (modify)
**Status:** Not started

Add signal classification dependencies:

- `pip install pyrtlsdr` — direct IQ capture
- `pip install torch torchvision` — training only, NOT on Pi (document clearly)
- `pip install onnx onnxruntime` — ONNX export and verification (training machine only)
- `pip install scikit-learn` — CPU fallback classifier
- Create `code/ml/signal_classifier/data/collected/` directory for self-supervised samples
- Create `code/ml/signal_classifier/checkpoints/` directory
- Create `code/ml/signal_classifier/exports/` directory
- Create `code/ml/signal_classifier/reports/` directory
- Document in setup output:
  - pyrtlsdr replaces rtl_fm when signal classifier is active
  - Training requires x86 machine with GPU recommended
  - HEF compilation requires x86 Ubuntu 22 + Hailo DFC v3.31+

**Acceptance criteria:**
- pyrtlsdr installed on Pi
- Training dependencies documented as x86-only
- Required directories created
- Setup script remains idempotent

---

### T119 — Write unit tests for IQ to spectrogram conversion
**File:** `code/tests/unit/test_signal_classifier.py`
**Status:** Not started

Test the signal classification module:

**IQ to spectrogram tests:**
- Known sine wave IQ input produces single spectral peak at correct frequency bin
- FFT window size (256/512) produces expected output dimensions
- Hann windowing applied (verify spectral leakage reduction vs rectangular window)
- Normalization maps min to 0 and max to 255
- Resize to 224x224 preserves spectral features (peak still at correct relative position)

**Classification threshold tests:**
- Classification with confidence > 0.7 emitted
- Classification with confidence < 0.7 suppressed
- Uncertain flag set when top two classes within 10%
- Uncertain flag not set when top class dominates

**CPU fallback tests:**
- Fallback classifier produces valid modulation type from spectral features
- Fallback operates when Hailo model path not configured

**Test fixture:**
- Synthetic IQ data for known modulation types: pure FM tone, AM carrier + modulation, CW on/off keying

**Acceptance criteria:**
- Spectrogram conversion verified against known signals
- Threshold and confidence filtering tested
- CPU fallback produces valid output
- Synthetic fixtures cover at least FM, AM, and CW

---

### T120 — Integration test for end-to-end signal classification pipeline
**File:** `code/tests/integration/test_classifier_pipeline.py`
**Status:** Not started

Integration test for the full classification pipeline:

- Feed synthetic IQ data through iq_capture → signal_classifier → API → Socket.IO event chain
- Verify FM signal classified as FM with confidence > 0.7
- Verify `/api/classifier/status` returns valid state with accuracy tracking
- Verify `signal_classified` Socket.IO events emitted with correct payloads
- Verify self-supervised logging: when classification matches preset expected_modulation, IQ chunk saved to collected directory
- Verify accuracy tracking: correct count increments when classification matches expected_modulation

**Live test (manual, document procedure):**
- Tune to known FM broadcast station, verify classifier labels it FM within 5 seconds
- Enable ADS-B preset on 1090 MHz, verify ADS-B classification fires
- Switch between presets, verify classifier adapts within 1-2 seconds

Mark with `@pytest.mark.integration`.

**Acceptance criteria:**
- Synthetic pipeline test passes end-to-end
- API and Socket.IO outputs verified
- Self-supervised logging verified
- Manual test procedure documented

---

## Dependency Chain
```
T106 (dataset) → T107 (training) → T108 (ONNX export) → T109 (HEF compilation)
T107 → T110 (evaluation)
T111 (IQ capture) → T112 (classifier inference)
T113 (presets) → T112
T112 → T114 (API routes)
T114 → T115 (classifier UI) → T116 (CSS) → T117 (layout integration)
T118 (setup) — independent, can run in parallel
T112 → T119 (classifier tests)
T111 + T112 + T113 + T114 → T120 (integration test)
```

## Success Criteria
- Raw IQ samples converted to spectrograms and classified by modulation type in real time on Hailo-8L NPU
- 10 classifications per second sustained (100ms per chunk)
- Target classes identified: AM, FM, WFM, SSB, P25, DMR, ADS-B, NOAA APT, WEFAX, CW, unknown
- >90% accuracy on RadioML test set at SNR >10 dB
- 70-80% accuracy on real-world signals (documented baseline)
- Self-supervised labeling pipeline collects confirmed training samples passively
- CPU fallback classifier operates when Hailo unavailable
- Classification panel displays real-time spectrogram waterfall and modulation history
- Accuracy tracking compares classifier output against preset expected_modulation
- All unit and mocked integration tests pass
