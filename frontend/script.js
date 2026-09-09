"use strict";

/*
 * ============================================================
 * CryptoRisk AI — Dashboard Controller
 * Backend Report Schema: 3.0
 *
 * Backend is the single source of truth.
 * ============================================================
 */


/* ============================================================
   API
   ============================================================ */

const API = {
    dashboard: "/api/dashboard",
    analyze: "/api/analyze",
    logout: "/api/auth/logout",
    me: "/api/auth/me",

    market: (symbol) =>
        `/api/market/${encodeURIComponent(symbol)}`,

    history: (id) =>
        `/api/history/${encodeURIComponent(id)}`,

    deleteHistory: (id) =>
        `/api/history/${encodeURIComponent(id)}`
};


/* ============================================================
   STORAGE
   ============================================================ */

const STORAGE_KEYS = {
    token: "token"
};


/* ============================================================
   APPLICATION STATE
   ============================================================ */

const state = {
    token: null,
    user: null,

    latestReport: null,

    currentReportId: null,
    currentSymbol: null,

    livePollTimer: null,

    isAnalyzing: false
};


/* ============================================================
   DOM HELPERS
   ============================================================ */

function $(selector) {
    return document.querySelector(selector);
}


function $all(selector) {
    return Array.from(
        document.querySelectorAll(selector)
    );
}


function setText(
    selector,
    value,
    fallback = "—"
) {
    const element = $(selector);

    if (!element) {
        return;
    }

    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        element.textContent = fallback;
        return;
    }

    element.textContent = String(value);
}


function setHTML(
    selector,
    html
) {
    const element = $(selector);

    if (element) {
        element.innerHTML = html;
    }
}


function show(element) {
    if (!element) {
        return;
    }

    element.hidden = false;
    element.style.display = "";
}


function hide(element) {
    if (!element) {
        return;
    }

    element.hidden = true;
    element.style.display = "none";
}


function toggle(
    element,
    visible
) {
    if (visible) {
        show(element);
    } else {
        hide(element);
    }
}


/* ============================================================
   AUTH
   ============================================================ */

function getTokenFromStorage() {
    return localStorage.getItem(
        STORAGE_KEYS.token
    );
}


function saveToken(token) {
    if (!token) {
        return;
    }

    state.token = token;

    localStorage.setItem(
        STORAGE_KEYS.token,
        token
    );
}


function clearToken() {
    state.token = null;

    localStorage.removeItem(
        STORAGE_KEYS.token
    );
}


function consumeQueryToken() {
    const params =
        new URLSearchParams(
            window.location.search
        );

    const token =
        params.get("token");

    if (!token) {
        return null;
    }

    saveToken(token);

    const cleanUrl =
        window.location.pathname +
        window.location.hash;

    window.history.replaceState(
        {},
        document.title,
        cleanUrl
    );

    return token;
}


function getAuthHeaders() {
    const token =
        state.token ||
        getTokenFromStorage();

    if (!token) {
        return {};
    }

    return {
        Authorization:
            `Bearer ${token}`
    };
}


function redirectToHome() {
    clearToken();

    stopLivePolling();

    window.location.href = "/";
}


/* ============================================================
   API REQUEST LAYER
   ============================================================ */

/*
 * Resolve an API path against the configured backend base URL.
 *
 * The static frontend (served from its own origin) loads
 * frontend/config.js, which sets window.CONFIG.API_BASE_URL to
 * the Flask backend. The backend-served dashboard does not load
 * config.js, so CONFIG is undefined and same-origin relative
 * URLs are used unchanged.
 */
function resolveApiUrl(url) {
    const configured =
        typeof window !== "undefined" &&
        window.CONFIG &&
        window.CONFIG.API_BASE_URL;

    const base =
        typeof configured === "string"
            ? configured.trim().replace(/\/+$/, "")
            : "";

    if (
        !base ||
        typeof url !== "string" ||
        url.startsWith("http://") ||
        url.startsWith("https://") ||
        url.startsWith("//")
    ) {
        return url;
    }

    if (url.startsWith("/")) {
        return `${base}${url}`;
    }

    return `${base}/${url}`;
}


async function apiRequest(
    url,
    options = {}
) {
    const resolvedUrl =
        resolveApiUrl(url);

    const headers = {
        Accept: "application/json",

        ...(options.headers || {}),

        ...getAuthHeaders()
    };

    if (
        options.body &&
        typeof options.body !== "string"
    ) {
        headers["Content-Type"] =
            "application/json";

        options = {
            ...options,

            body: JSON.stringify(
                options.body
            )
        };
    }

    let response;

    try {
        response =
            await fetch(
                resolvedUrl,
                {
                    ...options,
                    headers
                }
            );
    } catch (error) {
        console.error(
            "Network error:",
            error
        );

        throw new Error(
            "Unable to connect to the CryptoRisk backend."
        );
    }

    let payload = null;

    const contentType =
        response.headers.get(
            "content-type"
        ) || "";

    if (
        contentType.includes(
            "application/json"
        )
    ) {
        try {
            payload =
                await response.json();
        } catch (error) {
            console.warn(
                "Could not parse JSON response.",
                error
            );

            payload = null;
        }
    } else {
        try {
            const text =
                await response.text();

            if (text) {
                payload = {
                    message: text
                };
            }
        } catch {
            payload = null;
        }
    }

    /*
     * Session expired.
     */
    if (response.status === 401) {
        clearToken();

        stopLivePolling();

        if (
            window.location.pathname !== "/" &&
            window.location.pathname !== ""
        ) {
            window.location.href = "/";
        }

        throw new Error(
            payload?.message ||
            payload?.error ||
            "Your session has expired."
        );
    }

    /*
     * Other HTTP errors.
     */
    if (!response.ok) {
        const message =
            payload?.message ||
            payload?.error ||
            payload?.detail ||
            `Request failed (${response.status}).`;

        throw new Error(message);
    }

    return payload || {};
}


/* ============================================================
   ERROR UI
   ============================================================ */

function showAnalysisError(
    message
) {
    const element =
        $("#analysis-error");

    if (!element) {
        console.error(
            message
        );

        return;
    }

    element.textContent =
        message ||
        "Something went wrong.";

    show(element);
}


function clearAnalysisError() {
    const element =
        $("#analysis-error");

    if (!element) {
        return;
    }

    element.textContent = "";

    hide(element);
}


/* ============================================================
   USER UI
   ============================================================ */

function renderUser(user) {
    if (
        !user ||
        typeof user !== "object"
    ) {
        return;
    }

    state.user = user;

    const displayName =
        firstDefined(
            user.username,
            user.name,
            user.email,
            "User"
        );

    setText(
        ".user-name",
        displayName
    );

    setText(
        ".user-email",
        user.email || ""
    );

    const avatars =
        $all(".user-avatar");

    avatars.forEach(
        (avatar) => {
            if (user.avatar_url) {
                avatar.src =
                    user.avatar_url;

                avatar.alt =
                    displayName;
            } else {
                avatar.removeAttribute(
                    "src"
                );

                avatar.alt =
                    displayName;
            }
        }
    );
}


/* ============================================================
   PROGRESS SYSTEM
   ============================================================ */

const PROGRESS_STAGES = {
    market: {
        percent: 20,
        title:
            "Fetching live market data"
    },

    model: {
        percent: 45,
        title:
            "Running quantitative risk engine"
    },

    stress: {
        percent: 65,
        title:
            "Running stress scenarios"
    },

    ai: {
        percent: 82,
        title:
            "Synthesizing evidence"
    },

    save: {
        percent: 96,
        title:
            "Saving intelligence report"
    },

    complete: {
        percent: 100,
        title:
            "Analysis complete"
    }
};

