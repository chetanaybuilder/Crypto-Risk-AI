import logging
import math

from config import (
    NATIVE_ASSETS,
    REPORT_SCHEMA_VERSION,
    RISK_WEIGHTS,
    SUPPORTED_HISTORY_DAYS,
)
from services.coingecko import (
    enrich_market_7d,
    fetch_market_data,
    fetch_price_history,
)
from services.gemini import run_gemini_interpretation
from services.goplus import fetch_token_security
from utils.helpers import (
    first_defined,
    format_number,
    json_safe,
    normalize_symbol,
    utc_now_iso,
)
from utils.math_helpers import (
    clamp,
    numeric,
    optional_numeric,
    calculate_quant_metrics,
    extract_beta_value,
    extract_volatility_value,
)

logger = logging.getLogger(__name__)


def score_volatility(volatility):
    """
    Convert annualized volatility into a 0-100 risk score.

    Annualized volatility is expected in percentage units.

    <=20%   -> 15
    <=40%   -> 30
    <=60%   -> 50
    <=80%   -> 70
    <=120%  -> 85
    >120%   -> 95
    """
    volatility = optional_numeric(volatility)

    if volatility is None or not math.isfinite(volatility):
        return None

    volatility = max(volatility, 0)

    if volatility <= 20:
        return 15

    if volatility <= 40:
        return 30

    if volatility <= 60:
        return 50

    if volatility <= 80:
        return 70

    if volatility <= 120:
        return 85

    return 95


def score_liquidity(volume_24h, market_cap):
    """
    Estimate liquidity risk from 24h volume / market cap.

    Higher turnover generally implies lower liquidity risk.

    If market cap is unavailable, a conservative volume-only fallback
    is used rather than fabricating a turnover ratio.
    """
    volume_24h = optional_numeric(volume_24h)
    market_cap = optional_numeric(market_cap)

    if (
        volume_24h is None
        or not math.isfinite(volume_24h)
        or volume_24h < 0
    ):
        return None

    if (
        market_cap is None
        or not math.isfinite(market_cap)
        or market_cap <= 0
    ):
        if volume_24h >= 1_000_000_000:
            return 20

        if volume_24h >= 100_000_000:
            return 35

        if volume_24h >= 10_000_000:
            return 50

        if volume_24h >= 1_000_000:
            return 65

        if volume_24h >= 100_000:
            return 80

        return 90

    turnover = volume_24h / market_cap

    if not math.isfinite(turnover):
        return None

    if turnover >= 0.50:
        return 10

    if turnover >= 0.25:
        return 20

    if turnover >= 0.10:
        return 35

    if turnover >= 0.05:
        return 50

    if turnover >= 0.02:
        return 65

    if turnover >= 0.01:
        return 80

    return 90


def score_beta(beta):
    """
    Convert absolute BTC beta into a 0-100 market-sensitivity score.

    Beta magnitude is used because both strongly positive and strongly
    negative beta represent substantial BTC sensitivity.
    """
    beta = optional_numeric(beta)

    if beta is None or not math.isfinite(beta):
        return None

    beta = abs(beta)

    if beta <= 0.50:
        return 20

    if beta <= 0.80:
        return 35

    if beta <= 1.00:
        return 50

    if beta <= 1.25:
        return 65

    if beta <= 1.50:
        return 80

    return 95


def score_structural_risk(security):
    """
    Convert normalized GoPlus security findings into a 0-100
    structural-risk score.

    Missing security data is unknown, not automatically dangerous.

    Scores are based on the actual raw_signals fields when available,
    rather than matching human-readable flag text.
    """
    if not isinstance(security, dict):
        return None

    if security.get("not_applicable"):
        return None

    if not security.get("available"):
        return None

    raw_signals = security.get("raw_signals")

    if not isinstance(raw_signals, dict):
        raw_signals = {}

    score = 10

    honeypot = raw_signals.get("honeypot")
    blacklist = raw_signals.get("blacklist")
    ownership_recovery = raw_signals.get(
        "ownership_recovery"
    )
    owner_balance_change = raw_signals.get(
        "owner_balance_change"
    )
    open_source = raw_signals.get("open_source")
    buy_tax = optional_numeric(
        raw_signals.get("buy_tax")
    )
    sell_tax = optional_numeric(
        raw_signals.get("sell_tax")
    )

    if honeypot is True:
        score += 45

    if blacklist is True:
        score += 30

    if ownership_recovery is True:
        score += 25

    if owner_balance_change is True:
        score += 25

    if open_source is False:
        score += 10

    if buy_tax is not None and math.isfinite(buy_tax):
        if buy_tax > 0.10:
            score += 25
        elif buy_tax > 0.05:
            score += 15

    if sell_tax is not None and math.isfinite(sell_tax):
        if sell_tax > 0.10:
            score += 25
        elif sell_tax > 0.05:
            score += 15

    return clamp(score, 0, 100)


