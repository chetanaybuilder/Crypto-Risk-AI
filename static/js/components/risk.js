import { getPillars, getPillar } from './market.js';
import { renderPillar, buildPillarDetail } from './pillars.js';
import { formatConfidence, clampScore, applyRiskClass } from '../utils/formatters.js';
import { getRiskProfile } from './market.js';
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
        
        if (bar.parentElement) {
            bar.parentElement.style.display = "none";
        }

        return;
    }
    
    if (bar.parentElement) {
        bar.parentElement.style.display = "";
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

    // Set numeric score value
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

    // Map structural/security pillar data to contract card elements
    let contractPillar = Object.assign({}, firstDefined(
        getPillar(report, "structural"),
        getPillar(report, "contract")
    ) || {});

    // Phase 4: Frontend Component Rendering - Verify State Mapping
    if (report && report.security) {
        if (report.security.available === true) {
            contractPillar.score = report.security.score; // (score / 100) logic is handled by formatScore in pillars.js
            contractPillar.label = "Audited";
        } else if (["BTC", "ETH", "SOL", "AVAX", "BNB", "DOT", "NEAR"].includes((report.token_symbol || "").toUpperCase())) {
            contractPillar.score = null;
            contractPillar.label = "Native Asset";
            contractPillar.detail = "Not applicable — native assets have no smart contract to analyze.";
        } else if (report.security.status === "Unavailable" || report.security.available === false) {
            contractPillar.score = null;
            contractPillar.label = "Unavailable";
            contractPillar.detail = "Contract/security signal unavailable — no contract security data.";
        }
    }

    renderPillar(
        "contract",
        contractPillar
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




