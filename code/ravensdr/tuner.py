# RTL-FM process manager (Mode A)

import logging
import subprocess
import threading
import time

log = logging.getLogger(__name__)


class Tuner:
    """Manages an rtl_fm subprocess for SDR reception."""

    def __init__(self, pcm_queue, audio_queue):
        self.pcm_queue = pcm_queue      # -> transcriber
        self.audio_queue = audio_queue   # -> audio router
        self.current_freq = None
        self.current_mode = "fm"
        self.squelch = 0
        self.gain = "auto"
        self.is_running = False
        self._process = None
        self._thread = None
        self._stop_event = threading.Event()

    def tune(self, freq, mode="fm"):
        self.stop()
        self.current_freq = freq
        self.current_mode = mode
        self._stop_event.clear()

        gain_arg = [] if self.gain == "auto" else ["-g", str(self.gain)]
        cmd = [
            "rtl_fm",
            "-f", freq,
            "-M", mode,
            "-s", "200k",
            "-r", "16k",
            "-l", str(self.squelch),
        ] + gain_arg + ["-"]

        log.info("Starting rtl_fm: %s", " ".join(cmd))
        try:
            self._process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
        except FileNotFoundError:
            log.error("rtl_fm not found — is rtl-sdr installed?")
            raise

        self.is_running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._process and self._process.poll() is None:
            # Close pipes first to unblock the read loop
            for pipe in (self._process.stdout, self._process.stderr):
                try:
                    pipe.close()
                except Exception:
                    pass
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
            log.info("rtl_fm stopped")
        self._process = None
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None
        self.is_running = False
        self._drain_queues()

    def set_squelch(self, level):
        self.squelch = max(0, min(100, level))
        if self.is_running:
            self.tune(self.current_freq, self.current_mode)

    def set_gain(self, value):
        self.gain = value
        if self.is_running:
            self.tune(self.current_freq, self.current_mode)

    def poll(self):
        """Check if rtl_fm process is still alive. Returns False if crashed."""
        if self._process and self._process.poll() is not None:
            self.is_running = False
            return False
        return True

    def _read_loop(self):
        try:
            while not self._stop_event.is_set():
                chunk = self._process.stdout.read(4096)
                if not chunk:
                    break
                try:
                    self.pcm_queue.put(chunk, timeout=0.5)
                except Exception:
                    pass
                try:
                    self.audio_queue.put(chunk, timeout=0.5)
                except Exception:
                    pass
        except (ValueError, OSError):
            # Pipe closed during shutdown — expected
            pass
        self.is_running = False

    def _drain_queues(self):
        for q in (self.pcm_queue, self.audio_queue):
            while not q.empty():
                try:
                    q.get_nowait()
                except Exception:
                    break