def risk_label(score):
    """
    Convert a 0-100 risk score into a human-readable label.
    """
    score = optional_numeric(score)

    if score is None or not math.isfinite(score):
        return "Unavailable"

    if score >= 80:
        return "Critical"

    if score >= 65:
        return "High"

    if score >= 50:
        return "Elevated"

    if score >= 35:
        return "Moderate"

    return "Low"


def calculate_composite_risk(
    volatility_score,
    liquidity_score,
    sensitivity_score,
    structural_score,
):
    """
    Calculate a weighted composite risk score.

    Only valid available pillars participate.

    Returns:
        (composite_score, confidence, is_partial)
    """
    values = {
        "volatility": volatility_score,
        "liquidity": liquidity_score,
        "market_sensitivity": sensitivity_score,
        "structural": structural_score,
    }

    weighted_sum = 0.0
    weight_sum = 0.0
    total_weight = 0.0

    for key, raw_value in values.items():
        weight = optional_numeric(
            RISK_WEIGHTS.get(key)
        )

        if (
            weight is None
            or not math.isfinite(weight)
            or weight <= 0
        ):
            continue

        total_weight += weight

        value = optional_numeric(raw_value)

        if (
            value is None
            or not math.isfinite(value)
        ):
            continue

        value = clamp(value, 0, 100)

        weighted_sum += value * weight
        weight_sum += weight

    if total_weight <= 0:
        return None, 0, True

    if weight_sum <= 0:
        return None, 0, True

    composite = weighted_sum / weight_sum

    participation = clamp(
        weight_sum / total_weight,
        0,
        1,
    )

    confidence = clamp(
        10 + int(round(participation * 85)),
        10,
        95,
    )

    is_partial = participation < 0.999

    return (
        int(round(clamp(composite, 0, 100))),
        confidence,
        is_partial,
    )


def build_risk_profile(
    market,
    quant,
    security=None,
):
    """
    Build the complete quantitative risk profile.
    """
    market = market if isinstance(market, dict) else {}
    quant = quant if isinstance(quant, dict) else {}

    volatility = extract_volatility_value(
        quant,
        market,
    )

    beta = extract_beta_value(
        quant
    )

    volume = optional_numeric(
        market.get("volume_24h")
    )

    market_cap = optional_numeric(
        market.get("market_cap")
    )

    volatility_score = score_volatility(
        volatility
    )

    liquidity_score = score_liquidity(
        volume,
        market_cap,
    )

    sensitivity_score = score_beta(
        beta
    )

    structural_score = score_structural_risk(
        security
    )

    if (
        isinstance(security, dict)
        and security.get("not_applicable")
    ):
        structural_detail = "Not applicable."

    elif (
        isinstance(security, dict)
        and security.get("available")
    ):
        structural_detail = security.get(
            "status",
            "Security assessment available.",
        )

    else:
        structural_detail = (
            "Contract security assessment unavailable."
        )

    (
        composite,
        confidence,
        is_partial,
    ) = calculate_composite_risk(
        volatility_score,
        liquidity_score,
        sensitivity_score,
        structural_score,
    )

    pillars = {
        "volatility": {
            "score": volatility_score,
            "label": risk_label(volatility_score),
            "weight": RISK_WEIGHTS.get(
                "volatility"
            ),
            "detail": (
                f"Annualized realized volatility: "
                f"{format_number(volatility, 1)}%"
                if volatility is not None
                else "Volatility data unavailable."
            ),
        },
        "liquidity": {
            "score": liquidity_score,
            "label": risk_label(liquidity_score),
            "weight": RISK_WEIGHTS.get(
                "liquidity"
            ),
            "detail": (
                "Liquidity estimated from 24h "
                "volume-to-market-cap turnover."
                if (
                    liquidity_score is not None
                    and market_cap is not None
                )
                else (
                    "Liquidity estimated from 24h volume "
                    "only; market cap is unavailable."
                    if (
                        liquidity_score is not None
                        and market_cap is None
                    )
                    else "Liquidity data unavailable."
                )
            ),
        },
        "market_sensitivity": {
            "score": sensitivity_score,
            "label": risk_label(sensitivity_score),
            "weight": RISK_WEIGHTS.get(
                "market_sensitivity"
            ),
            "detail": (
                f"BTC beta: {format_number(beta, 2)}"
                if beta is not None
                else "BTC sensitivity unavailable."
            ),
        },
        "structural": {
            "score": structural_score,
            "label": risk_label(structural_score),
            "weight": RISK_WEIGHTS.get(
                "structural"
            ),
            "detail": structural_detail,
        },
    }

    risk_profile = {
        "composite_score": composite,
        "label": risk_label(composite),
        "confidence": confidence,
        "partial_data": is_partial,
        "pillars": pillars,
    }

    return json_safe(risk_profile)


