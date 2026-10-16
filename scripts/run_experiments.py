"""Run the comparison sweep that the report's evaluation section is built from.

Four questions, answered by measurement rather than assertion:

  1. What does the model reach when all three datasets are pooled? (the ceiling)
  2. What does federated training reach on the same data, split three ways?
  3. How much does the non-IID split cost, compared with an even one?
  4. What does each level of differential-privacy noise cost in accuracy?

    python scripts/run_experiments.py            # the full sweep, about ten minutes
    python scripts/run_experiments.py --rounds 5 # quicker, for a dry run

Outputs artifacts/experiments.json, artifacts/experiments.md (paste straight into
the report) and two PNG figures.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from typing import Any, Dict, List

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(command: List[str], label: str) -> None:
    print(f"\n=== {label} ===")
    print("  " + " ".join(command[1:]))
    result = subprocess.run(command, cwd=REPO_ROOT)
    if result.returncode != 0:
        raise SystemExit(f"{label} failed with exit code {result.returncode}")


def ensure_iid_partition(seed: int) -> str:
    """Build the even split used for the IID comparison, if it is not there yet."""
    directory = os.path.join(REPO_ROOT, "data_iid")
    if os.path.exists(os.path.join(directory, "partition_summary.json")):
        print("reusing the existing IID partition in data_iid/")
        return directory

    run(
        [
            sys.executable,
            os.path.join("scripts", "partition_data.py"),
            "--output", "data_iid",
            "--iid",
            "--seed", str(seed),
        ],
        "building an IID partition for comparison",
    )
    return directory


def federated_run(
    name: str,
    data_dir: str,
    rounds: int,
    dp: bool,
    noise: float,
    clip: float,
) -> Dict[str, Any]:
    """One complete federation, isolated in its own artifacts directory."""
    output_root = os.path.join(REPO_ROOT, "artifacts", "experiments", name)
    os.makedirs(output_root, exist_ok=True)

    command = [
        sys.executable,
        os.path.join("scripts", "run_local.py"),
        "--rounds", str(rounds),
        "--run-id", name,
        "--data", data_dir,
        "--artifacts", output_root,
    ]
    if dp:
        command += ["--dp", "--noise-multiplier", str(noise), "--clip-norm", str(clip)]

    started = time.time()
    print(f"\n=== {name} ===")
    result = subprocess.run(command, cwd=REPO_ROOT)
    if result.returncode != 0:
        raise SystemExit(f"run {name} failed with exit code {result.returncode}")

    with open(os.path.join(output_root, "global", "summary.json"), encoding="utf-8") as handle:
        summary = json.load(handle)

    return {
        "name": name,
        "mode": "federated",
        "split": "iid" if "iid" in name else "non-iid",
        "dp": dp,
        "noise_multiplier": noise if dp else 0.0,
        "clip_norm": clip if dp else None,
        "rounds": rounds,
        "final_accuracy": summary["final_accuracy"],
        "best_accuracy": summary["best_accuracy"],
        "epsilon": summary["privacy"].get("epsilon"),
        "wall_seconds": round(time.time() - started, 1),
        "history": [
            {"round": entry["round"], "accuracy": entry["accuracy"], "loss": entry["loss"]}
            for entry in summary["history"]
        ],
    }


def centralized(rounds: int) -> Dict[str, Any]:
    """The ceiling: one model, all three shards pooled.

    Given the same number of passes over the data as the federation gets, so the
    comparison is about where the data lives and not about compute budget.
    """
    output = os.path.join("artifacts", "experiments", "centralized.json")
    run(
        [
            sys.executable,
            os.path.join("scripts", "train_centralized.py"),
            "--epochs", str(rounds),
            "--output", output,
        ],
        "centralised baseline",
    )
    with open(os.path.join(REPO_ROOT, output), encoding="utf-8") as handle:
        summary = json.load(handle)

    return {
        "name": "centralized",
        "mode": "centralized",
        "split": "pooled",
        "dp": False,
        "noise_multiplier": 0.0,
        "clip_norm": None,
        "rounds": rounds,
        "final_accuracy": summary["final_accuracy"],
        "best_accuracy": summary["best_accuracy"],
        "epsilon": None,
        "wall_seconds": summary["wall_seconds"],
        "history": [
            {"round": entry["epoch"], "accuracy": entry["test_accuracy"], "loss": entry["test_loss"]}
            for entry in summary["history"]
        ],
    }


DESCRIPTIONS = {
    "centralized": "All data pooled on one server",
    "fed-iid": "Federated, even split across three sites",
    "fed-noniid": "Federated, realistic uneven split",
    "fed-noniid-dp-005": "Federated non-IID, light privacy noise",
    "fed-noniid-dp-02": "Federated non-IID, moderate privacy noise",
    "fed-noniid-dp-05": "Federated non-IID, heavy privacy noise",
}


def write_markdown(results: List[Dict[str, Any]], path: str) -> None:
    ceiling = next(
        (entry["final_accuracy"] for entry in results if entry["mode"] == "centralized"), None
    )

    lines = [
        "# FedMed evaluation",
        "",
        f"Generated {time.strftime('%Y-%m-%d %H:%M')}. PneumoniaMNIST at 64 pixels, three sites,",
        f"{results[0]['rounds']} rounds or epochs, identical model and learning rate throughout.",
        "",
        "| Configuration | Final accuracy | Best round | vs pooled | Epsilon | Seconds |",
        "|---|---|---|---|---|---|",
    ]

    for entry in results:
        # Signed as accuracy relative to the ceiling, so a cost reads as a
        # negative number rather than as a confusing positive "gap".
        gap = (
            "baseline"
            if entry["mode"] == "centralized"
            else f"{(entry['final_accuracy'] - ceiling) * 100:+.1f} pts"
            if ceiling is not None
            else "n/a"
        )
        epsilon = f"{entry['epsilon']:.0f}" if entry["epsilon"] is not None else "none"
        lines.append(
            f"| {DESCRIPTIONS.get(entry['name'], entry['name'])} "
            f"| {entry['final_accuracy'] * 100:.1f}% "
            f"| {entry['best_accuracy'] * 100:.1f}% "
            f"| {gap} "
            f"| {epsilon} "
            f"| {entry['wall_seconds']:.0f} |"
        )

    lines += [
        "",
        "## Reading the table",
        "",
        "The gap between the pooled baseline and federated non-IID training is the price of",
        "keeping the images apart. The gap between the IID and non-IID federated rows is the",
        "price of the hospitals being genuinely different from one another, which is the part",
        "a synthetic even split would hide.",
        "",
        "The epsilon column is where the honesty lives. Noise levels light enough to preserve",
        "accuracy produce budgets far too large to claim as a formal guarantee, because three",
        "sites all participating in every round give no subsampling amplification to collect.",
        "The mitigation is more participating hospitals, not a smaller number in this column.",
        "",
        "Final and best accuracy differ by several points in some rows. Federated averaging over",
        "three unequal sites is genuinely noisy round to round, so quote both columns rather than",
        "picking whichever one flatters the configuration.",
        "",
    ]

    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def write_figures(results: List[Dict[str, Any]], directory: str) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib is not installed, skipping the figures")
        return

    # Figure 1: convergence.
    figure, axes = plt.subplots(figsize=(7.5, 4.2))
    for entry in results:
        if not entry["history"]:
            continue
        axes.plot(
            [point["round"] for point in entry["history"]],
            [point["accuracy"] * 100 for point in entry["history"]],
            marker="o",
            markersize=3.5,
            linewidth=1.8,
            label=DESCRIPTIONS.get(entry["name"], entry["name"]),
        )
    axes.set_xlabel("round (federated) or epoch (centralised)")
    axes.set_ylabel("test accuracy (%)")
    axes.set_title("Convergence under each configuration")
    axes.grid(True, linewidth=0.5, alpha=0.35)
    axes.legend(fontsize=8, loc="lower right")
    figure.tight_layout()
    figure.savefig(os.path.join(directory, "convergence.png"), dpi=160)
    plt.close(figure)

    # Figure 2: the privacy and accuracy trade, which is the interesting one.
    noisy = [entry for entry in results if entry["dp"]]
    clean = next((entry for entry in results if entry["name"] == "fed-noniid"), None)
    if noisy:
        points = ([(0.0, clean["final_accuracy"])] if clean else []) + [
            (entry["noise_multiplier"], entry["final_accuracy"]) for entry in noisy
        ]
        points.sort()

        figure, axes = plt.subplots(figsize=(6.4, 4.0))
        axes.plot(
            [point[0] for point in points],
            [point[1] * 100 for point in points],
            marker="o",
            linewidth=1.8,
        )
        for entry in noisy:
            if entry["epsilon"] is not None:
                axes.annotate(
                    f"e={entry['epsilon']:.0f}",
                    (entry["noise_multiplier"], entry["final_accuracy"] * 100),
                    textcoords="offset points",
                    xytext=(6, 6),
                    fontsize=8,
                )
        axes.set_xlabel("noise multiplier")
        axes.set_ylabel("test accuracy (%)")
        axes.set_title("What each unit of privacy noise costs in accuracy")
        axes.grid(True, linewidth=0.5, alpha=0.35)
        figure.tight_layout()
        figure.savefig(os.path.join(directory, "privacy_tradeoff.png"), dpi=160)
        plt.close(figure)

    print(f"figures written to {directory}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the FedMed evaluation sweep")
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--clip-norm", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--skip-iid",
        action="store_true",
        help="Skip the IID comparison, which needs a second partition",
    )
    args = parser.parse_args()

    output_directory = os.path.join(REPO_ROOT, "artifacts", "experiments")
    os.makedirs(output_directory, exist_ok=True)

    data_dir = os.path.join(REPO_ROOT, "data")
    results: List[Dict[str, Any]] = [centralized(args.rounds)]

    if not args.skip_iid:
        iid_dir = ensure_iid_partition(args.seed)
        results.append(
            federated_run("fed-iid", iid_dir, args.rounds, False, 0.0, args.clip_norm)
        )

    results.append(
        federated_run("fed-noniid", data_dir, args.rounds, False, 0.0, args.clip_norm)
    )
    for noise, label in ((0.05, "005"), (0.2, "02"), (0.5, "05")):
        results.append(
            federated_run(
                f"fed-noniid-dp-{label}", data_dir, args.rounds, True, noise, args.clip_norm
            )
        )

    json_path = os.path.join(output_directory, "experiments.json")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump({"rounds": args.rounds, "results": results}, handle, indent=2)

    markdown_path = os.path.join(REPO_ROOT, "artifacts", "experiments.md")
    write_markdown(results, markdown_path)
    write_figures(results, output_directory)

    print("\n" + "=" * 70)
    with open(markdown_path, encoding="utf-8") as handle:
        print(handle.read())
    print(f"raw results: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
