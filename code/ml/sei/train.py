#!/usr/bin/env python3
"""Triplet loss training script for SEI 1D CNN embedding model.

Trains a 1D CNN + attention model on raw IQ samples to produce
128-dimensional embedding vectors for emitter fingerprinting.
Uses metric learning (triplet loss) so same-emitter embeddings
cluster together.

Training runs on x86 with GPU recommended, NOT on Raspberry Pi.
"""

import argparse
import os
import sys

import numpy as np

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import Dataset, DataLoader
except ImportError:
    print("ERROR: PyTorch required — pip install torch")
    sys.exit(1)


class SEINet(nn.Module):
    """1D CNN + attention for RF fingerprint embedding."""

    def __init__(self, embedding_dim=128):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv1d(2, 32, kernel_size=7, padding=3),
            nn.BatchNorm1d(32),
            nn.ReLU(),
            nn.Conv1d(32, 64, kernel_size=7, padding=3),
            nn.BatchNorm1d(64),
            nn.ReLU(),
            nn.Conv1d(64, 128, kernel_size=7, padding=3),
            nn.BatchNorm1d(128),
            nn.ReLU(),
            nn.Conv1d(128, 256, kernel_size=7, padding=3),
            nn.BatchNorm1d(256),
            nn.ReLU(),
        )
        # Channel attention (SE block)
        self.attention = nn.Sequential(
            nn.AdaptiveAvgPool1d(1),
            nn.Flatten(),
            nn.Linear(256, 64),
            nn.ReLU(),
            nn.Linear(64, 256),
            nn.Sigmoid(),
        )
        self.pool = nn.AdaptiveAvgPool1d(1)
        self.embed = nn.Sequential(
            nn.Linear(256, 256),
            nn.ReLU(),
            nn.Linear(256, embedding_dim),
        )

    def forward(self, x):
        # x: (batch, 2, 1024)
        h = self.conv(x)
        # Attention
        att = self.attention(h).unsqueeze(2)
        h = h * att
        # Pool and embed
        h = self.pool(h).squeeze(2)
        emb = self.embed(h)
        # L2 normalize
        emb = nn.functional.normalize(emb, p=2, dim=1)
        return emb


class TripletDataset(Dataset):
    """Dataset that yields (anchor, positive, negative) triplets."""

    def __init__(self, data_dir, samples_per_emitter=4):
        self.emitters = {}
        self.emitter_ids = []
        self.samples_per_emitter = samples_per_emitter

        for emitter_id in os.listdir(data_dir):
            emitter_path = os.path.join(data_dir, emitter_id)
            if not os.path.isdir(emitter_path):
                continue
            files = [os.path.join(emitter_path, f)
                     for f in os.listdir(emitter_path) if f.endswith(".npy")]
            if len(files) >= 2:  # need at least 2 samples for anchor+positive
                self.emitters[emitter_id] = files
                self.emitter_ids.append(emitter_id)

        print(f"Loaded {len(self.emitter_ids)} emitters with 2+ samples")

    def __len__(self):
        return sum(len(f) for f in self.emitters.values())

    def __getitem__(self, idx):
        # Random anchor emitter
        rng = np.random.default_rng()
        anc_id = rng.choice(self.emitter_ids)
        files = self.emitters[anc_id]

        # Anchor and positive from same emitter
        anc_idx, pos_idx = rng.choice(len(files), size=2, replace=False)
        anchor = self._load(files[anc_idx])
        positive = self._load(files[pos_idx])

        # Negative from different emitter
        neg_ids = [e for e in self.emitter_ids if e != anc_id]
        neg_id = rng.choice(neg_ids)
        neg_files = self.emitters[neg_id]
        negative = self._load(neg_files[rng.integers(len(neg_files))])

        return anchor, positive, negative

    def _load(self, path):
        iq = np.load(path)
        if np.iscomplexobj(iq):
            i_ch = iq.real.astype(np.float32)
            q_ch = iq.imag.astype(np.float32)
        else:
            # Assume shape (2, N) or (N, 2)
            if iq.ndim == 2 and iq.shape[0] == 2:
                i_ch, q_ch = iq[0].astype(np.float32), iq[1].astype(np.float32)
            else:
                i_ch = iq.astype(np.float32)
                q_ch = np.zeros_like(i_ch)

        # Pad/truncate to 1024
        for arr_name in ['i_ch', 'q_ch']:
            arr = locals()[arr_name]
            if len(arr) < 1024:
                arr = np.pad(arr, (0, 1024 - len(arr)))
            else:
                arr = arr[:1024]
            if arr_name == 'i_ch':
                i_ch = arr
            else:
                q_ch = arr

        return torch.from_numpy(np.stack([i_ch, q_ch], axis=0))


class TripletLoss(nn.Module):
    def __init__(self, margin=0.3):
        super().__init__()
        self.margin = margin

    def forward(self, anchor, positive, negative):
        d_pos = torch.sum((anchor - positive) ** 2, dim=1)
        d_neg = torch.sum((anchor - negative) ** 2, dim=1)
        loss = torch.clamp(d_pos - d_neg + self.margin, min=0.0)
        return loss.mean()


def run_training(args):
    dataset = TripletDataset(args.data_dir)
    if len(dataset.emitter_ids) < 2:
        print("ERROR: Need at least 2 emitters with 2+ samples each")
        sys.exit(1)

    loader = DataLoader(dataset, batch_size=args.batch_size, shuffle=True, num_workers=2)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    model = SEINet(embedding_dim=args.embedding_dim).to(device)
    optimizer = optim.Adam(model.parameters(), lr=args.lr)
    scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=20, gamma=0.5)
    criterion = TripletLoss(margin=args.margin)

    os.makedirs(args.output_dir, exist_ok=True)
    best_loss = float("inf")

    for epoch in range(args.epochs):
        model.train()
        total_loss = 0.0
        n_batches = 0

        for anchor, positive, negative in loader:
            anchor = anchor.to(device)
            positive = positive.to(device)
            negative = negative.to(device)

            anc_emb = model(anchor)
            pos_emb = model(positive)
            neg_emb = model(negative)

            loss = criterion(anc_emb, pos_emb, neg_emb)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            total_loss += loss.item()
            n_batches += 1

        scheduler.step()
        avg_loss = total_loss / max(n_batches, 1)
        lr = optimizer.param_groups[0]["lr"]
        print(f"Epoch {epoch + 1}/{args.epochs} — loss: {avg_loss:.4f}, lr: {lr:.6f}")

        if avg_loss < best_loss:
            best_loss = avg_loss
            path = os.path.join(args.output_dir, "sei_model.pth")
            torch.save({
                "epoch": epoch + 1,
                "model_state_dict": model.state_dict(),
                "embedding_dim": args.embedding_dim,
                "loss": avg_loss,
            }, path)
            print(f"  -> Best model saved (loss: {avg_loss:.4f})")

    print(f"\nTraining complete. Best loss: {best_loss:.4f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train SEI embedding model")
    parser.add_argument("--data_dir", type=str, required=True)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch_size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--margin", type=float, default=0.3)
    parser.add_argument("--embedding_dim", type=int, default=128)
    parser.add_argument("--output_dir", type=str, default="checkpoints")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    run_training(args)
