import logging
import re
from urllib.parse import quote

from config import GOPLUS_API_URL, MARKET_TIMEOUT
from utils.helpers import (
    _http_get_market,
    format_number,
    json_safe,
    utc_now_iso,
)
from utils.math_helpers import clamp, optional_numeric

logger = logging.getLogger(__name__)


def goplus_bool(value):
    """
    Parse GoPlus boolean-like values.

    Missing or unknown values remain None.
    """
    if value is None:
        return None

    normalized = str(value).strip().lower()

    if normalized in {"1", "true", "yes"}:
        return True

    if normalized in {"0", "false", "no"}:
        return False

    return None


def goplus_number(value):
    """
    Parse GoPlus numeric values.

    Missing or invalid values remain None.
    """
    if value is None:
        return None

    return optional_numeric(value)


def _unavailable_report(message):
    """
    Return the standard unavailable GoPlus response.
    """
    return {
        "status": "Unavailable",
        "confidence": 0,
        "flags": [message],
        "red_flags": [],
        "source": "GoPlus",
        "timestamp": utc_now_iso(),
        "available": False,
    }


def fetch_token_security(chain_id, contract_address):
    """
    Fetch token contract security information from GoPlus.

    Missing GoPlus fields remain unknown rather than being treated
    as safe or unsafe.
    """
    if not chain_id or not contract_address:
        return _unavailable_report(
            "Contract security provider unavailable."
        )

    address = str(contract_address).strip()

    if not re.fullmatch(r"0x[a-fA-F0-9]{40}", address):
        return {
            "status": "Unavailable",
            "confidence": 0,
            "flags": ["Invalid contract address format."],
            "red_flags": [],
            "source": "GoPlus",
            "timestamp": utc_now_iso(),
            "available": False,
        }

    address = address.lower()
    chain_id = str(chain_id).strip()

    try:
        url = (
            f"{GOPLUS_API_URL.rstrip('/')}/"
            f"{quote(chain_id, safe='')}"
        )

        response, status_code, error_reason = _http_get_market(
            url,
            params={
                "contract_addresses": address,
            },
            timeout=MARKET_TIMEOUT,
        )

        if response is None or (
            status_code is not None and status_code >= 400
        ):
            logger.warning(
                "GoPlus security lookup failed for chain=%s addr=%s: %s",
                chain_id,
                address,
                error_reason or f"HTTP {status_code}",
            )
            return _unavailable_report(
                "Contract security provider unavailable."
            )

        try:
            payload = response.json()
        except ValueError:
            logger.warning(
                "GoPlus returned invalid JSON for chain=%s addr=%s",
                chain_id,
                address,
            )
            return _unavailable_report(
                "Contract security provider returned invalid data."
            )

        if not isinstance(payload, dict):
            return _unavailable_report(
                "Contract security data unavailable."
            )

        api_code = payload.get("code")

        if api_code != 1:
            logger.warning(
                "GoPlus API returned code=%s for chain=%s addr=%s: %s",
                api_code,
                chain_id,
                address,
                payload.get("message"),
            )
            return _unavailable_report(
                "Contract security data unavailable."
            )

        result = payload.get("result")

        if not isinstance(result, dict):
            return _unavailable_report(
                "Contract security data unavailable."
            )

        data = result.get(address)

        if data is None:
            for key, value in result.items():
                if str(key).lower() == address:
                    data = value
                    break

        if not isinstance(data, dict):
            return _unavailable_report(
                "Contract security data unavailable."
            )

        flags = []
        red_flags = []

        honeypot = goplus_bool(
            data.get("is_honeypot")
        )

        if honeypot is True:
            flags.append(
                "Potential honeypot behavior detected."
            )
            red_flags.append(
                "Honeypot risk signal."
            )

        open_source = goplus_bool(
            data.get("is_open_source")
        )

        if open_source is False:
            flags.append(
                "Contract source is not verified."
            )
            red_flags.append(
                "Unverified contract source."
            )

        ownership_recovery = goplus_bool(
            data.get("can_take_back_ownership")
        )

        if ownership_recovery is True:
            flags.append(
                "Ownership recovery capability detected."
            )
            red_flags.append(
                "Ownership-control risk."
            )

        owner_change = goplus_bool(
            data.get("owner_change_balance")
        )

        if owner_change is True:
            flags.append(
                "Owner balance-change capability detected."
            )
            red_flags.append(
                "Owner-controlled balance risk."
            )

        blacklist = goplus_bool(
            data.get("is_blacklisted")
        )

        if blacklist is True:
            flags.append(
                "Blacklist functionality detected."
            )
            red_flags.append(
                "Blacklist/control risk."
            )

        buy_tax = goplus_number(
            data.get("buy_tax")
        )

        sell_tax = goplus_number(
            data.get("sell_tax")
        )

        if buy_tax is not None and buy_tax > 0.05:
            flags.append(
                f"Elevated buy tax detected: "
                f"{format_number(buy_tax * 100, 2)}%."
            )
            red_flags.append(
                "Elevated buy tax."
            )

        if sell_tax is not None and sell_tax > 0.05:
            flags.append(
                f"Elevated sell tax detected: "
                f"{format_number(sell_tax * 100, 2)}%."
            )
            red_flags.append(
                "Elevated sell tax."
            )

        explicit_fields = [
            honeypot,
            open_source,
            ownership_recovery,
            owner_change,
            blacklist,
            buy_tax,
            sell_tax,
        ]

        available_fields = sum(
            value is not None
            for value in explicit_fields
        )

        confidence = clamp(
            40 + available_fields * 8,
            40,
            95,
        )

        if red_flags:
            status = "Audited"
        else:
            status = "Audited"

        security_report = {
            "status": status,
            "score": max(0, 100 - (len(red_flags) * 20)),
            "confidence": confidence,
            "flags": flags,
            "red_flags": red_flags,
            "source": "GoPlus",
            "timestamp": utc_now_iso(),
            "available": True,
            "raw_signals": {
                "honeypot": honeypot,
                "open_source": open_source,
                "ownership_recovery": ownership_recovery,
                "owner_balance_change": owner_change,
                "blacklist": blacklist,
                "buy_tax": buy_tax,
                "sell_tax": sell_tax,
            },
        }

        return json_safe(security_report)

    except Exception as exc:
        print(f"[Contract Audit ERROR] {exc}")
        logger.exception(
            "Unexpected GoPlus security lookup error "
            "for chain=%s addr=%s: %s",
            chain_id,
            address,
            exc,
        )

        return _unavailable_report(
            "Contract security provider unavailable."
        )