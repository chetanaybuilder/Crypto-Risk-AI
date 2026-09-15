import { stopLivePolling } from './market.js';
import { state } from '../state/store.js';
import { apiRequest, API, friendlyErrorMessage, renderUser, applyJobProgress, clearAnalysisError, showAnalysisError } from './client.js';
import { startProgress, animateProgressTo, finishProgress, abortProgress, clearReportView } from '../components/ui.js';
import { refreshHistory } from './history.js';
import { startLivePolling, setLastFetchTime } from './market.js';
import { renderReport, getReportFromPayload, getMarket, updateLiveMarket } from '../components/market.js';
import { show, hide, setText, firstDefined, normalizeSymbol } from '../utils/dom.js';
import { redirectToHome } from './auth.js';
import { renderHistory } from '../components/history.js';

/* ============================================================
   JOB POLLING CONFIG
   ============================================================ */

export const JOB_POLL_INTERVAL_MS = 1500;

// FIX (Bug 7): JOB_POLL_MAX_MS is no longer hardcoded at 340000.
// It is derived from the backend's real ANALYSIS_JOB_TIMEOUT_SECONDS
// (exposed via GET /health as "analysis_job_timeout_seconds") plus a
// 60s headroom, and refreshed at startup by syncJobPollCeiling().
// The value below is only the fallback for when /health is
// unreachable (backend default is 150s).
export const JOB_POLL_DEFAULT_TIMEOUT_SECONDS = 150;
export const JOB_POLL_HEADROOM_MS = 60000;

export let JOB_POLL_MAX_MS =
    JOB_POLL_DEFAULT_TIMEOUT_SECONDS * 1000 +
    JOB_POLL_HEADROOM_MS;

export async function syncJobPollCeiling() {
    try {
        const payload = await apiRequest("/health");

        const seconds = Number(
            payload?.analysis_job_timeout_seconds
        );

        if (Number.isFinite(seconds) && seconds > 0) {
            JOB_POLL_MAX_MS =
                seconds * 1000 + JOB_POLL_HEADROOM_MS;

            console.log(
                "CryptoRisk job poll ceiling synced from /health:",
                JOB_POLL_MAX_MS + "ms"
            );
        }
    } catch (error) {
        console.warn(
            "Could not read /health for job timeout config; using fallback ceiling.",
            error
        );
    }
}




/* ============================================================
   DASHBOARD LOAD
   ============================================================ */

export async function loadDashboard() {
    if (!state.token) {
        redirectToHome();
        return;
    }

    try {
        const payload =
            await apiRequest(
                API.dashboard
            );

        console.log(
            "CryptoRisk dashboard payload:",
            payload
        );

        if (payload.user) {
            renderUser(
                payload.user
            );
        }

        /*
         * Support:
         * payload.latest
         * payload.data.latest
         * payload.report
         * etc.
         */
        const latest =
            payload.latest ||
            payload.data?.latest ||
            payload.report ||
            payload.data?.report ||
            null;

        const report =
            getReportFromPayload(
                latest || payload
            );

        if (report) {
            state.latestReport =
                report;

            state.currentReportId =
                firstDefined(
                    latest?.id,
                    latest?.analysis_id,
                    payload.analysis_id,
                    report.id
                );

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
                // The dashboard payload already contains fresh market data.
                // Prevent startLivePolling from instantly firing a redundant request.
                setLastFetchTime(state.currentSymbol, Date.now());
                startLivePolling(
                    state.currentSymbol
                );
            }
        } else {
            console.warn(
                "No valid latest report found:",
                payload
            );

            state.currentReportId =
                null;

            state.currentSymbol =
                null;

            stopLivePolling();
            clearReportView();
        }

        const history =
            Array.isArray(
                payload.history
            )
                ? payload.history
                : (
                    Array.isArray(
                        payload.data?.history
                    )
                        ? payload.data.history
                        : []
                );

        renderHistory(
            history
        );
    } catch (error) {
        console.error(
            "Dashboard load failed:",
            error
        );

        // FIX (Bug 6): friendly message instead of raw error string.
        showAnalysisError(
            friendlyErrorMessage(error) ||
            "Unable to load dashboard."
        );
    }
}


/* ============================================================
   JOB POLLING (async analyze flow)
   ============================================================
   FIX (core bug fix): the backend runs the full pipeline
   (market fetch, history x2, quant, security, stress, evidence,
   Gemini) which can legitimately take well over the timeout
   window of most reverse proxies / browsers when called
   synchronously via POST /api/analyze. The backend already
   exposes an async job flow for exactly this reason:
     POST /api/analyze/start          -> { job_id }
     GET  /api/analyze/status/<id>    -> { job: { status, progress,
                                            stage, ... }, latest? }
   We now use that flow exclusively from the UI.
   ============================================================ */

export function stopJobPolling() {
    if (state.jobPollTimer) {
        clearTimeout(state.jobPollTimer);
        state.jobPollTimer = null;
    }

    state.activeJobId = null;
    state.jobPollStartedAt = 0;
}

/**
 * Polls /api/analyze/status/<jobId> until the job completes,
 * fails, times out server-side, or we exceed our own client-side
 * polling ceiling (JOB_POLL_MAX_MS). Resolves with the completed
 * report, or throws an Error with a useful message.
 */
