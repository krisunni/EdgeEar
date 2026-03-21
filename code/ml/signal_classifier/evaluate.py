#!/usr/bin/env python3
"""Assess signal classifier model performance.

Computes accuracy, per-class metrics, confusion matrix, and SNR vs accuracy.
Supports PyTorch (.pth) and ONNX models.
"""

import argparse
import json
import os
import sys

import numpy as np

TARGET_CLASSES = [
    "AM", "FM", "WFM", "SSB", "P25", "DMR",
    "ADSB", "NOAA_APT", "WEFAX", "CW", "unknown",
]


def run_pytorch_inference(model_path, images, num_classes):
    """Run inference with PyTorch model."""
    import torch
    from torchvision import models
    import torch.nn as nn

    checkpoint = torch.load(model_path, map_location="cpu")
    model = models.mobilenet_v2(weights=None)
    model.classifier[1] = nn.Linear(model.last_channel, num_classes)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.train(False)

    predictions = []
    batch_size = 64
    for i in range(0, len(images), batch_size):
        batch = images[i:i + batch_size].astype(np.float32) / 255.0
        # Replicate to 3 channels
        batch = np.stack([batch, batch, batch], axis=1)
        with torch.no_grad():
            outputs = model(torch.from_numpy(batch))
            preds = outputs.argmax(dim=1).numpy()
            predictions.extend(preds.tolist())

    return np.array(predictions)


def run_onnx_inference(model_path, images, num_classes):
    """Run inference with ONNX model."""
    import onnxruntime as ort

    session = ort.InferenceSession(model_path)
    predictions = []
    batch_size = 64

    for i in range(0, len(images), batch_size):
        batch = images[i:i + batch_size].astype(np.float32) / 255.0
        batch = np.stack([batch, batch, batch], axis=1)
        outputs = session.run(None, {"input": batch})[0]
        preds = outputs.argmax(axis=1)
        predictions.extend(preds.tolist())

    return np.array(predictions)


def compute_metrics(labels, predictions, class_names):
    """Compute per-class precision, recall, F1 and overall accuracy."""
    num_classes = len(class_names)
    metrics = {}

    # Overall accuracy
    correct = np.sum(labels == predictions)
    total = len(labels)
    metrics["overall_accuracy"] = round(correct / total, 4) if total > 0 else 0.0

    # Per-class metrics
    per_class = {}
    for i, name in enumerate(class_names):
        tp = np.sum((predictions == i) & (labels == i))
        fp = np.sum((predictions == i) & (labels != i))
        fn = np.sum((predictions != i) & (labels == i))

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        per_class[name] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": int(np.sum(labels == i)),
        }

    metrics["per_class"] = per_class

    # Confusion matrix
    cm = np.zeros((num_classes, num_classes), dtype=int)
    for true, pred in zip(labels, predictions):
        if true < num_classes and pred < num_classes:
            cm[true][pred] += 1
    metrics["confusion_matrix"] = cm.tolist()

    return metrics


def save_confusion_matrix_png(cm, class_names, output_path):
    """Save confusion matrix as PNG using matplotlib."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(10, 8))
        im = ax.imshow(cm, interpolation="nearest", cmap="Blues")
        ax.figure.colorbar(im, ax=ax)

        ax.set(xticks=np.arange(len(class_names)),
               yticks=np.arange(len(class_names)),
               xticklabels=class_names, yticklabels=class_names,
               title="Confusion Matrix",
               ylabel="True label", xlabel="Predicted label")

        plt.setp(ax.get_xticklabels(), rotation=45, ha="right", rotation_mode="anchor")

        # Add text annotations
        thresh = cm.max() / 2.0
        for i in range(len(class_names)):
            for j in range(len(class_names)):
                ax.text(j, i, format(cm[i][j], "d"),
                        ha="center", va="center",
                        color="white" if cm[i][j] > thresh else "black",
                        fontsize=8)

        fig.tight_layout()
        plt.savefig(output_path, dpi=150)
        plt.close()
        print(f"Confusion matrix saved: {output_path}")
    except ImportError:
        print("WARNING: matplotlib not available — skipping confusion matrix PNG")


def run_assessment(args):
    # Load test data
    print(f"Loading test data from {args.dataset_path}...")
    data = np.load(args.dataset_path)
    test_images = data["test_images"]
    test_labels = data["test_labels"]

    # Load class mapping
    class_map_path = os.path.splitext(args.dataset_path)[0] + "_classes.json"
    if os.path.exists(class_map_path):
        with open(class_map_path) as f:
            class_map = json.load(f)
        class_names = [class_map[str(i)] for i in range(len(class_map))]
    else:
        class_names = TARGET_CLASSES

    num_classes = len(class_names)
    print(f"Test samples: {len(test_images)}, Classes: {num_classes}")

    # Run inference
    model_path = args.model
    if model_path.endswith(".pth"):
        print("Running PyTorch inference...")
        predictions = run_pytorch_inference(model_path, test_images, num_classes)
    elif model_path.endswith(".onnx"):
        print("Running ONNX inference...")
        predictions = run_onnx_inference(model_path, test_images, num_classes)
    else:
        print(f"ERROR: Unsupported model format: {model_path}")
        sys.exit(1)

    # Compute metrics
    metrics = compute_metrics(test_labels, predictions, class_names)

    # Print summary
    print(f"\n{'=' * 60}")
    print(f"Overall Accuracy: {metrics['overall_accuracy']:.4f}")
    print(f"{'=' * 60}")
    print(f"{'Class':<12} {'Precision':>10} {'Recall':>10} {'F1':>10} {'Support':>10}")
    print(f"{'-' * 52}")
    for name in class_names:
        m = metrics["per_class"][name]
        print(f"{name:<12} {m['precision']:>10.4f} {m['recall']:>10.4f} "
              f"{m['f1']:>10.4f} {m['support']:>10}")

    # Save report
    os.makedirs(args.output_dir, exist_ok=True)
    report_path = os.path.join(args.output_dir, "assessment_report.json")
    with open(report_path, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"\nReport saved: {report_path}")

    # Save confusion matrix PNG
    cm = np.array(metrics["confusion_matrix"])
    cm_path = os.path.join(args.output_dir, "confusion_matrix.png")
    save_confusion_matrix_png(cm, class_names, cm_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Assess signal classifier performance")
    parser.add_argument("--model", type=str, required=True,
                        help="Path to model (.pth or .onnx)")
    parser.add_argument("--dataset_path", type=str, required=True,
                        help="Path to dataset .npz file")
    parser.add_argument("--output_dir", type=str, default="reports")
    args = parser.parse_args()
    run_assessment(args)
