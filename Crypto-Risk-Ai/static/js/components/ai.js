import { renderForensicCards } from './dataQuality.js';
import { getSecurity, getDataQuality } from './market.js';
import { applyRiskClass } from '../utils/formatters.js';
import { getAI } from './market.js';
import { firstDefined, setText } from '../utils/dom.js';
import { marked } from 'https://cdn.jsdelivr.net/npm/marked/lib/marked.esm.js';

/* ============================================================
   AI REPORT
   ============================================================ */

export function renderAI(report) {
    const ai =
        getAI(report);

    const security =
        getSecurity(report);

    const quality =
        getDataQuality(report);

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

    const securityFlags =
        Array.isArray(
            security.red_flags
        )
            ? security.red_flags
            : [];

    let securityText =
        firstDefined(
            security.status,
            security.label,
            "Unavailable"
        );

    if (
        securityFlags.length
    ) {
        securityText =
            securityFlags
                .map(
                    (flag) =>
                        String(flag)
                )
                .join(" • ");
    }

    setText(
        "#ai-contract-risk",
        securityText
    );

    applyRiskClass(
        $("#ai-contract-risk"),
        security.status
    );

    const missingSignals =
        Array.isArray(
            quality.missing_signals
        )
            ? quality.missing_signals
            : [];

    const hasExecutiveSummary =
        Boolean(
            ai.executive_summary
        );

    let evidenceStatus;

    if (!hasExecutiveSummary) {
        evidenceStatus =
            "Unavailable";
    } else if (
        missingSignals.length === 0
    ) {
        evidenceStatus =
            "Complete backend report";
    } else {
        evidenceStatus =
            "Some signals unavailable";
    }

    setText(
        "#ai-evidence-status",
        evidenceStatus
    );

    setText(
        "#ai-risk-regime",
        ai.risk_regime
    );

    setText(
        "#ai-primary-risk-driver",
        ai.primary_risk_driver
    );

    setText(
        "#ai-what-changed",
        ai.what_changed
    );

    setText(
        "#ai-what-matters-now",
        ai.what_matters_now
    );

    setText(
        "#ai-watch-next",
        ai.watch_next
    );

    setText(
        "#ai-stress-interpretation",
        ai.stress_interpretation
    );

    renderForensicCards(
        report
    );
}