/*
 * Active animation handle so we can cancel a previous
 * run if startProgress is invoked again before the
 * prior animation finishes.
 */
let _progressAnim = null;


/*
 * Map a 0–100 progress value to the matching pipeline
 * stage so the status pills light up continuously as
 * the beam advances instead of jumping discretely.
 */
function _stageForPercent(
    percent
) {
    if (percent >= 96) {
        return "save";
    }
    if (percent >= 82) {
        return "ai";
    }
    if (percent >= 65) {
        return "stress";
    }
    if (percent >= 45) {
        return "model";
    }
    return "market";
}


/*
 * Smooth, continuous progress from 1% to target using
 * requestAnimationFrame. The beam eases naturally and
 * never gets stuck — it always advances toward the
 * target and snaps to 100% once the API responds.
 */
function animateProgress(
    targetPercent = 100
) {
    const fill =
        $("#progress-fill");

    const percentEl =
        $("#progress-percent");

    const startPercent = 1;
    const startTime = performance.now();

    /*
     * Cap the visible run to ~4.5s so the bar never
     * crawls — the API response snaps it to 100%.
     */
    const durationMs = 4500;

    if (_progressAnim) {
        cancelAnimationFrame(
            _progressAnim
        );
        _progressAnim = null;
    }

    function frame(
        now
    ) {
        const elapsed = now - startTime;

        /*
         * Ease-out cubic: fast start, gentle approach
         * to the target so the beam feels alive.
         */
        const t = Math.min(
            elapsed / durationMs,
            1
        );

        const eased = 1 - Math.pow(
            1 - t,
            3
        );

        const current = startPercent + (
            targetPercent - startPercent
        ) * eased;

        const stageName = _stageForPercent(
            current
        );

        const config =
            PROGRESS_STAGES[stageName] ||
            PROGRESS_STAGES.market;

        if (fill) {
            fill.style.width =
                `${current}%`;
        }

        if (percentEl) {
            percentEl.textContent =
                `${Math.round(current)}%`;
        }

        setText(
            "#progress-title",
            config.title
        );

        /*
         * Light up status pills to match the beam.
         */
        const stageOrder = [
            "market",
            "model",
            "stress",
            "ai",
            "save"
        ];

        const currentIndex =
            stageOrder.indexOf(
                stageName
            );

        $all(
            ".progress-status"
        ).forEach(
            (element) => {
                element.classList.remove(
                    "active",
                    "complete"
                );

                const index =
                    stageOrder.indexOf(
                        element.dataset.stage
                    );

                if (
                    index < 0
                ) {
                    return;
                }

                if (
                    index < currentIndex
                ) {
                    element.classList.add(
                        "complete"
                    );
                } else if (
                    index === currentIndex
                ) {
                    element.classList.add(
                        "active"
                    );
                }
            }
        );

        if (
            t < 1 &&
            current < targetPercent
        ) {
            _progressAnim =
                requestAnimationFrame(
                    frame
                );
            return;
        }

        /*
         * Reached the target — ensure the final
         * stage is fully lit.
         */
        setProgressStage(
            _stageForPercent(
                targetPercent
            )
        );
    }

    _progressAnim = requestAnimationFrame(
        frame
    );
}


function setProgressStage(
    stage
) {
    const config =
        PROGRESS_STAGES[stage] ||
        PROGRESS_STAGES.market;

    setText(
        "#progress-title",
        config.title
    );

    setText(
        "#progress-percent",
        `${config.percent}%`
    );

    const fill =
        $("#progress-fill");

    if (fill) {
        fill.style.width =
            `${config.percent}%`;
    }

    $all(
        ".progress-status"
    ).forEach(
        (element) => {
            element.classList.remove(
                "active",
                "complete"
            );

            const stageName =
                element.dataset.stage;

            if (
                stageName === stage
            ) {
                element.classList.add(
                    "active"
                );
            }
        }
    );

    const stageOrder = [
        "market",
        "model",
        "stress",
        "ai",
        "save"
    ];

    const currentIndex =
        stageOrder.indexOf(stage);

    if (currentIndex < 0) {
        return;
    }

    $all(
        ".progress-status"
    ).forEach(
        (element) => {
            const index =
                stageOrder.indexOf(
                    element.dataset.stage
                );

            if (
                index >= 0 &&
                index < currentIndex
            ) {
                element.classList.add(
                    "complete"
                );
            }
        }
    );
}


function startProgress() {
    const overlay =
        $("#analysis-progress");

    if (!overlay) {
        return;
    }

    show(overlay);

    /*
     * Kick off the smooth beam animation from 1%.
     * It runs concurrently with the API request and
     * snaps to 100% when finishProgress is called.
     */
    animateProgress(95);
}


function finishProgress() {
    const overlay =
        $("#analysis-progress");

    if (!overlay) {
        return;
    }

    /*
     * Snap the beam to 100% and light up every
     * stage pill so the user sees a clean finish.
     */
    animateProgress(100);

    setProgressStage(
        "complete"
    );

    setTimeout(
        () => {
            hide(overlay);
        },
        450
    );
}


/* ============================================================
   FORMATTERS
   ============================================================ */

function formatNumber(
    value,
    decimals = 2
) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "—";
    }

    const number =
        Number(value);

    if (
        !Number.isFinite(number)
    ) {
        return "—";
    }

    return number.toLocaleString(
        undefined,
        {
            maximumFractionDigits:
                decimals
        }
    );
}


function formatUsd(value) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "—";
    }

    const number =
        Number(value);

    if (
        !Number.isFinite(number)
    ) {
        return "—";
    }

    if (
        Math.abs(number) >=
        1_000_000_000
    ) {
        return `$${formatNumber(
            number / 1_000_000_000,
            2
        )}B`;
    }

    if (
        Math.abs(number) >=
        1_000_000
    ) {
        return `$${formatNumber(
            number / 1_000_000,
            2
        )}M`;
    }

    if (
        Math.abs(number) >=
        1_000
    ) {
        return `$${formatNumber(
            number / 1_000,
            2
        )}K`;
    }

    if (
        Math.abs(number) >= 1
    ) {
        return `$${formatNumber(
            number,
            2
        )}`;
    }

    return `$${number.toFixed(6)}`;
}


function formatPercent(
    value
) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "—";
    }

    const number =
        Number(value);

    if (
        !Number.isFinite(number)
    ) {
        return "—";
    }

    const sign =
        number > 0
            ? "+"
            : "";

    return `${sign}${number.toFixed(2)}%`;
}


function formatScore(
    value
) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "—";
    }

    const number =
        Number(value);

    if (
        !Number.isFinite(number)
    ) {
        return "—";
    }

    return Math.round(number);
}


function formatConfidence(
    value
) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "—";
    }

    const number =
        Number(value);

    if (
        !Number.isFinite(number)
    ) {
        return "—";
    }

    return `${number.toFixed(1)}%`;
}


function formatDate(value) {
    if (!value) {
        return "—";
    }

    const date =
        new Date(value);

    if (
        Number.isNaN(
            date.getTime()
        )
    ) {
        return String(value);
    }

    return date.toLocaleString(
        undefined,
        {
            dateStyle: "medium",
            timeStyle: "short"
        }
    );
}