def calculate_stress_test(
    beta,
    volatility,
    liquidity_score,
):
    """
    Run deterministic BTC downside scenarios.

    This is a scenario model, not a forecast.

    Core relationship:

        asset_move ≈ BTC_shock × beta

    Volatility and liquidity are used only as bounded downside
    uncertainty adjustments. They cannot turn a downside scenario
    into an arbitrary prediction.

    Beta is required because the scenarios are explicitly BTC-relative.
    """
    beta = optional_numeric(beta)

    if (
        beta is None
        or not math.isfinite(beta)
    ):
        return json_safe({
            "available": False,
            "unavailable_reason": (
                "Beta unavailable — no historical BTC data."
            ),
            "benchmark": "BTC",
            "base_scenario": {},
            "scenarios": [],
            "expected_downside_pct": None,
            "drawdown_pct": None,
            "resilience_score": None,
            "resilience_label": "Unavailable",
            "verdict": (
                "Unavailable — no BTC benchmark history"
            ),
            "confidence": None,
            "assumed_parameters": [],
            "used_default_beta": False,
            "used_default_volatility": False,
            "used_default_liquidity": False,
            "methodology": (
                "BTC-relative scenario analysis requires "
                "a measured BTC beta."
            ),
        })

    beta = max(beta, -5.0)
    beta = min(beta, 5.0)

    volatility = optional_numeric(volatility)
    volatility_is_assumed = (
        volatility is None
        or not math.isfinite(volatility)
    )

    if volatility_is_assumed:
        volatility = 60.0

    volatility = clamp(
        max(volatility, 0),
        0,
        250,
    )

    liquidity_score = optional_numeric(
        liquidity_score
    )

    liquidity_is_assumed = (
        liquidity_score is None
        or not math.isfinite(liquidity_score)
    )

    if liquidity_is_assumed:
        liquidity_score = 50.0

    liquidity_score = clamp(
        liquidity_score,
        0,
        100,
    )

    scenarios = []

    for btc_shock in (-5, -10, -20, -30):
        beta_move = btc_shock * beta

        # Volatility adjustment:
        #
        # Higher realized volatility increases uncertainty around
        # the beta-derived move, but the adjustment is capped so
        # volatility cannot dominate the BTC-beta relationship.
        volatility_factor = clamp(
            volatility / 100,
            0,
            2.5,
        )

        volatility_adjustment = (
            abs(beta_move)
            * volatility_factor
            * 0.08
        )

        # Liquidity adjustment:
        #
        # Scores above 50 represent increasing liquidity risk.
        liquidity_factor = clamp(
            (liquidity_score - 50) / 50,
            0,
            1,
        )

        liquidity_adjustment = (
            abs(beta_move)
            * liquidity_factor
            * 0.08
        )

        # Only increase downside magnitude when the beta-derived
        # scenario itself is negative.
        if beta_move < 0:
            estimated_move = (
                beta_move
                - volatility_adjustment
                - liquidity_adjustment
            )
        else:
            # For inverse/negative-beta assets, uncertainty should
            # reduce the positive hedge effect rather than create
            # an artificial downside prediction.
            estimated_move = (
                beta_move
                - volatility_adjustment
                + liquidity_adjustment
            )

        estimated_move = clamp(
            estimated_move,
            -100,
            100,
        )

        downside_magnitude = max(
            abs(min(estimated_move, 0)),
            0,
        )

        resilience = clamp(
            100
            - downside_magnitude * 1.8
            - max(liquidity_score - 50, 0) * 0.20,
            0,
            100,
        )

        scenarios.append({
            "btc_shock_pct": btc_shock,
            "estimated_asset_move_pct": round(
                estimated_move,
                2,
            ),
            "resilience_score": round(
                resilience,
                1,
            ),
        })

    ten_percent_case = next(
        (
            item
            for item in scenarios
            if item["btc_shock_pct"] == -10
        ),
        scenarios[0],
    )

    # Confidence measures data completeness, not whether the
    # scenario will actually occur.
    confidence = 90.0

    if volatility_is_assumed:
        confidence -= 20

    if liquidity_is_assumed:
        confidence -= 10

    confidence = clamp(
        confidence,
        20,
        90,
    )

    resilience_score = ten_percent_case.get(
        "resilience_score"
    )

    if resilience_score >= 65:
        verdict = "Relatively resilient"
        resilience_label = "Resilient"

    elif resilience_score >= 40:
        verdict = "Moderate stress sensitivity"
        resilience_label = "Moderate"

    else:
        verdict = "High downside sensitivity"
        resilience_label = "Fragile"

    expected_drawdown = ten_percent_case.get(
        "estimated_asset_move_pct"
    )

    assumed_parameters = []

    if volatility_is_assumed:
        assumed_parameters.append("volatility")

    if liquidity_is_assumed:
        assumed_parameters.append("liquidity_score")

    stress_report = {
        "available": True,
        "benchmark": "BTC",
        "scenarios": scenarios,
        "base_scenario": ten_percent_case,
        "beta": round(beta, 3),
        "volatility": round(volatility, 2),
        "liquidity_score": round(
            liquidity_score,
            2,
        ),
        "confidence": round(
            confidence,
            1,
        ),
        "verdict": verdict,
        "expected_drawdown_pct": (
            round(expected_drawdown, 2)
            if expected_drawdown is not None
            else None
        ),
        "drawdown_pct": (
            round(expected_drawdown, 2)
            if expected_drawdown is not None
            else None
        ),
        "resilience_label": resilience_label,
        "resilience_score": round(
            resilience_score,
            1,
        ),
        "assumed_parameters": assumed_parameters,
        "used_default_beta": False,
        "used_default_volatility": volatility_is_assumed,
        "used_default_liquidity": liquidity_is_assumed,
        "methodology": (
            "Scenario estimates combine measured BTC beta "
            "with bounded volatility and liquidity adjustments. "
            "They are scenario estimates, not forecasts."
        ),
    }

    return json_safe(stress_report)


