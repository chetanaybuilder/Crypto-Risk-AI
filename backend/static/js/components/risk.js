import { getPillars, getPillar } from './market.js';
import { renderPillar, buildPillarDetail } from './pillars.js';
import { formatConfidence, clampScore, applyRiskClass } from '../utils/formatters.js';
import { getRiskProfile, getRiskScore, getRiskSeverity } from './market.js';
import { formatScore, normalizeSeverity } from '../utils/formatters.js';
import { firstDefined, setText } from '../utils/dom.js';

/* ============================================================
   RISK SCORE BAR
   ============================================================ */

export function updateScoreBar(
    bar,
    score
) {
    if (!bar) return;

    const numericScore =
        clampScore(score);

    if (
        numericScore === null
    ) {
        bar.style.width =
            "0%";

        bar.removeAttribute(
            "aria-valuenow"
        );

        return;
    }

    bar.style.width =
        `${numericScore}%`;

    bar.setAttribute(
        "aria-valuenow",
        String(
            Math.round(
                numericScore
            )
        )
    );
}




/* ============================================================
   MAIN RISK PROFILE
   ============================================================ */

export function renderRiskProfile(
    report
) {
    const risk =
        getRiskProfile(report);

    const compositeScore =
        firstDefined(
            risk.composite_score,
            risk.score,
            report.risk_score
        );

    const rawLabel =
        firstDefined(
            risk.label,
            risk.severity,
            report.risk_label,
            report.risk_severity
        );

    const label =
        normalizeSeverity(
            rawLabel
        );

    const confidence =
        firstDefined(
            risk.confidence,
            report.risk_confidence
        );

    // FIX (B1): the HTML template already renders a static "/ 100"
    // label next to #report-risk-score, so appending "/100" here
    // produced "39/100 /100". Set ONLY the number and let the static
    // label render once.
    setText(
        "#report-risk-score",
        compositeScore !== null
            ? formatScore(
                compositeScore
            )
            : "—"
    );

    const partialBadge = document.getElementById("report-risk-partial");
    if (partialBadge) {
        partialBadge.style.display = risk.partial_data ? "inline-block" : "none";
    }

    setText(
        "#report-risk-label",
        label
    );

    setText(
        "#report-outlook",
        firstDefined(
            report.outlook,
            report.trend,
            report.risk_label,
            risk.label
        )
    );

    setText(
        "#report-risk-confidence",
        formatConfidence(
            confidence
        )
    );

    applyRiskClass(
        $("#report-risk-score"),
        rawLabel
    );

    applyRiskClass(
        $("#report-risk-label"),
        rawLabel
    );

    applyRiskClass(
        $("#report-outlook"),
        firstDefined(
            report.outlook,
            rawLabel
        )
    );

    /*
     * Always render all pillars.
     *
     * Missing pillars are explicitly
     * cleared instead of leaving old
     * values on screen.
     */
    renderPillar(
        "volatility",
        getPillar(
            report,
            "volatility"
        )
    );

    renderPillar(
        "liquidity",
        getPillar(
            report,
            "liquidity"
        )
    );

    const marketSensitivity =
        firstDefined(
            getPillars(report)
                .market_sensitivity,
            getPillars(report)
                .marketSensitivity,
            getPillars(report)
            ["market-sensitivity"]
        );

    renderPillar(
        "market-sensitivity",
        marketSensitivity || {}
    );

    /*
     * FIX (B3): the "Contract" card the user actually sees uses the
     * #pillar-contract-value / #pillar-contract-bar /
     * #pillar-contract-detail DOM elements, while the backend
     * returns the security/structural pillar under the key
     * "structural" in risk_profile.pillars. Previously the data was
     * written to #pillar-structural-* elements (which don't exist in
     * the served template), so the visible Contract card never
     * updated and always showed its placeholder. The structural
     * pillar is now rendered directly into the contract elements,
     * and the dead "contract"-key lookup block was removed.
     *
     * Native assets (BTC/ETH/…) return a not-applicable security
     * object, which buildPillarDetail() renders as
     * "Not applicable — native assets have no smart contract to
     * analyze" instead of a bare "—".
     */
    renderPillar(
        "contract",
        firstDefined(
            getPillar(
                report,
                "structural"
            ),
            getPillar(
                report,
                "contract"
            )
        )
    );

    renderPillar(
        "composite",
        {
            score:
                compositeScore,
            label:
                rawLabel,
            confidence:
                confidence,
            detail:
                "Combined evidence-based risk score."
        }
    );
}