function formatRelativeTime(
    value
) {
    if (!value) {
        return "—";
    }

    const date =
        new Date(value);

    if (
        Number.isNaN(
            date.getTime()
        )
    ) {
        return formatDate(value);
    }

    const seconds =
        Math.floor(
            (
                Date.now() -
                date.getTime()
            ) / 1000
        );

    if (seconds < 10) {
        return "just now";
    }

    if (seconds < 60) {
        return `${seconds}s ago`;
    }

    const minutes =
        Math.floor(
            seconds / 60
        );

    if (minutes < 60) {
        return `${minutes}m ago`;
    }

    const hours =
        Math.floor(
            minutes / 60
        );

    if (hours < 24) {
        return `${hours}h ago`;
    }

    return `${Math.floor(
        hours / 24
    )}d ago`;
}


function clampScore(value) {
    /*
     * IMPORTANT:
     * Missing score = null.
     * NEVER convert missing score to 0.
     */
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return null;
    }

    const number =
        Number(value);

    if (
        !Number.isFinite(number)
    ) {
        return null;
    }

    return Math.max(
        0,
        Math.min(
            100,
            number
        )
    );
}


/* ============================================================
   SAFE DATA HELPERS
   ============================================================ */

function firstDefined(
    ...values
) {
    for (
        const value of values
    ) {
        if (
            value !== undefined &&
            value !== null &&
            value !== ""
        ) {
            return value;
        }
    }

    return null;
}


function isRiskReport(
    value
) {
    if (
        !value ||
        typeof value !== "object"
    ) {
        return false;
    }

    /*
     * Strong indicators of schema 3.0.
     */
    if (
        value.schema_version ||
        value.risk_profile ||
        value.risk_drivers ||
        value.stress_test ||
        value.data_quality
    ) {
        return true;
    }

    /*
     * Also support a direct report
     * without schema_version.
     */
    return Boolean(
        value.risk_score !== undefined &&
        (
            value.asset ||
            value.token_symbol
        )
    );
}


