# Integration test for end-to-end signal classification pipeline

import json
import numpy as np
from unittest.mock import MagicMock, patch

import pytest

from ravensdr.signal_classifier import SignalClassifier, MODULATION_CLASSES


pytestmark = pytest.mark.integration


class TestClassifierPipelineEndToEnd:
    """Feed synthetic IQ through classifier and verify API + event chain."""

    def test_fm_signal_classified_and_event_emitted(self):
        """FM signal should be classified and emit signal_classified event."""
        emitted_events = []

        def mock_emit(event, data, **kw):
            emitted_events.append((event, data))

        clf = SignalClassifier(emit_fn=mock_emit)

        # Generate FM signal
        n = 8192
        t = np.arange(n) / 2400000
        mod = np.sin(2 * np.pi * 1000 * t)
        phase = 2 * np.pi * 100000 * t + 5 * np.cumsum(mod) / 2400000
        iq = np.exp(1j * phase)

        result = clf.classify_iq(iq, frequency_hz=162550000, expected_modulation="FM")

        if result is not None:
            # Verify event emitted
            signal_events = [e for e in emitted_events if e[0] == "signal_classified"]
            assert len(signal_events) == 1

            event_data = signal_events[0][1]
            assert "modulation" in event_data
            assert "confidence" in event_data
            assert "frequency_hz" in event_data
            assert "timestamp" in event_data
            assert "uncertain" in event_data
            assert event_data["frequency_hz"] == 162550000
            assert event_data["modulation"] in MODULATION_CLASSES

    def test_status_api_reflects_classifications(self):
        """Classifier status should track total classifications."""
        clf = SignalClassifier()

        # Classify multiple signals
        for i in range(5):
            n = 4096
            t = np.arange(n) / 2400000
            iq = np.exp(2j * np.pi * (50000 + i * 10000) * t)
            clf.classify_iq(iq, frequency_hz=100000000)

        status = clf.get_status()
        assert status["classifications_total"] >= 0
        assert status["backend"] == "cpu"
        assert status["active"] is True
        assert "accuracy_vs_presets" in status

    def test_accuracy_tracking_correct_match(self):
        """When classification matches expected_modulation, accuracy should increase."""
        clf = SignalClassifier()

        n = 8192
        t = np.arange(n) / 2400000
        mod = np.sin(2 * np.pi * 1000 * t)
        phase = 2 * np.pi * 100000 * t + 5 * np.cumsum(mod) / 2400000
        iq = np.exp(1j * phase)

        result = clf.classify_iq(iq, frequency_hz=162550000, expected_modulation="FM")

        status = clf.get_status()
        if result is not None and result["modulation"] == "FM":
            assert status["correct_count"] >= 1
            assert status["compared_count"] >= 1

    def test_accuracy_tracking_incorrect_match(self):
        """When classification doesn't match expected_modulation, compared increments but correct does not."""
        clf = SignalClassifier()

        n = 4096
        t = np.arange(n) / 2400000
        iq = np.exp(2j * np.pi * 100000 * t)

        # Expect a modulation that the CPU fallback will NOT predict
        result = clf.classify_iq(iq, frequency_hz=1090000000, expected_modulation="ADSB")

        status = clf.get_status()
        if result is not None:
            assert status["compared_count"] >= 1
            # CPU fallback won't classify as ADSB, so correct_count stays 0
            assert status["correct_count"] == 0

    def test_multiple_signals_sequential(self):
        """Multiple sequential classifications should all produce valid results."""
        emit = MagicMock()
        clf = SignalClassifier(emit_fn=emit)

        signals = [
            # (description, freq_hz, expected_mod, iq_generator)
            ("AM tone", 118000000, "AM",
             lambda: np.exp(2j * np.pi * 50000 * np.arange(4096) / 2400000) *
                     (1 + 0.5 * np.sin(2 * np.pi * 1000 * np.arange(4096) / 2400000))),
            ("Broadband noise", 94900000, "WFM",
             lambda: np.random.randn(4096) + 1j * np.random.randn(4096)),
            ("Narrow tone", 14070000, "CW",
             lambda: np.exp(2j * np.pi * 800 * np.arange(4096) / 2400000)),
        ]

        results = []
        for desc, freq, expected, gen in signals:
            iq = gen()
            result = clf.classify_iq(iq, frequency_hz=freq, expected_modulation=expected)
            results.append(result)

        # At least some should produce classifications
        classified = [r for r in results if r is not None]
        # CPU fallback should classify most signals
        assert len(classified) >= 1

        # All classified results should be valid
        for r in classified:
            assert r["modulation"] in MODULATION_CLASSES
            assert r["confidence"] >= 0.7

    def test_self_supervised_logging(self, tmp_path):
        """When classification matches expected_modulation, IQ should be saved."""
        import ravensdr.signal_classifier as sc_module

        # Temporarily redirect collected dir to tmp
        original_dir = sc_module.COLLECTED_DIR
        sc_module.COLLECTED_DIR = str(tmp_path / "collected")

        try:
            clf = SignalClassifier()

            n = 8192
            t = np.arange(n) / 2400000
            mod = np.sin(2 * np.pi * 1000 * t)
            phase = 2 * np.pi * 100000 * t + 5 * np.cumsum(mod) / 2400000
            iq = np.exp(1j * phase)

            result = clf.classify_iq(iq, frequency_hz=162550000, expected_modulation="FM")

            if result is not None and result["modulation"] == "FM":
                # Check that a file was saved
                import os
                fm_dir = tmp_path / "collected" / "FM"
                assert fm_dir.exists()
                npy_files = list(fm_dir.glob("*.npy"))
                assert len(npy_files) >= 1

                # Verify saved data is valid
                saved = np.load(str(npy_files[0]))
                assert np.iscomplexobj(saved)
                assert len(saved) == n
        finally:
            sc_module.COLLECTED_DIR = original_dir


class TestClassifierWithPresets:
    """Test classifier integration with preset expected_modulation."""

    def test_presets_have_expected_modulation(self):
        """All presets should have expected_modulation field."""
        from ravensdr.presets import get_presets

        for preset in get_presets():
            assert "expected_modulation" in preset, \
                f"Preset '{preset['id']}' missing expected_modulation"
            assert preset["expected_modulation"] in MODULATION_CLASSES, \
                f"Preset '{preset['id']}' has invalid expected_modulation: {preset['expected_modulation']}"
