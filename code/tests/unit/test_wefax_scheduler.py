# Unit tests for WEFAX broadcast scheduler

import datetime
from unittest.mock import MagicMock, patch

import pytest

from ravensdr.wefax_scheduler import (
    NMC_SCHEDULE,
    NOJ_SCHEDULE,
    NMC_FREQUENCIES,
    NOJ_FREQUENCIES,
    PRIORITY_CHART_TYPES,
    WefaxScheduler,
    select_frequency,
)


class TestSelectFrequency:
    """Test HF frequency selection based on time of day."""

    def test_daytime_prefers_higher_frequencies(self):
        # UTC 12:00 = daytime
        freq = select_frequency(NMC_FREQUENCIES, 12)
        assert freq >= 8000  # should pick 8682 or higher

    def test_nighttime_prefers_lower_frequencies(self):
        # UTC 02:00 = nighttime
        freq = select_frequency(NMC_FREQUENCIES, 2)
        assert freq <= 5000  # should pick 4346 or lower

    def test_daytime_boundary_06(self):
        freq = select_frequency(NMC_FREQUENCIES, 6)
        assert freq >= 8000

    def test_nighttime_boundary_05(self):
        freq = select_frequency(NMC_FREQUENCIES, 5)
        assert freq <= 5000

    def test_nighttime_boundary_18(self):
        freq = select_frequency(NMC_FREQUENCIES, 18)
        assert freq <= 5000

    def test_single_frequency(self):
        freq = select_frequency([8682.0], 12)
        assert freq == 8682.0

    def test_noj_daytime(self):
        freq = select_frequency(NOJ_FREQUENCIES, 10)
        assert freq >= 8000

    def test_noj_nighttime(self):
        freq = select_frequency(NOJ_FREQUENCIES, 22)
        assert freq <= 5000


class TestWefaxSchedulerSchedule:
    """Test broadcast schedule parsing."""

    def test_nmc_schedule_has_entries(self):
        assert len(NMC_SCHEDULE) > 0

    def test_noj_schedule_has_entries(self):
        assert len(NOJ_SCHEDULE) > 0

    def test_nmc_schedule_has_required_fields(self):
        for entry in NMC_SCHEDULE:
            assert "utc_time" in entry
            assert "chart_type" in entry
            assert "description" in entry
            assert "duration_minutes" in entry

    def test_noj_schedule_has_required_fields(self):
        for entry in NOJ_SCHEDULE:
            assert "utc_time" in entry
            assert "chart_type" in entry
            assert "description" in entry
            assert "duration_minutes" in entry

    def test_nmc_frequencies_correct(self):
        assert 4346.0 in NMC_FREQUENCIES
        assert 8682.0 in NMC_FREQUENCIES
        assert 12786.0 in NMC_FREQUENCIES
        assert 17151.2 in NMC_FREQUENCIES

    def test_noj_frequencies_correct(self):
        assert 2054.0 in NOJ_FREQUENCIES
        assert 4298.0 in NOJ_FREQUENCIES
        assert 8459.0 in NOJ_FREQUENCIES
        assert 12412.0 in NOJ_FREQUENCIES

    def test_priority_chart_types(self):
        assert "surface_analysis" in PRIORITY_CHART_TYPES
        assert "24hr_forecast" in PRIORITY_CHART_TYPES


