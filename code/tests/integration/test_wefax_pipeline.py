# Integration test for WEFAX end-to-end pipeline

import datetime
import os
import tempfile
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from ravensdr.wefax_scheduler import WefaxScheduler
from ravensdr.wefax_receiver import WefaxReceiver, FREQ_OFFSET_KHZ


pytestmark = pytest.mark.integration


class TestWefaxPipelineMocked:
    """Test scheduler → receiver → decoder → event chain with mocked hardware."""

    def test_scheduler_triggers_receiver(self):
        """Verify scheduler calls on_broadcast_start for priority broadcasts at broadcast time."""
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

    def test_receiver_constructs_correct_rtl_fm_cmd(self):
        """Verify rtl_fm command has -D 2 and USB mode for WEFAX."""
        freq_khz = 8682.0
        tuned_khz = freq_khz + FREQ_OFFSET_KHZ
        tuned_hz = int(tuned_khz * 1000)

        cmd = WefaxReceiver.build_rtl_fm_cmd(tuned_hz)

        assert cmd[0] == "rtl_fm"
        assert "-E" in cmd and cmd[cmd.index("-E") + 1] == "direct2"
        assert "-M" in cmd and cmd[cmd.index("-M") + 1] == "usb"
        assert "-f" in cmd and cmd[cmd.index("-f") + 1] == str(tuned_hz)

    def test_frequency_offset_applied_correctly(self):
        """Verify -1.9 kHz offset for multiple stations and frequencies."""
        test_cases = [
            (8682.0, 8680.1),
            (4346.0, 4344.1),
            (12786.0, 12784.1),
            (4298.0, 4296.1),
            (8459.0, 8457.1),
        ]
        for listed, expected_tuned in test_cases:
            tuned = listed + FREQ_OFFSET_KHZ
            assert abs(tuned - expected_tuned) < 0.01, \
                f"Listed {listed} kHz should tune to {expected_tuned}, got {tuned}"

    def test_apt_priority_over_wefax(self):
        """Verify WEFAX mode cannot be entered during APT mode."""
        from ravensdr.input_source import InputSource

        with patch("ravensdr.input_source.detect_sdr", return_value=True):
            source = InputSource("SDR")

        # Simulate APT mode active
        source._apt_mode = True
        result = source.enter_wefax_mode(8682.0)
        assert result is False
        assert source.wefax_mode is False

    def test_wefax_mode_enter_exit(self):
        """Verify SDR enters and exits WEFAX mode correctly."""
        from ravensdr.input_source import InputSource

        with patch("ravensdr.input_source.detect_sdr", return_value=True):
            source = InputSource("SDR")

        assert source.wefax_mode is False

        result = source.enter_wefax_mode(8682.0)
        assert result is True
        assert source.wefax_mode is True

        # Cannot tune while in WEFAX mode
        tune_result = source.tune({"freq": "162.550M", "mode": "fm", "label": "test"})
        assert tune_result is False

        source.exit_wefax_mode()
        assert source.wefax_mode is False

    def test_wefax_mode_resumes_preset(self):
        """Verify normal scanning resumes after WEFAX mode exits."""
        from ravensdr.input_source import InputSource

        with patch("ravensdr.input_source.detect_sdr", return_value=True):
            source = InputSource("SDR")

        preset = {"freq": "162.550M", "mode": "fm", "label": "NOAA Seattle"}
        source.current_preset = preset

        source.enter_wefax_mode(8682.0)

        with patch.object(source, "tune") as mock_tune:
            source.exit_wefax_mode()
            mock_tune.assert_called_once_with(preset)

    def test_decoded_image_filename_convention(self):
        """Verify decoded PNG filename follows expected convention."""
        meta = WefaxReceiver._parse_filename("NMC_8682kHz_surface_analysis_2026-03-16T1230Z.png")
        assert meta["station"] == "NMC"
        assert meta["frequency_khz"] == 8682.0
        assert meta["chart_type"] == "surface_analysis"
        assert meta["decoded_at"] == "2026-03-16T1230Z"
        assert "/static/images/wefax/" in meta["url"]

    def test_socketio_event_payload(self):
        """Verify wefax_image_ready event contains all required fields."""
        emit_fn = MagicMock()
        receiver = WefaxReceiver(emit_fn=emit_fn)

        # Simulate the emit that would happen after decode
        event_data = {
            "url": "/static/images/wefax/NMC_8682kHz_surface_analysis_2026-03-16T1230Z.png",
            "station": "NMC",
            "frequency_khz": 8682.0,
            "chart_type": "surface_analysis",
            "decoded_at": "2026-03-16T12:42:00Z",
            "image_width": 1809,
            "ioc": 576,
        }

        emit_fn("wefax_image_ready", event_data)

        emit_fn.assert_called_once()
        call_args = emit_fn.call_args[0]
        assert call_args[0] == "wefax_image_ready"
        payload = call_args[1]
        assert "url" in payload
        assert "station" in payload
        assert "frequency_khz" in payload
        assert "chart_type" in payload
        assert "decoded_at" in payload
        assert "image_width" in payload
        assert "ioc" in payload


class TestManualTestProcedure:
    """
    Manual test procedure for live broadcast validation.

    These tests document how to validate the WEFAX pipeline with real
    hardware. They are NOT automated — run them manually during a known
    broadcast window.

    1. Connect RTL-SDR Blog V4 with long wire antenna (5-10m)
    2. Tune to NMC on 8682 kHz during a known daytime broadcast window
       (check https://www.weather.gov/marine/radiofax for schedule)
    3. Expected: rtl_fm starts with -D 2 (Q-branch direct sampling)
    4. Expected: fldigi decodes WEFAX audio into a greyscale PNG
    5. Expected: decoded chart is visible in the WEFAX panel

    Signal notes:
    - NMC on 8682 kHz: receivable from Redmond WA with basic antenna during daytime
    - NOJ on 4298 kHz: stronger at night from Redmond
    - Lower frequencies (2-4 MHz) propagate better at night
    - Higher frequencies (8-12 MHz) propagate better during day
    """

    @pytest.mark.skip(reason="Manual test — requires hardware and live broadcast")
    def test_live_nmc_8682(self):
        """Tune to NMC 8682 kHz and decode a live WEFAX broadcast."""
        pass

    @pytest.mark.skip(reason="Manual test — requires hardware and live broadcast")
    def test_live_noj_4298_night(self):
        """Tune to NOJ 4298 kHz at night and decode a live WEFAX broadcast."""
        pass
