# Integration test for meteor scatter detection pipeline

import datetime
from unittest.mock import MagicMock, patch

import pytest

from ravensdr.meteor_detector import MeteorDetector
from ravensdr.meteor_analyzer import MeteorAnalyzer


pytestmark = pytest.mark.integration


class TestMeteorPipelineMocked:
    """Test detector → analyzer → API → Socket.IO event chain with mocked hardware."""

    def test_detector_emits_events(self):
        """Verify detector emits meteor_detection events on valid bursts."""
        emit_fn = MagicMock()
        detector = MeteorDetector(emit_fn=emit_fn, frequency_hz=143050000)

        # Simulate 3 underdense and 1 overdense burst
        now = datetime.datetime.utcnow()

        # Underdense bursts (< 0.5s)
        for i in range(3):
            detector._burst_start = now + datetime.timedelta(seconds=i * 10)
            detector._burst_samples = [70.0, 68.0, 65.0]
            end = detector._burst_start + datetime.timedelta(milliseconds=200)
            detector._process_burst(end)

        # Overdense burst (> 0.5s)
        detector._burst_start = now + datetime.timedelta(seconds=30)
        detector._burst_samples = [70.0] * 20 + [65.0] * 10
        end = detector._burst_start + datetime.timedelta(seconds=2)
        detector._process_burst(end)

        assert emit_fn.call_count == 4
        assert detector.get_event_count() == 4

        # Check trail types
        events = detector.get_events(limit=10)
        trail_types = [e["trail_type"] for e in events]
        assert trail_types.count("underdense") == 3
        assert trail_types.count("overdense") == 1

    def test_analyzer_tags_shower(self):
        """Verify analyzer tags events with correct shower info."""
        analyzer = MeteorAnalyzer()

        # Event during Perseids
        event = {
            "timestamp": "2026-08-12T03:42:17.234Z",
            "trail_type": "underdense",
            "duration_ms": 200,
        }
        analyzer.tag_event_shower(event)
        assert event["shower"] == "Perseids"
        assert event["shower_active"] is True

        # Event outside any shower
        event2 = {
            "timestamp": "2026-03-15T12:00:00.000Z",
            "trail_type": "underdense",
            "duration_ms": 150,
        }
        analyzer.tag_event_shower(event2)
        assert event2["shower"] is None
        assert event2["shower_active"] is False

    def test_stats_from_events(self):
        """Verify stats calculation from known event list."""
        analyzer = MeteorAnalyzer()
        now = datetime.datetime.utcnow()

        events = []
        for i in range(10):
            events.append({
                "timestamp": (now - datetime.timedelta(minutes=i * 5)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "trail_type": "underdense" if i < 7 else "overdense",
            })

        stats = analyzer.get_session_stats(events)
        assert stats["total"] == 10
        assert stats["underdense_count"] == 7
        assert stats["overdense_count"] == 3

        hourly = analyzer.get_hourly_stats(events, hours=24)
        total_in_hourly = sum(h["count"] for h in hourly)
        assert total_in_hourly == 10

    def test_dual_dongle_mode(self):
        """Verify meteor detector can be configured for second dongle."""
        detector = MeteorDetector(device_index=1, frequency_hz=143050000)
        cmd = detector.build_rtl_fm_cmd()
        assert "-d" in cmd
        assert cmd[cmd.index("-d") + 1] == "1"

    def test_meteor_mode_lowest_priority(self):
        """Verify meteor mode is preempted by other modes."""
        from ravensdr.input_source import InputSource

        with patch("ravensdr.input_source.detect_sdr", return_value=True):
            source = InputSource("SDR")

        # Enter meteor mode
        result = source.enter_meteor_mode(143050000)
        assert result is True
        assert source.meteor_mode is True

        # Tuning should exit meteor mode automatically
        with patch.object(source._source, "tune"):
            with patch.object(source._source, "stop"):
                result = source.tune({"freq": "162.550M", "mode": "fm", "label": "test"})
        assert source.meteor_mode is False

    def test_meteor_mode_blocked_by_apt(self):
        """Verify meteor mode cannot be entered during APT pass."""
        from ravensdr.input_source import InputSource

        with patch("ravensdr.input_source.detect_sdr", return_value=True):
            source = InputSource("SDR")

        source._apt_mode = True
        result = source.enter_meteor_mode(143050000)
        assert result is False
        assert source.meteor_mode is False

    def test_meteor_mode_blocked_by_wefax(self):
        """Verify meteor mode cannot be entered during WEFAX recording."""
        from ravensdr.input_source import InputSource

        with patch("ravensdr.input_source.detect_sdr", return_value=True):
            source = InputSource("SDR")

        source._wefax_mode = True
        result = source.enter_meteor_mode(143050000)
        assert result is False


class TestManualTestProcedure:
    """
    Manual test procedure for live meteor detection validation.

    1. Connect RTL-SDR Blog V4 (or second dongle for dual mode)
    2. Set METEOR_ENABLED=true and optionally METEOR_DUAL_DONGLE=true
    3. Tune to 143.050 MHz (amateur meteor scatter calling frequency)
    4. Run detector for 24 hours

    Expected results:
    - Pre-dawn hours (02:00-06:00 local): 5-15 sporadic detections per hour
    - Afternoon (12:00-18:00 local): 2-5 sporadic detections per hour
    - During Perseid peak (Aug 11-13): 30-60+ detections per hour pre-dawn

    Notes:
    - Initial threshold may need tuning based on local noise environment
    - If false positive rate is high, increase METEOR_THRESHOLD_DB
    - Second dongle strongly recommended for 24/7 monitoring
    - No audio — this is pure power detection
    """

    @pytest.mark.skip(reason="Manual test — requires hardware and 24h runtime")
    def test_live_24h_detection(self):
        """Run meteor detector for 24 hours on 143.050 MHz."""
        pass

    @pytest.mark.skip(reason="Manual test — requires hardware during shower peak")
    def test_live_perseid_peak(self):
        """Run during Perseid peak (Aug 11-13) and verify elevated rates."""
        pass
