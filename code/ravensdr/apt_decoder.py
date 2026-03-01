# APT decoder — rtl_fm recording + noaa-apt CLI image decode

import datetime
import glob
import logging
import os
import subprocess
import threading

log = logging.getLogger(__name__)

RAW_DIR = "/tmp/ravensdr/apt"
IMAGE_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "images", "apt")

# Recording parameters
RECORD_DURATION = 900  # 15 minutes
DEFAULT_GAIN = 40
SAMPLE_RATE = "60k"
OUTPUT_RATE = "11025"


class AptDecoder:
    """Records APT satellite passes via rtl_fm and decodes with noaa-apt."""

    def __init__(self, emit_fn=None):
        self.emit_fn = emit_fn or (lambda *a, **kw: None)
        self._recording = False
        self._process = None
        self._thread = None
        self._current_pass = None

    @property
    def is_recording(self):
        return self._recording

    @property
    def current_pass(self):
        return self._current_pass

    def record_pass(self, pass_info, gain=DEFAULT_GAIN):
        """Start recording an APT pass in a background thread."""
        if self._recording:
            log.warning("Already recording a pass — skipping %s", pass_info.get("satellite"))
            return False

        self._current_pass = pass_info
        self._thread = threading.Thread(
            target=self._record_and_decode,
            args=(pass_info, gain),
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self):
        """Stop any active recording."""
        self._recording = False
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
        self._process = None
        self._current_pass = None

    def get_latest_image(self):
        """Return metadata for the most recently decoded APT image."""
        image_dir = os.path.abspath(IMAGE_DIR)
        if not os.path.isdir(image_dir):
            return None

        images = sorted(glob.glob(os.path.join(image_dir, "*.png")), reverse=True)
        if not images:
            return None

        filename = os.path.basename(images[0])
        # Parse filename: NOAA-19_2026-02-28T1430Z.png
        parts = filename.replace(".png", "").split("_", 1)
        satellite = parts[0].replace("-", " ") if parts else "Unknown"
        pass_time = parts[1] if len(parts) > 1 else ""

        return {
            "url": f"/static/images/apt/{filename}",
            "satellite": satellite,
            "pass_time": pass_time,
            "filename": filename,
        }

    def get_image_history(self, count=5):
        """Return metadata for the last N decoded images."""
        image_dir = os.path.abspath(IMAGE_DIR)
        if not os.path.isdir(image_dir):
            return []

        images = sorted(glob.glob(os.path.join(image_dir, "*.png")), reverse=True)
        history = []
        for img_path in images[:count]:
            filename = os.path.basename(img_path)
            parts = filename.replace(".png", "").split("_", 1)
            satellite = parts[0].replace("-", " ") if parts else "Unknown"
            pass_time = parts[1] if len(parts) > 1 else ""
            history.append({
                "url": f"/static/images/apt/{filename}",
                "satellite": satellite,
                "pass_time": pass_time,
                "filename": filename,
            })
        return history

    def _record_and_decode(self, pass_info, gain):
        """Record rtl_fm audio, then decode with noaa-apt."""
        satellite = pass_info.get("satellite", "NOAA-19")
        frequency = pass_info.get("frequency", "137.9125M")
        timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H%MZ")
        safe_name = satellite.replace(" ", "-")

        os.makedirs(RAW_DIR, exist_ok=True)
        os.makedirs(os.path.abspath(IMAGE_DIR), exist_ok=True)

        wav_file = os.path.join(RAW_DIR, f"{safe_name}_{timestamp}.wav")
        png_file = os.path.join(
            os.path.abspath(IMAGE_DIR), f"{safe_name}_{timestamp}.png"
        )

        # Record with rtl_fm piped through sox to create WAV
        self._recording = True
        log.info("APT recording started: %s at %s for %ds",
                 satellite, frequency, RECORD_DURATION)

        try:
            # rtl_fm outputs raw PCM, pipe through sox to make WAV
            rtl_cmd = [
                "rtl_fm",
                "-f", frequency,
                "-M", "fm",
                "-s", SAMPLE_RATE,
                "-r", OUTPUT_RATE,
                "-g", str(gain),
                "-",
            ]

            sox_cmd = [
                "sox",
                "-t", "raw",
                "-r", OUTPUT_RATE,
                "-e", "signed",
                "-b", "16",
                "-c", "1",
                "-",
                wav_file,
            ]

            rtl_proc = subprocess.Popen(
                rtl_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            )
            sox_proc = subprocess.Popen(
                sox_cmd, stdin=rtl_proc.stdout, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            self._process = rtl_proc

            # Wait for recording duration
            try:
                rtl_proc.wait(timeout=RECORD_DURATION)
            except subprocess.TimeoutExpired:
                rtl_proc.terminate()
                rtl_proc.wait(timeout=5)

            sox_proc.wait(timeout=10)

        except FileNotFoundError as e:
            log.error("Recording failed — command not found: %s", e)
            self._recording = False
            self._current_pass = None
            return
        except Exception as e:
            log.error("Recording error: %s", e)
            self._recording = False
            self._current_pass = None
            return
        finally:
            self._process = None

        if not os.path.exists(wav_file):
            log.error("WAV file not created: %s", wav_file)
            self._recording = False
            self._current_pass = None
            return

        log.info("APT recording complete: %s (%.1f MB)",
                 wav_file, os.path.getsize(wav_file) / 1e6)

        # Decode with noaa-apt
        try:
            decode_cmd = [
                "noaa-apt", wav_file,
                "-o", png_file,
                "--rotate", "auto",
            ]
            result = subprocess.run(
                decode_cmd, capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0:
                log.error("noaa-apt decode failed: %s", result.stderr)
                self._recording = False
                self._current_pass = None
                return
        except FileNotFoundError:
            log.error("noaa-apt not found — is it installed?")
            self._recording = False
            self._current_pass = None
            return
        except Exception as e:
            log.error("Decode error: %s", e)
            self._recording = False
            self._current_pass = None
            return

        self._recording = False
        self._current_pass = None

        if not os.path.exists(png_file):
            log.error("Decoded PNG not created: %s", png_file)
            return

        log.info("APT image decoded: %s", png_file)

        # Clean up raw WAV
        try:
            os.remove(wav_file)
            log.info("Cleaned up raw WAV: %s", wav_file)
        except OSError:
            pass

        # Emit event
        self.emit_fn("apt_image_ready", {
            "url": f"/static/images/apt/{safe_name}_{timestamp}.png",
            "satellite": satellite,
            "pass_time": timestamp,
            "max_elevation": pass_info.get("max_elevation", 0),
            "location": f"{pass_info.get('lat', OBSERVER_LAT)}N, {pass_info.get('lon', OBSERVER_LON)}W",
        })

    @staticmethod
    def build_rtl_fm_cmd(frequency, gain=DEFAULT_GAIN):
        """Build the rtl_fm command for APT recording (for testing)."""
        return [
            "rtl_fm",
            "-f", frequency,
            "-M", "fm",
            "-s", SAMPLE_RATE,
            "-r", OUTPUT_RATE,
            "-g", str(gain),
            "-",
        ]

    @staticmethod
    def build_noaa_apt_cmd(wav_file, png_file):
        """Build the noaa-apt decode command (for testing)."""
        return [
            "noaa-apt", wav_file,
            "-o", png_file,
            "--rotate", "auto",
        ]


# Import observer coords for location in events
OBSERVER_LAT = "47.6740"
OBSERVER_LON = "122.1215"
