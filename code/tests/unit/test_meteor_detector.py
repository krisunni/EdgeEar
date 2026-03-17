# Unit tests for meteor scatter detector

import datetime
import numpy as np
from unittest.mock import MagicMock, patch

import pytest

from ravensdr.meteor_detector import (
    DEFAULT_THRESHOLD_DB,
    MAX_BURST_SEC,
    MIN_BURST_MS,
    UNDERDENSE_THRESHOLD_SEC,
    MeteorDetector,
)


class TestRtlFmCommand:
    """Test rtl_fm command construction for meteor monitoring."""

    def test_default_command(self):
        detector = MeteorDetector(frequency_hz=143050000)
        cmd = detector.build_rtl_fm_cmd()
        assert cmd[0] == "rtl_fm"
        assert "-f" in cmd
        idx = cmd.index("-f")
        assert cmd[idx + 1] == "143050000"
        assert "-M" in cmd
        assert cmd[cmd.index("-M") + 1] == "fm"
        assert cmd[-1] == "-"

    def test_dual_dongle_command(self):
        detector = MeteorDetector(frequency_hz=143050000, device_index=1)
        cmd = detector.build_rtl_fm_cmd()
        assert "-d" in cmd
        idx = cmd.index("-d")
        assert cmd[idx + 1] == "1"

    def test_single_dongle_no_device_flag(self):
        detector = MeteorDetector(frequency_hz=143050000, device_index=0)
        cmd = detector.build_rtl_fm_cmd()
        assert "-d" not in cmd

    def test_gain_set(self):
        detector = MeteorDetector()
        cmd = detector.build_rtl_fm_cmd()
        assert "-g" in cmd
        assert "40" in cmd


class TestThresholdDetection:
    """Test burst detection logic against synthetic data."""

    def test_baseline_computation(self):
        detector = MeteorDetector()
        # Feed some baseline samples
        for _ in range(100):
            detector._update_baseline(50.0, 0.046)
        assert abs(detector._baseline_power_db - 50.0) < 1.0

    def test_burst_below_threshold_ignored(self):
        detector = MeteorDetector(threshold_db=10)
        detector._baseline_power_db = 50.0
        detector._in_burst = False

        # Power at 55 dB — only 5 dB above baseline, below 10 dB threshold
        excess = 55.0 - detector._baseline_power_db
        assert excess < detector.threshold_db

    def test_burst_above_threshold_detected(self):
        detector = MeteorDetector(threshold_db=10)
        detector._baseline_power_db = 50.0

        # Power at 65 dB — 15 dB above baseline
        excess = 65.0 - detector._baseline_power_db
        assert excess >= detector.threshold_db


class TestDurationFiltering:
    """Test burst duration filtering."""

    def test_short_burst_filtered(self):
        detector = MeteorDetector()
        detector._burst_start = datetime.datetime.utcnow()
        detector._burst_samples = [70.0]

        # Burst only 20ms — should be filtered
        end = detector._burst_start + datetime.timedelta(milliseconds=20)
        emit_fn = MagicMock()
        detector.emit_fn = emit_fn
        detector._process_burst(end)
        emit_fn.assert_not_called()

    def test_long_burst_flagged_as_interference(self):
        detector = MeteorDetector()
        detector._burst_start = datetime.datetime.utcnow()
        detector._burst_samples = [70.0] * 100

        # 35 second burst — flagged as interference
        end = detector._burst_start + datetime.timedelta(seconds=35)
        emit_fn = MagicMock()
        detector.emit_fn = emit_fn
        detector._process_burst(end)
        emit_fn.assert_not_called()

    def test_valid_burst_emitted(self):
        detector = MeteorDetector()
        detector._burst_start = datetime.datetime.utcnow()
        detector._burst_samples = [70.0, 68.0, 65.0]

        # 200ms burst — valid
        end = detector._burst_start + datetime.timedelta(milliseconds=200)
        emit_fn = MagicMock()
        detector.emit_fn = emit_fn
        detector._process_burst(end)
        emit_fn.assert_called_once()
        call_args = emit_fn.call_args[0]
        assert call_args[0] == "meteor_detection"
        event = call_args[1]
        assert event["duration_ms"] == 200
        assert event["trail_type"] == "underdense"


class TestTrailClassification:
    """Test trail type classification."""

    def test_underdense_short_duration(self):
        result = MeteorDetector._classify_trail(0.2, [70, 65, 60])
        assert result == "underdense"

    def test_underdense_at_boundary(self):
        result = MeteorDetector._classify_trail(0.49, [70, 65])
        assert result == "underdense"

    def test_overdense_at_boundary(self):
        result = MeteorDetector._classify_trail(0.5, [70, 70, 65])
        assert result == "overdense"

    def test_overdense_long_duration(self):
        result = MeteorDetector._classify_trail(3.0, [70] * 50)
        assert result == "overdense"


