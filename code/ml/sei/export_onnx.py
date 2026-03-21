#!/usr/bin/env python3
"""Export trained SEI PyTorch model to ONNX format.

Exports with fixed input shape (1, 2, 1024) float32, opset 13
for Hailo DFC v3.x compatibility.
"""

import argparse
import os
import sys

import numpy as np

try:
    import torch
    import torch.nn as nn
except ImportError:
    print("ERROR: PyTorch required — pip install torch")
    sys.exit(1)

# Import model architecture
sys.path.insert(0, os.path.dirname(__file__))
from train import SEINet


def run_export(args):
    print(f"Loading checkpoint from {args.checkpoint}...")
    checkpoint = torch.load(args.checkpoint, map_location="cpu")
    embedding_dim = checkpoint.get("embedding_dim", 128)

    model = SEINet(embedding_dim=embedding_dim)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.train(False)

    dummy_input = torch.randn(1, 2, 1024)
    os.makedirs(args.output_dir, exist_ok=True)
    onnx_path = os.path.join(args.output_dir, "sei_model.onnx")

    print(f"Exporting to ONNX (opset {args.opset})...")
    torch.onnx.export(
        model, dummy_input, onnx_path,
        opset_version=args.opset,
        input_names=["input"],
        output_names=["embedding"],
        dynamic_axes=None,
    )

    # Verify
    try:
        import onnx
        import onnxruntime as ort

        onnx_model = onnx.load(onnx_path)
        onnx.checker.check_model(onnx_model)

        test_input = np.random.randn(1, 2, 1024).astype(np.float32)
        with torch.no_grad():
            pt_out = model(torch.from_numpy(test_input)).numpy()
        session = ort.InferenceSession(onnx_path)
        onnx_out = session.run(None, {"input": test_input})[0]
        diff = np.max(np.abs(pt_out - onnx_out))
        print(f"Max diff PyTorch vs ONNX: {diff:.2e}")
        if diff > 1e-5:
            print(f"WARNING: exceeds tolerance 1e-5")
        else:
            print("Verification passed")
    except ImportError:
        print("onnx/onnxruntime not installed — skipping verification")

    print(f"\nONNX model saved: {onnx_path}")
    print(f"Input: (1, 2, 1024) float32")
    print(f"Output: (1, {embedding_dim}) float32")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export SEI model to ONNX")
    parser.add_argument("--checkpoint", type=str, required=True)
    parser.add_argument("--output_dir", type=str, default="exports")
    parser.add_argument("--opset", type=int, default=13)
    args = parser.parse_args()
    run_export(args)
