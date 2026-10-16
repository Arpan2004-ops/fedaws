"""Tests for the privacy accountant and the checkpoint storage.

The accountant produces a number that goes straight into the report, so it is
checked against the properties an epsilon must have rather than against a value
copied out of a previous run.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from fedmed.metrics import LocalMetrics
from fedmed.privacy import build_report, compute_epsilon
from fedmed.storage import LocalStorage


# ------------------------------------------------------------------ privacy


def test_no_noise_means_no_finite_budget():
    assert compute_epsilon(0.0, 10) is None


def test_more_noise_buys_a_smaller_epsilon():
    quiet = compute_epsilon(0.4, 10)
    loud = compute_epsilon(1.2, 10)

    assert loud < quiet


def test_more_rounds_spend_more_budget():
    assert compute_epsilon(1.0, 20) > compute_epsilon(1.0, 10)


def test_subsampling_amplifies_privacy():
    """Selecting a fraction of clients each round should lower epsilon.

    This is the property the report leans on when explaining why three
    hospitals cannot reach a tight budget: with everyone participating every
    round there is no amplification to collect.
    """
    everyone = compute_epsilon(1.0, 10, sampling_rate=1.0)
    a_tenth = compute_epsilon(1.0, 10, sampling_rate=0.1)

    assert a_tenth < everyone


def test_epsilon_is_positive_and_finite():
    epsilon = compute_epsilon(0.8, 15, 1.0, 1e-5)

    assert epsilon > 0
    assert np.isfinite(epsilon)


def test_a_looser_delta_gives_a_smaller_epsilon():
    assert compute_epsilon(1.0, 10, delta=1e-3) < compute_epsilon(1.0, 10, delta=1e-7)


def test_disabled_report_records_the_mechanism_as_none():
    report = build_report(0.5, 1.0, 10, 3, enabled=False)

    assert report.mechanism == "none"
    assert report.epsilon is None
    assert report.noise_multiplier == 0.0


def test_report_serialises_for_the_dashboard():
    payload = build_report(0.5, 1.0, 10, 3).as_dict()

    assert json.loads(json.dumps(payload))["rounds"] == 10
    assert payload["sampling_rate"] == 1.0


def test_report_records_partial_participation():
    report = build_report(1.0, 1.0, 10, num_clients=10, clients_per_round=3)

    assert report.sampling_rate == pytest.approx(0.3)


# ------------------------------------------------------------------ storage


def weights():
    return [np.arange(6, dtype=np.float32).reshape(2, 3), np.ones(4, dtype=np.float32)]


def test_checkpoint_round_trip(tmp_path):
    storage = LocalStorage(str(tmp_path))
    original = weights()

    storage.save_checkpoint(3, original, {"run_id": "test", "round": 3, "accuracy": 0.9})
    restored, metadata = storage.load_latest()

    assert metadata["round"] == 3
    assert metadata["accuracy"] == 0.9
    for a, b in zip(original, restored):
        np.testing.assert_array_equal(a, b)


def test_each_round_is_kept_as_its_own_object(tmp_path):
    """Versioned checkpoints are the audit trail; overwriting would destroy it."""
    storage = LocalStorage(str(tmp_path))

    for round_number in (1, 2, 3):
        storage.save_checkpoint(round_number, weights(), {"round": round_number})

    for round_number in (1, 2, 3):
        assert (tmp_path / "global" / f"round_{round_number:03d}.npz").exists()


def test_latest_tracks_the_most_recent_round(tmp_path):
    storage = LocalStorage(str(tmp_path))

    storage.save_checkpoint(1, weights(), {"round": 1})
    storage.save_checkpoint(2, weights(), {"round": 2})

    assert storage.load_latest()[1]["round"] == 2


def test_write_and_read_json(tmp_path):
    storage = LocalStorage(str(tmp_path))

    storage.write_json("global/summary.json", {"final_accuracy": 0.88})
    payload = json.loads(storage.read_bytes("global/summary.json").decode("utf-8"))

    assert payload["final_accuracy"] == 0.88


# ------------------------------------------------------------------ metrics


def test_local_metrics_accumulates_rounds(tmp_path):
    path = tmp_path / "metrics.json"
    sink = LocalMetrics(str(path))

    sink.record_round("run-1", 1, {"accuracy": 0.7})
    sink.record_round("run-1", 2, {"accuracy": 0.8})

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert [entry["round"] for entry in payload["rounds"]] == [1, 2]
    assert payload["rounds"][1]["accuracy"] == 0.8
    assert payload["run_id"] == "run-1"