def build_risk_drivers(
    risk_profile,
):
    """
    Produce concise, evidence-backed risk drivers.
    """
    if not isinstance(risk_profile, dict):
        return [{
            "title": "Risk profile unavailable",
            "severity": "Unavailable",
            "detail": (
                "Insufficient quantitative data to identify "
                "dominant risk drivers."
            ),
        }]

    pillars = risk_profile.get(
        "pillars",
        {}
    )

    if not isinstance(pillars, dict):
        pillars = {}

    drivers = []

    volatility = pillars.get(
        "volatility",
        {}
    )
    liquidity = pillars.get(
        "liquidity",
        {}
    )
    sensitivity = pillars.get(
        "market_sensitivity",
        {}
    )
    structural = pillars.get(
        "structural",
        {}
    )

    if (
        isinstance(volatility, dict)
        and volatility.get("score") is not None
        and volatility["score"] >= 70
    ):
        drivers.append({
            "title": "High volatility",
            "severity": volatility.get(
                "label",
                "High",
            ),
            "detail": volatility.get(
                "detail",
                "Volatility is elevated.",
            ),
        })

    if (
        isinstance(liquidity, dict)
        and liquidity.get("score") is not None
        and liquidity["score"] >= 65
    ):
        drivers.append({
            "title": "Liquidity pressure",
            "severity": liquidity.get(
                "label",
                "High",
            ),
            "detail": liquidity.get(
                "detail",
                "Liquidity conditions are weaker.",
            ),
        })

    if (
        isinstance(sensitivity, dict)
        and sensitivity.get("score") is not None
        and sensitivity["score"] >= 70
    ):
        drivers.append({
            "title": "High BTC sensitivity",
            "severity": sensitivity.get(
                "label",
                "High",
            ),
            "detail": sensitivity.get(
                "detail",
                "Asset shows elevated BTC sensitivity.",
            ),
        })

    if (
        isinstance(structural, dict)
        and structural.get("score") is not None
        and structural["score"] >= 65
    ):
        drivers.append({
            "title": "Structural risk",
            "severity": structural.get(
                "label",
                "High",
            ),
            "detail": structural.get(
                "detail",
                "Contract/security signals require attention.",
            ),
        })

    if not drivers:
        drivers.append({
            "title": "No dominant quantitative red flag",
            "severity": "Moderate",
            "detail": (
                "Current available signals do not show "
                "a single dominant risk driver."
            ),
        })

    return drivers[:6]


