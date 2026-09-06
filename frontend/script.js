/* ============================================================
   CRYPTORISK AI
   FRONTEND INTELLIGENCE TERMINAL
   PART 1 / 2
   ============================================================ */

(() => {
    "use strict";

    /* ---------------------------------------------------------
       CONFIG
       --------------------------------------------------------- */

    const CONFIG = window.CONFIG || {};

    const API_BASE_URL = String(
        CONFIG.API_BASE_URL ||
        "https://crypto-risk-ai-j1ag.onrender.com"
    ).replace(/\/+$/, "");

    const API_TIMEOUT =
        Number(CONFIG.API_TIMEOUT) > 0
            ? Number(CONFIG.API_TIMEOUT)
            : 30000;

    const LIVE_REFRESH_INTERVAL =
        Number(CONFIG.LIVE_REFRESH_INTERVAL) > 0
            ? Number(CONFIG.LIVE_REFRESH_INTERVAL)
            : 15000;

    const TOKEN_KEYS = ["token", "auth_token"];

    /* ---------------------------------------------------------
       APPLICATION STATE
       --------------------------------------------------------- */

    const state = {
        token: null,
        user: null,
        report: null,
        history: [],
        analysisRunning: false,
        liveTimer: null,
        liveRefreshing: false
    };

    /* ---------------------------------------------------------
       DOM HELPERS
       --------------------------------------------------------- */

    function getElement(id) {
        return document.getElementById(id);
    }

    function query(selector) {
        return document.querySelector(selector);
    }

    function queryAll(selector) {
        return Array.from(document.querySelectorAll(selector));
    }

    function isDashboardPage() {
        return document.body.classList.contains("dashboard-page");
    }

    function setText(id, value) {
        const element = getElement(id);

        if (!element) {
            return;
        }

        if (value === undefined || value === null || value === "") {
            element.textContent = "—";
        } else {
            element.textContent = String(value);
        }
    }

    function setHidden(id, hidden) {
        const element = getElement(id);

        if (!element) {
            return;
        }

        element.hidden = Boolean(hidden);
    }

    function addClass(id, className) {
        const element = getElement(id);

        if (element && className) {
            element.classList.add(className);
        }
    }

    function removeClasses(id, classes) {
        const element = getElement(id);

        if (!element) {
            return;
        }

        classes.forEach((className) => {
            element.classList.remove(className);
        });
    }

    /* ---------------------------------------------------------
       AUTHENTICATION
       --------------------------------------------------------- */

    function getToken() {
        for (const key of TOKEN_KEYS) {
            const token = localStorage.getItem(key);

            if (token) {
                return token;
            }
        }

        return null;
    }

    function saveToken(token) {
        if (!token) {
            return;
        }

        localStorage.setItem("token", token);
        localStorage.setItem("auth_token", token);

        state.token = token;
    }

    function clearToken() {
        TOKEN_KEYS.forEach((key) => {
            localStorage.removeItem(key);
        });

        state.token = null;
    }

    function processOAuthToken() {
        const params = new URLSearchParams(window.location.search);
        const token = params.get("token");

        if (!token) {
            return;
        }

        saveToken(token);

        params.delete("token");

        const query = params.toString();

        const cleanURL =
            window.location.pathname +
            (query ? `?${query}` : "");

        window.history.replaceState(
            {},
            document.title,
            cleanURL
        );
    }

    /* ---------------------------------------------------------
       API
       --------------------------------------------------------- */

    function buildAPIURL(path) {
        const normalized =
            String(path || "").startsWith("/")
                ? path
                : `/${path}`;

        return `${API_BASE_URL}${normalized}`;
    }

    async function apiRequest(path, options = {}) {
        const controller = new AbortController();

        const timeoutId = window.setTimeout(() => {
            controller.abort();
        }, API_TIMEOUT);

        const headers = new Headers(
            options.headers || {}
        );

        if (options.body && !headers.has("Content-Type")) {
            headers.set(
                "Content-Type",
                "application/json"
            );
        }

        const token = state.token || getToken();

        if (token) {
            headers.set(
                "Authorization",
                `Bearer ${token}`
            );
        }

        try {
            const response = await fetch(
                buildAPIURL(path),
                {
                    ...options,
                    headers,
                    credentials: "include",
                    signal: controller.signal
                }
            );

            let payload = null;

            const contentType =
                response.headers.get("content-type") || "";

            if (contentType.includes("application/json")) {
                try {
                    payload = await response.json();
                } catch {
                    payload = null;
                }
            }

            if (response.status === 401) {
                clearToken();

                if (isDashboardPage()) {
                    window.location.replace("index.html");
                }

                throw new Error(
                    "Your session has expired. Please sign in again."
                );
            }

            if (!response.ok) {
                const message =
                    payload?.error ||
                    payload?.message ||
                    `Request failed (${response.status}).`;

                throw new Error(message);
            }

            return payload;
        } catch (error) {
            if (error.name === "AbortError") {
                throw new Error(
                    "The request timed out. Please try again."
                );
            }

            throw error;
        } finally {
            window.clearTimeout(timeoutId);
        }
    }

    /* ---------------------------------------------------------
       FORM / ERROR UI
       --------------------------------------------------------- */

    function showError(message) {
        const element = getElement("analysis-error");

        if (!element) {
            return;
        }

        element.textContent = message || "";
        element.hidden = !message;
    }

    function setAnalyzeLoading(loading) {
        const button =
            getElement("analyze-button");

        const loader =
            getElement("button-loader");

        if (button) {
            button.disabled = loading;
            button.classList.toggle(
                "is-loading",
                loading
            );
        }

        if (loader) {
            loader.hidden = !loading;
        }
    }

    /* ---------------------------------------------------------
       GOOGLE LOGIN
       --------------------------------------------------------- */

    function setupGoogleLogin() {
        queryAll("[data-google-login]").forEach(
            (link) => {
                link.setAttribute(
                    "href",
                    buildAPIURL("/api/auth/google")
                );
            }
        );
    }

    /* ---------------------------------------------------------
       LOGOUT
       --------------------------------------------------------- */

    function setupLogout() {
        const button =
            getElement("logout-button");

        if (!button) {
            return;
        }

        button.addEventListener(
            "click",
            async () => {
                button.disabled = true;

                try {
                    await apiRequest(
                        "/api/auth/logout",
                        {
                            method: "POST"
                        }
                    );
                } catch (error) {
                    console.warn(
                        "Logout request failed:",
                        error
                    );
                } finally {
                    clearToken();

                    window.location.replace(
                        "index.html"
                    );
                }
            }
        );
    }

    /* ---------------------------------------------------------
       USER
       --------------------------------------------------------- */

    function renderUser(user) {
        if (!user) {
            return;
        }

        state.user = user;

        setText(
            "user-name",
            user.username ||
            user.name ||
            "User"
        );

        setText(
            "user-email",
            user.email || ""
        );

        const avatar =
            getElement("user-avatar");

        if (!avatar) {
            return;
        }

        const name =
            user.username ||
            user.name ||
            user.email ||
            "U";

        avatar.textContent =
            String(name)
                .charAt(0)
                .toUpperCase();

        if (user.avatar_url) {
            avatar.style.backgroundImage =
                `url("${String(user.avatar_url)
                    .replace(/"/g, '\\"')}")`;

            avatar.style.backgroundSize =
                "cover";

            avatar.style.backgroundPosition =
                "center";

            avatar.textContent = "";
        } else {
            avatar.style.backgroundImage = "";
        }
    }

    async function loadUser() {
        const payload =
            await apiRequest("/api/auth/me");

        if (payload?.user) {
            renderUser(payload.user);
        }

        return payload;
    }

    /* ---------------------------------------------------------
       PROGRESS OVERLAY
       --------------------------------------------------------- */

    function ensureProgressOverlay() {
        if (getElement("analysis-progress")) {
            return;
        }

        const overlay =
            document.createElement("div");

        overlay.id = "analysis-progress";
        overlay.hidden = true;

        overlay.innerHTML = `
            <div class="progress-overlay">
                <div class="progress-card">
                    <div class="progress-eyebrow">
                        CRYPTORISK AI
                    </div>

                    <h3 id="progress-title">
                        Preparing analysis
                    </h3>

                    <div class="progress-track">
                        <div id="progress-fill"></div>
                    </div>

                    <div class="progress-meta">
                        <span id="progress-percent">
                            0%
                        </span>

                        <span>
                            EVIDENCE ENGINE
                        </span>
                    </div>
                </div>
            </div>
        `;

        document.body.appendChild(overlay);
    }

    function updateProgress(title, percent) {
        ensureProgressOverlay();

        setText(
            "progress-title",
            title
        );

        setText(
            "progress-percent",
            `${percent}%`
        );

        const fill =
            getElement("progress-fill");

        if (fill) {
            const bounded =
                Math.max(
                    0,
                    Math.min(100, Number(percent) || 0)
                );

            fill.style.width =
                `${bounded}%`;
        }
    }

    function showProgress() {
        ensureProgressOverlay();

        setHidden(
            "analysis-progress",
            false
        );
    }

    function hideProgress() {
        setHidden(
            "analysis-progress",
            true
        );
    }

    /* ---------------------------------------------------------
       FORMATTERS
       --------------------------------------------------------- */

    function numeric(value) {
        const number = Number(value);

        return Number.isFinite(number)
            ? number
            : null;
    }

    function formatPrice(value) {
        const number = numeric(value);

        if (number === null) {
            return "—";
        }

        if (number >= 1) {
            return `$${number.toLocaleString(
                "en-US",
                {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2
                }
            )}`;
        }

        if (number >= 0.01) {
            return `$${number.toLocaleString(
                "en-US",
                {
                    minimumFractionDigits: 4,
                    maximumFractionDigits: 4
                }
            )}`;
        }

        if (number > 0) {
            return `$${number.toPrecision(6)}`;
        }

        return "$0.00";
    }

    function formatCompact(value) {
        const number = numeric(value);

        if (number === null) {
            return "—";
        }

        const absolute =
            Math.abs(number);

        if (absolute >= 1e12) {
            return `$${(
                number / 1e12
            ).toFixed(2)}T`;
        }

        if (absolute >= 1e9) {
            return `$${(
                number / 1e9
            ).toFixed(2)}B`;
        }

        if (absolute >= 1e6) {
            return `$${(
                number / 1e6
            ).toFixed(2)}M`;
        }

        if (absolute >= 1e3) {
            return `$${(
                number / 1e3
            ).toFixed(2)}K`;
        }

        return `$${number.toFixed(2)}`;
    }

    function formatPercent(value) {
        const number = numeric(value);

        if (number === null) {
            return "—";
        }

        const sign =
            number > 0
                ? "+"
                : "";

        return `${sign}${number.toFixed(2)}%`;
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
            return "—";
        }

        return date.toLocaleString(
            "en-IN",
            {
                day: "2-digit",
                month: "short",
                year: "numeric",
                hour: "2-digit",
                minute: "2-digit"
            }
        );
    }

    /* ---------------------------------------------------------
       RISK HELPERS
       --------------------------------------------------------- */

    function normalizeSeverity(value) {
        return String(
            value || ""
        )
            .trim()
            .toLowerCase();
    }

    function riskClass(severity) {
        const value =
            normalizeSeverity(severity);

        if (value.includes("critical")) {
            return "risk-critical";
        }

        if (value.includes("high")) {
            return "risk-high";
        }

        if (value.includes("moderate")) {
            return "risk-moderate";
        }

        if (value.includes("low")) {
            return "risk-low";
        }

        return "";
    }

    function applyRiskClass(element, severity) {
        if (!element) {
            return;
        }

        removeClasses(
            element.id,
            [
                "risk-low",
                "risk-moderate",
                "risk-high",
                "risk-critical"
            ]
        );

        const className =
            riskClass(severity);

        if (className) {
            element.classList.add(
                className
            );
        }
    }

    function setChangeClass(id, value) {
        const element =
            getElement(id);

        if (!element) {
            return;
        }

        element.classList.remove(
            "positive",
            "negative",
            "neutral"
        );

        const number =
            numeric(value);

        if (number === null) {
            element.classList.add(
                "neutral"
            );
        } else if (number > 0) {
            element.classList.add(
                "positive"
            );
        } else if (number < 0) {
            element.classList.add(
                "negative"
            );
        } else {
            element.classList.add(
                "neutral"
            );
        }
    }

    function setRiskBar(id, value) {
        const element =
            getElement(id);

        if (!element) {
            return;
        }

        const number =
            numeric(value);

        if (number === null) {
            element.style.width =
                "0%";

            return;
        }

        const bounded =
            Math.max(
                0,
                Math.min(100, number)
            );

        element.style.width =
            `${bounded}%`;
    }

    /* ---------------------------------------------------------
       REPORT VISIBILITY
       --------------------------------------------------------- */

    function setReportVisible(visible) {
        const report =
            getElement(
                "intelligence-report"
            );

        if (!report) {
            return;
        }

        report.hidden = !visible;

        report.classList.toggle(
            "report-visible",
            Boolean(visible)
        );
    }

    /* ---------------------------------------------------------
       REPORT EXTRACTION
       --------------------------------------------------------- */

    function extractReport(payload) {
        if (!payload) {
            return null;
        }

        return (
            payload.latest ||
            payload.analysis ||
            payload.report ||
            null
        );
    }

    /* ---------------------------------------------------------
       RENDER REPORT
       --------------------------------------------------------- */

    function renderReport(report) {
        if (!report) {
            setReportVisible(false);
            return;
        }

        state.report = report;

        setReportVisible(true);

        renderIdentity(report);
        renderMarket(report);
        renderRisk(report);
        renderStress(report);
        renderAutopsy(report);

        /* IMPORTANT:
           Data quality is rendered here so every
           report path updates it automatically. */
        renderDataQuality(report);
    }

    /* ---------------------------------------------------------
       IDENTITY
       --------------------------------------------------------- */

    function renderIdentity(report) {
        const asset =
            report.asset || {};

        const profile =
            report.risk_profile || {};

        const ai =
            report.ai || {};

        const symbol =
            asset.symbol || "—";

        setText(
            "report-token",
            symbol
        );

        setText(
            "report-outlook",
            ai.risk_regime ||
            profile.severity ||
            "UNAVAILABLE"
        );

        setText(
            "autopsy-token",
            `${symbol} / LIVE EVIDENCE`
        );

        setText(
            "autopsy-summary",
            ai.executive_summary ||
            "No executive summary is available."
        );

        document.title =
            `${symbol} Risk Intelligence | CryptoRisk AI`;
    }

    /* ---------------------------------------------------------
       MARKET
       --------------------------------------------------------- */

    function renderMarket(report) {
        const market =
            report.market || {};

        const change =
            numeric(
                market.price_change_24h_pct
            );

        setText(
            "report-price",
            formatPrice(
                market.current_price_usd
            )
        );

        setText(
            "report-change",
            change === null
                ? "—"
                : formatPercent(change)
        );

        setChangeClass(
            "report-change",
            change
        );

        setText(
            "report-volume",
            formatCompact(
                market.total_volume_usd
            )
        );

        setText(
            "report-market-cap",
            formatCompact(
                market.market_cap_usd
            )
        );

        setText(
            "report-change-7d",
            formatPercent(
                market.price_change_7d_pct
            )
        );

        setText(
            "report-high",
            formatPrice(
                market.high_24h_usd
            )
        );

        setText(
            "report-low",
            formatPrice(
                market.low_24h_usd
            )
        );

        const status =
            getElement("market-status");

        if (status) {
            status.textContent =
                market.source
                    ? `LIVE · ${market.source}`
                    : "LIVE MARKET DATA";
        }

        setText(
            "market-live-status",
            market.source
                ? `LIVE · ${market.source}`
                : "LIVE"
        );

        setText(
            "market-updated",
            market.timestamp
                ? `Updated ${formatDate(
                    market.timestamp
                )}`
                : "Live market data"
        );

        setText(
            "data-source",
            market.source ||
            "Unavailable"
        );
    }

    /* ---------------------------------------------------------
       RISK
       --------------------------------------------------------- */

    function renderRisk(report) {
        const profile =
            report.risk_profile || {};

        const pillars =
            profile.pillars || {};

        const score =
            numeric(
                profile.overall_score
            );

        setText(
            "report-risk-score",
            score === null
                ? "—"
                : Math.round(score)
        );

        setText(
            "report-risk-label",
            profile.severity ||
            "UNAVAILABLE"
        );

        const scoreElement =
            getElement(
                "report-risk-score"
            );

        const labelElement =
            getElement(
                "report-risk-label"
            );

        applyRiskClass(
            scoreElement,
            profile.severity
        );

        applyRiskClass(
            labelElement,
            profile.severity
        );

        const volatility =
            pillars.volatility?.score;

        const liquidity =
            pillars.liquidity?.score;

        const structural =
            pillars.structural?.score;

        const sensitivity =
            pillars.market_sensitivity?.score;

        setText(
            "pillar-volatility-value",
            numeric(volatility) === null
                ? "N/A"
                : Math.round(
                    Number(volatility)
                )
        );

        setText(
            "pillar-liquidity-value",
            numeric(liquidity) === null
                ? "N/A"
                : Math.round(
                    Number(liquidity)
                )
        );

        setText(
            "pillar-contract-value",
            numeric(structural) === null
                ? "N/A"
                : Math.round(
                    Number(structural)
                )
        );

        setText(
            "pillar-composite-value",
            numeric(sensitivity) === null
                ? "N/A"
                : Math.round(
                    Number(sensitivity)
                )
        );

        setRiskBar(
            "pillar-volatility-bar",
            volatility
        );

        setRiskBar(
            "pillar-liquidity-bar",
            liquidity
        );

        setRiskBar(
            "pillar-contract-bar",
            structural
        );

        setRiskBar(
            "pillar-composite-bar",
            sensitivity
        );

        renderRiskDrivers(report);
    }

    /* ---------------------------------------------------------
       RISK DRIVERS
       --------------------------------------------------------- */

    function renderRiskDrivers(report) {
        const container =
            getElement("risk-drivers");

        if (!container) {
            return;
        }

        container.replaceChildren();

        const drivers =
            Array.isArray(
                report.risk_drivers
            )
                ? report.risk_drivers
                : [];

        if (!drivers.length) {
            const empty =
                document.createElement("div");

            empty.className =
                "risk-driver empty";

            empty.textContent =
                "No additional quantified risk drivers available.";

            container.appendChild(empty);

            return;
        }

        drivers
            .slice(0, 6)
            .forEach((driver) => {
                const card =
                    document.createElement("div");

                card.className =
                    "risk-driver";

                const title =
                    document.createElement("strong");

                const detail =
                    document.createElement("span");

                if (
                    typeof driver ===
                    "string"
                ) {
                    title.textContent =
                        driver;

                    detail.textContent =
                        "Evidence signal";
                } else {
                    title.textContent =
                        driver.name ||
                        driver.title ||
                        driver.factor ||
                        "Risk driver";

                    detail.textContent =
                        driver.detail ||
                        driver.description ||
                        driver.reason ||
                        "Quantitative risk signal";
                }

                card.appendChild(title);
                card.appendChild(detail);

                container.appendChild(card);
            });
        }

        /* ============================================================
   CRYPTORISK AI
   FRONTEND INTELLIGENCE TERMINAL
   PART 2 / 2
   ============================================================ */

    /* ---------------------------------------------------------
       STRESS TEST
       --------------------------------------------------------- */

    function renderStress(report) {
        const stress =
            report.stress_test || {};

        const beta =
            numeric(stress.beta);

        const drawdown =
            numeric(
                stress.expected_drawdown_pct
            );

        setText(
            "stress-beta",
            beta === null
                ? "—"
                : `${beta.toFixed(2)}x`
        );

        setText(
            "stress-drawdown",
            drawdown === null
                ? "—"
                : formatPercent(drawdown)
        );

        setText(
            "stress-resilience",
            stress.resilience_label ||
            "UNAVAILABLE"
        );

        setText(
            "stress-confidence",
            stress.confidence ||
            "—"
        );

        const ai =
            report.ai || {};

        setText(
            "stress-verdict",
            ai.stress_interpretation ||
            stress.verdict ||
            buildStressVerdict(stress)
        );
    }

    function buildStressVerdict(stress) {
        const scenarios =
            Array.isArray(stress.scenarios)
                ? stress.scenarios
                : [];

        if (!scenarios.length) {
            return "Stress-test interpretation is unavailable.";
        }

        const scenario =
            scenarios[0] || {};

        const scenarioDrawdown =
            numeric(
                scenario.expected_drawdown_pct
            );

        if (scenarioDrawdown !== null) {
            return (
                `The selected stress scenario estimates ` +
                `an expected drawdown of ` +
                `${formatPercent(scenarioDrawdown)}.`
            );
        }

        return (
            "Stress scenario data is available for review."
        );
    }

    /* ---------------------------------------------------------
       AUTOPSY / FORENSIC VIEW
       --------------------------------------------------------- */

    function renderAutopsy(report) {
        const ai =
            report.ai || {};

        const security =
            report.security || {};

        setText(
            "autopsy-summary",
            ai.executive_summary ||
            "No executive summary is available."
        );

        const container =
            getElement("forensic-cards");

        if (!container) {
            return;
        }

        container.replaceChildren();

        const secondary =
            Array.isArray(
                ai.secondary_risk_drivers
            )
                ? ai.secondary_risk_drivers
                : [];

        const securityFlags =
            Array.isArray(
                security.red_flags
            )
                ? security.red_flags
                : [];

        const liquidityDetail =
            report
                .risk_profile
                ?.pillars
                ?.liquidity
                ?.detail;

        const cards = [
            {
                title: "MARKET STRUCTURE",
                text:
                    ai.what_matters_now ||
                    ai.primary_risk_driver ||
                    "No market-structure interpretation available."
            },
            {
                title: "RISK SIGNALS",
                text:
                    secondary[0] ||
                    securityFlags[0] ||
                    ai.primary_risk_driver ||
                    "No additional risk signal available."
            },
            {
                title: "LIQUIDITY PROFILE",
                text:
                    liquidityDetail ||
                    ai.watch_next ||
                    "Liquidity evidence should be monitored continuously."
            }
        ];

        cards.forEach((item) => {
            const card =
                document.createElement("article");

            card.className =
                "forensic-card";

            const heading =
                document.createElement("span");

            heading.className =
                "forensic-label";

            heading.textContent =
                item.title;

            const body =
                document.createElement("p");

            body.textContent =
                String(item.text);

            card.appendChild(heading);
            card.appendChild(body);

            container.appendChild(card);
        });
    }

    /* ---------------------------------------------------------
       DATA QUALITY
       --------------------------------------------------------- */

    function renderDataQuality(report) {
        const quality =
            report.data_quality || {};

        const evidence =
            report.evidence || {};

        const confidence =
            quality.confidence ||
            report.risk_profile?.confidence ||
            "—";

        const source =
            quality.source ||
            report.market?.source ||
            evidence.market_source ||
            "—";

        setText(
            "data-confidence",
            confidence
        );

        setText(
            "market-source",
            source
        );

        const freshness =
            numeric(
                quality.freshness_seconds
            );

        setText(
            "data-freshness",
            freshness === null
                ? "—"
                : `${Math.round(
                    freshness
                )}s`
        );

        const missing =
            Array.isArray(
                quality.missing_signals
            )
                ? quality.missing_signals
                : [];

        const container =
            getElement("missing-signals");

        if (!container) {
            return;
        }

        container.replaceChildren();

        if (!missing.length) {
            const item =
                document.createElement("span");

            item.textContent =
                "No major missing signals reported.";

            container.appendChild(item);

            return;
        }

        missing
            .slice(0, 8)
            .forEach((signal) => {
                const item =
                    document.createElement("span");

                item.textContent =
                    String(signal);

                container.appendChild(item);
            });
    }

    /* ---------------------------------------------------------
       HISTORY
       --------------------------------------------------------- */

    function renderHistory(history) {
        const tbody =
            getElement("history-tbody");

        if (!tbody) {
            return;
        }

        const rows =
            Array.isArray(history)
                ? history
                : [];

        setText(
            "history-count",
            rows.length
        );

        tbody.replaceChildren();

        if (!rows.length) {
            const row =
                document.createElement("tr");

            const cell =
                document.createElement("td");

            cell.colSpan = 5;
            cell.className =
                "history-empty";

            cell.textContent =
                "No analyses yet.";

            row.appendChild(cell);
            tbody.appendChild(row);

            return;
        }

        rows.forEach((item) => {
            const row =
                document.createElement("tr");

            const asset =
                document.createElement("td");

            const risk =
                document.createElement("td");

            const outlook =
                document.createElement("td");

            const date =
                document.createElement("td");

            const action =
                document.createElement("td");

            const symbol =
                item.token_symbol ||
                item.asset?.symbol ||
                "—";

            const severity =
                item.risk_severity ||
                item.severity ||
                "—";

            const score =
                numeric(item.risk_score);

            const trend =
                item.trend ||
                item.risk_regime ||
                "—";

            asset.textContent =
                String(symbol);

            risk.textContent =
                score === null
                    ? String(
                        severity
                    ).toUpperCase()
                    : `${String(
                        severity
                    ).toUpperCase()} · ${Math.round(
                        score
                    )}`;

            outlook.textContent =
                String(trend);

            date.textContent =
                formatDate(
                    item.created_at
                );

            const openButton =
                document.createElement("button");

            openButton.type = "button";
            openButton.className =
                "history-action";

            openButton.textContent =
                "OPEN";

            openButton.addEventListener(
                "click",
                () => {
                    openHistoryReport(
                        item.id
                    );
                }
            );

            action.appendChild(
                openButton
            );

            row.appendChild(asset);
            row.appendChild(risk);
            row.appendChild(outlook);
            row.appendChild(date);
            row.appendChild(action);

            tbody.appendChild(row);
        });
    }

    /* ---------------------------------------------------------
       OPEN HISTORY REPORT
       --------------------------------------------------------- */

    async function openHistoryReport(id) {
        if (!id) {
            return;
        }

        try {
            showError("");

            const payload =
                await apiRequest(
                    `/api/history/${encodeURIComponent(
                        id
                    )}`
                );

            const report =
                extractReport(payload);

            if (!report) {
                throw new Error(
                    "This report could not be loaded."
                );
            }

            renderReport(report);
            startLivePolling();

            window.scrollTo({
                top: 0,
                behavior: "smooth"
            });

        } catch (error) {
            console.error(
                "History error:",
                error
            );

            showError(
                error.message ||
                "Unable to load this report."
            );
        }
    }

    /* ---------------------------------------------------------
       LOAD DASHBOARD
       --------------------------------------------------------- */

    async function loadDashboard() {
        try {
            const payload =
                await apiRequest(
                    "/api/dashboard"
                );

            if (payload?.user) {
                renderUser(
                    payload.user
                );
            }

            state.history =
                Array.isArray(
                    payload?.history
                )
                    ? payload.history
                    : [];

            renderHistory(
                state.history
            );

            const report =
                extractReport(payload);

            if (report) {
                renderReport(report);
                startLivePolling();
            } else {
                setReportVisible(false);
            }

        } catch (error) {
            console.error(
                "Dashboard loading error:",
                error
            );

            showError(
                error.message ||
                "Unable to load the dashboard."
            );
        }
    }

    /* ---------------------------------------------------------
       ANALYSIS
       --------------------------------------------------------- */

    async function runAnalysis(symbol) {
        if (
            state.analysisRunning
        ) {
            return;
        }

        state.analysisRunning = true;

        showError("");
        setAnalyzeLoading(true);
        showProgress();

        try {
            updateProgress(
                "Fetching live market data",
                15
            );

            await delay(250);

            updateProgress(
                "Computing quantitative signals",
                35
            );

            const payload =
                await apiRequest(
                    "/api/analyze",
                    {
                        method: "POST",
                        body: JSON.stringify({
                            token_symbol: symbol
                        })
                    }
                );

            updateProgress(
                "Running stress model",
                65
            );

            await delay(250);

            updateProgress(
                "Synthesizing evidence",
                82
            );

            await delay(250);

            const report =
                extractReport(payload);

            if (!report) {
                throw new Error(
                    "The analysis engine returned no report."
                );
            }

            renderReport(report);

            if (
                Array.isArray(
                    payload?.history
                )
            ) {
                state.history =
                    payload.history;

                renderHistory(
                    state.history
                );
            }

            updateProgress(
                "Saving report",
                100
            );

            await delay(400);

            startLivePolling();

        } catch (error) {
            console.error(
                "Analysis error:",
                error
            );

            showError(
                error.message ||
                "Analysis failed. Please try again."
            );

        } finally {
            hideProgress();
            setAnalyzeLoading(false);
            state.analysisRunning = false;
        }
    }

    function delay(milliseconds) {
        return new Promise(
            (resolve) => {
                window.setTimeout(
                    resolve,
                    milliseconds
                );
            }
        );
    }

    /* ---------------------------------------------------------
       ANALYSIS FORM
       --------------------------------------------------------- */

    function setupAnalysisForm() {
        const form =
            getElement(
                "analysis-form"
            );

        if (!form) {
            return;
        }

        form.addEventListener(
            "submit",
            async (event) => {
                event.preventDefault();

                const input =
                    getElement(
                        "token-symbol"
                    );

                if (!input) {
                    return;
                }

                const symbol =
                    String(
                        input.value || ""
                    )
                        .trim()
                        .toUpperCase();

                input.value =
                    symbol;

                if (
                    !/^[A-Z0-9]{2,15}$/.test(
                        symbol
                    )
                ) {
                    showError(
                        "Enter a valid token symbol using 2–15 letters or numbers."
                    );

                    input.focus();

                    return;
                }

                await runAnalysis(
                    symbol
                );
            }
        );

        const input =
            getElement(
                "token-symbol"
            );

        if (input) {
            input.addEventListener(
                "input",
                () => {
                    input.value =
                        input.value
                            .toUpperCase()
                            .replace(
                                /[^A-Z0-9]/g,
                                ""
                            )
                            .slice(0, 15);

                    if (
                        input.value.length >= 2
                    ) {
                        showError("");
                    }
                }
            );
        }
    }

    /* ---------------------------------------------------------
       LIVE MARKET REFRESH
       --------------------------------------------------------- */

    async function refreshLiveMarket() {
        if (
            state.liveRefreshing ||
            !state.report?.asset?.symbol
        ) {
            return;
        }

        state.liveRefreshing = true;

        const symbol =
            String(
                state.report.asset.symbol
            ).toUpperCase();

        try {
            const payload =
                await apiRequest(
                    `/api/market/${encodeURIComponent(
                        symbol
                    )}`
                );

            const market =
                payload?.market ||
                payload?.data ||
                payload;

            if (market) {
                updateLiveMarket(
                    market
                );
            }

        } catch (error) {
            console.warn(
                "Live market refresh failed:",
                error.message
            );

        } finally {
            state.liveRefreshing =
                false;
        }
    }

    function updateLiveMarket(market) {
        const price =
            market.current_price_usd ??
            market.current_price ??
            market.price;

        const change =
            market.price_change_24h_pct ??
            market.price_change_percentage_24h ??
            market.change_24h;

        const volume =
            market.total_volume_usd ??
            market.total_volume ??
            market.volume;

        setText(
            "report-price",
            formatPrice(price)
        );

        const changeNumber =
            numeric(change);

        setText(
            "report-change",
            changeNumber === null
                ? "—"
                : formatPercent(
                    changeNumber
                )
        );

        setChangeClass(
            "report-change",
            changeNumber
        );

        setText(
            "report-volume",
            formatCompact(volume)
        );

        const status =
            getElement(
                "market-status"
            );

        if (status) {
            status.textContent =
                market.source
                    ? `LIVE · ${market.source}`
                    : "LIVE MARKET DATA";
        }

        setText(
            "market-live-status",
            market.source
                ? `LIVE · ${market.source}`
                : "LIVE"
        );

        setText(
            "market-updated",
            market.timestamp
                ? `Updated ${formatDate(
                    market.timestamp
                )}`
                : "Just refreshed"
        );
    }

    function startLivePolling() {
        stopLivePolling();

        if (
            !state.report?.asset?.symbol
        ) {
            return;
        }

        refreshLiveMarket();

        state.liveTimer =
            window.setInterval(
                refreshLiveMarket,
                LIVE_REFRESH_INTERVAL
            );
    }

    function stopLivePolling() {
        if (state.liveTimer) {
            window.clearInterval(
                state.liveTimer
            );

            state.liveTimer = null;
        }
    }

    /* ---------------------------------------------------------
       DELETE CURRENT REPORT
       --------------------------------------------------------- */

    async function deleteCurrentReport() {
        const button =
            getElement(
                "delete-current-report"
            );

        if (!button) {
            return;
        }

        const reportId =
            state.report?.id ||
            state.report?.analysis_id ||
            state.report?.report_id;

        if (!reportId) {
            showError(
                "No saved report is selected."
            );

            return;
        }

        const confirmed =
            window.confirm(
                "Delete this analysis from your history?"
            );

        if (!confirmed) {
            return;
        }

        button.disabled = true;

        try {
            await apiRequest(
                `/api/history/${encodeURIComponent(
                    reportId
                )}`,
                {
                    method: "DELETE"
                }
            );

            state.history =
                state.history.filter(
                    (item) =>
                        String(item.id) !==
                        String(reportId)
                );

            state.report = null;

            stopLivePolling();

            renderHistory(
                state.history
            );

            setReportVisible(
                false
            );

            showError("");

        } catch (error) {
            console.error(
                "Delete error:",
                error
            );

            showError(
                error.message ||
                "Unable to delete the report."
            );

        } finally {
            button.disabled = false;
        }
    }

    function setupDelete() {
        const button =
            getElement(
                "delete-current-report"
            );

        if (!button) {
            return;
        }

        button.addEventListener(
            "click",
            deleteCurrentReport
        );
    }

    /* ---------------------------------------------------------
       LANDING PAGE
       --------------------------------------------------------- */

    function setupLandingPage() {
        queryAll(
            'a[href^="#"]'
        ).forEach((link) => {
            link.addEventListener(
                "click",
                (event) => {
                    const targetID =
                        link.getAttribute(
                            "href"
                        );

                    if (
                        !targetID ||
                        targetID === "#"
                    ) {
                        return;
                    }

                    const target =
                        document.querySelector(
                            targetID
                        );

                    if (!target) {
                        return;
                    }

                    event.preventDefault();

                    target.scrollIntoView({
                        behavior: "smooth",
                        block: "start"
                    });
                }
            );
        });
    }

    /* ---------------------------------------------------------
       REVEAL EFFECTS
       --------------------------------------------------------- */

    function setupRevealEffects() {
        const elements =
            queryAll(
                ".feature-card, " +
                ".process-card, " +
                ".search-card, " +
                ".intelligence-report, " +
                ".forensic-card"
            );

        if (!elements.length) {
            return;
        }

        if (
            !("IntersectionObserver" in window)
        ) {
            elements.forEach(
                (element) => {
                    element.classList.add(
                        "is-visible"
                    );
                }
            );

            return;
        }

        const observer =
            new IntersectionObserver(
                (entries) => {
                    entries.forEach(
                        (entry) => {
                            if (
                                !entry.isIntersecting
                            ) {
                                return;
                            }

                            entry.target.classList.add(
                                "is-visible"
                            );

                            observer.unobserve(
                                entry.target
                            );
                        }
                    );
                },
                {
                    threshold: 0.08
                }
            );

        elements.forEach(
            (element) => {
                observer.observe(
                    element
                );
            }
        );
    }

    /* ---------------------------------------------------------
       POINTER / 3D EFFECT
       --------------------------------------------------------- */

    function setupPointerEffects() {
        if (
            window.matchMedia &&
            window.matchMedia(
                "(prefers-reduced-motion: reduce)"
            ).matches
        ) {
            return;
        }

        const cards =
            queryAll(
                ".feature-card, " +
                ".process-card, " +
                ".search-card, " +
                ".risk-pillar, " +
                ".stress-card, " +
                ".forensic-card"
            );

        cards.forEach((card) => {
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
                        (
                            (event.clientX -
                                rect.left) /
                                rect.width -
                            0.5
                        ) * 2;

                    const y =
                        (
                            (event.clientY -
                                rect.top) /
                                rect.height -
                            0.5
                        ) * 2;

                    card.style.setProperty(
                        "--pointer-x",
                        x.toFixed(3)
                    );

                    card.style.setProperty(
                        "--pointer-y",
                        y.toFixed(3)
                    );
                }
            );

            card.addEventListener(
                "pointerleave",
                () => {
                    card.style.removeProperty(
                        "--pointer-x"
                    );

                    card.style.removeProperty(
                        "--pointer-y"
                    );
                }
            );
        });
    }

    /* ---------------------------------------------------------
       DASHBOARD INITIALIZATION
       --------------------------------------------------------- */

    async function initializeDashboard() {
        processOAuthToken();

        state.token =
            getToken();

        if (!state.token) {
            window.location.replace(
                "index.html"
            );

            return;
        }

        setupGoogleLogin();
        setupLogout();
        setupAnalysisForm();
        setupDelete();

        ensureProgressOverlay();

        try {
            await loadUser();
        } catch (error) {
            console.warn(
                "Unable to load user:",
                error.message
            );
        }

        await loadDashboard();
    }

    /* ---------------------------------------------------------
       LANDING INITIALIZATION
       --------------------------------------------------------- */

    function initializeLanding() {
        setupGoogleLogin();
        setupLandingPage();
        setupRevealEffects();
        setupPointerEffects();
    }

    /* ---------------------------------------------------------
       APPLICATION INITIALIZATION
       --------------------------------------------------------- */

    function initialize() {
        if (isDashboardPage()) {
            initializeDashboard();
        } else {
            initializeLanding();
        }
    }

    /* ---------------------------------------------------------
       CLEANUP
       --------------------------------------------------------- */

    window.addEventListener(
        "beforeunload",
        () => {
            stopLivePolling();
        }
    );

    /* ---------------------------------------------------------
       START
       --------------------------------------------------------- */

    if (
        document.readyState ===
        "loading"
    ) {
        document.addEventListener(
            "DOMContentLoaded",
            initialize,
            {
                once: true
            }
        );
    } else {
        initialize();
    }

})();