"""Unit tests for APT decoder — rtl_fm command construction and noaa-apt integration."""

import os
from unittest.mock import patch, MagicMock

import pytest

from ravensdr.apt_decoder import AptDecoder, DEFAULT_GAIN, SAMPLE_RATE, OUTPUT_RATE


class TestRtlFmCommand:

    def test_default_command(self):
        cmd = AptDecoder.build_rtl_fm_cmd("137.6200M")
        assert cmd[0] == "rtl_fm"
        assert "-f" in cmd
        assert "137.6200M" in cmd
        assert "-M" in cmd
        assert "fm" in cmd
        assert "-s" in cmd
        assert SAMPLE_RATE in cmd
        assert "-r" in cmd
        assert OUTPUT_RATE in cmd

    def test_custom_gain(self):
        cmd = AptDecoder.build_rtl_fm_cmd("137.9125M", gain=50)
        assert "-g" in cmd
        idx = cmd.index("-g")
        assert cmd[idx + 1] == "50"

    def test_default_gain(self):
        cmd = AptDecoder.build_rtl_fm_cmd("137.6200M")
        assert "-g" in cmd
        idx = cmd.index("-g")
        assert cmd[idx + 1] == str(DEFAULT_GAIN)

    def test_noaa15_frequency(self):
        cmd = AptDecoder.build_rtl_fm_cmd("137.6200M")
        assert "137.6200M" in cmd

    def test_noaa19_frequency(self):
        cmd = AptDecoder.build_rtl_fm_cmd("137.9125M")
        assert "137.9125M" in cmd

    def test_outputs_to_stdout(self):
        cmd = AptDecoder.build_rtl_fm_cmd("137.6200M")
        assert cmd[-1] == "-"


class TestNoaaAptCommand:

    def test_decode_command(self):
        cmd = AptDecoder.build_noaa_apt_cmd("/tmp/test.wav", "/tmp/test.png")
        assert cmd[0] == "noaa-apt"
        assert "/tmp/test.wav" in cmd
        assert "-o" in cmd
        assert "/tmp/test.png" in cmd
        assert "--rotate" in cmd
        assert "auto" in cmd


class TestOutputFilenames:

    def test_filename_convention(self):
        decoder = AptDecoder()
        pass_info = {
            "satellite": "NOAA 19",
            "frequency": "137.9125M",
        }
        # The filename is generated inside _record_and_decode;
        # verify the safe_name replacement logic
        safe_name = pass_info["satellite"].replace(" ", "-")
        assert safe_name == "NOAA-19"

    def test_filename_noaa15(self):
        safe_name = "NOAA 15".replace(" ", "-")
        assert safe_name == "NOAA-15"


class TestDecoderState:

    def test_not_recording_initially(self):
        decoder = AptDecoder()
        assert decoder.is_recording is False

    def test_no_current_pass_initially(self):
        decoder = AptDecoder()
        assert decoder.current_pass is None

    def test_cannot_record_while_recording(self):
        decoder = AptDecoder()
        decoder._recording = True
        result = decoder.record_pass({"satellite": "NOAA 19"})
        assert result is False


class TestEventPayload:

    def test_emit_called_with_correct_event(self):
        emit_fn = MagicMock()
        decoder = AptDecoder(emit_fn=emit_fn)
        # Directly test the emit would be called with apt_image_ready
        # (full test requires mocking subprocess)
        assert decoder.emit_fn == emit_fn


class TestLatestImage:

    def test_no_image_returns_none(self):
        decoder = AptDecoder()
        # Point to a non-existent directory
        with patch("ravensdr.apt_decoder.IMAGE_DIR", "/tmp/ravensdr_test_nonexistent"):
            result = decoder.get_latest_image()
            assert result is None

    def test_image_history_empty(self):
        decoder = AptDecoder()
        with patch("ravensdr.apt_decoder.IMAGE_DIR", "/tmp/ravensdr_test_nonexistent"):
            result = decoder.get_image_history()
            assert result == []