function getReportFromPayload(
    payload
) {
    if (!payload) {
        return null;
    }

    /*
     * Case 1:
     *
     * Backend returns the report itself.
     */
    if (
        isRiskReport(payload)
    ) {
        return payload;
    }

    /*
     * Case 2:
     *
     * Backend wraps report in analysis.
     */
    const candidates = [
        payload.analysis,

        /*
         * Case 3:
         * { report: {...} }
         */
        payload.report,

        /*
         * Case 4:
         * { latest: { report: {...} } }
         */
        payload.latest?.report,

        /*
         * Case 5:
         * { latest: {...report...} }
         */
        payload.latest,

        /*
         * Case 6:
         * { data: {...report...} }
         */
        payload.data
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
   REPORT ACCESSORS
   ============================================================ */

function getRiskProfile(
    report
) {
    return (
        report?.risk_profile || {}
    );
}


function getPillars(
    report
) {
    return (
        report
            ?.risk_profile
            ?.pillars || {}
    );
}


function getPillar(
    report,
    name
) {
    return (
        report
            ?.risk_profile
            ?.pillars
            ?.[name] || {}
    );
}


function getAI(
    report
) {
    return (
        report?.ai || {}
    );
}


function getMarket(
    report
) {
    return (
        report?.market || {}
    );
}


function getSecurity(
    report
) {
    return (
        report?.security || {}
    );
}


function getStress(
    report
) {
    /*
     * Backend Schema 3.0 exposes the scenario model under
     * BOTH ``stress_test`` (canonical) and ``stress``
     * (legacy alias). Normalize here so every render site
     * reads the same object.
     */
    const stress =
        report?.stress_test ||
        report?.stress ||
        {};

    return stress;
}


function getDataQuality(
    report
) {
    return (
        report?.data_quality || {}
    );
}


/* ============================================================
   DASHBOARD LOAD
   ============================================================ */

async function loadDashboard() {
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

        /*
         * User
         */
        if (payload.user) {
            renderUser(
                payload.user
            );
        }

        /*
         * Latest report.
         *
         * IMPORTANT:
         * Do not assume latest itself is always
         * the report.
         */
        const latest =
            payload.latest;

        if (latest) {
            const report =
                getReportFromPayload(
                    latest
                );

            if (report) {
                state.latestReport =
                    report;

                state.currentReportId =
                    latest.id ||
                    latest.analysis_id ||
                    report.id ||
                    null;

                state.currentSymbol =
                    firstDefined(
                        report?.asset?.symbol,
                        report?.token_symbol
                    );

                renderReport(
                    report
                );

                if (
                    state.currentSymbol
                ) {
                    startLivePolling(
                        state.currentSymbol
                    );
                }

            } else {
                console.warn(
                    "Latest dashboard item did not contain a valid report.",
                    latest
                );

                clearReportView();
            }

        } else {
            clearReportView();
        }

        /*
         * History
         */
        renderHistory(
            Array.isArray(
                payload.history
            )
                ? payload.history
                : []
        );

    } catch (error) {
        console.error(
            "Dashboard load failed:",
            error
        );

        showAnalysisError(
            error.message ||
            "Unable to load dashboard."
        );
    }
}


/* ============================================================
   ANALYSIS
   ============================================================ */

async function runAnalysis(
    symbol
) {
    if (state.isAnalyzing) {
        return;
    }

    state.isAnalyzing = true;

    clearAnalysisError();

    startProgress();

    stopLivePolling();

    const normalizedSymbol =
        String(symbol || "")
            .trim()
            .toUpperCase();

    if (!normalizedSymbol) {
        state.isAnalyzing = false;

        hide(
            $("#analysis-progress")
        );

        showAnalysisError(
            "Enter a token symbol."
        );

        return;
    }

    try {
        /*
         * Fire the analysis request. The beam animation
         * (started in startProgress) runs concurrently
         * and advances smoothly while we await the API.
         */
        const payload =
            await apiRequest(
                API.analyze,
                {
                    method: "POST",

                    body: {
                        token_symbol:
                            normalizedSymbol
                    }
                }
            );

        console.log(
            "CryptoRisk analyze payload:",
            payload
        );

        /*
         * Extract actual report.
         */
        const report =
            getReportFromPayload(
                payload
            );

        if (!report) {
            console.error(
                "Analyze response did not contain a recognizable report:",
                payload
            );

            throw new Error(
                "The backend returned data, but no valid risk report was found."
            );
        }

        /*
         * Store report.
         */
        state.latestReport =
            report;

        state.currentReportId =
            firstDefined(
                payload.analysis_id,
                payload.id,
                payload.analysis?.id,
                payload.report?.id,
                payload.latest?.id,
                report.id
            );

        state.currentSymbol =
            firstDefined(
                report?.asset?.symbol,
                report?.token_symbol,
                normalizedSymbol
            );

        /*
         * User.
         */
        if (payload.user) {
            renderUser(
                payload.user
            );
        }

        /*
         * Render.
         */
        renderReport(
            report
        );

        /*
         * History.
         */
        if (
            Array.isArray(
                payload.history
            )
        ) {
            renderHistory(
                payload.history
            );
        } else {
            await refreshHistory();
        }

        finishProgress();

        /*
         * Live market only updates market
         * fields. It never changes risk score.
         */
        startLivePolling(
            state.currentSymbol
        );

    } catch (error) {
        console.error(
            "Analysis failed:",
            error
        );

        showAnalysisError(
            error.message ||
            "Analysis failed."
        );

        hide(
            $("#analysis-progress")
        );

    } finally {
        state.isAnalyzing = false;
    }
}


/* ============================================================
   HISTORY FETCH
   ============================================================ */

async function refreshHistory() {
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

        renderHistory(
            Array.isArray(
                payload.history
            )
                ? payload.history
                : []
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

async function loadHistoryReport(
    id
) {
    if (!id) {
        return;
    }

    clearAnalysisError();

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
            firstDefined(
                report?.asset?.symbol,
                report?.token_symbol
            );

        renderReport(
            report
        );

        if (
            state.currentSymbol
        ) {
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

        showAnalysisError(
            error.message ||
            "Unable to load report."
        );
    }
}


/* ============================================================
   DELETE REPORT
   ============================================================ */

async function deleteReport(
    id
) {
    if (!id) {
        return;
    }

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

            clearReportView();

            stopLivePolling();
        }

        await refreshHistory();

    } catch (error) {
        console.error(
            "Delete report failed:",
            error
        );

        showAnalysisError(
            error.message ||
            "Unable to delete report."
        );
    }
}


async function deleteCurrentReport() {
    if (
        !state.currentReportId
    ) {
        return;
    }

    await deleteReport(
        state.currentReportId
    );
}


/* ============================================================
   LOGOUT
   ============================================================ */

async function logout() {
    try {
        if (state.token) {
            await apiRequest(
                API.logout,
                {
                    method: "POST"
                }
            );
        }

    } catch (error) {
        console.warn(
            "Logout request failed:",
            error
        );

    } finally {
        clearToken();

        stopLivePolling();

        window.location.href = "/";
    }
}


/* ============================================================
   LIVE MARKET POLLING
   ============================================================ */

function stopLivePolling() {
    if (
        state.livePollTimer
    ) {
        clearInterval(
            state.livePollTimer
        );

        state.livePollTimer = null;
    }
}


function startLivePolling(
    symbol
) {
    stopLivePolling();

    if (!symbol) {
        return;
    }

    state.currentSymbol =
        String(symbol)
            .trim()
            .toUpperCase();

    refreshLiveMarket(
        state.currentSymbol
    );

    state.livePollTimer =
        setInterval(
            () => {
                refreshLiveMarket(
                    state.currentSymbol
                );
            },
            15000
        );
}


async function refreshLiveMarket(
    symbol
) {
    if (!symbol) {
        return;
    }

    try {
        const payload =
            await apiRequest(
                API.market(symbol)
            );

        const market =
            payload?.market ||
            payload?.data ||
            payload;

        updateLiveMarket(
            market
        );

    } catch (error) {
        console.warn(
            "Live market refresh failed:",
            error
        );

        setText(
            "#market-live-status",
            "Live feed unavailable"
        );
    }
}


function updateLiveMarket(
    market
) {
    if (
        !market ||
        typeof market !== "object"
    ) {
        return;
    }

    /*
     * Exact v3 market fields first.
     */
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
            market.volume
        );

    const marketCap =
        firstDefined(
            market.market_cap,
            market.market_cap_usd
        );

    const source =
        firstDefined(
            market.source,
            "Backend market feed"
        );

    const timestamp =
        firstDefined(
            market.timestamp,
            market.updated_at
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

    /*
     * If live endpoint provides market cap,
     * update it too.
     */
    if (
        marketCap !== null
    ) {
        setText(
            "#report-market-cap",
            formatUsd(marketCap)
        );
    }

    /*
     * Refresh 7d / high / low cards too.
     */
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
        "#market-live-status",
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

    /*
     * Positive / negative styling.
     */
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

    const liveDot =
        $("#market-live-dot");

    if (liveDot) {
        liveDot.classList.add(
            "active"
        );
    }
}


/* ============================================================
   EMPTY REPORT STATE
   ============================================================ */

function clearReportView() {
    state.latestReport = null;

    setText(
        "#report-token",
        "No analysis yet"
    );

    setText(
        "#report-outlook",
        "—"
    );

    setText(
        "#report-risk-score",
        "—"
    );

    setText(
        "#report-risk-label",
        "—"
    );

    setText(
        "#report-risk-confidence",
        "—"
    );

    setText(
        "#report-price",
        "—"
    );

    setText(
        "#report-change",
        "—"
    );

    setText(
        "#report-volume",
        "—"
    );

    setText(
        "#report-market-cap",
        "—"
    );

    setText(
        "#report-change-7d",
        "—"
    );

    setText(
        "#report-high",
        "—"
    );

    setText(
        "#report-low",
        "—"
    );

    setText(
        "#market-live-status",
        "—"
    );

    setText(
        "#market-updated",
        "—"
    );

    setText(
        "#data-source",
        "—"
    );

    setText(
        "#market-source",
        "—"
    );

    /*
     * Risk pillars.
     */
    const pillarNames = [
        "volatility",
        "liquidity",
        "market-sensitivity",
        "market_sensitivity",
        "structural",
        "contract",
        "composite"
    ];

    pillarNames.forEach(
        (name) => {
            setText(
                `#pillar-${name}-value`,
                "—"
            );

            setText(
                `#pillar-${name}-detail`,
                "—"
            );

            const bar =
                $(`#pillar-${name}-bar`);

            if (bar) {
                bar.style.width =
                    "0%";

                bar.removeAttribute(
                    "aria-valuenow"
                );
            }
        }
    );

    /*
     * Risk drivers.
     */
    const drivers =
        $("#risk-drivers");

    if (drivers) {
        drivers.replaceChildren();
    }

    /*
     * Stress.
     */
    setText(
        "#stress-beta",
        "—"
    );

    setText(
        "#stress-drawdown",
        "—"
    );

    setText(
        "#stress-resilience",
        "—"
    );

    setText(
        "#stress-confidence",
        "—"
    );

    setText(
        "#stress-verdict",
        "—"
    );

    setText(
        "#ai-stress-interpretation",
        "—"
    );

    /*
     * AI.
     */
    setText(
        "#executive-summary",
        "—"
    );

    setText(
        "#ai-market-structure",
        "—"
    );

    setText(
        "#ai-liquidity",
        "—"
    );

    setText(
        "#ai-contract-risk",
        "—"
    );

    setText(
        "#ai-evidence-status",
        "—"
    );

    const forensic =
        $("#forensic-cards");

    if (forensic) {
        forensic.replaceChildren();
    }

    /*
     * Data quality.
     */
    setText(
        "#data-confidence",
        "—"
    );

    setText(
        "#data-freshness",
        "—"
    );

    renderMissingSignals(
        []
    );

    updateCurrentReportDeleteButton();
}


/* ============================================================
   FORM HANDLER
   ============================================================ */

async function handleAnalysisSubmit(
    event
) {
    event.preventDefault();

    const input =
        $("#token-symbol");

    if (!input) {
        return;
    }

    const symbol =
        input.value
            .trim()
            .toUpperCase();

    if (!symbol) {
        showAnalysisError(
            "Enter a token symbol."
        );

        input.focus();

        return;
    }

    if (
        !/^[A-Z0-9]{2,15}$/.test(
            symbol
        )
    ) {
        showAnalysisError(
            "Enter a valid token symbol."
        );

        input.focus();

        return;
    }

    const button =
        $("#analyze-button");

    if (button) {
        button.disabled = true;

        button.dataset.originalText =
            button.textContent;

        button.textContent =
            "Analyzing…";
    }

    try {
        await runAnalysis(
            symbol
        );

    } finally {
        if (button) {
            button.disabled = false;

            button.textContent =
                button.dataset.originalText ||
                "Analyze";
        }
    }
}


/* ============================================================
   INITIALIZATION
   ============================================================ */

async function initializeDashboard() {
    /*
     * OAuth callback.
     */
    consumeQueryToken();

    state.token =
        getTokenFromStorage();

    if (!state.token) {
        redirectToHome();

        return;
    }

    await loadDashboard();
}


function initializeIndexPage() {
    const googleLinks =
        $all(
            'a[href="/api/auth/google"]'
        );

    googleLinks.forEach(
        (link) => {
            link.addEventListener(
                "click",
                () => {
                    clearAnalysisError();
                }
            );
        }
    );
}


/* ============================================================
   END OF PART 1
   ============================================================

   Part 2 contains:

   - Risk severity
   - Risk score bars
   - Risk profile
   - Pillars
   - Risk drivers
   - Stress test
   - AI report
   - Data quality
   - Complete report rendering
   - History
   - Auth
   - Keyboard UX
   - Visibility handling
   - Final initialization
   ============================================================ */


   /* ============================================================
   CryptoRisk AI — Dashboard Controller
   Part 2 / 2
   ============================================================ */


/* ============================================================
   RISK SEVERITY
   ============================================================ */

function normalizeSeverity(
    value
) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "Unavailable";
    }

    const text =
        String(value)
            .trim()
            .toLowerCase();

    if (
        text.includes("critical")
    ) {
        return "Critical";
    }

    if (
        text.includes("high") ||
        text.includes("elevated")
    ) {
        return "High";
    }

    if (
        text.includes("moderate") ||
        text.includes("medium")
    ) {
        return "Moderate";
    }

    if (
        text.includes("low") ||
        text.includes("minimal")
    ) {
        return "Low";
    }

    if (
        text.includes("unavailable")
    ) {
        return "Unavailable";
    }

    return String(value);
}


