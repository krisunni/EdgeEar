# Hailo NPU venv Debug Report & Fix Plan

## Status: COMPLETE (2026-02-25)

---

## 1. Debug Summary

### The Problem
Hailo-8L NPU inference fails with:
```
CHECK failed - Input buffer size 0 is different than expected 320000
  for input 'tiny-whisper-encoder-10s/input_layer1'
```

### Critical Discovery
- **System Python3** (`python3 /tmp/test_ref.py`) → **SUCCESS**
- **Venv Python3** (`/home/kris/ravenSDR/.venv/bin/python3 /tmp/test_ref.py`) → **FAILS** with buffer size 0

Even after symlinking the venv's `hailo_platform` to the system copy, the venv still fails. The `.so` files and `pyhailort.py` are byte-identical.

### Root Cause Analysis

Two independent issues found:

#### Issue A: Venv environment corruption
The venv at `/home/kris/ravenSDR/.venv` has:
- `include-system-site-packages = false` — hailo_platform was installed separately
- `pip list` shows `hailort None` (broken metadata)
- `.pth` files auto-load `_distutils_hack` and `__editable___ravensdr_0_1_0_finder` at startup
- Something in this venv's environment interferes with Hailo's C++ bindings

**Actual root cause (discovered during implementation):** The venv installed numpy 2.4.2, while the system has numpy 1.24.2. Hailo's C++ bindings (`pyhailort`) were compiled against the numpy 1.x C ABI. The numpy 2.x ndarray struct layout changed, causing `set_buffer()` to read buffer size as 0 from the wrong struct offset.

**Fix:** Pin `numpy<2` in the venv. The `--system-site-packages` venv alone was NOT sufficient — the venv's own numpy 2.x shadowed the system numpy 1.x.

#### Issue B: ravenSDR transcriber uses wrong Hailo SDK patterns
Comparing ravenSDR's `transcriber.py` with the working reference (`whisper-hailo-8l-fastapi`):

| Pattern | ravenSDR (broken) | Reference (works) |
|---------|-------------------|---------------------|
| VDevice lifecycle | Created at `__init__`, held forever | Created inside inference loop with `with` |
| `configure()` | Called without context manager | Used with `with` context manager |
| Bindings | Created fresh each inference call | Created once, reused across iterations |
| VDevice scope | App lifetime | Inference thread lifetime |

The reference creates VDevice and configure() inside a dedicated `_inference_loop` thread, using context managers for proper resource lifecycle. ravenSDR creates them at init time and holds them indefinitely.

---

## 2. Fix Plan

### Phase 1: Fix the venv (5 min)

**File:** Pi5 shell commands (no code changes)

1. Recreate venv with system site-packages:
   ```bash
   cd /home/kris/ravenSDR
   mv .venv .venv.broken
   python3 -m venv --system-site-packages .venv
   .venv/bin/pip install -e .
   .venv/bin/pip install flask flask-socketio numpy eventlet torch transformers
   ```

2. Verify hailo_platform works in new venv:
   ```bash
   .venv/bin/python3 /tmp/test_ref.py
   ```

3. If test passes, remove old venv:
   ```bash
   rm -rf .venv.broken
   ```

### Phase 2: Rewrite transcriber to match working Hailo patterns (main fix)

**File:** `code/ravensdr/transcriber.py`

Refactor `_init_hailo()` and `_transcribe_hailo()` to match the reference project's proven pattern:

1. **Move VDevice + configure into `_inference_loop`** — don't hold device handles at init time
2. **Use context managers** for VDevice and configure()
3. **Create bindings once** after configure, reuse them in the loop
4. **Use a Queue** to pass mel data into the inference thread (already exists: `pcm_queue`)

#### Detailed changes to `transcriber.py`:

**Remove from `__init__`:**
- Remove all `self._hailo_*` instance variables for VDevice, configured models, bindings
- Keep: model paths, decoder assets, tokenizer (these are pure data, no device handles)

