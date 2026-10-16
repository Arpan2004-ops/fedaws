"""A hospital node.

Three copies of this container run in the federation, distinguished only by
``HOSPITAL_ID``. Each one reads a single shard that lives in its own private
bucket, trains on it locally, and returns weights plus scalar metrics.

Nothing in this file has a code path that sends pixels anywhere. The gRPC
messages Flower emits contain the model parameter list and the metrics dictionary
built in ``fit`` and ``evaluate``, and that is the whole outbound surface.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from typing import Dict, List, Tuple

import flwr as fl
import numpy as np
from flwr.common import Config, NDArrays, Scalar

from fedmed import data as data_utils
from fedmed.config import FederationConfig, StorageConfig, TLSConfig, TrainingConfig
from fedmed.model import build_model, get_weights, set_weights
from fedmed.storage import build_storage

HOSPITAL_ID = os.environ.get("HOSPITAL_ID", "unknown")

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format=f"%(asctime)s %(levelname)s [hospital-{HOSPITAL_ID}] %(message)s",
)
LOGGER = logging.getLogger("fedmed.hospital")

VALIDATION_FRACTION = 0.15


def fetch_shard(storage_config: StorageConfig) -> str:
    """Return a local path to this hospital's shard, downloading it if needed.

    On Fargate the shard is pulled once from the hospital's own S3 bucket into
    the task's ephemeral storage, which disappears when the task stops.
    """
    local_path = os.environ.get("SHARD_PATH", f"/workspace/data/hospital_{HOSPITAL_ID}/shard.npz")
    if storage_config.backend.lower() != "s3":
        return local_path

    key = os.environ.get("SHARD_KEY", "shard.npz")
    storage = build_storage(storage_config, bucket=storage_config.data_bucket)
    LOGGER.info("downloading %s from s3://%s", key, storage_config.data_bucket)
    blob = storage.read_bytes(key)
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, "wb") as handle:
        handle.write(blob)
    LOGGER.info("shard cached at %s (%.1f MB)", local_path, len(blob) / 1e6)
    return local_path


def split_train_validation(
    shard: data_utils.Shard, seed: int
) -> Tuple[data_utils.Shard, data_utils.Shard]:
    """Hold back a slice of the local data so the hospital can score the global model.

    This is what makes the federated evaluation round meaningful: each hospital
    judges the incoming global model on patients the model has never trained on.
    """
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(shard))
    cut = max(int(len(shard) * (1 - VALIDATION_FRACTION)), 1)
    train_index, validation_index = order[:cut], order[cut:]
    if validation_index.size == 0:  # tiny shard, reuse the tail of training
        validation_index = train_index[-1:]
    return (
        data_utils.Shard(shard.images[train_index], shard.labels[train_index], "train"),
        data_utils.Shard(shard.images[validation_index], shard.labels[validation_index], "val"),
    )


class HospitalClient(fl.client.NumPyClient):
    """Implements the three calls Flower makes on a participant."""

    def __init__(
        self,
        train_shard: data_utils.Shard,
        validation_shard: data_utils.Shard,
        training: TrainingConfig,
    ) -> None:
        self.train_shard = train_shard
        self.validation_shard = validation_shard
        self.training = training
        self.model = build_model(seed=training.seed)

    def get_properties(self, config: Config) -> Dict[str, Scalar]:
        return {"hospital_id": HOSPITAL_ID, "examples": len(self.train_shard)}

    def get_parameters(self, config: Config) -> NDArrays:
        return get_weights(self.model)

    def fit(
        self, parameters: NDArrays, config: Config
    ) -> Tuple[NDArrays, int, Dict[str, Scalar]]:
        """Start from the global model, train locally, hand back new weights."""
        set_weights(self.model, list(parameters))
        started_at = time.time()
        stats = data_utils.train_local(
            self.model,
            self.train_shard,
            epochs=self.training.local_epochs,
            batch_size=self.training.batch_size,
            learning_rate=self.training.learning_rate,
        )
        elapsed = time.time() - started_at
        LOGGER.info(
            "local training done: loss %.4f accuracy %.4f on %s images in %.1fs",
            stats["train_loss"],
            stats["train_accuracy"],
            len(self.train_shard),
            elapsed,
        )
        metrics: Dict[str, Scalar] = {
            "hospital_id": HOSPITAL_ID,
            "train_loss": stats["train_loss"],
            "train_accuracy": stats["train_accuracy"],
            "local_seconds": elapsed,
        }
        return get_weights(self.model), len(self.train_shard), metrics

    def evaluate(
        self, parameters: NDArrays, config: Config
    ) -> Tuple[float, int, Dict[str, Scalar]]:
        """Score the incoming global model on this hospital's held-out patients."""
        set_weights(self.model, list(parameters))
        results = data_utils.evaluate(self.model, self.validation_shard)
        LOGGER.info(
            "global model on local validation: accuracy %.4f loss %.4f",
            results["accuracy"],
            results["loss"],
        )
        return (
            results["loss"],
            len(self.validation_shard),
            {"hospital_id": HOSPITAL_ID, "accuracy": results["accuracy"]},
        )


def connect_with_retry(
    client: fl.client.Client, address: str, root_certificates: bytes | None
) -> None:
    """Retry the initial connection.

    Fargate starts all four tasks at once, so a hospital routinely comes up
    before the aggregator is listening. Without this the demo fails on a race.
    """
    attempts = int(os.environ.get("CONNECT_ATTEMPTS", "30"))
    delay = float(os.environ.get("CONNECT_DELAY_SECONDS", "5"))
    for attempt in range(1, attempts + 1):
        try:
            LOGGER.info("connecting to %s (attempt %s/%s)", address, attempt, attempts)
            fl.client.start_client(
                server_address=address,
                client=client,
                root_certificates=root_certificates,
            )
            return
        except Exception as error:  # noqa: BLE001 - any transport error is worth a retry
            if attempt == attempts:
                raise
            LOGGER.warning("server not ready (%s); retrying in %ss", error, delay)
            time.sleep(delay)


def main() -> int:
    federation = FederationConfig()
    training = TrainingConfig()
    storage_config = StorageConfig()
    tls = TLSConfig()

    shard_path = fetch_shard(storage_config)
    shard = data_utils.load_shard(shard_path, name=f"hospital-{HOSPITAL_ID}")
    train_shard, validation_shard = split_train_validation(shard, training.seed)
    LOGGER.info(
        "local dataset: %s images (%s train / %s validation), class balance %s",
        len(shard),
        len(train_shard),
        len(validation_shard),
        shard.class_counts,
    )

    root_certificates = None
    if tls.enabled:
        with open(tls.ca_path, "rb") as handle:
            root_certificates = handle.read()
        LOGGER.info("TLS enabled, pinning CA at %s", tls.ca_path)

    client = HospitalClient(train_shard, validation_shard, training).to_client()
    connect_with_retry(client, federation.server_address, root_certificates)
    LOGGER.info("federation finished, shutting down; local data was never transmitted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
