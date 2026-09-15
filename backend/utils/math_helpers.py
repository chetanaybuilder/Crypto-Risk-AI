from typing import Any, List, Optional, Tuple, Dict
import math
from utils.helpers import *

def standard_deviation(
    values: list,
    sample: bool = False,
) -> float:
    """
    Standard deviation of a value list.

    sample=False (default): population std dev (divide by N).
    sample=True: sample std dev (divide by N-1) — the correct
    unbiased estimator for return series, which typically have
    very few observations (e.g. 7 daily returns from 8 candles).
    Population std dev understates volatility by ~sqrt((N-1)/N),
    which matters at these small sample sizes (~6.5% low).
    """

    if not isinstance(
        values,
        list,
    ):
        return 0.0

    cleaned = [
        numeric(value)
        for value in values
        if optional_numeric(value)
        is not None
    ]

    min_points = 3 if sample else 2

    if len(cleaned) < min_points:
        return 0.0

    avg = mean(cleaned)

    divisor = (
        (len(cleaned) - 1)
        if sample
        else len(cleaned)
    )

    variance_value = (
        sum(
            (
                value - avg
            ) ** 2
            for value in cleaned
        )
        / divisor
    )

    return math.sqrt(
        max(
            variance_value,
            0.0,
        )
    )


def covariance(
    values_a: list,
    values_b: list,
) -> float:

    if (
        not isinstance(
            values_a,
            list,
        )
        or not isinstance(
            values_b,
            list,
        )
    ):
        return 0.0

    pairs = [
        (
            numeric(a),
            numeric(b),
        )
        for a, b in zip(
            values_a,
            values_b,
        )
        if optional_numeric(a)
        is not None
        and optional_numeric(b)
        is not None
    ]

    if len(pairs) < 2:
        return 0.0

    a_values = [
        pair[0]
        for pair in pairs
    ]

    b_values = [
        pair[1]
        for pair in pairs
    ]

    mean_a = mean(a_values)
    mean_b = mean(b_values)

    return mean(
        [
            (
                (a - mean_a)
                * (b - mean_b)
            )
            for a, b in pairs
        ]
    )


def variance(
    values: list,
) -> float:

    if not isinstance(
        values,
        list,
    ):
        return 0.0

    cleaned = [
        numeric(value)
        for value in values
        if optional_numeric(value)
        is not None
    ]

    if len(cleaned) < 2:
        return 0.0

    avg = mean(cleaned)

    return mean(
        [
            (
                value - avg
            ) ** 2
            for value in cleaned
        ]
    )


def calculate_returns(
    prices: list,
) -> list:

    if not isinstance(
        prices,
        list,
    ):
        return []

    cleaned = [
        optional_numeric(price)
        for price in prices
    ]

    cleaned = [
        price
        for price in cleaned
        if (
            price is not None
            and price > 0
        )
    ]

    if len(cleaned) < 2:
        return []

    returns = []

    for previous, current in zip(
        cleaned,
        cleaned[1:],
    ):

        if previous <= 0:
            continue

        returns.append(
            (
                current - previous
            )
            / previous
        )

    return returns


def max_drawdown(
    prices: list,
) -> float:
    """
    Calculate maximum drawdown from a price series.

    Methodology:
        Track running peak; compute drawdown at each point as
        (price - peak) / peak * 100. Return the absolute value
        of the largest observed decline.

    This measures the worst peak-to-tail decline an investor
    would have experienced holding the asset over the period.

    Returns:
        float: Maximum drawdown as a positive percentage
    """

    cleaned = [
        optional_numeric(price)
        for price in prices
    ]

    cleaned = [
        price
        for price in cleaned
        if (
            price is not None
            and price > 0
        )
    ]

    if not cleaned:
        return 0.0

    peak = cleaned[0]
    maximum_drawdown = 0.0

    for price in cleaned:

        if price > peak:
            peak = price

        if peak <= 0:
            continue

        # Drawdown from peak as percentage (negative value)
        drawdown = (
            (
                price - peak
            )
            / peak
        ) * 100.0

        maximum_drawdown = min(
            maximum_drawdown,
            drawdown,
        )

    return abs(
        numeric(
            maximum_drawdown
        )
    )


