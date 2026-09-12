"use strict";

/*
 * ============================================================
 * CryptoRisk AI — Dashboard Controller
 * Backend Report Schema: 3.0
 *
 * Backend is the single source of truth.
 *
 * FIX (this revision):
 *  - CRITICAL: runAnalysis() now uses the async job flow
 *    (POST /api/analyze/start -> poll GET /api/analyze/status/<id>)
 *    instead of the synchronous POST /api/analyze call.
 *    The synchronous endpoint runs the ENTIRE pipeline (market +
 *    history x2 + quant + security + stress + Gemini) inside a
 *    single HTTP request/response cycle, which can take 30-60s+
 *    worst case. Any reverse proxy / browser / host timeout in
 *    that window kills the request with no useful error, which
 *    is why "click Analyze" could look like it does nothing, and
 *    why reports sometimes came back cut off (client gave up
 *    mid-request while backend was still working).
 *  - Progress bar is now driven by REAL backend stage/progress
 *    values from the job status endpoint instead of a fake
 *    fixed-duration animation.
 *  - Added a hard client-side polling timeout + visible error
 *    if a job gets stuck, instead of polling forever silently.
 *  - Kept all previously-existing robustness fixes (nested
 *    response extraction, live market polling, etc.)
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
    animationId: null,

    init() {
        this.tokens = document.querySelectorAll(".physics-token");

        if (!this.tokens.length) return;

        this.isActive = true;

        document.addEventListener("mousemove", (event) => {
            this.targetX = event.clientX;
            this.targetY = event.clientY;
        });

        this.animate();
    },

    animate() {
        if (!this.isActive) return;

        this.cursorX += (this.targetX - this.cursorX) * 0.08;
        this.cursorY += (this.targetY - this.cursorY) * 0.08;

        this.tokens.forEach((token, index) => {
            const rect = token.getBoundingClientRect();

            const centerX = rect.left + rect.width / 2;
            const centerY = rect.top + rect.height / 2;

            const deltaX = centerX - this.cursorX;
            const deltaY = centerY - this.cursorY;

            const distance = Math.sqrt(
                deltaX * deltaX + deltaY * deltaY
            );

            const repulsionRadius = 250;

            if (distance < repulsionRadius && distance > 0) {
                const force =
                    Math.pow(
                        1 - distance / repulsionRadius,
                        2
                    ) * 60;

                const dirX = deltaX / distance;
                const dirY = deltaY / distance;

                const displacementX = dirX * force;
                const displacementY = dirY * force;
                const displacementZ = force * 0.5 + index * 10;

                token.style.transform =
                    `translate3d(${displacementX}px, ${displacementY}px, ${displacementZ}px) ` +
                    `rotateZ(${dirX * 5}deg)`;
            } else {
                token.style.transform = "";
            }
        });

        this.animationId = requestAnimationFrame(() => this.animate());
    },

    destroy() {
        this.isActive = false;

        if (this.animationId) {
            cancelAnimationFrame(this.animationId);
            this.animationId = null;
        }
    }
};


/* ============================================================
   API
   ============================================================ */

