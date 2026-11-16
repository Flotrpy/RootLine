"""Python mirror of controller/internal/catalog.

The Go catalog is the source of truth; tests/test_catalog.py fails if the two
drift apart.
"""

from __future__ import annotations

from typing import Final

SERVICES: Final[tuple[str, ...]] = (
    "accounting",
    "ad",
    "cart",
    "checkout",
    "currency",
    "email",
    "flagd",
    "fraud-detection",
    "frontend",
    "frontend-proxy",
    "image-provider",
    "kafka",
    "load-generator",
    "payment",
    "product-catalog",
    "quote",
    "recommendation",
    "shipping",
    "valkey-cart",
)
"""OpenTelemetry Demo services, used to tell the model which names are valid
and to drive P1 anonymisation.

Checked against the 42 v0.1 snapshots: frontend-web (browser spans) and
telemetry-docs also appear in the evidence, and kafka and valkey-cart emit no
spans. No fault targets any of them; the list stays as it was so every v0.1
prompt is identical (a limitation, noted in the README).
"""

CATEGORIES: Final[tuple[str, ...]] = (
    "cpu_saturation",
    "dependency_unavailable",
    "error",
    "latency",
    "lock_contention",
    "memory_leak",
    "network_latency",
    "network_loss",
    "network_reset",
    "network_throughput",
    "none",
    "queue_lag",
)

FAULTS: Final[tuple[str, ...]] = (
    "paymentFailure",
    "paymentUnreachable",
    "productCatalogFailure",
    "productCatalogLockContention",
    "emailMemoryLeak",
    "recommendationCacheFailure",
    "kafkaQueueProblems",
    "intlShippingSlowdown",
    "imageSlowLoad",
    "adHighCpu",
    "toxiLatency",
    "netemLoss",
    "toxiReset",
    "toxiBandwidth",
    "healthy",
)

FLAGS: Final[tuple[str, ...]] = FAULTS[:10]

HW_FAULTS: Final[tuple[str, ...]] = ("hwWeakSignal", "hwContention", "hwWifiOutage")
"""Phase 3 hardware arm: real Wi-Fi faults, outside the 15-type pilot."""

HW_EMULATES: Final[dict[str, str]] = {
    "hwWeakSignal": "netemLoss",
    "hwContention": "toxiLatency",
    "hwWifiOutage": "toxiReset",
}
"""Each hardware fault's emulated counterpart, for emulation validity."""

EDGES: Final[tuple[str, ...]] = ("checkout->payment", "frontend->product-catalog")


def forbidden_strings() -> tuple[str, ...]:
    """Strings that would reveal the label if they reached a model.

    Every fault and flag name is redacted from every pack, not only the
    current incident's, so redaction itself reveals nothing.
    """
    return tuple(sorted((set(FAULTS) | set(FLAGS) | set(HW_FAULTS)) - {"healthy"}))
