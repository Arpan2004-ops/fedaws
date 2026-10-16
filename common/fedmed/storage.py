"""Model checkpoint storage with interchangeable local and S3 backends.

The same code path runs under docker compose (writes to a mounted volume) and on
Fargate (writes to a versioned S3 bucket). Switching is a single environment
variable, ``STORAGE_BACKEND``.
"""

from __future__ import annotations

import io
import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import numpy as np

from .config import StorageConfig

LOGGER = logging.getLogger(__name__)

LATEST_KEY = "global/latest.npz"
SUMMARY_KEY = "global/summary.json"


def _serialise(weights: List[np.ndarray], metadata: Dict[str, Any]) -> bytes:
    """Pack a parameter list plus metadata into one compressed ``.npz`` blob."""
    buffer = io.BytesIO()
    arrays = {f"arr_{index}": array for index, array in enumerate(weights)}
    arrays["__metadata__"] = np.frombuffer(
        json.dumps(metadata).encode("utf-8"), dtype=np.uint8
    )
    np.savez_compressed(buffer, **arrays)
    return buffer.getvalue()


def _deserialise(blob: bytes) -> tuple[List[np.ndarray], Dict[str, Any]]:
    with np.load(io.BytesIO(blob), allow_pickle=False) as archive:
        metadata: Dict[str, Any] = {}
        if "__metadata__" in archive.files:
            metadata = json.loads(bytes(archive["__metadata__"]).decode("utf-8"))
        indices = sorted(
            (int(name.split("_")[1]) for name in archive.files if name.startswith("arr_")),
        )
        weights = [np.array(archive[f"arr_{index}"]) for index in indices]
    return weights, metadata


class Storage(ABC):
    """Persist and retrieve global model checkpoints."""

    @abstractmethod
    def save_checkpoint(
        self, server_round: int, weights: List[np.ndarray], metadata: Dict[str, Any]
    ) -> str:
        """Write one round's global model and return a human-readable location."""

    @abstractmethod
    def load_latest(self) -> tuple[List[np.ndarray], Dict[str, Any]]:
        """Read back the most recent global model."""

    @abstractmethod
    def write_json(self, key: str, payload: Dict[str, Any]) -> str:
        """Write a small JSON document (run summaries, partition manifests)."""

    @abstractmethod
    def read_bytes(self, key: str) -> bytes:
        """Read an arbitrary object, used to fetch a hospital's data shard."""


class LocalStorage(Storage):
    """Filesystem backend used by docker compose and the unit tests."""

    def __init__(self, root: str) -> None:
        self.root = root
        try:
            os.makedirs(os.path.join(root, "global"), exist_ok=True)
        except OSError as error:
            # The inference API mounts the artifacts volume read-only, because
            # it has no business writing checkpoints. Failing to create a
            # directory it will never write to must not stop it from serving.
            LOGGER.debug("could not create %s: %s", root, error)

    def _path(self, key: str) -> str:
        path = os.path.join(self.root, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path

    def save_checkpoint(
        self, server_round: int, weights: List[np.ndarray], metadata: Dict[str, Any]
    ) -> str:
        blob = _serialise(weights, metadata)
        round_key = f"global/round_{server_round:03d}.npz"
        for key in (round_key, LATEST_KEY):
            with open(self._path(key), "wb") as handle:
                handle.write(blob)
        return os.path.join(self.root, round_key)

    def load_latest(self) -> tuple[List[np.ndarray], Dict[str, Any]]:
        with open(self._path(LATEST_KEY), "rb") as handle:
            return _deserialise(handle.read())

    def write_json(self, key: str, payload: Dict[str, Any]) -> str:
        path = self._path(key)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        return path

    def read_bytes(self, key: str) -> bytes:
        with open(self._path(key), "rb") as handle:
            return handle.read()


class S3Storage(Storage):
    """S3 backend. Bucket versioning gives a free audit trail of every round."""

    def __init__(self, bucket: str, region: str, prefix: str = "") -> None:
        if not bucket:
            raise ValueError("S3Storage requires a bucket name (set MODELS_BUCKET)")
        import boto3  # imported lazily so local runs need no AWS SDK

        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.client = boto3.client("s3", region_name=region)

    def _key(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    def save_checkpoint(
        self, server_round: int, weights: List[np.ndarray], metadata: Dict[str, Any]
    ) -> str:
        blob = _serialise(weights, metadata)
        round_key = f"global/round_{server_round:03d}.npz"
        for key in (round_key, LATEST_KEY):
            self.client.put_object(
                Bucket=self.bucket,
                Key=self._key(key),
                Body=blob,
                ContentType="application/octet-stream",
                ServerSideEncryption="AES256",
            )
        return f"s3://{self.bucket}/{self._key(round_key)}"

    def load_latest(self) -> tuple[List[np.ndarray], Dict[str, Any]]:
        response = self.client.get_object(Bucket=self.bucket, Key=self._key(LATEST_KEY))
        return _deserialise(response["Body"].read())

    def write_json(self, key: str, payload: Dict[str, Any]) -> str:
        self.client.put_object(
            Bucket=self.bucket,
            Key=self._key(key),
            Body=json.dumps(payload, indent=2).encode("utf-8"),
            ContentType="application/json",
            ServerSideEncryption="AES256",
        )
        return f"s3://{self.bucket}/{self._key(key)}"

    def read_bytes(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=self._key(key))
        return response["Body"].read()


def build_storage(config: Optional[StorageConfig] = None, bucket: Optional[str] = None) -> Storage:
    """Pick a backend from configuration.

    ``bucket`` overrides the models bucket, which is how a hospital node points
    the same class at its own private data bucket.
    """
    config = config or StorageConfig()
    if config.backend.lower() == "s3":
        return S3Storage(bucket or config.models_bucket, config.aws_region)
    root = config.local_root
    LOGGER.info("Using local storage at %s", root)
    return LocalStorage(root)


__all__ = [
    "LATEST_KEY",
    "LocalStorage",
    "S3Storage",
    "Storage",
    "SUMMARY_KEY",
    "build_storage",
]
