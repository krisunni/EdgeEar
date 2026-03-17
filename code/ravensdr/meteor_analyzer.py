# Meteor statistics analyzer — shower calendar, flux rate, hourly/daily stats

import datetime
import json
import logging
import os

log = logging.getLogger(__name__)

SHOWER_FILE = os.path.join(os.path.dirname(__file__), "data", "meteor_showers.json")


def load_shower_calendar():
    """Load meteor shower calendar from JSON file."""
    try:
        with open(SHOWER_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log.warning("Failed to load meteor shower calendar: %s", e)
        return []


class MeteorAnalyzer:
    """Analyzes meteor detection events — shower correlation, rate stats."""

    def __init__(self):
        self._showers = load_shower_calendar()
        self._session_start = datetime.datetime.utcnow()

    def get_showers(self):
        """Return full shower calendar with current/next highlighted."""
        today = datetime.datetime.utcnow()
        result = []
        for shower in self._showers:
            entry = dict(shower)
            entry["is_active"] = self._is_shower_active(shower, today)
            result.append(entry)
        return result

    def get_current_shower(self, date=None):
        """Return the active shower for a given date, or None."""
        date = date or datetime.datetime.utcnow()
        for shower in self._showers:
            if self._is_shower_active(shower, date):
                return shower
        return None

    def get_next_shower(self, date=None):
        """Return the next upcoming shower and days until peak."""
        date = date or datetime.datetime.utcnow()
        year = date.year
        best = None
        best_days = 999

        for shower in self._showers:
            peak_str = shower["peak_date"]  # "MM-DD"
            month, day = map(int, peak_str.split("-"))

            # Check this year and next year
            for y in [year, year + 1]:
                try:
                    peak_dt = datetime.datetime(y, month, day)
                except ValueError:
                    continue
                delta = (peak_dt - date).days
                if delta > 0 and delta < best_days:
                    best_days = delta
                    best = {
                        "name": shower["name"],
                        "peak_date": f"{y}-{peak_str}",
                        "days_until": delta,
                        "zhr": shower.get("zhr", 0),
                        "parent_body": shower.get("parent_body", ""),
                    }
        return best

    def tag_event_shower(self, event, date=None):
        """Tag an event dict with active shower info."""
        if date is None:
            try:
                ts = event.get("timestamp", "")
                date = datetime.datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")
            except (ValueError, TypeError):
                date = datetime.datetime.utcnow()

        shower = self.get_current_shower(date)
        if shower:
            event["shower"] = shower["name"]
            event["shower_active"] = True
        else:
            event["shower"] = None
            event["shower_active"] = False
        return event

    def get_hourly_stats(self, events, hours=24):
        """Return list of hourly detection counts for the last N hours."""
        now = datetime.datetime.utcnow()
        counts = [0] * hours

        for event in events:
            try:
                ts = datetime.datetime.strptime(
                    event["timestamp"][:19], "%Y-%m-%dT%H:%M:%S"
                )
            except (ValueError, KeyError):
                continue

            age_hours = (now - ts).total_seconds() / 3600
            if 0 <= age_hours < hours:
                bucket = int(age_hours)
                counts[bucket] += 1

        # Return in chronological order (oldest first)
        result = []
        for i in range(hours - 1, -1, -1):
            hour_dt = now - datetime.timedelta(hours=i)
            result.append({
                "hour": hour_dt.strftime("%Y-%m-%dT%H:00:00Z"),
                "count": counts[i],
            })
        return result

    def get_daily_stats(self, events, days=7):
        """Return list of daily detection counts for the last N days."""
        now = datetime.datetime.utcnow()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        counts = [0] * days

        for event in events:
            try:
                ts = datetime.datetime.strptime(
                    event["timestamp"][:19], "%Y-%m-%dT%H:%M:%S"
                )
            except (ValueError, KeyError):
                continue

            age_days = (today - ts.replace(hour=0, minute=0, second=0, microsecond=0)).days
            if 0 <= age_days < days:
                counts[age_days] += 1

        result = []
        for i in range(days - 1, -1, -1):
            day_dt = today - datetime.timedelta(days=i)
            result.append({
                "date": day_dt.strftime("%Y-%m-%d"),
                "count": counts[i],
            })
        return result

    def get_session_stats(self, events):
        """Return session statistics summary."""
        if not events:
            return {
                "total": 0,
                "peak_hourly_rate": 0,
                "underdense_count": 0,
                "overdense_count": 0,
                "underdense_ratio": 0,
                "session_hours": 0,
            }

        underdense = sum(1 for e in events if e.get("trail_type") == "underdense")
        overdense = sum(1 for e in events if e.get("trail_type") == "overdense")
        total = len(events)

        # Peak hourly rate from hourly stats
        hourly = self.get_hourly_stats(events, hours=24)
        peak_rate = max(h["count"] for h in hourly) if hourly else 0

        session_hours = (datetime.datetime.utcnow() - self._session_start).total_seconds() / 3600

        return {
            "total": total,
            "peak_hourly_rate": peak_rate,
            "underdense_count": underdense,
            "overdense_count": overdense,
            "underdense_ratio": round(underdense / total, 2) if total > 0 else 0,
            "session_hours": round(session_hours, 1),
        }

    def _is_shower_active(self, shower, date):
        """Check if a shower is active on a given date."""
        active_start = shower.get("active_start", shower["peak_date"])
        active_end = shower.get("active_end", shower.get("peak_end", shower["peak_date"]))

        try:
            start_month, start_day = map(int, active_start.split("-"))
            end_month, end_day = map(int, active_end.split("-"))
        except (ValueError, AttributeError):
            return False

        year = date.year
        try:
            start_dt = datetime.datetime(year, start_month, start_day)
            end_dt = datetime.datetime(year, end_month, end_day)
        except ValueError:
            return False

        # Handle year wrap (e.g., Quadrantids: active_start=12-28, active_end=01-12)
        if end_dt < start_dt:
            # Check if date is in the late part of current year or early part of next year
            if date.month >= start_month:
                end_dt = datetime.datetime(year + 1, end_month, end_day)
            else:
                start_dt = datetime.datetime(year - 1, start_month, start_day)

        return start_dt <= date <= end_dt
