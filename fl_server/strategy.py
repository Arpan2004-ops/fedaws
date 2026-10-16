"""The aggregation strategy: FedAvg, optional differential privacy, persistence.

Two things are worth knowing about the ordering here.

First, the per-round checkpoint and the metrics record are written from the
server-side ``evaluate_fn`` rather than from ``aggregate_fit``. Flower calls the
strategy's ``evaluate`` with the parameters that come *out* of aggregation, so
when differential privacy is switched on this is the only hook that sees the
noised model. Saving from inside ``aggregate_fit`` would persist the clean
average and quietly defeat the privacy layer.

Second, ``DifferentialPrivacyServerSideFixedClipping`` wraps a strategy rather
than replacing it, so FedAvg keeps doing the weighted averaging and the wrapper
only adds clipping and noise around it.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
from flwr.common import Metrics, NDArrays, Scalar
from flwr.server.strategy import FedAvg, Strategy

from fedmed import data as data_utils
from fedmed.metrics import MetricsSink
from fedmed.model import build_model, set_weights
from fedmed.storage import Storage

LOGGER = logging.getLogger(__name__)


class RoundRecorder:
    """Collects what each hospital reported during the current round.

    Flower hands client training metrics to ``fit_metrics_aggregation_fn`` and
    then throws them away. The dashboard wants them per hospital, so they are
    parked here until ``evaluate_fn`` assembles the round record.
    """

    def __init__(self) -> None:
        self.hospitals: List[Dict[str, Any]] = []
        self.round_started_at: float = time.time()

    def reset(self) -> None:
        self.hospitals = []
        self.round_started_at = time.time()

    def capture(self, results: List[Tuple[int, Metrics]]) -> Metrics:
        """Store per-hospital metrics and return the sample-weighted average."""
        self.hospitals = [
            {
                "hospital_id": str(metrics.get("hospital_id", f"unknown-{index}")),
                "examples": int(num_examples),
                "train_loss": float(metrics.get("train_loss", 0.0)),
                "train_accuracy": float(metrics.get("train_accuracy", 0.0)),
                "local_seconds": float(metrics.get("local_seconds", 0.0)),
            }
            for index, (num_examples, metrics) in enumerate(results)
        ]
        total = sum(item["examples"] for item in self.hospitals) or 1
        return {
            "train_loss": sum(i["train_loss"] * i["examples"] for i in self.hospitals) / total,
            "train_accuracy": sum(
                i["train_accuracy"] * i["examples"] for i in self.hospitals
            )
            / total,
            "participating_hospitals": len(self.hospitals),
            "total_examples": total,
        }


def make_evaluate_fn(
    test_shard: data_utils.Shard,
    storage: Storage,
    sink: MetricsSink,
    recorder: RoundRecorder,
    run_id: str,
    privacy: Dict[str, Any],
    history: List[Dict[str, Any]],
) -> Callable[[int, NDArrays, Dict[str, Scalar]], Optional[Tuple[float, Dict[str, Scalar]]]]:
    """Build the centralised evaluation hook.

    The server holds a global test set that belongs to no hospital, which is what
    makes the round-by-round accuracy curve comparable across runs.
    """

    model = build_model()

    def evaluate_fn(
        server_round: int, parameters: NDArrays, config: Dict[str, Scalar]
    ) -> Optional[Tuple[float, Dict[str, Scalar]]]:
        set_weights(model, list(parameters))
        results = data_utils.evaluate(model, test_shard)

        if server_round == 0:
            # Round 0 is the evaluation of the initial random model. It is a
            # useful baseline for the chart but there is nothing to checkpoint.
            LOGGER.info("initial model accuracy %.4f", results["accuracy"])
            return results["loss"], {"accuracy": results["accuracy"]}

        metadata = {
            "run_id": run_id,
            "round": server_round,
            "accuracy": results["accuracy"],
            "loss": results["loss"],
            "privacy": privacy,
            "saved_at": int(time.time()),
        }
        location = storage.save_checkpoint(server_round, list(parameters), metadata)

        record: Dict[str, Any] = {
            "accuracy": results["accuracy"],
            "loss": results["loss"],
            "recall_normal": results["recall_normal"],
            "recall_pneumonia": results["recall_pneumonia"],
            "test_examples": int(results["examples"]),
            "round_seconds": round(time.time() - recorder.round_started_at, 2),
            "hospitals": recorder.hospitals,
            "checkpoint": location,
            "dp_enabled": bool(privacy.get("mechanism") != "none"),
        }
        sink.record_round(run_id, server_round, record)
        history.append({"round": server_round, **record})
        recorder.reset()

        LOGGER.info(
            "round %s | accuracy %.4f | loss %.4f | checkpoint %s",
            server_round,
            results["accuracy"],
            results["loss"],
            location,
        )
        return results["loss"], {"accuracy": results["accuracy"]}

    return evaluate_fn


def build_strategy(
    initial_parameters,
    evaluate_fn,
    recorder: RoundRecorder,
    num_hospitals: int,
    dp_enabled: bool,
    noise_multiplier: float,
    clipping_norm: float,
) -> Strategy:
    """FedAvg over every hospital, optionally wrapped in the DP mechanism."""

    strategy: Strategy = FedAvg(
        fraction_fit=1.0,
        fraction_evaluate=1.0,
        min_fit_clients=num_hospitals,
        min_evaluate_clients=num_hospitals,
        min_available_clients=num_hospitals,
        initial_parameters=initial_parameters,
        evaluate_fn=evaluate_fn,
        fit_metrics_aggregation_fn=recorder.capture,
        evaluate_metrics_aggregation_fn=_weighted_average,
    )

    if not dp_enabled or noise_multiplier <= 0:
        LOGGER.warning("differential privacy is DISABLED for this run")
        return strategy

    from flwr.server.strategy import DifferentialPrivacyServerSideFixedClipping

    LOGGER.info(
        "differential privacy on: clip=%.3f noise_multiplier=%.4f",
        clipping_norm,
        noise_multiplier,
    )
    return DifferentialPrivacyServerSideFixedClipping(
        strategy,
        noise_multiplier=noise_multiplier,
        clipping_norm=clipping_norm,
        num_sampled_clients=num_hospitals,
    )


def _weighted_average(results: List[Tuple[int, Metrics]]) -> Metrics:
    """Sample-weighted mean of the hospitals' local evaluation metrics."""
    total = sum(num_examples for num_examples, _ in results) or 1
    accuracy = sum(
        float(metrics.get("accuracy", 0.0)) * num_examples for num_examples, metrics in results
    )
    return {"accuracy": accuracy / total}


def parameters_l2_norm(parameters: NDArrays) -> float:
    """Handy for the report: how large is the update the server just averaged."""
    return float(np.sqrt(sum(float(np.sum(np.square(array))) for array in parameters)))


__all__ = [
    "RoundRecorder",
    "build_strategy",
    "make_evaluate_fn",
    "parameters_l2_norm",
]