def realized_volatility(
    prices: list,
) -> dict:
    """
    Compute realized volatility from a daily price series.

    Methodology:
        1. Calculate log returns: ln(current / previous)
        2. Compute SAMPLE standard deviation of returns
           (divide by N-1 — the unbiased estimator; with only
           ~7 daily returns the population estimator understates
           volatility by ~6.5%)
        3. Annualize: daily_std * sqrt(365) * 100
           (365 because crypto trades 24/7)

    Returns:
        dict: daily_volatility_pct, annualized_volatility_pct, observations
    """

    try:

        if not isinstance(
            prices,
            list,
        ):
            prices = []

        # Log returns: ln(current / previous).
        # More precise than simple returns for volatile series —
        # a +15% day contributes ln(1.15) ≈ 13.98%, not 15%,
        # so volatility is not overstated by asymmetric moves.
        cleaned = [
            optional_numeric(price)
            for price in prices
        ]

        cleaned = [
            price
            for price in cleaned
            if (
                price is not None
                and price > 0
            )
        ]

        returns = []

        for previous, current in zip(
            cleaned,
            cleaned[1:],
        ):

            if previous <= 0 or current <= 0:
                continue

            returns.append(
                math.log(
                    current / previous
                )
            )

        if len(returns) < 2:

            return json_safe({
                "daily_volatility_pct": None,
                "annualized_volatility_pct": None,
                "observations": len(
                    returns
                ),
            })

        daily_std = standard_deviation(
            returns,
            sample=True,
        )

        daily_std = numeric(
            daily_std,
            default=0.0,
        )

        # Annualization factor: sqrt(365) for daily data
        annualized = (
            daily_std
            * math.sqrt(365)
            * 100.0
        )

        return json_safe({
            "daily_volatility_pct": numeric(
                daily_std * 100.0
            ),
            "annualized_volatility_pct": numeric(
                annualized
            ),
            "observations": len(
                returns
            ),
        })

    except Exception as exc:

        logger.debug(
            "realized_volatility failed: %s",
            exc,
        )

        return {
            "daily_volatility_pct": None,
            "annualized_volatility_pct": None,
            "observations": 0,
        }


def calculate_beta(
    asset_prices: list,
    btc_prices: list,
) -> dict:
    """
    Calculate BTC beta (market sensitivity) for an asset.

    Methodology:
        Beta = Cov(asset_returns, btc_returns) / Var(btc_returns)

    A beta of 1.0 indicates the asset moves in line with BTC.
    Beta > 1.0 indicates amplified sensitivity to BTC movements.

    Returns:
        dict: beta coefficient and observation count
    """

    try:

        # P2: align by calendar date rather than by raw list position.
        # This guarantees that a return on day T for the asset is always
        # paired with a return on day T for BTC, even if the two series
        # have different lengths or small gaps (e.g. a newly-listed coin).
        aligned_asset, btc_aligned, aligned_dates = _align_series_by_date(
            asset_prices,
            btc_prices,
        )

        asset_returns = calculate_returns(
            aligned_asset
        )

        btc_returns = calculate_returns(
            btc_aligned
        )

        if not isinstance(
            asset_returns,
            list,
        ):
            asset_returns = []

        if not isinstance(
            btc_returns,
            list,
        ):
            btc_returns = []

        length = min(
            len(asset_returns),
            len(btc_returns),
        )

        if length < 2:

            return json_safe({
                "beta": None,
                "observations": int(length),
            })

        asset_returns = asset_returns[
            -length:
        ]

        btc_returns = btc_returns[
            -length:
        ]

        logger.info(
            "[BETA] %d aligned return observations over %s to %s",
            length,
            aligned_dates[0].isoformat() if aligned_dates else "?",
            aligned_dates[-1].isoformat() if aligned_dates else "?",
        )

        btc_variance = variance(
            btc_returns
        )

        btc_variance = optional_numeric(
            btc_variance
        )

        if (
            btc_variance is None
            or btc_variance <= 0
        ):

            return json_safe({
                "beta": None,
                "observations": int(length),
            })

        covariance_value = optional_numeric(
            covariance(
                asset_returns,
                btc_returns,
            )
        )

        if covariance_value is None:

            return json_safe({
                "beta": None,
                "observations": int(length),
            })

        # Beta = Cov(asset, BTC) / Var(BTC)
        beta = safe_divide(
            covariance_value,
            btc_variance,
            default=0.0,
        )

        beta_value = optional_numeric(beta)

        return json_safe({
            "beta": beta_value,
            "observations": int(length),
        })

    except Exception as exc:

        logger.debug(
            "calculate_beta failed: %s",
            exc,
        )

        return {
            "beta": None,
            "observations": 0,
        }


