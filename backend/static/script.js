"use strict";

/*
 * CryptoRisk AI — Dashboard Controller
 * Part 1 / 2
 *
 * Rules:
 * - Same-origin backend
 * - No config.js
 * - No direct CoinGecko/browser market API calls
 * - Backend is the single source of truth for risk calculations
 * - Gemini output is treated as backend-generated report data
 */

const API = {
    dashboard: "/api/dashboard",
    analyze: "/api/analyze",
    logout: "/api/auth/logout",
    me: "/api/auth/me",
    market: (symbol) => `/api/market/${encodeURIComponent(symbol)}`,
    history: (id) => `/api/history/${encodeURIComponent(id)}`,
    deleteHistory: (id) => `/api/history/${encodeURIComponent(id)}`
};

const STORAGE_KEYS = {
    token: "token"
};

const state = {
    token: null,
    user: null,
    latestReport: null,
    currentReportId: null,
    currentSymbol: null,
    livePollTimer: null,
    isAnalyzing: false
};


/* =========================================================
   DOM HELPERS
   ========================================================= */

function $(selector) {
    return document.querySelector(selector);
}

function $all(selector) {
    return Array.from(document.querySelectorAll(selector));
}

function setText(selector, value, fallback = "—") {
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

function setHTML(selector, html) {
    const element = $(selector);

    if (element) {
        element.innerHTML = html;
    }
}

function show(element) {
    if (!element) return;

    element.hidden = false;
    element.style.display = "";
}

function hide(element) {
    if (!element) return;

    element.hidden = true;
    element.style.display = "none";
}

function toggle(element, visible) {
    if (visible) {
        show(element);
    } else {
        hide(element);
    }
}


/* =========================================================
   AUTH
   ========================================================= */

function getTokenFromStorage() {
    return localStorage.getItem(STORAGE_KEYS.token);
}

function saveToken(token) {
    if (!token) {
        return;
    }

    state.token = token;
    localStorage.setItem(STORAGE_KEYS.token, token);
}

function clearToken() {
    state.token = null;
    localStorage.removeItem(STORAGE_KEYS.token);
}

function consumeQueryToken() {
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token");

    if (token) {
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

    return null;
}

function getAuthHeaders() {
    const token = state.token || getTokenFromStorage();

    if (!token) {
        return {};
    }

    return {
        Authorization: `Bearer ${token}`
    };
}

function redirectToHome() {
    clearToken();
    stopLivePolling();

    window.location.href = "/";
}


/* =========================================================
   API REQUEST LAYER
   ========================================================= */

async function apiRequest(
    url,
    options = {}
) {
    const headers = {
        Accept: "application/json",
        ...(options.headers || {}),
        ...getAuthHeaders()
    };

    if (
        options.body &&
        typeof options.body !== "string"
    ) {
        headers["Content-Type"] = "application/json";

        options = {
            ...options,
            body: JSON.stringify(options.body)
        };
    }

    let response;

    try {
        response = await fetch(url, {
            ...options,
            headers
        });
    } catch (error) {
        throw new Error(
            "Unable to connect to the CryptoRisk backend."
        );
    }

    let payload = null;

    const contentType =
        response.headers.get("content-type") || "";

    if (contentType.includes("application/json")) {
        try {
            payload = await response.json();
        } catch {
            payload = null;
        }
    } else {
        try {
            const text = await response.text();

            if (text) {
                payload = {
                    message: text
                };
            }
        } catch {
            payload = null;
        }
    }

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


/* =========================================================
   ERROR UI
   ========================================================= */

function showAnalysisError(message) {
    const element = $("#analysis-error");

    if (!element) {
        return;
    }

    element.textContent =
        message || "Something went wrong.";

    show(element);
}

function clearAnalysisError() {
    const element = $("#analysis-error");

    if (!element) {
        return;
    }

    element.textContent = "";
    hide(element);
}


/* =========================================================
   USER UI
   ========================================================= */

function renderUser(user) {
    if (!user) {
        return;
    }

    state.user = user;

    const displayName =
        user.username ||
        user.name ||
        user.email ||
        "User";

    setText(".user-name", displayName);
    setText(".user-email", user.email || "");

    const avatars = $all(".user-avatar");

    avatars.forEach((avatar) => {
        if (user.avatar_url) {
            avatar.src = user.avatar_url;
            avatar.alt = displayName;
        } else {
            avatar.removeAttribute("src");
            avatar.alt = displayName;
        }
    });
}


/* =========================================================
   PROGRESS SYSTEM
   ========================================================= */

const PROGRESS_STAGES = {
    market: {
        percent: 20,
        title: "Fetching live market data"
    },

    model: {
        percent: 45,
        title: "Running quantitative risk engine"
    },

    stress: {
        percent: 65,
        title: "Running stress scenarios"
    },

    ai: {
        percent: 82,
        title: "Synthesizing evidence"
    },

    save: {
        percent: 96,
        title: "Saving intelligence report"
    },

    complete: {
        percent: 100,
        title: "Analysis complete"
    }
};

function setProgressStage(stage) {
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

    const fill = $("#progress-fill");

    if (fill) {
        fill.style.width = `${config.percent}%`;
    }

    $all(".progress-status").forEach((element) => {
        element.classList.remove(
            "active",
            "complete"
        );

        const stageName =
            element.dataset.stage;

        if (stageName === stage) {
            element.classList.add("active");
        }
    });

    const stageOrder = [
        "market",
        "model",
        "stress",
        "ai",
        "save"
    ];

    const currentIndex =
        stageOrder.indexOf(stage);

    if (currentIndex >= 0) {
        $all(".progress-status").forEach(
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
}

function startProgress() {
    const overlay = $("#analysis-progress");

    if (!overlay) {
        return;
    }

    show(overlay);

    setProgressStage("market");
}

function finishProgress() {
    const overlay = $("#analysis-progress");

    if (!overlay) {
        return;
    }

    setProgressStage("complete");

    setTimeout(() => {
        hide(overlay);
    }, 350);
}


/* =========================================================
   FORMATTERS
   ========================================================= */

function formatNumber(
    value,
    decimals = 2
) {
    const number = Number(value);

    if (!Number.isFinite(number)) {
        return "—";
    }

    return number.toLocaleString(
        undefined,
        {
            maximumFractionDigits: decimals
        }
    );
}

function formatUsd(value) {
    const number = Number(value);

    if (!Number.isFinite(number)) {
        return "—";
    }

    if (Math.abs(number) >= 1_000_000_000) {
        return `$${formatNumber(
            number / 1_000_000_000,
            2
        )}B`;
    }

    if (Math.abs(number) >= 1_000_000) {
        return `$${formatNumber(
            number / 1_000_000,
            2
        )}M`;
    }

    if (Math.abs(number) >= 1_000) {
        return `$${formatNumber(
            number / 1_000,
            2
        )}K`;
    }

    if (Math.abs(number) >= 1) {
        return `$${formatNumber(
            number,
            2
        )}`;
    }

    return `$${number.toFixed(6)}`;
}

function formatPercent(value) {
    const number = Number(value);

    if (!Number.isFinite(number)) {
        return "—";
    }

    const sign =
        number > 0
            ? "+"
            : "";

    return `${sign}${number.toFixed(2)}%`;
}

function formatScore(value) {
    const number = Number(value);

    if (!Number.isFinite(number)) {
        return "—";
    }

    return Math.round(number);
}

function formatDate(value) {
    if (!value) {
        return "—";
    }

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
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

function formatRelativeTime(value) {
    if (!value) {
        return "—";
    }

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return formatDate(value);
    }

    const seconds =
        Math.floor(
            (Date.now() - date.getTime()) /
            1000
        );

    if (seconds < 10) {
        return "just now";
    }

    if (seconds < 60) {
        return `${seconds}s ago`;
    }

    const minutes =
        Math.floor(seconds / 60);

    if (minutes < 60) {
        return `${minutes}m ago`;
    }

    const hours =
        Math.floor(minutes / 60);

    if (hours < 24) {
        return `${hours}h ago`;
    }

    return `${Math.floor(hours / 24)}d ago`;
}

function clampScore(value) {
    const number = Number(value);

    if (!Number.isFinite(number)) {
        return 0;
    }

    return Math.max(
        0,
        Math.min(100, number)
    );
}


/* =========================================================
   SAFE DATA HELPERS
   ========================================================= */

function firstDefined(...values) {
    for (const value of values) {
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

function getReportFromPayload(payload) {
    if (!payload) {
        return null;
    }

    return (
        payload.analysis ||
        payload.latest?.report ||
        payload.latest ||
        null
    );
}

function getRiskProfile(report) {
    return report?.risk_profile || {};
}

function getPillar(
    report,
    name
) {
    return (
        report?.risk_profile?.pillars?.[name] ||
        {}
    );
}

function getAI(report) {
    return report?.ai || {};
}

function getMarket(report) {
    return report?.market || {};
}

function getSecurity(report) {
    return report?.security || {};
}

function getStress(report) {
    return report?.stress_test || {};
}


/* =========================================================
   DASHBOARD LOAD
   ========================================================= */

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

        renderUser(payload.user);

        const latest =
            payload.latest;

        if (latest) {
            const report =
                latest.report ||
                latest;

            state.latestReport = report;
            state.currentReportId =
                latest.id ||
                report.id ||
                null;

            state.currentSymbol =
                report?.asset?.symbol ||
                latest.token_symbol ||
                null;

            renderReport(report);

            if (state.currentSymbol) {
                startLivePolling(
                    state.currentSymbol
                );
            }
        } else {
            clearReportView();
        }

        renderHistory(
            payload.history || []
        );
    } catch (error) {
        console.error(
            "Dashboard load failed:",
            error
        );

        showAnalysisError(
            error.message
        );
    }
}


/* =========================================================
   ANALYSIS
   ========================================================= */

async function runAnalysis(symbol) {
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

    try {
        setProgressStage("market");

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

        setProgressStage("model");

        await new Promise(
            (resolve) =>
                setTimeout(resolve, 150)
        );

        setProgressStage("stress");

        await new Promise(
            (resolve) =>
                setTimeout(resolve, 150)
        );

        setProgressStage("ai");

        await new Promise(
            (resolve) =>
                setTimeout(resolve, 150)
        );

        setProgressStage("save");

        const report =
            getReportFromPayload(payload);

        if (!report) {
            throw new Error(
                "The backend returned an empty analysis report."
            );
        }

        state.latestReport = report;

        state.currentReportId =
            payload.analysis_id ||
            payload.id ||
            payload.analysis?.id ||
            payload.latest?.id ||
            null;

        state.currentSymbol =
            report?.asset?.symbol ||
            normalizedSymbol;

        renderUser(payload.user);

        renderReport(report);

        if (payload.history) {
            renderHistory(
                payload.history
            );
        } else {
            await refreshHistory();
        }

        finishProgress();

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

        const overlay =
            $("#analysis-progress");

        hide(overlay);
    } finally {
        state.isAnalyzing = false;
    }
}


/* =========================================================
   HISTORY FETCH
   ========================================================= */

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
            payload.history || []
        );
    } catch (error) {
        console.error(
            "History refresh failed:",
            error
        );
    }
}


/* =========================================================
   SINGLE HISTORY REPORT
   ========================================================= */

async function loadHistoryReport(id) {
    if (!id) {
        return;
    }

    clearAnalysisError();

    try {
        const payload =
            await apiRequest(
                API.history(id)
            );

        const report =
            payload.analysis ||
            payload.report ||
            payload;

        if (!report) {
            throw new Error(
                "This report could not be loaded."
            );
        }

        state.latestReport = report;
        state.currentReportId = id;

        state.currentSymbol =
            report?.asset?.symbol ||
            report?.token_symbol ||
            null;

        renderReport(report);

        if (state.currentSymbol) {
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
            error.message
        );
    }
}


/* =========================================================
   DELETE REPORT
   ========================================================= */

async function deleteReport(id) {
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
            String(state.currentReportId) ===
            String(id)
        ) {
            state.currentReportId = null;
            state.latestReport = null;

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
            error.message
        );
    }
}

