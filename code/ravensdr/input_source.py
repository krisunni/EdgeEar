# InputSource abstraction — SDR or web stream

import logging
import queue
import subprocess

from ravensdr.tuner import Tuner
from ravensdr.stream_source import StreamSource

log = logging.getLogger(__name__)


def detect_sdr():
    """Check if an RTL-SDR device is connected."""
    try:
        result = subprocess.run(
            ["rtl_test", "-t"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


class InputSource:
    """Unified abstraction over Tuner (SDR) and StreamSource (web stream)."""

    def __init__(self, mode):
        self.mode = mode  # "SDR" or "WEBSTREAM"
        self.pcm_queue = queue.Queue(maxsize=200)
        self.audio_queue = queue.Queue(maxsize=200)
        self.current_preset = None
        self.sdr_connected = (mode == "SDR")
        self._error_callback = None

        if mode == "SDR":
            self._source = Tuner(self.pcm_queue, self.audio_queue)
        else:
            self._source = StreamSource(self.pcm_queue, self.audio_queue)

    def set_error_callback(self, callback):
        """Set callback for error/recovery notifications: callback(event, data)."""
        self._error_callback = callback

    def tune(self, preset):
        """Tune to a preset. Uses stream_url in WEBSTREAM mode, freq in SDR mode."""
        self.current_preset = preset
        if self.mode == "WEBSTREAM":
            stream_url = preset.get("stream_url")
            if not stream_url:
                log.error("Preset '%s' has no stream_url for web stream mode",
                          preset.get("label"))
                return False
            self._source.connect(stream_url)
        else:
            self._source.tune(preset["freq"], preset.get("mode", "fm"))
        return True

    def stop(self):
        self._source.stop()
        self.current_preset = None

    @property
    def is_running(self):
        return self._source.is_running

    def poll(self):
        return self._source.poll()

    def check_sdr_connected(self):
        """Check if SDR hardware is still plugged in. Returns True/False."""
        was_connected = self.sdr_connected
        self.sdr_connected = detect_sdr()

        if was_connected and not self.sdr_connected:
            log.warning("SDR disconnected")
            if self._error_callback:
                self._error_callback("sdr_disconnected", {
                    "message": "SDR dongle disconnected. Plug it back in to auto-recover."
                })

        elif not was_connected and self.sdr_connected:
            log.info("SDR reconnected")
            if self._error_callback:
                self._error_callback("sdr_reconnected", {
                    "message": "SDR dongle reconnected."
                })

        return self.sdr_connected

    def restart(self):
        """Restart the current source (retry after crash)."""
        if not self.current_preset:
            log.warning("Cannot restart — no preset selected")
            return False
        preset = self.current_preset
        self._source.stop()
        return self.tune(preset)

    def set_squelch(self, level):
        if self.mode == "SDR":
            self._source.set_squelch(level)

    def set_gain(self, value):
        if self.mode == "SDR":
            self._source.set_gain(value)

    @property
    def squelch(self):
        if self.mode == "SDR":
            return self._source.squelch
        return 0

    @property
    def gain(self):
        if self.mode == "SDR":
            return self._source.gain
        return "N/A"
