import { refreshLiveMarket } from '../api/market.js';
import { toggle, normalizeSymbol } from '../utils/dom.js';
import { state } from '../state/store.js';
import { firstDefined, isPlainObject, setText, setHTML, $, normalizeSource } from '../utils/dom.js';
import { formatUsd, formatPercent, formatDate, formatRelativeTime } from '../utils/formatters.js';
import { renderRiskProfile } from './risk.js';
import { renderRiskDrivers } from './pillars.js';
import { renderStressTest } from './stress.js';
import { renderAI } from './ai.js';
import { renderDataQuality } from './dataQuality.js';
import { updateCurrentReportDeleteButton, clearReportView } from './ui.js';
import { stopLivePolling, startLivePolling } from '../api/market.js';

/* ============================================================
   REPORT EXTRACTION
   ============================================================ */

export function isRiskReport(value) {
    if (
        !isPlainObject(value)
    ) {
        return false;
    }

    /*
     * Strong report markers.
     */
    if (
        value.schema_version ||
        value.risk_profile ||
        value.risk_drivers ||
        value.stress_test ||
        value.data_quality ||
        value.ai
    ) {
        return true;
    }

    /*
     * Standard score-based report.
     */
    if (
        value.risk_score !==
        undefined &&
        (
            value.asset ||
            value.token_symbol ||
            value.symbol
        )
    ) {
        return true;
    }

    /*
     * Some backend versions may put
     * the score inside risk_profile.
     */
    if (
        value.risk_profile &&
        (
            value.risk_profile
                .composite_score !==
            undefined ||
            value.risk_profile.score !==
            undefined
        )
    ) {
        return true;
    }

    return false;
}

export function getReportFromPayload(
    payload
) {
    if (!payload) {
        return null;
    }

    if (isRiskReport(payload)) {
        return payload;
    }

    /*
     * Search only known report-wrapper
     * locations. Do not blindly accept
     * arbitrary nested objects.
     */
    const candidates = [
        payload.report,
        payload.analysis,

        payload.latest?.report,
        payload.latest?.analysis,
        payload.latest,

        // Job status payload shape: { job: {...}, latest: {...} }
        payload.job?.report,

        payload.data?.report,
        payload.data?.analysis,
        payload.data?.latest?.report,
        payload.data?.latest?.analysis,
        payload.data?.latest,
        payload.data,

        payload.result?.report,
        payload.result?.analysis,
        payload.result,

        payload.response?.report,
        payload.response?.analysis,
        payload.response
    ];

    for (
        const candidate of candidates
    ) {
        if (
            isRiskReport(candidate)
        ) {
            return candidate;
        }
    }

    return null;
}




/* ============================================================
   MARKET RESPONSE EXTRACTION
   ============================================================ */

export function getMarketFromPayload(
    payload
) {
    if (!payload) {
        return null;
    }

    /*
     * Direct market object:
     * { price, source, ... }
     */
    if (
        isPlainObject(payload) &&
        (
            payload.price !==
            undefined ||
            payload.current_price_usd !==
            undefined ||
            payload.current_price !==
            undefined
        )
    ) {
        return payload;
    }

    const candidates = [
        payload.market,

        payload.data?.market,
        payload.data,

        payload.result?.market,
        payload.result,

        payload.response?.market,
        payload.response,

        payload.report?.market,
        payload.analysis?.market,

        payload.latest?.market,
        payload.latest?.report?.market,
        payload.latest?.analysis?.market,

        payload.data?.report?.market,
        payload.data?.analysis?.market
    ];

    for (
        const candidate of candidates
    ) {
        if (
            isPlainObject(candidate) &&
            (
                candidate.price !==
                undefined ||
                candidate.current_price_usd !==
                undefined ||
                candidate.current_price !==
                undefined ||
                candidate.price_usd !==
                undefined
            )
        ) {
            return candidate;
        }
    }

    return null;
}




/* ============================================================
   REPORT ACCESSORS
   ============================================================ */

export function getRiskProfile(report) {
    return isPlainObject(
        report?.risk_profile
    )
        ? report.risk_profile
        : {};
}

export function getPillars(report) {
    const pillars =
        getRiskProfile(report)
            .pillars;

    return isPlainObject(pillars)
        ? pillars
        : {};
}

