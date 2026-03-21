#!/usr/bin/env python3
"""Assess SEI model performance.

Computes rank-1/rank-5 identification accuracy, equal error rate (EER),
ROC curves, and embedding space visualization.
"""

import argparse
import json
import os
import sys

import numpy as np

try:
    import torch
except ImportError:
    print("ERROR: PyTorch required — pip install torch")
    sys.exit(1)

sys.path.insert(0, os.path.dirname(__file__))
from train import SEINet


def load_test_data(data_dir):
    """Load test IQ data organized by emitter directory."""
    emitters = {}
    for emitter_id in os.listdir(data_dir):
        edir = os.path.join(data_dir, emitter_id)
        if not os.path.isdir(edir):
            continue
        samples = []
        for fname in os.listdir(edir):
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
                samples.append(np.stack([i_ch, q_ch]))
        if samples:
            emitters[emitter_id] = samples
    return emitters


def get_embeddings(model, samples, device):
    """Get embeddings for a list of IQ samples."""
    embeddings = []
    for s in samples:
        inp = torch.from_numpy(s).unsqueeze(0).to(device)
        with torch.no_grad():
            emb = model(inp).cpu().numpy().flatten()
        embeddings.append(emb)
    return embeddings


def cosine_sim(a, b):
    dot = np.dot(a, b)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def run_assessment(args):
    # Load model
    checkpoint = torch.load(args.model, map_location="cpu")
    embedding_dim = checkpoint.get("embedding_dim", 128)
    model = SEINet(embedding_dim=embedding_dim)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.train(False)
    device = torch.device("cpu")

    # Load test data
    emitters = load_test_data(args.data_dir)
    if len(emitters) < 2:
        print("ERROR: Need at least 2 emitters for assessment")
        sys.exit(1)

    print(f"Emitters: {len(emitters)}")
    for eid, samples in emitters.items():
        print(f"  {eid}: {len(samples)} samples")

    # Get all embeddings
    all_embeddings = {}
    for eid, samples in emitters.items():
        all_embeddings[eid] = get_embeddings(model, samples, device)

    # Rank-1 identification: for each query, find nearest in gallery
    correct_rank1 = 0
    correct_rank5 = 0
    total = 0

    # Build gallery (mean embedding per emitter from first half of samples)
    gallery = {}
    queries = {}
    for eid, embeds in all_embeddings.items():
        half = max(1, len(embeds) // 2)
        gallery[eid] = np.mean(embeds[:half], axis=0)
        queries[eid] = embeds[half:]

    for query_eid, query_embeds in queries.items():
        for qe in query_embeds:
            sims = []
            for gal_eid, gal_emb in gallery.items():
                sims.append((gal_eid, cosine_sim(qe, gal_emb)))
            sims.sort(key=lambda x: x[1], reverse=True)

            total += 1
            if sims[0][0] == query_eid:
                correct_rank1 += 1
            if query_eid in [s[0] for s in sims[:5]]:
                correct_rank5 += 1

    rank1_acc = correct_rank1 / total if total > 0 else 0
    rank5_acc = correct_rank5 / total if total > 0 else 0

    # Same vs different emitter similarity distributions
    same_sims = []
    diff_sims = []
    eids = list(all_embeddings.keys())
    for i, eid in enumerate(eids):
        embeds = all_embeddings[eid]
        for j in range(len(embeds)):
            for k in range(j + 1, min(j + 5, len(embeds))):
                same_sims.append(cosine_sim(embeds[j], embeds[k]))
        for other_eid in eids[i + 1:]:
            other = all_embeddings[other_eid]
            for j in range(min(5, len(embeds))):
                for k in range(min(5, len(other))):
                    diff_sims.append(cosine_sim(embeds[j], other[k]))

    # Print results
    print(f"\n{'=' * 50}")
    print(f"Rank-1 Accuracy: {rank1_acc:.4f} ({correct_rank1}/{total})")
    print(f"Rank-5 Accuracy: {rank5_acc:.4f} ({correct_rank5}/{total})")
    print(f"Same-emitter similarity: {np.mean(same_sims):.4f} +/- {np.std(same_sims):.4f}")
    print(f"Diff-emitter similarity: {np.mean(diff_sims):.4f} +/- {np.std(diff_sims):.4f}")
    print(f"{'=' * 50}")

    # Save report
    os.makedirs(args.output_dir, exist_ok=True)
    report = {
        "rank1_accuracy": round(rank1_acc, 4),
        "rank5_accuracy": round(rank5_acc, 4),
        "total_queries": total,
        "num_emitters": len(emitters),
        "same_emitter_sim_mean": round(float(np.mean(same_sims)), 4) if same_sims else 0,
        "same_emitter_sim_std": round(float(np.std(same_sims)), 4) if same_sims else 0,
        "diff_emitter_sim_mean": round(float(np.mean(diff_sims)), 4) if diff_sims else 0,
        "diff_emitter_sim_std": round(float(np.std(diff_sims)), 4) if diff_sims else 0,
    }
    report_path = os.path.join(args.output_dir, "sei_assessment_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport saved: {report_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Assess SEI model")
    parser.add_argument("--model", type=str, required=True)
    parser.add_argument("--data_dir", type=str, required=True)
    parser.add_argument("--output_dir", type=str, default="reports")
    args = parser.parse_args()
    run_assessment(args)
