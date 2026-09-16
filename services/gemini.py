"""
Gemini AI interpretation layer for CryptoRisk AI.

Gemini is an interpretation layer only — it explains what the
quantitative engine already computed. It must never replace or
override risk_engine.py's numbers.

This module guarantees run_gemini_interpretation() never raises:
any failure anywhere in the pipeline degrades to a deterministic
fallback report instead of propagating an exception to callers.
"""

import json
import time
import re
import logging
from typing import Optional
from concurrent.futures import TimeoutError as FuturesTimeoutError

from config import (
    AI_STRING_FIELDS,
    FIELD_LABELS,
    GEMINI_MAX_RETRIES,
    GEMINI_TIMEOUT_SECONDS,
    AI_LIST_FIELDS,
)
from utils.helpers import format_number, json_safe
from utils.math_helpers import clamp

# Explicit imports instead of `from extensions import *`.
# `_gemini_generate` is underscore-prefixed, so a wildcard import
# silently skips it unless extensions.py lists it in __all__ — that
# was a near-certain NameError the first time Gemini was actually
# called. Importing explicitly here removes that fragility.
from extensions import gemini_client, GEMINI_EXECUTOR, _gemini_generate

logger = logging.getLogger(__name__)

# Safety net: even if config accidentally ships with 0 retries, we
# still want at least one retry on a timeout/transient error before
# giving up. A single slow response should not permanently degrade
# every report to the fallback text.
_MIN_RETRIES = 1

# Base delay for exponential backoff between retry attempts.
_RETRY_BASE_DELAY_SECONDS = 0.5


def build_gemini_prompt(symbol, evidence):
    """
    Build the strict, evidence-only interpretation prompt sent to Gemini.
    """

    evidence_json = json.dumps(
        json_safe(evidence),
        ensure_ascii=False,
        indent=2,
    )

    return f"""
You are the AI interpretation layer of CryptoRisk AI.

Analyze ONLY the supplied evidence packet.

Asset:
{symbol.upper()}

EVIDENCE PACK:
{evidence_json}

STRICT RULES:

1. Do not invent prices, percentages, news, events,
   contract findings, market conditions, or statistics.

2. Every factual statement must be supported by the evidence.

3. If information is unavailable, explicitly say it is unavailable.

4. Do not pretend that missing contract/security data means
   the contract is safe.

5. Do not make buy/sell recommendations.

6. Do not provide personalized financial advice.

7. Do not predict a guaranteed future outcome.

8. Stress scenarios are scenarios, NOT forecasts.

9. Explain what the quantitative numbers mean.

10. AVOID GENERIC TEMPLATES: Do not write sentences like "The strongest
    available risk signal is volatility" or "Monitor structural
    security." Instead, write highly specific, data-driven analysis
    using the exact numbers and asset characteristics from the
    evidence packet. Your reasoning must be entirely bespoke for the
    specific asset.

11. Clearly identify the most important weaknesses in the
    current evidence.

12. Distinguish observed facts from scenario interpretation.

13. If any signals are missing in the evidence, the executive
    summary must explicitly start with a caveat acknowledging
    that it is based on partial data.

14. PRECISION: Whenever a numeric value exists in the evidence packet,
    quote it exactly as given (same decimal precision, same units).
    Never round, estimate, or hedge with words like "around", "roughly",
    or "approximately" when an exact figure is present in the evidence.
    Reference specific field values by name when explaining a claim
    (e.g. "30-day realized volatility of 84.2%" rather than "high
    volatility").

15. If the asset is a native Layer-1 network (e.g., BTC), treat smart
    contract structural risk as N/A. Do not flag it as 'null' or instruct
    the user to monitor it.

16. Only generate the phrase "Based on partial data" if the missing
    signals array length is greater than zero. If the array is empty,
    state that the data is fully verified.

17. Output plain text and avoid wrapping risk categories or null values
    in quotation marks.

18. Apply an absolute value function Math.abs() to price change variables
    when paired with negative verbs to prevent phrases like "decreased by -0.83%".

19. OUTPUT FORMAT: Return ONLY the JSON object below. No markdown code
    fences, no preamble, no trailing commentary, no explanation outside
    the JSON. The entire response body must be valid, directly
    parseable JSON — nothing else.

Return ONLY valid JSON.

Required JSON structure:

{{
  "executive_summary": "string",
  "risk_regime": "string",
  "primary_risk_driver": "string",
  "secondary_risk_drivers": ["string"],
  "what_changed": "string",
  "what_matters_now": "string",
  "watch_next": "string",
  "risk_mitigating_factors": ["string"],
  "red_flags": ["string"],
  "bull_case": "string",
  "base_case": "string",
  "bear_case": "string",
  "stress_interpretation": "string",
  "data_quality_note": "string",
  "confidence": 0
}}

The confidence value must be between 0 and 100.

Focus on:

- what the numbers actually indicate
- the dominant risk
- important weaknesses
- useful mitigating factors
- what should be monitored next
- limitations in the evidence
- missing security or market signals
"""


