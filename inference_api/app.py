"""Inference and reporting API for the federated model.

Deployed as a Lambda container image behind an HTTP API Gateway, and runnable as
a plain uvicorn app for local development. It is the only public entry point to
the platform.

Privacy behaviour worth stating in the report: an uploaded X-ray is decoded in
memory, classified, and discarded. Nothing writes the image, its filename, or any
pixel data to disk or to a bucket. The audit trail records a SHA-256 digest of
the bytes, which proves a given image was submitted if someone later presents the
same file, but cannot be turned back into the image.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import time
from typing import Any, Dict, List, Optional

import numpy as np
import torch
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image

from fedmed import data as data_utils
from fedmed.config import StorageConfig
from fedmed.model import CLASS_NAMES, IMAGE_SIZE, build_model, set_weights
from fedmed.storage import build_storage

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
LOGGER = logging.getLogger("fedmed.api")

MODEL_CACHE_SECONDS = int(os.environ.get("MODEL_CACHE_SECONDS", "60"))
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(8 * 1024 * 1024)))
AUDIT_ENABLED = os.environ.get("AUDIT_ENABLED", "true").lower() in {"1", "true", "yes"}

app = FastAPI(
    title="FedMed Inference API",
    description="Serves the model produced by the federated training rounds",
    version="0.1.0",
)

# The dashboard is a static site on a different origin, so it needs CORS. The
# allowed origin list is configurable and defaults to the permissive value only
# because this is a teaching deployment with no patient data behind it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class ModelHolder:
    """Keeps one copy of the global model warm inside the Lambda container.

    Re-reading the checkpoint on every request would add hundreds of milliseconds
    and a needless S3 call, but caching forever would mean a finished training run
    never reaches the API. A short time-to-live gets both.
    """

    def __init__(self) -> None:
        self.model = None
        self.metadata: Dict[str, Any] = {}
        self.loaded_at: float = 0.0

    def refresh(self, force: bool = False) -> None:
        if not force and self.model is not None:
            if time.time() - self.loaded_at < MODEL_CACHE_SECONDS:
                return
        storage = build_storage(StorageConfig())
        weights, metadata = storage.load_latest()
        model = build_model()
        set_weights(model, weights)
        model.eval()
        self.model = model
        self.metadata = metadata
        self.loaded_at = time.time()
        LOGGER.info("loaded global model from round %s", metadata.get("round"))

    def get(self):
        self.refresh()
        if self.model is None:
            raise HTTPException(
                status_code=503,
                detail="No global model is available yet. Run a training round first.",
            )
        return self.model


HOLDER = ModelHolder()


def decode_image(raw: bytes) -> np.ndarray:
    """Turn an uploaded file into a 64x64 grayscale array.

    Accepts anything Pillow can open, so a demo can use a PNG exported from the
    dataset or a JPEG chest film without any client-side preparation.
    """
    try:
        image = Image.open(io.BytesIO(raw))
        image = image.convert("L").resize((IMAGE_SIZE, IMAGE_SIZE), Image.BILINEAR)
    except Exception as error:  # noqa: BLE001 - any decode failure is a client error
        raise HTTPException(status_code=400, detail=f"Unreadable image: {error}") from error
    return np.asarray(image, dtype=np.uint8)


def write_audit_entry(digest: str, prediction: Dict[str, Any]) -> None:
    """Record that a prediction happened, without recording what was in it."""
    config = StorageConfig()
    if not AUDIT_ENABLED or config.backend.lower() != "s3":
        return
    try:
        import boto3

        table = boto3.resource("dynamodb", region_name=config.aws_region).Table(
            config.audit_table
        )
        table.put_item(
            Item={
                "request_hash": digest,
                "timestamp": int(time.time()),
                "predicted_label": prediction["label"],
                "model_round": int(prediction.get("model_round") or 0),
            }
        )
    except Exception as error:  # pragma: no cover - telemetry must not break serving
        LOGGER.warning("audit write failed: %s", error)


@app.get("/health")
def health() -> Dict[str, Any]:
    """Liveness plus whether a trained model has been published yet."""
    try:
        HOLDER.refresh()
        model_round = HOLDER.metadata.get("round")
    except Exception as error:  # noqa: BLE001 - health must answer even when S3 is empty
        LOGGER.info("health check could not load a model: %s", error)
        model_round = None
    return {
        "status": "ok",
        "model_available": model_round is not None,
        "model_round": model_round,
        "storage_backend": StorageConfig().backend,
    }


@app.get("/model")
def model_info() -> Dict[str, Any]:
    """Describe the model currently being served, including its privacy budget."""
    HOLDER.refresh()
    if HOLDER.model is None:
        raise HTTPException(status_code=503, detail="No global model available yet")
    return {
        "run_id": HOLDER.metadata.get("run_id"),
        "round": HOLDER.metadata.get("round"),
        "accuracy": HOLDER.metadata.get("accuracy"),
        "loss": HOLDER.metadata.get("loss"),
        "privacy": HOLDER.metadata.get("privacy", {}),
        "classes": CLASS_NAMES,
        "input_size": IMAGE_SIZE,
        "loaded_at": int(HOLDER.loaded_at),
    }


@app.get("/rounds")
def rounds(run_id: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
    """Return the per-round training history that drives the dashboard chart."""
    config = StorageConfig()
    if config.backend.lower() == "s3":
        return {"rounds": _rounds_from_dynamo(config, run_id, limit)}
    return {"rounds": _rounds_from_file(config, limit)}


def _rounds_from_dynamo(
    config: StorageConfig, run_id: Optional[str], limit: int
) -> List[Dict[str, Any]]:
    import boto3
    from boto3.dynamodb.conditions import Key

    table = boto3.resource("dynamodb", region_name=config.aws_region).Table(
        config.rounds_table
    )
    if run_id:
        response = table.query(
            KeyConditionExpression=Key("run_id").eq(run_id), Limit=limit
        )
    else:
        # No run specified: scan, then keep the newest run only. The table holds
        # a handful of demo runs, so a scan is cheaper than a secondary index.
        response = table.scan(Limit=limit)
    items = _decimals_to_floats(response.get("Items", []))
    if not items:
        return []
    if not run_id:
        newest = max(items, key=lambda item: item.get("timestamp", 0))["run_id"]
        items = [item for item in items if item["run_id"] == newest]
    return sorted(items, key=lambda item: item["round"])


def _rounds_from_file(config: StorageConfig, limit: int) -> List[Dict[str, Any]]:
    import json

    path = os.path.join(config.local_root, "metrics.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as handle:
        return json.load(handle).get("rounds", [])[:limit]


def _decimals_to_floats(value: Any) -> Any:
    """DynamoDB returns Decimal, which the JSON encoder refuses to serialise."""
    from decimal import Decimal

    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, list):
        return [_decimals_to_floats(item) for item in value]
    if isinstance(value, dict):
        return {key: _decimals_to_floats(item) for key, item in value.items()}
    return value


@app.post("/predict")
async def predict(file: UploadFile = File(...)) -> Dict[str, Any]:
    """Classify one chest X-ray with the current global model."""
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty upload")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413, detail=f"Image exceeds {MAX_UPLOAD_BYTES} bytes"
        )

    model = HOLDER.get()
    array = decode_image(raw)
    tensor = data_utils.preprocess_image(array)

    with torch.no_grad():
        probabilities = torch.softmax(model(tensor), dim=1)[0]
    index = int(torch.argmax(probabilities).item())

    prediction = {
        "label": CLASS_NAMES[index],
        "confidence": round(float(probabilities[index].item()), 4),
        "probabilities": {
            name: round(float(probabilities[i].item()), 4)
            for i, name in enumerate(CLASS_NAMES)
        },
        "model_round": HOLDER.metadata.get("round"),
        "model_run_id": HOLDER.metadata.get("run_id"),
    }

    digest = hashlib.sha256(raw).hexdigest()
    write_audit_entry(digest, prediction)
    # The digest goes back to the caller so a clinician can quote it in a ticket
    # without attaching the image itself.
    prediction["request_hash"] = digest
    return prediction


# Lambda entry point. API Gateway payloads are translated by Mangum.
try:
    from mangum import Mangum

    handler = Mangum(app, lifespan="off")
except ImportError:  # pragma: no cover - only needed inside the Lambda image
    handler = None


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
