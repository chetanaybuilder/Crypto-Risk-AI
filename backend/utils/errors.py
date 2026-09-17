"""
Domain Exception Definitions.

Defines typed errors for domain-specific failure modes across market data
resolution and upstream provider communication.
"""


class MarketDataUnavailableError(RuntimeError):
    """Raised when upstream market telemetry providers cannot return a usable snapshot."""


class UnsupportedAssetError(ValueError):
    """Raised when an asset ticker cannot be resolved to a recognized market identifier."""
