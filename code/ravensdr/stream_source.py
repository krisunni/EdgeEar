# Web stream ingest via ffmpeg (Mode B)

import logging
import subprocess
import threading

log = logging.getLogger(__name__)


class StreamSource:
    """Ingests a web audio stream via ffmpeg, outputs raw 16kHz mono PCM."""

    def __init__(self, pcm_queue, audio_queue):
        self.pcm_queue = pcm_queue      # -> transcriber
        self.audio_queue = audio_queue   # -> audio router
        self.current_url = None
        self.is_running = False
        self._process = None
        self._thread = None
        self._stop_event = threading.Event()
        self._retries = 0
        self.MAX_RETRIES = 3

    def connect(self, stream_url):
        self.stop()
        self.current_url = stream_url
        self._stop_event.clear()
        self._retries = 0
        self._start_ffmpeg()

    def _start_ffmpeg(self):
        cmd = [
            "ffmpeg",
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5",
            "-i", self.current_url,
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            "-f", "s16le",
            "pipe:1",
        ]

        log.info("Starting ffmpeg: %s", self.current_url)
        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError:
            log.error("ffmpeg not found — is it installed?")
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
                try:
                    self._process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    log.warning("ffmpeg process did not exit after kill")
            log.info("ffmpeg stopped")
        self._process = None
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None
        self.is_running = False
        self._drain_queues()

    def poll(self):
        """Check if ffmpeg process is still alive. Returns False if crashed."""
        if self._process and self._process.poll() is not None:
            self.is_running = False
            return False
        return True

    def _kill_process(self):
        """Kill current ffmpeg process without touching threads or queues."""
        if self._process and self._process.poll() is None:
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
                try:
                    self._process.wait(timeout=2)
                except Exception:
                    pass
        self._process = None

    def _read_loop(self):
        import time
        while not self._stop_event.is_set():
            try:
                chunk = self._process.stdout.read(4096)
                if not chunk:
                    if self._stop_event.is_set():
                        break
                    self._retries += 1
                    if self._retries <= self.MAX_RETRIES:
                        log.warning("Stream dropped, retrying (%d/%d)...",
                                    self._retries, self.MAX_RETRIES)
                        self._kill_process()
                        time.sleep(1)
                        if self._stop_event.is_set():
                            break
                        self._restart_ffmpeg()
                        continue
                    else:
                        log.error("Stream failed after %d retries", self.MAX_RETRIES)
                        break
                self._retries = 0
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
                if not self._stop_event.is_set():
                    log.debug("Pipe error in read loop")
                break
        self.is_running = False

    def _restart_ffmpeg(self):
        """Restart ffmpeg process in-place (same thread, no new thread)."""
        cmd = [
            "ffmpeg",
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5",
            "-i", self.current_url,
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            "-f", "s16le",
            "pipe:1",
        ]
        log.info("Restarting ffmpeg: %s", self.current_url)
        try:
            self._process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
        except FileNotFoundError:
            log.error("ffmpeg not found during restart")
            self.is_running = False

    def _drain_queues(self):
        for q in (self.pcm_queue, self.audio_queue):
            while not q.empty():
                try:
                    q.get_nowait()
                except Exception:
                    break
