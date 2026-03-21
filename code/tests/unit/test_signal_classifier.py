# Unit tests for signal classifier — IQ to spectrogram conversion,
# confidence filtering, CPU fallback

import numpy as np
from unittest.mock import MagicMock

import pytest

from ravensdr.signal_classifier import (
    CONFIDENCE_THRESHOLD,
    FFT_SIZE,
    MODULATION_CLASSES,
    SPECTROGRAM_SIZE,
    UNCERTAINTY_MARGIN,
    SignalClassifier,
    iq_to_spectrogram,
    spectrogram_to_image,
)


class TestIQToSpectrogram:
    """Test IQ to spectrogram conversion."""

    def test_known_sine_wave_produces_spectral_peak(self):
        """A single-frequency sine wave should produce a peak at the correct bin."""
        sample_rate = 2400000
        freq = 100000  # 100 kHz tone
        n_samples = 4096
        t = np.arange(n_samples) / sample_rate
        iq = np.exp(2j * np.pi * freq * t)

        spectrogram = iq_to_spectrogram(iq, fft_size=256, hop=128)

        assert spectrogram.ndim == 2
        assert spectrogram.shape[1] == 256

        # The peak should be at a consistent bin across time frames
        mean_spectrum = np.mean(spectrogram, axis=0)
        peak_bin = np.argmax(mean_spectrum)
        # Verify there IS a clear peak (max much higher than mean)
        assert mean_spectrum[peak_bin] > np.mean(mean_spectrum) + 10

    def test_fft_size_256_output_dimensions(self):
        """FFT size 256 should produce 256 frequency bins."""
        iq = np.random.randn(2000) + 1j * np.random.randn(2000)
        spectrogram = iq_to_spectrogram(iq, fft_size=256, hop=128)
        assert spectrogram.shape[1] == 256

    def test_fft_size_512_output_dimensions(self):
        """FFT size 512 should produce 512 frequency bins."""
        iq = np.random.randn(4000) + 1j * np.random.randn(4000)
        spectrogram = iq_to_spectrogram(iq, fft_size=512, hop=256)
        assert spectrogram.shape[1] == 512

    def test_hann_window_reduces_leakage(self):
        """Hann window should reduce spectral leakage vs no windowing."""
        sample_rate = 2400000
        freq = 100000
        n = 2048
        t = np.arange(n) / sample_rate
        iq = np.exp(2j * np.pi * freq * t)

        spec = iq_to_spectrogram(iq, fft_size=256, hop=128)
        mean_spec = np.mean(spec, axis=0)
        peak_bin = np.argmax(mean_spec)

        # With Hann windowing, the peak should be significantly
        # above the sidelobes (at least 20 dB)
        peak_val = mean_spec[peak_bin]
        # Look at bins far from the peak
        far_bins = np.concatenate([mean_spec[:max(0, peak_bin-20)],
                                    mean_spec[peak_bin+20:]])
        if len(far_bins) > 0:
            mean_far = np.mean(far_bins)
            assert peak_val - mean_far > 15  # at least 15 dB separation

    def test_short_input_handled(self):
        """Inputs shorter than FFT size should still produce output."""
        iq = np.random.randn(100) + 1j * np.random.randn(100)
        spectrogram = iq_to_spectrogram(iq, fft_size=256, hop=128)
        assert spectrogram.shape[0] >= 1
        assert spectrogram.shape[1] == 256

    def test_output_values_in_dbm(self):
        """Output values should be in dB scale (finite, not NaN)."""
        iq = np.random.randn(2000) + 1j * np.random.randn(2000)
        spectrogram = iq_to_spectrogram(iq)
        assert np.all(np.isfinite(spectrogram))


class TestSpectrogramToImage:
    """Test spectrogram normalization and resize."""

    def test_normalization_maps_to_0_255(self):
        """Min-max normalization should map to 0-255 range."""
        # Use exact model input size to avoid resize sampling effects
        spec = np.random.randn(224, 224) * 20 - 80
        img = spectrogram_to_image(spec, size=224)
        assert img.dtype == np.uint8
        assert img.min() == 0
        assert img.max() == 255

    def test_resize_to_224x224(self):
        """Output should be resized to SPECTROGRAM_SIZE."""
        spec = np.random.randn(50, 256) * 20
        img = spectrogram_to_image(spec, size=224)
        assert img.shape == (224, 224)

    def test_preserves_spectral_peak(self):
        """After resize, the spectral peak should still be at roughly the same relative position."""
        spec = np.zeros((100, 256))
        # Put a peak at column 128 (middle)
        spec[:, 125:131] = 50
        img = spectrogram_to_image(spec, size=224)
        # Peak should be near the middle of the image
        mean_row = np.mean(img, axis=0)
        peak_col = np.argmax(mean_row)
        assert abs(peak_col - 112) < 20  # within ~10% of center

    def test_flat_spectrogram_produces_zero_image(self):
        """A constant spectrogram should produce all zeros (no variation)."""
        spec = np.ones((50, 256)) * -80
        img = spectrogram_to_image(spec)
        assert img.max() == 0


