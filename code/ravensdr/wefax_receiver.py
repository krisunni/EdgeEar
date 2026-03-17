# WEFAX receiver — rtl_fm HF direct sampling + fldigi WEFAX decode

import datetime
import glob
import logging
import os
import subprocess
import threading

import numpy as np

log = logging.getLogger(__name__)

RAW_DIR = "/tmp/ravensdr/wefax"
IMAGE_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "images", "wefax")

# WEFAX standard
IOC = 576  # lines per minute (IOC 576 for NMC/NOJ)
IMAGE_WIDTH = 1809  # pixels

# Frequency offset — WEFAX convention: tune 1.9 kHz below listed frequency
FREQ_OFFSET_KHZ = -1.9

# Recording parameters
SAMPLE_RATE = "12k"
OUTPUT_RATE = "11025"


class WefaxReceiver:
    """Records HF WEFAX broadcasts via rtl_fm direct sampling and decodes with fldigi."""

    def __init__(self, emit_fn=None):
        self.emit_fn = emit_fn or (lambda *a, **kw: None)
        self._recording = False
        self._process = None
        self._thread = None
        self._current_broadcast = None

    @property
    def is_recording(self):
        return self._recording

    @property
    def current_broadcast(self):
        return self._current_broadcast

    def record_broadcast(self, broadcast_info):
        """Start recording a WEFAX broadcast in a background thread."""
        if self._recording:
            log.warning("Already recording WEFAX — skipping %s", broadcast_info.get("description"))
            return False

        self._current_broadcast = broadcast_info
        self._thread = threading.Thread(
            target=self._record_and_decode,
            args=(broadcast_info,),
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
        self._current_broadcast = None

    def get_latest_image(self, chart_type=None):
        """Return metadata for the most recently decoded WEFAX chart."""
        image_dir = os.path.abspath(IMAGE_DIR)
        if not os.path.isdir(image_dir):
            return None

        pattern = os.path.join(image_dir, "*.png")
        images = sorted(glob.glob(pattern), reverse=True)

        for img_path in images:
            meta = self._parse_filename(os.path.basename(img_path))
            if chart_type and meta.get("chart_type") != chart_type:
                continue
            return meta

        return None

    def get_image_history(self, count=10, chart_type=None):
        """Return metadata for the last N decoded charts."""
        image_dir = os.path.abspath(IMAGE_DIR)
        if not os.path.isdir(image_dir):
            return []

        images = sorted(glob.glob(os.path.join(image_dir, "*.png")), reverse=True)
        history = []
        for img_path in images:
            meta = self._parse_filename(os.path.basename(img_path))
            if chart_type and meta.get("chart_type") != chart_type:
                continue
            history.append(meta)
            if len(history) >= count:
                break
        return history

    def _record_and_decode(self, broadcast_info):
        """Record rtl_fm audio, then decode WEFAX with fldigi."""
        station = broadcast_info.get("station", "NMC")
        freq_khz = broadcast_info.get("frequency_khz", 8682.0)
        chart_type = broadcast_info.get("chart_type", "surface_analysis")
        duration_min = broadcast_info.get("duration_minutes", 10)
        timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H%MZ")

        os.makedirs(RAW_DIR, exist_ok=True)
        os.makedirs(os.path.abspath(IMAGE_DIR), exist_ok=True)

        basename = f"{station}_{freq_khz:.0f}kHz_{chart_type}_{timestamp}"
        wav_file = os.path.join(RAW_DIR, f"{basename}.wav")
        png_file = os.path.join(os.path.abspath(IMAGE_DIR), f"{basename}.png")

        # Apply frequency offset (tune 1.9 kHz below listed frequency)
        tuned_khz = freq_khz + FREQ_OFFSET_KHZ
        tuned_hz = int(tuned_khz * 1000)

        self._recording = True
        log.info("WEFAX recording: %s %s at %.1f kHz (tuned %.1f kHz) for %d min",
                 station, chart_type, freq_khz, tuned_khz, duration_min)

        duration_sec = duration_min * 60

        try:
            # rtl_fm with HF direct sampling (Q-branch for V4)
            rtl_cmd = self.build_rtl_fm_cmd(tuned_hz)

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
                rtl_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            sox_proc = subprocess.Popen(
                sox_cmd, stdin=rtl_proc.stdout, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            self._process = rtl_proc

            # Log rtl_fm stderr in background (PLL lock, tuner info)
            stderr_thread = threading.Thread(
                target=self._log_rtl_stderr, args=(rtl_proc.stderr,), daemon=True
            )
            stderr_thread.start()

            try:
                rtl_proc.wait(timeout=duration_sec)
            except subprocess.TimeoutExpired:
                rtl_proc.terminate()
                rtl_proc.wait(timeout=5)

            sox_proc.wait(timeout=10)

        except FileNotFoundError as e:
            log.error("WEFAX recording failed — command not found: %s", e)
            self._recording = False
            self._current_broadcast = None
            return
        except Exception as e:
            log.error("WEFAX recording error: %s", e)
            self._recording = False
            self._current_broadcast = None
            return
        finally:
            self._process = None

        if not os.path.exists(wav_file):
            log.error("WEFAX WAV file not created: %s", wav_file)
            self._recording = False
            self._current_broadcast = None
            return

        file_size = os.path.getsize(wav_file)
        log.info("WEFAX recording complete: %s (%.1f MB)",
                 wav_file, file_size / 1e6)

        # Sanity check — if WAV is tiny, rtl_fm likely failed to start
        if file_size < 10000:
            log.error("WEFAX WAV too small (%.0f bytes) — rtl_fm likely failed. "
                      "Check rtl_fm stderr logs above.", file_size)
            self._recording = False
            self._current_broadcast = None
            try:
                os.remove(wav_file)
            except OSError:
                pass
            return

        # Analyze signal level from the recorded WAV
        self._analyze_wav_signal(wav_file, station, freq_khz)

        # Decode with fldigi
        decode_ok = self._decode_wefax(wav_file, png_file)
        self._recording = False
        self._current_broadcast = None

        if not decode_ok:
            return

        # Clean up raw WAV
        try:
            os.remove(wav_file)
            log.info("Cleaned up raw WAV: %s", wav_file)
        except OSError:
            pass

        # Emit event
        filename = os.path.basename(png_file)
        self.emit_fn("wefax_image_ready", {
            "url": f"/static/images/wefax/{filename}",
            "station": station,
            "frequency_khz": freq_khz,
            "chart_type": chart_type,
            "decoded_at": datetime.datetime.utcnow().isoformat() + "Z",
            "image_width": IMAGE_WIDTH,
            "ioc": IOC,
        })
        log.info("WEFAX image decoded: %s", png_file)

    def _decode_wefax(self, wav_file, png_file):
        """Decode WEFAX audio to PNG using fldigi in headless mode."""
        try:
            # Use fldigi with Xvfb for headless WEFAX decoding
            # fldigi --wefax-only decodes WEFAX from audio file to image
            decode_cmd = self.build_fldigi_cmd(wav_file, png_file)

            result = subprocess.run(
                decode_cmd, capture_output=True, text=True, timeout=180
            )
            if result.returncode != 0:
                log.error("fldigi WEFAX decode failed: %s", result.stderr)
                return False

        except FileNotFoundError:
            log.error("fldigi not found — is it installed? (sudo apt install fldigi)")
            return False
        except subprocess.TimeoutExpired:
            log.error("fldigi decode timed out")
            return False
        except Exception as e:
            log.error("WEFAX decode error: %s", e)
            return False

        if not os.path.exists(png_file):
            log.error("Decoded WEFAX PNG not created: %s", png_file)
            return False

        return True

    @staticmethod
    def _log_rtl_stderr(stderr):
        """Log rtl_fm stderr for diagnostics (PLL lock, tuner info)."""
        try:
            for line in stderr:
                msg = line.decode("utf-8", errors="replace").strip()
                if msg:
                    log.info("rtl_fm(wefax): %s", msg)
        except (ValueError, OSError):
            pass

    @staticmethod
    def _analyze_wav_signal(wav_file, station, freq_khz):
        """Analyze the recorded WAV file and log signal quality metrics."""
        try:
            # Read raw PCM from the WAV file (skip 44-byte header)
            with open(wav_file, "rb") as f:
                header = f.read(44)
                # Read first 30 seconds for analysis (11025 Hz * 2 bytes * 30s)
                raw = f.read(11025 * 2 * 30)

            if len(raw) < 1024:
                log.warning("WEFAX signal: WAV too small for analysis (%d bytes)", len(raw))
                return

            samples = np.frombuffer(raw[:len(raw) - len(raw) % 2], dtype=np.int16).astype(np.float64)
            rms = np.sqrt(np.mean(samples ** 2))
            peak = int(np.max(np.abs(samples)))
            if rms > 0:
                rms_db = 20 * np.log10(rms)
            else:
                rms_db = -100.0

            # Estimate signal quality
            if rms > 1000:
                quality = "STRONG"
            elif rms > 500:
                quality = "GOOD"
            elif rms > 100:
                quality = "WEAK"
            else:
                quality = "NO SIGNAL (noise floor only)"

            log.info("WEFAX signal %s %.1f kHz: RMS=%.0f (%.1f dB) peak=%d — %s",
                     station, freq_khz, rms, rms_db, peak, quality)

            if rms < 100:
                log.warning("WEFAX signal too weak — check antenna and frequency. "
                            "Long wire (5-10m) strongly recommended for HF.")

        except Exception as e:
            log.warning("WEFAX signal analysis failed: %s", e)

    @staticmethod
    def build_rtl_fm_cmd(tuned_hz):
        """Build rtl_fm command for WEFAX HF direct sampling.

        Blog fork of rtl_fm uses -E direct2 for Q-branch direct sampling
        (not -D 2 which is the stock rtl-sdr flag). USB demodulation is
        supported via -M usb.
        """
        return [
            "rtl_fm",
            "-E", "direct2",     # Q-branch direct sampling (Blog fork syntax)
            "-f", str(tuned_hz),
            "-M", "usb",         # Upper sideband demodulation
            "-s", SAMPLE_RATE,
            "-r", OUTPUT_RATE,
            "-",
        ]

    @staticmethod
    def build_fldigi_cmd(wav_file, png_file):
        """Build fldigi command for WEFAX decoding."""
        # Run fldigi under Xvfb for headless operation
        return [
            "xvfb-run", "--auto-servernum",
            "fldigi",
            "--wefax-only",
            "-i", wav_file,
            "-o", png_file,
        ]

    @staticmethod
    def _parse_filename(filename):
        """Parse WEFAX filename into metadata dict."""
        # Format: NMC_8682kHz_surface_analysis_2026-03-16T1230Z.png
        name = filename.replace(".png", "")
        parts = name.split("_", 2)  # station, freq, rest

        station = parts[0] if len(parts) > 0 else "Unknown"
        freq_str = parts[1] if len(parts) > 1 else ""
        rest = parts[2] if len(parts) > 2 else ""

        # Parse frequency
        freq_khz = 0.0
        if freq_str.endswith("kHz"):
            try:
                freq_khz = float(freq_str.replace("kHz", ""))
            except ValueError:
                pass

        # Split rest into chart_type and timestamp
        # chart_type may contain underscores, timestamp is the last part
        if rest:
            # Timestamp is always the last segment after the last underscore
            # Format: ...chart_type_2026-03-16T1230Z
            last_under = rest.rfind("_")
            if last_under > 0:
                chart_type = rest[:last_under]
                decoded_at = rest[last_under + 1:]
            else:
                chart_type = rest
                decoded_at = ""
        else:
            chart_type = ""
            decoded_at = ""

        return {
            "url": f"/static/images/wefax/{filename}",
            "station": station,
            "frequency_khz": freq_khz,
            "chart_type": chart_type,
            "decoded_at": decoded_at,
            "filename": filename,
        }