def calculate_liquidity_metrics(
    market: dict,
) -> dict:
    """
    Estimate liquidity risk from market structure.

    Methodology:
        Turnover ratio = (24h_volume / market_cap) * 100

    Higher turnover indicates deeper markets and lower exit risk.
    This ratio is used by score_liquidity() to generate a 0-100 risk score.

    Returns:
        dict: volume_24h, market_cap, turnover_pct
    """

    try:

        if not isinstance(
            market,
            dict,
        ):
            market = {}

        volume = optional_numeric(
            market.get(
                "volume_24h"
            )
        )

        market_cap = optional_numeric(
            market.get(
                "market_cap"
            )
        )

        turnover = None

        if (
            volume is not None
            and market_cap is not None
            and market_cap > 0
            and volume >= 0
        ):

            try:

                # Turnover as percentage: higher = more liquid
                turnover_value = (
                    volume
                    / market_cap
                ) * 100.0

                turnover = optional_numeric(
                    turnover_value
                )

            except (
                ZeroDivisionError,
                ArithmeticError,
                TypeError,
                ValueError,
                OverflowError,
            ) as exc:

                logger.debug(
                    "Liquidity turnover failed: %s",
                    exc,
                )

                turnover = None

        return json_safe({
            "volume_24h": volume,
            "market_cap": market_cap,
            "turnover_pct": turnover,
        })

    except Exception as exc:

        logger.debug(
            "calculate_liquidity_metrics failed: %s",
            exc,
        )

        return {
            "volume_24h": None,
            "market_cap": None,
            "turnover_pct": None,
        }


def calculate_quant_metrics(
    symbol: str,
    market: dict,
    history: list,
    btc_history: list,
) -> dict:

    try:

        symbol = normalize_symbol(
            symbol
        )

        if not isinstance(
            market,
            dict,
        ):
            market = {}

        if not isinstance(
            history,
            list,
        ):
            history = []

        if not isinstance(
            btc_history,
            list,
        ):
            btc_history = []

        # FIX (Bug 3): history is now a list of {"timestamp": ..., "price": ...}
        # dicts (P2 format). Functions like realized_volatility(), max_drawdown(),
        # and calculate_returns() expect bare floats. Extract prices first.
        history_prices = _prices_only(history)

        volatility = realized_volatility(
            history_prices
        )

        # calculate_beta uses _align_series_by_date internally,
        # which expects the rich P2 format with timestamps.
        beta = calculate_beta(
            history,
            btc_history,
        )

        liquidity = calculate_liquidity_metrics(
            market
        )

        drawdown = max_drawdown(
            history_prices
        )

        returns = calculate_returns(
            history_prices
        )

        current_price = optional_numeric(
            market.get("price")
        )

        # FIX (Bug 4): history[-1] is now a dict, not a float.
        # Extract the price float from the last entry.
        historical_price = (
            history_prices[-1]
            if history_prices
            else None
        )

        price_change_from_history = (
            percentage_change(
                current_price,
                historical_price,
            )
            if (
                current_price is not None
                and historical_price is not None
            )
            else None
        )

        return json_safe({
            "symbol": symbol,

            "volatility": volatility,

            "beta": beta,

            "liquidity": liquidity,

            "max_drawdown_pct": drawdown,

            "return_observations": len(
                returns
            ),

            "price_change_from_history_pct": (
                price_change_from_history
            ),

            "history_observations": len(
                history
            ),

            "btc_history_observations": len(
                btc_history
            ),
        })

    except Exception as exc:

        logger.warning(
            "quant metrics failed; returning safe defaults: %s",
            exc,
        )

        return json_safe({
            "symbol": normalize_symbol(
                symbol
            ),
            "volatility": {
                "daily_volatility_pct": None,
                "annualized_volatility_pct": None,
                "observations": 0,
            },
            "beta": {
                "beta": None,
                "observations": 0,
            },
            "liquidity": {
                "volume_24h": None,
                "market_cap": None,
                "turnover_pct": None,
            },
            "max_drawdown_pct": 0.0,
            "return_observations": 0,
            "price_change_from_history_pct": None,
            "history_observations": 0,
            "btc_history_observations": 0,
        })


def extract_volatility_value(
    quant,
    market=None,
):
    """
    Extract the scalar annualized volatility used by the
    risk engine.

    PART 1 stores volatility as a nested dictionary.
    """

    quant = quant or {}
    market = market or {}

    volatility = quant.get(
        "volatility"
    )

    if isinstance(volatility, dict):
        volatility = first_defined(
            volatility.get(
                "annualized_volatility_pct"
            ),
            volatility.get(
                "annualized_pct"
            ),
        )

    if volatility is None:
        volatility = market.get(
            "volatility"
        )

    return optional_numeric(
        volatility
    )


def extract_beta_value(
    quant,
):
    """
    Extract scalar BTC beta from the nested beta structure
    produced by PART 1.
    """

    quant = quant or {}

    beta = quant.get(
        "beta"
    )

    if isinstance(beta, dict):
        beta = beta.get(
            "beta"
        )

    return optional_numeric(
        beta
    )


