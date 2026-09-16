class MarketDataUnavailableError(RuntimeError):
    """Raised when CoinGecko cannot provide a usable market snapshot."""


class UnsupportedAssetError(ValueError):
    """Raised when a ticker has no verified CoinGecko asset ID."""


