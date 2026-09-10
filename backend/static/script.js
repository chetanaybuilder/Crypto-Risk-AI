"use strict";

/*
 * ============================================================
 * CryptoRisk AI — Dashboard Controller
 *
 * Backend Report Schema: 3.0
 * Backend is the single source of truth.
 *
 * Gothic Halloween Wealth Edition Features:
 * - Cursor-repulsion physics for floating tokens
 * - Dollar-sign analysis beam animation
 * - Fire hover effects on interactive elements
 * - Particle effects for wealth burst
 *
 * FIX LOG:
 *  - Removed a fully duplicated `MoneyMeteor` object literal.
 *    The second copy had its methods pasted outside any
 *    object/class body (bare `foo() {...}` statements and
 *    stray `const startX = ...` lines at top level), which is
 *    a hard SyntaxError in JS — the whole file failed to parse.
 *  - Consolidated two conflicting `spawnMeteor()` variants
 *    (one used short keys like `sSize`/`isB`/`cCore`, the other
 *    used long keys like `symbolSize`/`isBitcoin`/`colorCore`).
 *    Kept the short-key version since drawTrail/drawCore/updM
 *    all read those keys.
 *  - Added `AnalysisBeam.renderParticles()` — called every
 *    frame from `startParticleLoop()` but never defined.
 *  - Added `AnalysisBeam.triggerWealthBurst()` — called from
 *    `animateProgress()` but never defined.
 *  - Removed a dead duplicate `setText("#stress-beta", ...)`
 *    call in `renderStressTest()`.
 * ============================================================
 */

/* ============================================================
   CURSOR-REPULSION PHYSICS ENGINE
   ============================================================ */

const CursorPhysics = {
    cursorX: 0,
    cursorY: 0,
    targetX: 0,
    targetY: 0,
    tokens: [],
    isActive: false,

    init() {
        this.tokens = document.querySelectorAll('.physics-token');
        if (this.tokens.length === 0) return;
        this.isActive = true;
        document.addEventListener('mousemove', (e) => {
            this.targetX = e.clientX;
            this.targetY = e.clientY;
        });
        this.animate();
    },

    animate() {
        if (!this.isActive) return;
        this.cursorX += (this.targetX - this.cursorX) * 0.08;
        this.cursorY += (this.targetY - this.cursorY) * 0.08;

        this.tokens.forEach((token, index) => {
            const rect = token.getBoundingClientRect();
            const tokenCenterX = rect.left + rect.width / 2;
            const tokenCenterY = rect.top + rect.height / 2;
            const deltaX = tokenCenterX - this.cursorX;
            const deltaY = tokenCenterY - this.cursorY;
            const distance = Math.sqrt(deltaX * deltaX + deltaY * deltaY);
            const repulsionRadius = 250;

            if (distance < repulsionRadius && distance > 0) {
                const force = Math.pow(1 - distance / repulsionRadius, 2) * 60;
                const dirX = deltaX / distance;
                const dirY = deltaY / distance;
                const displaceX = dirX * force;
                const displaceY = dirY * force;
                const displaceZ = force * 0.5 + index * 10;
                token.style.transform = `translate3d(${displaceX}px, ${displaceY}px, ${displaceZ}px) rotateZ(${dirX * 5}deg)`;
            } else {
                token.style.transform = '';
            }
        });
        requestAnimationFrame(() => this.animate());
    }
};


/* ============================================================
   API
   ============================================================ */

const API = {
    dashboard: "/api/dashboard",
    analyze: "/api/analyze",
    logout: "/api/auth/logout",
    me: "/api/auth/me",

    market: (symbol) => `/api/market/${encodeURIComponent(symbol)}`,
    history: (id) => `/api/history/${encodeURIComponent(id)}`,
    deleteHistory: (id) => `/api/history/${encodeURIComponent(id)}`
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
    return Array.from(document.querySelectorAll(selector));
}

