# NPU Model Training Guide — Signal Classifier & SEI

How to train, compile, and deploy the signal classification and specific emitter identification models for Hailo-8L NPU inference.

## Architecture Overview

```
Mac (Apple Silicon)          Pi 5 (Hailo-8L)
─────────────────          ──────────────────
1. Collect IQ data    ←──  Self-supervised labeling (CPU fallback)
2. Train model (PyTorch)    ADS-B IQ collection (ICAO hex labels)
3. Export ONNX
4. Compile HEF        ──→  5. Deploy .hef files
                            6. Set env vars, restart
                            7. Inference on NPU
```

Both Mac (Apple Silicon) and Pi 5 are ARM64 — training on Mac means the model learns ARM-native float behavior with no x86→ARM quantization mismatch.

---

## Prerequisites (Mac)

```bash
# Python environment (use same Python version as Pi if possible)
python3 -m venv ml-venv
source ml-venv/bin/activate

# Training dependencies (NOT needed on Pi)
pip install torch torchvision numpy h5py
pip install onnx onnxruntime
pip install matplotlib   # for evaluation plots

# Hailo DFC — required for HEF compilation
# Download from https://hailo.ai/developer-zone/
# Requires x86 Docker or Rosetta — see "HEF Compilation" section below
```

---

## Phase 16: Signal Classifier (MobileNetV2)

### Step 1 — Collect Training Data

The classifier collects training data automatically via self-supervised labeling while running on CPU fallback. When a classification matches the preset's `expected_modulation`, the raw IQ chunk is saved.

**On the Pi:**
```bash
# Just run ravenSDR — collection happens passively
python3 code/ravensdr/app.py

# Tune to different presets (Weather, Aviation, Broadcast)
# Each confirmed classification saves an IQ sample to:
#   code/ml/signal_classifier/data/collected/<modulation>/<timestamp>.npy
```

**Check collection progress:**
```bash
# Count collected samples per class
for d in code/ml/signal_classifier/data/collected/*/; do
    echo "$(basename $d): $(ls $d/*.npy 2>/dev/null | wc -l) samples"
done
```

Minimum recommended: 500+ samples per class for meaningful training. More is better.

**Optional — RadioML benchmark dataset:**
```bash
# Download RadioML 2018.01A from https://www.deepsig.ai/datasets
# This adds 2.5M simulated IQ samples across 24 modulation classes
# Combined with your real-world collected data for best results
```

### Step 2 — Build Dataset

Copy collected data from Pi to Mac, then build the training dataset:

```bash
# On Mac, from the repo root
cd code/ml/signal_classifier

# Build dataset from collected samples (and optionally RadioML)
python3 dataset.py \
    --custom-dir data/collected \
    --output data/dataset.npz

# With RadioML (if downloaded):
python3 dataset.py \
    --radioml /path/to/GOLD_XYZ_OSC.0001_1024.hdf5 \
    --custom-dir data/collected \
    --output data/dataset.npz
```

This creates `data/dataset.npz` (train/val/test splits) and `data/dataset_classes.json` (class index mapping).

### Step 3 — Train

```bash
python3 train.py \
    --dataset_path data/dataset.npz \
    --epochs 50 \
    --batch_size 64 \
    --lr 1e-3 \
    --output_dir checkpoints

# Output: checkpoints/best_model.pth
# Training uses MobileNetV2 pretrained on ImageNet
# Differential learning rates: 1e-5 pretrained, 1e-3 new classifier head
# Early stopping with patience=10 on validation loss
```

**Apple Silicon note:** PyTorch MPS backend is used automatically if available. Training a MobileNetV2 on ~10K samples takes ~5 minutes on M1/M2.

### Step 4 — Evaluate

```bash
python3 evaluate.py \
    --model checkpoints/best_model.pth \
    --dataset_path data/dataset.npz \
    --output_dir reports

# Output:
#   reports/assessment_report.json — per-class precision/recall/F1
#   reports/confusion_matrix.png  — visual confusion matrix
#
# Target: >90% accuracy at SNR >10 dB (RadioML benchmark)
# Real-world: expect 70-80% due to multipath and interference
```

### Step 5 — Export ONNX

```bash
python3 export_onnx.py \
    --checkpoint checkpoints/best_model.pth \
    --output_dir exports

# Output: exports/signal_classifier.onnx
# Input shape:  (1, 3, 224, 224) float32
# Output shape: (1, 11) float32 (softmax over modulation classes)
# Opset 13 for Hailo DFC compatibility
```

### Step 6 — Compile HEF

