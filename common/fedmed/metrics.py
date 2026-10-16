"""Per-round metric sinks: a local JSON file, DynamoDB, and CloudWatch.

The dashboard reads whatever the sink wrote, so the same React app works against
a docker compose run and against the deployed API.
"""

from __future__ import annotations

import json
import logging
import os
import time
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any, Dict, List, Optional

from .config import StorageConfig

LOGGER = logging.getLogger(__name__)


def _to_dynamo(value: Any) -> Any:
    """DynamoDB rejects Python floats, so numbers go in as Decimal."""
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return Decimal(str(round(value, 6)))
    if isinstance(value, dict):
        return {key: _to_dynamo(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_dynamo(item) for item in value]
    return value


class MetricsSink(ABC):
    """Record what happened in one federated round."""

    @abstractmethod
    def record_round(self, run_id: str, server_round: int, payload: Dict[str, Any]) -> None:
        ...

    def close(self) -> None:  # pragma: no cover - default is a no-op
        return None


class LocalMetrics(MetricsSink):
    """Append rounds to a JSON file the dashboard can load directly."""

    def __init__(self, path: str) -> None:
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.rounds: List[Dict[str, Any]] = []

    def record_round(self, run_id: str, server_round: int, payload: Dict[str, Any]) -> None:
        entry = {"run_id": run_id, "round": server_round, "timestamp": int(time.time())}
        entry.update(payload)
        self.rounds.append(entry)
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump({"run_id": run_id, "rounds": self.rounds}, handle, indent=2)
        LOGGER.info("round %s metrics written to %s", server_round, self.path)


class AwsMetrics(MetricsSink):
    """Write one item per round to DynamoDB plus a custom CloudWatch metric."""

    def __init__(
        self,
        table_name: str,
        region: str,
        namespace: str = "FedMed",
        push_cloudwatch: bool = True,
    ) -> None:
        import boto3  # lazy import keeps local runs SDK-free

        self.table = boto3.resource("dynamodb", region_name=region).Table(table_name)
        self.namespace = namespace
        self.cloudwatch = (
            boto3.client("cloudwatch", region_name=region) if push_cloudwatch else None
        )

    def record_round(self, run_id: str, server_round: int, payload: Dict[str, Any]) -> None:
        item = {"run_id": run_id, "round": server_round, "timestamp": int(time.time())}
        item.update(payload)
        self.table.put_item(Item=_to_dynamo(item))

        if self.cloudwatch is None:
            return
        metric_data = [
            {
                "MetricName": name,
                "Dimensions": [{"Name": "RunId", "Value": run_id}],
                "Value": float(value),
                "Unit": "None",
            }
            for name, value in payload.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ]
        if metric_data:
            self.cloudwatch.put_metric_data(
                Namespace=self.namespace, MetricData=metric_data[:20]
            )


class NullMetrics(MetricsSink):
    """Used when a sink fails to start. Training must never die over telemetry."""

    def record_round(self, run_id: str, server_round: int, payload: Dict[str, Any]) -> None:
        LOGGER.warning("metrics sink unavailable, dropping round %s", server_round)


def build_metrics_sink(config: Optional[StorageConfig] = None) -> MetricsSink:
    config = config or StorageConfig()
    if config.backend.lower() == "s3":
        try:
            return AwsMetrics(
                table_name=config.rounds_table,
                region=config.aws_region,
                namespace=config.cloudwatch_namespace,
                push_cloudwatch=config.push_cloudwatch,
            )
        except Exception as error:  # pragma: no cover - depends on live AWS
            LOGGER.error("could not create the AWS metrics sink: %s", error)
            return NullMetrics()
    return LocalMetrics(os.path.join(config.local_root, "metrics.json"))


__all__ = ["AwsMetrics", "LocalMetrics", "MetricsSink", "NullMetrics", "build_metrics_sink"]
