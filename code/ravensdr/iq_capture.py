# Direct IQ capture via pyrtlsdr — replaces rtl_fm for main audio pipeline
#
# Provides raw IQ samples for signal classification and demodulated audio
# for the existing transcription pipeline. Includes FM/AM/WFM demodulation,
# squelch, de-emphasis, and all Tuner-compatible controls.
# Device mutex prevents concurrent access with rtl_fm.

import logging
import math
import re

import numpy as np

# Use REAL stdlib modules, not eventlet's green versions.
try:
    from eventlet.patcher import original
    threading = original("threading")
except ImportError:
    import threading

log = logging.getLogger(__name__)

# Default capture parameters
DEFAULT_SAMPLE_RATE = 240000    # 240 kHz (close to rtl_fm's 200k, lower CPU than 2.4 MHz)
DEFAULT_GAIN = 40
AUDIO_RATE = 16000              # output sample rate (Whisper expects 16kHz)
CHUNK_DURATION_MS = 100         # 100ms per chunk
IQ_CHUNK_SIZE = DEFAULT_SAMPLE_RATE * CHUNK_DURATION_MS // 1000  # 24K samples

# Mode-specific sample rates (match tuner.py MODE_SAMPLE_RATES)
MODE_SAMPLE_RATES = {
    "am": 240000,
    "fm": 240000,
    "wbfm": 240000,
}


# ── DSP Functions ──

def parse_freq_string(freq_str):
    """Convert frequency string to Hz integer.

    Supports formats: "162.550M", "8682.0k", "143050000", "1090M"

    Args:
        freq_str: frequency string with optional M/k suffix

    Returns:
        frequency in Hz as integer
    """
    freq_str = freq_str.strip()
    m = re.match(r'^([0-9.]+)\s*([MmKk]?)$', freq_str)
    if not m:
        return int(float(freq_str))

    value = float(m.group(1))
    suffix = m.group(2).upper()
    if suffix == 'M':
        return round(value * 1e6)
    elif suffix == 'K':
        return round(value * 1e3)
    else:
        return round(value)


def fm_demodulate(iq_samples, audio_rate=AUDIO_RATE, sample_rate=DEFAULT_SAMPLE_RATE):
    """Demodulate FM from complex IQ samples.

    Uses frequency discriminator: instantaneous frequency = d(phase)/dt.
    Works for both narrowband FM and wideband FM (same algorithm,
    bandwidth determined by capture sample rate).
    """
    if len(iq_samples) < 2:
        return np.array([], dtype=np.float64)

    # Frequency discriminator via conjugate product (avoids phase unwrap issues)
    product = iq_samples[1:] * np.conj(iq_samples[:-1])
    audio = np.angle(product)

    # Normalize to [-1, 1]
    audio = audio / np.pi

    # Decimate to audio_rate
    decimation = sample_rate // audio_rate
    if decimation > 1:
        n = len(audio) // decimation * decimation
        audio = audio[:n].reshape(-1, decimation).mean(axis=1)

    return audio


def am_demodulate(iq_samples, audio_rate=AUDIO_RATE, sample_rate=DEFAULT_SAMPLE_RATE):
    """Demodulate AM from complex IQ samples using envelope detection."""
    if len(iq_samples) < 2:
        return np.array([], dtype=np.float64)

    # Envelope detection (magnitude of complex signal)
    envelope = np.abs(iq_samples).astype(np.float64)

    # Remove DC component
    envelope = envelope - np.mean(envelope)

    # Normalize
    peak = np.max(np.abs(envelope))
    if peak > 0:
        envelope = envelope / peak

    # Decimate to audio_rate
    decimation = sample_rate // audio_rate
    if decimation > 1:
        n = len(envelope) // decimation * decimation
        envelope = envelope[:n].reshape(-1, decimation).mean(axis=1)

    return envelope


def wfm_demodulate(iq_samples, audio_rate=AUDIO_RATE, sample_rate=DEFAULT_SAMPLE_RATE):
    """Demodulate wideband FM. Same as FM — bandwidth is in the capture rate."""
    return fm_demodulate(iq_samples, audio_rate=audio_rate, sample_rate=sample_rate)


def apply_deemphasis(audio, sample_rate=AUDIO_RATE, tau=75e-6):
    """Apply de-emphasis filter (single-pole IIR low-pass).

    Standard FM de-emphasis: 75μs time constant (US/Japan) or 50μs (Europe).
    Reduces high-frequency hiss on FM signals.

    Args:
        audio: float64 audio array (normalized to [-1, 1])
        sample_rate: audio sample rate
        tau: time constant in seconds (default 75μs for US FM)

    Returns:
        filtered float64 audio array
    """
    if len(audio) == 0:
        return audio

    # alpha = exp(-1 / (sample_rate * tau))
    # At 16kHz, 75μs: alpha ≈ 0.9174
    alpha = math.exp(-1.0 / (sample_rate * tau))

    # IIR filter: y[n] = (1-alpha)*x[n] + alpha*y[n-1]
    out = np.empty_like(audio)
    out[0] = (1.0 - alpha) * audio[0]
    for i in range(1, len(audio)):
        out[i] = (1.0 - alpha) * audio[i] + alpha * out[i - 1]

    return out


