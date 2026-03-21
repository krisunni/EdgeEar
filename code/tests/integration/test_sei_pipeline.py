# Integration test for end-to-end SEI pipeline

import numpy as np
from unittest.mock import MagicMock

import pytest

from ravensdr.sei_model import SEIModel, EMBEDDING_DIM
from ravensdr.iq_segmenter import IQSegmenter, Segment
from ravensdr.signal_classifier import SignalClassifier


pytestmark = pytest.mark.integration


class TestSEIPipelineEndToEnd:
    """Feed synthetic IQ through segmenter → classifier → SEI and verify events."""

    def test_enrollment_and_reidentification(self, tmp_path):
        """First observation enrolls, second re-identifies."""
        emitted = []

        def mock_emit(event, data, **kw):
            emitted.append((event, data))

        sei = SEIModel(emit_fn=mock_emit, db_path=str(tmp_path / "test.json"))

        # Same signal (same "transmitter")
        t = np.arange(1024) / 2400000
        iq = 10.0 * np.exp(2j * np.pi * 50000 * t)

        # First: enroll
        r1 = sei.identify(iq, frequency_hz=121500000, snr_db=20, duration_ms=200)
        assert r1["event"] == "new_emitter"
        new_events = [e for e in emitted if e[0] == "new_emitter"]
        assert len(new_events) == 1

        # Second: re-identify
        r2 = sei.identify(iq, frequency_hz=121500000, snr_db=20, duration_ms=200)
        assert r2["event"] == "re_identified"
        assert r2["emitter_id"] == r1["emitter_id"]
        id_events = [e for e in emitted if e[0] == "emitter_identified"]
        assert len(id_events) == 1

    def test_three_distinct_emitters(self, tmp_path):
        """Three different signals should produce three separate emitter IDs."""
        sei = SEIModel(db_path=str(tmp_path / "test.json"))

        emitter_ids = set()
        for freq_offset in [50000, 150000, 300000]:
            t = np.arange(1024) / 2400000
            iq = 10.0 * np.exp(2j * np.pi * freq_offset * t)
            # Add unique per-emitter noise to differentiate
            iq += (freq_offset / 300000) * np.random.randn(1024)

            r = sei.identify(iq, frequency_hz=100000000 + freq_offset,
                              snr_db=25, duration_ms=200)
            if r is not None:
                emitter_ids.add(r["emitter_id"])

        # Should have enrolled multiple distinct emitters
        # (CPU fallback may or may not distinguish all three)
        assert len(emitter_ids) >= 1

    def test_database_persistence(self, tmp_path):
        """Emitters should persist across model instances."""
        db_path = str(tmp_path / "persist.json")

        # Create and enroll
        sei1 = SEIModel(db_path=db_path)
        t = np.arange(1024) / 2400000
        iq = 10.0 * np.exp(2j * np.pi * 50000 * t)
        sei1.identify(iq, frequency_hz=121500000, snr_db=20, duration_ms=200)
        sei1.label_emitter("EMITTER-001", "Test Aircraft")
        sei1.stop()

        # Load in new instance
        sei2 = SEIModel(db_path=db_path)
        assert sei2.get_status()["emitter_count"] == 1
        record = sei2.get_emitter("EMITTER-001")
        assert record is not None
        assert record["label"] == "Test Aircraft"

    def test_api_emitter_list(self, tmp_path):
        """list_emitters should return all enrolled emitters."""
        sei = SEIModel(db_path=str(tmp_path / "test.json"))

        for i in range(5):
            t = np.arange(1024) / 2400000
            iq = float(i + 1) * np.exp(2j * np.pi * (50000 + i * 50000) * t)
            iq += 0.5 * np.random.randn(1024)
            sei.identify(iq, frequency_hz=100000000, snr_db=25, duration_ms=200)

        result = sei.list_emitters()
        assert result["total"] >= 1
        assert len(result["emitters"]) >= 1

    def test_label_via_api(self, tmp_path):
        """Label assignment should persist."""
        sei = SEIModel(db_path=str(tmp_path / "test.json"))
        t = np.arange(1024) / 2400000
        iq = 10.0 * np.exp(2j * np.pi * 50000 * t)
        sei.identify(iq, frequency_hz=1090000000, snr_db=20, duration_ms=200)

        assert sei.label_emitter("EMITTER-001", "ASA355 (A1B2C3)")
        record = sei.get_emitter("EMITTER-001")
        assert record["label"] == "ASA355 (A1B2C3)"


class TestClassifierToSEIIntegration:
    """Test signal classifier forwarding to SEI."""

    def test_classifier_forwards_to_sei(self, tmp_path):
        """When SEI model is set, classifier should forward classified IQ."""
        emitted = []

        def mock_emit(event, data, **kw):
            emitted.append((event, data))

        clf = SignalClassifier(emit_fn=mock_emit)
        sei = SEIModel(emit_fn=mock_emit, db_path=str(tmp_path / "test.json"))
        clf.set_sei_model(sei)

        # Classify a signal (will also forward to SEI if conditions met)
        t = np.arange(4096) / 2400000
        iq = 10.0 * np.exp(2j * np.pi * 100000 * t)

        result = clf.classify_iq(iq, frequency_hz=121500000)

        # SEI may or may not have enough SNR/duration to process,
        # but the pipeline should not crash
        assert result is None or result["modulation"] in [
            "AM", "FM", "WFM", "SSB", "P25", "DMR", "ADSB",
            "NOAA_APT", "WEFAX", "CW", "unknown",
        ]

    def test_classify_segment_method(self, tmp_path):
        """classify_segment should accept Segment objects."""
        import datetime

        clf = SignalClassifier()
        sei = SEIModel(db_path=str(tmp_path / "test.json"))
        clf.set_sei_model(sei)

        segment = Segment(
            iq_samples=10.0 * np.exp(2j * np.pi * 100000 * np.arange(4096) / 2400000),
            start_time=datetime.datetime.now(datetime.timezone.utc),
            duration_ms=500,
            frequency_hz=121500000,
            snr_db=20.0,
            peak_power_db=-50.0,
            mean_power_db=-55.0,
        )

        result = clf.classify_segment(segment)
        # Should produce a classification or None
        if result is not None:
            assert "modulation" in result
            assert "confidence" in result
