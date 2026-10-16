"""Tests for the model plumbing and the shard loader.

These cover the invariants the federation silently depends on: that a parameter
list survives a round trip through Flower's NumPy representation, that every
hospital builds the same architecture, and that a malformed shard is rejected at
load time rather than producing nonsense results twenty minutes into a run.
"""

from __future__ import annotations

import numpy as np
import pytest
import torch

from fedmed import data as data_utils
from fedmed.model import (
    CLASS_NAMES,
    IMAGE_SIZE,
    build_model,
    count_parameters,
    get_weights,
    set_weights,
)


def make_shard(count: int = 40, seed: int = 0) -> data_utils.Shard:
    rng = np.random.default_rng(seed)
    images = rng.integers(0, 256, size=(count, IMAGE_SIZE, IMAGE_SIZE), dtype=np.uint8)
    labels = rng.integers(0, len(CLASS_NAMES), size=count).astype(np.int64)
    return data_utils.Shard(images=images, labels=labels, name="synthetic")


def test_two_models_built_with_the_same_seed_are_identical():
    """Every hospital must start a run from the same weights.

    If they did not, the first FedAvg would average unrelated random networks and
    the run would spend several rounds recovering from the damage.
    """
    left = get_weights(build_model(seed=7))
    right = get_weights(build_model(seed=7))

    assert len(left) == len(right)
    for a, b in zip(left, right):
        np.testing.assert_array_equal(a, b)


def test_weights_survive_a_round_trip():
    model = build_model(seed=1)
    other = build_model(seed=2)
    original = get_weights(model)

    set_weights(other, original)

    for a, b in zip(original, get_weights(other)):
        np.testing.assert_allclose(a, b, rtol=1e-6, atol=1e-8)


def test_set_weights_rejects_the_wrong_number_of_arrays():
    model = build_model(seed=1)
    weights = get_weights(model)

    with pytest.raises(ValueError, match="parameter count mismatch"):
        set_weights(model, weights[:-1])


def test_the_parameter_list_carries_no_integer_buffers():
    """GroupNorm was chosen over BatchNorm partly for this.

    BatchNorm contributes an int64 num_batches_tracked buffer. Averaging integer
    counters across hospitals is meaningless, and it is the kind of bug that
    shows up as a slightly worse model rather than as an error.
    """
    for array in get_weights(build_model(seed=1)):
        assert np.issubdtype(array.dtype, np.floating)


def test_the_model_is_small_enough_for_a_one_vcpu_task():
    # Roughly a hundred kilobytes per round of network traffic per hospital.
    assert count_parameters(build_model()) < 100_000


def test_forward_pass_shape():
    model = build_model(seed=1)
    logits = model(torch.zeros(4, 1, IMAGE_SIZE, IMAGE_SIZE))
    assert logits.shape == (4, len(CLASS_NAMES))


def test_load_shard_round_trip(tmp_path):
    shard = make_shard(25)
    path = tmp_path / "shard.npz"
    np.savez_compressed(path, images=shard.images, labels=shard.labels)

    loaded = data_utils.load_shard(str(path))

    assert len(loaded) == 25
    np.testing.assert_array_equal(loaded.images, shard.images)
    assert sum(loaded.class_counts.values()) == 25


def test_load_shard_accepts_a_trailing_channel_axis(tmp_path):
    """MedMNIST hands back (N, H, W, 1); the loader has to squeeze it."""
    shard = make_shard(10)
    path = tmp_path / "shard.npz"
    np.savez_compressed(path, images=shard.images[..., None], labels=shard.labels)

    assert data_utils.load_shard(str(path)).images.shape == (10, IMAGE_SIZE, IMAGE_SIZE)


def test_load_shard_rejects_the_wrong_image_size(tmp_path):
    path = tmp_path / "shard.npz"
    np.savez_compressed(
        path, images=np.zeros((5, 28, 28), dtype=np.uint8), labels=np.zeros(5, dtype=np.int64)
    )

    with pytest.raises(ValueError, match="expected 64x64"):
        data_utils.load_shard(str(path))


def test_load_shard_rejects_a_label_count_mismatch(tmp_path):
    path = tmp_path / "shard.npz"
    np.savez_compressed(
        path,
        images=np.zeros((5, IMAGE_SIZE, IMAGE_SIZE), dtype=np.uint8),
        labels=np.zeros(4, dtype=np.int64),
    )

    with pytest.raises(ValueError, match="images but"):
        data_utils.load_shard(str(path))


def test_training_reduces_loss_on_a_learnable_shard():
    """A shard the model can memorise; if this does not improve, training is broken."""
    rng = np.random.default_rng(3)
    labels = np.array([0, 1] * 30, dtype=np.int64)
    images = np.stack(
        [
            (rng.integers(0, 60, (IMAGE_SIZE, IMAGE_SIZE)) if label == 0
             else rng.integers(195, 256, (IMAGE_SIZE, IMAGE_SIZE))).astype(np.uint8)
            for label in labels
        ]
    )
    shard = data_utils.Shard(images=images, labels=labels)

    model = build_model(seed=5)
    before = data_utils.evaluate(model, shard)["loss"]
    data_utils.train_local(model, shard, epochs=3, batch_size=16, learning_rate=1e-2)
    after = data_utils.evaluate(model, shard)["loss"]

    assert after < before


def test_evaluate_reports_per_class_recall():
    results = data_utils.evaluate(build_model(seed=1), make_shard(30))

    for name in CLASS_NAMES:
        assert 0.0 <= results[f"recall_{name}"] <= 1.0
    assert 0.0 <= results["accuracy"] <= 1.0


def test_preprocess_image_normalises_to_a_single_batch():
    tensor = data_utils.preprocess_image(
        np.full((IMAGE_SIZE, IMAGE_SIZE), 255, dtype=np.uint8)
    )

    assert tensor.shape == (1, 1, IMAGE_SIZE, IMAGE_SIZE)
    assert torch.allclose(tensor, torch.ones_like(tensor))