def _format_fiat(value):
    if value is None:
        return None
    try:
        val = float(value)
        abs_val = abs(val)
        if abs_val >= 1_000_000_000_000:
            return f"${val / 1_000_000_000_000:.2f}T"
        if abs_val >= 1_000_000_000:
            return f"${val / 1_000_000_000:.2f}B"
        if abs_val >= 1_000_000:
            return f"${val / 1_000_000:.2f}M"
        if abs_val >= 1000:
            return f"${val:,.0f}"
        return f"${val:,.2f}"
    except (TypeError, ValueError):
        return None

def _round_pct(value):
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None

def build_evidence_pack(
    symbol,
    market,
    quant,
    risk_profile,
    stress,
    security,
    risk_drivers,
):
    """
    Create the factual evidence packet supplied to Gemini.
    """
    market = market if isinstance(market, dict) else {}
    quant = quant if isinstance(quant, dict) else {}

    volatility = extract_volatility_value(
        quant,
        market,
    )

    beta = extract_beta_value(
        quant
    )

    evidence = {
        "asset": symbol.upper(),

        "market": {
            "price_usd": _format_fiat(market.get("price")),
            "change_24h_pct": _round_pct(market.get(
                "price_change_24h_pct"
            )),
            "change_7d_pct": _round_pct(market.get(
                "price_change_7d_pct"
            )),
            "volume_24h_usd": _format_fiat(market.get(
                "volume_24h"
            )),
            "market_cap_usd": _format_fiat(market.get(
                "market_cap"
            )),
            "high_24h_usd": _format_fiat(market.get(
                "high_24h"
            )),
            "low_24h_usd": _format_fiat(market.get(
                "low_24h"
            )),
            "source": market.get("source"),
        },

        "quantitative": {
            "volatility_pct": _round_pct(volatility),
            "beta_to_btc": _round_pct(beta),
            "max_drawdown_pct": _round_pct(quant.get(
                "max_drawdown_pct"
            )),
            "history_observations": quant.get(
                "history_observations"
            ),
            "volatility_detail": quant.get(
                "volatility"
            ),
            "beta_detail": quant.get(
                "beta"
            ),
            "liquidity_detail": quant.get(
                "liquidity"
            ),
        },

        "risk_profile": risk_profile,
        "stress_test": stress,

        "security": (
            security
            if isinstance(security, dict)
            else {
                "available": False,
                "status": "Unavailable",
            }
        ),

        "risk_drivers": risk_drivers,

        "data_quality": market.get(
            "data_quality",
            {},
        ),
    }

    return json_safe(evidence)


def _field_error_label(field_name):
    """
    Normalize internal market field names to frontend labels.
    """
    labels = {
        "price": "Live price",
        "volume_24h": "24h volume",
        "total_volume": "24h volume",
        "market_cap": "Market cap",
        "high_24h": "24h high",
        "low_24h": "24h low",
        "history": "Price history",
        "history_observations": "Price history",
        "btc_history": "BTC benchmark history",
        "btc_history_observations": (
            "BTC benchmark history"
        ),
        "contract_security": "Contract security",
    }

    return labels.get(
        str(field_name),
        str(field_name),
    )