const API = {
    dashboard: "/api/dashboard",

    // FIX: analyze is now the async job-start endpoint, not the
    // synchronous endpoint. See runAnalysis() below.
    analyzeStart: "/api/analyze/start",
    analyzeStatus: (jobId) =>
        `/api/analyze/status/${encodeURIComponent(jobId)}`,

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
   JOB POLLING CONFIG
   ============================================================ */

const JOB_POLL_INTERVAL_MS = 1500;

// FIX (Bug 7): JOB_POLL_MAX_MS is no longer hardcoded at 340000.
// It is derived from the backend's real ANALYSIS_JOB_TIMEOUT_SECONDS
// (exposed via GET /health as "analysis_job_timeout_seconds") plus a
// 60s headroom, and refreshed at startup by syncJobPollCeiling().
// The value below is only the fallback for when /health is
// unreachable (backend default is 150s).
const JOB_POLL_DEFAULT_TIMEOUT_SECONDS = 150;
const JOB_POLL_HEADROOM_MS = 60000;

let JOB_POLL_MAX_MS =
    JOB_POLL_DEFAULT_TIMEOUT_SECONDS * 1000 +
    JOB_POLL_HEADROOM_MS;

async function syncJobPollCeiling() {
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
   APPLICATION STATE
   ============================================================ */

const state = {
    token: null,
    user: null,
    latestReport: null,
    currentReportId: null,
    currentSymbol: null,

    livePollTimer: null,
    liveRequestId: 0,
    isLiveRequestInFlight: false,

    // FIX (Bug 3): timestamp of the last live market fetch, used to
    // avoid an unnecessary immediate request when the tab becomes
    // visible again within the market cache window.
    lastLiveMarketFetchAt: 0,

    isAnalyzing: false,

    // Job polling state
    activeJobId: null,
    jobPollTimer: null,
    jobPollStartedAt: 0
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


/* ============================================================
   SAFE VALUE HELPERS
   ============================================================ */

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

function isPlainObject(value) {
    return (
        value !== null &&
        typeof value === "object" &&
        !Array.isArray(value)
    );
}

function normalizeSymbol(symbol) {
    if (symbol === null || symbol === undefined) {
        return null;
    }

    const normalized = String(symbol)
        .trim()
        .toUpperCase();

    return normalized || null;
}

function normalizeSource(source) {
    if (
        source === null ||
        source === undefined ||
        source === ""
    ) {
        return "Backend market feed";
    }

    const text = String(source).trim();

    const normalized = text.toLowerCase();

    if (
        normalized.includes("coingecko") ||
        normalized === "coin gecko"
    ) {
        return "CoinGecko";
    }


    if (normalized.includes("backend")) {
        return "Backend market feed";
    }

    return text;
}


/* ============================================================
   AUTH
   ============================================================ */

function getTokenFromStorage() {
    try {
        return localStorage.getItem(STORAGE_KEYS.token);
    } catch (error) {
        console.warn("Unable to read auth token:", error);
        return null;
    }
}

function saveToken(token) {
    if (!token) return;

    state.token = token;

    try {
        localStorage.setItem(
            STORAGE_KEYS.token,
            token
        );
    } catch (error) {
        console.warn("Unable to save auth token:", error);
    }
}

function clearToken() {
    state.token = null;

    try {
        localStorage.removeItem(STORAGE_KEYS.token);
    } catch (error) {
        console.warn("Unable to clear auth token:", error);
    }
}

function consumeQueryToken() {
    const params = new URLSearchParams(
        window.location.search
    );

    const token = params.get("token");

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

    if (!state.token) {
        state.token = token;
    }

    return {
        Authorization: `Bearer ${token}`
    };
}

function redirectToHome() {
    clearToken();
    stopLivePolling();
    stopJobPolling();

    window.location.href = "/";
}


/* ============================================================
   API URL RESOLUTION
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


/* ============================================================
   API REQUEST LAYER
   ============================================================ */

async function apiRequest(url, options = {}) {
    const resolvedUrl = resolveApiUrl(url);

    let requestOptions = {
        ...options
    };

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

        requestOptions.body =
            JSON.stringify(options.body);
    }

    requestOptions.headers = headers;

    let response;

    try {
        response = await fetch(
            resolvedUrl,
            requestOptions
        );
    } catch (error) {
        console.error(
            "Network error:",
            error
        );

        const networkError = new Error(
            "Unable to connect to the CryptoRisk backend. Check that the backend is running and reachable."
        );

        networkError.code = "NETWORK_ERROR";

        throw networkError;
    }

    let payload = null;

    const contentType =
        response.headers.get("content-type") || "";

    if (
        contentType
            .toLowerCase()
            .includes("application/json")
    ) {
        try {
            payload = await response.json();
        } catch (error) {
            console.warn(
                "Could not parse JSON response.",
                error
            );

            if (response.ok) {
                const parseError = new Error(
                    "Backend returned an invalid JSON response."
                );

                parseError.code =
                    "INVALID_JSON";

                throw parseError;
            }
        }
    } else {
        try {
            const text = await response.text();

            if (text) {
                payload = {
                    message: text
                };
            }
        } catch (error) {
            console.warn(
                "Could not read backend response.",
                error
            );
        }
    }

    if (response.status === 401) {
        clearToken();
        stopLivePolling();
        stopJobPolling();

        if (
            window.location.pathname !== "/" &&
            window.location.pathname !== ""
        ) {
            window.location.href = "/";
        }

        const authError = new Error(
            payload?.message ||
            payload?.error ||
            "Your session has expired."
        );

        authError.status = 401;
        authError.code = "AUTH_EXPIRED";

        throw authError;
    }

    if (!response.ok) {
        let message =
            payload?.message ||
            payload?.error ||
            payload?.detail;

        if (!message) {
            switch (response.status) {
                case 404:
                    message =
                        "The requested CryptoRisk endpoint was not found.";
                    break;

                case 429:
                    message =
                        "The market data service is rate-limited. Please try again shortly.";
                    break;

                case 500:
                    message =
                        "CryptoRisk backend returned an internal server error.";
                    break;

                case 502:
                    message =
                        "CryptoRisk backend received a bad upstream response.";
                    break;

                case 503:
                    message =
                        "CryptoRisk backend is temporarily unavailable.";
                    break;

                default:
                    message =
                        `Request failed (${response.status}).`;
            }
        }

        const requestError = new Error(
            String(message)
        );

        requestError.status =
            response.status;

        requestError.payload = payload;

        // FIX (Bug 5/6): surface the backend's error code (e.g.
        // UNSUPPORTED_ASSET, MARKET_DATA_UNAVAILABLE) on the Error so
        // the UI can translate it into a friendly message instead of
        // showing a raw provider error string.
        requestError.code =
            payload?.code ||
            null;

        throw requestError;
    }

    return payload || {};
}

function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
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

    element.textContent =
        message || "Something went wrong.";

    show(element);
}

function clearAnalysisError() {
    const element = $("#analysis-error");

    if (!element) return;

    element.textContent = "";

    hide(element);
}


/* ============================================================
   FRIENDLY ERROR MESSAGES
   ============================================================
   FIX (Bug 6): the backend/API layer produces raw error strings
   like "CoinGecko returned HTTP 429; retry_after=12." — meaningless
   (and scary) to users who don't know what CoinGecko is. This
   translator maps known error codes / patterns to user-facing text
   and falls back to the original message for anything unknown.
   ============================================================ */

function friendlyErrorMessage(error) {
    const raw =
        error instanceof Error
            ? error.message || ""
            : String(error || "");

    const code =
        error && typeof error === "object"
            ? String(error.code || "")
            : "";

    const haystack =
        `${code} ${raw}`.toLowerCase();

    // Unsupported token — a distinct 400 from the backend, or a
    // failed job whose error mentions an unsupported asset.
    if (
        code === "UNSUPPORTED_ASSET" ||
        haystack.includes("unsupported asset")
    ) {
        return "This token isn't supported yet.";
    }

    // Rate limiting / provider cooldown.
    if (
        code === "MARKET_DATA_UNAVAILABLE" ||
        haystack.includes("429") ||
        haystack.includes("rate limit") ||
        haystack.includes("rate-limit") ||
        haystack.includes("rate-limited") ||
        haystack.includes("cooldown") ||
        haystack.includes("cooling down")
    ) {
        return "Market data provider is temporarily busy — please retry in about a minute.";
    }

    // Timed-out / orphaned jobs (server-side activity timeout or
    // the client-side polling ceiling).
    if (
        haystack.includes("timed out") ||
        haystack.includes("timeout") ||
        haystack.includes("taking much longer") ||
        haystack.includes("took too long")
    ) {
        return "Analysis took too long and timed out — please try again.";
    }

    // Unknown — keep the existing message.
    return raw;
}


/* ============================================================
   USER UI
   ============================================================ */

function renderUser(user) {
    if (!isPlainObject(user)) {
        return;
    }

    state.user = user;

    const displayName = firstDefined(
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

    avatars.forEach((avatar) => {
        if (user.avatar_url) {
            avatar.src = user.avatar_url;
            avatar.alt = String(
                displayName
            );
        } else {
            avatar.removeAttribute("src");
            avatar.alt = String(
                displayName
            );
        }
    });
}


/* ============================================================
   PROGRESS SYSTEM
   ============================================================
   FIX: this now maps the backend's real `stage` values
   (market, history, quant, risk, security, stress, evidence,
   ai, save, complete — see ANALYSIS_STAGES in app.py) onto a
   visual progress bar, driven by real polled data instead of
   a fixed-duration fake animation.
   ============================================================ */

const PROGRESS_STAGES = {
    market: {
        percent: 15,
        title: "Fetching live market data"
    },
    history: {
        percent: 30,
        title: "Loading historical price data"
    },
    quant: {
        percent: 48,
        title: "Running quantitative risk engine"
    },
    risk: {
        percent: 60,
        title: "Building composite risk profile"
    },
    security: {
        percent: 68,
        title: "Checking structural risk signals"
    },
    stress: {
        percent: 76,
        title: "Running stress scenarios"
    },
    evidence: {
        percent: 84,
        title: "Building evidence package"
    },
    ai: {
        percent: 92,
        title: "Synthesizing AI intelligence"
    },
    save: {
        percent: 97,
        title: "Saving intelligence report"
    },
    complete: {
        percent: 100,
        title: "Analysis complete"
    },

    // Fallback stage names the backend may send early/on error
    queued: {
        percent: 5,
        title: "Queued"
    },
    initializing: {
        percent: 8,
        title: "Initializing intelligence engine"
    },
    error: {
        percent: 100,
        title: "Analysis failed"
    },
    timeout: {
        percent: 100,
        title: "Analysis timed out"
    }
};

const PROGRESS_ORDER = [
    "market",
    "history",
    "quant",
    "risk",
    "security",
    "stress",
    "evidence",
    "ai",
    "save"
];

let _progressAnim = null;
let _progressCurrent = 0;

function updateProgressDOM(
    current,
    stageName,
    titleOverride = null
) {
    const fill = $("#progress-fill");
    const percentEl =
        $("#progress-percent");

    const clamped = Math.max(
        0,
        Math.min(100, current)
    );

    const config =
        PROGRESS_STAGES[stageName] ||
        PROGRESS_STAGES.market;

    if (fill) {
        fill.style.width =
            `${clamped}%`;
    }

    if (percentEl) {
        percentEl.textContent =
            `${Math.round(clamped)}%`;
    }

    setText(
        "#progress-title",
        titleOverride || config.title
    );

    const currentIndex =
        PROGRESS_ORDER.indexOf(
            stageName
        );

    $all(".progress-status")
        .forEach((element) => {
            element.classList.remove(
                "active",
                "complete"
            );

            const index =
                PROGRESS_ORDER.indexOf(
                    element.dataset.stage
                );

            if (index < 0) return;

            if (
                currentIndex >= 0 &&
                index < currentIndex
            ) {
                element.classList.add(
                    "complete"
                );
            }

            if (
                index === currentIndex
            ) {
                element.classList.add(
                    "active"
                );
            }
        });
}

/**
 * Smoothly animates the visible progress bar from its current
 * value toward a target percent. Used to make discrete backend
 * poll updates (e.g. jumps from 20% -> 48%) look smooth instead
 * of snapping instantly.
 */
function animateProgressTo(
    targetPercent,
    stageName,
    titleOverride = null,
    durationMs = 500
) {
    const target = Math.max(
        0,
        Math.min(100, targetPercent)
    );

    if (_progressAnim) {
        cancelAnimationFrame(
            _progressAnim
        );

        _progressAnim = null;
    }

    const startPercent = _progressCurrent;
    const startTime = performance.now();

    // If target is behind current (shouldn't normally happen),
    // just jump — never animate backwards.
    if (target <= startPercent) {
        _progressCurrent = target;
        updateProgressDOM(target, stageName, titleOverride);
        return;
    }

    function frame(now) {
        const elapsed = now - startTime;
        const t = Math.min(elapsed / durationMs, 1);
        const eased = 1 - Math.pow(1 - t, 3);

        const current =
            startPercent + (target - startPercent) * eased;

        _progressCurrent = current;

        updateProgressDOM(current, stageName, titleOverride);

        if (t < 1) {
            _progressAnim = requestAnimationFrame(frame);
            return;
        }

        _progressCurrent = target;
        updateProgressDOM(target, stageName, titleOverride);
        _progressAnim = null;
    }

    _progressAnim = requestAnimationFrame(frame);
}

function startProgress() {
    const overlay =
        $("#analysis-progress");

    if (overlay) {
        show(overlay);
    }

    _progressCurrent = 0;

    updateProgressDOM(1, "queued", "Starting analysis…");

    if (
        typeof AnalysisBeam !==
        "undefined"
    ) {
        AnalysisBeam.create();
        AnalysisBeam.setProgress(1);
    }
}

/**
 * Called on every successful job-status poll with the real
 * backend progress/stage/title/message.
 */
function applyJobProgress(job) {
    if (!job) return;

    const percent = Number(job.progress);
    const stage = job.stage || "market";
    const title = job.stage_title || job.message || null;

    const safePercent = Number.isFinite(percent)
        ? percent
        : (PROGRESS_STAGES[stage]?.percent ?? _progressCurrent);

    animateProgressTo(safePercent, stage, title, 500);

    if (
        typeof AnalysisBeam !== "undefined"
    ) {
        AnalysisBeam.setProgress(safePercent);
    }
}

function finishProgress() {
    const overlay =
        $("#analysis-progress");

    animateProgressTo(100, "complete", "Analysis complete", 400);

    if (
        typeof AnalysisBeam !==
        "undefined"
    ) {
        AnalysisBeam.setProgress(100);
    }

    setTimeout(() => {
        if (overlay) {
            hide(overlay);
        }

        if (
            typeof AnalysisBeam !==
            "undefined"
        ) {
            AnalysisBeam.remove();
        }
    }, 700);
}

function abortProgress() {
    const overlay = $("#analysis-progress");

    if (_progressAnim) {
        cancelAnimationFrame(_progressAnim);
        _progressAnim = null;
    }

    if (overlay) {
        hide(overlay);
    }

    if (typeof AnalysisBeam !== "undefined") {
        AnalysisBeam.remove();
    }
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

    const number = Number(value);

    if (!Number.isFinite(number)) {
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

    const number = Number(value);

    if (!Number.isFinite(number)) {
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

function formatPercent(value) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "—";
    }

    const number = Number(value);

    if (!Number.isFinite(number)) {
        return "—";
    }

    const sign =
        number > 0 ? "+" : "";

    return `${sign}${number.toFixed(
        2
    )}%`;
}

function formatScore(value) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "—";
    }

    const number = Number(value);

    if (!Number.isFinite(number)) {
        return "—";
    }

    return Math.round(number);
}

function formatConfidence(value) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "—";
    }

    const number = Number(value);

    if (!Number.isFinite(number)) {
        return "—";
    }

    /*
     * Supports both:
     * 0.82  -> 82.0%
     * 82    -> 82.0%
     */
    const normalized =
        number >= 0 &&
        number <= 1
            ? number * 100
            : number;

    return `${normalized.toFixed(
        1
    )}%`;
}

