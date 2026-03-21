#!/usr/bin/env python3
"""ADS-B-labeled IQ collection script for SEI training data.

Captures raw IQ segments and labels them with ICAO hex codes from
ADS-B decoder output. Aircraft transponders provide ground truth
emitter identity for training the SEI model.

Runs on Raspberry Pi alongside ravenSDR.
"""

import argparse
import datetime
import json
import os
import sys
import time

import numpy as np


def parse_duration(s):
    """Parse duration string like '24h', '30m', '7d' to seconds."""
    s = s.strip().lower()
    if s.endswith("h"):
        return int(s[:-1]) * 3600
    elif s.endswith("m"):
        return int(s[:-1]) * 60
    elif s.endswith("d"):
        return int(s[:-1]) * 86400
    elif s.endswith("s"):
        return int(s[:-1])
    return int(s)


def collect(args):
    duration_sec = parse_duration(args.duration)
    output_dir = args.output_dir
    min_snr = args.min_snr

    os.makedirs(output_dir, exist_ok=True)

    # Metadata log
    meta_path = os.path.join(output_dir, "collection_metadata.jsonl")

    stats = {
        "total_samples": 0,
        "unique_emitters": set(),
        "samples_per_emitter": {},
        "start_time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    print(f"SEI IQ Collection")
    print(f"  Duration: {duration_sec}s")
    print(f"  Output: {output_dir}")
    print(f"  Min SNR: {min_snr} dB")
    print(f"  Waiting for ADS-B decoder data...")

    # In production, this hooks into the running ravenSDR ADS-B decoder
    # and IQ capture pipeline. For now, document the interface.
    try:
        # Try to import ravenSDR components
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from ravensdr.iq_capture import IQCapture
    except ImportError:
        print("NOTE: Run this alongside ravenSDR for live collection.")
        print("      Standalone mode: provide pre-recorded IQ files.")

    start = time.time()
    sample_count = 0

    def on_adsb_iq(iq_samples, icao_hex, frequency_hz, snr_estimate):
        """Callback for each ADS-B-labeled IQ segment."""
        nonlocal sample_count

        if snr_estimate < min_snr:
            return

        # Save IQ segment
        emitter_dir = os.path.join(output_dir, icao_hex)
        os.makedirs(emitter_dir, exist_ok=True)

        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H_%M_%S_%f")
        filename = f"{ts}.npy"
        filepath = os.path.join(emitter_dir, filename)
        np.save(filepath, iq_samples[:1024])  # 1024 samples per window

        # Log metadata
        meta = {
            "icao_hex": icao_hex,
            "timestamp": ts,
            "frequency_hz": frequency_hz,
            "snr_db": round(snr_estimate, 1),
            "sample_count": min(len(iq_samples), 1024),
            "file": filepath,
        }
        with open(meta_path, "a") as f:
            f.write(json.dumps(meta) + "\n")

        sample_count += 1
        stats["unique_emitters"].add(icao_hex)
        stats["samples_per_emitter"][icao_hex] = \
            stats["samples_per_emitter"].get(icao_hex, 0) + 1

        if sample_count % 100 == 0:
            elapsed = time.time() - start
            print(f"  [{elapsed:.0f}s] {sample_count} samples, "
                  f"{len(stats['unique_emitters'])} emitters")

    # Wait for duration (in production, collection runs in background)
    print(f"\nCollection interface ready. Duration: {duration_sec}s")
    print("In production, hook on_adsb_iq callback to ADS-B decoder + IQ capture.")
    print("See ravensdr/adsb_receiver.py for ADS-B integration point.\n")

    # For standalone mode, just wait
    try:
        time.sleep(min(duration_sec, 5))  # cap at 5s in standalone
    except KeyboardInterrupt:
        pass

    # Report
    stats["total_samples"] = sample_count
    stats["end_time"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    stats["unique_emitters"] = len(stats["unique_emitters"])

    print(f"\nCollection complete:")
    print(f"  Total samples: {stats['total_samples']}")
    print(f"  Unique emitters: {stats['unique_emitters']}")

    # Check minimum samples per emitter
    for icao, count in stats.get("samples_per_emitter", {}).items():
        if count < 100:
            print(f"  WARNING: {icao} has only {count} samples (need 100+)")

    # Save stats
    stats_path = os.path.join(output_dir, "collection_stats.json")
    stats["samples_per_emitter"] = dict(stats.get("samples_per_emitter", {}))
    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2)
    print(f"  Stats saved: {stats_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect ADS-B-labeled IQ for SEI training")
    parser.add_argument("--duration", type=str, default="24h",
                        help="Collection duration (e.g., 24h, 30m, 7d)")
    parser.add_argument("--output_dir", type=str, default="data/collected",
                        help="Output directory for labeled IQ segments")
    parser.add_argument("--min_snr", type=float, default=15.0,
                        help="Minimum SNR in dB to save sample")
    args = parser.parse_args()
    collect(args)
