# Unit tests for meteor statistics analyzer and shower calendar

import datetime
from unittest.mock import patch

import pytest

from ravensdr.meteor_analyzer import MeteorAnalyzer, load_shower_calendar


class TestShowerCalendar:
    """Test shower calendar loading and querying."""

    def test_calendar_loads(self):
        showers = load_shower_calendar()
        assert len(showers) >= 7

    def test_calendar_has_required_fields(self):
        showers = load_shower_calendar()
        for shower in showers:
            assert "name" in shower
            assert "peak_date" in shower
            assert "zhr" in shower
            assert "speed_kms" in shower
            assert "parent_body" in shower


class TestGetCurrentShower:
    """Test active shower detection."""

    def test_perseids_active_august_12(self):
        analyzer = MeteorAnalyzer()
        date = datetime.datetime(2026, 8, 12)
        shower = analyzer.get_current_shower(date)
        assert shower is not None
        assert shower["name"] == "Perseids"

    def test_geminids_active_december_14(self):
        analyzer = MeteorAnalyzer()
        date = datetime.datetime(2026, 12, 14)
        shower = analyzer.get_current_shower(date)
        assert shower is not None
        assert shower["name"] == "Geminids"

    def test_no_shower_march_15(self):
        analyzer = MeteorAnalyzer()
        date = datetime.datetime(2026, 3, 15)
        shower = analyzer.get_current_shower(date)
        assert shower is None

    def test_leonids_active_november_17(self):
        analyzer = MeteorAnalyzer()
        date = datetime.datetime(2026, 11, 17)
        shower = analyzer.get_current_shower(date)
        assert shower is not None
        assert shower["name"] == "Leonids"

    def test_quadrantids_year_wrap(self):
        """Quadrantids: active 12-28 to 01-12 — wraps across year boundary."""
        analyzer = MeteorAnalyzer()
        # Should be active on Jan 3
        date = datetime.datetime(2026, 1, 3)
        shower = analyzer.get_current_shower(date)
        assert shower is not None
        assert shower["name"] == "Quadrantids"

        # Should be active on Dec 30
        date = datetime.datetime(2025, 12, 30)
        shower = analyzer.get_current_shower(date)
        assert shower is not None
        assert shower["name"] == "Quadrantids"


class TestGetNextShower:
    """Test next upcoming shower prediction."""

    def test_next_from_march(self):
        analyzer = MeteorAnalyzer()
        date = datetime.datetime(2026, 3, 15)
        next_shower = analyzer.get_next_shower(date)
        assert next_shower is not None
        assert next_shower["days_until"] > 0
        # Should be Lyrids (April 22)
        assert next_shower["name"] == "Lyrids"

    def test_next_from_september(self):
        analyzer = MeteorAnalyzer()
        date = datetime.datetime(2026, 9, 1)
        next_shower = analyzer.get_next_shower(date)
        assert next_shower is not None
        assert next_shower["name"] == "Orionids"

    def test_next_has_required_fields(self):
        analyzer = MeteorAnalyzer()
        next_shower = analyzer.get_next_shower(datetime.datetime(2026, 6, 1))
        assert next_shower is not None
        assert "name" in next_shower
        assert "peak_date" in next_shower
        assert "days_until" in next_shower
        assert "zhr" in next_shower


class TestShowerCorrelation:
    """Test event tagging with active shower."""

    def test_tag_during_perseids(self):
        analyzer = MeteorAnalyzer()
        event = {"timestamp": "2026-08-12T03:42:17.234Z"}
        analyzer.tag_event_shower(event)
        assert event["shower"] == "Perseids"
        assert event["shower_active"] is True

    def test_tag_outside_shower(self):
        analyzer = MeteorAnalyzer()
        event = {"timestamp": "2026-03-15T12:00:00.000Z"}
        analyzer.tag_event_shower(event)
        assert event["shower"] is None
        assert event["shower_active"] is False

    def test_tag_during_geminids(self):
        analyzer = MeteorAnalyzer()
        event = {"timestamp": "2026-12-14T04:00:00.000Z"}
        analyzer.tag_event_shower(event)
        assert event["shower"] == "Geminids"
        assert event["shower_active"] is True


class TestHourlyStats:
    """Test hourly rate calculations."""

    def test_empty_events(self):
        analyzer = MeteorAnalyzer()
        stats = analyzer.get_hourly_stats([], hours=24)
        assert len(stats) == 24
        assert all(h["count"] == 0 for h in stats)

    def test_known_events(self):
        analyzer = MeteorAnalyzer()
        now = datetime.datetime.utcnow()

        events = [
            {"timestamp": (now - datetime.timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S.000Z")},
            {"timestamp": (now - datetime.timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%S.000Z")},
            {"timestamp": (now - datetime.timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z")},
        ]

        stats = analyzer.get_hourly_stats(events, hours=24)
        # All 3 events should be in the most recent hour bucket
        assert stats[-1]["count"] == 3

    def test_events_in_different_hours(self):
        analyzer = MeteorAnalyzer()
        now = datetime.datetime.utcnow()

        events = [
            {"timestamp": (now - datetime.timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S.000Z")},
            {"timestamp": (now - datetime.timedelta(hours=2, minutes=10)).strftime("%Y-%m-%dT%H:%M:%S.000Z")},
        ]

        stats = analyzer.get_hourly_stats(events, hours=24)
        total = sum(h["count"] for h in stats)
        assert total == 2


class TestDailyStats:
    """Test daily rate calculations."""

    def test_empty_events(self):
        analyzer = MeteorAnalyzer()
        stats = analyzer.get_daily_stats([], days=7)
        assert len(stats) == 7
        assert all(d["count"] == 0 for d in stats)


class TestSessionStats:
    """Test session statistics."""

    def test_empty_session(self):
        analyzer = MeteorAnalyzer()
        stats = analyzer.get_session_stats([])
        assert stats["total"] == 0
        assert stats["peak_hourly_rate"] == 0
        assert stats["underdense_ratio"] == 0

    def test_mixed_trail_types(self):
        analyzer = MeteorAnalyzer()
        now = datetime.datetime.utcnow()
        events = [
            {"timestamp": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "trail_type": "underdense"},
            {"timestamp": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "trail_type": "underdense"},
            {"timestamp": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "trail_type": "overdense"},
        ]

        stats = analyzer.get_session_stats(events)
        assert stats["total"] == 3
        assert stats["underdense_count"] == 2
        assert stats["overdense_count"] == 1
        assert abs(stats["underdense_ratio"] - 0.67) < 0.01


class TestGetShowers:
    """Test full shower calendar with active flag."""

    def test_returns_all_showers(self):
        analyzer = MeteorAnalyzer()
        showers = analyzer.get_showers()
        assert len(showers) >= 7

    def test_active_flag_present(self):
        analyzer = MeteorAnalyzer()
        showers = analyzer.get_showers()
        for shower in showers:
            assert "is_active" in shower
