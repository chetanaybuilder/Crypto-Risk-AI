import time
import logging
from typing import Dict, Any, List, Optional
from config import *
from extensions import *
from utils.helpers import *
from utils.math_helpers import *
from services.coingecko import fetch_market_data, enrich_market_7d, fetch_price_history
from services.goplus import fetch_token_security
from services.db_service import submit_analysis_job, update_analysis_job
from services.gemini import run_gemini_interpretation

logger = logging.getLogger(__name__)

def score_volatility(
    volatility,
):
    """
    Convert annualized volatility into a 0–100 risk score.

    Scoring bands (annualized volatility %):
        ≤20%  → 15 (Low risk)
        ≤40%  → 30 (Moderate)
        ≤60%  → 50 (Elevated)
        ≤80%  → 70 (High)
        ≤120% → 85 (Very high)
        >120% → 95 (Extreme)

    Higher volatility = higher risk.
    """

    if volatility is None:
        return None

    volatility = optional_numeric(
        volatility
    )

    if volatility is None:
        return None

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


def score_liquidity(
    volume_24h,
    market_cap,
):
    """
    Estimate liquidity risk using 24h volume / market cap.

    Higher turnover generally means lower liquidity risk.
    """

    volume_24h = optional_numeric(
        volume_24h
    )

    market_cap = optional_numeric(
        market_cap
    )

    if volume_24h is None:
        return None

    if market_cap is None or market_cap <= 0:
        # Degraded but useful fallback when CoinGecko market cap is
        # unavailable: score observable 24h quote volume directly.
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

    turnover = (
        volume_24h / market_cap
    )

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


def score_beta(
    beta,
):
    """
    Convert BTC beta into market-sensitivity risk.
    """

    beta = optional_numeric(
        beta
    )

    if beta is None:
        return None

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


def score_structural_risk(
    security,
):
    """
    Convert contract/security findings into a 0–100 risk score.

    Missing security data is NOT automatically treated as
    dangerous.
    """

    if not security:
        return None

    if security.get("not_applicable"):
        return None

    status = str(
        security.get(
            "status",
            "",
        )
    ).strip().lower()

    if status in {
        "unavailable",
        "not available",
        "unknown",
    }:
        return None

    flags = security.get(
        "flags"
    ) or []

    if not isinstance(
        flags,
        list,
    ):
        flags = []

    score = 10

    for flag in flags:

        text = str(
            flag
        ).lower()

        if "honeypot" in text:
            score += 45

        elif "blacklist" in text:
            score += 30

        elif "ownership" in text:
            score += 25

        elif "tax" in text:
            score += 20

        elif "source" in text:
            score += 10

        else:
            score += 8

    return clamp(
        score,
        0,
        100,
    )