function formatDate(value) {
    if (!value) return "—";

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

function formatRelativeTime(value) {
    if (!value) return "—";

    const date =
        new Date(value);

    if (
        Number.isNaN(
            date.getTime()
        )
    ) {
        return formatDate(value);
    }

    const seconds = Math.floor(
        (Date.now() -
            date.getTime()) /
            1000
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
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return null;
    }

    const number = Number(value);

    if (!Number.isFinite(number)) {
        return null;
    }

    return Math.max(
        0,
        Math.min(100, number)
    );
}


/* ============================================================
   REPORT EXTRACTION
   ============================================================ */

function isRiskReport(value) {
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

function getReportFromPayload(
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

function getMarketFromPayload(
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

function getRiskProfile(report) {
    return isPlainObject(
        report?.risk_profile
    )
        ? report.risk_profile
        : {};
}

function getPillars(report) {
    const pillars =
        getRiskProfile(report)
            .pillars;

    return isPlainObject(pillars)
        ? pillars
        : {};
}

function getPillar(
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

function getAI(report) {
    return isPlainObject(report?.ai)
        ? report.ai
        : {};
}

function getMarket(report) {
    return isPlainObject(report?.market)
        ? report.market
        : {};
}

function getSecurity(report) {
    return isPlainObject(
        report?.security
    )
        ? report.security
        : {};
}

function getStress(report) {
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

function getDataQuality(report) {
    return isPlainObject(
        report?.data_quality
    )
        ? report.data_quality
        : {};
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

function stopJobPolling() {
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
function pollAnalysisJob(jobId) {
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

async function runAnalysis(
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

async function loadHistoryReport(
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

async function deleteReport(id) {
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

async function deleteCurrentReport() {
    if (!state.currentReportId) {
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
        stopJobPolling();

        window.location.href = "/";
    }
}


/* ============================================================
   LIVE MARKET POLLING
   ============================================================ */

// FIX (Bug 3): raised from 15s to 30s. With CoinGecko free-tier
// limits, a 15s interval alone could exhaust quota when a dashboard
// tab was left open, causing later /api/analyze calls to hit the
// provider cooldown and return available: false.
const LIVE_MARKET_POLL_INTERVAL_MS = 30000;

function stopLivePolling() {
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

function startLivePolling(symbol) {
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
    if (!document.hidden) {
        const sinceLastFetch =
            Date.now() -
            (state.lastLiveMarketFetchAt || 0);

        if (sinceLastFetch >= LIVE_MARKET_POLL_INTERVAL_MS) {
            refreshLiveMarket(
                normalizedSymbol
            );
        }
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

async function refreshLiveMarket(
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
    state.lastLiveMarketFetchAt =
        Date.now();

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

function setMarketLiveState(
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

function updateLiveMarket(
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

    const source =
        normalizeSource(
            firstDefined(
                market.source,
                market.provider,
                market.data_source
            )
        );

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

                bar.classList.remove(
                    "risk-low",
                    "risk-moderate",
                    "risk-high",
                    "risk-critical"
                );
            }

            const value =
                $(`#pillar-${name}-value`);

            if (value) {
                value.classList.remove(
                    "risk-low",
                    "risk-moderate",
                    "risk-high",
                    "risk-critical"
                );
            }
        }
    );

    const drivers =
        $("#risk-drivers");

    if (drivers) {
        drivers.replaceChildren();
    }

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

    setText(
        "#data-confidence",
        "—"
    );

    setText(
        "#data-freshness",
        "—"
    );

    renderMissingSignals([]);

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

    if (!input) return;

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

    // FIX (Bug 2): optional contract security inputs. The backend
    // runs the GoPlus structural check only when BOTH chain_id and
    // contract_address are provided; leaving them blank is fine and
    // is reported as "not applicable" (not a missing signal).
    const chainIdInput =
        $("#chain-id");

    const contractAddressInput =
        $("#contract-address");

    const chainIdValue = chainIdInput
        ? String(chainIdInput.value || "").trim()
        : "";

    const contractAddressValue = contractAddressInput
        ? String(contractAddressInput.value || "").trim()
        : "";

    if (
        contractAddressValue &&
        !/^0x[a-fA-F0-9]{40}$/.test(
            contractAddressValue
        )
    ) {
        showAnalysisError(
            "Enter a valid contract address (0x followed by 40 hex characters) or leave it blank."
        );

        if (contractAddressInput) {
            contractAddressInput.focus();
        }

        return;
    }

    if (
        contractAddressValue &&
        !chainIdValue
    ) {
        showAnalysisError(
            "Select a chain for the contract security check, or leave the address blank."
        );

        if (chainIdInput) {
            chainIdInput.focus();
        }

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
            symbol,
            {
                chainId: chainIdValue,
                contractAddress: contractAddressValue
            }
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
   RISK SEVERITY
   ============================================================ */

function normalizeSeverity(value) {
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
        normalized ===
        "critical"
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
    if (!element) return;

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
    if (!bar) return;

    const numericScore =
        clampScore(score);

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

function renderMarket(report) {
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

    const source =
        normalizeSource(
            firstDefined(
                market.source,
                market.provider,
                market.data_source
            )
        );

    const timestamp =
        firstDefined(
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
   MAIN RISK PROFILE
   ============================================================ */

function renderRiskProfile(
    report
) {
    const risk =
        getRiskProfile(report);

    const compositeScore =
        firstDefined(
            risk.composite_score,
            risk.score,
            report.risk_score
        );

    const rawLabel =
        firstDefined(
            risk.label,
            risk.severity,
            report.risk_label,
            report.risk_severity
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

    // FIX (B1): the HTML template already renders a static "/ 100"
    // label next to #report-risk-score, so appending "/100" here
    // produced "39/100 /100". Set ONLY the number and let the static
    // label render once.
    setText(
        "#report-risk-score",
        compositeScore !== null
            ? formatScore(
                compositeScore
            )
            : "—"
    );

    setText(
        "#report-risk-label",
        label
    );

    setText(
        "#report-outlook",
        firstDefined(
            report.outlook,
            report.trend,
            report.risk_label,
            risk.label
        )
    );

    setText(
        "#report-risk-confidence",
        formatConfidence(
            confidence
        )
    );

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
        firstDefined(
            report.outlook,
            rawLabel
        )
    );

    /*
     * Always render all pillars.
     *
     * Missing pillars are explicitly
     * cleared instead of leaving old
     * values on screen.
     */
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

    const marketSensitivity =
        firstDefined(
            getPillars(report)
                .market_sensitivity,
            getPillars(report)
                .marketSensitivity,
            getPillars(report)
                ["market-sensitivity"]
        );

    renderPillar(
        "market-sensitivity",
        marketSensitivity || {}
    );

    /*
     * FIX (B3): the "Contract" card the user actually sees uses the
     * #pillar-contract-value / #pillar-contract-bar /
     * #pillar-contract-detail DOM elements, while the backend
     * returns the security/structural pillar under the key
     * "structural" in risk_profile.pillars. Previously the data was
     * written to #pillar-structural-* elements (which don't exist in
     * the served template), so the visible Contract card never
     * updated and always showed its placeholder. The structural
     * pillar is now rendered directly into the contract elements,
     * and the dead "contract"-key lookup block was removed.
     *
     * Native assets (BTC/ETH/…) return a not-applicable security
     * object, which buildPillarDetail() renders as
     * "Not applicable — native assets have no smart contract to
     * analyze" instead of a bare "—".
     */
    renderPillar(
        "contract",
        firstDefined(
            getPillar(
                report,
                "structural"
            ),
            getPillar(
                report,
                "contract"
            )
        )
    );

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
    const safePillar =
        isPlainObject(pillar)
            ? pillar
            : {};

    const score =
        firstDefined(
            safePillar.score,
            safePillar.risk_score,
            safePillar.value
        );

    const label =
        firstDefined(
            safePillar.label,
            safePillar.severity
        );

    const valueElement =
        $(`#pillar-${name}-value`);

    const barElement =
        $(`#pillar-${name}-bar`);

    const detailElement =
        $(`#pillar-${name}-detail`);

    /*
     * CRITICAL FIX:
     * Clear every pillar first.
     *
     * Without this, if report #1 has
     * liquidity and report #2 doesn't,
     * report #1's liquidity score remains
     * visible.
     */
    if (
        score === null ||
        score === undefined ||
        score === ""
    ) {
        if (valueElement) {
            valueElement.textContent =
                "N/A";

            applyRiskClass(
                valueElement,
                null
            );
        }

        if (barElement) {
            updateScoreBar(
                barElement,
                null
            );

            applyRiskClass(
                barElement,
                null
            );
        }

        if (detailElement) {
            detailElement.textContent =
                buildPillarDetail(
                    name,
                    safePillar
                );
        }

        return;
    }

    if (valueElement) {
        valueElement.textContent =
            `${formatScore(
                score
            )}/100`;

        applyRiskClass(
            valueElement,
            label
        );
    }

    if (barElement) {
        updateScoreBar(
            barElement,
            score
        );

        applyRiskClass(
            barElement,
            label
        );
    }

    if (detailElement) {
        detailElement.textContent =
            buildPillarDetail(
                name,
                safePillar
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
    if (
        !isPlainObject(pillar)
    ) {
        return (
            generatePillarFallbackDetail(
                name,
                null
            ) ||
            "Signal unavailable."
        );
    }

    const detail =
        firstDefined(
            pillar.detail,
            pillar.description,
            pillar.reason,
            pillar.interpretation
        );

    /*
     * FIX (B3): native assets (BTC/ETH/…) have no smart contract, so
     * the security/structural pillar is "not applicable". That must
     * never render as a bare "—" (which reads as "broken/unknown").
     * A not-applicable signal is shown as an explanation instead.
     */
    if (pillar.not_applicable === true) {
        return (
            "Not applicable — native assets (e.g. BTC/ETH) have " +
            "no smart contract to analyze."
        );
    }

    if (
        detail !== null &&
        /not[\s-]?applicable/i.test(
            String(detail)
        )
    ) {
        return (
            `${String(detail)
                .replace(/\.$/, "")
                .trim()} — native assets (e.g. BTC/ETH) have no ` +
            "smart contract to analyze."
        );
    }

    if (detail !== null) {
        return String(detail);
    }

    const score =
        firstDefined(
            pillar.score,
            pillar.risk_score,
            pillar.value
        );

    if (
        score === null ||
        score === undefined
    ) {
        return firstDefined(
            pillar.label,
            pillar.severity,
            generatePillarFallbackDetail(
                name,
                null
            ),
            "Signal unavailable."
        );
    }

    return generatePillarFallbackDetail(
        name,
        score
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
            "Contract/security risk contribution.",

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
            "Structural/contract security signal unavailable — no contract security data.",

        contract:
            "Contract/security signal unavailable — no contract security data."
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

    if (!container) return;

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
            const safeDriver =
                isPlainObject(
                    driver
                )
                    ? driver
                    : {};

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

            heading.textContent =
                firstDefined(
                    safeDriver.title,
                    safeDriver.name,
                    `Risk driver ${
                        index + 1
                    }`
                );

            badge.textContent =
                normalizeSeverity(
                    firstDefined(
                        safeDriver.severity,
                        safeDriver.label
                    )
                );

            badge.className =
                "risk-badge";

            applyRiskClass(
                badge,
                firstDefined(
                    safeDriver.severity,
                    safeDriver.label
                )
            );

            body.textContent =
                firstDefined(
                    safeDriver.detail,
                    safeDriver.description,
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
        isPlainObject(stress)
            ? stress
            : {};

    const expected =
        firstDefined(
            stressObj.expected_drawdown_pct,
            stressObj.drawdown_pct,
            stressObj.max_drawdown_pct,
            stressObj.expected_downside_pct
        );

    if (
        expected !== null
    ) {
        return expected;
    }

    const base =
        stressObj.base_scenario;

    if (
        isPlainObject(base)
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
        isPlainObject(stress)
            ? stress
            : {};

    const label =
        firstDefined(
            stressObj.resilience_label,
            stressObj.resilience,
            stressObj.resilience_status
        );

    if (label !== null) {
        return label;
    }

    const base =
        stressObj.base_scenario;

    const rawScore =
        firstDefined(
            isPlainObject(base)
                ? base.resilience_score
                : null,

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
        isPlainObject(stress)
            ? stress
            : {};

    const reportObj =
        isPlainObject(report)
            ? report
            : {};

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

    const beta =
        firstDefined(
            stress.beta,
            stress.beta_to_btc,
            report?.quantitative?.beta?.beta,
            report?.quantitative?.beta
        );

    setText(
        "#stress-beta",
        formatNumber(
            beta,
            3
        )
    );

    setText(
        "#stress-drawdown",
        formatPercent(
            getExpectedDrawdown(
                stress
            )
        )
    );

    const resilience =
        getResilienceLabel(
            stress
        );

    setText(
        "#stress-resilience",
        resilience
    );

    setText(
        "#stress-confidence",
        formatConfidence(
            getStressConfidence(
                report,
                stress
            )
        )
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

    applyRiskClass(
        $("#stress-resilience"),
        firstDefined(
            stress.resilience_label,
            resilience
        )
    );

    setText(
        "#ai-stress-interpretation",
        getAI(report)
            .stress_interpretation
    );
}


/* ============================================================
   AI REPORT
   ============================================================ */

function renderAI(report) {
    const ai =
        getAI(report);

    const security =
        getSecurity(report);

    const quality =
        getDataQuality(report);

    setText(
        "#executive-summary",
        firstDefined(
            ai.executive_summary,
            ai.summary,
            "No executive summary was returned."
        )
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

    setText(
        "#ai-liquidity",
        firstDefined(
            ai.watch_next,
            "No monitoring guidance returned."
        )
    );

    const securityFlags =
        Array.isArray(
            security.red_flags
        )
            ? security.red_flags
            : [];

    let securityText =
        firstDefined(
            security.status,
            security.label,
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
                .join(" • ");
    }

    setText(
        "#ai-contract-risk",
        securityText
    );

    applyRiskClass(
        $("#ai-contract-risk"),
        security.status
    );

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

    if (!hasExecutiveSummary) {
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

function renderDataQuality(
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

    const source =
        normalizeSource(
            firstDefined(
                reportMarket.source,
                reportMarket.provider,
                quality.source
            )
        );

    setText(
        "#market-source",
        source
    );

    /*
     * Support all common timestamp names.
     */
    const timestamp =
        firstDefined(
            reportMarket.timestamp,
            reportMarket.updated_at,
            reportMarket.fetched_at,
            reportMarket.last_updated,

            quality.timestamp,
            quality.updated_at,
            quality.fetched_at,

            reportObj.generated_at,
            reportObj.created_at,
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

function renderMissingSignals(
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
                        .trim() !== ""
            );
    } else if (
        typeof missing ===
        "string"
    ) {
        if (
            missing.trim()
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


/* ============================================================
   COMPLETE REPORT RENDERER
   ============================================================ */

function renderReport(
    report
) {
    if (
        !isRiskReport(report)
    ) {
        clearReportView();
        return;
    }

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
   DELETE BUTTON STATE
   ============================================================ */

function updateCurrentReportDeleteButton() {
    const button =
        $("#delete-current-report");

    if (!button) return;

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

    if (!tbody) return;

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
            const safeRecord =
                isPlainObject(record)
                    ? record
                    : {};

            const id =
                firstDefined(
                    safeRecord.id,
                    safeRecord.analysis_id
                );

            const row =
                document.createElement(
                    "tr"
                );

            row.dataset.reportId =
                String(
                    id ?? ""
                );

            const assetCell =
                createHistoryCell(
                    firstDefined(
                        safeRecord.token_symbol,
                        safeRecord.asset?.symbol,
                        safeRecord.symbol,
                        "—"
                    )
                );

            const riskCell =
                document.createElement(
                    "td"
                );

            const riskValue =
                firstDefined(
                    safeRecord.risk_label,
                    safeRecord.risk_severity,
                    safeRecord.label,
                    safeRecord.severity
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

            const outlookCell =
                createHistoryCell(
                    firstDefined(
                        safeRecord.outlook,
                        safeRecord.trend,
                        "—"
                    )
                );

            const score =
                firstDefined(
                    safeRecord.risk_score,
                    safeRecord.composite_score,
                    safeRecord.risk_profile
                        ?.composite_score
                );

            const scoreCell =
                createHistoryCell(
                    score !== null
                        ? `${formatScore(
                            score
                        )}/100`
                        : "—"
                );

            const dateValue =
                firstDefined(
                    safeRecord.created_at,
                    safeRecord.timestamp,
                    safeRecord.generated_at,
                    safeRecord.updated_at
                );

            const dateCell =
                createHistoryCell(
                    dateValue
                        ? formatDate(
                            dateValue
                        )
                        : "—"
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
                String(id ?? "");

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
                String(id ?? "");

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

    if (!target) return;

    const action =
        target.dataset.action;

    const id =
        target.dataset.id;

    if (!id) return;

    event.preventDefault();
    event.stopPropagation();

    if (
        action ===
        "view-history"
    ) {
        loadHistoryReport(id);
        return;
    }

    if (
        action ===
        "delete-history"
    ) {
        deleteReport(id);
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
        )?.value?.trim();

    const password =
        form.querySelector(
            "[name='password']"
        )?.value;

    const username =
        form.querySelector(
            "[name='username']"
        )?.value?.trim();

    if (!email || !password) {
        showAnalysisError(
            "Email and password are required."
        );

        return;
    }

    if (
        action === "signup" &&
        !username
    ) {
        showAnalysisError(
            "Username is required."
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
                payload.access_token,
                payload.data?.token,
                payload.data?.access_token
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
        // FIX (Bug 6): friendly message instead of raw error string.
        showAnalysisError(
            friendlyErrorMessage(error) ||
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
        stopJobPolling();

        if (
            typeof CursorPhysics !==
            "undefined"
        ) {
            CursorPhysics.destroy();
        }

        if (
            typeof MoneyMeteor !==
            "undefined"
        ) {
            MoneyMeteor.destroy();
        }
    }
);


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

    particleAnimationId: null,
    removeTimer: null,

    create() {
        /*
         * Cancel any previous removal timer.
         */
        if (this.removeTimer) {
            clearTimeout(
                this.removeTimer
            );

            this.removeTimer = null;
        }

        /*
         * Remove existing beam synchronously.
         * This prevents an old setTimeout from
         * deleting a newly-created beam.
         */
        this.remove(true);

        this.progress = 0;
        this.targetProgress = 0;
        this.isAnimating = false;

        this.container =
            document.createElement(
                "div"
            );

        this.container.className =
            "analysis-beam-container";

        this.container.innerHTML = `
            <div class="analysis-beam-overlay"></div>

            <div class="analysis-beam-content">
                <div class="beam-percentage-display">0%</div>

                <div class="beam-progress-track">
                    <div class="beam-progress-fill"></div>
                    <div class="beam-currency-stream"></div>
                </div>

                <div class="beam-status-text">
                    Initializing Analysis...
                </div>

                <div class="beam-particles-canvas"></div>
            </div>
        `;

        document.body.appendChild(
            this.container
        );

        this.canvas =
            document.createElement(
                "canvas"
            );

        this.canvas.className =
            "beam-particle-canvas";

        const particleContainer =
            this.container.querySelector(
                ".beam-particles-canvas"
            );

        if (particleContainer) {
            particleContainer.appendChild(
                this.canvas
            );
        }

        this.ctx =
            this.canvas.getContext(
                "2d"
            );

        this.resizeCanvas();

        this.initParticles();

        this.initCurrencySymbols();

        requestAnimationFrame(
            () => {
                if (
                    this.container
                ) {
                    this.container.classList.add(
                        "active"
                    );
                }
            }
        );

        this.startParticleLoop();
    },

    startParticleLoop() {
        if (
            this.particleAnimationId
        ) {
            cancelAnimationFrame(
                this.particleAnimationId
            );
        }

        const loop = () => {
            if (
                !this.container
            ) {
                this.particleAnimationId =
                    null;

                return;
            }

            this.renderParticles();

            this.particleAnimationId =
                requestAnimationFrame(
                    loop
                );
        };

        loop();
    },

    renderParticles() {
        if (
            !this.ctx ||
            !this.canvas
        ) {
            return;
        }

        this.ctx.clearRect(
            0,
            0,
            this.canvas.width,
            this.canvas.height
        );

        this.particles.forEach(
            (particle) => {
                particle.x +=
                    particle.vx;

                particle.y +=
                    particle.vy;

                particle.life -=
                    0.006;

                if (
                    particle.life <=
                        0 ||
                    particle.y <
                        -10 ||
                    particle.y >
                        this.canvas.height +
                            10
                ) {
                    particle.x =
                        Math.random() *
                        this.canvas.width;

                    particle.y =
                        this.canvas.height +
                        10;

                    particle.vx =
                        (
                            Math.random() -
                            0.5
                        ) * 2;

                    particle.vy =
                        (
                            Math.random() -
                            0.5
                        ) * 2 -
                        1;

                    particle.life =
                        Math.random() *
                            0.5 +
                        0.5;
                }

                this.ctx.beginPath();

                this.ctx.arc(
                    particle.x,
                    particle.y,
                    particle.size,
                    0,
                    Math.PI * 2
                );

                this.ctx.fillStyle =
                    particle.color;

                this.ctx.globalAlpha =
                    Math.max(
                        0,
                        particle.alpha *
                            particle.life
                    );

                this.ctx.fill();

                this.ctx.globalAlpha =
                    1;
            }
        );
    },

    resizeCanvas() {
        if (
            !this.canvas ||
            !this.container
        ) {
            return;
        }

        const rect =
            this.container.getBoundingClientRect();

        this.canvas.width =
            Math.max(
                1,
                Math.floor(
                    rect.width
                )
            );

        this.canvas.height =
            Math.max(
                1,
                Math.floor(
                    rect.height
                )
            );
    },

    initParticles() {
        this.particles = [];

        for (
            let i = 0;
            i < 50;
            i++
        ) {
            this.particles.push({
                x:
                    Math.random() *
                    (this.canvas?.width ||
                        800),

                y:
                    Math.random() *
                    (this.canvas?.height ||
                        200),

                vx:
                    (
                        Math.random() -
                        0.5
                    ) * 2,

                vy:
                    (
                        Math.random() -
                        0.5
                    ) * 2 -
                    1,

                size:
                    Math.random() *
                        3 +
                    1,

                alpha:
                    Math.random() *
                        0.5 +
                    0.2,

                color:
                    [
                        "#ffd700",
                        "#ff6b2b",
                        "#39ff14",
                        "#7c3aed"
                    ][
                        Math.floor(
                            Math.random() *
                                4
                        )
                    ],

                life:
                    Math.random()
            });
        }
    },

    initCurrencySymbols() {
        const stream =
            this.container?.querySelector(
                ".beam-currency-stream"
            );

        if (!stream) {
            return;
        }

        const symbols = [
            "$",
            "💰",
            "$",
            "₿",
            "$",
            "💰",
            "$",
            "₿",
            "$",
            "💰",
            "$",
            "₿",
            "$",
            "💰"
        ];

        symbols.forEach(
            (symbol, index) => {
                const element =
                    document.createElement(
                        "span"
                    );

                element.className =
                    "beam-currency-symbol";

                element.textContent =
                    symbol;

                element.style.animationDelay =
                    `${index * 0.12}s`;

                stream.appendChild(
                    element
                );
            }
        );
    },

    setProgress(percent) {
        this.targetProgress =
            Math.min(
                100,
                Math.max(
                    0,
                    Number(percent) ||
                        0
                )
            );

        if (
            !this.isAnimating
        ) {
            this.animateProgress();
        }
    },

    animateProgress() {
        this.isAnimating =
            true;

        const update = () => {
            const diff =
                this.targetProgress -
                this.progress;

            if (
                Math.abs(diff) <
                0.5
            ) {
                this.progress =
                    this.targetProgress;
            } else {
                this.progress +=
                    diff * 0.1;
            }

            const fill =
                this.container?.querySelector(
                    ".beam-progress-fill"
                );

            if (fill) {
                fill.style.width =
                    `${this.progress}%`;
            }

            const percentEl =
                this.container?.querySelector(
                    ".beam-percentage-display"
                );

            if (percentEl) {
                percentEl.textContent =
                    `${Math.round(
                        this.progress
                    )}%`;
            }

            const statusEl =
                this.container?.querySelector(
                    ".beam-status-text"
                );

            if (statusEl) {
                if (
                    this.progress <
                    15
                ) {
                    statusEl.textContent =
                        "Connecting to Market Data...";
                } else if (
                    this.progress <
                    30
                ) {
                    statusEl.textContent =
                        "Fetching Price History...";
                } else if (
                    this.progress <
                    50
                ) {
                    statusEl.textContent =
                        "Running Quantitative Engine...";
                } else if (
                    this.progress <
                    70
                ) {
                    statusEl.textContent =
                        "Building Risk Profile...";
                } else if (
                    this.progress <
                    85
                ) {
                    statusEl.textContent =
                        "Running Stress Tests...";
                } else if (
                    this.progress <
                    95
                ) {
                    statusEl.textContent =
                        "Generating AI Insights...";
                } else {
                    statusEl.textContent =
                        "Finalizing Report...";
                }
            }

            if (
                this.progress <
                    this.targetProgress ||
                Math.abs(diff) >
                    0.5
            ) {
                requestAnimationFrame(
                    update
                );
            } else {
                this.isAnimating =
                    false;

                this.triggerWealthBurst();
            }
        };

        update();
    },

    triggerWealthBurst() {
        if (
            !this.particles?.length
        ) {
            return;
        }

        this.particles.forEach(
            (particle) => {
                particle.vx =
                    (
                        Math.random() -
                        0.5
                    ) * 6;

                particle.vy =
                    -(
                        Math.random() *
                            6 +
                        2
                    );

                particle.life = 1;

                particle.alpha =
                    Math.random() *
                        0.5 +
                    0.5;
            }
        );
    },

    remove(immediate = false) {
        if (
            this.removeTimer
        ) {
            clearTimeout(
                this.removeTimer
            );

            this.removeTimer = null;
        }

        if (
            this.particleAnimationId
        ) {
            cancelAnimationFrame(
                this.particleAnimationId
            );

            this.particleAnimationId =
                null;
        }

        const oldContainer =
            this.container;

        if (!oldContainer) {
            return;
        }

        if (immediate) {
            if (
                oldContainer.parentNode
            ) {
                oldContainer.parentNode.removeChild(
                    oldContainer
                );
            }

            if (
                this.container ===
                oldContainer
            ) {
                this.container =
                    null;

                this.canvas =
                    null;

                this.ctx =
                    null;
            }

            return;
        }

        oldContainer.classList.remove(
            "active"
        );

        this.removeTimer =
            setTimeout(() => {
                if (
                    oldContainer.parentNode
                ) {
                    oldContainer.parentNode.removeChild(
                        oldContainer
                    );
                }

                if (
                    this.container ===
                    oldContainer
                ) {
                    this.container =
                        null;

                    this.canvas =
                        null;

                    this.ctx =
                        null;
                }

                this.removeTimer =
                    null;
            }, 500);
    }
};


/* ============================================================
   MONEY METEOR
   ============================================================ */

const MoneyMeteor = {
    canvas: null,
    ctx: null,

    meteors: [],
    particles: [],
    bitcoinSymbols: [],
    dollarBillSymbols: [],

    animationId: null,
    isRunning: false,

    lastSpawn: 0,
    spawnInterval: 800,

    W: 0,
    H: 0,

    resizeHandler: null,

    init() {
        this.canvas =
            document.getElementById(
                "meteor-canvas"
            );

        if (!this.canvas) {
            return;
        }

        this.ctx =
            this.canvas.getContext(
                "2d"
            );

        this.resize();

        this.resizeHandler =
            () => this.resize();

        window.addEventListener(
            "resize",
            this.resizeHandler
        );

        this.isRunning = true;

        this.animate();
    },

    resize() {
        if (!this.canvas) {
            return;
        }

        this.W =
            window.innerWidth;

        this.H =
            window.innerHeight;

        this.canvas.width =
            this.W;

        this.canvas.height =
            this.H;
    },

    spawnMeteor() {
        const angle =
            -Math.PI / 2 +
            (
                Math.random() -
                0.5
            ) * 0.6;

        const speed =
            6 +
            Math.random() * 10;

        const startX =
            Math.random() *
            this.W;

        const startY =
            -40 -
            Math.random() *
                100;

        const isBitcoin =
            Math.random() < 0.5;

        const symbol =
            isBitcoin
                ? "₿"
                : "$";

        const symbolSize =
            isBitcoin
                ? 28 +
                  Math.random() *
                      12
                : 22 +
                  Math.random() *
                      8;

        const coreColor =
            isBitcoin
                ? "#fffbe6"
                : "#ff4500";

        this.meteors.push({
            x: startX,
            y: startY,

            vx:
                Math.cos(angle) *
                speed,

            vy:
                Math.sin(angle) *
                speed,

            life: 1,

            decay:
                0.005 +
                Math.random() *
                    0.008,

            len:
                120 +
                Math.random() *
                    200,

            isB: isBitcoin,
            sym: symbol,
            sSize: symbolSize,

            colorMain:
                isBitcoin
                    ? "#ffd700"
                    : "#ff6b2b",

            cCore: coreColor,

            tail: [],

            rot:
                Math.random() *
                Math.PI *
                2,

            rotSpd:
                (
                    Math.random() -
                    0.5
                ) * 0.1
        });
    },

    updM(meteor) {
        meteor.x += meteor.vx;
        meteor.y += meteor.vy;

        meteor.rot +=
            meteor.rotSpd;

        meteor.life -=
            meteor.decay;

        const tailLength =
            Math.floor(
                meteor.len *
                (
                    0.3 +
                    Math.random() *
                        0.4
                )
            );

        meteor.tail.unshift({
            x: meteor.x,
            y: meteor.y,
            life: 1
        });

        if (
            meteor.tail.length >
            tailLength
        ) {
            meteor.tail.pop();
        }

        meteor.tail.forEach(
            (point) => {
                point.life -=
                    0.025 +
                    Math.random() *
                        0.02;
            }
        );

        if (
            meteor.life <= 0
        ) {
            return;
        }

        if (
            Math.random() <
            0.35
        ) {
            this.particles.push({
                x:
                    meteor.x +
                    (
                        Math.random() -
                        0.5
                    ) * 10,

                y:
                    meteor.y +
                    (
                        Math.random() -
                        0.5
                    ) * 10,

                vx:
                    (
                        Math.random() -
                        0.5
                    ) * 2,

                vy:
                    (
                        Math.random() -
                        0.5
                    ) * 2 -
                    0.5,

                life: 1,

                decay:
                    0.02 +
                    Math.random() *
                        0.03,

                size:
                    1.5 +
                    Math.random() *
                        2.5,

                isB:
                    meteor.isB
            });
        }

        if (
            Math.random() <
            0.15
        ) {
            this.bitcoinSymbols.push({
                x:
                    meteor.x +
                    (
                        Math.random() -
                        0.5
                    ) *
                        meteor.len *
                        0.5,

                y:
                    meteor.y +
                    (
                        Math.random() -
                        0.5
                    ) *
                        meteor.len *
                        0.5,

                vx:
                    (
                        Math.random() -
                        0.5
                    ) * 0.3,

                vy:
                    -0.3 -
                    Math.random() *
                        0.6,

                life: 1,

                decay:
                    0.015 +
                    Math.random() *
                        0.015,

                size:
                    8 +
                    Math.random() *
                        6,

                rot:
                    Math.random() *
                    Math.PI *
                    2,

                rotSpd:
                    (
                        Math.random() -
                        0.5
                    ) * 0.1
            });
        }

        if (
            Math.random() <
            0.12
        ) {
            this.dollarBillSymbols.push({
                x:
                    meteor.x +
                    (
                        Math.random() -
                        0.5
                    ) *
                        meteor.len *
                        0.3,

                y:
                    meteor.y +
                    (
                        Math.random() -
                        0.5
                    ) *
                        meteor.len *
                        0.3,

                vx:
                    (
                        Math.random() -
                        0.5
                    ) * 0.4,

                vy:
                    -0.4 -
                    Math.random() *
                        0.8,

                life: 1,

                decay:
                    0.012 +
                    Math.random() *
                        0.012,

                size:
                    7 +
                    Math.random() *
                        5,

                rot:
                    Math.random() *
                    Math.PI *
                    2,

                rotSpd:
                    (
                        Math.random() -
                        0.5
                    ) * 0.12
            });
        }
    },

    drawTrail(meteor) {
        const ctx =
            this.ctx;

        const tail =
            meteor.tail;

        if (!ctx || !tail) {
            return;
        }

        for (
            let i = 1;
            i < tail.length;
            i++
        ) {
            const point =
                tail[i];

            const alpha =
                point.life *
                meteor.life *
                0.8;

            if (
                alpha <= 0
            ) {
                continue;
            }

            const width =
                (
                    i /
                    tail.length
                ) *
                (
                    meteor.isB
                        ? 6
                        : 4
                ) *
                meteor.life;

            const gradient =
                ctx.createLinearGradient(
                    tail[i - 1].x,
                    tail[i - 1].y,
                    point.x,
                    point.y
                );

            if (
                meteor.isB
            ) {
                gradient.addColorStop(
                    0,
                    `rgba(255,255,200,${alpha})`
                );

                gradient.addColorStop(
                    0.4,
                    `rgba(255,180,50,${alpha * 0.9})`
                );

                gradient.addColorStop(
                    0.7,
                    `rgba(255,100,20,${alpha * 0.6})`
                );

                gradient.addColorStop(
                    1,
                    `rgba(255,50,0,${alpha * 0.1})`
                );
            } else {
                gradient.addColorStop(
                    0,
                    `rgba(255,220,100,${alpha})`
                );

                gradient.addColorStop(
                    0.4,
                    `rgba(255,120,20,${alpha * 0.9})`
                );

                gradient.addColorStop(
                    0.7,
                    `rgba(200,30,0,${alpha * 0.6})`
                );

                gradient.addColorStop(
                    1,
                    `rgba(100,0,0,${alpha * 0.05})`
                );
            }

            ctx.beginPath();

            ctx.arc(
                point.x,
                point.y,
                width,
                0,
                Math.PI * 2
            );

            ctx.fillStyle =
                gradient;

            ctx.fill();
        }
    },

    drawCore(meteor) {
        const ctx =
            this.ctx;

        if (!ctx) {
            return;
        }

        const size =
            meteor.sSize;

        ctx.save();

        ctx.translate(
            meteor.x,
            meteor.y
        );

        ctx.rotate(
            meteor.rot
        );

        const glowRadius =
            size * 1.8;

        const glow =
            ctx.createRadialGradient(
                0,
                0,
                size * 0.2,
                0,
                0,
                glowRadius
            );

        if (
            meteor.isB
        ) {
            glow.addColorStop(
                0,
                "rgba(255,255,220,0.9)"
            );

            glow.addColorStop(
                0.3,
                "rgba(255,200,80,0.6)"
            );

            glow.addColorStop(
                0.7,
                "rgba(255,120,20,0.2)"
            );

            glow.addColorStop(
                1,
                "rgba(255,60,0,0)"
            );
        } else {
            glow.addColorStop(
                0,
                "rgba(255,200,100,0.9)"
            );

            glow.addColorStop(
                0.3,
                "rgba(255,100,20,0.6)"
            );

            glow.addColorStop(
                0.7,
                "rgba(200,30,0,0.25)"
            );

            glow.addColorStop(
                1,
                "rgba(80,0,0,0)"
            );
        }

        ctx.beginPath();

        ctx.arc(
            0,
            0,
            glowRadius,
            0,
            Math.PI * 2
        );

        ctx.fillStyle =
            glow;

        ctx.fill();

        ctx.font =
            `${size}px JetBrains Mono, Fira Code, monospace`;

        ctx.textAlign =
            "center";

        ctx.textBaseline =
            "middle";

        ctx.shadowColor =
            meteor.isB
                ? "#ffd700"
                : "#ff4500";

        ctx.shadowBlur =
            25;

        ctx.fillStyle =
            meteor.cCore;

        ctx.fillText(
            meteor.sym,
            0,
            0
        );

        ctx.shadowBlur = 0;

        ctx.font =
            `${size * 0.85}px JetBrains Mono, Fira Code, monospace`;

        ctx.fillStyle =
            "#fff";

        ctx.fillText(
            meteor.sym,
            0,
            0
        );

        ctx.restore();
    },

    updParticles() {
        const ctx =
            this.ctx;

        if (!ctx) return;

        for (
            let i =
                this.particles.length -
                1;
            i >= 0;
            i--
        ) {
            const particle =
                this.particles[i];

            particle.x +=
                particle.vx;

            particle.y +=
                particle.vy;

            particle.vy -=
                0.02;

            particle.life -=
                particle.decay;

            if (
                particle.life <=
                0
            ) {
                this.particles.splice(
                    i,
                    1
                );

                continue;
            }

            const hue =
                particle.isB
                    ? 45 +
                      Math.random() *
                          20
                    : 20 +
                      Math.random() *
                          20;

            const lightness =
                particle.isB
                    ? 50 +
                      Math.random() *
                          30
                    : 40 +
                      Math.random() *
                          30;

            ctx.beginPath();

            ctx.arc(
                particle.x,
                particle.y,
                particle.size *
                    particle.life,
                0,
                Math.PI * 2
            );

            ctx.fillStyle =
                `hsla(${hue},100%,${lightness}%,${particle.life * 0.8})`;

            ctx.fill();
        }
    },

    updBtcSym() {
        const ctx =
            this.ctx;

        if (!ctx) return;

        for (
            let i =
                this.bitcoinSymbols.length -
                1;
            i >= 0;
            i--
        ) {
            const bitcoin =
                this.bitcoinSymbols[i];

            bitcoin.x +=
                bitcoin.vx;

            bitcoin.y +=
                bitcoin.vy;

            bitcoin.vy -=
                0.01;

            bitcoin.rot +=
                bitcoin.rotSpd;

            bitcoin.life -=
                bitcoin.decay;

            if (
                bitcoin.life <=
                0
            ) {
                this.bitcoinSymbols.splice(
                    i,
                    1
                );

                continue;
            }

            ctx.save();

            ctx.translate(
                bitcoin.x,
                bitcoin.y
            );

            ctx.rotate(
                bitcoin.rot
            );

            ctx.globalAlpha =
                bitcoin.life;

            ctx.font =
                `${bitcoin.size}px JetBrains Mono, Fira Code, monospace`;

            ctx.textAlign =
                "center";

            ctx.textBaseline =
                "middle";

            ctx.shadowColor =
                "#ffd700";

            ctx.shadowBlur =
                12;

            ctx.fillStyle =
                "#ffd700";

            ctx.fillText(
                "₿",
                0,
                0
            );

            ctx.shadowBlur = 0;
            ctx.globalAlpha = 1;

            ctx.restore();
        }
    },

    updDollarSym() {
        const ctx =
            this.ctx;

        if (!ctx) return;

        for (
            let i =
                this.dollarBillSymbols.length -
                1;
            i >= 0;
            i--
        ) {
            const dollar =
                this.dollarBillSymbols[i];

            dollar.x +=
                dollar.vx;

            dollar.y +=
                dollar.vy;

            dollar.vy -=
                0.015;

            dollar.rot +=
                dollar.rotSpd;

            dollar.life -=
                dollar.decay;

            if (
                dollar.life <=
                0
            ) {
                this.dollarBillSymbols.splice(
                    i,
                    1
                );

                continue;
            }

            ctx.save();

            ctx.translate(
                dollar.x,
                dollar.y
            );

            ctx.rotate(
                dollar.rot
            );

            ctx.globalAlpha =
                dollar.life * 0.9;

            ctx.font =
                `${dollar.size}px JetBrains Mono, Fira Code, monospace`;

            ctx.textAlign =
                "center";

            ctx.textBaseline =
                "middle";

            ctx.shadowColor =
                "#ff4500";

            ctx.shadowBlur =
                10;

            ctx.fillStyle =
                dollar.life > 0.5
                    ? "#ff4500"
                    : "#ffd700";

            ctx.fillText(
                "$",
                0,
                0
            );

            ctx.shadowBlur = 0;
            ctx.globalAlpha = 1;

            ctx.restore();
        }
    },

    drawBgGlow() {
        const ctx =
            this.ctx;

        if (!ctx) return;

        const gradientOne =
            ctx.createRadialGradient(
                this.W / 2,
                this.H * 0.7,
                0,
                this.W / 2,
                this.H * 0.7,
                this.W * 0.7
            );

        gradientOne.addColorStop(
            0,
            "rgba(255,100,20,0.04)"
        );

        gradientOne.addColorStop(
            0.5,
            "rgba(255,60,0,0.02)"
        );

        gradientOne.addColorStop(
            1,
            "rgba(0,0,0,0)"
        );

        ctx.fillStyle =
            gradientOne;

        ctx.fillRect(
            0,
            0,
            this.W,
            this.H
        );

        const gradientTwo =
            ctx.createRadialGradient(
                this.W * 0.2,
                this.H * 0.3,
                0,
                this.W * 0.2,
                this.H * 0.3,
                this.W * 0.4
            );

        gradientTwo.addColorStop(
            0,
            "rgba(255,215,0,0.03)"
        );

        gradientTwo.addColorStop(
            1,
            "rgba(0,0,0,0)"
        );

        ctx.fillStyle =
            gradientTwo;

        ctx.fillRect(
            0,
            0,
            this.W,
            this.H
        );
    },

    animate() {
        if (
            !this.isRunning
        ) {
            return;
        }

        const ctx =
            this.ctx;

        if (!ctx) {
            return;
        }

        ctx.clearRect(
            0,
            0,
            this.W,
            this.H
        );

        this.drawBgGlow();

        const now =
            performance.now();

        if (
            now -
                this.lastSpawn >
            this.spawnInterval
        ) {
            this.spawnMeteor();

            this.lastSpawn =
                now;

            this.spawnInterval =
                600 +
                Math.random() *
                    600;
        }

        for (
            let i =
                this.meteors.length -
                1;
            i >= 0;
            i--
        ) {
            const meteor =
                this.meteors[i];

            this.updM(
                meteor
            );

            if (
                meteor.life <=
                    0 ||
                meteor.y >
                    this.H + 50 ||
                meteor.x <
                    -100 ||
                meteor.x >
                    this.W + 100
            ) {
                this.meteors.splice(
                    i,
                    1
                );

                continue;
            }

            this.drawTrail(
                meteor
            );

            this.drawCore(
                meteor
            );
        }

        this.updBtcSym();
        this.updDollarSym();
        this.updParticles();

        this.animationId =
            requestAnimationFrame(
                () => this.animate()
            );
    },

    destroy() {
        this.isRunning = false;

        if (
            this.animationId
        ) {
            cancelAnimationFrame(
                this.animationId
            );

            this.animationId =
                null;
        }

        if (
            this.resizeHandler
        ) {
            window.removeEventListener(
                "resize",
                this.resizeHandler
            );

            this.resizeHandler =
                null;
        }

        this.meteors = [];
        this.particles = [];
        this.bitcoinSymbols = [];
        this.dollarBillSymbols = [];
    }
};


/* ============================================================
   FINAL DOM INITIALIZATION
   ============================================================ */

document.addEventListener(
    "DOMContentLoaded",
    () => {
        CursorPhysics.init();

        if (
            document.getElementById(
                "meteor-canvas"
            )
        ) {
            MoneyMeteor.init();
        }

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

        const historyBody =
            $("#history-tbody");

        if (historyBody) {
            historyBody.addEventListener(
                "click",
                handleHistoryClick
            );
        }

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

        // FIX (Bug 7): sync the job polling ceiling from the
        // backend's real ANALYSIS_JOB_TIMEOUT_SECONDS (via /health)
        // instead of hardcoding it. Fire-and-forget — the fallback
        // ceiling is already valid.
        syncJobPollCeiling();

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