def fallback_ai_report(symbol, risk_profile, stress, security=None):
    """
    Safe deterministic fallback when Gemini is unavailable,
    times out, or returns invalid JSON.
    """

    risk_profile = risk_profile or {}
    stress = stress or {}

    score = risk_profile.get("composite_score")
    label = risk_profile.get("label", "Unavailable")

    drivers = []
    for key, pillar in risk_profile.get("pillars", {}).items():
        if isinstance(pillar, dict) and pillar.get("score") is not None:
            drivers.append((key, pillar.get("score")))

    drivers.sort(key=lambda item: item[1], reverse=True)

    primary_driver = drivers[0][0] if drivers else "available quantitative signals"

    security_available = bool(security and security.get("available"))

    if security_available:
        security_note = (
            "Contract security signals were available "
            "from the configured security provider."
        )
    else:
        security_note = (
            "Contract security data was unavailable; "
            "structural risk cannot be fully assessed."
        )

    is_partial = risk_profile.get("partial_data", False)
    partial_prefix = "Based on partial data: " if is_partial else ""

    return {
        "executive_summary": (
            partial_prefix
            + f"{symbol.upper()} currently has a {label.lower()} quantitative risk profile"
            + (
                f" with a composite score of {format_number(score, 1)}."
                if score is not None
                else "."
            )
            + " The analysis is based on the available "
              "market, volatility, liquidity and stress signals."
        ),
        "synthesis": (
            "Gemini AI interpretation is temporarily unavailable. "
            "This report contains only deterministic quantitative signals."
        ),
        "risk_regime": label,
        "primary_risk_driver": (
            f"The strongest available risk signal is {primary_driver.replace('_', ' ')}."
        ),
        "secondary_risk_drivers": [
            "Risk should be interpreted using the full pillar breakdown.",
            "Scenario sensitivity can change as market conditions change.",
        ],
        "what_changed": "Insufficient data to dynamically determine what changed.",
        "what_matters_now": (
            f"Monitor structural security and track changes to the "
            f"{primary_driver.replace('_', ' ')}."
        ),
        "watch_next": "Upcoming market liquidity shifts and beta recalibration.",
        "risk_mitigating_factors": [
            "Quantitative data is continually reassessed.",
            "Stress scenarios provide additional downside context.",
        ],
        "red_flags": security.get("red_flags", []) if security else [],
        "bull_case": "Quantitative model shows strength in mitigating factors.",
        "base_case": f"Market forces align with a {label.lower()} profile.",
        "bear_case": (
            f"Shocks to {primary_driver.replace('_', ' ')} could destabilize the asset."
        ),
        "stress_interpretation": stress.get("verdict", "Stress result unavailable."),
        "data_quality_note": (
            "AI interpretation is limited to the supplied evidence. " + security_note
        ),
        "confidence": 50,
    }


def _minimal_safe_report(symbol, error_note=None):
    """
    Absolute last-resort report.

    Used only if even `fallback_ai_report` itself fails unexpectedly
    (e.g. because of a malformed risk_profile/stress payload), so
    callers of run_gemini_interpretation are guaranteed to always get
    back a well-formed dict and never an exception.
    """

    note = "AI interpretation is unavailable."
    if error_note:
        note += f" ({error_note})"

    try:
        label = str(symbol).upper()
    except Exception:
        label = "the requested asset"

    return {
        "executive_summary": (
            f"Automated interpretation for {label} could not be generated. "
            f"Quantitative signals may still be available separately."
        ),
        "synthesis": "AI interpretation pipeline failed unexpectedly.",
        "risk_regime": "Unavailable",
        "primary_risk_driver": "Unavailable",
        "secondary_risk_drivers": [],
        "what_changed": "Unavailable",
        "what_matters_now": "Unavailable",
        "watch_next": "Unavailable",
        "risk_mitigating_factors": [],
        "red_flags": [],
        "bull_case": "Unavailable",
        "base_case": "Unavailable",
        "bear_case": "Unavailable",
        "stress_interpretation": "Unavailable",
        "data_quality_note": note,
        "confidence": 0,
        "provider": "deterministic_fallback",
        "fallback_used": True,
        "partially_invalid_fields": ["all"],
    }


