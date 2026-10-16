"""Differential-privacy accounting for the report and the dashboard.

Flower applies the mechanism itself: clip every client update to a fixed L2 norm,
then add Gaussian noise to the aggregate. What it does not give you is the
privacy budget, so this module converts a noise multiplier and a round count into
an epsilon at a chosen delta using Renyi differential privacy.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional

# The RDP order grid used by the Opacus and TF-Privacy accountants.
_INTEGER_ORDERS: List[int] = list(range(2, 64)) + [128, 256, 512]


@dataclass
class PrivacyReport:
    """A privacy budget statement that can be quoted directly in the report."""

    mechanism: str
    noise_multiplier: float
    clipping_norm: float
    sampling_rate: float
    rounds: int
    delta: float
    epsilon: Optional[float]

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)


def _log_add(logx: float, logy: float) -> float:
    """Numerically stable log(exp(logx) + exp(logy))."""
    if logx == -math.inf:
        return logy
    if logy == -math.inf:
        return logx
    lower, higher = min(logx, logy), max(logx, logy)
    return higher + math.log1p(math.exp(lower - higher))


def _log_comb(n: int, k: int) -> float:
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def _rdp_sampled_gaussian(q: float, noise_multiplier: float, alpha: int) -> float:
    """RDP of the sampled Gaussian mechanism at an integer order.

    Binomial expansion from Mironov, Talwar and Zhang, 2019.
    """
    if q >= 1.0:
        # Full participation: the plain Gaussian mechanism.
        return alpha / (2.0 * noise_multiplier**2)

    log_terms = -math.inf
    for i in range(alpha + 1):
        log_term = (
            _log_comb(alpha, i)
            + i * math.log(q)
            + (alpha - i) * math.log1p(-q)
            + (i * i - i) / (2.0 * noise_multiplier**2)
        )
        log_terms = _log_add(log_terms, log_term)
    return float(log_terms) / (alpha - 1)


def compute_epsilon(
    noise_multiplier: float,
    rounds: int,
    sampling_rate: float = 1.0,
    delta: float = 1e-5,
) -> Optional[float]:
    """Convert a noise multiplier and round count into an (epsilon, delta) budget.

    Returns ``None`` when noise is switched off, because no finite budget exists.
    """
    if noise_multiplier <= 0 or rounds <= 0:
        return None
    sampling_rate = min(max(sampling_rate, 1e-12), 1.0)

    best = math.inf
    for alpha in _INTEGER_ORDERS:
        rdp = rounds * _rdp_sampled_gaussian(sampling_rate, noise_multiplier, alpha)
        # Canonne, Kamath and Steinke, 2020: a tight RDP to (eps, delta) conversion.
        epsilon = (
            rdp
            + math.log1p(-1.0 / alpha)
            - (math.log(delta) + math.log(alpha)) / (alpha - 1)
        )
        best = min(best, epsilon)
    if not math.isfinite(best):
        return None
    return max(best, 0.0)


def build_report(
    noise_multiplier: float,
    clipping_norm: float,
    rounds: int,
    num_clients: int,
    clients_per_round: Optional[int] = None,
    delta: float = 1e-5,
    enabled: bool = True,
) -> PrivacyReport:
    """Assemble the privacy statement shown on the dashboard."""
    if not enabled or noise_multiplier <= 0:
        return PrivacyReport(
            mechanism="none",
            noise_multiplier=0.0,
            clipping_norm=clipping_norm,
            sampling_rate=1.0,
            rounds=rounds,
            delta=delta,
            epsilon=None,
        )
    sampled = clients_per_round or num_clients
    sampling_rate = sampled / max(num_clients, 1)
    return PrivacyReport(
        mechanism="server-side fixed clipping with Gaussian noise",
        noise_multiplier=noise_multiplier,
        clipping_norm=clipping_norm,
        sampling_rate=sampling_rate,
        rounds=rounds,
        delta=delta,
        epsilon=compute_epsilon(noise_multiplier, rounds, sampling_rate, delta),
    )


__all__ = ["PrivacyReport", "build_report", "compute_epsilon"]
