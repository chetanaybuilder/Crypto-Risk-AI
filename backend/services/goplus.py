import logging
import requests
from config import *
from utils.helpers import *

logger = logging.getLogger(__name__)

def goplus_bool(
    value,
):
    """
    Parse GoPlus boolean-like values.

    Missing values remain unknown rather than becoming False.
    """

    if value is None:
        return None

    normalized = (
        str(value)
        .strip()
        .lower()
    )

    if normalized in {
        "1",
        "true",
        "yes",
    }:
        return True

    if normalized in {
        "0",
        "false",
        "no",
    }:
        return False

    return None


def goplus_number(
    value,
):
    """
    Parse GoPlus numeric values.

    Missing or invalid values remain None.
    """

    if value is None:
        return None

    return optional_numeric(
        value
    )


def fetch_token_security(
    chain_id,
    contract_address,
):
    """
    Fetch contract security information from GoPlus.

    Missing fields are treated as UNKNOWN.
    """

    if not chain_id or not contract_address:
        return {
            "status": "Unavailable",
            "confidence": 0,
            "flags": [],
            "red_flags": [],
            "source": "GoPlus",
            "timestamp": utc_now_iso(),
            "available": False,
        }

    address = str(
        contract_address
    ).strip()

    if not re.fullmatch(
        r"0x[a-fA-F0-9]{40}",
        address,
    ):
        return {
            "status": "Unavailable",
            "confidence": 0,
            "flags": [
                "Invalid contract address format."
            ],
            "red_flags": [],
            "source": "GoPlus",
            "timestamp": utc_now_iso(),
            "available": False,
        }

    try:

        # FIX: replaced bare requests.get() + raise_for_status() with
        # the status-aware _http_get_market() helper so HTTP errors are
        # properly categorised (4xx vs 5xx vs timeout) and logged without
        # triggering the generic except-Exception handler for valid HTTP
        # error responses.
        url = (
            f"{GOPLUS_API_URL}/"
            f"{quote(str(chain_id))}"
        )

        response, status_code, error_reason = _http_get_market(
            url,
            params={
                "contract_addresses": address,
            },
            timeout=MARKET_TIMEOUT,
        )

        if response is None or (status_code is not None and status_code >= 400):
            logger.warning(
                "GoPlus security lookup failed for chain=%s addr=%s: %s",
                chain_id,
                address,
                error_reason or f"HTTP {status_code}",
            )
            return {
                "status": "Unavailable",
                "confidence": 0,
                "flags": [
                    "Contract security provider unavailable."
                ],
                "red_flags": [],
                "source": "GoPlus",
                "timestamp": utc_now_iso(),
                "available": False,
            }

        payload = response.json()

        result = (
            payload.get(
                "result",
                {},
            )
            if isinstance(
                payload,
                dict,
            )
            else {}
        )

        data = None

        if isinstance(
            result,
            dict,
        ):

            data = result.get(
                address
            )

            if data is None:
                data = result.get(
                    address.lower()
                )

            if data is None:

                for key, value in result.items():

                    if (
                        str(key).lower()
                        == address.lower()
                    ):
                        data = value
                        break

        if not isinstance(
            data,
            dict,
        ):
            return {
                "status": "Unavailable",
                "confidence": 0,
                "flags": [
                    "Contract security data unavailable."
                ],
                "red_flags": [],
                "source": "GoPlus",
                "timestamp": utc_now_iso(),
                "available": False,
            }

        flags = []
        red_flags = []

        honeypot = goplus_bool(
            data.get(
                "is_honeypot"
            )
        )

        if honeypot is True:
            flags.append(
                "Potential honeypot behavior detected."
            )

            red_flags.append(
                "Honeypot risk signal."
            )

        open_source = goplus_bool(
            data.get(
                "is_open_source"
            )
        )

        if open_source is False:
            flags.append(
                "Contract source is not verified."
            )

            red_flags.append(
                "Source verification unavailable."
            )

        ownership_recovery = goplus_bool(
            data.get(
                "can_take_back_ownership"
            )
        )

        if ownership_recovery is True:
            flags.append(
                "Ownership recovery capability detected."
            )

            red_flags.append(
                "Ownership-control risk."
            )

        owner_change = goplus_bool(
            data.get(
                "owner_change_balance"
            )
        )

        if owner_change is True:
            flags.append(
                "Owner balance-change capability detected."
            )

            red_flags.append(
                "Owner-controlled balance risk."
            )

        blacklist = goplus_bool(
            data.get(
                "is_blacklisted"
            )
        )

        if blacklist is True:
            flags.append(
                "Blacklist functionality detected."
            )

            red_flags.append(
                "Blacklist/control risk."
            )

        buy_tax = goplus_number(
            data.get(
                "buy_tax"
            )
        )

        sell_tax = goplus_number(
            data.get(
                "sell_tax"
            )
        )

        if (
            buy_tax is not None
            and buy_tax > 5
        ):
            flags.append(
                f"Elevated buy tax detected: "
                f"{format_number(buy_tax, 2)}%."
            )

            red_flags.append(
                "Elevated buy tax."
            )

        if (
            sell_tax is not None
            and sell_tax > 5
        ):
            flags.append(
                f"Elevated sell tax detected: "
                f"{format_number(sell_tax, 2)}%."
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
            item is not None
            for item in explicit_fields
        )

        confidence = clamp(
            40 + available_fields * 8,
            40,
            95,
        )

        if red_flags:
            status = (
                "Risk signals detected"
            )
        else:
            status = (
                "No major contract red flags detected"
            )

        security_report = {
            "status": status,
            "confidence": confidence,
            "flags": flags,
            "red_flags": red_flags,
            "source": "GoPlus",
            "timestamp": utc_now_iso(),
            "available": True,
            "raw_signals": {
                "honeypot": honeypot,
                "open_source": open_source,
                "ownership_recovery": (
                    ownership_recovery
                ),
                "owner_balance_change": (
                    owner_change
                ),
                "blacklist": blacklist,
                "buy_tax": buy_tax,
                "sell_tax": sell_tax,
            },
        }

        return json_safe(security_report)

    except Exception as exc:

        logger.warning(
            "GoPlus security lookup failed: %s",
            exc,
        )

        return {
            "status": "Unavailable",
            "confidence": 0,
            "flags": [
                "Contract security provider unavailable."
            ],
            "red_flags": [],
            "source": "GoPlus",
            "timestamp": utc_now_iso(),
            "available": False,
        }