export function getPillar(
    report,
    name
) {
    const pillars =
        getPillars(report);

    const pillar =
        pillars[name];

    return isPlainObject(pillar)
        ? pillar
        : {};
}

export function getAI(report) {
    return isPlainObject(report?.ai)
        ? report.ai
        : {};
}

export function getMarket(report) {
    return getMarketFromPayload(report) || {};
}

export function getSecurity(report) {
    return isPlainObject(
        report?.security
    )
        ? report.security
        : {};
}

export function getStress(report) {
    return isPlainObject(
        report?.stress_test
    )
        ? report.stress_test
        : (
            isPlainObject(
                report?.stress
            )
                ? report.stress
                : {}
        );
}

export function getDataQuality(report) {
    return isPlainObject(
        report?.data_quality
    )
        ? report.data_quality
        : {};
}




/* ============================================================
   MARKET RENDERING
   ============================================================ */

export function renderMarket(report) {
    const market =
        getMarket(report);

    const asset =
        isPlainObject(
            report?.asset
        )
            ? report.asset
            : {};

    const price =
        firstDefined(
            market.price,
            market.current_price_usd,
            market.price_usd,
            market.current_price
        );

    const change24 =
        firstDefined(
            market.price_change_24h_pct,
            market.change_24h_pct,
            market.price_change_24h,
            market.change_24h
        );

    const change7d =
        firstDefined(
            market.price_change_7d_pct,
            market.change_7d_pct,
            market.price_change_7d,
            market.change_7d
        );

    const high24 =
        firstDefined(
            market.high_24h,
            market.high_24h_usd,
            market.highPrice,
            market.high
        );

    const low24 =
        firstDefined(
            market.low_24h,
            market.low_24h_usd,
            market.lowPrice,
            market.low
        );

    const volume =
        firstDefined(
            market.volume_24h,
            market.volume_24h_usd,
            market.quoteVolume,
            market.volume
        );

    const marketCap =
        firstDefined(
            market.market_cap,
            market.market_cap_usd
        );

    let source =
        normalizeSource(
            firstDefined(
                market.source,
                market.provider,
                market.data_source
            )
        );

    if (report?.data_quality?.is_fallback_provider || market?.is_fallback_provider) {
        source += " (Fallback)";
    }

    const timestamp =
        firstDefined(
            report?.created_at,
            report?.generated_at,
            market.timestamp,
            market.updated_at,
            market.fetched_at,
            market.last_updated
        );

    setText(
        "#report-token",
        firstDefined(
            asset.symbol,
            report?.token_symbol,
            report?.symbol
        )
    );

    setText(
        "#report-price",
        formatUsd(price)
    );

    setText(
        "#report-change",
        formatPercent(change24)
    );

    setText(
        "#report-volume",
        formatUsd(volume)
    );

    setText(
        "#report-market-cap",
        formatUsd(marketCap)
    );

    setText(
        "#report-change-7d",
        formatPercent(change7d)
    );

    setText(
        "#report-high",
        formatUsd(high24)
    );

    setText(
        "#report-low",
        formatUsd(low24)
    );

    /*
     * IMPORTANT:
     * Report market data is NOT proof that
     * the live endpoint just succeeded.
     *
     * Therefore we do not mark this "Live"
     * here. refreshLiveMarket() owns live
     * status.
     */
    setText(
        "#market-live-status",
        "Report market snapshot"
    );

    setText(
        "#market-updated",
        timestamp
            ? formatRelativeTime(
                timestamp
            )
            : "Report timestamp unavailable"
    );

    setText(
        "#data-source",
        source
    );

    setText(
        "#market-source",
        source
    );

    const changeElement =
        $("#report-change");

    if (changeElement) {
        changeElement.classList.remove(
            "positive",
            "negative"
        );

        const numericChange =
            Number(change24);

        if (
            Number.isFinite(
                numericChange
            )
        ) {
            changeElement.classList.add(
                numericChange >= 0
                    ? "positive"
                    : "negative"
            );
        }
    }
}




/* ============================================================
   COMPLETE REPORT RENDERER
   ============================================================ */

