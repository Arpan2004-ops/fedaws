"""Dataset loading, local training and evaluation helpers.

A hospital shard is a single ``.npz`` file holding ``images`` (uint8, N x 64 x 64)
and ``labels`` (int64, N). Keeping shards as plain NumPy archives means a
hospital container needs no database and no dataset library at runtime, and it
makes the "this file never leaves the node" claim easy to inspect.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from .model import CLASS_NAMES, IMAGE_SIZE

# MedMNIST chest X-rays are 8-bit grayscale. Normalising to roughly zero mean and
# unit variance keeps the small network's gradients well scaled.
PIXEL_MEAN = 0.5
PIXEL_STD = 0.5


@dataclass
class Shard:
    """One hospital's private slice of the dataset (or the server's test set)."""

    images: np.ndarray  # uint8, (N, H, W)
    labels: np.ndarray  # int64, (N,)
    name: str = "shard"

    def __len__(self) -> int:
        return int(self.images.shape[0])

    @property
    def class_counts(self) -> Dict[str, int]:
        counts = np.bincount(self.labels.astype(np.int64), minlength=len(CLASS_NAMES))
        return {name: int(count) for name, count in zip(CLASS_NAMES, counts)}


def load_shard(path: str, name: str = "shard") -> Shard:
    """Read a shard from disk and sanity-check its shape."""
    with np.load(path) as archive:
        images = archive["images"]
        labels = archive["labels"]
    images = np.asarray(images)
    labels = np.asarray(labels).reshape(-1).astype(np.int64)
    if images.ndim == 4 and images.shape[-1] == 1:  # (N, H, W, 1) -> (N, H, W)
        images = images[..., 0]
    if images.ndim != 3:
        raise ValueError(f"{path}: expected images with shape (N, H, W), got {images.shape}")
    if images.shape[1] != IMAGE_SIZE or images.shape[2] != IMAGE_SIZE:
        raise ValueError(
            f"{path}: expected {IMAGE_SIZE}x{IMAGE_SIZE} images, got "
            f"{images.shape[1]}x{images.shape[2]}"
        )
    if images.shape[0] != labels.shape[0]:
        raise ValueError(f"{path}: {images.shape[0]} images but {labels.shape[0]} labels")
    return Shard(images=images, labels=labels, name=name)


def to_tensors(shard: Shard) -> Tuple[torch.Tensor, torch.Tensor]:
    """Convert a shard to normalised float tensors of shape (N, 1, H, W)."""
    images = torch.from_numpy(shard.images.astype(np.float32) / 255.0).unsqueeze(1)
    images = (images - PIXEL_MEAN) / PIXEL_STD
    labels = torch.from_numpy(shard.labels.astype(np.int64))
    return images, labels


def make_loader(shard: Shard, batch_size: int, shuffle: bool) -> DataLoader:
    images, labels = to_tensors(shard)
    dataset = TensorDataset(images, labels)
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        drop_last=False,
        num_workers=0,  # Fargate tasks get one vCPU; workers would only add overhead.
    )


def preprocess_image(array: np.ndarray) -> torch.Tensor:
    """Turn one raw grayscale image into a (1, 1, H, W) batch for inference."""
    if array.ndim == 3:
        array = array[..., 0] if array.shape[-1] == 1 else array.mean(axis=-1)
    tensor = torch.from_numpy(array.astype(np.float32) / 255.0).unsqueeze(0).unsqueeze(0)
    return (tensor - PIXEL_MEAN) / PIXEL_STD


def train_local(
    model: nn.Module,
    shard: Shard,
    epochs: int,
    batch_size: int,
    learning_rate: float,
) -> Dict[str, float]:
    """Run local SGD on a hospital's own data and report training statistics.

    Only the numbers returned here plus the updated weights ever leave the node.
    """
    device = torch.device("cpu")
    model.to(device).train()
    loader = make_loader(shard, batch_size=batch_size, shuffle=True)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)

    total_loss = 0.0
    total_correct = 0
    total_seen = 0
    for _ in range(epochs):
        for images, labels in loader:
            optimizer.zero_grad()
            logits = model(images)
            loss = criterion(logits, labels)
            loss.backward()
            optimizer.step()

            total_loss += float(loss.item()) * labels.size(0)
            total_correct += int((logits.argmax(dim=1) == labels).sum().item())
            total_seen += int(labels.size(0))

    return {
        "train_loss": total_loss / max(total_seen, 1),
        "train_accuracy": total_correct / max(total_seen, 1),
        "examples": float(len(shard)),
        "epochs": float(epochs),
    }


@torch.no_grad()
def evaluate(model: nn.Module, shard: Shard, batch_size: int = 128) -> Dict[str, float]:
    """Compute loss, accuracy and per-class recall on a held-out shard."""
    model.eval()
    loader = make_loader(shard, batch_size=batch_size, shuffle=False)
    criterion = nn.CrossEntropyLoss(reduction="sum")

    total_loss = 0.0
    total_correct = 0
    total_seen = 0
    per_class_correct = np.zeros(len(CLASS_NAMES), dtype=np.int64)
    per_class_total = np.zeros(len(CLASS_NAMES), dtype=np.int64)

    for images, labels in loader:
        logits = model(images)
        total_loss += float(criterion(logits, labels).item())
        predictions = logits.argmax(dim=1)
        total_correct += int((predictions == labels).sum().item())
        total_seen += int(labels.size(0))
        for class_index in range(len(CLASS_NAMES)):
            mask = labels == class_index
            per_class_total[class_index] += int(mask.sum().item())
            per_class_correct[class_index] += int((predictions[mask] == class_index).sum().item())

    metrics = {
        "loss": total_loss / max(total_seen, 1),
        "accuracy": total_correct / max(total_seen, 1),
        "examples": float(total_seen),
    }
    for class_index, class_name in enumerate(CLASS_NAMES):
        denominator = max(int(per_class_total[class_index]), 1)
        metrics[f"recall_{class_name}"] = float(per_class_correct[class_index]) / denominator
    return metrics