class TestWefaxSchedulerGetUpcoming:
    """Test get_upcoming_broadcasts method."""

    def test_returns_sorted_by_start_time(self):
        scheduler = WefaxScheduler()
        broadcasts = scheduler.get_upcoming_broadcasts(hours=6)
        times = [b["start_utc"] for b in broadcasts]
        assert times == sorted(times)

    def test_broadcasts_have_required_fields(self):
        scheduler = WefaxScheduler()
        broadcasts = scheduler.get_upcoming_broadcasts(hours=6)
        for b in broadcasts:
            assert "station" in b
            assert "frequency_khz" in b
            assert "chart_type" in b
            assert "start_utc" in b
            assert "duration_minutes" in b
            assert "description" in b
            assert "priority" in b

    def test_station_is_nmc_or_noj(self):
        scheduler = WefaxScheduler()
        broadcasts = scheduler.get_upcoming_broadcasts(hours=6)
        for b in broadcasts:
            assert b["station"] in ("NMC", "NOJ")

    def test_excludes_broadcasts_outside_window(self):
        scheduler = WefaxScheduler()
        now = datetime.datetime.utcnow()
        end = now + datetime.timedelta(hours=1)

        broadcasts = scheduler.get_upcoming_broadcasts(hours=1)
        for b in broadcasts:
            start = datetime.datetime.strptime(b["start_utc"], "%Y-%m-%dT%H:%M:%SZ")
            assert start <= end

    def test_priority_flag_matches_chart_type(self):
        scheduler = WefaxScheduler()
        broadcasts = scheduler.get_upcoming_broadcasts(hours=6)
        for b in broadcasts:
            if b["chart_type"] in PRIORITY_CHART_TYPES:
                assert b["priority"] is True
            else:
                assert b["priority"] is False

    def test_frequency_adapts_to_time(self):
        scheduler = WefaxScheduler()
        broadcasts = scheduler.get_upcoming_broadcasts(hours=6)

        # Verify that broadcasts with daytime UTC hours use higher freqs
        # and nighttime hours use lower freqs
        for b in broadcasts:
            h = int(b["start_utc"][11:13])
            if 6 <= h < 18:
                assert b["frequency_khz"] >= 8000, \
                    f"Daytime broadcast at {h}:00 should use high freq, got {b['frequency_khz']}"
            else:
                assert b["frequency_khz"] <= 5000, \
                    f"Nighttime broadcast at {h}:00 should use low freq, got {b['frequency_khz']}"


class TestWefaxSchedulerCallbacks:
    """Test scheduler event emission and broadcast triggering."""

    def test_start_stop(self):
        scheduler = WefaxScheduler()
        scheduler.start()
        assert scheduler._running is True
        scheduler.stop()
        assert scheduler._running is False

    def test_emit_fn_called_on_upcoming(self):
        emit_fn = MagicMock()
        scheduler = WefaxScheduler(emit_fn=emit_fn)

        # Manually inject a broadcast that's 3 minutes away
        now = datetime.datetime.utcnow()
        soon = now + datetime.timedelta(minutes=3)

        # Patch get_upcoming_broadcasts to return a known broadcast
        broadcast = {
            "station": "NMC",
            "frequency_khz": 8682.0,
            "chart_type": "surface_analysis",
            "start_utc": soon.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "duration_minutes": 10,
            "description": "North Pacific Surface Analysis",
            "priority": True,
        }

        with patch.object(scheduler, "get_upcoming_broadcasts", return_value=[broadcast]):
            scheduler._check_upcoming_broadcasts()

        emit_fn.assert_called_once()
        call_args = emit_fn.call_args
        assert call_args[0][0] == "wefax_broadcast_upcoming"

    def test_on_broadcast_start_called_at_broadcast_time(self):
        callback = MagicMock()
        scheduler = WefaxScheduler(on_broadcast_start=callback)

        now = datetime.datetime.utcnow()
        broadcast = {
            "station": "NMC",
            "frequency_khz": 8682.0,
            "chart_type": "surface_analysis",
            "start_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "duration_minutes": 10,
            "description": "North Pacific Surface Analysis",
            "priority": True,
        }

        with patch.object(scheduler, "get_upcoming_broadcasts", return_value=[broadcast]):
            scheduler._check_upcoming_broadcasts()

        callback.assert_called_once_with(broadcast)

    def test_non_priority_broadcasts_dont_trigger_recording(self):
        callback = MagicMock()
        scheduler = WefaxScheduler(on_broadcast_start=callback)

        now = datetime.datetime.utcnow()
        broadcast = {
            "station": "NMC",
            "frequency_khz": 8682.0,
            "chart_type": "96hr_forecast",
            "start_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "duration_minutes": 10,
            "description": "96-Hour Surface Forecast",
            "priority": False,
        }

        with patch.object(scheduler, "get_upcoming_broadcasts", return_value=[broadcast]):
            scheduler._check_upcoming_broadcasts()

        callback.assert_not_called()

    def test_duplicate_notification_suppressed(self):
        emit_fn = MagicMock()
        scheduler = WefaxScheduler(emit_fn=emit_fn)

        now = datetime.datetime.utcnow()
        soon = now + datetime.timedelta(minutes=3)
        broadcast = {
            "station": "NMC",
            "frequency_khz": 8682.0,
            "chart_type": "surface_analysis",
            "start_utc": soon.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "duration_minutes": 10,
            "description": "North Pacific Surface Analysis",
            "priority": True,
        }

        with patch.object(scheduler, "get_upcoming_broadcasts", return_value=[broadcast]):
            scheduler._check_upcoming_broadcasts()
            scheduler._check_upcoming_broadcasts()

        # Should only emit once
        assert emit_fn.call_count == 1
