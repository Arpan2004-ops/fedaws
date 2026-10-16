"""End-to-end tests for the public API.

These run the real FastAPI application against a checkpoint written to a
temporary directory, so they exercise the same code path the Lambda uses,
including the model cache and the image decoder.

The privacy assertions are the point of this file. A regression that started
persisting uploads would still pass every accuracy test, so it is checked here
explicitly.
"""

from __future__ import annotations

import importlib
import io
import os
import sys

import numpy as np
import pytest
from PIL import Image

from fedmed.model import IMAGE_SIZE, build_model, get_weights
from fedmed.storage import LocalStorage

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API_DIR = os.path.join(REPO_ROOT, "inference_api")


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A test client backed by a freshly written checkpoint.

    The application module is imported after the environment is set, because it
    reads the storage configuration at import time.
    """
    storage = LocalStorage(str(tmp_path))
    storage.save_checkpoint(
        4,
        get_weights(build_model(seed=42)),
        {
            "run_id": "test-run",
            "round": 4,
            "accuracy": 0.88,
            "loss": 0.31,
            "privacy": {"mechanism": "none", "epsilon": None, "delta": 1e-5},
        },
    )

    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_ROOT", str(tmp_path))
    monkeypatch.setenv("AUDIT_ENABLED", "false")
    monkeypatch.syspath_prepend(API_DIR)
    sys.modules.pop("app", None)

    from fastapi.testclient import TestClient

    app_module = importlib.import_module("app")
    with TestClient(app_module.app) as test_client:
        yield test_client, tmp_path

    sys.modules.pop("app", None)


def png_bytes(value: int = 200, size: int = IMAGE_SIZE) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(np.full((size, size), value, dtype=np.uint8)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_health_reports_the_published_round(client):
    test_client, _ = client

    payload = test_client.get("/health").json()

    assert payload["status"] == "ok"
    assert payload["model_available"] is True
    assert payload["model_round"] == 4


def test_model_endpoint_describes_the_checkpoint(client):
    test_client, _ = client

    payload = test_client.get("/model").json()

    assert payload["round"] == 4
    assert payload["run_id"] == "test-run"
    assert payload["classes"] == ["normal", "pneumonia"]
    assert payload["privacy"]["mechanism"] == "none"


def test_predict_returns_a_calibrated_distribution(client):
    test_client, _ = client

    payload = test_client.post("/predict", files={"file": ("x.png", png_bytes(), "image/png")}).json()

    assert payload["label"] in {"normal", "pneumonia"}
    assert 0.0 <= payload["confidence"] <= 1.0
    assert sum(payload["probabilities"].values()) == pytest.approx(1.0, abs=1e-3)
    assert payload["model_round"] == 4


def test_predict_accepts_an_image_that_is_not_already_64_pixels(client):
    """A clinician uploading a full-resolution film should not have to resize it."""
    test_client, _ = client

    response = test_client.post(
        "/predict", files={"file": ("x.png", png_bytes(size=512), "image/png")}
    )

    assert response.status_code == 200


def test_predict_returns_a_stable_hash_for_identical_bytes(client):
    test_client, _ = client
    raw = png_bytes()

    first = test_client.post("/predict", files={"file": ("a.png", raw, "image/png")}).json()
    second = test_client.post("/predict", files={"file": ("b.png", raw, "image/png")}).json()

    assert first["request_hash"] == second["request_hash"]
    assert len(first["request_hash"]) == 64


def test_predict_never_writes_the_uploaded_image_anywhere(client):
    """The privacy claim in the report, asserted rather than described.

    The only file the API is allowed to create is nothing at all: the checkpoint
    directory it read from must look exactly the same afterwards.
    """
    test_client, root = client
    before = sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())

    test_client.post("/predict", files={"file": ("scan.png", png_bytes(), "image/png")})

    after = sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())
    assert before == after


def test_predict_rejects_an_empty_upload(client):
    test_client, _ = client

    response = test_client.post("/predict", files={"file": ("empty.png", b"", "image/png")})

    assert response.status_code == 400


def test_predict_rejects_something_that_is_not_an_image(client):
    test_client, _ = client

    response = test_client.post(
        "/predict", files={"file": ("notes.txt", b"this is not a chest x-ray", "text/plain")}
    )

    assert response.status_code == 400
    assert "Unreadable image" in response.json()["detail"]


def test_rounds_endpoint_reads_the_local_metrics_file(client, tmp_path):
    test_client, root = client
    import json

    with open(os.path.join(str(root), "metrics.json"), "w", encoding="utf-8") as handle:
        json.dump({"run_id": "test-run", "rounds": [{"round": 1, "accuracy": 0.7}]}, handle)

    payload = test_client.get("/rounds").json()

    assert payload["rounds"][0]["accuracy"] == 0.7


def test_rounds_endpoint_is_empty_before_the_first_run(client):
    test_client, _ = client

    assert test_client.get("/rounds").json()["rounds"] == []