function severityClass(
    severity
) {
    const normalized =
        normalizeSeverity(
            severity
        ).toLowerCase();

    if (
        normalized === "critical"
    ) {
        return "risk-critical";
    }

    if (
        normalized === "high"
    ) {
        return "risk-high";
    }

    if (
        normalized === "moderate"
    ) {
        return "risk-moderate";
    }

    if (
        normalized === "low"
    ) {
        return "risk-low";
    }

    return "";
}


function applyRiskClass(
    element,
    severity
) {
    if (!element) {
        return;
    }

    element.classList.remove(
        "risk-low",
        "risk-moderate",
        "risk-high",
        "risk-critical"
    );

    const className =
        severityClass(
            severity
        );

    if (className) {
        element.classList.add(
            className
        );
    }
}


/* ============================================================
   RISK SCORE BAR
   ============================================================ */

function updateScoreBar(
    bar,
    score
) {
    if (!bar) {
        return;
    }

    const numericScore =
        clampScore(score);

    /*
     * Missing score:
     * empty bar, NOT 0/100.
     */
    if (
        numericScore === null
    ) {
        bar.style.width =
            "0%";

        bar.removeAttribute(
            "aria-valuenow"
        );

        return;
    }

    bar.style.width =
        `${numericScore}%`;

    bar.setAttribute(
        "aria-valuenow",
        String(
            Math.round(
                numericScore
            )
        )
    );
}


/* ============================================================
   MARKET RENDERING
   ============================================================ */

function renderMarket(
    report
) {
    const market =
        getMarket(report);

    const asset =
        report?.asset || {};

    /*
     * EXACT BACKEND SCHEMA 3.0
     *
     * Primary keys first, with legacy aliases as fallbacks
     * so older persisted reports still render.
     */
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

    const source =
        firstDefined(
            market.source,
            "Backend market feed"
        );

    const timestamp =
        firstDefined(
            market.timestamp,
            market.updated_at
        );

    /*
     * Token
     */
    setText(
        "#report-token",
        firstDefined(
            asset.symbol,
            report.token_symbol
        )
    );

    /*
     * Price
     */
    setText(
        "#report-price",
        formatUsd(price)
    );

    /*
     * 24h change
     */
    setText(
        "#report-change",
        formatPercent(change24)
    );

    /*
     * Volume
     */
    setText(
        "#report-volume",
        formatUsd(volume)
    );

    /*
     * Market cap
     */
    setText(
        "#report-market-cap",
        formatUsd(marketCap)
    );

    /*
     * 7D change / 24h high / 24h low.
     *
     * Backend Schema 3.0 provides these through:
     *   market.price_change_7d_pct
     *   market.high_24h
     *   market.low_24h
     */
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
     * Change styling.
     */
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

    /*
     * Metadata.
     */
    setText(
        "#market-live-status",
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
        firstDefined(
            source,
            "Backend market feed"
        )
    );

    setText(
        "#market-source",
        firstDefined(
            source,
            "Backend market feed"
        )
    );
}


/* ============================================================
   MAIN RISK PROFILE
   ============================================================ */

function renderRiskProfile(
    report
) {
    const risk =
        getRiskProfile(report);

    /*
     * EXACT:
     *
     * risk_profile.composite_score
     * risk_profile.label
     * risk_profile.confidence
     */
    const compositeScore =
        firstDefined(
            risk.composite_score,
            report.risk_score
        );

    const rawLabel =
        firstDefined(
            risk.label,
            report.risk_label
        );

    const label =
        normalizeSeverity(
            rawLabel
        );

    const confidence =
        firstDefined(
            risk.confidence,
            report.risk_confidence
        );

    /*
     * Main score.
     */
    setText(
        "#report-risk-score",
        compositeScore !== null
            ? `${formatScore(
                  compositeScore
              )}/100`
            : "—"
    );

    /*
     * Main label.
     */
    setText(
        "#report-risk-label",
        label
    );

    /*
     * OUTLOOK:
     *
     * Exact backend:
     * report.outlook
     */
    setText(
        "#report-outlook",
        firstDefined(
            report.outlook,
            report.risk_label,
            risk.label
        )
    );

    /*
     * Confidence.
     */
    setText(
        "#report-risk-confidence",
        formatConfidence(
            confidence
        )
    );

    /*
     * Styling.
     */
    applyRiskClass(
        $("#report-risk-score"),
        rawLabel
    );

    applyRiskClass(
        $("#report-risk-label"),
        rawLabel
    );

    applyRiskClass(
        $("#report-outlook"),
        report.outlook || rawLabel
    );


    /* ========================================================
       VOLATILITY
       ======================================================== */

    renderPillar(
        "volatility",
        getPillar(
            report,
            "volatility"
        )
    );


    /* ========================================================
       LIQUIDITY
       ======================================================== */

    renderPillar(
        "liquidity",
        getPillar(
            report,
            "liquidity"
        )
    );


    /* ========================================================
       MARKET SENSITIVITY
       ======================================================== */

    const marketSensitivity =
        getPillar(
            report,
            "market_sensitivity"
        );

    /*
     * Most likely HTML:
     *
     * pillar-market-sensitivity-value
     */
    renderPillar(
        "market-sensitivity",
        marketSensitivity
    );

    /*
     * Also support:
     *
     * pillar-market_sensitivity-value
     */
    renderPillar(
        "market_sensitivity",
        marketSensitivity
    );


    /* ========================================================
       STRUCTURAL
       ======================================================== */

    const structural =
        getPillar(
            report,
            "structural"
        );

    /*
     * Correct backend name.
     */
    renderPillar(
        "structural",
        structural
    );

    /*
     * Backward compatibility:
     * old HTML may call structural "contract".
     */
    renderPillar(
        "contract",
        structural
    );


    /* ========================================================
       COMPOSITE
       ======================================================== */

    renderPillar(
        "composite",
        {
            score:
                compositeScore,

            label:
                rawLabel,

            confidence:
                confidence,

            detail:
                "Combined evidence-based risk score."
        }
    );
}


/* ============================================================
   RISK PILLARS
   ============================================================ */