def build_structured_report(
    symbol,
    market,
    quant,
    security,
    risk_profile,
    stress,
    risk_drivers,
    evidence,
    ai,
):
    """
    Build the normalized report consumed by the frontend.
    """
    market = market if isinstance(market, dict) else {}
    quant = quant if isinstance(quant, dict) else {}
    ai = ai if isinstance(ai, dict) else {}
    risk_profile = (
        risk_profile
        if isinstance(risk_profile, dict)
        else {}
    )
    security = (
        security
        if isinstance(security, dict)
        else {}
    )

    composite_score = risk_profile.get(
        "composite_score"
    )

    is_native_asset = (
        symbol.upper() in NATIVE_ASSETS
    )

    security_not_applicable = (
        security.get("not_applicable") is True
    )

    field_checks = {
        "Live price": market.get("price"),
        "24h volume": market.get("volume_24h"),
        "Market cap": market.get("market_cap"),
        "24h high": market.get("high_24h"),
        "24h low": market.get("low_24h"),
        "Price history": quant.get(
            "history_observations"
        ),
        "BTC benchmark history": quant.get(
            "btc_history_observations"
        ),
    }

    if (
        not is_native_asset
        and not security_not_applicable
    ):
        field_checks["Contract security"] = (
            True
            if security.get("available")
            else None
        )

    available_fields = []
    missing_signals = []

    for name, value in field_checks.items():
        if value is not None:
            available_fields.append(name)
        else:
            missing_signals.append(name)

    field_errors = market.get(
        "field_errors"
    )

    if not isinstance(field_errors, dict):
        field_errors = {}

    for error_field in field_errors:
        label = _field_error_label(
            error_field
        )

        if label not in missing_signals:
            missing_signals.append(label)

    deduped_missing = []

    for signal_name in missing_signals:
        if signal_name not in deduped_missing:
            deduped_missing.append(signal_name)

    missing_signals = deduped_missing

    source_timestamps = market.get(
        "source_timestamps"
    )

    if not isinstance(source_timestamps, dict):
        source_timestamps = {}

    dq = (
        market.get("data_quality")
        if isinstance(
            market.get("data_quality"),
            dict,
        )
        else {}
    ).copy()

    dq["available_fields"] = available_fields
    dq["field_errors"] = dict(field_errors)
    dq["source_timestamps"] = dict(
        source_timestamps
    )
    dq["missing_signals"] = missing_signals
    dq["not_applicable"] = (
        ["Contract security"]
        if (
            is_native_asset
            or security_not_applicable
        )
        else []
    )

    field_count = len(field_checks)
    populated_count = len(available_fields)

    field_confidence = (
        populated_count / field_count * 100
        if field_count
        else 0
    )

    risk_confidence = optional_numeric(
        risk_profile.get("confidence")
    )

    if risk_confidence is None:
        risk_confidence = 0

    dq["confidence"] = round(
        min(
            field_confidence,
            risk_confidence,
        ),
        1,
    )

    dq["source"] = first_defined(
        market.get("source"),
        "Backend market feed",
    )

    dq["is_fallback_provider"] = bool(
        market.get(
            "is_fallback_provider",
            False,
        )
    )

    report = {
        "schema_version": REPORT_SCHEMA_VERSION,

        "token_symbol": symbol.upper(),

        "asset": {
            "symbol": symbol.upper(),
            "name": market.get(
                "asset_name",
                symbol.upper(),
            ),
        },

        "outlook": risk_profile.get(
            "label",
            "Unavailable",
        ),

        "risk_score": composite_score,

        "risk_label": risk_profile.get(
            "label",
            "Unavailable",
        ),

        "risk_confidence": risk_profile.get(
            "confidence",
            0,
        ),

        "market": market,

        "quantitative": quant,

        "risk_profile": risk_profile,

        "risk_drivers": risk_drivers,

        "security": (
            security
            if security
            else {
                "status": "Unavailable",
                "available": False,
                "flags": [],
                "red_flags": [],
                "confidence": 0,
            }
        ),

        "stress": stress,
        "stress_test": stress,

        "evidence": evidence,

        "ai": ai,

        "data_quality": dq,

        "analysis_meta": {
            "engine": (
                "CryptoRisk AI Quantitative Engine"
            ),
            "ai_engine": ai.get(
                "provider",
                "unknown",
            ),
            "generated_at": utc_now_iso(),
            "interpretation_only": True,
            "scenario_model": True,
        },
    }

    return json_safe(report)