def risk_label(
    score,
):
    """
    Convert composite score into a human-readable label.
    """

    if score is None:
        return "Unavailable"

    score = optional_numeric(
        score
    )

    if score is None:
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
    Calculate weighted composite risk score (0-100).

    Methodology:
        Only available (non-None) signals participate in the
        weighted average. This ensures the composite score
        remains meaningful even when some data sources are
        unavailable.

        composite = Σ(score_i × weight_i) / Σ(weight_i)

    Confidence is derived from total weight participation:
        - Full participation (all 4 signals) → ~95% confidence
        - Partial participation → scaled proportionally
        - Minimum floor of 10% confidence

    Returns:
        tuple: (composite_score, confidence_percentage)
    """

    values = {
        "volatility": volatility_score,
        "liquidity": liquidity_score,
        "market_sensitivity": sensitivity_score,
        "structural": structural_score,
    }

    weighted_sum = 0.0
    weight_sum = 0.0

    for key, value in values.items():

        if value is None:
            continue

        # Clamp each score to valid 0-100 range
        value = clamp(
            numeric(
                value,
                default=0,
            ),
            0,
            100,
        )

        weight = RISK_WEIGHTS[
            key
        ]

        weighted_sum += (
            value * weight
        )

        weight_sum += weight

    if weight_sum <= 0:
        return None, 0, True

    # Weighted average of available signals
    composite = (
        weighted_sum / weight_sum
    )

    # Confidence scales with data availability (10% floor, 95% ceiling)
    confidence = clamp(
        10 + int(
            weight_sum * 90
        ),
        10,
        95,
    )

    # Composite score considers partial data if available signals < 50%
    is_partial = weight_sum < 0.5

    return (
        int(
            round(
                composite,
                0,
            )
        ),
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

    Pipeline:
        1. Extract scalar values from nested quant structure
        2. Apply scoring functions to convert raw metrics → 0-100 scores
        3. Compute weighted composite score via calculate_composite_risk()
        4. Assemble pillar breakdown with labels, weights, and detail text

    Returns:
        dict: risk_profile with composite_score, label, confidence, pillars
    """

    market = market or {}
    quant = quant or {}

    volatility = extract_volatility_value(
        quant,
        market,
    )

    beta = extract_beta_value(
        quant
    )

    # NOTE: the market dict produced anywhere in this pipeline
    # (empty_market_data / fetch_coingecko_market)
    # only ever sets "volume_24h" and "market_cap" — there is no
    # "_usd"-suffixed variant. A dead first-lookup for "volume_24h_usd"
    # / "market_cap_usd" used to sit here; it always missed and fell
    # through to the correct key below, so behavior is unchanged —
    # this just removes the misleading dead branch.
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

    if security and security.get("not_applicable"):
        structural_detail = "Not applicable."
    elif security and security.get("available"):
        structural_detail = security.get(
            "status",
            "Security assessment available.",
        )
    else:
        structural_detail = "Contract security assessment unavailable."

    composite, confidence, is_partial = (
        calculate_composite_risk(
            volatility_score,
            liquidity_score,
            sensitivity_score,
            structural_score,
        )
    )

    pillars = {
        "volatility": {
            "score": volatility_score,
            "label": risk_label(
                volatility_score
            ),
            "weight": RISK_WEIGHTS[
                "volatility"
            ],
            "detail": (
                f"Annualized realized volatility: "
                f"{format_number(volatility, 1)}%"
                if volatility is not None
                else
                "Volatility data unavailable."
            ),
        },

        "liquidity": {
            "score": liquidity_score,
            "label": risk_label(
                liquidity_score
            ),
            "weight": RISK_WEIGHTS[
                "liquidity"
            ],
            "detail": (
                "Liquidity estimated from 24h "
                "volume-to-market-cap turnover."
                if liquidity_score is not None
                else
                (
                    "Liquidity signal unavailable: volume was not returned."
                    if volume is None
                    else
                    "Liquidity estimated from 24h volume only; market cap is unavailable."
                )
            ),
        },

        "market_sensitivity": {
            "score": sensitivity_score,
            "label": risk_label(
                sensitivity_score
            ),
            "weight": RISK_WEIGHTS[
                "market_sensitivity"
            ],
            "detail": (
                f"BTC beta: "
                f"{format_number(beta, 2)}"
                if beta is not None
                else
                "BTC sensitivity unavailable."
            ),
        },

        "structural": {
            "score": structural_score,
            "label": risk_label(
                structural_score
            ),
            "weight": RISK_WEIGHTS[
                "structural"
            ],
            "detail": structural_detail,
        },
    }

    risk_profile = {
        "composite_score": composite,
        "label": risk_label(
            composite
        ),
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
    Simulate downside scenarios relative to BTC shocks.

    This is a scenario model, NOT a prediction.

    Tracks which inputs are assumed defaults vs measured values
    so the output can flag when confidence scores are built on
    guessed parameters rather than real data.
    """

    beta_is_assumed = beta is None
    volatility_is_assumed = volatility is None
    liquidity_is_assumed = liquidity_score is None

    beta = optional_numeric(beta)
    if beta is None:
        return json_safe({
            "available": False,
            "unavailable_reason": "Beta unavailable — no historical BTC data",
            "base_scenario": {},
            "scenarios": [],
            "expected_downside_pct": None,
            "resilience_score": None,
            "verdict": "Unavailable — no BTC benchmark history",
            "confidence": None,
        })

    volatility = optional_numeric(volatility)
    if volatility is None:
        volatility = 60.0

    liquidity_score = optional_numeric(liquidity_score)
    if liquidity_score is None:
        liquidity_score = 50.0

    scenarios = []

    for btc_shock in [
        -5,
        -10,
        -20,
        -30,
    ]:

        raw_move = (
            btc_shock * beta
        )

        volatility_uncertainty = (
            min(
                volatility / 100,
                1.5,
            )
            * abs(raw_move)
            * 0.12
        )

        liquidity_penalty = (
            max(
                liquidity_score - 50,
                0,
            )
            / 100
        ) * abs(raw_move) * 0.15

        estimated_move = (
            raw_move
            - volatility_uncertainty
            - liquidity_penalty
        )

        resilience = clamp(
            100
            - abs(estimated_move) * 2.0
            - liquidity_score * 0.20,
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
            if item[
                "btc_shock_pct"
            ] == -10
        ),
        scenarios[0],
    )

    confidence = clamp(
        90
        - abs(beta - 1) * 20
        - max(
            volatility - 70,
            0,
        ) * 0.15
        - (40 if volatility_is_assumed else 0)
        - (20 if liquidity_is_assumed else 0),
        10,
        90,
    )

    if (
        ten_percent_case[
            "resilience_score"
        ] >= 65
    ):
        verdict = (
            "Relatively resilient"
        )

    elif (
        ten_percent_case[
            "resilience_score"
        ] >= 40
    ):
        verdict = (
            "Moderate stress sensitivity"
        )

    else:
        verdict = (
            "High downside sensitivity"
        )

    expected_drawdown_pct = (
        ten_percent_case.get(
            "estimated_asset_move_pct"
        )
    )

    drawdown_percent = (
        expected_drawdown_pct
        if expected_drawdown_pct is not None
        else None
    )

    resilience_score = (
        ten_percent_case.get(
            "resilience_score"
        )
    )

    if resilience_score is None:
        resilience_label = "Unavailable"
    elif resilience_score >= 65:
        resilience_label = "Resilient"
    elif resilience_score >= 40:
        resilience_label = "Moderate"
    else:
        resilience_label = "Fragile"

    # Build list of assumed parameters for transparency
    assumed_parameters = []
    if beta_is_assumed:
        assumed_parameters.append("beta")
    if volatility_is_assumed:
        assumed_parameters.append("volatility")
    if liquidity_is_assumed:
        assumed_parameters.append("liquidity_score")

    stress_report = {
        "benchmark": "BTC",
        "scenarios": scenarios,
        "base_scenario": ten_percent_case,
        "beta": round(
            beta,
            3,
        ),
        "volatility": round(
            volatility,
            2,
        ),
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
            round(
                drawdown_percent,
                2,
            )
            if drawdown_percent is not None
            else None
        ),
        "drawdown_pct": (
            round(
                drawdown_percent,
                2,
            )
            if drawdown_percent is not None
            else None
        ),
        "resilience_label": resilience_label,
        "resilience_score": (
            round(
                resilience_score,
                1,
            )
            if resilience_score is not None
            else None
        ),
        "assumed_parameters": assumed_parameters,
        "used_default_beta": beta_is_assumed,
        "used_default_volatility": volatility_is_assumed,
        "methodology": (
            "Scenario estimates combine BTC beta, "
            "realized volatility and liquidity risk. "
            "They are not forecasts."
        ),
    }

    return json_safe(stress_report)


def build_risk_drivers(
    risk_profile,
    market,
    quant,
    security=None,
):
    """
    Produce concise, evidence-backed risk drivers.
    """

    drivers = []

    pillars = (
        risk_profile.get(
            "pillars",
            {}
        )
        if risk_profile
        else {}
    )

    volatility = pillars.get(
        "volatility",
        {},
    )

    liquidity = pillars.get(
        "liquidity",
        {},
    )

    sensitivity = pillars.get(
        "market_sensitivity",
        {},
    )

    structural = pillars.get(
        "structural",
        {},
    )

    if (
        volatility.get("score") is not None
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
        liquidity.get("score") is not None
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
        sensitivity.get("score") is not None
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
        structural.get("score") is not None
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
            "title": (
                "No dominant quantitative red flag"
            ),
            "severity": "Moderate",
            "detail": (
                "Current available signals do not "
                "show a single dominant risk driver."
            ),
        })

    return drivers[:6]


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

    Gemini receives both scalar summaries and detailed
    quantitative structures.
    """

    market = market or {}
    quant = quant or {}

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
            "price_usd": market.get(
                "price"
            ),
            "change_24h_pct": market.get(
                "price_change_24h_pct"
            ),
            "change_7d_pct": market.get(
                "price_change_7d_pct"
            ),
            "volume_24h_usd": market.get(
                "volume_24h"
            ),
            "market_cap_usd": market.get(
                "market_cap"
            ),
            "high_24h_usd": market.get(
                "high_24h"
            ),
            "low_24h_usd": market.get(
                "low_24h"
            ),
            "source": market.get(
                "source"
            ),
        },

        "quantitative": {
            "volatility_pct": volatility,
            "beta_to_btc": beta,
            "max_drawdown_pct": quant.get(
                "max_drawdown_pct"
            ),
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

        "security": security or {
            "available": False,
            "status": "Unavailable",
        },

        "risk_drivers": risk_drivers,

        "data_quality": market.get(
            "data_quality",
            {},
        ),
    }

    return json_safe(evidence)


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
    Final normalized report consumed by the frontend.
    """

    composite_score = (
        risk_profile.get(
            "composite_score"
        )
    )

    market = market or {}
    quant = quant or {}
    ai = ai or {}
    stress = stress or {}

    # ------------------------------------------------------------------
    # Data Quality Module
    #
    # The provider market payload may not carry a nested
    # ``data_quality`` object.  Build a normalized one so the
    # frontend's Data Confidence card is always populated.
    #
    # Signals checked:
    #   - Live price availability
    #   - 24h volume availability
    #   - Market cap availability
    #   - Price history observations
    #
    # Missing signals are surfaced to the frontend for transparent
    # risk communication. When all signals are present, the frontend
    # displays "All primary risk vectors verified."
    # ------------------------------------------------------------------

    data_quality = (
        market.get(
            "data_quality",
            {},
        )
        if isinstance(
            market.get(
                "data_quality"
            ),
            dict,
        )
        else {}
    )

    dq = dict(
        data_quality
    )

    is_native_asset = symbol.upper() in NATIVE_ASSETS

    # FIX (Bug 2): a missing contract address is "not applicable",
    # NOT a failed/missing signal. "Contract security" only counts
    # against data quality when an address WAS provided but GoPlus
    # could not resolve it — in that case security is a genuine
    # failure (not_applicable is False / absent).
    security_not_applicable = (
        isinstance(security, dict)
        and security.get("not_applicable")
        is True
    )

    field_checks = {
        "Live price": market.get("price"),
        "24h volume": market.get("volume_24h"),
        "Market cap": market.get("market_cap"),
        "24h high": market.get("high_24h"),
        "24h low": market.get("low_24h"),
        "Price history": quant.get("history_observations"),
        "BTC benchmark history": quant.get("btc_history_observations"),
    }

    if (
        not is_native_asset
        and not security_not_applicable
    ):
        field_checks["Contract security"] = (
            True
            if isinstance(security, dict) and security.get("available")
            else None
        )

    available_fields = [
        name
        for name, value in field_checks.items()
        if value is not None and value != 0
    ]
    missing_signals = [
        name
        for name, value in field_checks.items()
        if value is None or value == 0
    ]

    # Also surface any field-level parse errors reported by the provider
    # (e.g., total_volume parse failures) even when the final top-level
    # field appears non-None from another source.
    #
    # FIX (B2): field_checks uses human-readable labels ("Market cap")
    # while field_errors historically used raw internal provider keys
    # ("market_cap"), so the SAME missing field was shown twice with
    # different casing ("Market cap" AND "market_cap"). Every
    # field_errors key is now translated through FIELD_LABELS to the
    # exact same display name used in field_checks, and the merged
    # list is deduplicated while preserving order.
    field_errors = dict(
        market.get("field_errors")
        if isinstance(market.get("field_errors"), dict)
        else {}
    )
    for error_field in field_errors:
        error_label = _field_error_label(error_field)

        if error_label not in missing_signals:
            missing_signals.append(error_label)

    # Final dedup (order-preserving) so no field can ever appear
    # twice in the UI under any name.
    deduped_missing_signals = []
    for signal_name in missing_signals:
        if signal_name not in deduped_missing_signals:
            deduped_missing_signals.append(signal_name)
    missing_signals = deduped_missing_signals

    dq["available_fields"] = available_fields
    dq["field_errors"] = field_errors
    dq["source_timestamps"] = dict(
        market.get("source_timestamps")
        if isinstance(market.get("source_timestamps"), dict)
        else {}
    )
    dq["missing_signals"] = missing_signals
    dq["not_applicable"] = (
        ["Contract security"]
        if (is_native_asset or security_not_applicable)
        else []
    )
    base_confidence = len(available_fields) / len(field_checks) * 100
    dq["confidence"] = round(
        min(
            base_confidence,
            risk_profile.get("confidence", 100)
        ),
        1,
    )

    dq["source"] = first_defined(
        market.get(
            "source"
        ),
        "Backend market feed",
    )

    # Pass through the fallback-provider flag so the frontend can
    # show a "via CoinMarketCap" label when CMC data is used.
    dq["is_fallback_provider"] = bool(
        market.get("is_fallback_provider", False)
    )

    report = {
        "schema_version": (
            REPORT_SCHEMA_VERSION
        ),

        "token_symbol": (
            symbol.upper()
        ),

        "asset": {
            "symbol": symbol.upper(),
            "name": market.get(
                "asset_name",
                symbol.upper(),
            ),
        },

        "outlook": (
            risk_profile.get(
                "label",
                "Unavailable",
            )
        ),

        "risk_score": composite_score,

        "risk_label": (
            risk_profile.get(
                "label",
                "Unavailable",
            )
        ),

        "risk_confidence": (
            risk_profile.get(
                "confidence",
                0,
            )
        ),

        "market": market,

        "quantitative": quant,

        "risk_profile": risk_profile,

        "risk_drivers": risk_drivers,

        "security": security or {
            "status": "Unavailable",
            "available": False,
            "flags": [],
            "red_flags": [],
            "confidence": 0,
        },

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
            "generated_at": (
                utc_now_iso()
            ),
            "interpretation_only": True,
            "scenario_model": True,
        },
    }

    # Final safety pass — ensure no NaN/Inf/Decimal/datetime values
    # leak into the JSON response. json.dumps raises ValueError on
    # NaN/Inf, which would surface as a 500 error in production.
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

    Callback signature:

        callback(
            percent,
            stage,
            title,
            message,
        )
    """

    if not callable(
        callback
    ):
        return

    try:

        callback(
            int(
                clamp(
                    percent,
                    0,
                    100,
                )
            ),
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
    gemini_max_retries_override: Optional[int] = None,
):
    """
    Main CryptoRisk AI pipeline.

    Pipeline:

        Market
          ↓
        History
          ↓
        Quantitative Engine
          ↓
        Security
          ↓
        Risk Profile
          ↓
        Stress Test
          ↓
        Evidence
          ↓
        Gemini
          ↓
        Structured Report

    gemini_max_retries_override: Optional[int]
        If not None, overrides GEMINI_MAX_RETRIES when calling
        run_gemini_interpretation(). Used by the synchronous
        /api/analyze route to force zero retries and cap
        worst-case latency. The background job path ignores
        this parameter and always uses GEMINI_MAX_RETRIES.
    """

    symbol = normalize_symbol(
        symbol
    )

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

    if not isinstance(market, dict) or not market.get("available"):
        logger.warning(
            "Market data unavailable for %s: %s",
            symbol,
            market.get(
                "unavailable_reason",
                "CoinGecko did not return usable market data.",
            )
            if isinstance(market, dict)
            else "CoinGecko did not return usable market data."
        )

    report_progress(
        progress_callback,
        20,
        "market",
        "Live market data received",
        "Market snapshot collected.",
    )

    # --------------------------------------------------------
    # Stage 2 — Historical Data
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

    # P1: enrich the market payload's 7d change from the same 30-day
    # series we just fetched, instead of letting fetch_market_data()
    # fire a second, overlapping 8-day CoinGecko request. This keeps a
    # single analysis to exactly one history request per symbol.
    try:
        market = enrich_market_7d(
            market,
            symbol,
            history=asset_history,
        )
    except Exception as exc:
        logger.debug("Market 7d enrichment (P1) failed: %s", exc)

    report_progress(
        progress_callback,
        38,
        "history",
        "Historical data ready",
        "Historical datasets prepared.",
    )

    # --------------------------------------------------------
    # Stage 3 — Quantitative Engine
    # --------------------------------------------------------

    report_progress(
        progress_callback,
        43,
        "quant",
        "Running quantitative risk engine",
        "Calculating volatility, beta, liquidity and drawdown.",
    )

    # IMPORTANT:
    # PART 1 signature is:
    #
    # calculate_quant_metrics(
    #     symbol,
    #     market,
    #     history,
    #     btc_history,
    # )
    #
    quant = calculate_quant_metrics(
        symbol,
        market,
        asset_history,
        btc_history,
    )

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

    elif (
        chain_id
        and contract_address
    ):

        security = fetch_token_security(
            chain_id,
            contract_address,
        )

    else:

        # FIX (Bug 2): the frontend can now send chain_id +
        # contract_address. When it doesn't, this is NOT a data
        # failure — the user simply didn't provide a contract, so the
        # signal is "not applicable" rather than "Unavailable".
        # data_quality.not_applicable marks it, so it neither lowers
        # the confidence score nor shows as a red missing-signal.
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

    # --------------------------------------------------------
    # Stage 5 — Risk Profile
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
        market,
        quant,
        security,
    )

    # --------------------------------------------------------
    # Stage 6 — Stress Test
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

    volatility_value = (
        extract_volatility_value(
            quant,
            market,
        )
    )

    liquidity_score = (
        risk_profile.get(
            "pillars",
            {}
        )
        .get(
            "liquidity",
            {}
        )
        .get(
            "score"
        )
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
        gemini_max_retries_override=gemini_max_retries_override,
    )

    report_progress(
        progress_callback,
        93,
        "ai",
        "AI synthesis complete",
        (
            "Interpretation validated and normalized."
            if not ai.get(
                "fallback_used"
            )
            else
            "AI unavailable; deterministic analysis retained."
        ),
    )

    # --------------------------------------------------------
    # Stage 9 — Save / Final Report
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


