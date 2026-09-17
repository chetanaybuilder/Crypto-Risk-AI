/**
 * AI Qualitative Intelligence View Component.
 * Projects executive summaries, market structure commentary, key risk drivers, and scenario analysis.
 */

import { $, firstDefined, setText } from '../utils/dom.js';
import { applyRiskClass } from '../utils/formatters.js';
import { renderForensicCards } from './dataQuality.js';
import { getAI, getDataQuality, getSecurity } from './market.js';

export function renderAI(report) {
    const ai = getAI(report);
    const security = getSecurity(report);
    const quality = getDataQuality(report);

    setText(
        "#executive-summary",
        firstDefined(
            ai.executive_summary,
            ai.summary,
            "No executive summary was returned."
        )
    );

    setText(
        "#ai-market-structure",
        firstDefined(
            ai.what_matters_now,
            ai.primary_risk_driver,
            ai.risk_regime,
            "No market interpretation available."
        )
    );

    setText(
        "#ai-liquidity",
        firstDefined(
            ai.watch_next,
            "No monitoring guidance returned."
        )
    );

    const securityFlags = Array.isArray(security.red_flags)
        ? security.red_flags
        : [];

    let securityText = firstDefined(
        security.status,
        security.label,
        "Unavailable"
    );

    if (securityFlags.length > 0) {
        securityText = securityFlags.map((flag) => String(flag)).join(" • ");
    }

    setText("#ai-contract-risk", securityText);

    const contractElement = $("#ai-contract-risk");
    if (contractElement) {
        applyRiskClass(contractElement, security.status);
    }

    const missingSignals = Array.isArray(quality.missing_signals)
        ? quality.missing_signals
        : [];

    const hasExecutiveSummary = Boolean(ai.executive_summary);

    let evidenceStatus;
    if (!hasExecutiveSummary) {
        evidenceStatus = "Unavailable";
    } else if (missingSignals.length === 0) {
        evidenceStatus = "Complete backend report";
    } else {
        evidenceStatus = "Some signals unavailable";
    }

    setText("#ai-evidence-status", evidenceStatus);
    setText("#ai-risk-regime", ai.risk_regime);
    setText("#ai-primary-risk-driver", ai.primary_risk_driver);
    setText("#ai-what-changed", ai.what_changed);
    setText("#ai-what-matters-now", ai.what_matters_now);
    setText("#ai-watch-next", ai.watch_next);
    setText("#ai-stress-interpretation", ai.stress_interpretation);

    renderForensicCards(report);
}
