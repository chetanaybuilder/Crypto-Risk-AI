import { state } from '../state/store.js';
import { apiRequest, API } from './client.js';
import { updateLiveMarket, getMarketFromPayload } from '../components/market.js';
import { setLastFetchTime, canFetchMarketNow } from './client.js';

/* ============================================================
   LIVE MARKET POLLING
   ============================================================ */

// FIX (Bug 3): raised from 15s to 30s. With CoinGecko free-tier
// limits, a 15s interval alone could exhaust quota when a dashboard
// tab was left open, causing later /api/analyze calls to hit the
// provider cooldown and return available: false.
export const LIVE_MARKET_POLL_INTERVAL_MS = 30000;

export let marketBackoffUntil = 0;

export function getLastFetchTime(symbol) {
    try {
        return Number(localStorage.getItem(`marketFetchGate:${symbol}`)) || 0;
    } catch (error) {
        return 0;
    }
}

export function setLastFetchTime(symbol, timestamp) {
    try {
        localStorage.setItem(`marketFetchGate:${symbol}`, timestamp);
    } catch (error) {
        // ignore
    }
}

export function canFetchMarketNow(symbol) {
    const now = Date.now();

    if (now < marketBackoffUntil) {
        return false;
    }

    const sinceLastFetch = now - getLastFetchTime(symbol);
    if (sinceLastFetch < LIVE_MARKET_POLL_INTERVAL_MS) {
        return false;
    }

    return true;
}

export function stopLivePolling() {
    if (state.livePollTimer) {
        clearInterval(
            state.livePollTimer
        );

        state.livePollTimer = null;
    }

    state.liveRequestId++;

    state.isLiveRequestInFlight =
        false;
}

export function startLivePolling(symbol) {
    stopLivePolling();

    const normalizedSymbol =
        normalizeSymbol(symbol);

    if (!normalizedSymbol) {
        return;
    }

    state.currentSymbol =
        normalizedSymbol;

    /*
     * FIX (Bug 3): immediate refresh — but ONLY when the tab is
     * visible AND the last market fetch is older than the polling
     * interval. This avoids an unnecessary request right after the
     * tab becomes visible again when a fetch already happened within
     * the backend's MARKET_CACHE_TTL window.
     */
    if (!document.hidden && canFetchMarketNow(normalizedSymbol)) {
        refreshLiveMarket(
            normalizedSymbol
        );
    }

    /*
     * FIX (Bug 3): then every 30 seconds (was 15s). Never poll while
     * the tab is hidden — the visibilitychange handler stops the
     * timer entirely, and this guard also protects against a missed
     * visibility event.
     */
    state.livePollTimer =
        setInterval(() => {

            if (document.hidden) {
                return;
            }

            /*
             * Never poll while a previous
             * request is still running.
             */
            if (
                state.isLiveRequestInFlight
            ) {
                return;
            }

            if (!canFetchMarketNow(state.currentSymbol)) {
                return;
            }

            if (
                !state.currentSymbol
            ) {
                return;
            }

            refreshLiveMarket(
                state.currentSymbol
            );
        }, LIVE_MARKET_POLL_INTERVAL_MS);
}

export async function refreshLiveMarket(
    symbol
) {
    const normalizedSymbol =
        normalizeSymbol(symbol);

    if (!normalizedSymbol) {
        return;
    }

    /*
     * Prevent stale response from an
     * older symbol from updating the UI.
     */
    const requestId =
        ++state.liveRequestId;

    state.isLiveRequestInFlight =
        true;

    // FIX (Bug 3): record when the last market fetch happened so
    // startLivePolling() can skip the immediate refresh if the tab
    // becomes visible again within the cache window.
    setLastFetchTime(normalizedSymbol, Date.now());

    try {
        const payload =
            await apiRequest(
                API.market(
                    normalizedSymbol
                )
            );

        /*
         * If another market request
         * started after this one,
         * discard this response.
         */
        if (
            requestId !==
            state.liveRequestId
        ) {
            return;
        }

        const market =
            getMarketFromPayload(
                payload
            );

        if (!market) {
            console.warn(
                "Market endpoint returned no recognizable market object:",
                payload
            );

            setMarketLiveState(
                false,
                "Market data unavailable"
            );

            return;
        }

        updateLiveMarket(
            market
        );
    } catch (error) {
        /*
         * Ignore stale requests.
         */
        if (
            requestId !==
            state.liveRequestId
        ) {
            return;
        }

        console.warn(
            "Live market refresh failed:",
            error
        );

        /*
         * Keep the error visible enough
         * for debugging instead of hiding
         * everything behind a generic state.
         */
        if (error.status === 429) {
            marketBackoffUntil = Date.now() + LIVE_MARKET_POLL_INTERVAL_MS;
            setMarketLiveState(
                false,
                "Market feed rate-limited"
            );
        } else if (
            error.status >= 500
        ) {
            setMarketLiveState(
                false,
                "Backend market error"
            );
        } else if (
            error.code ===
            "NETWORK_ERROR"
        ) {
            setMarketLiveState(
                false,
                "Backend unreachable"
            );
        } else {
            setMarketLiveState(
                false,
                "Live feed unavailable"
            );
        }
    } finally {
        if (
            requestId ===
            state.liveRequestId
        ) {
            state.isLiveRequestInFlight =
                false;
        }
    }
}

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

    /*
     * Always update the fields.
     *
     * This prevents old values from
     * remaining on screen when the new
     * response explicitly lacks them.
     */
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
     * Only say LIVE after the backend
     * successfully returned usable market
     * data.
     */
    setMarketLiveState(
        true,
        "Live • Backend feed"
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




