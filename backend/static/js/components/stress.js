import { getAI, getStress } from './market.js';
import { isPlainObject } from '../utils/dom.js';
import { formatNumber, formatConfidence, applyRiskClass } from '../utils/formatters.js';
import { getStressTest } from './market.js';
import { firstDefined, setText } from '../utils/dom.js';
import { formatPercent } from '../utils/formatters.js';

/* ============================================================
   STRESS TEST
   ============================================================ */

export function getExpectedDrawdown(
    stress
) {
    const stressObj =
        isPlainObject(stress)
            ? stress
            : {};

    const expected =
        firstDefined(
            stressObj.expected_drawdown_pct,
            stressObj.drawdown_pct,
            stressObj.max_drawdown_pct,
            stressObj.expected_downside_pct
        );

    if (
        expected !== null
    ) {
        return expected;
    }

    const base =
        stressObj.base_scenario;

    if (
        isPlainObject(base)
    ) {
        const move =
            firstDefined(
                base.estimated_asset_move_pct,
                base.asset_move_pct,
                base.drawdown_pct
            );

        if (move !== null) {
            const numericMove =
                Number(move);

            if (
                Number.isFinite(
                    numericMove
                )
            ) {
                return numericMove;
            }
        }
    }

    return null;
}

export function getResilienceLabel(
    stress
) {
    const stressObj =
        isPlainObject(stress)
            ? stress
            : {};

    const label =
        firstDefined(
            stressObj.resilience_label,
            stressObj.resilience,
            stressObj.resilience_status
        );

    if (label !== null) {
        return label;
    }

    const base =
        stressObj.base_scenario;

    const rawScore =
        firstDefined(
            isPlainObject(base)
                ? base.resilience_score
                : null,

            stressObj.resilience_score
        );

    if (rawScore !== null) {
        const score =
            Number(rawScore);

        if (
            Number.isFinite(score)
        ) {
            if (score >= 65) {
                return "Resilient";
            }

            if (score >= 40) {
                return "Moderate";
            }

            return "Fragile";
        }
    }

    return null;
}

export function getStressConfidence(
    report,
    stress
) {
    const stressObj =
        isPlainObject(stress)
            ? stress
            : {};

    const reportObj =
        isPlainObject(report)
            ? report
            : {};

    return firstDefined(
        stressObj.confidence,
        reportObj.risk_confidence,
        reportObj.ai?.confidence,
        reportObj.risk_profile?.confidence
    );
}

export function renderStressTest(
    report
) {
    const stress =
        getStress(report);

    const beta =
        firstDefined(
            stress.beta,
            stress.beta_to_btc,
            report?.quantitative?.beta?.beta,
            report?.quantitative?.beta
        );

    setText(
        "#stress-beta",
        formatNumber(
            beta,
            3
        )
    );

    setText(
        "#stress-drawdown",
        formatPercent(
            getExpectedDrawdown(
                stress
            )
        )
    );

    const resilience =
        getResilienceLabel(
            stress
        );

    setText(
        "#stress-resilience",
        resilience
    );

    setText(
        "#stress-confidence",
        formatConfidence(
            getStressConfidence(
                report,
                stress
            )
        )
    );

    setText(
        "#stress-verdict",
        firstDefined(
            stress.verdict,
            stress.interpretation,
            stress.stress_interpretation,
            "Scenario analysis unavailable."
        )
    );

    applyRiskClass(
        $("#stress-resilience"),
        firstDefined(
            stress.resilience_label,
            resilience
        )
    );

    setText(
        "#ai-stress-interpretation",
        getAI(report)
            .stress_interpretation
    );
}




