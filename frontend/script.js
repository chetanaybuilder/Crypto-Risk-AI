document.addEventListener("DOMContentLoaded", () => {
"use strict";

/*
==========================================================
CONFIGURATION
==========================================================
*/
const backendUrl = (
    window.CONFIG?.API_BASE_URL || ""
).replace(/\/$/, "");
const apiUrl = (path) => `${backendUrl}${path}`;
const getAuthToken = () =>
    localStorage.getItem("token") ||
    localStorage.getItem("auth_token");
const isDashboardPage =
    document.body.classList.contains("dashboard-page");
let hasSignedOut = false;
let currentReportId = null;
let dashboardInitialized = false;
let progressTimer = null;
/*
==========================================================
AUTHENTICATION
==========================================================
*/
function logoutAndStop() {
    if (hasSignedOut) return;
    hasSignedOut = true;
    localStorage.removeItem("token");
    localStorage.removeItem("auth_token");
    window.location.href = "index.html";
}
const queryToken =
    new URLSearchParams(window.location.search).get("token");
if (isDashboardPage && queryToken) {
    localStorage.setItem("token", queryToken);
    window.history.replaceState(
        {},
        document.title,
        window.location.pathname
    );
}
if (isDashboardPage && !getAuthToken()) {
    logoutAndStop();
    return;
}
function requestOptions(options = {}) {
    const token = getAuthToken();
    return {
        ...options,
        credentials: "include",
        headers: {
            ...(options.headers || {}),
            ...(token
                ? {
                    Authorization: `Bearer ${token}`,
                }
                : {}),
        },
    };
}
function setupAuthentication() {
    document
        .querySelectorAll("[data-google-login]")
        .forEach((link) => {
            link.href = apiUrl("/auth/google");
        });
}
setupAuthentication();
/*
==========================================================
ELEMENTS
==========================================================
*/
const input =
    document.querySelector(
        'input[name="token_symbol"]'
    );
const form =
    document.querySelector(
        ".search-card form"
    );
const reportPrice =
    document.getElementById(
        "report-price"
    );
const reportChange =
    document.getElementById(
        "report-change"
    );
const reportVolume =
    document.getElementById(
        "report-volume"
    );
const reportRiskScore =
    document.getElementById(
        "report-risk-score"
    );
/*
==========================================================
CREATE ANALYSIS PROGRESS UI
==========================================================
The dashboard HTML currently does not contain a progress
overlay, so create it dynamically.
==========================================================
*/
function createProgressOverlay() {
    if (
        document.getElementById(
            "analysis-progress"
        )
    ) {
        return;
    }
    const overlay =
        document.createElement("div");
    overlay.id =
        "analysis-progress";
    overlay.setAttribute(
        "aria-hidden",
        "true"
    );
    overlay.innerHTML = `
        <div class="analysis-progress-backdrop"></div>
        <div class="analysis-progress-card"
             role="status"
             aria-live="polite">
            <div class="analysis-progress-header">
                <span class="analysis-progress-kicker">
                    CRYPTORISK AI
                </span>
                <span
                    id="progress-percent"
                    class="analysis-progress-percent">
                    0%
                </span>
            </div>
            <div class="analysis-progress-title"
                 id="progress-stage">
                INITIALIZING
            </div>
            <p id="progress-message">
                Preparing cryptocurrency intelligence request...
            </p>
            <div class="analysis-progress-track">
                <div
                    id="progress-fill"
                    class="analysis-progress-fill">
                </div>
            </div>
            <div class="analysis-progress-statuses">
                <span class="progress-status active">
                    REQUEST
                </span>
                <span class="progress-status">
                    RESEARCH
                </span>
                <span class="progress-status">
                    AI ANALYSIS
                </span>
                <span class="progress-status">
                    REPORT
                </span>
            </div>
            <div class="analysis-progress-pulse">
                <span></span>
                ANALYSIS ENGINE RUNNING
            </div>
        </div>
    `;
    document.body.appendChild(
        overlay
    );
    injectProgressStyles();
}
function injectProgressStyles() {
    if (
        document.getElementById(
            "cryptorisk-progress-styles"
        )
    ) {
        return;
    }
    const style =
        document.createElement("style");
    style.id =
        "cryptorisk-progress-styles";
    style.textContent = `
        #analysis-progress {
            position: fixed;
            inset: 0;
            z-index: 99999;
            display: flex;
            align-items: center;
            justify-content: center;
            opacity: 0;
            visibility: hidden;
            pointer-events: none;
            transition:
                opacity .25s ease,
                visibility .25s ease;
        }
        #analysis-progress.is-visible {
            opacity: 1;
            visibility: visible;
            pointer-events: auto;
        }
        .analysis-progress-backdrop {
            position: absolute;
            inset: 0;
            background: rgba(5, 8, 15, .88);
            backdrop-filter: blur(14px);
        }
        .analysis-progress-card {
            position: relative;
            width: min(520px, calc(100% - 36px));
            padding: 30px;
            border: 1px solid rgba(255,255,255,.12);
            border-radius: 18px;
            background:
                linear-gradient(
                    145deg,
                    rgba(22,27,38,.98),
                    rgba(10,14,22,.98)
                );
            box-shadow:
                0 30px 100px rgba(0,0,0,.55);
        }
        .analysis-progress-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 20px;
            margin-bottom: 16px;
        }
        .analysis-progress-kicker {
            font-size: 11px;
            font-weight: 700;
            letter-spacing: .16em;
            opacity: .65;
        }
        .analysis-progress-percent {
            font-family: "JetBrains Mono", monospace;
            font-size: 14px;
            font-weight: 700;
        }
        .analysis-progress-title {
            font-family: "Space Grotesk", sans-serif;
            font-size: 25px;
            font-weight: 700;
            letter-spacing: .02em;
            margin-bottom: 8px;
        }
        .analysis-progress-card p {
            margin: 0 0 22px;
            opacity: .65;
            line-height: 1.6;
            font-size: 14px;
        }
        .analysis-progress-track {
            width: 100%;
            height: 7px;
            overflow: hidden;
            border-radius: 999px;
            background: rgba(255,255,255,.08);
        }
        .analysis-progress-fill {
            width: 0%;
            height: 100%;
            border-radius: inherit;
            background: currentColor;
            transition: width .65s ease;
            box-shadow: 0 0 18px currentColor;
        }
        .analysis-progress-statuses {
            display: grid;
            grid-template-columns:
                repeat(4, 1fr);
            gap: 8px;
            margin-top: 18px;
        }
        .progress-status {
            font-size: 9px;
            font-weight: 700;
            letter-spacing: .08em;
            opacity: .3;
            transition:
                opacity .2s ease,
                transform .2s ease;
        }
        .progress-status.active {
            opacity: 1;
            transform: translateY(-1px);
        }
        .progress-status.complete {
            opacity: .65;
        }
        .analysis-progress-pulse {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-top: 24px;
            font-family: "JetBrains Mono", monospace;
            font-size: 10px;
            letter-spacing: .08em;
            opacity: .55;
        }
        .analysis-progress-pulse span {
            width: 7px;
            height: 7px;
            border-radius: 50%;
            background: currentColor;
            animation:
                cryptoriskPulse 1.1s
                infinite ease-in-out;
        }
        @keyframes cryptoriskPulse {
            0%, 100% {
                opacity: .25;
                transform: scale(.8);
            }
            50% {
                opacity: 1;
                transform: scale(1.15);
            }
        }
        body.analysis-running {
            overflow: hidden;
        }
        @media (max-width: 600px) {
            .analysis-progress-card {
                padding: 24px;
            }
            .analysis-progress-title {
                font-size: 21px;
            }
            .analysis-progress-statuses {
                gap: 5px;
            }
            .progress-status {
                font-size: 8px;
            }
        }
    `;
    document.head.appendChild(
        style
    );
}
createProgressOverlay();
const overlay =
    document.getElementById(
        "analysis-progress"
    );
const progressFill =
    document.getElementById(
        "progress-fill"
    );
const progressPercent =
    document.getElementById(
        "progress-percent"
    );
const progressMessage =
    document.getElementById(
        "progress-message"
    );
const progressStage =
    document.getElementById(
        "progress-stage"
    );
const progressStatuses =
    document.querySelectorAll(
        ".progress-status"
    );
/*
==========================================================
LOGOUT
==========================================================
*/
async function handleLogout(event) {
    event?.preventDefault();
    localStorage.removeItem("token");
    localStorage.removeItem("auth_token");
    try {
        await fetch(
            apiUrl("/logout"),
            requestOptions({
                method: "GET",
            })
        );
    } catch (error) {
        console.warn(
            "Logout request failed:",
            error
        );
    }
    window.location.href =
        "index.html";
}
const logoutButton =
    document.getElementById(
        "logout-button"
    );
if (logoutButton) {
    logoutButton.addEventListener(
        "click",
        handleLogout
    );
}
/*
==========================================================
TOKEN INPUT
==========================================================
*/
if (input) {
    input.addEventListener(
        "input",
        () => {
            input.value =
                input.value
                    .toUpperCase()
                    .replace(
                        /[^A-Z0-9._-]/g,
                        ""
                    );
        }
    );
}
/*
==========================================================
PROGRESS ENGINE
==========================================================
*/
const progressStages = [
    {
        percent: 12,
        stage: "INITIALIZING",
        message:
            "Preparing cryptocurrency intelligence request...",
        active: 0,
    },
    {
        percent: 30,
        stage: "RESEARCHING",
        message:
            "Collecting market and asset intelligence...",
        active: 0,
    },
    {
        percent: 55,
        stage: "AI ANALYSIS",
        message:
            "Gemini is evaluating risk signals and evidence...",
        active: 1,
    },
    {
        percent: 78,
        stage: "STRUCTURING",
        message:
            "Building the structured intelligence report...",
        active: 2,
    },
    {
        percent: 92,
        stage: "SECURING",
        message:
            "Saving your analysis securely...",
        active: 3,
    },
];
function updateProgress(stageData) {
    if (!stageData) return;
    if (progressFill) {
        progressFill.style.width =
            `${stageData.percent}%`;
    }
    if (progressPercent) {
        progressPercent.textContent =
            `${stageData.percent}%`;
    }
    if (progressStage) {
        progressStage.textContent =
            stageData.stage;
    }
    if (progressMessage) {
        progressMessage.textContent =
            stageData.message;
    }
    progressStatuses.forEach(
        (item, index) => {
            item.classList.remove(
                "active",
                "complete"
            );
            if (
                index <
                stageData.active
            ) {
                item.classList.add(
                    "complete"
                );
            }
            if (
                index ===
                stageData.active
            ) {
                item.classList.add(
                    "active"
                );
            }
        }
    );
}
function startProgress() {
    if (!overlay) return;
    if (progressTimer) {
        clearTimeout(
            progressTimer
        );
        progressTimer = null;
    }
    overlay.classList.add(
        "is-visible"
    );
    overlay.setAttribute(
        "aria-hidden",
        "false"
    );
    document.body.classList.add(
        "analysis-running"
    );
    let currentStage = 0;
    updateProgress(
        progressStages[0]
    );
    const advance = () => {
        if (
            currentStage >=
            progressStages.length - 1
        ) {
            progressTimer = null;
            return;
        }
        currentStage += 1;
        updateProgress(
            progressStages[currentStage]
        );
        progressTimer =
            window.setTimeout(
                advance,
                1800
            );
    };
    progressTimer =
        window.setTimeout(
            advance,
            1200
        );
}
function stopProgress() {
    if (progressTimer) {
        clearTimeout(
            progressTimer
        );
        progressTimer = null;
    }
    if (overlay) {
        overlay.classList.remove(
            "is-visible"
        );
        overlay.setAttribute(
            "aria-hidden",
            "true"
        );
    }
    document.body.classList.remove(
        "analysis-running"
    );
}
/*
==========================================================
UTILITY
==========================================================
*/
function setText(selector, value) {
    const element =
        document.querySelector(
            selector
        );
    if (element) {
        element.textContent =
            value ?? "—";
    }
}
function safeNumber(
    value,
    fallback = 0
) {
    const number =
        Number(value);
    return Number.isFinite(number)
        ? number
        : fallback;
}
/*
==========================================================
RISK PILLARS
==========================================================
*/
function renderPillar(
    key,
    value
) {
    const score =
        Math.max(
            0,
            Math.min(
                100,
                safeNumber(
                    value,
                    0
                )
            )
        );
    setText(
        `#pillar-${key}-value`,
        `${Math.round(score)}/100`
    );
    const bar =
        document.querySelector(
            `#pillar-${key}-bar`
        );
    if (bar) {
        bar.style.width =
            `${score}%`;
    }
}
/*
==========================================================
FORENSIC CARDS
==========================================================
*/
function renderForensicCards(
    cards
) {
    const container =
        document.querySelector(
            "#forensic-cards"
        );
    if (!container) return;
    container.replaceChildren();
    const safeCards =
        Array.isArray(cards)
            ? cards.slice(0, 3)
            : [];
    const fallbackTitles = [
        "Momentum & Drawdown Risk",
        "Liquidity Depth & Slippage Risk",
        "Macro & Contract Sensitivity",
    ];
    const cardsToRender =
        safeCards.length
            ? safeCards
            : fallbackTitles.map(
                (title) => ({
                    title,
                    body:
                        "Awaiting live evidence.",
                })
            );
    cardsToRender.forEach(
        (card, index) => {
            const article =
                document.createElement(
                    "article"
                );
            article.className =
                "forensic-card";
            const number =
                document.createElement(
                    "span"
                );
            number.className =
                "forensic-index";
            number.textContent =
                String(index + 1)
                    .padStart(
                        2,
                        "0"
                    );
            const heading =
                document.createElement(
                    "h4"
                );
            heading.textContent =
                card?.title ||
                "Forensic finding";
            const paragraph =
                document.createElement(
                    "p"
                );
            paragraph.textContent =
                card?.body ||
                "Awaiting live evidence.";
            article.append(
                number,
                heading,
                paragraph
            );
            container.appendChild(
                article
            );
        }
    );
}
/*
==========================================================
DASHBOARD RENDER
==========================================================
*/
function renderDashboard(
    payload
) {
    if (
        !payload ||
        typeof payload !==
            "object"
    ) {
        return;
    }
    const latest =
        payload.latest || null;
    const user =
        payload.user || {};
    document
        .querySelectorAll(
            ".user-name"
        )
        .forEach(
            (element) => {
                element.textContent =
                    user.name ||
                    user.username ||
                    "User";
            }
        );
    const avatar =
        document.getElementById(
            "user-avatar"
        );
    if (avatar) {
        const name =
            user.name ||
            user.username ||
            "User";
        avatar.textContent =
            name
                .charAt(0)
                .toUpperCase();
    }
    if (!latest) {
        return;
    }
    currentReportId =
        latest.id ||
        currentReportId;
    const profile =
        latest.risk_profile ||
        {};
    const stress =
        latest.stress_test ||
        {};
    const autopsy =
        latest.autopsy ||
        {};
    const token =
        latest.token ||
        latest.token_symbol ||
        "ASSET";
    setText(
        "#report-token",
        token
    );
    setText(
        "#report-outlook",
        latest.trend ||
        latest.outlook ||
        "NEUTRAL"
    );
    setText(
        "#autopsy-token",
        `${token} / LIVE EVIDENCE`
    );
    setText(
        "#autopsy-summary",
        autopsy.autopsy_summary ||
        latest.autopsy_summary ||
        latest.summary ||
        "Awaiting live evidence."
    );
    setText(
        "#stress-beta",
        `${safeNumber(
            stress.beta,
            1
        ).toFixed(2)}x`
    );
    setText(
        "#stress-drawdown",
        `${safeNumber(
            stress.expected_drawdown,
            -10
        ).toFixed(2)}%`
    );
    setText(
        "#stress-resilience",
        stress.resilience_label ||
        "Moderate"
    );
    setText(
        "#stress-verdict",
        autopsy.stress_verdict ||
        latest.stress_verdict ||
        "Awaiting modeled BTC shock."
    );
    renderPillar(
        "volatility",
        profile.volatility_risk
    );
    renderPillar(
        "liquidity",
        profile.liquidity_risk
    );
    renderPillar(
        "contract",
        profile.contract_risk
    );
    renderPillar(
        "composite",
        profile.composite_score
    );
    renderForensicCards(
        autopsy.cards
    );
    const riskStrong =
        reportRiskScore?.querySelector(
            "strong"
        );
    if (riskStrong) {
        riskStrong.textContent =
            latest.risk_score_value ??
            latest.risk_score ??
            latest.risk ??
            "—";
    }
}
/*
==========================================================
HISTORY RENDER
==========================================================
*/
function renderHistory(
    history
) {
    const body =
        document.querySelector(
            "#history-tbody"
        );
    const count =
        document.getElementById(
            "history-count"
        );
    const safeHistory =
        Array.isArray(history)
            ? history
            : [];
    if (count) {
        count.textContent =
            `${safeHistory.length} REPORT${
                safeHistory.length === 1
                    ? ""
                    : "S"
            }`;
    }
    if (!body) return;
    body.replaceChildren();
    if (
        safeHistory.length
    ) {
        currentReportId =
            safeHistory[0]?.id ||
            currentReportId;
    }
    safeHistory.forEach(
        (item) => {
            const row =
                document.createElement(
                    "tr"
                );
            const asset =
                document.createElement(
                    "td"
                );
            const assetStrong =
                document.createElement(
                    "strong"
                );
            assetStrong.className =
                "history-token";
            assetStrong.textContent =
                item.token_symbol ||
                item.token ||
                "—";
            asset.appendChild(
                assetStrong
            );
            const outlook =
                document.createElement(
                    "td"
                );
            const outlookSpan =
                document.createElement(
                    "span"
                );
            outlookSpan.className =
                "neutral";
            outlookSpan.textContent =
                item.trend ||
                item.outlook ||
                "Unknown";
            outlook.appendChild(
                outlookSpan
            );
            const risk =
                document.createElement(
                    "td"
                );
            const riskSpan =
                document.createElement(
                    "span"
                );
            riskSpan.className =
                "high";
            riskSpan.textContent =
                item.risk_score ??
                item.risk ??
                "—";
            risk.appendChild(
                riskSpan
            );
            const price =
                document.createElement(
                    "td"
                );
            price.textContent =
                item.predicted_price ??
                "—";
            const time =
                document.createElement(
                    "td"
                );
            time.textContent =
                item.created_at ||
                "—";
            const action =
                document.createElement(
                    "td"
                );
            const deleteButton =
                document.createElement(
                    "button"
                );
            deleteButton.type =
                "button";
            deleteButton.className =
                "history-delete-button";
            deleteButton.dataset.deleteReport =
                item.id;
            deleteButton.title =
                "Delete report";
            deleteButton.setAttribute(
                "aria-label",
                "Delete report"
            );
            deleteButton.textContent =
                "×";
            action.appendChild(
                deleteButton
            );
            row.append(
                asset,
                outlook,
                risk,
                price,
                time,
                action
            );
            body.appendChild(
                row
            );
        }
    );
}
/*
==========================================================
MARKET DATA
==========================================================
*/
const tickerMap = {
    BTC: "bitcoin",
    ETH: "ethereum",
    SOL: "solana",
    USDT: "tether",
    USDC: "usd-coin",
    BNB: "binancecoin",
    XRP: "ripple",
    ADA: "cardano",
    DOGE: "dogecoin",
};
function formatUsd(
    value
) {
    const amount =
        Number(value);
    if (
        !Number.isFinite(
            amount
        )
    ) {
        return "—";
    }
    const absolute =
        Math.abs(amount);
    if (
        absolute >= 1e9
    ) {
        return `$${(
            amount / 1e9
        ).toFixed(2)}B`;
    }
    if (
        absolute >= 1e6
    ) {
        return `$${(
            amount / 1e6
        ).toFixed(2)}M`;
    }
    if (
        absolute >= 1e3
    ) {
        return `$${(
            amount / 1e3
        ).toFixed(2)}K`;
    }
    return `$${amount.toFixed(
        2
    )}`;
}
function calculateMarketRiskScore(
    marketData
) {
    let score = 50;
    const change7d =
        Math.abs(
            safeNumber(
                marketData
                    .price_change_percentage_7d_in_currency,
                0
            )
        );
    const marketCap =
        safeNumber(
            marketData.market_cap,
            1
        );
    const volume =
        safeNumber(
            marketData.total_volume,
            0
        );
    const turnover =
        volume /
        Math.max(
            marketCap,
            1
        );
    if (change7d > 20) {
        score += 15;
    } else if (
        change7d < 5
    ) {
        score -= 10;
    }
    if (turnover < 0.02) {
        score += 15;
    } else if (
        turnover > 0.10
    ) {
        score -= 10;
    }
    return Math.max(
        1,
        Math.min(
            99,
            Math.trunc(score)
        )
    );
}
async function loadMarketData(
    ticker
) {
    const normalized =
        ticker
            .trim()
            .toUpperCase();
    const coinId =
        tickerMap[
            normalized
        ];
    const controller =
        new AbortController();
    const timeout =
        window.setTimeout(
            () =>
                controller.abort(),
            10000
        );
    try {
        let resolvedCoinId =
            coinId;
        if (!resolvedCoinId) {
            const searchResponse =
                await fetch(
                    `https://api.coingecko.com/api/v3/search?query=${encodeURIComponent(
                        normalized
                    )}`,
                    {
                        signal:
                            controller.signal,
                    }
                );
            if (
                searchResponse.status ===
                429
            ) {
                throw new Error(
                    "Market data is rate-limited. Try again shortly."
                );
            }
            if (
                !searchResponse.ok
            ) {
                throw new Error(
                    "Market search failed."
                );
            }
            const searchData =
                await searchResponse.json();
            const coin =
                (
                    searchData.coins ||
                    []
                ).find(
                    (item) =>
                        String(
                            item.symbol ||
                            ""
                        ).toLowerCase() ===
                        normalized.toLowerCase()
                );
            if (!coin) {
                throw new Error(
                    "Ticker not found."
                );
            }
            resolvedCoinId =
                coin.id;
        }
        const marketResponse =
            await fetch(
                `https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=${encodeURIComponent(
                    resolvedCoinId
                )}&price_change_percentage=7d`,
                {
                    signal:
                        controller.signal,
                }
            );
        if (
            marketResponse.status ===
            429
        ) {
            throw new Error(
                "Market data is rate-limited. Try again shortly."
            );
        }
        if (
            !marketResponse.ok
        ) {
            throw new Error(
                "Market data request failed."
            );
        }
        const data =
            await marketResponse.json();
        const marketData =
            data?.[0];
        if (!marketData) {
            throw new Error(
                "Market data returned no result."
            );
        }
        if (reportPrice) {
            reportPrice.textContent =
                formatUsd(
                    marketData.current_price
                );
        }
        if (reportChange) {
            const change =
                safeNumber(
                    marketData.price_change_percentage_24h,
                    0
                );
            reportChange.textContent =
                `${
                    change >= 0
                        ? "+"
                        : ""
                }${change.toFixed(
                    2
                )}%`;
            reportChange.classList.toggle(
                "positive",
                change >= 0
            );
            reportChange.classList.toggle(
                "negative",
                change < 0
            );
        }
        if (reportVolume) {
            reportVolume.textContent =
                `24H VOL ${formatUsd(
                    marketData.total_volume
                )}`;
        }
        if (reportRiskScore) {
            const score =
                calculateMarketRiskScore(
                    marketData
                );
            const strong =
                reportRiskScore.querySelector(
                    "strong"
                );
            if (strong) {
                strong.textContent =
                    score;
            }
            reportRiskScore.classList.remove(
                "risk-score-green",
                "risk-score-yellow",
                "risk-score-red"
            );
            reportRiskScore.classList.add(
                score <= 35
                    ? "risk-score-green"
                    : score <= 69
                        ? "risk-score-yellow"
                        : "risk-score-red"
            );
        }
        return marketData;
    } finally {
        clearTimeout(
            timeout
        );
    }
}
/*
==========================================================
DASHBOARD API
==========================================================
*/
async function parseResponse(
    response
) {
    const contentType =
        response.headers.get(
            "content-type"
        ) || "";
    if (
        contentType.includes(
            "application/json"
        )
    ) {
        return await response.json();
    }
    const text =
        await response.text();
    return {
        success: false,
        message:
            text ||
            `Request failed with status ${response.status}.`,
    };
}
async function loadDashboard() {
    const response =
        await fetch(
            apiUrl(
                "/api/dashboard"
            ),
            requestOptions({
                method: "GET",
                headers: {
                    Accept:
                        "application/json",
                },
            })
        );
    if (
        response.status ===
        401
    ) {
        logoutAndStop();
        return null;
    }
    const payload =
        await parseResponse(
            response
        );
    if (!response.ok) {
        throw new Error(
            payload.message ||
            "Unable to load dashboard."
        );
    }
    renderDashboard(
        payload
    );
    renderHistory(
        payload.history || []
    );
    return payload;
}
async function initializeDashboardOnce() {
    if (
        dashboardInitialized ||
        !isDashboardPage
    ) {
        return;
    }
    dashboardInitialized =
        true;
    try {
        await loadDashboard();
    } catch (error) {
        console.error(
            "Dashboard initialization failed:",
            error
        );
    }
}
/*
==========================================================
ANALYSIS FORM
==========================================================
*/
if (form) {
    form.addEventListener(
        "submit",
        async (event) => {
            event.preventDefault();
            const button =
                form.querySelector(
                    ".analyze-button"
                );
            const buttonText =
                button?.querySelector(
                    ".button-text"
                );
            const token =
                input?.value
                    .trim()
                    .toUpperCase() ||
                "";
            if (
                !button ||
                !token ||
                form.dataset.submitting ===
                    "true"
            ) {
                return;
            }
            form.dataset.submitting =
                "true";
            button.disabled =
                true;
            button.classList.add(
                "is-loading"
            );
            if (buttonText) {
                buttonText.textContent =
                    "Analyzing...";
            }
            startProgress();
            try {
                const response =
                    await fetch(
                        apiUrl(
                            "/api/dashboard"
                        ),
                        requestOptions({
                            method:
                                "POST",
                            headers: {
                                "Content-Type":
                                    "application/json",
                                Accept:
                                    "application/json",
                                "X-Requested-With":
                                    "XMLHttpRequest",
                            },
                            body:
                                JSON.stringify(
                                    {
                                        token_symbol:
                                            token,
                                    }
                                ),
                        })
                    );
                if (
                    response.status ===
                    401
                ) {
                    logoutAndStop();
                    return;
                }
                const payload =
                    await parseResponse(
                        response
                    );
                if (
                    !response.ok ||
                    payload.success === false
                ) {
                    throw new Error(
                        payload.message ||
                        payload.error ||
                        `Analysis failed (${response.status}).`
                    );
                }
                /*
                Keep progress visible long enough
                for the successful transition to feel
                intentional.
                */
                updateProgress({
                    percent: 100,
                    stage: "COMPLETE",
                    message:
                        "Risk intelligence report ready.",
                    active: 3,
                });
                renderDashboard(
                    payload
                );
                renderHistory(
                    payload.history ||
                    []
                );
                /*
                Market data should not destroy an
                otherwise successful AI analysis.
                */
                try {
                    await loadMarketData(
                        token
                    );
                } catch (
                    marketError
                ) {
                    console.warn(
                        "Market data unavailable:",
                        marketError
                    );
                }
                await new Promise(
                    (resolve) =>
                        setTimeout(
                            resolve,
                            450
                        )
                );
            } catch (error) {
                console.error(
                    "Analysis request failed:",
                    error
                );
                window.alert(
                    error?.message ||
                    "Unable to complete analysis."
                );
            } finally {
                stopProgress();
                form.dataset.submitting =
                    "false";
                button.disabled =
                    false;
                button.classList.remove(
                    "is-loading"
                );
                if (buttonText) {
                    buttonText.textContent =
                        "Analyze";
                }
            }
        }
    );
}
/*
==========================================================
INITIAL LOAD
==========================================================
*/
initializeDashboardOnce();
/*
==========================================================
HISTORY DELETE
==========================================================
*/
const historyBody =
    document.querySelector(
        "#history-tbody"
    );
async function deleteReport(
    reportId,
    button
) {
    if (!reportId) return;
    if (
        !window.confirm(
            "Delete this analysis report? This cannot be undone."
        )
    ) {
        return;
    }
    if (button) {
        button.disabled =
            true;
    }
    try {
        const response =
            await fetch(
                apiUrl(
                    `/api/history/${encodeURIComponent(
                        reportId
                    )}/delete`
                ),
                requestOptions({
                    method:
                        "POST",
                    headers: {
                        Accept:
                            "application/json",
                    },
                })
            );
        if (
            response.status ===
            401
        ) {
            logoutAndStop();
            return;
        }
        const payload =
            await parseResponse(
                response
            );
        if (!response.ok) {
            throw new Error(
                payload.message ||
                "Unable to delete report."
            );
        }
        await loadDashboard();
    } catch (error) {
        console.error(
            "Delete failed:",
            error
        );
        if (button) {
            button.disabled =
                false;
        }
        window.alert(
            error.message ||
            "Unable to delete report."
        );
    }
}
if (historyBody) {
    historyBody.addEventListener(
        "click",
        async (event) => {
            const button =
                event.target.closest(
                    "[data-delete-report]"
                );
            if (!button) return;
            await deleteReport(
                button.dataset
                    .deleteReport,
                button
            );
        }
    );
}
const deleteCurrentButton =
    document.querySelector(
        "#delete-current-report"
    );
if (deleteCurrentButton) {
    deleteCurrentButton.addEventListener(
        "click",
        async (event) => {
            event.preventDefault();
            if (!currentReportId) {
                return;
            }
            await deleteReport(
                currentReportId,
                deleteCurrentButton
            );
        }
    );
}
/*
==========================================================
3D POINTER EFFECT
==========================================================
*/
const cards =
    document.querySelectorAll(
        ".search-card, " +
        ".intelligence-report, " +
        ".history-card, " +
        ".report-panel, " +
        ".metric-card, " +
        ".risk-hero-card"
    );
cards.forEach(
    (card) => {
        card.addEventListener(
            "pointermove",
            (event) => {
                const rect =
                    card.getBoundingClientRect();
                if (
                    !rect.width ||
                    !rect.height
                ) {
                    return;
                }
                const x =
                    event.clientX -
                    rect.left;
                const y =
                    event.clientY -
                    rect.top;
                const rotateX =
                    (
                        y /
                            rect.height -
                        0.5
                    ) * -2;
                const rotateY =
                    (
                        x /
                            rect.width -
                        0.5
                    ) * 2;
                card.style.setProperty(
                    "--mouse-x",
                    `${x}px`
                );
                card.style.setProperty(
                    "--mouse-y",
                    `${y}px`
                );
                card.style.transform =
                    `perspective(1000px)
                     rotateX(${rotateX}deg)
                     rotateY(${rotateY}deg)
                     translateZ(0)`;
            }
        );
        card.addEventListener(
            "pointerleave",
            () => {
                card.style.transform =
                    "";
            }
        );
    }
);
/*
==========================================================
FLASH MESSAGES
==========================================================
*/
document
    .querySelectorAll(".flash")
    .forEach(
        (flash) => {
            setTimeout(
                () => {
                    flash.style.opacity =
                        "0";
                    flash.style.transform =
                        "translateY(-8px)";
                    setTimeout(
                        () =>
                            flash.remove(),
                        400
                    );
                },
                7000
            );
        }
    );

});