async function deleteCurrentReport() {
    if (!state.currentReportId) {
        return;
    }

    await deleteReport(
        state.currentReportId
    );
}


/* =========================================================
   LOGOUT
   ========================================================= */

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


/* =========================================================
   LIVE MARKET POLLING
   ========================================================= */

function stopLivePolling() {
    if (state.livePollTimer) {
        clearInterval(
            state.livePollTimer
        );

        state.livePollTimer = null;
    }
}

function startLivePolling(symbol) {
    stopLivePolling();

    if (!symbol) {
        return;
    }

    state.currentSymbol =
        String(symbol).toUpperCase();

    /*
     * Poll every 15 seconds.
     * Only market values are updated.
     * Risk calculations remain backend-controlled.
     */

    refreshLiveMarket(
        state.currentSymbol
    );

    state.livePollTimer =
        setInterval(() => {
            refreshLiveMarket(
                state.currentSymbol
            );
        }, 15000);
}

async function refreshLiveMarket(symbol) {
    if (!symbol) {
        return;
    }

    try {
        const payload =
            await apiRequest(
                API.market(symbol)
            );

        const market =
            payload.market ||
            payload.data ||
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

function updateLiveMarket(market) {
    if (!market) {
        return;
    }

    const price =
        firstDefined(
            market.current_price_usd,
            market.price_usd,
            market.current_price,
            market.price
        );

    const change24 =
        firstDefined(
            market.change_24h_pct,
            market.price_change_24h,
            market.change_24h
        );

    const volume =
        firstDefined(
            market.volume_24h_usd,
            market.total_volume_usd,
            market.volume_24h,
            market.volume
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
        "#market-live-status",
        "Live • Backend feed"
    );

    setText(
        "#market-updated",
        firstDefined(
            market.timestamp,
            market.updated_at
        )
            ? formatRelativeTime(
                  firstDefined(
                      market.timestamp,
                      market.updated_at
                  )
              )
            : "Updated now"
    );

    setText(
        "#data-source",
        market.source || "Backend market feed"
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

    const liveDot =
        $("#market-live-dot");

    if (liveDot) {
        liveDot.classList.add(
            "active"
        );
    }
}


/* =========================================================
   EMPTY REPORT STATE
   ========================================================= */

function clearReportView() {
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
}


/* =========================================================
   FORM HANDLERS
   ========================================================= */

async function handleAnalysisSubmit(event) {
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
        !/^[A-Z0-9]{2,15}$/.test(symbol)
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
        await runAnalysis(symbol);
    } finally {
        if (button) {
            button.disabled = false;

            button.textContent =
                button.dataset.originalText ||
                "Analyze";
        }
    }
}


/* =========================================================
   INITIALIZATION
   ========================================================= */

async function initializeDashboard() {
    /*
     * OAuth callback redirects to:
     * /dashboard?token=...
     *
     * Consume it before making protected API calls.
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
    /*
     * Google login is handled by the Flask route:
     * /api/auth/google
     *
     * Nothing is sent directly to Google from JavaScript.
     */

    const googleLinks =
        $all(
            'a[href="/api/auth/google"]'
        );

    googleLinks.forEach((link) => {
        link.addEventListener(
            "click",
            () => {
                clearAnalysisError();
            }
        );
    });
}


/* =========================================================
   GLOBAL EVENT BINDINGS
   ========================================================= */

document.addEventListener(
    "DOMContentLoaded",
    () => {
        const analysisForm =
            $("#analysis-form");

        if (analysisForm) {
            analysisForm.addEventListener(
                "submit",
                handleAnalysisSubmit
            );
        }

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


/*
 * Part 2 continues with:
 * - renderReport()
 * - risk pillar rendering
 * - risk severity classes
 * - stress test rendering
 * - AI evidence rendering
 * - forensic cards
 * - data quality
 * - history table
 * - delete buttons
 * - remaining dashboard UI helpers
 */



/* =========================================================
   PART 2 / 2
   REPORT RENDERING + RISK UI + HISTORY
   ========================================================= */


/* =========================================================
   RISK SEVERITY
   ========================================================= */

function normalizeSeverity(value) {
    if (!value) {
        return "Unknown";
    }

    const text =
        String(value)
            .trim()
            .toLowerCase();

    if (text.includes("critical")) {
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

    return String(value);
}

function severityClass(severity) {
    const normalized =
        normalizeSeverity(severity)
            .toLowerCase();

    if (normalized === "critical") {
        return "risk-critical";
    }

    if (normalized === "high") {
        return "risk-high";
    }

    if (normalized === "moderate") {
        return "risk-moderate";
    }

    if (normalized === "low") {
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
        severityClass(severity);

    if (className) {
        element.classList.add(
            className
        );
    }
}


/* =========================================================
   RISK SCORE BAR
   ========================================================= */

function updateScoreBar(
    bar,
    score
) {
    if (!bar) {
        return;
    }

    const numericScore =
        clampScore(score);

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


/* =========================================================
   MARKET RENDERING
   ========================================================= */

function renderMarket(report) {
    const market =
        getMarket(report);

    const asset =
        report?.asset || {};

    const price =
        firstDefined(
            market.current_price_usd,
            market.price_usd,
            market.current_price,
            market.price
        );

    const change24 =
        firstDefined(
            market.change_24h_pct,
            market.price_change_24h,
            market.change_24h
        );

    const change7 =
        firstDefined(
            market.change_7d_pct,
            market.price_change_7d,
            market.change_7d
        );

    const volume =
        firstDefined(
            market.volume_24h_usd,
            market.total_volume_usd,
            market.volume_24h,
            market.volume
        );

    const marketCap =
        firstDefined(
            market.market_cap_usd,
            market.market_cap
        );

    const high =
        firstDefined(
            market.high_24h_usd,
            market.high_24h,
            market.high
        );

    const low =
        firstDefined(
            market.low_24h_usd,
            market.low_24h,
            market.low
        );

    setText(
        "#report-token",
        asset.symbol ||
        report.token_symbol ||
        "—"
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
        formatPercent(change7)
    );

    setText(
        "#report-high",
        formatUsd(high)
    );

    setText(
        "#report-low",
        formatUsd(low)
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

    setText(
        "#market-live-status",
        "Live • Backend feed"
    );

    setText(
        "#market-updated",
        market.timestamp
            ? formatRelativeTime(
                  market.timestamp
              )
            : "Updated now"
    );

    setText(
        "#data-source",
        market.source ||
        "Backend market feed"
    );
}


/* =========================================================
   MAIN RISK PROFILE
   ========================================================= */

function renderRiskProfile(report) {
    const risk =
        getRiskProfile(report);

    const score =
        firstDefined(
            risk.overall_score,
            risk.score
        );

    const severity =
        normalizeSeverity(
            risk.severity
        );

    const confidence =
        firstDefined(
            risk.confidence,
            report?.data_quality?.confidence
        );

    setText(
        "#report-risk-score",
        Number.isFinite(Number(score))
            ? `${formatScore(score)}/100`
            : "—"
    );

    setText(
        "#report-risk-label",
        severity
    );

    setText(
        "#report-outlook",
        firstDefined(
            report?.ai?.risk_regime,
            severity
        )
    );

    const scoreElement =
        $("#report-risk-score");

    const labelElement =
        $("#report-risk-label");

    applyRiskClass(
        scoreElement,
        severity
    );

    applyRiskClass(
        labelElement,
        severity
    );

    renderPillar(
        "volatility",
        getPillar(
            report,
            "volatility"
        )
    );

    renderPillar(
        "liquidity",
        getPillar(
            report,
            "liquidity"
        )
    );

    /*
     * The dashboard calls this pillar
     * "contract", while the backend
     * calls it "structural".
     */
    renderPillar(
        "contract",
        getPillar(
            report,
            "structural"
        )
    );

    renderPillar(
        "composite",
        {
            score: score,
            severity: severity,
            confidence: confidence
        }
    );
}


/* =========================================================
   RISK PILLARS
   ========================================================= */

function renderPillar(
    name,
    pillar
) {
    if (!pillar) {
        return;
    }

    const score =
        firstDefined(
            pillar.score,
            pillar.value
        );

    const severity =
        normalizeSeverity(
            pillar.severity
        );

    const valueElement =
        $(`#pillar-${name}-value`);

    const barElement =
        $(`#pillar-${name}-bar`);

    const detailElement =
        $(`#pillar-${name}-detail`);

    if (valueElement) {
        valueElement.textContent =
            Number.isFinite(Number(score))
                ? `${formatScore(score)}/100`
                : "N/A";

        applyRiskClass(
            valueElement,
            severity
        );
    }

    if (barElement) {
        if (
            Number.isFinite(
                Number(score)
            )
        ) {
            updateScoreBar(
                barElement,
                score
            );

            applyRiskClass(
                barElement,
                severity
            );
        } else {
            barElement.style.width =
                "0%";
        }
    }

    if (detailElement) {
        detailElement.textContent =
            buildPillarDetail(
                name,
                pillar
            );
    }
}

function buildPillarDetail(
    name,
    pillar
) {
    const score =
        Number(pillar.score);

    const confidence =
        pillar.confidence;

    const details =
        firstDefined(
            pillar.detail,
            pillar.description,
            pillar.reason,
            pillar.interpretation
        );

    if (details) {
        return String(details);
    }

    if (!Number.isFinite(score)) {
        return "Insufficient evidence.";
    }

    let label = "Risk contribution";

    if (name === "volatility") {
        label =
            "Price instability contribution";
    } else if (name === "liquidity") {
        label =
            "Liquidity and exit-risk contribution";
    } else if (name === "contract") {
        label =
            "Structural/security contribution";
    } else if (name === "composite") {
        label =
            "Combined evidence-based risk score";
    }

    if (
        confidence !== undefined &&
        confidence !== null
    ) {
        return `${label} • confidence ${confidence}`;
    }

    return label;
}


/* =========================================================
   RISK DRIVERS
   ========================================================= */

function renderRiskDrivers(report) {
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
            document.createElement("div");

        empty.className =
            "empty-state";

        empty.textContent =
            "No material risk drivers were returned.";

        container.appendChild(empty);

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

            const title =
                document.createElement(
                    "h4"
                );

            const body =
                document.createElement(
                    "p"
                );

            const score =
                document.createElement(
                    "span"
                );

            const name =
                firstDefined(
                    driver?.name,
                    driver?.title,
                    driver?.driver,
                    `Risk driver ${index + 1}`
                );

            const explanation =
                firstDefined(
                    driver?.reason,
                    driver?.description,
                    driver?.detail,
                    driver?.explanation,
                    ""
                );

            const driverScore =
                firstDefined(
                    driver?.score,
                    driver?.impact
                );

            title.textContent =
                String(name);

            body.textContent =
                String(
                    explanation ||
                    "Evidence indicates this factor contributes to the current risk profile."
                );

            if (
                driverScore !== null &&
                driverScore !== undefined
            ) {
                score.textContent =
                    `Impact: ${formatScore(driverScore)}/100`;
            }

            card.appendChild(title);
            card.appendChild(body);

            if (score.textContent) {
                card.appendChild(score);
            }

            container.appendChild(card);
        }
    );
}


/* =========================================================
   STRESS TEST
   ========================================================= */

function renderStressTest(report) {
    const stress =
        getStress(report);

    const ai =
        getAI(report);

    const beta =
        firstDefined(
            stress.beta
        );

    const drawdown =
        firstDefined(
            stress.expected_drawdown_pct,
            stress.expected_drawdown
        );

    const resilience =
        firstDefined(
            stress.resilience_label,
            stress.resilience
        );

    const confidence =
        firstDefined(
            stress.confidence
        );

    setText(
        "#stress-beta",
        Number.isFinite(Number(beta))
            ? Number(beta).toFixed(2)
            : "N/A"
    );

    setText(
        "#stress-drawdown",
        Number.isFinite(Number(drawdown))
            ? formatPercent(drawdown)
            : "N/A"
    );

    setText(
        "#stress-resilience",
        resilience || "N/A"
    );

    setText(
        "#stress-confidence",
        confidence !== null
            ? String(confidence)
            : "N/A"
    );

    const verdict =
        firstDefined(
            ai.stress_interpretation,
            stress.verdict,
            stress.interpretation
        );

    setText(
        "#stress-verdict",
        verdict ||
        "Stress results are shown from the backend scenario engine."
    );
}


/* =========================================================
   AI REPORT
   ========================================================= */

function renderAI(report) {
    const ai =
        getAI(report);

    const security =
        getSecurity(report);

    const evidence =
        Array.isArray(
            report?.evidence
        )
            ? report.evidence
            : [];

    const hasEvidence =
        evidence.length > 0;

    const dataConfidence =
        report?.data_quality?.confidence;

    setText(
        "#executive-summary",
        ai.executive_summary ||
        "No executive summary was returned."
    );

    /*
     * Market structure:
     * Prefer explicit "what matters now",
     * then primary driver.
     */
    setText(
        "#ai-market-structure",
        firstDefined(
            ai.what_matters_now,
            ai.primary_risk_driver,
            ai.risk_regime,
            "No market-structure interpretation available."
        )
    );

    /*
     * Liquidity:
     * Use watch-next because the backend
     * should remain the source of interpretation.
     */
    setText(
        "#ai-liquidity",
        firstDefined(
            ai.watch_next,
            "No liquidity-specific interpretation available."
        )
    );

    /*
     * Contract/security:
     * Never invent security claims in the browser.
     */
    const securityFlags =
        Array.isArray(
            security.red_flags
        )
            ? security.red_flags
            : [];

    let contractText =
        firstDefined(
            security.status,
            ai.red_flags?.[0],
            "Security evidence unavailable."
        );

    if (
        securityFlags.length > 0
    ) {
        contractText =
            securityFlags.join(" • ");
    }

    setText(
        "#ai-contract-risk",
        contractText
    );

    setText(
        "#ai-evidence-status",
        hasEvidence
            ? "Evidence-backed"
            : "Limited evidence"
    );

    renderForensicCards(
        report
    );
}


/* =========================================================
   FORENSIC / INTELLIGENCE CARDS
   ========================================================= */

function renderForensicCards(report) {
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
            title: "Primary risk driver",
            value: firstDefined(
                ai.primary_risk_driver,
                "Not identified"
            )
        },
        {
            title: "What changed",
            value: firstDefined(
                ai.what_changed,
                "No material change reported."
            )
        },
        {
            title: "What matters now",
            value: firstDefined(
                ai.what_matters_now,
                "No immediate interpretation available."
            )
        },
        {
            title: "Watch next",
            value: firstDefined(
                ai.watch_next,
                "No monitoring signal returned."
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

            card.appendChild(heading);
            card.appendChild(text);

            container.appendChild(card);
        }
    );
}


/* =========================================================
   DATA QUALITY
   ========================================================= */

function renderDataQuality(report) {
    const quality =
        report?.data_quality || {};

    const confidence =
        firstDefined(
            quality.confidence
        );

    const source =
        firstDefined(
            quality.source,
            report?.market?.source,
            "Backend market feed"
        );

    const timestamp =
        firstDefined(
            quality.timestamp,
            report?.market?.timestamp
        );

    const missing =
        firstDefined(
            quality.missing_signals,
            quality.missing,
            []
        );

    setText(
        "#data-confidence",
        confidence !== null
            ? String(confidence)
            : "N/A"
    );

    setText(
        "#market-source",
        source
    );

    setText(
        "#data-freshness",
        timestamp
            ? formatRelativeTime(
                  timestamp
              )
            : "Unknown"
    );

    renderMissingSignals(
        missing
    );
}

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

    if (Array.isArray(missing)) {
        signals = missing;
    } else if (
        typeof missing === "string" &&
        missing.trim()
    ) {
        signals = [missing];
    }

    if (!signals.length) {
        const item =
            document.createElement(
                "span"
            );

        item.className =
            "data-ok";

        item.textContent =
            "No major missing signals reported.";

        container.appendChild(item);

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

            container.appendChild(item);
        }
    );
}


/* =========================================================
   COMPLETE REPORT RENDERER
   ========================================================= */

function renderReport(report) {
    if (!report) {
        clearReportView();
        return;
    }

    state.latestReport = report;

    state.currentSymbol =
        report?.asset?.symbol ||
        report?.token_symbol ||
        state.currentSymbol;

    renderMarket(report);

    renderRiskProfile(report);

    renderRiskDrivers(report);

    renderStressTest(report);

    renderAI(report);

    renderDataQuality(report);

    updateCurrentReportDeleteButton();

    /*
     * Update page-level metadata where
     * available without depending on a
     * particular HTML implementation.
     */
    if (report.generated_at) {
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


/* =========================================================
   DELETE BUTTON STATE
   ========================================================= */

function updateCurrentReportDeleteButton() {
    const button =
        $("#delete-current-report");

    if (!button) {
        return;
    }

    button.disabled =
        !state.currentReportId;
}


/* =========================================================
   HISTORY TABLE
   ========================================================= */

function renderHistory(history) {
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
        String(records.length)
    );

    if (!records.length) {
        const row =
            document.createElement("tr");

        const cell =
            document.createElement("td");

        cell.colSpan = 6;

        cell.className =
            "empty-history";

        cell.textContent =
            "No analyses yet.";

        row.appendChild(cell);
        tbody.appendChild(row);

        return;
    }

    records.forEach(
        (record) => {
            const row =
                document.createElement(
                    "tr"
                );

            row.dataset.reportId =
                String(record.id);

            const assetCell =
                createHistoryCell(
                    firstDefined(
                        record.token_symbol,
                        "—"
                    )
                );

            const riskCell =
                document.createElement(
                    "td"
                );

            const risk =
                normalizeSeverity(
                    record.risk_severity
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

            const outlookCell =
                createHistoryCell(
                    firstDefined(
                        record.trend,
                        "—"
                    )
                );

            const scoreCell =
                createHistoryCell(
                    Number.isFinite(
                        Number(
                            record.risk_score
                        )
                    )
                        ? `${formatScore(
                              record.risk_score
                          )}/100`
                        : "—"
                );

            const dateCell =
                createHistoryCell(
                    formatDate(
                        record.created_at
                    )
                );

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
                String(record.id);

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
                String(record.id);

            actionCell.appendChild(
                viewButton
            );

            actionCell.appendChild(
                deleteButton
            );

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

            tbody.appendChild(row);
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
        String(
            value === undefined ||
            value === null
                ? "—"
                : value
        );

    return cell;
}


/* =========================================================
   HISTORY EVENT DELEGATION
   ========================================================= */

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
        action === "view-history"
    ) {
        loadHistoryReport(id);
        return;
    }

    if (
        action === "delete-history"
    ) {
        deleteReport(id);
    }
}


/* =========================================================
   EXTRA LOGIN / SIGNUP SUPPORT
   ========================================================= */

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

    if (!email || !password) {
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
            payload.token ||
            payload.access_token;

        if (!token) {
            throw new Error(
                "Authentication succeeded but no session token was returned."
            );
        }

        saveToken(token);

        window.location.href =
            "/dashboard";
    } catch (error) {
        showAnalysisError(
            error.message
        );
    }
}


/* =========================================================
   KEYBOARD UX
   ========================================================= */

function setupKeyboardShortcuts() {
    document.addEventListener(
        "keydown",
        (event) => {
            /*
             * "/" focuses the token search
             * unless the user is already typing.
             */
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


/* =========================================================
   PAGE VISIBILITY
   ========================================================= */

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


/* =========================================================
   BEFORE UNLOAD CLEANUP
   ========================================================= */

window.addEventListener(
    "beforeunload",
    () => {
        stopLivePolling();
    }
);


/* =========================================================
   FINAL EVENT BINDINGS
   ========================================================= */

document.addEventListener(
    "DOMContentLoaded",
    () => {
        const historyBody =
            $("#history-tbody");

        if (historyBody) {
            historyBody.addEventListener(
                "click",
                handleHistoryClick
            );
        }

        /*
         * Optional auth forms.
         * Safe even if index.html doesn't
         * contain them.
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

        setupKeyboardShortcuts();

        setupVisibilityHandling();
    }
);


/* =========================================================
   GLOBAL ERROR SAFETY
   ========================================================= */

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