function setText(selector, value, fallback = "—") {
    const element = $(selector);
    if (!element) return;

    if (value === null || value === undefined || value === "") {
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


/* ============================================================
   AUTH
   ============================================================ */

function getTokenFromStorage() {
    return localStorage.getItem(STORAGE_KEYS.token);
}

function saveToken(token) {
    if (!token) return;
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

    if (!token) {
        return null;
    }

    saveToken(token);

    const cleanUrl = window.location.pathname + window.location.hash;
    window.history.replaceState({}, document.title, cleanUrl);

    return token;
}

function getAuthHeaders() {
    const token = state.token || getTokenFromStorage();
    if (!token) return {};
    return { Authorization: `Bearer ${token}` };
}

function redirectToHome() {
    clearToken();
    stopLivePolling();
    window.location.href = "/";
}


/* ============================================================
   API REQUEST LAYER
   ============================================================ */

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

async function apiRequest(url, options = {}) {
    const resolvedUrl = resolveApiUrl(url);

    const headers = {
        Accept: "application/json",
        ...(options.headers || {}),
        ...getAuthHeaders()
    };

    if (options.body && typeof options.body !== "string") {
        headers["Content-Type"] = "application/json";
        options = {
            ...options,
            body: JSON.stringify(options.body)
        };
    }

    let response;

    try {
        response = await fetch(resolvedUrl, { ...options, headers });
    } catch (error) {
        console.error("Network error:", error);
        throw new Error("Unable to connect to the CryptoRisk backend.");
    }

    let payload = null;
    const contentType = response.headers.get("content-type") || "";

    if (contentType.includes("application/json")) {
        try {
            payload = await response.json();
        } catch (error) {
            console.warn("Could not parse JSON response.", error);
            payload = null;
        }
    } else {
        try {
            const text = await response.text();
            if (text) {
                payload = { message: text };
            }
        } catch {
            payload = null;
        }
    }

    if (response.status === 401) {
        clearToken();
        stopLivePolling();

        if (window.location.pathname !== "/" && window.location.pathname !== "") {
            window.location.href = "/";
        }

        throw new Error(
            payload?.message || payload?.error || "Your session has expired."
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


/* ============================================================
   ERROR UI
   ============================================================ */

function showAnalysisError(message) {
    const element = $("#analysis-error");

    if (!element) {
        console.error(message);
        return;
    }

    element.textContent = message || "Something went wrong.";
    show(element);
}

function clearAnalysisError() {
    const element = $("#analysis-error");
    if (!element) return;
    element.textContent = "";
    hide(element);
}


/* ============================================================
   USER UI
   ============================================================ */

function renderUser(user) {
    if (!user || typeof user !== "object") return;

    state.user = user;

    const displayName = firstDefined(user.username, user.name, user.email, "User");

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


/* ============================================================
   PROGRESS SYSTEM
   ============================================================ */

const PROGRESS_STAGES = {
    market: { percent: 20, title: "Fetching live market data" },
    model: { percent: 45, title: "Running quantitative risk engine" },
    stress: { percent: 65, title: "Running stress scenarios" },
    ai: { percent: 82, title: "Synthesizing evidence" },
    save: { percent: 96, title: "Saving intelligence report" },
    complete: { percent: 100, title: "Analysis complete" }
};

let _progressAnim = null;

function _stageForPercent(percent) {
    if (percent >= 96) return "save";
    if (percent >= 82) return "ai";
    if (percent >= 65) return "stress";
    if (percent >= 45) return "model";
    return "market";
}

function animateProgress(targetPercent = 100) {
    const fill = $("#progress-fill");
    const percentEl = $("#progress-percent");

    const startPercent = 1;
    const startTime = performance.now();
    const durationMs = 4500;

    if (_progressAnim) {
        cancelAnimationFrame(_progressAnim);
        _progressAnim = null;
    }

    function frame(now) {
        const elapsed = now - startTime;
        const t = Math.min(elapsed / durationMs, 1);
        const eased = 1 - Math.pow(1 - t, 3);
        const current = startPercent + (targetPercent - startPercent) * eased;

        const stageName = _stageForPercent(current);
        const config = PROGRESS_STAGES[stageName] || PROGRESS_STAGES.market;

        if (fill) {
            fill.style.width = `${current}%`;
        }

        if (percentEl) {
            percentEl.textContent = `${Math.round(current)}%`;
        }

        setText("#progress-title", config.title);

        const stageOrder = ["market", "model", "stress", "ai", "save"];
        const currentIndex = stageOrder.indexOf(stageName);

        $all(".progress-status").forEach((element) => {
            element.classList.remove("active", "complete");

            const index = stageOrder.indexOf(element.dataset.stage);
            if (index < 0) return;

            if (index < currentIndex) {
                element.classList.add("complete");
            } else if (index === currentIndex) {
                element.classList.add("active");
            }
        });

        if (t < 1 && current < targetPercent) {
            _progressAnim = requestAnimationFrame(frame);
            return;
        }

        setProgressStage(_stageForPercent(targetPercent));
    }

    _progressAnim = requestAnimationFrame(frame);
}

function setProgressStage(stage) {
    const config = PROGRESS_STAGES[stage] || PROGRESS_STAGES.market;

    setText("#progress-title", config.title);
    setText("#progress-percent", `${config.percent}%`);

    const fill = $("#progress-fill");
    if (fill) {
        fill.style.width = `${config.percent}%`;
    }

    $all(".progress-status").forEach((element) => {
        element.classList.remove("active", "complete");

        const stageName = element.dataset.stage;
        if (stageName === stage) {
            element.classList.add("active");
        }
    });

    const stageOrder = ["market", "model", "stress", "ai", "save"];
    const currentIndex = stageOrder.indexOf(stage);

    if (currentIndex < 0) return;

    $all(".progress-status").forEach((element) => {
        const index = stageOrder.indexOf(element.dataset.stage);
        if (index >= 0 && index < currentIndex) {
            element.classList.add("complete");
        }
    });
}

function startProgress() {
    const overlay = $("#analysis-progress");
    if (!overlay) return;

    show(overlay);
    animateProgress(95);
}

function finishProgress() {
    const overlay = $("#analysis-progress");
    if (!overlay) return;

    animateProgress(100);
    setProgressStage("complete");

    setTimeout(() => {
        hide(overlay);
    }, 450);
}


/* ============================================================
   FORMATTERS
   ============================================================ */

function formatNumber(value, decimals = 2) {
    if (value === null || value === undefined || value === "") return "—";

    const number = Number(value);
    if (!Number.isFinite(number)) return "—";

    return number.toLocaleString(undefined, { maximumFractionDigits: decimals });
}

function formatUsd(value) {
    if (value === null || value === undefined || value === "") return "—";

    const number = Number(value);
    if (!Number.isFinite(number)) return "—";

    if (Math.abs(number) >= 1_000_000_000) {
        return `$${formatNumber(number / 1_000_000_000, 2)}B`;
    }

    if (Math.abs(number) >= 1_000_000) {
        return `$${formatNumber(number / 1_000_000, 2)}M`;
    }

    if (Math.abs(number) >= 1_000) {
        return `$${formatNumber(number / 1_000, 2)}K`;
    }

    if (Math.abs(number) >= 1) {
        return `$${formatNumber(number, 2)}`;
    }

    return `$${number.toFixed(6)}`;
}

function formatPercent(value) {
    if (value === null || value === undefined || value === "") return "—";

    const number = Number(value);
    if (!Number.isFinite(number)) return "—";

    const sign = number > 0 ? "+" : "";
    return `${sign}${number.toFixed(2)}%`;
}

function formatScore(value) {
    if (value === null || value === undefined || value === "") return "—";

    const number = Number(value);
    if (!Number.isFinite(number)) return "—";

    return Math.round(number);
}

function formatConfidence(value) {
    if (value === null || value === undefined || value === "") return "—";

    const number = Number(value);
    if (!Number.isFinite(number)) return "—";

    return `${number.toFixed(1)}%`;
}

function formatDate(value) {
    if (!value) return "—";

    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);

    return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function formatRelativeTime(value) {
    if (!value) return "—";

    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return formatDate(value);

    const seconds = Math.floor((Date.now() - date.getTime()) / 1000);

    if (seconds < 10) return "just now";
    if (seconds < 60) return `${seconds}s ago`;

    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;

    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;

    return `${Math.floor(hours / 24)}d ago`;
}

function clampScore(value) {
    if (value === null || value === undefined || value === "") return null;

    const number = Number(value);
    if (!Number.isFinite(number)) return null;

    return Math.max(0, Math.min(100, number));
}


/* ============================================================
   SAFE DATA HELPERS
   ============================================================ */

function firstDefined(...values) {
    for (const value of values) {
        if (value !== undefined && value !== null && value !== "") {
            return value;
        }
    }
    return null;
}

function isRiskReport(value) {
    if (!value || typeof value !== "object") return false;

    if (
        value.schema_version ||
        value.risk_profile ||
        value.risk_drivers ||
        value.stress_test ||
        value.data_quality
    ) {
        return true;
    }

    return Boolean(
        value.risk_score !== undefined && (value.asset || value.token_symbol)
    );
}

function getReportFromPayload(payload) {
    if (!payload) return null;

    if (isRiskReport(payload)) {
        return payload;
    }

    const candidates = [
        payload.analysis,
        payload.report,
        payload.latest?.report,
        payload.latest,
        payload.data
    ];

    for (const candidate of candidates) {
        if (isRiskReport(candidate)) {
            return candidate;
        }
    }

    return null;
}


/* ============================================================
   REPORT ACCESSORS
   ============================================================ */

function getRiskProfile(report) {
    return report?.risk_profile || {};
}

function getPillars(report) {
    return report?.risk_profile?.pillars || {};
}

function getPillar(report, name) {
    return report?.risk_profile?.pillars?.[name] || {};
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
    return report?.stress_test || report?.stress || {};
}

function getDataQuality(report) {
    return report?.data_quality || {};
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
        const payload = await apiRequest(API.dashboard);

        console.log("CryptoRisk dashboard payload:", payload);

        if (payload.user) {
            renderUser(payload.user);
        }

        const latest = payload.latest;

        if (latest) {
            const report = getReportFromPayload(latest);

            if (report) {
                state.latestReport = report;

                state.currentReportId =
                    latest.id || latest.analysis_id || report.id || null;

                state.currentSymbol = firstDefined(
                    report?.asset?.symbol,
                    report?.token_symbol
                );

                renderReport(report);

                if (state.currentSymbol) {
                    startLivePolling(state.currentSymbol);
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

        renderHistory(Array.isArray(payload.history) ? payload.history : []);
    } catch (error) {
        console.error("Dashboard load failed:", error);
        showAnalysisError(error.message || "Unable to load dashboard.");
    }
}


/* ============================================================
   ANALYSIS — Frontend Analysis Orchestrator
   ============================================================ */

async function runAnalysis(symbol) {
    if (state.isAnalyzing) return;

    state.isAnalyzing = true;

    clearAnalysisError();
    startProgress();
    stopLivePolling();

    const normalizedSymbol = String(symbol || "").trim().toUpperCase();

    if (!normalizedSymbol) {
        state.isAnalyzing = false;
        hide($("#analysis-progress"));
        showAnalysisError("Enter a token symbol.");
        return;
    }

    try {
        const payload = await apiRequest(API.analyze, {
            method: "POST",
            body: { token_symbol: normalizedSymbol }
        });

        console.log("CryptoRisk analyze payload:", payload);

        const report = getReportFromPayload(payload);

        if (!report) {
            console.error(
                "Analyze response did not contain a recognizable report:",
                payload
            );

            throw new Error(
                "The backend returned data, but no valid risk report was found."
            );
        }

        state.latestReport = report;

        state.currentReportId = firstDefined(
            payload.analysis_id,
            payload.id,
            payload.analysis?.id,
            payload.report?.id,
            payload.latest?.id,
            report.id
        );

        state.currentSymbol = firstDefined(
            report?.asset?.symbol,
            report?.token_symbol,
            normalizedSymbol
        );

        if (payload.user) {
            renderUser(payload.user);
        }

        renderReport(report);

        if (Array.isArray(payload.history)) {
            renderHistory(payload.history);
        } else {
            await refreshHistory();
        }

        finishProgress();

        startLivePolling(state.currentSymbol);
    } catch (error) {
        console.error("Analysis failed:", error);
        showAnalysisError(error.message || "Analysis failed.");
        hide($("#analysis-progress"));
    } finally {
        state.isAnalyzing = false;
    }
}


/* ============================================================
   HISTORY FETCH
   ============================================================ */

async function refreshHistory() {
    try {
        const payload = await apiRequest(API.dashboard);

        if (payload.user) {
            renderUser(payload.user);
        }

        renderHistory(Array.isArray(payload.history) ? payload.history : []);
    } catch (error) {
        console.error("History refresh failed:", error);
    }
}


/* ============================================================
   SINGLE HISTORY REPORT
   ============================================================ */

async function loadHistoryReport(id) {
    if (!id) return;

    clearAnalysisError();

    try {
        const payload = await apiRequest(API.history(id));

        console.log("History report payload:", payload);

        const report = getReportFromPayload(payload);

        if (!report) {
            throw new Error("This report could not be loaded.");
        }

        state.latestReport = report;
        state.currentReportId = id;

        state.currentSymbol = firstDefined(
            report?.asset?.symbol,
            report?.token_symbol
        );

        renderReport(report);

        if (state.currentSymbol) {
            startLivePolling(state.currentSymbol);
        }

        window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (error) {
        console.error("History report load failed:", error);
        showAnalysisError(error.message || "Unable to load report.");
    }
}


/* ============================================================
   DELETE REPORT
   ============================================================ */

async function deleteReport(id) {
    if (!id) return;

    try {
        await apiRequest(API.deleteHistory(id), { method: "DELETE" });

        if (String(state.currentReportId) === String(id)) {
            state.currentReportId = null;
            state.latestReport = null;
            clearReportView();
            stopLivePolling();
        }

        await refreshHistory();
    } catch (error) {
        console.error("Delete report failed:", error);
        showAnalysisError(error.message || "Unable to delete report.");
    }
}

async function deleteCurrentReport() {
    if (!state.currentReportId) return;
    await deleteReport(state.currentReportId);
}


/* ============================================================
   LOGOUT
   ============================================================ */

async function logout() {
    try {
        if (state.token) {
            await apiRequest(API.logout, { method: "POST" });
        }
    } catch (error) {
        console.warn("Logout request failed:", error);
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
    if (state.livePollTimer) {
        clearInterval(state.livePollTimer);
        state.livePollTimer = null;
    }
}

function startLivePolling(symbol) {
    stopLivePolling();

    if (!symbol) return;

    state.currentSymbol = String(symbol).trim().toUpperCase();

    refreshLiveMarket(state.currentSymbol);

    state.livePollTimer = setInterval(() => {
        refreshLiveMarket(state.currentSymbol);
    }, 15000);
}

async function refreshLiveMarket(symbol) {
    if (!symbol) return;

    try {
        const payload = await apiRequest(API.market(symbol));
        const market = payload?.market || payload?.data || payload;

        updateLiveMarket(market);
    } catch (error) {
        console.warn("Live market refresh failed:", error);
        setText("#market-live-status", "Live feed unavailable");
    }
}

function updateLiveMarket(market) {
    if (!market || typeof market !== "object") return;

    const price = firstDefined(
        market.price,
        market.current_price_usd,
        market.price_usd,
        market.current_price
    );

    const change24 = firstDefined(
        market.price_change_24h_pct,
        market.change_24h_pct,
        market.price_change_24h,
        market.change_24h
    );

    const change7d = firstDefined(
        market.price_change_7d_pct,
        market.change_7d_pct,
        market.price_change_7d,
        market.change_7d
    );

    const high24 = firstDefined(
        market.high_24h,
        market.high_24h_usd,
        market.highPrice,
        market.high
    );

    const low24 = firstDefined(
        market.low_24h,
        market.low_24h_usd,
        market.lowPrice,
        market.low
    );

    const volume = firstDefined(
        market.volume_24h,
        market.volume_24h_usd,
        market.total_volume_usd,
        market.volume
    );

    const marketCap = firstDefined(market.market_cap, market.market_cap_usd);
    const source = firstDefined(market.source, "Backend market feed");
    const timestamp = firstDefined(market.timestamp, market.updated_at);

    setText("#report-price", formatUsd(price));
    setText("#report-change", formatPercent(change24));
    setText("#report-volume", formatUsd(volume));

    if (marketCap !== null) {
        setText("#report-market-cap", formatUsd(marketCap));
    }

    setText("#report-change-7d", formatPercent(change7d));
    setText("#report-high", formatUsd(high24));
    setText("#report-low", formatUsd(low24));

    setText("#market-live-status", "Live • Backend feed");
    setText(
        "#market-updated",
        timestamp ? formatRelativeTime(timestamp) : "Updated now"
    );
    setText("#data-source", source);
    setText("#market-source", source);

    const changeElement = $("#report-change");

    if (changeElement) {
        changeElement.classList.remove("positive", "negative");

        const numericChange = Number(change24);
        if (Number.isFinite(numericChange)) {
            changeElement.classList.add(numericChange >= 0 ? "positive" : "negative");
        }
    }

    const liveDot = $("#market-live-dot");
    if (liveDot) {
        liveDot.classList.add("active");
    }
}


/* ============================================================
   EMPTY REPORT STATE
   ============================================================ */

function clearReportView() {
    state.latestReport = null;

    setText("#report-token", "No analysis yet");
    setText("#report-outlook", "—");
    setText("#report-risk-score", "—");
    setText("#report-risk-label", "—");
    setText("#report-risk-confidence", "—");
    setText("#report-price", "—");
    setText("#report-change", "—");
    setText("#report-volume", "—");
    setText("#report-market-cap", "—");
    setText("#report-change-7d", "—");
    setText("#report-high", "—");
    setText("#report-low", "—");
    setText("#market-live-status", "—");
    setText("#market-updated", "—");
    setText("#data-source", "—");
    setText("#market-source", "—");

    const pillarNames = [
        "volatility",
        "liquidity",
        "market-sensitivity",
        "market_sensitivity",
        "structural",
        "contract",
        "composite"
    ];

    pillarNames.forEach((name) => {
        setText(`#pillar-${name}-value`, "—");
        setText(`#pillar-${name}-detail`, "—");

        const bar = $(`#pillar-${name}-bar`);
        if (bar) {
            bar.style.width = "0%";
            bar.removeAttribute("aria-valuenow");
        }
    });

    const drivers = $("#risk-drivers");
    if (drivers) {
        drivers.replaceChildren();
    }

    setText("#stress-beta", "—");
    setText("#stress-drawdown", "—");
    setText("#stress-resilience", "—");
    setText("#stress-confidence", "—");
    setText("#stress-verdict", "—");
    setText("#ai-stress-interpretation", "—");

    setText("#executive-summary", "—");
    setText("#ai-market-structure", "—");
    setText("#ai-liquidity", "—");
    setText("#ai-contract-risk", "—");
    setText("#ai-evidence-status", "—");

    const forensic = $("#forensic-cards");
    if (forensic) {
        forensic.replaceChildren();
    }

    setText("#data-confidence", "—");
    setText("#data-freshness", "—");

    renderMissingSignals([]);

    updateCurrentReportDeleteButton();
}


/* ============================================================
   FORM HANDLER
   ============================================================ */

async function handleAnalysisSubmit(event) {
    event.preventDefault();

    const input = $("#token-symbol");
    if (!input) return;

    const symbol = input.value.trim().toUpperCase();

    if (!symbol) {
        showAnalysisError("Enter a token symbol.");
        input.focus();
        return;
    }

    if (!/^[A-Z0-9]{2,15}$/.test(symbol)) {
        showAnalysisError("Enter a valid token symbol.");
        input.focus();
        return;
    }

    const button = $("#analyze-button");

    if (button) {
        button.disabled = true;
        button.dataset.originalText = button.textContent;
        button.textContent = "Analyzing…";
    }

    try {
        await runAnalysis(symbol);
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = button.dataset.originalText || "Analyze";
        }
    }
}


/* ============================================================
   INITIALIZATION
   ============================================================ */

async function initializeDashboard() {
    consumeQueryToken();

    state.token = getTokenFromStorage();

    if (!state.token) {
        redirectToHome();
        return;
    }

    await loadDashboard();
}

function initializeIndexPage() {
    const googleLinks = $all('a[href="/api/auth/google"]');

    googleLinks.forEach((link) => {
        link.addEventListener("click", () => {
            clearAnalysisError();
        });
    });
}


/* ============================================================
   RISK SEVERITY
   ============================================================ */

function normalizeSeverity(value) {
    if (value === null || value === undefined || value === "") {
        return "Unavailable";
    }

    const text = String(value).trim().toLowerCase();

    if (text.includes("critical")) return "Critical";
    if (text.includes("high") || text.includes("elevated")) return "High";
    if (text.includes("moderate") || text.includes("medium")) return "Moderate";
    if (text.includes("low") || text.includes("minimal")) return "Low";
    if (text.includes("unavailable")) return "Unavailable";

    return String(value);
}

function severityClass(severity) {
    const normalized = normalizeSeverity(severity).toLowerCase();

    if (normalized === "critical") return "risk-critical";
    if (normalized === "high") return "risk-high";
    if (normalized === "moderate") return "risk-moderate";
    if (normalized === "low") return "risk-low";

    return "";
}

function applyRiskClass(element, severity) {
    if (!element) return;

    element.classList.remove("risk-low", "risk-moderate", "risk-high", "risk-critical");

    const className = severityClass(severity);
    if (className) {
        element.classList.add(className);
    }
}


/* ============================================================
   RISK SCORE BAR
   ============================================================ */

function updateScoreBar(bar, score) {
    if (!bar) return;

    const numericScore = clampScore(score);

    if (numericScore === null) {
        bar.style.width = "0%";
        bar.removeAttribute("aria-valuenow");
        return;
    }

    bar.style.width = `${numericScore}%`;
    bar.setAttribute("aria-valuenow", String(Math.round(numericScore)));
}


/* ============================================================
   MARKET RENDERING
   ============================================================ */

function renderMarket(report) {
    const market = getMarket(report);
    const asset = report?.asset || {};

    const price = firstDefined(
        market.price,
        market.current_price_usd,
        market.price_usd,
        market.current_price
    );

    const change24 = firstDefined(
        market.price_change_24h_pct,
        market.change_24h_pct,
        market.price_change_24h,
        market.change_24h
    );

    const change7d = firstDefined(
        market.price_change_7d_pct,
        market.change_7d_pct,
        market.price_change_7d,
        market.change_7d
    );

    const high24 = firstDefined(
        market.high_24h,
        market.high_24h_usd,
        market.highPrice,
        market.high
    );

    const low24 = firstDefined(
        market.low_24h,
        market.low_24h_usd,
        market.lowPrice,
        market.low
    );

    const volume = firstDefined(
        market.volume_24h,
        market.volume_24h_usd,
        market.quoteVolume,
        market.volume
    );

    const marketCap = firstDefined(market.market_cap, market.market_cap_usd);
    const source = firstDefined(market.source, "Backend market feed");
    const timestamp = firstDefined(market.timestamp, market.updated_at);

    setText("#report-token", firstDefined(asset.symbol, report.token_symbol));
    setText("#report-price", formatUsd(price));
    setText("#report-change", formatPercent(change24));
    setText("#report-volume", formatUsd(volume));
    setText("#report-market-cap", formatUsd(marketCap));

    setText("#report-change-7d", formatPercent(change7d));
    setText("#report-high", formatUsd(high24));
    setText("#report-low", formatUsd(low24));

    const changeElement = $("#report-change");

    if (changeElement) {
        changeElement.classList.remove("positive", "negative");

        const numericChange = Number(change24);
        if (Number.isFinite(numericChange)) {
            changeElement.classList.add(numericChange >= 0 ? "positive" : "negative");
        }
    }

    setText("#market-live-status", "Live • Backend feed");
    setText(
        "#market-updated",
        timestamp ? formatRelativeTime(timestamp) : "Updated now"
    );
    setText("#data-source", firstDefined(source, "Backend market feed"));
    setText("#market-source", firstDefined(source, "Backend market feed"));
}


/* ============================================================
   MAIN RISK PROFILE
   ============================================================ */

function renderRiskProfile(report) {
    const risk = getRiskProfile(report);

    const compositeScore = firstDefined(risk.composite_score, report.risk_score);
    const rawLabel = firstDefined(risk.label, report.risk_label);
    const label = normalizeSeverity(rawLabel);
    const confidence = firstDefined(risk.confidence, report.risk_confidence);

    setText(
        "#report-risk-score",
        compositeScore !== null ? `${formatScore(compositeScore)}/100` : "—"
    );

    setText("#report-risk-label", label);

    setText("#report-outlook", firstDefined(report.outlook, report.risk_label, risk.label));

    setText("#report-risk-confidence", formatConfidence(confidence));

    applyRiskClass($("#report-risk-score"), rawLabel);
    applyRiskClass($("#report-risk-label"), rawLabel);
    applyRiskClass($("#report-outlook"), report.outlook || rawLabel);

    renderPillar("volatility", getPillar(report, "volatility"));
    renderPillar("liquidity", getPillar(report, "liquidity"));

    const marketSensitivity = getPillar(report, "market_sensitivity");
    renderPillar("market-sensitivity", marketSensitivity);

    const structural = getPillar(report, "structural");
    renderPillar("structural", structural);

    renderPillar("composite", {
        score: compositeScore,
        label: rawLabel,
        confidence: confidence,
        detail: "Combined evidence-based risk score."
    });
}


/* ============================================================
   RISK PILLARS
   ============================================================ */

function renderPillar(name, pillar) {
    if (!pillar || typeof pillar !== "object") return;

    const score = pillar.score;
    const label = normalizeSeverity(pillar.label);

    const valueElement = $(`#pillar-${name}-value`);
    const barElement = $(`#pillar-${name}-bar`);
    const detailElement = $(`#pillar-${name}-detail`);

    if (valueElement) {
        if (score === null || score === undefined || score === "") {
            valueElement.textContent = "N/A";
        } else {
            valueElement.textContent = `${formatScore(score)}/100`;
        }

        applyRiskClass(valueElement, pillar.label);
    }

    if (barElement) {
        updateScoreBar(barElement, score);
        applyRiskClass(barElement, pillar.label);
    }

    if (detailElement) {
        detailElement.textContent = buildPillarDetail(name, pillar);
    }
}


/* ============================================================
   PILLAR DETAIL
   ============================================================ */

function buildPillarDetail(name, pillar) {
    if (!pillar || typeof pillar !== "object") {
        return firstDefined(
            name && generatePillarFallbackDetail(name, null),
            "Signal unavailable."
        );
    }

    if (pillar.detail !== null && pillar.detail !== undefined && pillar.detail !== "") {
        return String(pillar.detail);
    }

    if (pillar.score === null || pillar.score === undefined) {
        return firstDefined(
            pillar.label,
            generatePillarFallbackDetail(name, null),
            "Signal unavailable."
        );
    }

    return generatePillarFallbackDetail(name, pillar.score);
}

function generatePillarFallbackDetail(name, score) {
    const descriptions = {
        volatility: "Volatility risk contribution.",
        liquidity: "Liquidity and exit-risk contribution.",
        "market-sensitivity": "Market sensitivity contribution.",
        market_sensitivity: "Market sensitivity contribution.",
        structural: "Structural risk contribution.",
        contract: "Structural risk contribution.",
        composite: "Combined evidence-based risk score."
    };

    const missingDescriptions = {
        liquidity:
            "Liquidity signal unavailable — no volume or market-cap data to estimate exit risk.",
        "market-sensitivity":
            "Market sensitivity signal unavailable — no BTC beta could be calculated.",
        market_sensitivity:
            "Market sensitivity signal unavailable — no BTC beta could be calculated.",
        volatility: "Volatility signal unavailable — insufficient price history.",
        structural: "Structural signal unavailable — no contract/security data.",
        contract: "Structural signal unavailable — no contract/security data."
    };

    if (score === null || score === undefined) {
        return missingDescriptions[name] || descriptions[name] || "Signal unavailable.";
    }

    return descriptions[name] || "Risk contribution.";
}


/* ============================================================
   RISK DRIVERS
   ============================================================ */

function renderRiskDrivers(report) {
    const container = $("#risk-drivers");
    if (!container) return;

    container.replaceChildren();

    const drivers = Array.isArray(report?.risk_drivers) ? report.risk_drivers : [];

    if (!drivers.length) {
        const empty = document.createElement("div");
        empty.className = "empty-state";
        empty.textContent = "No material risk drivers were returned.";
        container.appendChild(empty);
        return;
    }

    drivers.forEach((driver, index) => {
        const card = document.createElement("article");
        card.className = "risk-driver-card";

        const heading = document.createElement("h4");
        const badge = document.createElement("span");
        const body = document.createElement("p");

        heading.textContent = firstDefined(driver?.title, `Risk driver ${index + 1}`);

        badge.textContent = normalizeSeverity(driver?.severity);
        badge.className = "risk-badge";
        applyRiskClass(badge, driver?.severity);

        body.textContent = firstDefined(driver?.detail, "No additional detail was provided.");

        card.appendChild(heading);
        card.appendChild(badge);
        card.appendChild(body);

        container.appendChild(card);
    });
}


/* ============================================================
   STRESS TEST
   ============================================================ */

function getExpectedDrawdown(stress) {
    const stressObj = stress || {};

    const expected = firstDefined(
        stressObj.expected_drawdown_pct,
        stressObj.drawdown_pct,
        stressObj.max_drawdown_pct,
        stressObj.expected_downside_pct
    );

    if (expected !== null) {
        return expected;
    }

    const base = stressObj.base_scenario || {};

    if (typeof base === "object" && base !== null) {
        const move = firstDefined(
            base.estimated_asset_move_pct,
            base.asset_move_pct,
            base.drawdown_pct
        );

        const numericMove = Number(move);

        if (Number.isFinite(numericMove)) {
            return Math.abs(numericMove);
        }
    }

    return null;
}

function getResilienceLabel(stress) {
    const stressObj = stress || {};

    const label = firstDefined(
        stressObj.resilience_label,
        stressObj.resilience,
        stressObj.resilience_status
    );

    if (label !== null) {
        return label;
    }

    const base = stressObj.base_scenario || {};

    const rawScore = firstDefined(base.resilience_score, stressObj.resilience_score);
    const score = Number(rawScore);

    if (Number.isFinite(score)) {
        if (score >= 65) return "Resilient";
        if (score >= 40) return "Moderate";
        return "Fragile";
    }

    return null;
}

function getStressConfidence(report, stress) {
    const stressObj = stress || {};
    const reportObj = report || {};

    return firstDefined(
        stressObj.confidence,
        reportObj.risk_confidence,
        reportObj.ai?.confidence,
        reportObj.risk_profile?.confidence
    );
}

function renderStressTest(report) {
    const stress = getStress(report);

    /*
     * NOTE: previously this called setText("#stress-beta", ...)
     * TWICE — once with just stress.beta, then immediately
     * overwritten by the fuller fallback chain below. The dead
     * first call has been removed.
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

    setText("#stress-drawdown", formatPercent(getExpectedDrawdown(stress)));

    setText("#stress-resilience", getResilienceLabel(stress));

    setText(
        "#stress-confidence",
        formatConfidence(getStressConfidence(report, stress))
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

    applyRiskClass($("#stress-resilience"), stress.resilience_label);

    setText("#ai-stress-interpretation", getAI(report).stress_interpretation);
}


/* ============================================================
   AI REPORT
   ============================================================ */

function renderAI(report) {
    const ai = getAI(report);
    const security = getSecurity(report);
    const quality = getDataQuality(report);

    setText(
        "#executive-summary",
        firstDefined(ai.executive_summary, "No executive summary was returned.")
    );

    setText(
        "#ai-market-structure",
        firstDefined(
            ai.what_matters_now,
            ai.primary_risk_driver,
            ai.risk_regime,
            "No market interpretation available."
        )
    );

    setText("#ai-liquidity", firstDefined(ai.watch_next, "No monitoring guidance returned."));

    const securityFlags = Array.isArray(security.red_flags) ? security.red_flags : [];

    let securityText = firstDefined(security.status, "Unavailable");

    if (securityFlags.length) {
        securityText = securityFlags.map((flag) => String(flag)).join(" • ");
    }

    setText("#ai-contract-risk", securityText);
    applyRiskClass($("#ai-contract-risk"), security.status);

    const missingSignals = Array.isArray(quality.missing_signals)
        ? quality.missing_signals
        : [];

    const hasExecutiveSummary = Boolean(ai.executive_summary);

    let evidenceStatus;

    if (!hasExecutiveSummary) {
        evidenceStatus = "Unavailable";
    } else if (missingSignals.length === 0) {
        evidenceStatus = "Complete backend report";
    } else {
        evidenceStatus = "Some signals unavailable";
    }

    setText("#ai-evidence-status", evidenceStatus);

    setText("#ai-risk-regime", ai.risk_regime);
    setText("#ai-primary-risk-driver", ai.primary_risk_driver);
    setText("#ai-what-changed", ai.what_changed);
    setText("#ai-what-matters-now", ai.what_matters_now);
    setText("#ai-watch-next", ai.watch_next);
    setText("#ai-stress-interpretation", ai.stress_interpretation);

    renderForensicCards(report);
}


/* ============================================================
   FORENSIC / INTELLIGENCE CARDS
   ============================================================ */

function renderForensicCards(report) {
    const container = $("#forensic-cards");
    if (!container) return;

    container.replaceChildren();

    const ai = getAI(report);

    const cards = [
        {
            title: "Primary risk driver",
            value: firstDefined(ai.primary_risk_driver, "Not identified.")
        },
        {
            title: "What changed",
            value: firstDefined(ai.what_changed, "No material change reported.")
        },
        {
            title: "What matters now",
            value: firstDefined(ai.what_matters_now, "No immediate interpretation available.")
        },
        {
            title: "Watch next",
            value: firstDefined(ai.watch_next, "No monitoring signal returned.")
        },
        {
            title: "Stress interpretation",
            value: firstDefined(ai.stress_interpretation, "No stress interpretation returned.")
        }
    ];

    cards.forEach((item) => {
        const card = document.createElement("article");
        card.className = "forensic-card";

        const heading = document.createElement("h4");
        const text = document.createElement("p");

        heading.textContent = item.title;
        text.textContent = String(item.value);

        card.appendChild(heading);
        card.appendChild(text);

        container.appendChild(card);
    });
}
/* ============================================================
   DATA QUALITY — Confidence & Missing Signals Renderer
   ============================================================ */

function renderDataQuality(report) {
    const quality = getDataQuality(report);
    const reportObj = report || {};

    const confidence = firstDefined(
        quality.confidence,
        reportObj.risk_confidence,
        reportObj.ai?.confidence,
        reportObj.risk_profile?.confidence
    );

    setText("#data-confidence", formatConfidence(confidence));

    setText(
        "#market-source",
        firstDefined(reportObj?.market?.source, quality.source, "Backend market feed")
    );

    const timestamp = reportObj?.market?.timestamp;

    setText("#data-freshness", timestamp ? formatRelativeTime(timestamp) : "Unknown");

    renderMissingSignals(firstDefined(quality.missing_signals, quality.missing, []));
}


/* ============================================================
   MISSING SIGNALS — Data Confidence Module
   ============================================================ */

function renderMissingSignals(missing) {
    const container = $("#missing-signals");
    if (!container) return;

    container.replaceChildren();

    let signals = [];

    if (Array.isArray(missing)) {
        signals = missing.filter(
            (signal) => signal !== null && signal !== undefined && String(signal).trim() !== ""
        );
    } else if (typeof missing === "string" && missing.trim()) {
        signals = [missing];
    }

    if (!signals.length) {
        const item = document.createElement("span");
        item.className = "data-ok";
        item.textContent = "All primary risk vectors verified.";
        container.appendChild(item);
        return;
    }

    signals.forEach((signal) => {
        const item = document.createElement("span");
        item.className = "missing-signal";
        item.textContent = String(signal);
        container.appendChild(item);
    });
}


/* ============================================================
   COMPLETE REPORT RENDERER — Main DOM Rendering Pipeline
   ============================================================ */

function renderReport(report) {
    if (!report || typeof report !== "object") {
        clearReportView();
        return;
    }

    console.log("Rendering CryptoRisk report:", report);

    state.latestReport = report;

    state.currentSymbol = firstDefined(
        report?.asset?.symbol,
        report?.token_symbol,
        state.currentSymbol
    );

    renderMarket(report);
    renderRiskProfile(report);
    renderRiskDrivers(report);
    renderStressTest(report);
    renderAI(report);
    renderDataQuality(report);

    updateCurrentReportDeleteButton();

    if (report.generated_at) {
        const generated = document.querySelector("[data-report-generated]");
        if (generated) {
            generated.textContent = formatDate(report.generated_at);
        }
    }
}


/* ============================================================
   DELETE BUTTON STATE
   ============================================================ */

function updateCurrentReportDeleteButton() {
    const button = $("#delete-current-report");
    if (!button) return;

    button.disabled = !state.currentReportId;
}


/* ============================================================
   HISTORY TABLE
   ============================================================ */

function renderHistory(history) {
    const tbody = $("#history-tbody");
    if (!tbody) return;

    tbody.replaceChildren();

    const records = Array.isArray(history) ? history : [];

    setText("#history-count", String(records.length));

    if (!records.length) {
        const row = document.createElement("tr");
        const cell = document.createElement("td");

        cell.colSpan = 6;
        cell.className = "empty-history";
        cell.textContent = "No analyses yet.";

        row.appendChild(cell);
        tbody.appendChild(row);
        return;
    }

    records.forEach((record) => {
        const row = document.createElement("tr");
        row.dataset.reportId = String(record.id);

        const assetCell = createHistoryCell(
            firstDefined(record.token_symbol, record.asset?.symbol, record.symbol, "—")
        );

        const riskCell = document.createElement("td");

        const riskValue = firstDefined(record.risk_label, record.risk_severity, record.label);
        const risk = normalizeSeverity(riskValue);

        const riskBadge = document.createElement("span");
        riskBadge.className = "risk-badge";
        riskBadge.textContent = risk;
        applyRiskClass(riskBadge, risk);

        riskCell.appendChild(riskBadge);

        const outlookCell = createHistoryCell(firstDefined(record.outlook, record.trend, "—"));

        const score = firstDefined(record.risk_score, record.composite_score);
        const scoreCell = createHistoryCell(
            score !== null ? `${formatScore(score)}/100` : "—"
        );

        const dateValue = firstDefined(record.created_at, record.timestamp, record.generated_at);
        const dateCell = createHistoryCell(dateValue ? formatDate(dateValue) : "—");

        const actionCell = document.createElement("td");

        const viewButton = document.createElement("button");
        viewButton.type = "button";
        viewButton.className = "history-view";
        viewButton.textContent = "View";
        viewButton.dataset.action = "view-history";
        viewButton.dataset.id = String(record.id);

        const deleteButton = document.createElement("button");
        deleteButton.type = "button";
        deleteButton.className = "history-delete";
        deleteButton.textContent = "Delete";
        deleteButton.dataset.action = "delete-history";
        deleteButton.dataset.id = String(record.id);

        actionCell.appendChild(viewButton);
        actionCell.appendChild(deleteButton);

        row.appendChild(assetCell);
        row.appendChild(riskCell);
        row.appendChild(outlookCell);
        row.appendChild(scoreCell);
        row.appendChild(dateCell);
        row.appendChild(actionCell);

        tbody.appendChild(row);
    });
}

function createHistoryCell(value) {
    const cell = document.createElement("td");

    cell.textContent =
        value === null || value === undefined || value === "" ? "—" : String(value);

    return cell;
}


/* ============================================================
   HISTORY EVENT DELEGATION
   ============================================================ */

function handleHistoryClick(event) {
    const target = event.target.closest("[data-action]");
    if (!target) return;

    const action = target.dataset.action;
    const id = target.dataset.id;

    if (!id) return;

    event.preventDefault();
    event.stopPropagation();

    if (action === "view-history") {
        loadHistoryReport(id);
        return;
    }

    if (action === "delete-history") {
        deleteReport(id);
    }
}


/* ============================================================
   LOGIN / SIGNUP
   ============================================================ */

async function handleAuthForm(event) {
    const form = event.currentTarget;
    event.preventDefault();

    const action = form.dataset.auth;

    if (action !== "login" && action !== "signup") return;

    const email = form.querySelector("[name='email']")?.value?.trim();
    const password = form.querySelector("[name='password']")?.value;
    const username = form.querySelector("[name='username']")?.value?.trim();

    if (!email || !password) {
        showAnalysisError("Email and password are required.");
        return;
    }

    const endpoint = action === "signup" ? "/api/auth/signup" : "/api/auth/login";

    const body =
        action === "signup" ? { username, email, password } : { email, password };

    try {
        const payload = await apiRequest(endpoint, { method: "POST", body });

        const token = firstDefined(payload.token, payload.access_token);

        if (!token) {
            throw new Error("Authentication succeeded but no session token was returned.");
        }

        saveToken(token);
        window.location.href = "/dashboard";
    } catch (error) {
        showAnalysisError(error.message || "Authentication failed.");
    }
}


/* ============================================================
   KEYBOARD UX
   ============================================================ */

function setupKeyboardShortcuts() {
    document.addEventListener("keydown", (event) => {
        if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey) {
            return;
        }

        const active = document.activeElement;

        const isTyping =
            active &&
            (active.tagName === "INPUT" ||
                active.tagName === "TEXTAREA" ||
                active.isContentEditable);

        if (isTyping) return;

        const input = $("#token-symbol");
        if (!input) return;

        event.preventDefault();
        input.focus();
    });
}


/* ============================================================
   PAGE VISIBILITY
   ============================================================ */

function setupVisibilityHandling() {
    document.addEventListener("visibilitychange", () => {
        if (document.hidden) {
            stopLivePolling();
            return;
        }

        if (state.currentSymbol && state.token) {
            startLivePolling(state.currentSymbol);
        }
    });
}


/* ============================================================
   BEFORE UNLOAD
   ============================================================ */

window.addEventListener("beforeunload", () => {
    stopLivePolling();
});


/* ============================================================
   DOLLAR-SIGN ANALYSIS BEAM
   ============================================================ */

const AnalysisBeam = {
    container: null,
    canvas: null,
    ctx: null,
    particles: [],
    progress: 0,
    targetProgress: 0,
    isAnimating: false,

    create() {
        this.remove();

        this.container = document.createElement('div');
        this.container.className = 'analysis-beam-container';
        this.container.innerHTML = `
            <div class="analysis-beam-overlay"></div>
            <div class="analysis-beam-content">
                <div class="beam-percentage-display">0%</div>
                <div class="beam-progress-track">
                    <div class="beam-progress-fill"></div>
                    <div class="beam-currency-stream"></div>
                </div>
                <div class="beam-status-text">Initializing Analysis...</div>
                <div class="beam-particles-canvas"></div>
            </div>
        `;

        document.body.appendChild(this.container);

        this.canvas = document.createElement('canvas');
        this.canvas.className = 'beam-particle-canvas';
        this.container.querySelector('.beam-particles-canvas').appendChild(this.canvas);
        this.ctx = this.canvas.getContext('2d');

        this.resizeCanvas();
        this.initParticles();
        this.initCurrencySymbols();

        requestAnimationFrame(() => this.container.classList.add('active'));

        this.startParticleLoop();
    },

    startParticleLoop() {
        const loop = () => {
            if (!this.container) return;
            this.renderParticles();
            requestAnimationFrame(loop);
        };
        loop();
    },

    /*
     * FIX: called every frame from startParticleLoop() but was
     * never defined in the original file ("renderParticles is
     * not a function" the instant the beam appeared).
     */
    renderParticles() {
        if (!this.ctx || !this.canvas) return;

        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

        this.particles.forEach((p) => {
            p.x += p.vx;
            p.y += p.vy;
            p.life -= 0.006;

            if (p.life <= 0 || p.y < -10 || p.y > this.canvas.height + 10) {
                p.x = Math.random() * this.canvas.width;
                p.y = this.canvas.height + 10;
                p.vx = (Math.random() - 0.5) * 2;
                p.vy = (Math.random() - 0.5) * 2 - 1;
                p.life = Math.random() * 0.5 + 0.5;
            }

            this.ctx.beginPath();
            this.ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
            this.ctx.fillStyle = p.color;
            this.ctx.globalAlpha = Math.max(0, p.alpha * p.life);
            this.ctx.fill();
            this.ctx.globalAlpha = 1;
        });
    },

    resizeCanvas() {
        if (!this.canvas) return;
        const rect = this.container.getBoundingClientRect();
        this.canvas.width = rect.width;
        this.canvas.height = rect.height;
    },

    initParticles() {
        this.particles = [];
        for (let i = 0; i < 50; i++) {
            this.particles.push({
                x: Math.random() * (this.canvas?.width || 800),
                y: Math.random() * (this.canvas?.height || 200),
                vx: (Math.random() - 0.5) * 2,
                vy: (Math.random() - 0.5) * 2 - 1,
                size: Math.random() * 3 + 1,
                alpha: Math.random() * 0.5 + 0.2,
                color: ['#ffd700', '#ff6b2b', '#39ff14', '#7c3aed'][Math.floor(Math.random() * 4)],
                life: Math.random()
            });
        }
    },

    initCurrencySymbols() {
        const stream = this.container?.querySelector('.beam-currency-stream');
        if (!stream) return;

        const symbols = ['$', '💰', '$', '₿', '$', '💰', '$', '₿', '$', '💰', '$', '₿', '$', '💰'];

        symbols.forEach((symbol, index) => {
            const el = document.createElement('span');
            el.className = 'beam-currency-symbol';
            el.textContent = symbol;
            el.style.animationDelay = `${index * 0.12}s`;
            stream.appendChild(el);
        });
    },

    setProgress(percent) {
        this.targetProgress = Math.min(100, Math.max(0, percent));
        if (!this.isAnimating) this.animateProgress();
    },

    animateProgress() {
        this.isAnimating = true;

        const update = () => {
            const diff = this.targetProgress - this.progress;

            if (Math.abs(diff) < 0.5) {
                this.progress = this.targetProgress;
            } else {
                this.progress += diff * 0.1;
            }

            const fill = this.container?.querySelector('.beam-progress-fill');
            if (fill) fill.style.width = `${this.progress}%`;

            const percentEl = this.container?.querySelector('.beam-percentage-display');
            if (percentEl) percentEl.textContent = `${Math.round(this.progress)}%`;

            const statusEl = this.container?.querySelector('.beam-status-text');
            if (statusEl) {
                if (this.progress < 15) statusEl.textContent = 'Connecting to Market Data...';
                else if (this.progress < 30) statusEl.textContent = 'Fetching Price History...';
                else if (this.progress < 50) statusEl.textContent = 'Running Quantitative Engine...';
                else if (this.progress < 70) statusEl.textContent = 'Building Risk Profile...';
                else if (this.progress < 85) statusEl.textContent = 'Running Stress Tests...';
                else if (this.progress < 95) statusEl.textContent = 'Generating AI Insights...';
                else statusEl.textContent = 'Finalizing Report...';
            }

            if (this.progress < this.targetProgress || Math.abs(diff) > 0.5) {
                requestAnimationFrame(update);
            } else {
                this.isAnimating = false;
                this.triggerWealthBurst();
            }
        };

        update();
    },

    /*
     * FIX: called once the beam reaches its target, but was never
     * defined in the original file — same "not a function" crash
     * as renderParticles above. Gives the particle pool an upward
     * burst so the finish reads as a payoff moment.
     */
    triggerWealthBurst() {
        if (!this.particles || !this.particles.length) return;

        this.particles.forEach((p) => {
            p.vx = (Math.random() - 0.5) * 6;
            p.vy = -(Math.random() * 6 + 2);
            p.life = 1;
            p.alpha = Math.random() * 0.5 + 0.5;
        });
    },

    remove() {
        if (this.container) {
            this.container.classList.remove('active');
            setTimeout(() => {
                if (this.container?.parentNode) this.container.parentNode.removeChild(this.container);
                this.container = null;
            }, 500);
        }
    }
};


/* ============================================================
   MONEY METEOR — Burning Bitcoin + Fiery Dollar Bill Particle System
   ============================================================

   FIX: the original file declared `const MoneyMeteor = {...}` a
   SECOND time later on, and that second copy had its methods
   pasted in as bare statements outside any object body (plus a
   dangling `spawnMeteor()` fragment with mismatched property
   names). That's an immediate SyntaxError. This is the single,
   consolidated, working version, using the short property names
   (sSize, isB, cCore, rot, rotSpd, len) since those are what
   drawTrail/drawCore/updM/animate actually read.
   ============================================================ */

const MoneyMeteor = {
    canvas: null, ctx: null,
    meteors: [], particles: [],
    bitcoinSymbols: [], dollarBillSymbols: [],
    animationId: null, isRunning: false,
    lastSpawn: 0, spawnInterval: 800,
    W: 0, H: 0,

    init() {
        this.canvas = document.getElementById('meteor-canvas');
        if (!this.canvas) return;
        this.ctx = this.canvas.getContext('2d');
        this.resize();
        window.addEventListener('resize', () => this.resize());
        this.isRunning = true;
        this.animate();
    },

    resize() {
        this.W = window.innerWidth;
        this.H = window.innerHeight;
        this.canvas.width = this.W;
        this.canvas.height = this.H;
    },

    spawnMeteor() {
        const angle = -Math.PI / 2 + (Math.random() - 0.5) * 0.6;
        const speed = 6 + Math.random() * 10;
        const sx = Math.random() * this.W;
        const sy = -40 - Math.random() * 100;
        const isB = Math.random() < 0.5;
        const sym = isB ? String.fromCharCode(0x0243) : '$';
        const sSize = isB ? 28 + Math.random() * 12 : 22 + Math.random() * 8;
        const cCore = isB ? '#fffbe6' : '#ff4500';

        this.meteors.push({
            x: sx, y: sy,
            vx: Math.cos(angle) * speed,
            vy: Math.sin(angle) * speed,
            life: 1.0,
            decay: 0.005 + Math.random() * 0.008,
            len: 120 + Math.random() * 200,
            isB, sym, sSize,
            colorMain: isB ? '#ffd700' : '#ff6b2b',
            cCore, tail: [],
            rot: Math.random() * Math.PI * 2,
            rotSpd: (Math.random() - 0.5) * 0.1
        });
    },

    updM(m) {
        m.x += m.vx; m.y += m.vy;
        m.rot += m.rotSpd;
        m.life -= m.decay;

        const tLen = Math.floor(m.len * (0.3 + Math.random() * 0.4));
        m.tail.unshift({ x: m.x, y: m.y, life: 1 });
        if (m.tail.length > tLen) m.tail.pop();
        m.tail.forEach((p) => (p.life -= 0.025 + Math.random() * 0.02));

        if (m.life <= 0) return;

        if (Math.random() < 0.35) {
            this.particles.push({
                x: m.x + (Math.random() - 0.5) * 10,
                y: m.y + (Math.random() - 0.5) * 10,
                vx: (Math.random() - 0.5) * 2,
                vy: (Math.random() - 0.5) * 2 - 0.5,
                life: 1,
                decay: 0.02 + Math.random() * 0.03,
                size: 1.5 + Math.random() * 2.5,
                isB: m.isB
            });
        }

        if (Math.random() < 0.15) {
            this.bitcoinSymbols.push({
                x: m.x + (Math.random() - 0.5) * m.len * 0.5,
                y: m.y + (Math.random() - 0.5) * m.len * 0.5,
                vx: (Math.random() - 0.5) * 0.3,
                vy: -0.3 - Math.random() * 0.6,
                life: 1,
                decay: 0.015 + Math.random() * 0.015,
                size: 8 + Math.random() * 6,
                rot: Math.random() * Math.PI * 2,
                rotSpd: (Math.random() - 0.5) * 0.1
            });
        }

        if (Math.random() < 0.12) {
            this.dollarBillSymbols.push({
                x: m.x + (Math.random() - 0.5) * m.len * 0.3,
                y: m.y + (Math.random() - 0.5) * m.len * 0.3,
                vx: (Math.random() - 0.5) * 0.4,
                vy: -0.4 - Math.random() * 0.8,
                life: 1,
                decay: 0.012 + Math.random() * 0.012,
                size: 7 + Math.random() * 5,
                rot: Math.random() * Math.PI * 2,
                rotSpd: (Math.random() - 0.5) * 0.12
            });
        }
    },

    drawTrail(m) {
        const ctx = this.ctx, tail = m.tail;

        for (let i = 1; i < tail.length; i++) {
            const p = tail[i];
            const a = p.life * m.life * 0.8;
            if (a <= 0) continue;

            const w = (i / tail.length) * (m.isB ? 6 : 4) * m.life;
            const g = ctx.createLinearGradient(tail[i - 1].x, tail[i - 1].y, p.x, p.y);

            if (m.isB) {
                g.addColorStop(0, `rgba(255,255,200,${a})`);
                g.addColorStop(0.4, `rgba(255,180,50,${a * 0.9})`);
                g.addColorStop(0.7, `rgba(255,100,20,${a * 0.6})`);
                g.addColorStop(1, `rgba(255,50,0,${a * 0.1})`);
            } else {
                g.addColorStop(0, `rgba(255,220,100,${a})`);
                g.addColorStop(0.4, `rgba(255,120,20,${a * 0.9})`);
                g.addColorStop(0.7, `rgba(200,30,0,${a * 0.6})`);
                g.addColorStop(1, `rgba(100,0,0,${a * 0.05})`);
            }

            ctx.beginPath();
            ctx.arc(p.x, p.y, w, 0, Math.PI * 2);
            ctx.fillStyle = g;
            ctx.fill();
        }
    },

    drawCore(m) {
        const ctx = this.ctx, s = m.sSize;

        ctx.save();
        ctx.translate(m.x, m.y);
        ctx.rotate(m.rot);

        const gr = s * 1.8;
        const glow = ctx.createRadialGradient(0, 0, s * 0.2, 0, 0, gr);

        if (m.isB) {
            glow.addColorStop(0, 'rgba(255,255,220,0.9)');
            glow.addColorStop(0.3, 'rgba(255,200,80,0.6)');
            glow.addColorStop(0.7, 'rgba(255,120,20,0.2)');
            glow.addColorStop(1, 'rgba(255,60,0,0)');
        } else {
            glow.addColorStop(0, 'rgba(255,200,100,0.9)');
            glow.addColorStop(0.3, 'rgba(255,100,20,0.6)');
            glow.addColorStop(0.7, 'rgba(200,30,0,0.25)');
            glow.addColorStop(1, 'rgba(80,0,0,0)');
        }

        ctx.beginPath();
        ctx.arc(0, 0, gr, 0, Math.PI * 2);
        ctx.fillStyle = glow;
        ctx.fill();

        ctx.font = s + 'px JetBrains Mono, Fira Code, monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.shadowColor = m.isB ? '#ffd700' : '#ff4500';
        ctx.shadowBlur = 25;
        ctx.fillStyle = m.cCore;
        ctx.fillText(m.sym, 0, 0);
        ctx.shadowBlur = 0;

        ctx.font = (s * 0.85) + 'px JetBrains Mono, Fira Code, monospace';
        ctx.fillStyle = '#fff';
        ctx.fillText(m.sym, 0, 0);

        ctx.restore();
    },

    updParticles() {
        const ctx = this.ctx;

        for (let i = this.particles.length - 1; i >= 0; i--) {
            const p = this.particles[i];
            p.x += p.vx; p.y += p.vy;
            p.vy -= 0.02;
            p.life -= p.decay;

            if (p.life <= 0) { this.particles.splice(i, 1); continue; }

            const hue = p.isB ? 45 + Math.random() * 20 : 20 + Math.random() * 20;
            const lit = p.isB ? 50 + Math.random() * 30 : 40 + Math.random() * 30;

            ctx.beginPath();
            ctx.arc(p.x, p.y, p.size * p.life, 0, Math.PI * 2);
            ctx.fillStyle = `hsla(${hue},100%,${lit}%,${p.life * 0.8})`;
            ctx.fill();
        }
    },

    updBtcSym() {
        const ctx = this.ctx;

        for (let i = this.bitcoinSymbols.length - 1; i >= 0; i--) {
            const b = this.bitcoinSymbols[i];
            b.x += b.vx; b.y += b.vy;
            b.vy -= 0.01;
            b.rot += b.rotSpd;
            b.life -= b.decay;

            if (b.life <= 0) { this.bitcoinSymbols.splice(i, 1); continue; }

            ctx.save();
            ctx.translate(b.x, b.y);
            ctx.rotate(b.rot);
            ctx.globalAlpha = b.life;
            ctx.font = b.size + 'px JetBrains Mono, Fira Code, monospace';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.shadowColor = '#ffd700';
            ctx.shadowBlur = 12;
            ctx.fillStyle = '#ffd700';
            ctx.fillText(String.fromCharCode(0x0243), 0, 0);
            ctx.shadowBlur = 0;
            ctx.globalAlpha = 1;
            ctx.restore();
        }
    },

    updDollarSym() {
        const ctx = this.ctx;

        for (let i = this.dollarBillSymbols.length - 1; i >= 0; i--) {
            const d = this.dollarBillSymbols[i];
            d.x += d.vx; d.y += d.vy;
            d.vy -= 0.015;
            d.rot += d.rotSpd;
            d.life -= d.decay;

            if (d.life <= 0) { this.dollarBillSymbols.splice(i, 1); continue; }

            ctx.save();
            ctx.translate(d.x, d.y);
            ctx.rotate(d.rot);
            ctx.globalAlpha = d.life * 0.9;
            ctx.font = d.size + 'px JetBrains Mono, Fira Code, monospace';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.shadowColor = '#ff4500';
            ctx.shadowBlur = 10;
            ctx.fillStyle = d.life > 0.5 ? '#ff4500' : '#ffd700';
            ctx.fillText('$', 0, 0);
            ctx.shadowBlur = 0;
            ctx.globalAlpha = 1;
            ctx.restore();
        }
    },

    drawBgGlow() {
        const ctx = this.ctx;
        if (!ctx) return;

        const g1 = ctx.createRadialGradient(this.W / 2, this.H * 0.7, 0, this.W / 2, this.H * 0.7, this.W * 0.7);
        g1.addColorStop(0, 'rgba(255,100,20,0.04)');
        g1.addColorStop(0.5, 'rgba(255,60,0,0.02)');
        g1.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = g1;
        ctx.fillRect(0, 0, this.W, this.H);

        const g2 = ctx.createRadialGradient(this.W * 0.2, this.H * 0.3, 0, this.W * 0.2, this.H * 0.3, this.W * 0.4);
        g2.addColorStop(0, 'rgba(255,215,0,0.03)');
        g2.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = g2;
        ctx.fillRect(0, 0, this.W, this.H);
    },

    animate() {
        if (!this.isRunning) return;

        const ctx = this.ctx;
        if (!ctx) return;

        ctx.clearRect(0, 0, this.W, this.H);
        this.drawBgGlow();

        const now = performance.now();
        if (now - this.lastSpawn > this.spawnInterval) {
            this.spawnMeteor();
            this.lastSpawn = now;
            this.spawnInterval = 600 + Math.random() * 600;
        }

        for (let i = this.meteors.length - 1; i >= 0; i--) {
            const m = this.meteors[i];
            this.updM(m);

            if (m.life <= 0 || m.y > this.H + 50 || m.x < -100 || m.x > this.W + 100) {
                this.meteors.splice(i, 1);
                continue;
            }

            this.drawTrail(m);
            this.drawCore(m);
        }

        this.updBtcSym();
        this.updDollarSym();
        this.updParticles();

        this.animationId = requestAnimationFrame(() => this.animate());
    }
};


/* ============================================================
   FINAL DOM INITIALIZATION
   ============================================================ */

document.addEventListener("DOMContentLoaded", () => {
    CursorPhysics.init();

    if (document.getElementById("meteor-canvas")) {
        MoneyMeteor.init();
    }

    const analysisForm = $("#analysis-form");
    if (analysisForm) {
        analysisForm.addEventListener("submit", handleAnalysisSubmit);
    }

    const logoutButtons = $all("[data-action='logout'], #logout-button");
    logoutButtons.forEach((button) => {
        button.addEventListener("click", (event) => {
            event.preventDefault();
            logout();
        });
    });

    const deleteButton = $("#delete-current-report");
    if (deleteButton) {
        deleteButton.addEventListener("click", async () => {
            await deleteCurrentReport();
        });
    }

    const historyBody = $("#history-tbody");
    if (historyBody) {
        historyBody.addEventListener("click", handleHistoryClick);
    }

    $all("form[data-auth]").forEach((form) => {
        form.addEventListener("submit", handleAuthForm);
    });

    setupKeyboardShortcuts();
    setupVisibilityHandling();

    if (document.querySelector("#analysis-form")) {
        initializeDashboard();
    } else {
        initializeIndexPage();
    }
});


/* ============================================================
   GLOBAL ERROR SAFETY
   ============================================================ */

window.addEventListener("error", (event) => {
    console.error("Frontend error:", event.error || event.message);
});

window.addEventListener("unhandledrejection", (event) => {
    console.error("Unhandled promise rejection:", event.reason);
});


/* ============================================================
   END OF SCRIPT
   ============================================================ */