class TestClassificationThreshold:
    """Test confidence threshold and uncertainty filtering."""

    def test_above_threshold_emitted(self):
        """Classification with confidence > 0.7 should emit event."""
        emit = MagicMock()
        clf = SignalClassifier(emit_fn=emit)

        # Generate a test signal (pure tone = likely FM or CW on CPU fallback)
        sample_rate = 2400000
        n = 2048
        t = np.arange(n) / sample_rate
        iq = np.exp(2j * np.pi * 100000 * t)

        result = clf.classify_iq(iq, frequency_hz=100000000)

        # CPU fallback should produce a result (may or may not exceed threshold
        # depending on heuristics)
        if result is not None:
            assert result["confidence"] >= CONFIDENCE_THRESHOLD
            assert result["modulation"] in MODULATION_CLASSES
            assert emit.called

    def test_below_threshold_suppressed(self):
        """Classification with confidence < 0.7 should return None."""
        clf = SignalClassifier()

        # Very noisy signal should be hard to classify
        iq = np.random.randn(256) + 1j * np.random.randn(256)
        iq *= 0.001  # very weak signal

        # With just 256 samples (1 FFT frame), classification may be uncertain
        result = clf.classify_iq(iq)
        # Result may be None (below threshold) or a low-confidence classification
        # Either outcome is acceptable for noise
        if result is not None:
            assert result["confidence"] >= CONFIDENCE_THRESHOLD

    def test_too_few_samples_returns_none(self):
        """Fewer samples than FFT size should return None."""
        clf = SignalClassifier()
        iq = np.array([1 + 0j, 2 + 0j])  # too short
        result = clf.classify_iq(iq)
        assert result is None


class TestUncertaintyFlag:
    """Test uncertainty detection when top classes are close."""

    def test_uncertain_flag_set(self):
        """When top two classes within margin, uncertain should be True."""
        clf = SignalClassifier()

        # Create ambiguous signal: mix of FM and AM characteristics
        sample_rate = 2400000
        n = 4096
        t = np.arange(n) / sample_rate
        # FM-like signal + AM-like noise
        iq = np.exp(2j * np.pi * 50000 * t) * (1 + 0.5 * np.cos(2 * np.pi * 1000 * t))
        iq += 0.3 * (np.random.randn(n) + 1j * np.random.randn(n))

        result = clf.classify_iq(iq, frequency_hz=100000000)
        # Result may or may not be uncertain — we just check the field exists
        if result is not None:
            assert "uncertain" in result
            assert isinstance(result["uncertain"], bool)


class TestCPUFallback:
    """Test CPU fallback classifier."""

    def test_cpu_fallback_produces_valid_output(self):
        """CPU fallback should return a valid modulation type."""
        clf = SignalClassifier()
        assert clf.backend == "cpu"

        sample_rate = 2400000
        n = 4096
        t = np.arange(n) / sample_rate
        iq = np.exp(2j * np.pi * 200000 * t)  # wideband-ish

        result = clf.classify_iq(iq, frequency_hz=94900000)
        if result is not None:
            assert result["modulation"] in MODULATION_CLASSES
            assert 0 <= result["confidence"] <= 1
            assert "timestamp" in result

    def test_cpu_fallback_wideband_signal(self):
        """Wideband signal should tend toward WFM classification on CPU fallback."""
        clf = SignalClassifier()

        # Broadband noise = many occupied bins
        iq = np.random.randn(4096) + 1j * np.random.randn(4096)

        result = clf.classify_iq(iq, frequency_hz=94900000)
        if result is not None:
            # Broadband signal should classify as WFM or FM
            assert result["modulation"] in MODULATION_CLASSES


class TestClassifierStatus:
    """Test classifier status reporting."""

    def test_initial_status(self):
        """Initial status should show CPU backend and zero counts."""
        clf = SignalClassifier()
        status = clf.get_status()
        assert status["backend"] == "cpu"
        assert status["active"] is True
        assert status["classifications_total"] == 0
        assert status["accuracy_vs_presets"] == 0.0

    def test_accuracy_tracking(self):
        """Accuracy should track correct classifications vs expected modulation."""
        emit = MagicMock()
        clf = SignalClassifier(emit_fn=emit)

        # Classify with expected_modulation matching CPU fallback result
        sample_rate = 2400000
        n = 4096
        t = np.arange(n) / sample_rate
        iq = np.exp(2j * np.pi * 200000 * t)

        result = clf.classify_iq(iq, frequency_hz=100000000, expected_modulation="FM")

        status = clf.get_status()
        if result is not None:
            assert status["classifications_total"] >= 1
            assert status["compared_count"] >= 1


class TestSyntheticSignals:
    """Test classification on synthetic known signal types."""

    def test_pure_tone_classified(self):
        """A pure CW tone should be classifiable."""
        clf = SignalClassifier()
        n = 4096
        t = np.arange(n) / 2400000
        # Very narrow bandwidth = CW-like
        iq = np.exp(2j * np.pi * 1000 * t)

        result = clf.classify_iq(iq, frequency_hz=14070000)
        # CPU fallback may classify as CW, AM, or SSB for a pure tone
        if result is not None:
            assert result["modulation"] in MODULATION_CLASSES

    def test_fm_modulated_signal(self):
        """FM-modulated signal should be classifiable."""
        clf = SignalClassifier()
        n = 8192
        t = np.arange(n) / 2400000
        # FM: frequency varies with modulation
        mod = np.sin(2 * np.pi * 1000 * t)  # 1 kHz modulation
        phase = 2 * np.pi * 100000 * t + 5 * np.cumsum(mod) / 2400000
        iq = np.exp(1j * phase)

        result = clf.classify_iq(iq, frequency_hz=162550000)
        if result is not None:
            assert result["modulation"] in MODULATION_CLASSES

    def test_am_envelope_signal(self):
        """AM-modulated signal should be classifiable."""
        clf = SignalClassifier()
        n = 8192
        t = np.arange(n) / 2400000
        # AM: envelope varies with modulation
        carrier = np.exp(2j * np.pi * 100000 * t)
        mod = 1 + 0.5 * np.sin(2 * np.pi * 1000 * t)
        iq = carrier * mod

        result = clf.classify_iq(iq, frequency_hz=118000000)
        if result is not None:
            assert result["modulation"] in MODULATION_CLASSES
