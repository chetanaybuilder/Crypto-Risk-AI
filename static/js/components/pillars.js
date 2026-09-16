import { updateScoreBar } from './risk.js';
import { state } from '../state/store.js';
import { isPlainObject } from '../utils/dom.js';
import { formatScore, applyRiskClass } from '../utils/formatters.js';
import { getRiskProfile } from './market.js';
import { normalizeSeverity } from '../utils/formatters.js';
import { firstDefined } from '../utils/dom.js';

/* ============================================================
   RISK PILLARS
   ============================================================ */

export function renderPillar(
    name,
    pillar
) {
    const safePillar =
        isPlainObject(pillar)
            ? pillar
            : {};

    const score =
        firstDefined(
            safePillar.score,
            safePillar.risk_score,
            safePillar.value
        );

    const label =
        firstDefined(
            safePillar.label,
            safePillar.severity
        );

    const valueElement =
        $(`#pillar-${name}-value`);

    const barElement =
        $(`#pillar-${name}-bar`);

    const detailElement =
        $(`#pillar-${name}-detail`);

    /*
     * CRITICAL FIX:
     * Clear every pillar first.
     *
     * Without this, if report #1 has
     * liquidity and report #2 doesn't,
     * report #1's liquidity score remains
     * visible.
     */
    if (
        score === null ||
        score === undefined ||
        score === ""
    ) {
        if (valueElement) {
            if (safePillar.label === "Native Asset") {
                valueElement.textContent = "N/A - Native Asset";
            } else if (safePillar.label === "Unavailable") {
                valueElement.textContent = "Unavailable";
            } else {
                valueElement.textContent = "N/A";
            }

            applyRiskClass(
                valueElement,
                null
            );
        }

        if (barElement) {
            updateScoreBar(
                barElement,
                null
            );

            applyRiskClass(
                barElement,
                null
            );
        }

        if (detailElement) {
            detailElement.textContent =
                buildPillarDetail(
                    name,
                    safePillar
                );
        }

        return;
    }

    if (valueElement) {
        valueElement.textContent =
            `${formatScore(
                score
            )}/100`;

        applyRiskClass(
            valueElement,
            label
        );
    }

    if (barElement) {
        updateScoreBar(
            barElement,
            score
        );

        applyRiskClass(
            barElement,
            label
        );
    }

    if (detailElement) {
        detailElement.textContent =
            buildPillarDetail(
                name,
                safePillar
            );
    }
}




/* ============================================================
   PILLAR DETAIL
   ============================================================ */

export function buildPillarDetail(
    name,
    pillar
) {
    if (
        !isPlainObject(pillar)
    ) {
        return (
            generatePillarFallbackDetail(
                name,
                null
            ) ||
            "Signal unavailable."
        );
    }

    const detail =
        firstDefined(
            pillar.detail,
            pillar.description,
            pillar.reason,
            pillar.interpretation
        );

    /*
     * FIX (B3): native assets (BTC/ETH/…) have no smart contract, so
     * the security/structural pillar is "not applicable". That must
     * never render as a bare "—" (which reads as "broken/unknown").
     * A not-applicable signal is shown as an explanation instead.
     */
    if (pillar.not_applicable === true) {
        return (
            "Not applicable — native assets (e.g. BTC/ETH) have " +
            "no smart contract to analyze."
        );
    }

    if (
        detail !== null &&
        /not[\s-]?applicable/i.test(
            String(detail)
        )
    ) {
        return (
            `${String(detail)
                .replace(/\.$/, "")
                .trim()} — native assets (e.g. BTC/ETH) have no ` +
            "smart contract to analyze."
        );
    }

    if (detail !== null) {
        return String(detail);
    }

    const score =
        firstDefined(
            pillar.score,
            pillar.risk_score,
            pillar.value
        );

    if (
        score === null ||
        score === undefined
    ) {
        return firstDefined(
            pillar.label,
            pillar.severity,
            generatePillarFallbackDetail(
                name,
                null
            ),
            "Signal unavailable."
        );
    }

    return generatePillarFallbackDetail(
        name,
        score
    );
}

export function generatePillarFallbackDetail(
    name,
    score
) {
    const descriptions = {
        volatility:
            "Volatility risk contribution.",

        liquidity:
            "Liquidity and exit-risk contribution.",

        "market-sensitivity":
            "Market sensitivity contribution.",

        market_sensitivity:
            "Market sensitivity contribution.",

        structural:
            "Structural risk contribution.",

        contract:
            "Contract/security risk contribution.",

        composite:
            "Combined evidence-based risk score."
    };

    const missingDescriptions = {
        liquidity:
            "Liquidity signal unavailable — no volume or market-cap data to estimate exit risk.",

        "market-sensitivity":
            "Market sensitivity signal unavailable — no BTC beta could be calculated.",

        market_sensitivity:
            "Market sensitivity signal unavailable — no BTC beta could be calculated.",

        volatility:
            "Volatility signal unavailable — insufficient price history.",

        structural:
            "Structural/contract security signal unavailable — no contract security data.",

        contract:
            "Contract/security signal unavailable — no contract security data."
    };

    if (
        score === null ||
        score === undefined
    ) {
        return (
            missingDescriptions[name] ||
            descriptions[name] ||
            "Signal unavailable."
        );
    }

    return (
        descriptions[name] ||
        "Risk contribution."
    );
}




/* ============================================================
   RISK DRIVERS
   ============================================================ */

export function renderRiskDrivers(
    report
) {
    const container =
        $("#risk-drivers");

    if (!container) return;

    container.replaceChildren();

    const drivers =
        Array.isArray(
            report?.risk_drivers
        )
            ? report.risk_drivers
            : [];

    if (!drivers.length) {
        const empty =
            document.createElement(
                "div"
            );

        empty.className =
            "empty-state";

        empty.textContent =
            "No material risk drivers were returned.";

        container.appendChild(
            empty
        );

        return;
    }

    drivers.forEach(
        (driver, index) => {
            const safeDriver =
                isPlainObject(
                    driver
                )
                    ? driver
                    : {};

            const card =
                document.createElement(
                    "article"
                );

            card.className =
                "risk-driver-card";

            const heading =
                document.createElement(
                    "h4"
                );

            const badge =
                document.createElement(
                    "span"
                );

            const body =
                document.createElement(
                    "p"
                );

            heading.textContent =
                firstDefined(
                    safeDriver.title,
                    safeDriver.name,
                    `Risk driver ${index + 1
                    }`
                );

            badge.textContent =
                normalizeSeverity(
                    firstDefined(
                        safeDriver.severity,
                        safeDriver.label
                    )
                );

            badge.className =
                "risk-badge";

            applyRiskClass(
                badge,
                firstDefined(
                    safeDriver.severity,
                    safeDriver.label
                )
            );

            body.textContent =
                firstDefined(
                    safeDriver.detail,
                    safeDriver.description,
                    "No additional detail was provided."
                );

            card.appendChild(
                heading
            );

            card.appendChild(
                badge
            );

            card.appendChild(
                body
            );

            container.appendChild(
                card
            );
        }
    );
}