function renderPillar(
    name,
    pillar
) {
    if (
        !pillar ||
        typeof pillar !== "object"
    ) {
        return;
    }

    /*
     * EXACT:
     *
     * pillar.score
     */
    const score =
        pillar.score;

    /*
     * EXACT:
     *
     * pillar.label
     */
    const label =
        normalizeSeverity(
            pillar.label
        );

    const valueElement =
        $(`#pillar-${name}-value`);

    const barElement =
        $(`#pillar-${name}-bar`);

    const detailElement =
        $(`#pillar-${name}-detail`);

    /*
     * Score.
     */
    if (valueElement) {
        if (
            score === null ||
            score === undefined ||
            score === ""
        ) {
            /*
             * IMPORTANT:
             * unavailable != 0
             */
            valueElement.textContent =
                "N/A";
        } else {
            valueElement.textContent =
                `${formatScore(
                    score
                )}/100`;
        }

        applyRiskClass(
            valueElement,
            pillar.label
        );
    }

    /*
     * Bar.
     */
    if (barElement) {
        updateScoreBar(
            barElement,
            score
        );

        applyRiskClass(
            barElement,
            pillar.label
        );
    }

    /*
     * Detail.
     */
    if (detailElement) {
        detailElement.textContent =
            buildPillarDetail(
                name,
                pillar
            );
    }
}


/* ============================================================
   PILLAR DETAIL
   ============================================================ */

function buildPillarDetail(
    name,
    pillar
) {
    /*
     * Guard against a missing / malformed pillar so the
     * description text is never broken.
     */
    if (
        !pillar ||
        typeof pillar !== "object"
    ) {
        return firstDefined(
            name &&
                generatePillarFallbackDetail(
                    name,
                    null
                ),
            "Signal unavailable."
        );
    }

    /*
     * Backend's exact explanation.
     */
    if (
        pillar.detail !== null &&
        pillar.detail !== undefined &&
        pillar.detail !== ""
    ) {
        return String(
            pillar.detail
        );
    }

    /*
     * If unavailable.
     */
    if (
        pillar.score === null ||
        pillar.score === undefined
    ) {
        return firstDefined(
            pillar.label,
            generatePillarFallbackDetail(
                name,
                null
            ),
            "Signal unavailable."
        );
    }

    return generatePillarFallbackDetail(
        name,
        pillar.score
    );
}


function generatePillarFallbackDetail(
    name,
    score
) {
    const descriptions = {
        volatility:
            "Volatility risk contribution.",

        liquidity:
            "Liquidity and exit-risk contribution.",

        "market-sensitivity":
            "Market sensitivity contribution.",

        market_sensitivity:
            "Market sensitivity contribution.",

        structural:
            "Structural risk contribution.",

        contract:
            "Structural risk contribution.",

        composite:
            "Combined evidence-based risk score."
    };

    const missingDescriptions = {
        liquidity:
            "Liquidity signal unavailable — no volume or market-cap data to estimate exit risk.",

        "market-sensitivity":
            "Market sensitivity signal unavailable — no BTC beta could be calculated.",

        market_sensitivity:
            "Market sensitivity signal unavailable — no BTC beta could be calculated.",

        volatility:
            "Volatility signal unavailable — insufficient price history.",

        structural:
            "Structural signal unavailable — no contract/security data.",

        contract:
            "Structural signal unavailable — no contract/security data."
    };

    if (
        score === null ||
        score === undefined
    ) {
        return (
            missingDescriptions[name] ||
            descriptions[name] ||
            "Signal unavailable."
        );
    }

    return (
        descriptions[name] ||
        "Risk contribution."
    );
}


/* ============================================================
   RISK DRIVERS
   ============================================================ */

function renderRiskDrivers(
    report
) {
    const container =
        $("#risk-drivers");

    if (!container) {
        return;
    }

    container.replaceChildren();

    const drivers =
        Array.isArray(
            report?.risk_drivers
        )
            ? report.risk_drivers
            : [];

    if (!drivers.length) {
        const empty =
            document.createElement(
                "div"
            );

        empty.className =
            "empty-state";

        empty.textContent =
            "No material risk drivers were returned.";

        container.appendChild(
            empty
        );

        return;
    }

    drivers.forEach(
        (driver, index) => {
            const card =
                document.createElement(
                    "article"
                );

            card.className =
                "risk-driver-card";

            const heading =
                document.createElement(
                    "h4"
                );

            const badge =
                document.createElement(
                    "span"
                );

            const body =
                document.createElement(
                    "p"
                );

            /*
             * EXACT:
             * driver.title
             */
            heading.textContent =
                firstDefined(
                    driver?.title,
                    `Risk driver ${index + 1}`
                );

            /*
             * EXACT:
             * driver.severity
             */
            badge.textContent =
                normalizeSeverity(
                    driver?.severity
                );

            badge.className =
                "risk-badge";

            applyRiskClass(
                badge,
                driver?.severity
            );

            /*
             * EXACT:
             * driver.detail
             */
            body.textContent =
                firstDefined(
                    driver?.detail,
                    "No additional detail was provided."
                );

            card.appendChild(
                heading
            );

            card.appendChild(
                badge
            );

            card.appendChild(
                body
            );

            container.appendChild(
                card
            );
        }
    );
}


/* ============================================================
   STRESS TEST
   ============================================================ */

function getExpectedDrawdown(
    stress
) {
    const stressObj =
        stress || {};

    /*
     * Backend Schema 3.0:
     * stress_test.expected_drawdown_pct
     * stress_test.drawdown_pct
     */
    const expected =
        firstDefined(
            stressObj.expected_drawdown_pct,
            stressObj.drawdown_pct,
            stressObj.max_drawdown_pct,
            stressObj.expected_downside_pct
        );

    if (expected !== null) {
        return expected;
    }

    /*
     * Older payloads expose the -10% BTC shock scenario.
     * Derive the expected drawdown from that scenario's
     * estimated asset move.
     */
    const base =
        stressObj.base_scenario || {};

    if (
        typeof base === "object" &&
        base !== null
    ) {
        const move =
            firstDefined(
                base.estimated_asset_move_pct,
                base.asset_move_pct,
                base.drawdown_pct
            );

        const numericMove =
            Number(move);

        if (
            Number.isFinite(
                numericMove
            )
        ) {
            return Math.abs(
                numericMove
            );
        }
    }

    return null;
}


function getResilienceLabel(
    stress
) {
    const stressObj =
        stress || {};

    const label =
        firstDefined(
            stressObj.resilience_label,
            stressObj.resilience,
            stressObj.resilience_status
        );

    if (label !== null) {
        return label;
    }

    /*
     * Derive a label from the base scenario's resilience
     * score so the card is never left as a dash.
     */
    const base =
        stressObj.base_scenario || {};

    const rawScore =
        firstDefined(
            base.resilience_score,
            stressObj.resilience_score
        );

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

    return null;
}


function getStressConfidence(
    report,
    stress
) {
    const stressObj =
        stress || {};

    const reportObj =
        report || {};

    return firstDefined(
        stressObj.confidence,
        reportObj.risk_confidence,
        reportObj.ai?.confidence,
        reportObj.risk_profile?.confidence
    );
}