export function renderReport(
    report
) {
    if (
        !isRiskReport(report)
    ) {
        clearReportView();
        return;
    }

    document.body.classList.add('report-active');
    console.log(
        "Rendering CryptoRisk report:",
        report
    );

    state.latestReport =
        report;

    state.currentSymbol =
        normalizeSymbol(
            firstDefined(
                report?.asset?.symbol,
                report?.token_symbol,
                report?.symbol,
                state.currentSymbol
            )
        );

    renderMarket(
        report
    );

    renderRiskProfile(
        report
    );

    renderRiskDrivers(
        report
    );

    renderStressTest(
        report
    );

    renderAI(
        report
    );

    renderDataQuality(
        report
    );

    updateCurrentReportDeleteButton();

    const generated =
        firstDefined(
            report.generated_at,
            report.created_at,
            report.updated_at
        );

    if (generated) {
        const element =
            document.querySelector(
                "[data-report-generated]"
            );

        if (element) {
            element.textContent =
                formatDate(
                    generated
                );
        }
    }
}


/* ============================================================
   LIVE MARKET UPDATE
   ============================================================ */

export function setMarketLiveState(
    isLive,
    message
) {
    setText(
        "#market-live-status",
        message || (
            isLive
                ? "Live • Backend feed"
                : "Live feed unavailable"
        )
    );

    const liveDot =
        $("#market-live-dot");

    if (liveDot) {
        liveDot.classList.toggle(
            "active",
            Boolean(isLive)
        );
    }
}

export function updateLiveMarket(
    market
) {
    if (
        !isPlainObject(market)
    ) {
        setMarketLiveState(
            false,
            "Market data unavailable"
        );

        return;
    }

    if (market.available === false) {
        setMarketLiveState(
            false,
            market.unavailable_reason || "Live feed unavailable"
        );
    } else {
        setMarketLiveState(
            true,
            "Live • Backend feed"
        );
    }

    const price =
        firstDefined(
            market.price,
            market.current_price_usd,
            market.price_usd,
            market.current_price
        );

    const change24 =
        firstDefined(
            market.price_change_24h_pct,
            market.change_24h_pct,
            market.price_change_24h,
            market.change_24h
        );

    const change7d =
        firstDefined(
            market.price_change_7d_pct,
            market.change_7d_pct,
            market.price_change_7d,
            market.change_7d
        );

    const high24 =
        firstDefined(
            market.high_24h,
            market.high_24h_usd,
            market.highPrice,
            market.high
        );

    const low24 =
        firstDefined(
            market.low_24h,
            market.low_24h_usd,
            market.lowPrice,
            market.low
        );

    const volume =
        firstDefined(
            market.volume_24h,
            market.volume_24h_usd,
            market.total_volume_usd,
            market.quoteVolume,
            market.volume
        );

    const marketCap =
        firstDefined(
            market.market_cap,
            market.market_cap_usd
        );

    let source =
        normalizeSource(
            firstDefined(
                market.source,
                market.provider,
                market.data_source
            )
        );

    if (market.is_fallback_provider) {
        source += " (Fallback)";
    }

    const timestamp =
        firstDefined(
            market.timestamp,
            market.updated_at,
            market.fetched_at,
            market.last_updated
        );

    setText(
        "#report-price",
        formatUsd(price)
    );

    setText(
        "#report-change",
        formatPercent(change24)
    );

    setText(
        "#report-volume",
        formatUsd(volume)
    );

    setText(
        "#report-market-cap",
        formatUsd(marketCap)
    );

    setText(
        "#report-change-7d",
        formatPercent(change7d)
    );

    setText(
        "#report-high",
        formatUsd(high24)
    );

    setText(
        "#report-low",
        formatUsd(low24)
    );

    setText(
        "#market-updated",
        timestamp
            ? formatRelativeTime(
                timestamp
            )
            : "Updated now"
    );

    setText(
        "#data-source",
        source
    );

    setText(
        "#market-source",
        source
    );

    const changeElement =
        $("#report-change");

    if (changeElement) {
        changeElement.classList.remove(
            "positive",
            "negative"
        );

        const numericChange =
            Number(change24);

        if (
            Number.isFinite(
                numericChange
            )
        ) {
            changeElement.classList.add(
                numericChange >= 0
                    ? "positive"
                    : "negative"
            );
        }
    }
}