def clean_ai_text(value, fallback="", max_length=1800):
    if not isinstance(value, str):
        return fallback

    value = value.strip()
    if not value:
        return fallback

    return value[:max_length]


def clean_ai_list(value, fallback=None, max_items=6):
    if not isinstance(value, list):
        return fallback or []

    result = []
    for item in value:
        if not isinstance(item, str):
            continue

        text = item.strip()
        if not text:
            continue

        result.append(text[:500])
        if len(result) >= max_items:
            break

    if not result:
        return fallback or []

    return result


def validate_ai_report(parsed, fallback):
    """
    Normalize Gemini output without allowing malformed content to
    break the report.

    Returns:
        tuple: (cleaned_dict, fallback_used, fallback_fields)
            fallback_used: bool - True if any field needed fallback
            fallback_fields: list - which specific fields used fallback
    """

    if not isinstance(parsed, dict):
        return fallback, True, ["all"]

    cleaned = dict(fallback)
    fallback_used = False
    fallback_fields = []

    for field in AI_STRING_FIELDS:
        value = parsed.get(field)

        if not isinstance(value, str) or not value.strip():
            fallback_used = True
            fallback_fields.append(field)

        cleaned[field] = clean_ai_text(value, fallback.get(field, ""))

    for field in AI_LIST_FIELDS:
        value = parsed.get(field)

        if not isinstance(value, list):
            fallback_used = True
            fallback_fields.append(field)

        cleaned[field] = clean_ai_list(value, fallback=fallback.get(field, []))

    confidence = parsed.get("confidence")

    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = fallback.get("confidence", 50)
        fallback_used = True
        fallback_fields.append("confidence")

    cleaned["confidence"] = round(clamp(confidence, 0, 100), 1)

    return cleaned, fallback_used, fallback_fields


def extract_json_object(text):
    """
    Extract JSON even if Gemini accidentally surrounds it with
    whitespace or markdown code fences.
    """

    if not isinstance(text, str):
        return None

    text = text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE)
        text = re.sub(r"```$", "", text).strip()

    try:
        return json.loads(text)
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end <= start:
        return None

    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return None


def _resolve_max_retries(override: Optional[int]) -> int:
    """
    Resolve the effective retry budget for this call.

    - Uses the override if provided (e.g. /api/analyze wants 0 retries
      for bounded latency on a synchronous request).
    - Falls back to config.GEMINI_MAX_RETRIES otherwise.
    - Never lets a background job silently run with zero retries:
      a single slow/timed-out Gemini response would then permanently
      degrade every report to the fallback text, which is what was
      happening in production. _MIN_RETRIES enforces a floor unless
      the caller explicitly overrode retries (bounded-latency callers
      are allowed to ask for 0 and get exactly 0).
    """

    if override is not None:
        try:
            return max(0, int(override))
        except (TypeError, ValueError):
            pass

    try:
        configured = max(0, int(GEMINI_MAX_RETRIES))
    except (TypeError, ValueError):
        configured = _MIN_RETRIES

    return max(configured, _MIN_RETRIES)


def run_gemini_interpretation(
    symbol,
    evidence,
    risk_profile,
    stress,
    security=None,
    gemini_max_retries_override: Optional[int] = None,
):
    """
    Reliable Gemini layer.

    Features:
      - SDK timeout
      - future timeout
      - retry with exponential backoff
      - JSON extraction
      - response validation
      - deterministic fallback

    gemini_max_retries_override: Optional[int]
        If not None, overrides the retry budget for this call (e.g. a
        synchronous endpoint requesting 0 retries for bounded latency).
        Background jobs should leave this as None to get the full
        configured budget.

    Guarantee: this function never raises. Any unexpected failure,
    anywhere in the pipeline, degrades to a safe fallback report
    instead of propagating an exception to the caller.
    """

    try:
        return _run_gemini_interpretation(
            symbol,
            evidence,
            risk_profile,
            stress,
            security=security,
            gemini_max_retries_override=gemini_max_retries_override,
        )
    except Exception as exc:
        # Last-resort net: nothing above this point should ever get
        # here, but if fallback_ai_report/build_gemini_prompt/etc.
        # choke on unexpected input shapes, callers still get a valid
        # report dict instead of a crash.
        logger.exception(
            "Unhandled failure in run_gemini_interpretation for %s: %s",
            symbol,
            exc,
        )
        return json_safe(_minimal_safe_report(symbol, str(exc)))


