import { state } from '../state/store.js';
import { show, hide, setText } from '../utils/dom.js';

/* ============================================================
   API URL RESOLUTION
   ============================================================ */

export function resolveApiUrl(url) {
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

export async function apiRequest(url, options = {}) {
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

export function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}




/* ============================================================
   ERROR UI
   ============================================================ */

export function showAnalysisError(message) {
    const element = $("#analysis-error");

    if (!element) {
        console.error(message);
        return;
    }

    element.textContent =
        message || "Something went wrong.";

    show(element);
}

export function clearAnalysisError() {
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

export function friendlyErrorMessage(error) {
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

export function renderUser(user) {
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

export const PROGRESS_STAGES = {
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

export const PROGRESS_ORDER = [
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

export let _progressAnim = null;
export let _progressCurrent = 0;

export function updateProgressDOM(
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
export function animateProgressTo(
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

export function startProgress() {
    _progressCurrent = 0;
    updateProgressDOM(1, "queued", "Starting analysis…");

    const wrapper = $("#energy-beam-wrapper");
    const beam = $(".energy-beam");
    const glow = $(".energy-beam-glow");

    if (wrapper) wrapper.classList.add("is-analyzing");
    if (beam) beam.style.width = "1%";
    if (glow) glow.style.width = "1%";
}

/**
 * Called on every successful job-status poll with the real
 * backend progress/stage/title/message.
 */
export function applyJobProgress(job) {
    if (!job) return;

    const percent = Number(job.progress);
    const stage = job.stage || "market";
    const title = job.stage_title || job.message || null;

    const safePercent = Number.isFinite(percent)
        ? percent
        : (PROGRESS_STAGES[stage]?.percent ?? _progressCurrent);

    animateProgressTo(safePercent, stage, title, 500);

    const beam = $(".energy-beam");
    const glow = $(".energy-beam-glow");
    if (beam) beam.style.width = `${safePercent}%`;
    if (glow) glow.style.width = `${safePercent}%`;
}

export function finishProgress() {
    animateProgressTo(100, "complete", "Analysis complete", 400);

    const beam = $(".energy-beam");
    const glow = $(".energy-beam-glow");
    if (beam) beam.style.width = "100%";
    if (glow) glow.style.width = "100%";

    setTimeout(() => {
        const wrapper = $("#energy-beam-wrapper");
        if (wrapper) wrapper.classList.remove("is-analyzing");
        if (beam) beam.style.width = "0%";
        if (glow) glow.style.width = "0%";
    }, 700);
}

export function abortProgress() {
    if (_progressAnim) {
        cancelAnimationFrame(_progressAnim);
        _progressAnim = null;
    }

    const wrapper = $("#energy-beam-wrapper");
    const beam = $(".energy-beam");
    const glow = $(".energy-beam-glow");

    if (wrapper) wrapper.classList.remove("is-analyzing");
    if (beam) beam.style.width = "0%";
    if (glow) glow.style.width = "0%";
}




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