**Rewrite `_init_hailo()`:**
- Only load decoder assets (npy files, tokenizer) and store model paths
- Do NOT create VDevice or configure models here
- Validate model files exist

**Rewrite `_inference_loop()`:**
- Create VDevice with context manager at loop start
- Create infer models, set format types
- Configure with context managers
- Create bindings once
- Run the while loop inside the innermost `with` block
- On each iteration: accumulate PCM, compute mel, set buffers, run inference
- Reuse the same bindings object each iteration (just call `set_buffer` again)

**Remove `_cleanup_hailo()`:**
- Context managers handle cleanup automatically

**Remove `_transcribe_hailo()` as separate method:**
- Inline the encoder→decoder pipeline into `_inference_loop` since it must run inside the `with` blocks

#### New `_inference_loop` structure:
```python
def _inference_loop(self):
    if self._backend == "hailo":
        self._inference_loop_hailo()
    elif self._backend == "cpu":
        self._inference_loop_cpu()

def _inference_loop_hailo(self):
    params = VDevice.create_params()
    params.scheduling_algorithm = HailoSchedulingAlgorithm.ROUND_ROBIN

    decoder_hef = HEF(self._decoder_path)
    sorted_output_names = decoder_hef.get_sorted_output_names()
    decoder_model_name = decoder_hef.get_network_group_names()[0]

    with VDevice(params) as vdevice:
        encoder_model = vdevice.create_infer_model(self._encoder_path)
        decoder_model = vdevice.create_infer_model(self._decoder_path)

        # Set format types
        encoder_model.input().set_format_type(FormatType.FLOAT32)
        encoder_model.output().set_format_type(FormatType.FLOAT32)
        decoder_model.input(f"{decoder_model_name}/input_layer1").set_format_type(FormatType.FLOAT32)
        decoder_model.input(f"{decoder_model_name}/input_layer2").set_format_type(FormatType.FLOAT32)
        for name in sorted_output_names:
            decoder_model.output(name).set_format_type(FormatType.FLOAT32)

        with encoder_model.configure() as encoder_configured:
            with decoder_model.configure() as decoder_configured:
                encoder_bindings = encoder_configured.create_bindings()
                decoder_bindings = decoder_configured.create_bindings()

                buffer = b""
                chunk_bytes = CHUNK_SAMPLES * 2

                while not self._stop_event.is_set():
                    # ... accumulate PCM from queue ...
                    # ... silence detection + signal level emit ...
                    # ... compute mel spectrogram ...
                    # ... encoder: set_buffer, run, get_buffer ...
                    # ... decoder loop: reuse decoder_bindings ...
                    # ... emit transcript ...
```

### Phase 3: Update `_cleanup_hailo` and `stop()`

- Remove `_cleanup_hailo()` entirely (context managers handle it)
- `stop()` just sets `_stop_event` — the context managers exit when the loop ends
- Add a `self._thread.join(timeout=5)` in `stop()` to wait for clean shutdown

### Phase 4: Keep CPU fallback path unchanged

The `_transcribe_cpu` method and faster-whisper path remain as-is. Only the Hailo path changes.

---

## 3. Files to Modify

| File | Change |
|------|--------|
| `code/ravensdr/transcriber.py` | Major refactor: move Hailo device lifecycle into inference loop with context managers |

## 4. Files for Reference (read-only)

| File | Purpose |
|------|---------|
| `whisper-hailo-8l-fastapi/app/application/pipelines/hailo_whisper_pipeline.py` | Working reference pattern (on Pi5) |

---

## 5. Verification

1. **Recreate venv** on Pi5 with `--system-site-packages`
2. **Run test_ref.py** in new venv — should pass
3. **Deploy updated transcriber.py** to Pi5
4. **Start ravenSDR app:** `python3 code/ravensdr/app.py`
5. **Tune to a frequency** and verify:
   - No "buffer size 0" error in logs
   - Signal level events emitted via Socket.IO
   - Transcription text appears after 10s of audio
6. **Stop and restart** to verify clean shutdown (no device handle leaks)
