# Unit tests for WEFAX receiver

import os
from unittest.mock import MagicMock, patch

import pytest

from ravensdr.wefax_receiver import (
    FREQ_OFFSET_KHZ,
    IMAGE_WIDTH,
    IOC,
    OUTPUT_RATE,
    SAMPLE_RATE,
    WefaxReceiver,
)


class TestRtlFmCommand:
    """Test rtl_fm command construction for WEFAX HF direct sampling."""

    def test_direct_sampling_flag(self):
        cmd = WefaxReceiver.build_rtl_fm_cmd(8680100)
        assert "-E" in cmd
        idx = cmd.index("-E")
        assert cmd[idx + 1] == "direct2"  # Q-branch (Blog fork syntax)

    def test_usb_demodulation(self):
        cmd = WefaxReceiver.build_rtl_fm_cmd(8680100)
        assert "-M" in cmd
        idx = cmd.index("-M")
        assert cmd[idx + 1] == "usb"

    def test_sample_rate(self):
        cmd = WefaxReceiver.build_rtl_fm_cmd(8680100)
        assert "-s" in cmd
        idx = cmd.index("-s")
        assert cmd[idx + 1] == SAMPLE_RATE

    def test_output_rate(self):
        cmd = WefaxReceiver.build_rtl_fm_cmd(8680100)
        assert "-r" in cmd
        idx = cmd.index("-r")
        assert cmd[idx + 1] == OUTPUT_RATE

    def test_frequency_in_hz(self):
        cmd = WefaxReceiver.build_rtl_fm_cmd(8680100)
        assert "-f" in cmd
        idx = cmd.index("-f")
        assert cmd[idx + 1] == "8680100"

    def test_pipe_output(self):
        cmd = WefaxReceiver.build_rtl_fm_cmd(8680100)
        assert cmd[-1] == "-"


class TestFrequencyOffset:
    """Test WEFAX frequency offset calculation."""

    def test_offset_value(self):
        assert FREQ_OFFSET_KHZ == -1.9

    def test_nmc_8682_offset(self):
        listed_khz = 8682.0
        tuned_khz = listed_khz + FREQ_OFFSET_KHZ
        assert tuned_khz == pytest.approx(8680.1)

    def test_nmc_4346_offset(self):
        listed_khz = 4346.0
        tuned_khz = listed_khz + FREQ_OFFSET_KHZ
        assert tuned_khz == pytest.approx(4344.1)

    def test_noj_4298_offset(self):
        listed_khz = 4298.0
        tuned_khz = listed_khz + FREQ_OFFSET_KHZ
        assert tuned_khz == pytest.approx(4296.1)


class TestFldigiCommand:
    """Test fldigi decode command construction."""

    def test_fldigi_cmd_includes_xvfb(self):
        cmd = WefaxReceiver.build_fldigi_cmd("/tmp/test.wav", "/tmp/test.png")
        assert cmd[0] == "xvfb-run"
        assert "--auto-servernum" in cmd

    def test_fldigi_cmd_includes_wefax_flag(self):
        cmd = WefaxReceiver.build_fldigi_cmd("/tmp/test.wav", "/tmp/test.png")
        assert "--wefax-only" in cmd

    def test_fldigi_cmd_includes_input_file(self):
        cmd = WefaxReceiver.build_fldigi_cmd("/tmp/test.wav", "/tmp/test.png")
        assert "-i" in cmd
        idx = cmd.index("-i")
        assert cmd[idx + 1] == "/tmp/test.wav"

    def test_fldigi_cmd_includes_output_file(self):
        cmd = WefaxReceiver.build_fldigi_cmd("/tmp/test.wav", "/tmp/test.png")
        assert "-o" in cmd
        idx = cmd.index("-o")
        assert cmd[idx + 1] == "/tmp/test.png"


class TestFilenameGeneration:
    """Test WEFAX output filename convention."""

    def test_parse_surface_analysis_filename(self):
        filename = "NMC_8682kHz_surface_analysis_2026-03-16T1230Z.png"
        meta = WefaxReceiver._parse_filename(filename)
        assert meta["station"] == "NMC"
        assert meta["frequency_khz"] == 8682.0
        assert meta["chart_type"] == "surface_analysis"
        assert meta["decoded_at"] == "2026-03-16T1230Z"
        assert meta["url"] == f"/static/images/wefax/{filename}"

    def test_parse_24hr_forecast_filename(self):
        filename = "NMC_8682kHz_24hr_forecast_2026-03-16T1300Z.png"
        meta = WefaxReceiver._parse_filename(filename)
        assert meta["station"] == "NMC"
        assert meta["chart_type"] == "24hr_forecast"

    def test_parse_wave_chart_filename(self):
        filename = "NOJ_4298kHz_wave_chart_2026-03-16T0300Z.png"
        meta = WefaxReceiver._parse_filename(filename)
        assert meta["station"] == "NOJ"
        assert meta["frequency_khz"] == 4298.0
        assert meta["chart_type"] == "wave_chart"

    def test_parse_48hr_forecast_filename(self):
        filename = "NMC_12786kHz_48hr_forecast_2026-03-16T1700Z.png"
        meta = WefaxReceiver._parse_filename(filename)
        assert meta["chart_type"] == "48hr_forecast"
        assert meta["frequency_khz"] == 12786.0


class TestWefaxReceiverState:
    """Test receiver state management."""

    def test_initial_state(self):
        receiver = WefaxReceiver()
        assert receiver.is_recording is False
        assert receiver.current_broadcast is None

    def test_stop_when_not_recording(self):
        receiver = WefaxReceiver()
        receiver.stop()  # should not raise
        assert receiver.is_recording is False

    def test_emit_fn_called_on_image_ready(self):
        emit_fn = MagicMock()
        receiver = WefaxReceiver(emit_fn=emit_fn)

        # Verify emit_fn is stored
        assert receiver.emit_fn is emit_fn


class TestConstants:
    """Test WEFAX constants."""

    def test_ioc(self):
        assert IOC == 576

    def test_image_width(self):
        assert IMAGE_WIDTH == 1809