def report_progress(
    callback,
    percent,
    stage,
    title,
    message="",
):
    """
    Safely report analysis progress.
    """
    if not callable(callback):
        return

    try:
        safe_percent = int(
            clamp(
                percent,
                0,
                100,
            )
        )

        callback(
            safe_percent,
            stage,
            title,
            message,
        )

    except Exception as exc:
        logger.debug(
            "Progress callback failed: %s",
            exc,
        )


def run_analysis(
    symbol,
    chain_id=None,
    contract_address=None,
    force_market_refresh=False,
    progress_callback=None,
    gemini_max_retries_override=None,
):
    """
    Main CryptoRisk AI analysis pipeline.

    Market
        ↓
    History
        ↓
    Quantitative engine
        ↓
    Security
        ↓
    Risk profile
        ↓
    Stress test
        ↓
    Evidence
        ↓
    Gemini
        ↓
    Structured report
    """
    symbol = normalize_symbol(symbol)

    if not symbol:
        raise ValueError(
            "Token symbol is required."
        )

    # --------------------------------------------------------
    # Stage 1 — Market
    # --------------------------------------------------------

    report_progress(
        progress_callback,
        10,
        "market",
        "Fetching live market data",
        "Connecting to market data providers.",
    )

    market = fetch_market_data(
        symbol,
        force_refresh=force_market_refresh,
        skip_7d_enrich=True,
    )

    if (
        not isinstance(market, dict)
        or not market.get("available")
    ):
        unavailable_reason = (
            market.get(
                "unavailable_reason",
                "Market provider did not return usable data.",
            )
            if isinstance(market, dict)
            else "Market provider did not return usable data."
        )
        logger.warning(
            "Market data unavailable for %s: %s",
            symbol,
            unavailable_reason,
        )
        
        from utils.errors import MarketDataUnavailableError
        raise MarketDataUnavailableError(unavailable_reason)

    report_progress(
        progress_callback,
        20,
        "market",
        "Live market data received",
        "Market snapshot collected.",
    )

    # --------------------------------------------------------
    # Stage 2 — Historical data
    # --------------------------------------------------------

    report_progress(
        progress_callback,
        25,
        "history",
        "Loading historical market data",
        "Preparing price history for quantitative analysis.",
    )

    asset_history = fetch_price_history(
        symbol,
        days=SUPPORTED_HISTORY_DAYS,
    )

    report_progress(
        progress_callback,
        32,
        "history",
        "Loading BTC benchmark history",
        "Preparing BTC benchmark for sensitivity analysis.",
    )

    btc_history = fetch_price_history(
        "BTC",
        days=SUPPORTED_HISTORY_DAYS,
    )

    try:
        market = enrich_market_7d(
            market,
            symbol,
            history=asset_history,
        )
    except Exception as exc:
        logger.debug(
            "Market 7d enrichment failed: %s",
            exc,
        )

    report_progress(
        progress_callback,
        38,
        "history",
        "Historical data ready",
        "Historical datasets prepared.",
    )

    # --------------------------------------------------------
    # Stage 3 — Quantitative engine
    # --------------------------------------------------------

    report_progress(
        progress_callback,
        43,
        "quant",
        "Running quantitative risk engine",
        "Calculating volatility, beta, liquidity and drawdown.",
    )

    quant = calculate_quant_metrics(
        symbol,
        market,
        asset_history,
        btc_history,
    )

    if not isinstance(quant, dict):
        logger.warning(
            "Quantitative engine returned invalid data for %s",
            symbol,
        )
        quant = {}

    report_progress(
        progress_callback,
        50,
        "quant",
        "Quantitative risk engine complete",
        "Core market risk metrics calculated.",
    )

    # --------------------------------------------------------
    # Stage 4 — Security
    # --------------------------------------------------------

    report_progress(
        progress_callback,
        54,
        "security",
        "Checking structural risk signals",
        "Evaluating available contract security data.",
    )

    if symbol.upper() in NATIVE_ASSETS:
        security = {
            "status": "Not applicable",
            "confidence": None,
            "flags": [],
            "red_flags": [],
            "source": "Asset classification",
            "timestamp": utc_now_iso(),
            "available": False,
            "not_applicable": True,
        }

    elif chain_id and contract_address:
        security = fetch_token_security(
            chain_id,
            contract_address,
        )

    else:
        security = {
            "status": (
                "Not applicable — no contract address provided"
            ),
            "confidence": None,
            "flags": [],
            "red_flags": [],
            "source": "Not provided",
            "timestamp": utc_now_iso(),
            "available": False,
            "not_applicable": True,
        }

    if not isinstance(security, dict):
        security = {
            "status": "Unavailable",
            "confidence": 0,
            "flags": [],
            "red_flags": [],
            "source": "GoPlus",
            "timestamp": utc_now_iso(),
            "available": False,
        }

    # --------------------------------------------------------
    # Stage 5 — Risk profile
    # --------------------------------------------------------

    report_progress(
        progress_callback,
        60,
        "risk",
        "Building composite risk profile",
        "Combining quantitative risk pillars.",
    )

    risk_profile = build_risk_profile(
        market,
        quant,
        security,
    )

    risk_drivers = build_risk_drivers(
        risk_profile,
    )

    # --------------------------------------------------------
    # Stage 6 — Stress test
    # --------------------------------------------------------

    report_progress(
        progress_callback,
        67,
        "stress",
        "Running downside stress scenarios",
        "Testing BTC-linked downside scenarios.",
    )

    beta_value = extract_beta_value(
        quant
    )

    volatility_value = extract_volatility_value(
        quant,
        market,
    )

    liquidity_score = (
        risk_profile
        .get("pillars", {})
        .get("liquidity", {})
        .get("score")
    )

    stress = calculate_stress_test(
        beta_value,
        volatility_value,
        liquidity_score,
    )

    report_progress(
        progress_callback,
        73,
        "stress",
        "Stress testing complete",
        "Scenario analysis completed.",
    )

    # --------------------------------------------------------
    # Stage 7 — Evidence
    # --------------------------------------------------------

    report_progress(
        progress_callback,
        78,
        "evidence",
        "Building evidence package",
        "Preparing verified quantitative inputs for AI interpretation.",
    )

    evidence = build_evidence_pack(
        symbol,
        market,
        quant,
        risk_profile,
        stress,
        security,
        risk_drivers,
    )

    report_progress(
        progress_callback,
        82,
        "evidence",
        "Evidence package ready",
        "AI will interpret the calculated evidence only.",
    )

    # --------------------------------------------------------
    # Stage 8 — Gemini
    # --------------------------------------------------------

    report_progress(
        progress_callback,
        86,
        "ai",
        "Synthesizing intelligence",
        "Gemini is interpreting the quantitative evidence.",
    )

    ai = run_gemini_interpretation(
        symbol,
        evidence,
        risk_profile,
        stress,
        security,
        gemini_max_retries_override=(
            gemini_max_retries_override
        ),
    )

    if not isinstance(ai, dict):
        logger.warning(
            "Gemini returned invalid response for %s",
            symbol,
        )
        ai = {
            "provider": "unknown",
            "fallback_used": True,
        }

    report_progress(
        progress_callback,
        93,
        "ai",
        "AI synthesis complete",
        (
            "Interpretation validated and normalized."
            if not ai.get("fallback_used")
            else
            "AI unavailable; deterministic analysis retained."
        ),
    )

    # --------------------------------------------------------
    # Stage 9 — Final report
    # --------------------------------------------------------

    report_progress(
        progress_callback,
        96,
        "save",
        "Finalizing intelligence report",
        "Combining market, quantitative, stress and AI layers.",
    )

    report = build_structured_report(
        symbol,
        market,
        quant,
        security,
        risk_profile,
        stress,
        risk_drivers,
        evidence,
        ai,
    )

    report_progress(
        progress_callback,
        98,
        "save",
        "Intelligence report ready",
        "Report successfully assembled.",
    )

    return report