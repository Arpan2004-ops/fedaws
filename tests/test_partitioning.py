"""Tests for the data split.

The central claim of the project is that no image is in two places at once. That
claim is only as good as the partitioner, so it is tested directly rather than
assumed.
"""

from __future__ import annotations

import importlib.util
import os

import numpy as np
import pytest

SCRIPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "partition_data.py"
)


def load_partition_module():
    """Import the script by path; scripts/ is not an installed package."""
    spec = importlib.util.spec_from_file_location("partition_data", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def partition():
    return load_partition_module()


def make_labels(count: int = 900, pneumonia_ratio: float = 0.74) -> np.ndarray:
    """Labels with roughly the class balance of the real training split."""
    pneumonia = int(count * pneumonia_ratio)
    labels = np.array([1] * pneumonia + [0] * (count - pneumonia), dtype=np.int64)
    np.random.default_rng(0).shuffle(labels)
    return labels


def test_dirichlet_shards_are_disjoint(partition):
    labels = make_labels()
    parts = partition.dirichlet_split(labels, 3, 0.5, np.random.default_rng(42))

    combined = np.concatenate(parts)
    assert len(np.unique(combined)) == len(combined)


def test_dirichlet_shards_cover_every_sample(partition):
    labels = make_labels()
    parts = partition.dirichlet_split(labels, 3, 0.5, np.random.default_rng(42))

    combined = np.sort(np.concatenate(parts))
    np.testing.assert_array_equal(combined, np.arange(len(labels)))


def test_dirichlet_actually_produces_unequal_hospitals(partition):
    """A split that came out balanced would make the whole demo pointless.

    With alpha = 0.5 the sites should differ noticeably in class balance. The
    threshold is loose because the draw is random; it is here to catch a
    partitioner that has silently become uniform, not to pin an exact value.
    """
    labels = make_labels()
    parts = partition.dirichlet_split(labels, 3, 0.5, np.random.default_rng(42))

    ratios = [
        float(np.mean(labels[part] == 1)) for part in parts if len(part) > 0
    ]
    assert max(ratios) - min(ratios) > 0.1


def test_iid_split_is_disjoint_and_balanced(partition):
    labels = make_labels()
    parts = partition.iid_split(labels, 3, np.random.default_rng(7))

    combined = np.concatenate(parts)
    assert len(np.unique(combined)) == len(labels)

    sizes = [len(part) for part in parts]
    assert max(sizes) - min(sizes) <= 1

    ratios = [float(np.mean(labels[part] == 1)) for part in parts]
    assert max(ratios) - min(ratios) < 0.1


def test_describe_reports_counts_and_ratio(partition):
    labels = np.array([0, 0, 1, 1, 1, 1], dtype=np.int64)

    summary = partition.describe(labels)

    assert summary["examples"] == 6
    assert summary["class_counts"] == {"normal": 2, "pneumonia": 4}
    assert summary["pneumonia_ratio"] == pytest.approx(0.6667, abs=1e-4)


def test_the_same_seed_reproduces_the_same_split(partition):
    """Reproducibility matters for the report: the numbers have to be defensible."""
    labels = make_labels()

    first = partition.dirichlet_split(labels, 3, 0.5, np.random.default_rng(11))
    second = partition.dirichlet_split(labels, 3, 0.5, np.random.default_rng(11))

    for left, right in zip(first, second):
        np.testing.assert_array_equal(left, right)