export function pollAnalysisJob(jobId) {
    return new Promise((resolve, reject) => {
        state.activeJobId = jobId;
        state.jobPollStartedAt = Date.now();

        const poll = async () => {
            // If a newer job superseded this one, or polling was
            // explicitly stopped, bail out quietly.
            if (state.activeJobId !== jobId) {
                return;
            }

            if (
                Date.now() - state.jobPollStartedAt >
                JOB_POLL_MAX_MS
            ) {
                stopJobPolling();
                reject(
                    new Error(
                        "Analysis is taking much longer than expected. " +
                        "It may still finish in the background — check " +
                        "your history in a minute, or try again."
                    )
                );
                return;
            }

            let payload;

            try {
                payload = await apiRequest(
                    API.analyzeStatus(jobId)
                );
            } catch (error) {
                // Transient poll failure (e.g. one dropped request)
                // shouldn't kill the whole flow — retry a few times
                // before giving up, unless it's an auth error (which
                // apiRequest already redirects on).
                if (error.code === "AUTH_EXPIRED") {
                    stopJobPolling();
                    reject(error);
                    return;
                }

                console.warn(
                    "Job status poll failed, retrying:",
                    error
                );

                if (state.activeJobId === jobId) {
                    state.jobPollTimer = setTimeout(
                        poll,
                        JOB_POLL_INTERVAL_MS
                    );
                }

                return;
            }

            if (state.activeJobId !== jobId) {
                return;
            }

            const job = payload?.job;

            if (!job) {
                stopJobPolling();
                reject(
                    new Error(
                        "The backend did not return a valid job status."
                    )
                );
                return;
            }

            applyJobProgress(job);

            if (job.status === "completed") {
                stopJobPolling();

                const report = getReportFromPayload(payload);

                if (!report) {
                    reject(
                        new Error(
                            "Analysis completed, but no valid report " +
                            "was returned."
                        )
                    );
                    return;
                }

                resolve({ report, payload });
                return;
            }

            if (job.status === "failed") {
                stopJobPolling();

                reject(
                    new Error(
                        job.error ||
                        job.message ||
                        "Analysis failed."
                    )
                );
                return;
            }

            // Still queued/running/saving — keep polling.
            if (state.activeJobId === jobId) {
                state.jobPollTimer = setTimeout(
                    poll,
                    JOB_POLL_INTERVAL_MS
                );
            }
        };

        poll();
    });
}




/* ============================================================
   ANALYSIS
   ============================================================ */

export async function runAnalysis(
    symbol,
    options = {}
) {
    if (state.isAnalyzing) {
        return;
    }

    const normalizedSymbol =
        normalizeSymbol(symbol);

    if (!normalizedSymbol) {
        showAnalysisError(
            "Enter a token symbol."
        );

        return;
    }

    state.isAnalyzing = true;

    clearAnalysisError();
    stopLivePolling();
    stopJobPolling();
    startProgress();

    try {
        // Step 1: start the background job.
        //
        // FIX (Bug 2): include the optional contract security fields
        // when BOTH are provided — the backend runs the GoPlus
        // structural check only when it receives chain_id AND
        // contract_address together.
        const requestBody = {
            token_symbol: normalizedSymbol
        };

        const chainId =
            typeof options.chainId === "string"
                ? options.chainId.trim()
                : "";

        const contractAddress =
            typeof options.contractAddress === "string"
                ? options.contractAddress.trim()
                : "";

        if (chainId && contractAddress) {
            requestBody.chain_id =
                chainId;

            requestBody.contract_address =
                contractAddress;
        }

        const startPayload = await apiRequest(
            API.analyzeStart,
            {
                method: "POST",
                body: requestBody
            }
        );

        console.log(
            "CryptoRisk analyze/start payload:",
            startPayload
        );

        const jobId = firstDefined(
            startPayload.job_id,
            startPayload.job?.id,
            startPayload.data?.job_id
        );

        if (!jobId) {
            throw new Error(
                "The backend did not return a job id for this analysis."
            );
        }

        // Step 2: poll until the job completes.
        const { report, payload } = await pollAnalysisJob(jobId);

        state.latestReport = report;

        state.currentReportId =
            firstDefined(
                payload.analysis?.id,
                payload.meta?.analysis_id,
                payload.analysis_id,
                payload.id,
                report.id
            );

        state.currentSymbol =
            normalizeSymbol(
                firstDefined(
                    report?.asset?.symbol,
                    report?.token_symbol,
                    report?.symbol,
                    normalizedSymbol
                )
            );

        if (payload.user) {
            renderUser(payload.user);
        }

        renderReport(report);

        const history =
            Array.isArray(payload.history)
                ? payload.history
                : Array.isArray(payload.data?.history)
                    ? payload.data.history
                    : null;

        if (history) {
            renderHistory(history);
        } else {
            await refreshHistory();
        }

        finishProgress();

        if (state.currentSymbol) {
            // FIX (Problem 1): Use the fresh market data from the newly completed 
            // analysis report to update the live UI immediately. This avoids a 
            // redundant /api/market call right after a job finishes.
            const jobMarket = getMarket(report);
            if (jobMarket && Object.keys(jobMarket).length > 0) {
                updateLiveMarket(jobMarket);
                setLastFetchTime(state.currentSymbol, Date.now());
            }

            startLivePolling(state.currentSymbol);
        }
    } catch (error) {
        console.error(
            "Analysis failed:",
            error
        );

        // FIX (Bug 6): translate raw provider errors into
        // user-friendly messages before showing them.
        showAnalysisError(
            friendlyErrorMessage(error) ||
            "Analysis failed."
        );

        abortProgress();
    } finally {
        state.isAnalyzing = false;
        stopJobPolling();
    }
}