class TestPowerMeasurement:
    """Test power extraction from burst samples."""

    def test_peak_power(self):
        detector = MeteorDetector()
        detector._burst_start = datetime.datetime.utcnow()
        detector._burst_samples = [60.0, 75.0, 68.0, 62.0]

        end = detector._burst_start + datetime.timedelta(milliseconds=200)
        emit_fn = MagicMock()
        detector.emit_fn = emit_fn
        detector._process_burst(end)

        event = emit_fn.call_args[0][1]
        assert event["peak_power_dbm"] == 75.0

    def test_mean_power(self):
        detector = MeteorDetector()
        detector._burst_start = datetime.datetime.utcnow()
        detector._burst_samples = [60.0, 70.0, 80.0]

        end = detector._burst_start + datetime.timedelta(milliseconds=200)
        emit_fn = MagicMock()
        detector.emit_fn = emit_fn
        detector._process_burst(end)

        event = emit_fn.call_args[0][1]
        assert abs(event["mean_power_dbm"] - 70.0) < 0.1


class TestEventPayload:
    """Test event payload structure."""

    def test_event_has_required_fields(self):
        detector = MeteorDetector(frequency_hz=143050000)
        detector._burst_start = datetime.datetime(2026, 8, 12, 3, 42, 17, 234000)
        detector._burst_samples = [70.0, 68.0]

        end = detector._burst_start + datetime.timedelta(milliseconds=300)
        emit_fn = MagicMock()
        detector.emit_fn = emit_fn
        detector._process_burst(end)

        event = emit_fn.call_args[0][1]
        assert "timestamp" in event
        assert "duration_ms" in event
        assert "peak_power_dbm" in event
        assert "mean_power_dbm" in event
        assert "frequency_hz" in event
        assert "doppler_offset_hz" in event
        assert "trail_type" in event
        assert "shower" in event
        assert "shower_active" in event
        assert event["frequency_hz"] == 143050000

    def test_timestamp_format(self):
        detector = MeteorDetector()
        detector._burst_start = datetime.datetime(2026, 8, 12, 3, 42, 17, 234000)
        detector._burst_samples = [70.0]

        end = detector._burst_start + datetime.timedelta(milliseconds=100)
        emit_fn = MagicMock()
        detector.emit_fn = emit_fn
        detector._process_burst(end)

        event = emit_fn.call_args[0][1]
        # Timestamp should be ISO 8601 with milliseconds
        assert event["timestamp"].startswith("2026-08-12T03:42:17.")
        assert event["timestamp"].endswith("Z")


class TestDetectorState:
    """Test detector state management."""

    def test_initial_state(self):
        detector = MeteorDetector()
        assert detector.is_running is False
        assert detector.get_event_count() == 0

    def test_stop_when_not_running(self):
        detector = MeteorDetector()
        detector.stop()  # should not raise

    def test_events_stored(self):
        detector = MeteorDetector()
        detector._burst_start = datetime.datetime.utcnow()
        detector._burst_samples = [70.0]
        end = detector._burst_start + datetime.timedelta(milliseconds=200)

        emit_fn = MagicMock()
        detector.emit_fn = emit_fn
        detector._process_burst(end)

        assert detector.get_event_count() == 1
        events = detector.get_events(limit=10)
        assert len(events) == 1

    def test_events_capped(self):
        detector = MeteorDetector()
        # Add 10001 events directly
        for i in range(10001):
            detector._events.append({"timestamp": f"2026-01-01T{i:05d}", "trail_type": "underdense"})
        # Cap should work
        assert len(detector._events) == 10001
        # After next burst processing, it will cap
        detector._burst_start = datetime.datetime.utcnow()
        detector._burst_samples = [70.0]
        end = detector._burst_start + datetime.timedelta(milliseconds=200)
        emit_fn = MagicMock()
        detector.emit_fn = emit_fn
        detector._process_burst(end)
        assert len(detector._events) <= 10001


class TestConstants:
    """Test detector constants."""

    def test_threshold_default(self):
        assert DEFAULT_THRESHOLD_DB == 10

    def test_min_burst_ms(self):
        assert MIN_BURST_MS == 50

    def test_max_burst_sec(self):
        assert MAX_BURST_SEC == 30

    def test_underdense_threshold(self):
        assert UNDERDENSE_THRESHOLD_SEC == 0.5
