# RTL-FM process manager (Mode A)

import logging
import os
import signal as _signal
import time

# Use REAL stdlib modules, not eventlet's green versions.
# Eventlet's patched subprocess/threading cause fd conflicts and broken wait().
try:
    from eventlet.patcher import original
    subprocess = original("subprocess")
    threading = original("threading")
except ImportError:
    import subprocess
    import threading

log = logging.getLogger(__name__)


def _kill_pid(pid):
    """Kill a process by PID using raw os calls (bypasses eventlet)."""
    try:
        os.kill(pid, _signal.SIGTERM)
    except OSError:
        return
    # Give it 2 seconds to exit
    for _ in range(20):
        try:
            result = os.waitpid(pid, os.WNOHANG)
            if result[0] != 0:
                return  # exited
        except ChildProcessError:
            return  # already reaped
        time.sleep(0.1)
    # Still alive — SIGKILL
    try:
        os.kill(pid, _signal.SIGKILL)
        os.waitpid(pid, 0)
    except OSError:
        pass


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
        self._pid = None
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
            self._pid = self._process.pid
        except FileNotFoundError:
            log.error("rtl_fm not found — is rtl-sdr installed?")
            raise

        self.is_running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        self._stderr_thread = threading.Thread(target=self._log_stderr, daemon=True)
        self._stderr_thread.start()

    def stop(self):
        self._stop_event.set()
        pid = self._pid
        if pid:
            # Close pipes first to unblock the read loop
            if self._process:
                for pipe in (self._process.stdout, self._process.stderr):
                    try:
                        pipe.close()
                    except Exception:
                        pass
            # Kill using raw OS calls — eventlet's subprocess.wait() is broken
            _kill_pid(pid)
            log.info("rtl_fm stopped (pid %d)", pid)
        self._process = None
        self._pid = None
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
            stdout = self._process.stdout
            while not self._stop_event.is_set():
                chunk = stdout.read(4096)
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

    def _log_stderr(self):
        """Log rtl_fm stderr output for diagnostics."""
        try:
            for line in self._process.stderr:
                msg = line.decode("utf-8", errors="replace").strip()
                if msg:
                    log.debug("rtl_fm: %s", msg)
        except (ValueError, OSError):
            pass

    def _drain_queues(self):
        for q in (self.pcm_queue, self.audio_queue):
            while not q.empty():
                try:
                    q.get_nowait()
                except Exception:
                    break