function renderStressTest(
    report
) {
    const stress =
        getStress(report);

    /*
     * EXACT:
     * stress_test.beta
     */
    setText(
        "#stress-beta",
        formatNumber(
            stress.beta,
            3
        )
    );

    /*
     * EXACT:
     * stress_test.beta
     */
    setText(
        "#stress-beta",
        formatNumber(
            firstDefined(
                stress.beta,
                stress.beta_to_btc,
                report?.quantitative?.beta?.beta,
                report?.quantitative?.beta
            ),
            3
        )
    );

    /*
     * EXACT:
     * stress_test.expected_drawdown_pct
     */
    setText(
        "#stress-drawdown",
        formatPercent(
            getExpectedDrawdown(stress)
        )
    );

    /*
     * EXACT:
     * stress_test.resilience_label
     */
    setText(
        "#stress-resilience",
        getResilienceLabel(stress)
    );

    /*
     * EXACT:
     * stress_test.confidence
     */
    setText(
        "#stress-confidence",
        formatConfidence(
            getStressConfidence(
                report,
                stress
            )
        )
    );

    /*
     * EXACT:
     * stress_test.verdict
     */
    setText(
        "#stress-verdict",
        firstDefined(
            stress.verdict,
            stress.interpretation,
            stress.stress_interpretation,
            "Scenario analysis unavailable."
        )
    );

    /*
     * Styling.
     */
    applyRiskClass(
        $("#stress-resilience"),
        stress.resilience_label
    );

    /*
     * AI interpretation is separate.
     */
    setText(
        "#ai-stress-interpretation",
        getAI(report).stress_interpretation
    );
}


/* ============================================================
   AI REPORT
   ============================================================ */

