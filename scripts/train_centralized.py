"""Train one model on all three shards pooled together.

This is the number every federated result is judged against. It is what you
would get if the three hospitals were allowed to hand their images to a single
server, so the gap between this and the federated accuracy is exactly the price
the platform pays for privacy.

    python scripts/train_centralized.py --epochs 10
"""

from __future__ import annotations

import argparse
import json
import os
import time

import numpy as np

from fedmed import data as data_utils
from fedmed.model import build_model, count_parameters

HOSPITAL_IDS = ["a", "b", "c"]


def pool_shards(data_root: str) -> data_utils.Shard:
    """Concatenate every hospital's shard, which the real platform never does."""
    images = []
    labels = []
    for hospital_id in HOSPITAL_IDS:
        shard = data_utils.load_shard(
            os.path.join(data_root, f"hospital_{hospital_id}", "shard.npz")
        )
        images.append(shard.images)
        labels.append(shard.labels)
    return data_utils.Shard(
        np.concatenate(images), np.concatenate(labels), name="centralized"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Centralised baseline for FedMed")
    parser.add_argument("--data", default="data")
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default="artifacts/centralized_baseline.json")
    args = parser.parse_args()

    train_shard = pool_shards(args.data)
    test_shard = data_utils.load_shard(os.path.join(args.data, "server", "test.npz"))
    print(f"pooled training set: {len(train_shard)} images {train_shard.class_counts}")
    print(f"test set:            {len(test_shard)} images {test_shard.class_counts}")

    model = build_model(seed=args.seed)
    print(f"model parameters:    {count_parameters(model):,}")

    started_at = time.time()
    history = []
    for epoch in range(1, args.epochs + 1):
        stats = data_utils.train_local(
            model,
            train_shard,
            epochs=1,
            batch_size=args.batch_size,
            learning_rate=args.learning_rate,
        )
        results = data_utils.evaluate(model, test_shard)
        history.append(
            {
                "epoch": epoch,
                "train_loss": stats["train_loss"],
                "test_accuracy": results["accuracy"],
                "test_loss": results["loss"],
            }
        )
        print(
            f"epoch {epoch:2d} | train loss {stats['train_loss']:.4f} | "
            f"test accuracy {results['accuracy']:.4f}"
        )

    final = data_utils.evaluate(model, test_shard)
    summary = {
        "mode": "centralized",
        "epochs": args.epochs,
        "train_examples": len(train_shard),
        "wall_seconds": round(time.time() - started_at, 2),
        "final_accuracy": final["accuracy"],
        "final_loss": final["loss"],
        "recall_normal": final["recall_normal"],
        "recall_pneumonia": final["recall_pneumonia"],
        "best_accuracy": max(entry["test_accuracy"] for entry in history),
        "history": history,
    }

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)

    print()
    print(f"centralised baseline accuracy: {final['accuracy']:.4f}")
    print(f"  recall normal    {final['recall_normal']:.4f}")
    print(f"  recall pneumonia {final['recall_pneumonia']:.4f}")
    print(f"written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
