import { getMarket } from './market.js';
import { normalizeSource } from '../utils/dom.js';
import { formatConfidence, formatRelativeTime } from '../utils/formatters.js';
import { getAI, getDataQuality, getSecurity, getRiskProfile } from './market.js';
import { firstDefined, setText } from '../utils/dom.js';
import { formatScore } from '../utils/formatters.js';

/* ============================================================
   FORENSIC / INTELLIGENCE CARDS
   ============================================================ */

export function renderForensicCards(
    report
) {
    const container =
        $("#forensic-cards");

    if (!container) return;

    container.replaceChildren();

    const ai =
        getAI(report);

    const cards = [
        {
            title:
                "Primary risk driver",

            value:
                firstDefined(
                    ai.primary_risk_driver,
                    "Not identified."
                )
        },

        {
            title:
                "What changed",

            value:
                firstDefined(
                    ai.what_changed,
                    "No material change reported."
                )
        },

        {
            title:
                "What matters now",

            value:
                firstDefined(
                    ai.what_matters_now,
                    "No immediate interpretation available."
                )
        },

        {
            title:
                "Watch next",

            value:
                firstDefined(
                    ai.watch_next,
                    "No monitoring signal returned."
                )
        },

        {
            title:
                "Stress interpretation",

            value:
                firstDefined(
                    ai.stress_interpretation,
                    "No stress interpretation returned."
                )
        }
    ];

    cards.forEach(
        (item) => {
            const card =
                document.createElement(
                    "article"
                );

            card.className =
                "forensic-card";

            const heading =
                document.createElement(
                    "h4"
                );

            const text =
                document.createElement(
                    "p"
                );

            heading.textContent =
                item.title;

            text.textContent =
                String(item.value);

            card.appendChild(
                heading
            );

            card.appendChild(
                text
            );

            container.appendChild(
                card
            );
        }
    );
}




/* ============================================================
   DATA QUALITY
   ============================================================ */

export function renderDataQuality(
    report
) {
    const quality =
        getDataQuality(report);

    const reportObj =
        report || {};

    const confidence =
        firstDefined(
            quality.confidence,
            reportObj.risk_confidence,
            reportObj.ai?.confidence,
            reportObj.risk_profile?.confidence
        );

    setText(
        "#data-confidence",
        formatConfidence(
            confidence
        )
    );

    const reportMarket =
        getMarket(reportObj);

    let source =
        normalizeSource(
            firstDefined(
                reportMarket.source,
                reportMarket.provider,
                quality.source
            )
        );

    if (quality.is_fallback_provider || reportMarket?.is_fallback_provider) {
        source += " (Fallback)";
    }

    setText(
        "#market-source",
        source
    );

    /*
     * Support all common timestamp names.
     */
    const timestamp =
        firstDefined(
            reportObj.created_at,
            reportObj.generated_at,

            reportMarket.timestamp,
            reportMarket.updated_at,
            reportMarket.fetched_at,
            reportMarket.last_updated,

            quality.timestamp,
            quality.updated_at,
            quality.fetched_at,

            reportObj.updated_at
        );

    setText(
        "#data-freshness",
        timestamp
            ? formatRelativeTime(
                timestamp
            )
            : "Unknown"
    );

    const missing =
        firstDefined(
            quality.missing_signals,
            quality.missing,
            []
        );

    renderMissingSignals(
        missing
    );
}




/* ============================================================
   MISSING SIGNALS
   ============================================================ */

export function renderMissingSignals(
    missing
) {
    const container =
        $("#missing-signals");

    if (!container) return;

    container.replaceChildren();

    let signals = [];

    if (
        Array.isArray(missing)
    ) {
        signals =
            missing.filter(
                (signal) =>
                    signal !== null &&
                    signal !== undefined &&
                    String(signal)
                        .trim() !== "" &&
                    String(signal) !== "Contract security data"
            );
    } else if (
        typeof missing ===
        "string"
    ) {
        if (
            missing.trim() &&
            missing !== "Contract security data"
        ) {
            signals = [
                missing
            ];
        }
    }

    if (!signals.length) {
        const item =
            document.createElement(
                "span"
            );

        item.className =
            "data-ok";

        item.textContent =
            "All primary risk vectors verified.";

        container.appendChild(
            item
        );

        return;
    }

    signals.forEach(
        (signal) => {
            const item =
                document.createElement(
                    "span"
                );

            item.className =
                "missing-signal";

            item.textContent =
                String(signal);

            container.appendChild(
                item
            );
        }
    );
}




