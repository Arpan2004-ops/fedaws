"""Download PneumoniaMNIST and split it into private per-hospital shards.

Run this once on a laptop. It produces:

    data/hospital_a/shard.npz     private to hospital A
    data/hospital_b/shard.npz     private to hospital B
    data/hospital_c/shard.npz     private to hospital C
    data/server/test.npz          the aggregator's held-out test set
    data/partition_summary.json   what the dashboard shows about the split

The default split is non-IID: a Dirichlet draw gives each hospital a different
class balance and a different volume, which is the situation federated learning
actually exists for. Pass ``--iid`` to produce the easy comparison case for the
report.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Dict, List

import numpy as np

HOSPITAL_IDS = ["a", "b", "c"]
CLASS_NAMES = ["normal", "pneumonia"]


def load_medmnist(size: int) -> Dict[str, tuple]:
    """Fetch the PneumoniaMNIST splits as raw NumPy arrays."""
    try:
        from medmnist import PneumoniaMNIST
    except ImportError as error:  # pragma: no cover - dependency guidance
        raise SystemExit(
            "medmnist is not installed. Run: pip install -r requirements-dev.txt"
        ) from error

    splits = {}
    for split in ("train", "val", "test"):
        dataset = PneumoniaMNIST(split=split, download=True, size=size)
        images = np.asarray(dataset.imgs)
        labels = np.asarray(dataset.labels).reshape(-1).astype(np.int64)
        if images.ndim == 4 and images.shape[-1] == 1:
            images = images[..., 0]
        splits[split] = (images.astype(np.uint8), labels)
        print(f"  {split:5s}: {images.shape[0]:5d} images, shape {images.shape[1:]}")
    return splits


def dirichlet_split(
    labels: np.ndarray, num_parts: int, alpha: float, rng: np.random.Generator
) -> List[np.ndarray]:
    """Assign every sample to a hospital, class by class, using Dirichlet weights.

    A small alpha means highly skewed hospitals. alpha=0.5 gives a realistic
    picture: one site sees mostly pneumonia, another is dominated by normals.
    """
    parts: List[List[int]] = [[] for _ in range(num_parts)]
    for class_index in range(len(CLASS_NAMES)):
        indices = np.where(labels == class_index)[0]
        rng.shuffle(indices)
        proportions = rng.dirichlet(np.repeat(alpha, num_parts))
        cut_points = (np.cumsum(proportions) * len(indices)).astype(int)[:-1]
        for part_index, chunk in enumerate(np.split(indices, cut_points)):
            parts[part_index].extend(chunk.tolist())

    result = []
    for part in parts:
        array = np.array(sorted(part), dtype=np.int64)
        rng.shuffle(array)
        result.append(array)
    return result


def iid_split(
    labels: np.ndarray, num_parts: int, rng: np.random.Generator
) -> List[np.ndarray]:
    """Equal-sized shards with the same class balance as the full dataset."""
    indices = rng.permutation(len(labels))
    return [np.array(sorted(chunk)) for chunk in np.array_split(indices, num_parts)]


def describe(labels: np.ndarray) -> Dict[str, object]:
    counts = np.bincount(labels, minlength=len(CLASS_NAMES))
    total = int(counts.sum())
    return {
        "examples": total,
        "class_counts": {name: int(count) for name, count in zip(CLASS_NAMES, counts)},
        "pneumonia_ratio": round(float(counts[1]) / max(total, 1), 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Partition PneumoniaMNIST across hospitals")
    parser.add_argument("--output", default="data", help="Output directory")
    parser.add_argument("--size", type=int, default=64, choices=[28, 64, 128], help="Image size")
    parser.add_argument("--alpha", type=float, default=0.5, help="Dirichlet concentration")
    parser.add_argument("--iid", action="store_true", help="Produce an IID split instead")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)

    print(f"Downloading PneumoniaMNIST at {args.size}x{args.size} ...")
    splits = load_medmnist(args.size)

    # Hospitals get the training split. The official validation split is folded
    # into the server's test set so the centralised curve is measured on enough
    # patients to be stable.
    train_images, train_labels = splits["train"]
    test_images = np.concatenate([splits["test"][0], splits["val"][0]])
    test_labels = np.concatenate([splits["test"][1], splits["val"][1]])

    if args.iid:
        partitions = iid_split(train_labels, len(HOSPITAL_IDS), rng)
        strategy = "iid"
    else:
        partitions = dirichlet_split(train_labels, len(HOSPITAL_IDS), args.alpha, rng)
        strategy = f"dirichlet(alpha={args.alpha})"

    summary: Dict[str, object] = {
        "dataset": f"PneumoniaMNIST-{args.size}",
        "strategy": strategy,
        "seed": args.seed,
        "classes": CLASS_NAMES,
        "hospitals": [],
        "server_test": describe(test_labels),
    }

    for hospital_id, indices in zip(HOSPITAL_IDS, partitions):
        directory = os.path.join(args.output, f"hospital_{hospital_id}")
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, "shard.npz")
        np.savez_compressed(
            path, images=train_images[indices], labels=train_labels[indices]
        )
        stats = describe(train_labels[indices])
        stats["hospital_id"] = hospital_id
        stats["path"] = path
        stats["size_mb"] = round(os.path.getsize(path) / 1e6, 2)
        summary["hospitals"].append(stats)
        print(
            f"  hospital {hospital_id}: {stats['examples']:5d} images, "
            f"{stats['pneumonia_ratio'] * 100:5.1f}% pneumonia, {stats['size_mb']} MB"
        )

    server_directory = os.path.join(args.output, "server")
    os.makedirs(server_directory, exist_ok=True)
    np.savez_compressed(
        os.path.join(server_directory, "test.npz"), images=test_images, labels=test_labels
    )
    print(f"  server test set: {len(test_labels)} images")

    # Sanity check: the shards must be disjoint, or the privacy story is a lie.
    all_indices = np.concatenate(partitions)
    assert len(np.unique(all_indices)) == len(all_indices), "hospital shards overlap"
    print(f"  disjointness verified across {len(all_indices)} training images")

    summary_path = os.path.join(args.output, "partition_summary.json")
    with open(summary_path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    print(f"Wrote {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
