import logging
import math
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from utils.helpers import (
    clamp,
    first_defined,
    json_safe,
    normalize_symbol,
    numeric,
    optional_numeric,
    percentage_change,
    safe_divide,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal numeric helpers
# ---------------------------------------------------------------------------

def _finite_float(value: Any) -> Optional[float]:
    """
    Convert value to a finite float.

    Unlike numeric(), invalid values remain None so that bad market data
    cannot silently become a legitimate zero inside statistical calculations.
    """
    value = optional_numeric(value)

    if value is None:
        return None

    if not math.isfinite(value):
        return None

    return value


def _mean(values: List[float]) -> float:
    """
    Numerically safer arithmetic mean.

    math.fsum() reduces floating-point accumulation error compared with
    ordinary sum() for large or heterogeneous values.
    """
    if not values:
        return 0.0

    return math.fsum(values) / len(values)


def _timestamp_to_datetime(value: Any) -> Optional[datetime]:
    """
    Normalize supported timestamps to timezone-aware UTC datetimes.

    Supported:
        - datetime
        - date
        - Unix seconds
        - Unix milliseconds
        - ISO-8601 strings
    """

    if value is None:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(
                tzinfo=timezone.utc
            )

        return value.astimezone(
            timezone.utc
        )

    if isinstance(value, date):
        return datetime(
            value.year,
            value.month,
            value.day,
            tzinfo=timezone.utc,
        )

    numeric_timestamp = _finite_float(value)

    if numeric_timestamp is not None:
        # Millisecond Unix timestamps are normally > 10^11.
        if abs(numeric_timestamp) > 10_000_000_000:
            numeric_timestamp /= 1000.0

        try:
            return datetime.fromtimestamp(
                numeric_timestamp,
                tz=timezone.utc,
            )
        except (
            OverflowError,
            OSError,
            ValueError,
        ):
            return None

    if isinstance(value, str):
        text = value.strip()

        if not text:
            return None

        # Numeric strings may be Unix timestamps.
        numeric_string = _finite_float(text)

        if numeric_string is not None:
            return _timestamp_to_datetime(
                numeric_string
            )

        # Handle common ISO-8601 UTC suffix.
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"

        try:
            parsed = datetime.fromisoformat(
                text
            )

            if parsed.tzinfo is None:
                parsed = parsed.replace(
                    tzinfo=timezone.utc
                )

            return parsed.astimezone(
                timezone.utc
            )

        except ValueError:
            return None

    return None


def _extract_price_point(
    item: Any,
) -> Optional[Tuple[Optional[datetime], float]]:
    """
    Extract (timestamp, price) from either:

        {"timestamp": ..., "price": ...}

    or a raw numeric price.

    Raw numeric prices have no timestamp.
    """

    if isinstance(item, dict):
        raw_price = first_defined(
            item.get("price"),
            item.get("close"),
            item.get("value"),
        )

        price = _finite_float(
            raw_price
        )

        if price is None or price <= 0:
            return None

        raw_timestamp = first_defined(
            item.get("timestamp"),
            item.get("time"),
            item.get("date"),
            item.get("datetime"),
        )

        timestamp = _timestamp_to_datetime(
            raw_timestamp
        )

        return timestamp, price

    price = _finite_float(item)

    if price is None or price <= 0:
        return None

    return None, price


def _prices_only(
    history: Any,
) -> List[float]:
    """
    Extract valid positive prices from a history series.

    This function intentionally does not invent prices for malformed
    records.
    """

    if not isinstance(
        history,
        list,
    ):
        return []

    prices = []

    for item in history:
        point = _extract_price_point(
            item
        )

        if point is None:
            continue

        _, price = point
        prices.append(price)

    return prices


def _series_points(
    history: Any,
) -> List[Tuple[datetime, float]]:
    """
    Extract valid timestamped price observations.

    Records without usable timestamps are excluded because they cannot
    participate safely in calendar-date alignment.
    """

    if not isinstance(
        history,
        list,
    ):
        return []

    points = []

    for item in history:
        point = _extract_price_point(
            item
        )

        if point is None:
            continue

        timestamp, price = point

        if timestamp is None:
            continue

        points.append(
            (
                timestamp,
                price,
            )
        )

    # Chronological order is mandatory for return calculations.
    points.sort(
        key=lambda point: point[0]
    )

    return points


def _align_series_by_date(
    asset_prices: Any,
    btc_prices: Any,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[datetime]]:
    """
    Align asset and BTC prices by UTC calendar date.

    Only dates present in BOTH series are retained.

    If multiple observations exist on the same date, the last
    chronological observation for that date is used.

    Returns:
        aligned_asset,
        aligned_btc,
        aligned_dates
    """

    asset_points = _series_points(
        asset_prices
    )

    btc_points = _series_points(
        btc_prices
    )

    if not asset_points or not btc_points:
        return [], [], []

    asset_by_date = {}

    for timestamp, price in asset_points:
        asset_by_date[
            timestamp.date()
        ] = {
            "timestamp": timestamp,
            "price": price,
        }

    btc_by_date = {}

    for timestamp, price in btc_points:
        btc_by_date[
            timestamp.date()
        ] = {
            "timestamp": timestamp,
            "price": price,
        }

    common_dates = sorted(
        set(asset_by_date)
        & set(btc_by_date)
    )

    aligned_asset = [
        asset_by_date[day]
        for day in common_dates
    ]

    aligned_btc = [
        btc_by_date[day]
        for day in common_dates
    ]

    aligned_dates = [
        datetime(
            day.year,
            day.month,
            day.day,
            tzinfo=timezone.utc,
        )
        for day in common_dates
    ]

    return (
        aligned_asset,
        aligned_btc,
        aligned_dates,
    )


def _prices_from_aligned(
    series: Any,
) -> List[float]:
    """Extract prices from an already-aligned series."""

    return _prices_only(
        series
    )


# ---------------------------------------------------------------------------
# Core statistics
# ---------------------------------------------------------------------------

def standard_deviation(
    values: list,
    sample: bool = False,
) -> float:
    """
    Calculate standard deviation.

    sample=False:
        Population standard deviation.

    sample=True:
        Sample standard deviation using N-1 degrees of freedom.

    For realized volatility estimated from historical returns, sample=True
    is generally appropriate because the observed return series represents
    a sample of the asset's underlying return process.
    """

    if not isinstance(
        values,
        list,
    ):
        return 0.0

    cleaned = []

    for value in values:
        numeric_value = _finite_float(
            value
        )

        if numeric_value is not None:
            cleaned.append(
                numeric_value
            )

    minimum_points = (
        2 if sample else 1
    )

    if len(cleaned) < minimum_points:
        return 0.0

    average = _mean(
        cleaned
    )

    squared_deviations = [
        (value - average) ** 2
        for value in cleaned
    ]

    divisor = (
        len(cleaned) - 1
        if sample
        else len(cleaned)
    )

    if divisor <= 0:
        return 0.0

    variance_value = (
        math.fsum(
            squared_deviations
        )
        / divisor
    )

    if not math.isfinite(
        variance_value
    ):
        return 0.0

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
    """
    Calculate population covariance between two aligned series.

    Both series must represent paired observations. Invalid pairs are
    discarded together so the pairing is never shifted.
    """

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

    pairs = []

    for a, b in zip(
        values_a,
        values_b,
    ):
        a_value = _finite_float(a)
        b_value = _finite_float(b)

        if (
            a_value is None
            or b_value is None
        ):
            continue

        pairs.append(
            (
                a_value,
                b_value,
            )
        )

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

    mean_a = _mean(
        a_values
    )

    mean_b = _mean(
        b_values
    )

    products = [
        (
            a - mean_a
        ) * (
            b - mean_b
        )
        for a, b in pairs
    ]

    result = (
        math.fsum(products)
        / len(pairs)
    )

    return (
        result
        if math.isfinite(result)
        else 0.0
    )


def variance(
    values: list,
) -> float:
    """
    Calculate population variance.

    This matches the covariance convention used by beta:
        beta = Cov(asset, BTC) / Var(BTC)
    """

    if not isinstance(
        values,
        list,
    ):
        return 0.0

    cleaned = []

    for value in values:
        numeric_value = _finite_float(
            value
        )

        if numeric_value is not None:
            cleaned.append(
                numeric_value
            )

    if len(cleaned) < 2:
        return 0.0

    average = _mean(
        cleaned
    )

    squared_deviations = [
        (
            value - average
        ) ** 2
        for value in cleaned
    ]

    result = (
        math.fsum(
            squared_deviations
        )
        / len(cleaned)
    )

    return (
        result
        if math.isfinite(result)
        else 0.0
    )


# ---------------------------------------------------------------------------
# Returns
# ---------------------------------------------------------------------------

def calculate_returns(
    prices: list,
) -> list:
    """
    Calculate simple returns:

        R_t = (P_t / P_(t-1)) - 1

    Invalid observations are NOT compressed across missing values when
    the input contains structured timestamped records.

    For a plain numeric list, valid positive observations are used.
    """

    if not isinstance(
        prices,
        list,
    ):
        return []

    if not prices:
        return []

    # Structured history: preserve chronological adjacency.
    if any(
        isinstance(
            item,
            dict,
        )
        for item in prices
    ):
        points = _series_points(
            prices
        )

        if len(points) < 2:
            return []

        returns = []

        for previous, current in zip(
            points,
            points[1:],
        ):
            previous_price = previous[1]
            current_price = current[1]

            if (
                previous_price <= 0
                or current_price <= 0
            ):
                continue

            result = (
                current_price
                / previous_price
            ) - 1.0

            if math.isfinite(result):
                returns.append(
                    result
                )

        return returns

    # Plain numeric history.
    cleaned = []

    for price in prices:
        numeric_price = _finite_float(
            price
        )

        if (
            numeric_price is not None
            and numeric_price > 0
        ):
            cleaned.append(
                numeric_price
            )

    if len(cleaned) < 2:
        return []

    returns = []

    for previous, current in zip(
        cleaned,
        cleaned[1:],
    ):
        if previous <= 0:
            continue

        result = (
            current / previous
        ) - 1.0

        if math.isfinite(result):
            returns.append(
                result
            )

    return returns


# ---------------------------------------------------------------------------
# Drawdown
# ---------------------------------------------------------------------------

def max_drawdown(
    prices: list,
) -> float:
    """
    Calculate maximum peak-to-trough drawdown.

    Returns a positive percentage.

    Example:
        peak = 100
        trough = 70
        result = 30.0
    """

    cleaned = _prices_only(
        prices
    )

    if not cleaned:
        return 0.0

    peak = cleaned[0]
    maximum_drawdown = 0.0

    for price in cleaned:
        if price > peak:
            peak = price

        if peak <= 0:
            continue

        drawdown_pct = (
            (price - peak)
            / peak
        ) * 100.0

        if math.isfinite(
            drawdown_pct
        ):
            maximum_drawdown = min(
                maximum_drawdown,
                drawdown_pct,
            )

    return abs(
        maximum_drawdown
    )


# ---------------------------------------------------------------------------
# Realized volatility
# ---------------------------------------------------------------------------

def realized_volatility(
    prices: list,
) -> dict:
    """
    Calculate realized annualized volatility.

    Steps:
        1. Extract valid positive prices.
        2. Calculate logarithmic returns.
        3. Calculate sample standard deviation.
        4. Annualize using sqrt(365), because crypto trades 24/7.

    Annualized volatility is returned as a percentage.

    Example:
        0.80 annualized decimal volatility
        -> 80.0%
    """

    try:
        if not isinstance(
            prices,
            list,
        ):
            return {
                "daily_volatility_pct": None,
                "annualized_volatility_pct": None,
                "observations": 0,
            }

        # Preserve structured chronological history.
        if any(
            isinstance(
                item,
                dict,
            )
            for item in prices
        ):
            points = _series_points(
                prices
            )

            cleaned = [
                price
                for _, price in points
            ]

        else:
            cleaned = _prices_only(
                prices
            )

        if len(cleaned) < 2:
            return {
                "daily_volatility_pct": None,
                "annualized_volatility_pct": None,
                "observations": 0,
            }

        log_returns = []

        for previous, current in zip(
            cleaned,
            cleaned[1:],
        ):
            if (
                previous <= 0
                or current <= 0
            ):
                continue

            ratio = (
                current / previous
            )

            if (
                ratio <= 0
                or not math.isfinite(ratio)
            ):
                continue

            log_return = math.log(
                ratio
            )

            if math.isfinite(
                log_return
            ):
                log_returns.append(
                    log_return
                )

        if len(log_returns) < 2:
            return {
                "daily_volatility_pct": None,
                "annualized_volatility_pct": None,
                "observations": len(
                    log_returns
                ),
            }

        daily_std = standard_deviation(
            log_returns,
            sample=True,
        )

        if (
            not math.isfinite(
                daily_std
            )
            or daily_std < 0
        ):
            return {
                "daily_volatility_pct": None,
                "annualized_volatility_pct": None,
                "observations": len(
                    log_returns
                ),
            }

        annualized = (
            daily_std
            * math.sqrt(365.0)
            * 100.0
        )

        if not math.isfinite(
            annualized
        ):
            return {
                "daily_volatility_pct": None,
                "annualized_volatility_pct": None,
                "observations": len(
                    log_returns
                ),
            }

        return json_safe({
            "daily_volatility_pct": (
                daily_std * 100.0
            ),
            "annualized_volatility_pct": annualized,
            "observations": len(
                log_returns
            ),
        })

    except Exception as exc:
        logger.exception(
            "realized_volatility failed: %s",
            exc,
        )

        return {
            "daily_volatility_pct": None,
            "annualized_volatility_pct": None,
            "observations": 0,
        }


# ---------------------------------------------------------------------------
# Beta
# ---------------------------------------------------------------------------

def calculate_beta(
    asset_prices: list,
    btc_prices: list,
) -> dict:
    """
    Calculate BTC beta:

        beta = Cov(asset_returns, BTC_returns)
               / Var(BTC_returns)

    Returns:
        beta
        observations

    Beta is calculated from SIMPLE returns, which is standard for
    market-regression beta.

    The asset and BTC histories are aligned by UTC calendar date before
    returns are calculated.
    """

    try:
        if (
            not isinstance(
                asset_prices,
                list,
            )
            or not isinstance(
                btc_prices,
                list,
            )
        ):
            return {
                "beta": None,
                "observations": 0,
            }

        # If both series are structured, align by date.
        if (
            any(
                isinstance(
                    item,
                    dict,
                )
                for item in asset_prices
            )
            or any(
                isinstance(
                    item,
                    dict,
                )
                for item in btc_prices
            )
        ):
            (
                aligned_asset,
                aligned_btc,
                aligned_dates,
            ) = _align_series_by_date(
                asset_prices,
                btc_prices,
            )

            asset_series = _prices_from_aligned(
                aligned_asset
            )

            btc_series = _prices_from_aligned(
                aligned_btc
            )

        else:
            # Plain lists cannot be calendar-aligned, so only use them
            # when both lengths are compatible.
            asset_series = _prices_only(
                asset_prices
            )

            btc_series = _prices_only(
                btc_prices
            )

            aligned_dates = []

        if (
            len(asset_series) < 3
            or len(btc_series) < 3
        ):
            return json_safe({
                "beta": None,
                "observations": 0,
            })

        # Both aligned series must have exactly the same length.
        length = min(
            len(asset_series),
            len(btc_series),
        )

        asset_series = asset_series[
            -length:
        ]

        btc_series = btc_series[
            -length:
        ]

        asset_returns = calculate_returns(
            asset_series
        )

        btc_returns = calculate_returns(
            btc_series
        )

        length = min(
            len(asset_returns),
            len(btc_returns),
        )

        if length < 2:
            return json_safe({
                "beta": None,
                "observations": length,
            })

        asset_returns = asset_returns[
            -length:
        ]

        btc_returns = btc_returns[
            -length:
        ]

        if aligned_dates:
            logger.info(
                "[BETA] %d aligned price observations "
                "over %s to %s",
                len(aligned_dates),
                aligned_dates[0].date().isoformat(),
                aligned_dates[-1].date().isoformat(),
            )

        btc_variance = variance(
            btc_returns
        )

        if (
            not math.isfinite(
                btc_variance
            )
            or btc_variance <= 1e-16
        ):
            # BTC barely moved; beta is mathematically unstable.
            return json_safe({
                "beta": None,
                "observations": length,
            })

        covariance_value = covariance(
            asset_returns,
            btc_returns,
        )

        if not math.isfinite(
            covariance_value
        ):
            return json_safe({
                "beta": None,
                "observations": length,
            })

        beta = (
            covariance_value
            / btc_variance
        )

        if not math.isfinite(
            beta
        ):
            return json_safe({
                "beta": None,
                "observations": length,
            })

        return json_safe({
            "beta": beta,
            "observations": length,
        })

    except Exception as exc:
        logger.exception(
            "calculate_beta failed: %s",
            exc,
        )

        return {
            "beta": None,
            "observations": 0,
        }


# ---------------------------------------------------------------------------
# Liquidity
# ---------------------------------------------------------------------------

def calculate_liquidity_metrics(
    market: dict,
) -> dict:
    """
    Calculate basic market-liquidity metrics.

    Turnover:

        turnover_pct =
            volume_24h / market_cap * 100

    Higher turnover generally indicates more active trading.

    This function measures the metric only. Risk scoring belongs in
    risk_engine.py.
    """

    try:
        if not isinstance(
            market,
            dict,
        ):
            market = {}

        volume = _finite_float(
            market.get(
                "volume_24h"
            )
        )

        market_cap = _finite_float(
            market.get(
                "market_cap"
            )
        )

        turnover = None

        if (
            volume is not None
            and volume >= 0
            and market_cap is not None
            and market_cap > 0
        ):
            turnover_value = (
                volume
                / market_cap
            ) * 100.0

            if math.isfinite(
                turnover_value
            ):
                turnover = turnover_value

        return json_safe({
            "volume_24h": volume,
            "market_cap": market_cap,
            "turnover_pct": turnover,
        })

    except Exception as exc:
        logger.exception(
            "calculate_liquidity_metrics failed: %s",
            exc,
        )

        return {
            "volume_24h": None,
            "market_cap": None,
            "turnover_pct": None,
        }


# ---------------------------------------------------------------------------
# Combined quantitative metrics
# ---------------------------------------------------------------------------

def calculate_quant_metrics(
    symbol: str,
    market: dict,
    history: list,
    btc_history: list,
) -> dict:
    """
    Calculate all quantitative signals consumed by risk_engine.py.
    """

    normalized_symbol = normalize_symbol(
        symbol
    )

    try:
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

        history_prices = _prices_only(
            history
        )

        volatility = realized_volatility(
            history
        )

        beta = calculate_beta(
            history,
            btc_history,
        )

        liquidity = calculate_liquidity_metrics(
            market
        )

        drawdown = max_drawdown(
            history
        )

        returns = calculate_returns(
            history
        )

        current_price = _finite_float(
            market.get(
                "price"
            )
        )

        historical_price = (
            history_prices[-1]
            if history_prices
            else None
        )

        price_change_from_history = None

        if (
            current_price is not None
            and historical_price is not None
        ):
            price_change_from_history = (
                percentage_change(
                    current_price,
                    historical_price,
                )
            )

        valid_history_count = len(
            history_prices
        )

        valid_btc_history_count = len(
            _prices_only(
                btc_history
            )
        )

        return json_safe({
            "symbol": normalized_symbol,

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

            "history_observations": (
                valid_history_count
            ),

            "btc_history_observations": (
                valid_btc_history_count
            ),
        })

    except Exception as exc:
        logger.exception(
            "quant metrics failed for %s: %s",
            normalized_symbol,
            exc,
        )

        return json_safe({
            "symbol": normalized_symbol,

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

            "max_drawdown_pct": None,

            "return_observations": 0,

            "price_change_from_history_pct": None,

            "history_observations": 0,

            "btc_history_observations": 0,
        })


# ---------------------------------------------------------------------------
# Risk-engine extraction helpers
# ---------------------------------------------------------------------------

def extract_volatility_value(
    quant,
    market=None,
):
    """
    Extract scalar annualized volatility for risk_engine.py.
    """

    quant = (
        quant
        if isinstance(
            quant,
            dict,
        )
        else {}
    )

    market = (
        market
        if isinstance(
            market,
            dict,
        )
        else {}
    )

    volatility = quant.get(
        "volatility"
    )

    if isinstance(
        volatility,
        dict,
    ):
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

    return _finite_float(
        volatility
    )


def extract_beta_value(
    quant,
):
    """
    Extract scalar BTC beta from the nested beta structure.
    """

    quant = (
        quant
        if isinstance(
            quant,
            dict,
        )
        else {}
    )

    beta = quant.get(
        "beta"
    )

    if isinstance(
        beta,
        dict,
    ):
        beta = beta.get(
            "beta"
        )

    return _finite_float(
        beta
    )