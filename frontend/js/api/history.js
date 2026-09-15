import { state } from '../state/store.js';
import { apiRequest, API } from './client.js';
import { renderHistory } from '../components/history.js';
import { renderReport } from '../components/market.js';
import { clearReportView, finishProgress } from '../components/ui.js';
import { startLivePolling } from './market.js';
import { show, hide, setText } from '../utils/dom.js';

/* ============================================================
   HISTORY FETCH
   ============================================================ */

export async function refreshHistory() {
    try {
        const payload =
            await apiRequest(
                API.dashboard
            );

        if (payload.user) {
            renderUser(
                payload.user
            );
        }

        const history =
            Array.isArray(
                payload.history
            )
                ? payload.history
                : Array.isArray(
                    payload.data?.history
                )
                    ? payload.data.history
                    : [];

        renderHistory(
            history
        );
    } catch (error) {
        console.error(
            "History refresh failed:",
            error
        );
    }
}




/* ============================================================
   SINGLE HISTORY REPORT
   ============================================================ */

export async function loadHistoryReport(
    id
) {
    if (!id) return;

    clearAnalysisError();
    stopLivePolling();

    try {
        const payload =
            await apiRequest(
                API.history(id)
            );

        console.log(
            "History report payload:",
            payload
        );

        const report =
            getReportFromPayload(
                payload
            );

        if (!report) {
            throw new Error(
                "This report could not be loaded."
            );
        }

        state.latestReport =
            report;

        state.currentReportId =
            id;

        state.currentSymbol =
            normalizeSymbol(
                firstDefined(
                    report?.asset?.symbol,
                    report?.token_symbol,
                    report?.symbol
                )
            );

        renderReport(
            report
        );

        if (
            state.currentSymbol
        ) {
            // The history payload already contains market data.
            // Prevent startLivePolling from instantly firing a redundant request.
            setLastFetchTime(state.currentSymbol, Date.now());
            startLivePolling(
                state.currentSymbol
            );
        }

        window.scrollTo({
            top: 0,
            behavior: "smooth"
        });
    } catch (error) {
        console.error(
            "History report load failed:",
            error
        );

        // FIX (Bug 6): friendly message instead of raw error string.
        showAnalysisError(
            friendlyErrorMessage(error) ||
            "Unable to load report."
        );
    }
}




/* ============================================================
   DELETE REPORT
   ============================================================ */

export async function deleteReport(id) {
    if (!id) return;

    try {
        await apiRequest(
            API.deleteHistory(id),
            {
                method: "DELETE"
            }
        );

        if (
            String(
                state.currentReportId
            ) === String(id)
        ) {
            state.currentReportId =
                null;

            state.latestReport =
                null;

            state.currentSymbol =
                null;

            clearReportView();
            stopLivePolling();
        }

        await refreshHistory();
    } catch (error) {
        console.error(
            "Delete report failed:",
            error
        );

        // FIX (Bug 6): friendly message instead of raw error string.
        showAnalysisError(
            friendlyErrorMessage(error) ||
            "Unable to delete report."
        );
    }
}

export async function deleteCurrentReport() {
    if (!state.currentReportId) {
        return;
    }

    await deleteReport(
        state.currentReportId
    );
}




