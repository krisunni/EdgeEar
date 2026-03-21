#!/usr/bin/env python3
"""Compile SEI ONNX model to Hailo HEF for HAILO8L.

1D CNN with attention — may require reshaping 1D convolutions to 2D
equivalents for Hailo compatibility. Document any required modifications.

Must run on x86 Ubuntu 22 with Hailo DFC v3.31+ installed.
"""

import argparse
import os
import sys

import numpy as np


def compile_hef(args):
    try:
        from hailo_sdk_client import ClientRunner
    except ImportError:
        print("ERROR: Hailo DFC SDK required — install on x86 Ubuntu 22")
        print("See: https://hailo.ai/developer-zone/")
        sys.exit(1)

    onnx_path = args.onnx_model
    if not os.path.exists(onnx_path):
        print(f"ERROR: ONNX model not found: {onnx_path}")
        sys.exit(1)

    print(f"Loading ONNX model: {onnx_path}")
    print(f"Target: HAILO8L")
    print()
    print("NOTE: 1D convolutions may need reshaping to 2D for Hailo compatibility.")
    print("If compilation fails on Conv1d layers, reshape input from (1, 2, 1024)")
    print("to (1, 2, 1, 1024) and use Conv2d with kernel_size=(1, 7) in the model.")
    print()

    runner = ClientRunner(hw_arch="hailo8l")

    print("Parsing ONNX model...")
    hn, npz = runner.translate_onnx_model(
        onnx_path,
        net_name="sei_model",
        start_node_names=["input"],
        end_node_names=["embedding"],
    )

    # Calibration data
    print("Loading calibration data...")
    if args.calibration_dir and os.path.isdir(args.calibration_dir):
        cal_samples = []
        for emitter_dir in os.listdir(args.calibration_dir):
            edir = os.path.join(args.calibration_dir, emitter_dir)
            if not os.path.isdir(edir):
                continue
            for fname in os.listdir(edir)[:10]:  # 10 per emitter
                if fname.endswith(".npy"):
                    iq = np.load(os.path.join(edir, fname))
                    if np.iscomplexobj(iq):
                        i_ch = iq.real[:1024].astype(np.float32)
                        q_ch = iq.imag[:1024].astype(np.float32)
                    else:
                        i_ch = iq[:1024].astype(np.float32)
                        q_ch = np.zeros(1024, dtype=np.float32)
                    if len(i_ch) < 1024:
                        i_ch = np.pad(i_ch, (0, 1024 - len(i_ch)))
                        q_ch = np.pad(q_ch, (0, 1024 - len(q_ch)))
                    cal_samples.append(np.stack([i_ch, q_ch])[np.newaxis])
            if len(cal_samples) >= 100:
                break
        if cal_samples:
            calib_dataset = np.concatenate(cal_samples[:100], axis=0)
        else:
            calib_dataset = np.random.randn(100, 2, 1024).astype(np.float32)
    else:
        print("WARNING: No calibration data — using random data")
        calib_dataset = np.random.randn(100, 2, 1024).astype(np.float32)

    print("Optimizing for HAILO8L...")
    runner.optimize(calib_dataset)

    os.makedirs(args.output_dir, exist_ok=True)
    hef_path = os.path.join(args.output_dir, "sei_model.hef")

    print("Compiling to HEF...")
    hef = runner.compile()
    with open(hef_path, "wb") as f:
        f.write(hef)

    print(f"\nHEF compiled: {hef_path}")
    print(f"File size: {os.path.getsize(hef_path) / 1024:.1f} KB")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compile SEI model to Hailo HEF")
    parser.add_argument("--onnx_model", type=str, required=True)
    parser.add_argument("--calibration_dir", type=str, help="Directory with labeled IQ data")
    parser.add_argument("--output_dir", type=str, default="exports")
    args = parser.parse_args()
    compile_hef(args)