def _run_gemini_interpretation(
    symbol,
    evidence,
    risk_profile,
    stress,
    security=None,
    gemini_max_retries_override: Optional[int] = None,
):

    try:
        fallback = fallback_ai_report(symbol, risk_profile, stress, security)
    except Exception as exc:
        logger.exception("fallback_ai_report failed for %s: %s", symbol, exc)
        fallback = _minimal_safe_report(symbol, str(exc))

    fallback["provider"] = "deterministic_fallback"
    fallback["fallback_used"] = True

    if gemini_client is None:
        fallback["data_quality_note"] += " Gemini API is not configured."
        return json_safe(fallback)

    try:
        prompt = build_gemini_prompt(symbol, evidence)
    except Exception as exc:
        logger.exception("build_gemini_prompt failed for %s: %s", symbol, exc)
        fallback["data_quality_note"] += f" Prompt construction failed ({exc})."
        return json_safe(fallback)

    max_retries = _resolve_max_retries(gemini_max_retries_override)
    total_attempts = max_retries + 1

    last_error = None

    for attempt in range(total_attempts):
        future = None
        attempt_start = time.monotonic()

        try:
            future = GEMINI_EXECUTOR.submit(_gemini_generate, prompt)
            raw_text = future.result(timeout=GEMINI_TIMEOUT_SECONDS)

            parsed = extract_json_object(raw_text)
            if parsed is None:
                raise ValueError("Gemini returned invalid JSON.")

            cleaned, used_fallback, fallback_fields = validate_ai_report(
                parsed, fallback
            )

            cleaned["provider"] = "Gemini"
            cleaned["fallback_used"] = used_fallback

            # Store the specific fields that used fallback so the
            # frontend can show granular info instead of implying
            # the entire AI layer failed when only one field was bad.
            cleaned["partially_invalid_fields"] = fallback_fields

            if used_fallback:
                if len(fallback_fields) <= 3:
                    fields_str = ", ".join(fallback_fields)
                    cleaned["data_quality_note"] += (
                        f" Some Gemini fields were invalid or missing "
                        f"({fields_str}) and were replaced with safe defaults."
                    )
                else:
                    cleaned["data_quality_note"] += (
                        f" Some Gemini fields were invalid or missing "
                        f"({len(fallback_fields)} fields) and were replaced "
                        f"with safe defaults."
                    )

            logger.info(
                "Gemini success for %s (attempt %s/%s, %.1fs)",
                symbol,
                attempt + 1,
                total_attempts,
                time.monotonic() - attempt_start,
            )

            return json_safe(cleaned)

        except FuturesTimeoutError:
            last_error = "Gemini analysis timed out."

            logger.warning(
                "Gemini timeout for %s (attempt %s/%s, waited %.1fs of %ss budget)",
                symbol,
                attempt + 1,
                total_attempts,
                time.monotonic() - attempt_start,
                GEMINI_TIMEOUT_SECONDS,
            )

            if future is not None:
                try:
                    future.cancel()
                except Exception:
                    pass

            if attempt < max_retries:
                delay = _RETRY_BASE_DELAY_SECONDS * (2 ** attempt)
                time.sleep(delay)
                continue

            break

        except Exception as exc:
            last_error = str(exc)

            logger.warning(
                "Gemini attempt %s/%s failed for %s after %.1fs: %s",
                attempt + 1,
                total_attempts,
                symbol,
                time.monotonic() - attempt_start,
                exc,
            )

            if attempt < max_retries:
                delay = _RETRY_BASE_DELAY_SECONDS * (2 ** attempt)
                time.sleep(delay)
                continue

            break

    logger.warning(
        "Gemini interpretation exhausted all %s attempt(s) for %s; using fallback. Last error: %s",
        total_attempts,
        symbol,
        last_error,
    )

    fallback["data_quality_note"] += (
        " Gemini interpretation was unavailable"
        + (f" ({last_error})." if last_error else ".")
    )

    return json_safe(fallback)


def _field_error_label(error_field) -> str:
    """
    Translate a raw internal field key into the same human-readable
    label used by field_checks. Unknown keys are normalized to
    readable text (snake_case/camelCase split + title case) so no raw
    internal identifier ever reaches the UI.
    """

    key = str(error_field)
    known = FIELD_LABELS.get(key)

    if known:
        return known

    readable = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", key).replace("_", " ")
    readable = readable.strip().title()

    return readable or key