function renderAI(
    report
) {
    const ai =
        getAI(report);

    const security =
        getSecurity(report);

    const quality =
        getDataQuality(report);

    /*
     * ========================================================
     * EXECUTIVE SUMMARY
     * ========================================================
     */
    setText(
        "#executive-summary",
        firstDefined(
            ai.executive_summary,
            "No executive summary was returned."
        )
    );


    /*
     * ========================================================
     * MARKET / STRUCTURE INTERPRETATION
     * ========================================================
     */
    setText(
        "#ai-market-structure",
        firstDefined(
            ai.what_matters_now,
            ai.primary_risk_driver,
            ai.risk_regime,
            "No market interpretation available."
        )
    );


    /*
     * ========================================================
     * WATCH / MONITORING
     * ========================================================
     *
     * This is NOT falsely labelled as a dedicated
     * liquidity calculation.
     */
    setText(
        "#ai-liquidity",
        firstDefined(
            ai.watch_next,
            "No monitoring guidance returned."
        )
    );


    /*
     * ========================================================
     * SECURITY
     * ========================================================
     */
    const securityFlags =
        Array.isArray(
            security.red_flags
        )
            ? security.red_flags
            : [];

    let securityText =
        firstDefined(
            security.status,
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
                .join(
                    " • "
                );
    }

    setText(
        "#ai-contract-risk",
        securityText
    );

    applyRiskClass(
        $("#ai-contract-risk"),
        security.status
    );


    /*
     * ========================================================
     * EVIDENCE STATUS
     * ========================================================
     *
     * There is NO report.evidence array in
     * the supplied v3 schema.
     */
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

    if (
        !hasExecutiveSummary
    ) {
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


    /*
     * ========================================================
     * DIRECT AI FIELDS
     * ========================================================
     *
     * These are optional HTML elements.
     * If they don't exist, setText simply does nothing.
     */
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


    /*
     * Intelligence cards.
     */
    renderForensicCards(
        report
    );
}


/* ============================================================
   FORENSIC / INTELLIGENCE CARDS
   ============================================================ */

function renderForensicCards(
    report
) {
    const container =
        $("#forensic-cards");

    if (!container) {
        return;
    }

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
                String(
                    item.value
                );

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

function renderDataQuality(
    report
) {
    const quality =
        getDataQuality(report);

    const reportObj =
        report || {};

    /*
     * EXACT:
     * data_quality.confidence
     *
     * Fallback chain so the Data Confidence card never
     * falls back to a dash when the nested object is empty.
     */
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

    /*
     * Source belongs to market.
     */
    setText(
        "#market-source",
        firstDefined(
            reportObj?.market?.source,
            quality.source,
            "Backend market feed"
        )
    );

    /*
     * Timestamp belongs to market.
     */
    const timestamp =
        reportObj?.market?.timestamp;

    setText(
        "#data-freshness",
        timestamp
            ? formatRelativeTime(
                  timestamp
              )
            : "Unknown"
    );

    /*
     * Exact:
     * data_quality.missing_signals
     */
    renderMissingSignals(
        firstDefined(
            quality.missing_signals,
            quality.missing,
            []
        )
    );
}


/* ============================================================
   MISSING SIGNALS
   ============================================================ */

function renderMissingSignals(
    missing
) {
    const container =
        $("#missing-signals");

    if (!container) {
        return;
    }

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
                    String(signal).trim() !== ""
            );
    } else if (
        typeof missing === "string" &&
        missing.trim()
    ) {
        signals = [
            missing
        ];
    }

    /*
     * No missing signals.
     */
    if (!signals.length) {
        const item =
            document.createElement(
                "span"
            );

        item.className =
            "data-ok";

        item.textContent =
            "No major missing signals reported.";

        container.appendChild(
            item
        );

        return;
    }

    /*
     * Missing signals.
     */
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


/* ============================================================
   COMPLETE REPORT RENDERER
   ============================================================ */

function renderReport(
    report
) {
    if (
        !report ||
        typeof report !== "object"
    ) {
        clearReportView();

        return;
    }

    /*
     * Debugging:
     * this lets us confirm exactly what reached
     * the renderer.
     */
    console.log(
        "Rendering CryptoRisk report:",
        report
    );

    /*
     * Store.
     */
    state.latestReport =
        report;

    /*
     * Token.
     */
    state.currentSymbol =
        firstDefined(
            report?.asset?.symbol,
            report?.token_symbol,
            state.currentSymbol
        );

    /*
     * Render every section.
     */
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

    /*
     * Optional generated timestamp.
     */
    if (
        report.generated_at
    ) {
        const generated =
            document.querySelector(
                "[data-report-generated]"
            );

        if (generated) {
            generated.textContent =
                formatDate(
                    report.generated_at
                );
        }
    }
}


/* ============================================================
   DELETE BUTTON STATE
   ============================================================ */

function updateCurrentReportDeleteButton() {
    const button =
        $("#delete-current-report");

    if (!button) {
        return;
    }

    button.disabled =
        !state.currentReportId;
}


/* ============================================================
   HISTORY TABLE
   ============================================================ */

function renderHistory(
    history
) {
    const tbody =
        $("#history-tbody");

    if (!tbody) {
        return;
    }

    tbody.replaceChildren();

    const records =
        Array.isArray(history)
            ? history
            : [];

    setText(
        "#history-count",
        String(
            records.length
        )
    );

    if (!records.length) {
        const row =
            document.createElement(
                "tr"
            );

        const cell =
            document.createElement(
                "td"
            );

        cell.colSpan = 6;

        cell.className =
            "empty-history";

        cell.textContent =
            "No analyses yet.";

        row.appendChild(
            cell
        );

        tbody.appendChild(
            row
        );

        return;
    }

    records.forEach(
        (record) => {
            const row =
                document.createElement(
                    "tr"
                );

            row.dataset.reportId =
                String(
                    record.id
                );

            /*
             * Asset
             */
            const assetCell =
                createHistoryCell(
                    firstDefined(
                        record.token_symbol,
                        record.asset?.symbol,
                        record.symbol,
                        "—"
                    )
                );

            /*
             * Risk
             */
            const riskCell =
                document.createElement(
                    "td"
                );

            const riskValue =
                firstDefined(
                    record.risk_label,
                    record.risk_severity,
                    record.label
                );

            const risk =
                normalizeSeverity(
                    riskValue
                );

            const riskBadge =
                document.createElement(
                    "span"
                );

            riskBadge.className =
                "risk-badge";

            riskBadge.textContent =
                risk;

            applyRiskClass(
                riskBadge,
                risk
            );

            riskCell.appendChild(
                riskBadge
            );

            /*
             * Outlook
             */
            const outlookCell =
                createHistoryCell(
                    firstDefined(
                        record.outlook,
                        record.trend,
                        "—"
                    )
                );

            /*
             * Score
             */
            const score =
                firstDefined(
                    record.risk_score,
                    record.composite_score
                );

            const scoreCell =
                createHistoryCell(
                    score !== null
                        ? `${formatScore(
                              score
                          )}/100`
                        : "—"
                );

            /*
             * Date
             */
            const dateValue =
                firstDefined(
                    record.created_at,
                    record.timestamp,
                    record.generated_at
                );

            const dateCell =
                createHistoryCell(
                    dateValue
                        ? formatDate(
                              dateValue
                          )
                        : "—"
                );

            /*
             * Actions
             */
            const actionCell =
                document.createElement(
                    "td"
                );

            const viewButton =
                document.createElement(
                    "button"
                );

            viewButton.type =
                "button";

            viewButton.className =
                "history-view";

            viewButton.textContent =
                "View";

            viewButton.dataset.action =
                "view-history";

            viewButton.dataset.id =
                String(
                    record.id
                );

            const deleteButton =
                document.createElement(
                    "button"
                );

            deleteButton.type =
                "button";

            deleteButton.className =
                "history-delete";

            deleteButton.textContent =
                "Delete";

            deleteButton.dataset.action =
                "delete-history";

            deleteButton.dataset.id =
                String(
                    record.id
                );

            actionCell.appendChild(
                viewButton
            );

            actionCell.appendChild(
                deleteButton
            );

            /*
             * Row.
             */
            row.appendChild(
                assetCell
            );

            row.appendChild(
                riskCell
            );

            row.appendChild(
                outlookCell
            );

            row.appendChild(
                scoreCell
            );

            row.appendChild(
                dateCell
            );

            row.appendChild(
                actionCell
            );

            tbody.appendChild(
                row
            );
        }
    );
}


function createHistoryCell(
    value
) {
    const cell =
        document.createElement(
            "td"
        );

    cell.textContent =
        value === null ||
        value === undefined ||
        value === ""
            ? "—"
            : String(value);

    return cell;
}


/* ============================================================
   HISTORY EVENT DELEGATION
   ============================================================ */

function handleHistoryClick(
    event
) {
    const target =
        event.target.closest(
            "[data-action]"
        );

    if (!target) {
        return;
    }

    const action =
        target.dataset.action;

    const id =
        target.dataset.id;

    if (!id) {
        return;
    }

    event.preventDefault();

    event.stopPropagation();

    if (
        action ===
        "view-history"
    ) {
        loadHistoryReport(
            id
        );

        return;
    }

    if (
        action ===
        "delete-history"
    ) {
        deleteReport(
            id
        );
    }
}


/* ============================================================
   LOGIN / SIGNUP
   ============================================================ */

async function handleAuthForm(
    event
) {
    const form =
        event.currentTarget;

    event.preventDefault();

    const action =
        form.dataset.auth;

    if (
        action !== "login" &&
        action !== "signup"
    ) {
        return;
    }

    const email =
        form.querySelector(
            "[name='email']"
        )?.value
            ?.trim();

    const password =
        form.querySelector(
            "[name='password']"
        )?.value;

    const username =
        form.querySelector(
            "[name='username']"
        )?.value
            ?.trim();

    if (
        !email ||
        !password
    ) {
        showAnalysisError(
            "Email and password are required."
        );

        return;
    }

    const endpoint =
        action === "signup"
            ? "/api/auth/signup"
            : "/api/auth/login";

    const body =
        action === "signup"
            ? {
                  username,
                  email,
                  password
              }
            : {
                  email,
                  password
              };

    try {
        const payload =
            await apiRequest(
                endpoint,
                {
                    method: "POST",
                    body
                }
            );

        const token =
            firstDefined(
                payload.token,
                payload.access_token
            );

        if (!token) {
            throw new Error(
                "Authentication succeeded but no session token was returned."
            );
        }

        saveToken(
            token
        );

        window.location.href =
            "/dashboard";

    } catch (error) {
        showAnalysisError(
            error.message ||
            "Authentication failed."
        );
    }
}


/* ============================================================
   KEYBOARD UX
   ============================================================ */

function setupKeyboardShortcuts() {
    document.addEventListener(
        "keydown",
        (event) => {
            if (
                event.key !== "/" ||
                event.ctrlKey ||
                event.metaKey ||
                event.altKey
            ) {
                return;
            }

            const active =
                document.activeElement;

            const isTyping =
                active &&
                (
                    active.tagName ===
                        "INPUT" ||
                    active.tagName ===
                        "TEXTAREA" ||
                    active.isContentEditable
                );

            if (isTyping) {
                return;
            }

            const input =
                $("#token-symbol");

            if (!input) {
                return;
            }

            event.preventDefault();

            input.focus();
        }
    );
}


/* ============================================================
   PAGE VISIBILITY
   ============================================================ */

function setupVisibilityHandling() {
    document.addEventListener(
        "visibilitychange",
        () => {
            if (
                document.hidden
            ) {
                stopLivePolling();

                return;
            }

            if (
                state.currentSymbol &&
                state.token
            ) {
                startLivePolling(
                    state.currentSymbol
                );
            }
        }
    );
}


/* ============================================================
   BEFORE UNLOAD
   ============================================================ */

window.addEventListener(
    "beforeunload",
    () => {
        stopLivePolling();
    }
);


/* ============================================================
   FINAL DOM INITIALIZATION
   ============================================================ */

document.addEventListener(
    "DOMContentLoaded",
    () => {
        /*
         * Analysis form.
         */
        const analysisForm =
            $("#analysis-form");

        if (analysisForm) {
            analysisForm.addEventListener(
                "submit",
                handleAnalysisSubmit
            );
        }

        /*
         * Logout buttons.
         */
        const logoutButtons =
            $all(
                "[data-action='logout'], #logout-button"
            );

        logoutButtons.forEach(
            (button) => {
                button.addEventListener(
                    "click",
                    (event) => {
                        event.preventDefault();

                        logout();
                    }
                );
            }
        );

        /*
         * Current report delete.
         */
        const deleteButton =
            $("#delete-current-report");

        if (deleteButton) {
            deleteButton.addEventListener(
                "click",
                async () => {
                    await deleteCurrentReport();
                }
            );
        }

        /*
         * History delegation.
         */
        const historyBody =
            $("#history-tbody");

        if (historyBody) {
            historyBody.addEventListener(
                "click",
                handleHistoryClick
            );
        }

        /*
         * Login/signup forms.
         */
        $all(
            "form[data-auth]"
        ).forEach(
            (form) => {
                form.addEventListener(
                    "submit",
                    handleAuthForm
                );
            }
        );

        /*
         * Keyboard shortcuts.
         */
        setupKeyboardShortcuts();

        /*
         * Visibility-aware polling.
         */
        setupVisibilityHandling();

        /*
         * Determine page.
         */
        if (
            document.querySelector(
                "#analysis-form"
            )
        ) {
            initializeDashboard();
        } else {
            initializeIndexPage();
        }
    }
);


/* ============================================================
   GLOBAL ERROR SAFETY
   ============================================================ */

window.addEventListener(
    "error",
    (event) => {
        console.error(
            "Frontend error:",
            event.error ||
            event.message
        );
    }
);


window.addEventListener(
    "unhandledrejection",
    (event) => {
        console.error(
            "Unhandled promise rejection:",
            event.reason
        );
    }
);


/* ============================================================
   END OF SCRIPT
   ============================================================ */