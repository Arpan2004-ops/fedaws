"""FedMed aggregation server.

Runs as a single Fargate task. It never reads a hospital's data bucket: the only
dataset it touches is the global test split that ships inside its own image, and
the only thing it receives from hospitals is a list of weight arrays.

The process exits as soon as the configured number of rounds completes, which is
what keeps a demo run down to a few cents of Fargate time.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional

import flwr as fl
from flwr.common import ndarrays_to_parameters
from flwr.server import ServerConfig

from fedmed import data as data_utils
from fedmed import privacy as privacy_utils
from fedmed.config import FederationConfig, PrivacyConfig, StorageConfig, TLSConfig
from fedmed.metrics import build_metrics_sink
from fedmed.model import build_model, count_parameters, get_weights
from fedmed.storage import build_storage

from strategy import RoundRecorder, build_strategy, make_evaluate_fn

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [server] %(message)s",
)
LOGGER = logging.getLogger("fedmed.server")

DEFAULT_TEST_SHARD = "/workspace/data/server/test.npz"


def load_certificates(tls: TLSConfig) -> Optional[tuple]:
    """Read the self-signed CA, server certificate and key for the gRPC channel."""
    if not tls.enabled:
        LOGGER.warning("TLS is DISABLED; the gRPC channel is in plaintext")
        return None
    paths = [tls.ca_path, tls.cert_path, tls.key_path]
    missing = [path for path in paths if not os.path.exists(path)]
    if missing:
        raise FileNotFoundError(
            "TLS_ENABLED is set but these files are missing: " + ", ".join(missing)
        )
    LOGGER.info("TLS enabled using %s", tls.cert_path)
    return tuple(open(path, "rb").read() for path in paths)


def main() -> int:
    parser = argparse.ArgumentParser(description="FedMed federated aggregation server")
    parser.add_argument(
        "--test-shard",
        default=os.environ.get("TEST_SHARD", DEFAULT_TEST_SHARD),
        help="Path to the global held-out test set used for centralised evaluation",
    )
    args = parser.parse_args()

    federation = FederationConfig()
    privacy_config = PrivacyConfig()
    storage_config = StorageConfig()
    tls = TLSConfig()

    run_id = federation.run_id or f"run-{int(time.time())}"
    LOGGER.info("run_id=%s rounds=%s hospitals=%s", run_id, federation.num_rounds, federation.num_hospitals)

    test_shard = data_utils.load_shard(args.test_shard, name="server-test")
    LOGGER.info(
        "global test set: %s images, class balance %s",
        len(test_shard),
        test_shard.class_counts,
    )

    model = build_model(seed=42)
    LOGGER.info("model has %s trainable parameters", f"{count_parameters(model):,}")
    initial_parameters = ndarrays_to_parameters(get_weights(model))

    storage = build_storage(storage_config)
    sink = build_metrics_sink(storage_config)
    recorder = RoundRecorder()
    history: List[Dict[str, Any]] = []

    privacy_report = privacy_utils.build_report(
        noise_multiplier=privacy_config.noise_multiplier,
        clipping_norm=privacy_config.clipping_norm,
        rounds=federation.num_rounds,
        num_clients=federation.num_hospitals,
        delta=privacy_config.delta,
        enabled=privacy_config.enabled,
    )
    LOGGER.info("privacy budget: %s", json.dumps(privacy_report.as_dict()))

    evaluate_fn = make_evaluate_fn(
        test_shard=test_shard,
        storage=storage,
        sink=sink,
        recorder=recorder,
        run_id=run_id,
        privacy=privacy_report.as_dict(),
        history=history,
    )

    strategy = build_strategy(
        initial_parameters=initial_parameters,
        evaluate_fn=evaluate_fn,
        recorder=recorder,
        num_hospitals=federation.num_hospitals,
        dp_enabled=privacy_config.enabled,
        noise_multiplier=privacy_config.noise_multiplier,
        clipping_norm=privacy_config.clipping_norm,
    )

    started_at = time.time()
    LOGGER.info("waiting for %s hospitals on %s", federation.num_hospitals, federation.bind_address)
    fl.server.start_server(
        server_address=federation.bind_address,
        config=ServerConfig(num_rounds=federation.num_rounds),
        strategy=strategy,
        certificates=load_certificates(tls),
    )
    elapsed = round(time.time() - started_at, 2)

    summary = {
        "run_id": run_id,
        "rounds": federation.num_rounds,
        "hospitals": federation.num_hospitals,
        "wall_seconds": elapsed,
        "privacy": privacy_report.as_dict(),
        "final_accuracy": history[-1]["accuracy"] if history else None,
        "best_accuracy": max((entry["accuracy"] for entry in history), default=None),
        "history": history,
        "finished_at": int(time.time()),
    }
    location = storage.write_json("global/summary.json", summary)
    LOGGER.info("run finished in %ss, summary at %s", elapsed, location)
    LOGGER.info("final accuracy: %s", summary["final_accuracy"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
