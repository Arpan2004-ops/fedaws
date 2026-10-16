"""Environment-driven configuration shared by every FedMed component.

Every knob the demo needs is an environment variable so the same container image
runs unchanged locally (docker compose) and on AWS Fargate.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def _env_int(name: str, default: int) -> int:
    return int(_env(name, str(default)))


def _env_float(name: str, default: float) -> float:
    return float(_env(name, str(default)))


def _env_bool(name: str, default: bool) -> bool:
    return _env(name, "true" if default else "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@dataclass
class TrainingConfig:
    """Hyper-parameters for local training on a hospital node."""

    local_epochs: int = field(default_factory=lambda: _env_int("LOCAL_EPOCHS", 1))
    batch_size: int = field(default_factory=lambda: _env_int("BATCH_SIZE", 64))
    learning_rate: float = field(default_factory=lambda: _env_float("LEARNING_RATE", 1e-3))
    seed: int = field(default_factory=lambda: _env_int("SEED", 42))


@dataclass
class FederationConfig:
    """Topology and round settings for the federation."""

    server_address: str = field(
        default_factory=lambda: _env("SERVER_ADDRESS", "fl-server:8080")
    )
    bind_address: str = field(default_factory=lambda: _env("BIND_ADDRESS", "0.0.0.0:8080"))
    num_rounds: int = field(default_factory=lambda: _env_int("NUM_ROUNDS", 10))
    num_hospitals: int = field(default_factory=lambda: _env_int("NUM_HOSPITALS", 3))
    run_id: str = field(default_factory=lambda: _env("RUN_ID", "local-run"))


@dataclass
class PrivacyConfig:
    """Differential-privacy knobs applied server side by the Flower strategy."""

    enabled: bool = field(default_factory=lambda: _env_bool("DP_ENABLED", True))
    noise_multiplier: float = field(
        default_factory=lambda: _env_float("DP_NOISE_MULTIPLIER", 0.05)
    )
    clipping_norm: float = field(default_factory=lambda: _env_float("DP_CLIP_NORM", 1.0))
    delta: float = field(default_factory=lambda: _env_float("DP_DELTA", 1e-5))


@dataclass
class StorageConfig:
    """Where model checkpoints, metrics and data shards live."""

    backend: str = field(default_factory=lambda: _env("STORAGE_BACKEND", "local"))
    local_root: str = field(default_factory=lambda: _env("LOCAL_ROOT", "/workspace/artifacts"))
    models_bucket: str = field(default_factory=lambda: _env("MODELS_BUCKET", ""))
    data_bucket: str = field(default_factory=lambda: _env("DATA_BUCKET", ""))
    rounds_table: str = field(default_factory=lambda: _env("ROUNDS_TABLE", "fedmed-rounds"))
    audit_table: str = field(default_factory=lambda: _env("AUDIT_TABLE", "fedmed-audit"))
    aws_region: str = field(default_factory=lambda: _env("AWS_REGION", "us-east-1"))
    cloudwatch_namespace: str = field(
        default_factory=lambda: _env("CLOUDWATCH_NAMESPACE", "FedMed")
    )
    push_cloudwatch: bool = field(default_factory=lambda: _env_bool("PUSH_CLOUDWATCH", False))


@dataclass
class TLSConfig:
    """Paths to the self-signed certificate material for the Flower gRPC channel."""

    enabled: bool = field(default_factory=lambda: _env_bool("TLS_ENABLED", False))
    ca_path: str = field(default_factory=lambda: _env("TLS_CA_PATH", "/certs/ca.crt"))
    cert_path: str = field(default_factory=lambda: _env("TLS_CERT_PATH", "/certs/server.crt"))
    key_path: str = field(default_factory=lambda: _env("TLS_KEY_PATH", "/certs/server.key"))
