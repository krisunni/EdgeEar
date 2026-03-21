# Unit tests for IQ capture DSP functions and Tuner-compatible interface

import numpy as np
from unittest.mock import MagicMock, patch
import queue

import pytest

from ravensdr.iq_capture import (
    parse_freq_string,
    fm_demodulate,
    am_demodulate,
    wfm_demodulate,
    apply_deemphasis,
    squelch_gate,
    audio_to_pcm_bytes,
    IQCapture,
    AUDIO_RATE,
)


class TestParseFreqString:
    """Test frequency string parsing."""

    def test_mhz_suffix(self):
        assert parse_freq_string("162.550M") == 162550000

    def test_mhz_lowercase(self):
        assert parse_freq_string("94.900m") == 94900000

    def test_khz_suffix(self):
        assert parse_freq_string("8682.0k") == 8682000

    def test_khz_uppercase(self):
        assert parse_freq_string("4298.0K") == 4298000

    def test_bare_number(self):
        assert parse_freq_string("143050000") == 143050000

    def test_integer_mhz(self):
        assert parse_freq_string("1090M") == 1090000000

    def test_whitespace_stripped(self):
        assert parse_freq_string("  162.550M  ") == 162550000

    def test_adsb_frequency(self):
        assert parse_freq_string("1090M") == 1090000000

    def test_all_presets_parse(self):
        """All preset frequency strings should parse correctly."""
        from ravensdr.presets import get_presets
        for preset in get_presets():
            freq_hz = parse_freq_string(preset["freq"])
            assert freq_hz > 0, f"Failed to parse: {preset['freq']}"


class TestFMDemodulate:
    """Test FM demodulation."""

    def test_pure_tone_produces_audio(self):
        """A modulated FM signal should produce non-silent audio."""
        sr = 240000
        n = 24000  # 100ms
        t = np.arange(n) / sr
        # FM modulated signal: carrier + modulation
        mod = np.sin(2 * np.pi * 1000 * t)
        phase = 2 * np.pi * 50000 * t + 5 * np.cumsum(mod) / sr
        iq = np.exp(1j * phase)

        audio = fm_demodulate(iq, audio_rate=16000, sample_rate=sr)
        assert len(audio) > 0
        assert np.max(np.abs(audio)) > 0.01

    def test_output_length_decimated(self):
        """Output should be decimated from sample_rate to audio_rate."""
        sr = 240000
        n = 24000
        iq = np.exp(2j * np.pi * 50000 * np.arange(n) / sr)

        audio = fm_demodulate(iq, audio_rate=16000, sample_rate=sr)
        expected_len = (n - 1) // (sr // 16000)
        assert abs(len(audio) - expected_len) <= 2

    def test_empty_input(self):
        audio = fm_demodulate(np.array([], dtype=np.complex64))
        assert len(audio) == 0

    def test_single_sample(self):
        audio = fm_demodulate(np.array([1 + 0j]))
        assert len(audio) == 0


class TestAMDemodulate:
    """Test AM demodulation."""

    def test_am_signal_produces_audio(self):
        sr = 240000
        n = 24000
        t = np.arange(n) / sr
        carrier = np.exp(2j * np.pi * 50000 * t)
        mod = 1 + 0.5 * np.sin(2 * np.pi * 1000 * t)
        iq = carrier * mod

        audio = am_demodulate(iq, audio_rate=16000, sample_rate=sr)
        assert len(audio) > 0
        assert np.max(np.abs(audio)) > 0.01

    def test_empty_input(self):
        audio = am_demodulate(np.array([], dtype=np.complex64))
        assert len(audio) == 0


class TestWFMDemodulate:
    """Test wideband FM demodulation."""

    def test_wfm_produces_audio(self):
        sr = 240000
        n = 24000
        t = np.arange(n) / sr
        mod = np.sin(2 * np.pi * 1000 * t)
        phase = 2 * np.pi * 50000 * t + 75000 * np.cumsum(mod) / sr
        iq = np.exp(1j * phase)

        audio = wfm_demodulate(iq, audio_rate=16000, sample_rate=sr)
        assert len(audio) > 0

    def test_same_as_fm(self):
        """WFM uses the same algorithm as FM."""
        sr = 240000
        iq = np.exp(2j * np.pi * 50000 * np.arange(24000) / sr)
        fm_out = fm_demodulate(iq, sample_rate=sr)
        wfm_out = wfm_demodulate(iq, sample_rate=sr)
        np.testing.assert_array_equal(fm_out, wfm_out)