def squelch_gate(audio, squelch_level):
    """Apply squelch gate — zero out audio when signal is below threshold.

    Args:
        audio: float64 audio array
        squelch_level: 0-100 (0 = squelch off, higher = more muting)

    Returns:
        gated audio array (zeros if below threshold)
    """
    if squelch_level <= 0:
        return audio

    if len(audio) == 0:
        return audio

    rms = np.sqrt(np.mean(audio ** 2))
    # Map squelch 0-100 to RMS threshold 0-0.3
    # squelch=20 (typical NOAA) → threshold ~0.06
    threshold = squelch_level * 0.003
    if rms < threshold:
        return np.zeros_like(audio)
    return audio


def audio_to_pcm_bytes(audio_float):
    """Convert float64 audio [-1, 1] to 16-bit signed PCM bytes.

    Args:
        audio_float: numpy float64 array normalized to [-1, 1]

    Returns:
        bytes of int16 PCM
    """
    pcm = np.clip(audio_float * 32767, -32768, 32767).astype(np.int16)
    return pcm.tobytes()


# ── IQ Capture Class ──

class IQCapture:
    """Direct IQ capture from RTL-SDR via pyrtlsdr.

    Full Tuner-compatible interface: tune(), stop(), set_squelch(), etc.
    Provides raw IQ for signal classification and demodulated audio
    for the transcription pipeline.
    """

    # Shared device mutex — prevents pyrtlsdr and rtl_fm from colliding
    device_lock = threading.Lock()

    def __init__(self, pcm_queue=None, audio_queue=None, device_index=0,
                 sample_rate=None, gain=DEFAULT_GAIN):
        self.pcm_queue = pcm_queue
        self.audio_queue = audio_queue
        self.device_index = device_index
        self._capture_sample_rate = sample_rate  # None = auto from mode
        self.gain = gain

        # Tuner-compatible state
        self.current_freq = None     # original string (e.g., "162.550M")
        self.current_mode = "fm"
        self.center_freq = 0         # Hz integer
        self.squelch = 0
        self.sample_rate = None      # None = auto (MODE_SAMPLE_RATES)
        self.deemp = None            # None = auto, True/False = explicit
        self.ppm = 0
        self.direct_sampling = 0

        self._sdr = None
        self._running = False
        self._thread = None
        self._iq_callback = None
        self._stop_event = threading.Event()

    @property
    def is_running(self):
        return self._running

    @property
    def effective_sample_rate(self):
        """Actual capture sample rate: explicit setting or auto from mode."""
        if self._capture_sample_rate:
            return self._capture_sample_rate
        if self.sample_rate:
            # Parse string like "200k" to int
            sr = self.sample_rate
            if isinstance(sr, str):
                sr = sr.lower().replace('k', '000').replace('m', '000000')
                return int(sr)
            return int(sr)
        return MODE_SAMPLE_RATES.get(self.current_mode, DEFAULT_SAMPLE_RATE)

    @property
    def effective_deemp(self):
        """Whether de-emphasis is active: auto = ON for fm/wbfm."""
        if self.deemp is not None:
            return self.deemp
        return self.current_mode in ("fm", "wbfm")

    def set_iq_callback(self, callback):
        """Set callback for raw IQ chunks: callback(iq_samples, frequency_hz)."""
        self._iq_callback = callback

    def tune(self, freq, mode="fm"):
        """Tune to a frequency (Tuner-compatible interface).

        Args:
            freq: frequency string like "162.550M" or Hz integer
            mode: demodulation mode ("fm", "am", "wbfm")
        """
        self.stop()
        self.current_freq = freq
        self.current_mode = mode

        if isinstance(freq, str):
            freq_hz = parse_freq_string(freq)
        else:
            freq_hz = int(freq)

        self.center_freq = freq_hz
        self._stop_event.clear()
        return self.start(freq_hz, mode)

    def start(self, frequency_hz, mode="fm"):
        """Start IQ capture on the given frequency."""
        if self._running:
            self.stop()

        self.center_freq = frequency_hz
        self.current_mode = mode
        self._stop_event.clear()

        if not self.device_lock.acquire(timeout=5):
            log.error("IQ capture: could not acquire device lock (device busy)")
            return False

        try:
            self._sdr = self._open_device()
            if self._sdr is None:
                self.device_lock.release()
                return False
        except Exception as e:
            log.error("IQ capture: failed to open device: %s", e)
            self.device_lock.release()
            return False

        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

        sr = self.effective_sample_rate
        log.info("IQ capture started: %.3f MHz, %s mode, %d kHz sample rate",
                 frequency_hz / 1e6, mode, sr // 1000)
        return True

    def stop(self):
        """Stop IQ capture and release device."""
        self._stop_event.set()
        self._running = False

        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

        if self._sdr is not None:
            try:
                self._sdr.cancel_read_async()
            except Exception:
                pass
            try:
                self._sdr.close()
            except Exception:
                pass
            self._sdr = None
            # Allow USB device to fully release before another process opens it
            import time
            time.sleep(0.5)

        try:
            self.device_lock.release()
        except RuntimeError:
            pass  # lock not held

        self._drain_queues()
        log.info("IQ capture stopped")

    def poll(self):
        """Check if capture thread is still alive (Tuner-compatible)."""
        if self._thread and not self._thread.is_alive():
            self._running = False
            return False
        return True

    def set_squelch(self, level):
        # Squelch is applied in DSP, no need to restart capture
        self.squelch = max(0, min(100, level))

    def set_gain(self, value):
        if value == self.gain:
            return
        self.gain = value
        if self._running:
            self.tune(self.current_freq, self.current_mode)

    def set_sample_rate(self, value):
        if value == self.sample_rate:
            return
        self.sample_rate = value
        if self._running:
            self.tune(self.current_freq, self.current_mode)

    def set_deemp(self, value):
        # De-emphasis is applied in DSP, no need to restart capture
        self.deemp = value

    def set_ppm(self, value):
        value = int(value)
        if value == self.ppm:
            return
        self.ppm = value
        if self._running:
            self.tune(self.current_freq, self.current_mode)

    def set_direct_sampling(self, value):
        value = int(value)
        if value == self.direct_sampling:
            return
        self.direct_sampling = value
        if self._running:
            self.tune(self.current_freq, self.current_mode)

    def _open_device(self):
        """Open RTL-SDR device via pyrtlsdr."""
        try:
            from rtlsdr import RtlSdr
        except (ImportError, AttributeError, OSError) as e:
            log.error("pyrtlsdr not usable — IQ capture unavailable: %s", e)
            return None

        sdr = RtlSdr(device_index=self.device_index)
        sdr.sample_rate = self.effective_sample_rate
        sdr.center_freq = self.center_freq
        if self.gain == "auto":
            sdr.gain = "auto"
        else:
            sdr.gain = self.gain

        # Apply PPM correction
        if self.ppm != 0:
            sdr.freq_correction = self.ppm

        # Apply direct sampling mode
        if self.direct_sampling != 0:
            try:
                sdr.set_direct_sampling(self.direct_sampling)
            except Exception as e:
                log.warning("Direct sampling mode %d not supported: %s",
                            self.direct_sampling, e)

        return sdr

    def _capture_loop(self):
        """Read IQ samples in a loop, demodulate, and dispatch."""
        sr = self.effective_sample_rate
        target_chunk = sr * CHUNK_DURATION_MS // 1000

        # Read in smaller USB-friendly blocks (must be multiple of 512 for librtlsdr)
        # then accumulate to target chunk size for demodulation
        read_size = 4096  # 4096 complex samples per USB read (~8KB, safe for libusb)
        accumulator = np.array([], dtype=np.complex128)

        reads = 0
        while not self._stop_event.is_set():
            try:
                samples = self._sdr.read_samples(read_size)
                reads += 1
            except Exception as e:
                if not self._stop_event.is_set():
                    log.warning("IQ capture read error after %d reads: %s", reads, e)
                break

            accumulator = np.concatenate([accumulator, samples])

            # Process when we have enough for a full chunk
            if len(accumulator) < target_chunk:
                continue

            iq_samples = accumulator[:target_chunk]
            accumulator = accumulator[target_chunk:]

            # Dispatch raw IQ to classifier callback
            if self._iq_callback:
                try:
                    self._iq_callback(iq_samples, self.center_freq)
                except Exception as e:
                    log.debug("IQ callback error: %s", e)

            # Demodulate to audio for transcription pipeline
            if self.pcm_queue is not None or self.audio_queue is not None:
                audio = self._demodulate(iq_samples, sr)

                # Apply de-emphasis
                if self.effective_deemp:
                    audio = apply_deemphasis(audio, sample_rate=AUDIO_RATE)

                # Apply squelch
                audio = squelch_gate(audio, self.squelch)

                # Convert to PCM bytes and push to queues
                pcm_bytes = audio_to_pcm_bytes(audio)

                if self.pcm_queue is not None:
                    try:
                        self.pcm_queue.put(pcm_bytes, timeout=0.5)
                    except Exception:
                        pass

                if self.audio_queue is not None:
                    try:
                        self.audio_queue.put_nowait(pcm_bytes)
                    except Exception:
                        pass

        self._running = False

    def _demodulate(self, iq_samples, sample_rate):
        """Demodulate IQ to float64 audio based on current mode."""
        if self.current_mode == "am":
            return am_demodulate(iq_samples, audio_rate=AUDIO_RATE,
                                  sample_rate=sample_rate)
        elif self.current_mode == "wbfm":
            return wfm_demodulate(iq_samples, audio_rate=AUDIO_RATE,
                                   sample_rate=sample_rate)
        else:
            # fm and anything else
            return fm_demodulate(iq_samples, audio_rate=AUDIO_RATE,
                                  sample_rate=sample_rate)

    def _drain_queues(self):
        """Drain both queues on stop."""
        for q in (self.pcm_queue, self.audio_queue):
            if q is None:
                continue
            while not q.empty():
                try:
                    q.get_nowait()
                except Exception:
                    break
