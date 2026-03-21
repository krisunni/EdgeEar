#!/usr/bin/env python3
"""PyTorch training script for MobileNetV2 signal classifier.

Fine-tunes MobileNetV2 (ImageNet pretrained) on RadioML spectrograms
with differential learning rates and cosine annealing.

Training pipeline runs on x86 with GPU recommended, NOT on Raspberry Pi.
"""

import argparse
import json
import os
import sys

import numpy as np

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import Dataset, DataLoader
    from torchvision import models
except ImportError:
    print("ERROR: PyTorch required — pip install torch torchvision")
    sys.exit(1)


class SpectrogramDataset(Dataset):
    """PyTorch dataset for spectrogram images."""

    def __init__(self, images, labels):
        self.images = images  # (N, 224, 224) uint8
        self.labels = labels  # (N,) int64

    def __len__(self):
        return len(self.images)

    def __getitem__(self, idx):
        img = self.images[idx].astype(np.float32) / 255.0
        # Replicate single channel to 3 channels (ImageNet pretrained expects RGB)
        img = np.stack([img, img, img], axis=0)
        return torch.from_numpy(img), torch.tensor(self.labels[idx], dtype=torch.long)


def build_model(num_classes):
    """Create MobileNetV2 with custom classifier head."""
    model = models.mobilenet_v2(weights=models.MobileNet_V2_Weights.IMAGENET1K_V1)
    # Replace classifier
    model.classifier[1] = nn.Linear(model.last_channel, num_classes)
    return model


def run_training(args):
    # Load dataset
    print(f"Loading dataset from {args.dataset_path}...")
    data = np.load(args.dataset_path)
    train_ds = SpectrogramDataset(data["train_images"], data["train_labels"])
    val_ds = SpectrogramDataset(data["val_images"], data["val_labels"])

    # Load class mapping
    class_map_path = os.path.splitext(args.dataset_path)[0] + "_classes.json"
    if os.path.exists(class_map_path):
        with open(class_map_path) as f:
            class_map = json.load(f)
        num_classes = len(class_map)
    else:
        num_classes = int(data["train_labels"].max()) + 1

    print(f"Train: {len(train_ds)}, Val: {len(val_ds)}, Classes: {num_classes}")

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True,
                              num_workers=4, pin_memory=True)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False,
                            num_workers=4, pin_memory=True)

    # Device
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    # Model
    model = build_model(num_classes).to(device)

    # Differential learning rates: pretrained layers get lower lr
    pretrained_params = []
    new_params = []
    for name, param in model.named_parameters():
        if "classifier" in name:
            new_params.append(param)
        else:
            pretrained_params.append(param)

    optimizer = optim.Adam([
        {"params": pretrained_params, "lr": args.lr * 0.01},  # 1e-5 for pretrained
        {"params": new_params, "lr": args.lr},                 # 1e-3 for new layers
    ])

    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)
    criterion = nn.CrossEntropyLoss()

    # Training loop
    best_val_acc = 0.0
    patience_counter = 0
    os.makedirs(args.output_dir, exist_ok=True)

    for epoch in range(args.epochs):
        # Train
        model.train()
        train_loss = 0.0
        train_correct = 0
        train_total = 0

        for images, labels in train_loader:
            images, labels = images.to(device), labels.to(device)
            optimizer.zero_grad()
            outputs = model(images)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()

            train_loss += loss.item() * images.size(0)
            _, predicted = outputs.max(1)
            train_total += labels.size(0)
            train_correct += predicted.eq(labels).sum().item()

        scheduler.step()

        train_loss /= train_total
        train_acc = train_correct / train_total

        # Validate
        model.set_mode_inference = False  # workaround: just use model.eval()
        model_was_training = model.training
        model.train(False)
        val_loss = 0.0
        val_correct = 0
        val_total = 0

        with torch.no_grad():
            for images, labels in val_loader:
                images, labels = images.to(device), labels.to(device)
                outputs = model(images)
                loss = criterion(outputs, labels)

                val_loss += loss.item() * images.size(0)
                _, predicted = outputs.max(1)
                val_total += labels.size(0)
                val_correct += predicted.eq(labels).sum().item()

        val_loss /= val_total
        val_acc = val_correct / val_total

        lr = optimizer.param_groups[1]["lr"]
        print(f"Epoch {epoch + 1}/{args.epochs} — "
              f"train_loss: {train_loss:.4f}, train_acc: {train_acc:.4f}, "
              f"val_loss: {val_loss:.4f}, val_acc: {val_acc:.4f}, lr: {lr:.6f}")

        # Save best model
        if val_acc > best_val_acc:
            best_val_acc = val_acc
            patience_counter = 0
            checkpoint_path = os.path.join(args.output_dir, "best_model.pth")
            torch.save({
                "epoch": epoch + 1,
                "model_state_dict": model.state_dict(),
                "optimizer_state_dict": optimizer.state_dict(),
                "val_acc": val_acc,
                "num_classes": num_classes,
            }, checkpoint_path)
            print(f"  -> Best model saved (val_acc: {val_acc:.4f})")
        else:
            patience_counter += 1
            if patience_counter >= args.patience:
                print(f"Early stopping at epoch {epoch + 1} (patience {args.patience})")
                break

    print(f"\nTraining complete. Best val accuracy: {best_val_acc:.4f}")
    print(f"Model saved to: {os.path.join(args.output_dir, 'best_model.pth')}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train MobileNetV2 signal classifier")
    parser.add_argument("--dataset_path", type=str, required=True,
                        help="Path to dataset .npz file")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--batch_size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--patience", type=int, default=10)
    parser.add_argument("--output_dir", type=str, default="checkpoints")
    parser.add_argument("--seed", type=int, default=42)

    args = parser.parse_args()
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    run_training(args)
