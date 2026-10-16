"""The classification model shared by every hospital and the aggregator.

A deliberately small CNN: it has to converge on a single Fargate vCPU in seconds
per epoch so a live classroom demo never stalls, while still being a real
convolutional network rather than a toy linear model.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import List

import numpy as np
import torch
import torch.nn as nn

IMAGE_SIZE = 64
NUM_CLASSES = 2
CLASS_NAMES = ["normal", "pneumonia"]


class PneumoniaCNN(nn.Module):
    """Three convolution blocks then a small classifier head.

    GroupNorm is used instead of BatchNorm on purpose. BatchNorm carries running
    mean/variance buffers that are computed on each hospital's own class
    distribution; averaging those across non-IID hospitals is known to degrade
    federated accuracy, and the integer ``num_batches_tracked`` buffer does not
    survive a weighted average cleanly. GroupNorm is stateless, so the parameter
    list Flower exchanges contains only learnable weights.
    """

    def __init__(self, num_classes: int = NUM_CLASSES) -> None:
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 16, kernel_size=3, padding=1),
            nn.GroupNorm(4, 16),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),  # 64 -> 32
            nn.Conv2d(16, 32, kernel_size=3, padding=1),
            nn.GroupNorm(8, 32),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),  # 32 -> 16
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.GroupNorm(8, 64),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),  # 16 -> 8
        )
        self.pool = nn.AdaptiveAvgPool2d(1)
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Dropout(0.2),
            nn.Linear(64, num_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.features(x)
        x = self.pool(x)
        return self.classifier(x)


def build_model(seed: int | None = None) -> PneumoniaCNN:
    """Create a model with a deterministic initialisation.

    Every hospital must start from identical weights, otherwise the first round
    of averaging mixes unrelated random networks.
    """
    if seed is not None:
        torch.manual_seed(seed)
    return PneumoniaCNN()


def get_weights(model: nn.Module) -> List[np.ndarray]:
    """Flower speaks lists of NumPy arrays, not torch state dicts."""
    return [value.detach().cpu().numpy() for value in model.state_dict().values()]


def set_weights(model: nn.Module, weights: List[np.ndarray]) -> None:
    """Load a Flower parameter list back into a torch model."""
    keys = list(model.state_dict().keys())
    if len(keys) != len(weights):
        raise ValueError(
            f"parameter count mismatch: model has {len(keys)}, received {len(weights)}"
        )
    state_dict = OrderedDict(
        (key, torch.tensor(np.asarray(value))) for key, value in zip(keys, weights)
    )
    model.load_state_dict(state_dict, strict=True)


def count_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())


__all__ = [
    "CLASS_NAMES",
    "IMAGE_SIZE",
    "NUM_CLASSES",
    "PneumoniaCNN",
    "build_model",
    "count_parameters",
    "get_weights",
    "set_weights",
]