class TestDeemphasis:
    """Test de-emphasis filter."""

    def test_reduces_high_frequency(self):
        """De-emphasis should attenuate high frequencies more than low."""
        sr = 16000
        n = 1600  # 100ms

        # Low frequency tone (500 Hz)
        t = np.arange(n) / sr
        low = np.sin(2 * np.pi * 500 * t)
        low_filtered = apply_deemphasis(low, sample_rate=sr)
        low_rms = np.sqrt(np.mean(low_filtered ** 2))

        # High frequency tone (4000 Hz)
        high = np.sin(2 * np.pi * 4000 * t)
        high_filtered = apply_deemphasis(high, sample_rate=sr)
        high_rms = np.sqrt(np.mean(high_filtered ** 2))

        # High freq should be attenuated more
        assert high_rms < low_rms

    def test_empty_input(self):
        result = apply_deemphasis(np.array([]))
        assert len(result) == 0

    def test_output_same_length(self):
        audio = np.random.randn(1600)
        result = apply_deemphasis(audio)
        assert len(result) == len(audio)


class TestSquelchGate:
    """Test squelch gating."""

    def test_squelch_zero_passes_all(self):
        """Squelch level 0 should pass all audio through."""
        audio = np.random.randn(1600) * 0.5
        result = squelch_gate(audio, 0)
        np.testing.assert_array_equal(result, audio)

    def test_squelch_mutes_silence(self):
        """High squelch should mute very quiet audio."""
        audio = np.random.randn(1600) * 0.0001  # very quiet
        result = squelch_gate(audio, 50)
        assert np.all(result == 0)

    def test_squelch_passes_loud(self):
        """Squelch should pass loud audio through."""
        audio = np.random.randn(1600) * 0.5  # loud
        result = squelch_gate(audio, 10)
        assert np.max(np.abs(result)) > 0

    def test_empty_input(self):
        result = squelch_gate(np.array([]), 50)
        assert len(result) == 0


class TestAudioToPCMBytes:
    """Test float-to-PCM conversion."""

    def test_output_is_bytes(self):
        audio = np.random.randn(1600) * 0.5
        result = audio_to_pcm_bytes(audio)
        assert isinstance(result, bytes)

    def test_output_length(self):
        audio = np.random.randn(1600)
        result = audio_to_pcm_bytes(audio)
        assert len(result) == 1600 * 2  # 16-bit = 2 bytes per sample

    def test_clipping(self):
        """Values outside [-1, 1] should be clipped to int16 range."""
        audio = np.array([10.0, -10.0, 0.0])
        result = audio_to_pcm_bytes(audio)
        pcm = np.frombuffer(result, dtype=np.int16)
        assert pcm[0] == 32767   # clipped at int16 max
        assert pcm[1] == -32768  # clipped at int16 min
        assert pcm[2] == 0


class TestIQCaptureInterface:
    """Test IQCapture Tuner-compatible interface."""

    def test_initial_state(self):
        cap = IQCapture()
        assert cap.squelch == 0
        assert cap.gain == 40
        assert cap.ppm == 0
        assert cap.direct_sampling == 0
        assert cap.deemp is None
        assert cap.is_running is False

    def test_effective_deemp_auto(self):
        cap = IQCapture()
        cap.current_mode = "fm"
        assert cap.effective_deemp is True
        cap.current_mode = "am"
        assert cap.effective_deemp is False
        cap.current_mode = "wbfm"
        assert cap.effective_deemp is True

    def test_effective_deemp_explicit(self):
        cap = IQCapture()
        cap.deemp = False
        cap.current_mode = "fm"
        assert cap.effective_deemp is False
        cap.deemp = True
        cap.current_mode = "am"
        assert cap.effective_deemp is True

    def test_effective_sample_rate_default(self):
        cap = IQCapture()
        cap.current_mode = "fm"
        assert cap.effective_sample_rate == 240000

    def test_poll_not_running(self):
        cap = IQCapture()
        assert cap.poll() is True  # no thread = not crashed

    def test_iq_callback_settable(self):
        cap = IQCapture()
        cb = MagicMock()
        cap.set_iq_callback(cb)
        assert cap._iq_callback is cb

    def test_drain_queues(self):
        q1 = queue.Queue()
        q2 = queue.Queue()
        q1.put(b"data")
        q2.put(b"data")
        cap = IQCapture(pcm_queue=q1, audio_queue=q2)
        cap._drain_queues()
        assert q1.empty()
        assert q2.empty()
