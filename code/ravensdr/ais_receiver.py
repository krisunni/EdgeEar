# AIS receiver — rtl_ais process manager + NMEA TCP reader

import logging
import os
import socket
import threading
import time

try:
    from eventlet.patcher import original
    subprocess = original("subprocess")
except ImportError:
    import subprocess

try:
    from pyais import decode as pyais_decode
    _HAS_PYAIS = True
except ImportError:
    _HAS_PYAIS = False

log = logging.getLogger(__name__)

AIS_HOST = "localhost"
AIS_PORT = 10110  # rtl_ais TCP output

# How long before a vessel is considered stale (seconds)
VESSEL_TTL = 600  # 10 minutes

# AIS ship type categories
SHIP_TYPES = {
    range(20, 30): "Wing in Ground",
    range(30, 36): "Fishing / Towing / Dredging",
    range(36, 40): "Military / Law Enforcement",
    range(40, 50): "High-Speed Craft",
    range(50, 55): "Pilot / SAR / Tug / Port Tender",
    range(60, 70): "Passenger",
    range(70, 80): "Cargo",
    range(80, 90): "Tanker",
    range(90, 100): "Other",
}


def _ship_type_label(code):
    """Return human-readable ship type from AIS type code."""
    if not code:
        return ""
    try:
        code = int(code)
    except (TypeError, ValueError):
        return ""
    for r, label in SHIP_TYPES.items():
        if code in r:
            return label
    return "Type %d" % code


class AisReceiver:
    """Manages rtl_ais process and reads NMEA TCP stream."""

    def __init__(self, device_index=0, ppm=0):
        self.device_index = device_index
        self.ppm = ppm
        self.process = None
        self._vessels = {}  # mmsi -> vessel dict
        self._poll_thread = None
        self._running = False

    @property
    def is_running(self):
        return self._running

    def start(self):
        """Start rtl_ais subprocess in TCP server mode."""
        if self._running:
            return

        # Kill any lingering rtl_ais
        try:
            subprocess.run(["killall", "-q", "rtl_ais"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        time.sleep(1)

        cmd = [
            "rtl_ais",
            "-T",               # TCP output mode
            "-n",               # disable NMEA checksum check (more tolerant)
            "-d", str(self.device_index),
            "-p", str(self.ppm),
        ]
        try:
            self.process = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except FileNotFoundError:
            log.error("rtl_ais not found — is it installed?")
            return

        # Wait for rtl_ais to start
        time.sleep(3)
        if self.process is None or self.process.poll() is not None:
            rc = self.process.returncode if self.process else "?"
            log.error("rtl_ais exited immediately (code %s)", rc)
            self.process = None
            return

        self._running = True
        self._poll_thread = threading.Thread(target=self._nmea_reader, daemon=True)
        self._poll_thread.start()
        log.info("rtl_ais started on device %d", self.device_index)

    def stop(self):
        """Stop rtl_ais and NMEA reader."""
        self._running = False
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process = None
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=3)
            self._poll_thread = None
        log.info("rtl_ais stopped")

    def _nmea_reader(self):
        """Connect to rtl_ais TCP port and parse NMEA sentences."""
        while self._running:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                sock.connect((AIS_HOST, AIS_PORT))
                log.info("Connected to rtl_ais NMEA stream on port %d", AIS_PORT)
                buf = ""
                while self._running:
                    try:
                        data = sock.recv(4096)
                    except socket.timeout:
                        self._expire_stale()
                        continue
                    if not data:
                        break
                    buf += data.decode("ascii", errors="replace")
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.strip()
                        if line:
                            self._parse_nmea(line)
                    self._expire_stale()
            except (ConnectionRefusedError, OSError) as e:
                if self._running:
                    log.debug("AIS connect failed: %s — retrying in 2s", e)
                    time.sleep(2)
            finally:
                try:
                    sock.close()
                except Exception:
                    pass

    def _parse_nmea(self, line):
        """Parse a single NMEA AIS sentence using pyais."""
        if not _HAS_PYAIS:
            return
        if not line.startswith("!"):
            return
        try:
            msgs = pyais_decode(line)
            for msg in msgs:
                self._update_vessel(msg)
        except Exception as e:
            log.debug("AIS parse error: %s — line: %s", e, line[:80])

    def _update_vessel(self, msg):
        """Update vessel dict from a decoded pyais message."""
        mmsi = str(getattr(msg, "mmsi", ""))
        if not mmsi:
            return

        v = self._vessels.get(mmsi, {"mmsi": mmsi})
        v["seen"] = time.time()

        # Position reports (msg types 1,2,3,18,19)
        lat = getattr(msg, "lat", None)
        lon = getattr(msg, "lon", None)
        if lat is not None and lon is not None:
            # pyais returns 91.0/181.0 for unavailable
            if abs(lat) <= 90 and abs(lon) <= 180:
                v["lat"] = float(lat)
                v["lon"] = float(lon)

        speed = getattr(msg, "speed", None)
        if speed is not None and speed < 102.3:  # 102.3 = not available
            v["speed"] = float(speed)

        course = getattr(msg, "course", None)
        if course is not None and course < 360:
            v["course"] = float(course)

        heading = getattr(msg, "heading", None)
        if heading is not None and heading < 360:
            v["heading"] = float(heading)

        # Static data (msg types 5, 24)
        shipname = getattr(msg, "shipname", None)
        if shipname and shipname.strip():
            v["name"] = shipname.strip()

        ship_type = getattr(msg, "ship_type", None)
        if ship_type:
            v["ship_type"] = int(ship_type)
            v["ship_type_label"] = _ship_type_label(ship_type)

        destination = getattr(msg, "destination", None)
        if destination and destination.strip():
            v["destination"] = destination.strip()

        self._vessels[mmsi] = v

    def _expire_stale(self):
        """Remove vessels not seen for VESSEL_TTL seconds."""
        now = time.time()
        stale = [k for k, v in self._vessels.items()
                 if now - v.get("seen", 0) > VESSEL_TTL]
        for k in stale:
            del self._vessels[k]

    def get_vessels(self):
        """Return current vessel list."""
        return list(self._vessels.values())