HEF compilation requires the Hailo Dataflow Compiler (DFC) v3.31+. The DFC is x86-only — on Mac you need Docker with Rosetta or an x86 VM/machine.

```bash
# Option A: Docker with Rosetta (Mac)
docker run --platform linux/amd64 -v $(pwd):/workspace hailo/dfc:3.31 \
    python3 /workspace/compile_hef.py \
    --onnx_model /workspace/exports/signal_classifier.onnx \
    --calibration_data /workspace/data/dataset.npz \
    --output_dir /workspace/exports

# Option B: x86 Ubuntu 22 machine with DFC installed
python3 compile_hef.py \
    --onnx_model exports/signal_classifier.onnx \
    --calibration_data data/dataset.npz \
    --output_dir exports

# Output: exports/signal_classifier.hef
```

### Step 7 — Deploy to Pi

```bash
# Copy HEF and class mapping to Pi
scp exports/signal_classifier.hef pi@pi5:~/ravenSDR/code/ml/signal_classifier/exports/
scp exports/signal_classifier_classes.json pi@pi5:~/ravenSDR/code/ml/signal_classifier/exports/

# On Pi — set environment variables and restart
export CLASSIFIER_HEF_PATH=/home/kris/ravenSDR/code/ml/signal_classifier/exports/signal_classifier.hef
export CLASSIFIER_CLASSES_PATH=/home/kris/ravenSDR/code/ml/signal_classifier/exports/signal_classifier_classes.json
python3 -m ravensdr.app

# Verify in logs:
#   Signal classifier loaded on Hailo-8L: /home/kris/.../signal_classifier.hef
#   Signal classifier initialized (backend: hailo)
```

---

## Phase 17: SEI Emitter Fingerprinting (1D CNN + Attention)

### Step 1 — Collect ADS-B-Labeled IQ Data

ADS-B transponders provide perfect ground truth for SEI training — each aircraft has a unique ICAO hex code baked into every transmission.

```bash
# On the Pi — run the ADS-B IQ collection script
cd code/ml/sei
python3 collect.py \
    --duration 24h \
    --output_dir data/collected \
    --min_snr 15

# This saves IQ segments organized by ICAO hex:
#   data/collected/A1B2C3/2026-03-17T14_22_01_001.npy
#   data/collected/D4E5F6/2026-03-17T14_22_02_234.npy
#   ...
#
# 24 hours of collection typically yields:
#   30-100 unique aircraft (emitters)
#   1000-5000 total IQ segments
#
# Minimum viable: 10 emitters × 100 segments each
```

**Longer is better.** Run collection for multiple days during peak air traffic hours for maximum emitter diversity.

### Step 2 — Train

Copy collected data from Pi to Mac:

```bash
cd code/ml/sei

python3 train.py \
    --data_dir data/collected \
    --epochs 100 \
    --batch_size 32 \
    --embedding_dim 128 \
    --margin 0.3 \
    --output_dir checkpoints

# Output: checkpoints/sei_model.pth
# Architecture: 1D CNN (4 conv layers) + SE attention → 128-dim embedding
# Training: triplet loss with semi-hard negative mining
# Same-emitter embeddings cluster, different-emitter embeddings push apart
```

**Apple Silicon note:** Triplet loss training is more GPU-intensive than classification. ~30 minutes for 10K samples on M1/M2.

### Step 3 — Evaluate

```bash
python3 evaluate.py \
    --model checkpoints/sei_model.pth \
    --data_dir data/collected \
    --output_dir reports

# Output:
#   reports/sei_assessment_report.json
#   Rank-1 accuracy (correct emitter as top match)
#   Rank-5 accuracy
#   Same vs different emitter similarity distributions
#
# Target: >85% rank-1 accuracy on ADS-B test set
```

### Step 4 — Export ONNX

```bash
python3 export_onnx.py \
    --checkpoint checkpoints/sei_model.pth \
    --output_dir exports

# Output: exports/sei_model.onnx
# Input shape:  (1, 2, 1024) float32 (I/Q channels)
# Output shape: (1, 128) float32 (L2-normalized embedding)
```

### Step 5 — Compile HEF

```bash
# Same DFC requirement as signal classifier
# NOTE: 1D convolutions may need reshaping to 2D for Hailo compatibility
# If compilation fails, reshape input from (1, 2, 1024) to (1, 2, 1, 1024)
# and use Conv2d with kernel_size=(1, 7) — see compile_hef.py comments

docker run --platform linux/amd64 -v $(pwd):/workspace hailo/dfc:3.31 \
    python3 /workspace/compile_hef.py \
    --onnx_model /workspace/exports/sei_model.onnx \
    --calibration_dir /workspace/data/collected \
    --output_dir /workspace/exports

# Output: exports/sei_model.hef
```

