import { state } from '../state/store.js';
import { apiRequest, API } from './client.js';
import { updateLiveMarket, getMarketFromPayload, setMarketLiveState } from '../components/market.js';
import { normalizeSymbol } from '../utils/dom.js';

/* ============================================================
   LIVE MARKET POLLING
   ============================================================ */

// Live market polling interval (30 seconds to respect rate limits)
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

    // Refresh immediately only when visible and outside cooldown window
    if (!document.hidden && canFetchMarketNow(normalizedSymbol)) {
        refreshLiveMarket(
            normalizedSymbol
        );
    }

    // Poll on interval while document is visible
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

    // Record fetch timestamp for gate management
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