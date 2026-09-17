/**
 * Asynchronous Analysis Pipeline API.
 * Orchestrates job submission, progress tracking, timeout sync, and dashboard data hydration.
 */

import { stopLivePolling } from './market.js';
import { state } from '../state/store.js';
import { apiRequest, API, friendlyErrorMessage, renderUser, applyJobProgress, clearAnalysisError, showAnalysisError, startProgress, finishProgress, abortProgress } from './client.js';
import { clearReportView } from '../components/ui.js';
import { refreshHistory } from './history.js';
import { startLivePolling, setLastFetchTime } from './market.js';
import { renderReport, getReportFromPayload, getMarket, updateLiveMarket } from '../components/market.js';
import { show, hide, setText, firstDefined, normalizeSymbol } from '../utils/dom.js';
import { redirectToHome, getTokenFromStorage } from './auth.js';
import { renderHistory } from '../components/history.js';

export const JOB_POLL_INTERVAL_MS = 1500;

// Dynamic job poll ceiling synchronized with backend timeout
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
            JOB_POLL_MAX_MS = seconds * 1000 + JOB_POLL_HEADROOM_MS;
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
        state.token = getTokenFromStorage();
    }

    if (!state.token) {
        redirectToHome();
        return;
    }

    try {
        const payload = await apiRequest(API.dashboard);

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

        showAnalysisError(
            friendlyErrorMessage(error) ||
            "Unable to load dashboard."
        );
    }
}


/* ============================================================
   JOB POLLING (Asynchronous Analysis Execution)
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
        // Attach optional contract security parameters if supplied
        const requestBody = {
            token_symbol: normalizedSymbol
        };

        const chainid =
            typeof options.chainId === "string"
                ? options.chainId.trim()
                : "";

        // 1. Try reading from options (supporting camelCase or snake_case)
        let chainId = options.chainId || options.chain_id || options.chain || "";
        let contractAddress = options.contractAddress || options.contract_address || options.address || "";

        // 2. Fallback: If options were empty, read directly from the HTML inputs
        if (!chainId) {
            const chainEl = document.getElementById("chain-id") ||
                document.querySelector("select[name='chain_id']") ||
                document.querySelector("select");
            chainId = chainEl?.value || "";
        }

        if (!contractAddress) {
            const addrEl = document.getElementById("contract-address") ||
                document.querySelector("input[name='contract_address']") ||
                document.querySelector("input[placeholder*='0x']");
            contractAddress = addrEl?.value || "";
        }

        chainId = typeof chainId === "string" ? chainId.trim() : "";
        contractAddress = typeof contractAddress === "string" ? contractAddress.trim() : "";

        // 3. Attach both fields to the request if present
        if (chainId && contractAddress) {
            requestBody.chain_id = chainId;
            requestBody.contract_address = contractAddress;
        }

        const startPayload = await apiRequest(
            API.analyzeStart,
            {
                method: "POST",
                body: requestBody
            }
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
            // Apply fresh market data from newly completed report
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