### Step 6 — Deploy to Pi

```bash
scp exports/sei_model.hef pi@pi5:~/ravenSDR/code/ml/sei/exports/

# On Pi
export SEI_HEF_PATH=/home/kris/ravenSDR/code/ml/sei/exports/sei_model.hef
python3 -m ravensdr.app

# Verify in logs:
#   SEI model loaded on Hailo-8L: /home/kris/.../sei_model.hef
#   SEI model initialized (backend: hailo, 0 emitters loaded)
```

---

## Environment Variables

| Variable | Purpose | Example |
|----------|---------|---------|
| `CLASSIFIER_HEF_PATH` | Path to signal classifier HEF | `/home/kris/ravenSDR/code/ml/signal_classifier/exports/signal_classifier.hef` |
| `CLASSIFIER_CLASSES_PATH` | Path to class mapping JSON | `/home/kris/ravenSDR/code/ml/signal_classifier/exports/signal_classifier_classes.json` |
| `SEI_HEF_PATH` | Path to SEI embedding model HEF | `/home/kris/ravenSDR/code/ml/sei/exports/sei_model.hef` |

Add to systemd service file for persistent configuration:

```ini
# /etc/systemd/system/ravensdr.service
[Service]
Environment=CLASSIFIER_HEF_PATH=/home/kris/ravenSDR/code/ml/signal_classifier/exports/signal_classifier.hef
Environment=CLASSIFIER_CLASSES_PATH=/home/kris/ravenSDR/code/ml/signal_classifier/exports/signal_classifier_classes.json
Environment=SEI_HEF_PATH=/home/kris/ravenSDR/code/ml/sei/exports/sei_model.hef
```

---

## CPU Fallback Behavior

Both models run on CPU fallback when no HEF file is configured. This is the default out-of-box experience.

| Model | CPU Fallback | Accuracy | Speed |
|-------|-------------|----------|-------|
| Signal Classifier | Spectral heuristics (bandwidth, peak-to-avg ratio) | ~50-60% | Instant |
| SEI | Statistical IQ features (moments, correlation, ZCR) | Low (deterministic but not discriminative) | Instant |

CPU fallback is useful for:
- Running the pipeline before models are trained
- Passive self-supervised data collection
- Development and testing without Hailo hardware

---

## Retraining Cycle

The system improves over time via self-supervised labeling:

```
1. Run with CPU fallback (or existing HEF)
2. Classifier labels IQ chunks when confidence > 0.7
   AND matches preset expected_modulation
3. Confirmed samples saved to ml/signal_classifier/data/collected/
4. Periodically: copy to Mac, retrain, compile new HEF, deploy
5. Each cycle improves real-world accuracy
```

For SEI, the ADS-B bootstrap provides an ongoing stream of ground-truth labeled data — every aircraft transponder is a known emitter identified by ICAO hex code.

---

## Hailo Multi-Model Notes

Running both signal classifier and SEI on the Hailo-8L simultaneously requires multi-context mode. The Hailo-8L has 13 TOPS and can typically run 2-3 small models concurrently.

Current model loading order:
1. Whisper encoder HEF (always loaded first, highest priority)
2. Whisper decoder HEF
3. Signal classifier HEF (if configured)
4. SEI embedding HEF (if configured)

If the Hailo-8L runs out of resources, the signal classifier and SEI fall back to CPU automatically. Whisper always gets NPU priority.

---

## Troubleshooting

**"Signal classifier: no HEF model, using CPU fallback"**
→ `CLASSIFIER_HEF_PATH` not set or file doesn't exist. Check path and file permissions.

**"SEI model: Hailo init failed"**
→ HEF may be compiled for wrong Hailo target (HAILO8 vs HAILO8L). Recompile with `--hw_arch hailo8l`.

**HEF compilation fails on Conv1d layers**
→ Hailo DFC may not support 1D convolutions natively. Reshape to 2D equivalent — see comments in `compile_hef.py`.

**Low classifier accuracy on real signals**
→ RadioML dataset uses simulated channels. Retrain with more collected real-world data. Expected: 70-80% real-world vs 90%+ on benchmark.

**SEI false positives increasing**
→ Emitter database growing too large. Prune emitters with `observation_count < 5` and `last_seen` older than 30 days.

**Whisper and classifier competing for NPU**
→ Whisper has priority. If latency increases, consider running classifier on CPU only (`CLASSIFIER_HEF_PATH` unset) and reserving NPU for Whisper + SEI.
