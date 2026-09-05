document.addEventListener("DOMContentLoaded", () => {

    const backendUrl = (
        window.APP_CONFIG?.backendUrl || ""
    ).replace(/\/$/, "");

    const apiUrl = (path) => `${backendUrl}${path}`;

    /*
    ==========================================================
    CRYPTORISK AI
    Dashboard Interaction Engine
    ==========================================================
    */

    const input = document.querySelector(
        'input[name="token_symbol"]'
    );

    const form = document.querySelector(
        ".search-card form"
    );

    const overlay = document.getElementById(
        "analysis-progress"
    );

    const progressFill = document.getElementById(
        "progress-fill"
    );

    const progressPercent = document.getElementById(
        "progress-percent"
    );

    const progressMessage = document.getElementById(
        "progress-title"
    );

    const progressStage = document.getElementById(
        "progress-title"
    );

    const progressStatuses =
        document.querySelectorAll(
            ".progress-status"
        );


    async function handleLogout() {

        window.location.href = apiUrl("/logout");

    }


    const logoutButton = document.getElementById(
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

                input.value = input.value
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

    let progressTimer = null;

    const progressStages = [
        {
            percent: 18,
            stage: "INITIALIZING",
            message:
                "Preparing cryptocurrency intelligence request...",
            active: 0
        },
        {
            percent: 38,
            stage: "RESEARCHING",
            message:
                "Building the asset risk intelligence context...",
            active: 0
        },
        {
            percent: 62,
            stage: "AI ANALYSIS",
            message:
                "Gemini is evaluating risks and market signals...",
            active: 1
        },
        {
            percent: 82,
            stage: "STRUCTURING",
            message:
                "Structuring your intelligence report...",
            active: 2
        },
        {
            percent: 94,
            stage: "SECURING",
            message:
                "Saving your analysis securely...",
            active: 3
        }
    ];

    const report = document.getElementById(
        "intelligence-report"
    );

    const reportPrice = document.getElementById(
        "report-price"
    );

    const reportChange = document.getElementById(
        "report-change"
    );

    const reportVolume = document.getElementById(
        "report-volume"
    );

    const reportRiskScore = document.getElementById(
        "report-risk-score"
    );

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

    function setText(selector, value) {
        const element = document.querySelector(selector);
        if (element) element.textContent = value ?? "—";
    }

    function renderInsights(selector, items, className) {
        const container = document.querySelector(selector);
        if (!container) return;

        container.replaceChildren();
        (items || []).forEach((item, index) => {
            const wrapper = document.createElement("div");
            wrapper.className = `insight-item ${className}`;
            wrapper.innerHTML = `
                <div class="insight-index">${String(index + 1).padStart(2, "0")}</div>
                <div><h4></h4><p></p></div>
            `;
            wrapper.querySelector("h4").textContent = item.title || "Insight";
            wrapper.querySelector("p").textContent = item.explanation || "";
            container.appendChild(wrapper);
        });
    }

    function renderDashboard(payload) {
        const latest = payload.latest;
        const user = payload.user || {};

        document.querySelectorAll(".user-name").forEach((element) => {
            element.textContent = user.name || user.username || "User";
        });

        if (!latest) return;

        setText("#report-token", latest.token);
        setText("#report-outlook", latest.trend);
        setText("#report-summary", latest.summary);
        setText("#report-problem", latest.problem_solved);

        if (reportRiskScore) {
            reportRiskScore.querySelector("strong").textContent =
                latest.risk_score_value ?? latest.risk ?? "—";
        }

        renderInsights("#report-risks", latest.key_risks, "risk-item");
        renderInsights("#report-signals", latest.key_signals, "signal-item");

        const watchContainer = document.querySelector("#report-watch");
        if (watchContainer) {
            watchContainer.replaceChildren();
            (latest.watch_next || []).forEach((item, index) => {
                const row = document.createElement("div");
                row.className = "watch-item";
                row.innerHTML = `<span class="watch-number">${String(index + 1).padStart(2, "0")}</span><span></span>`;
                row.querySelector("span:last-child").textContent = item;
                watchContainer.appendChild(row);
            });
        }
    }

    function renderHistory(history) {
        const body = document.querySelector("#history-tbody");
        if (!body) return;

        body.replaceChildren();
        history.forEach((item) => {
            const row = document.createElement("tr");
            row.innerHTML = `
                <td><strong class="history-token"></strong></td>
                <td><span class="neutral"></span></td>
                <td><span class="high"></span></td>
                <td></td><td></td>
                <td><button type="button" class="history-delete-button" data-delete-report="${item.id}" title="Delete report" aria-label="Delete report">×</button></td>
            `;
            row.querySelector(".history-token").textContent = item.token_symbol;
            row.children[1].firstElementChild.textContent = item.trend || "Unknown";
            row.children[2].firstElementChild.textContent = item.risk_score ?? "—";
            row.children[3].textContent = item.predicted_price ?? "—";
            row.children[4].textContent = item.created_at || "—";
            body.appendChild(row);
        });
    }

    function formatUsd(value) {
        const amount = Number(value);
        const absoluteAmount = Math.abs(amount);

        if (absoluteAmount >= 1e9) {
            return `$${(amount / 1e9).toFixed(2)}B`;
        }
        if (absoluteAmount >= 1e6) {
            return `$${(amount / 1e6).toFixed(2)}M`;
        }
        if (absoluteAmount >= 1e3) {
            return `$${(amount / 1e3).toFixed(2)}K`;
        }

        return `$${amount.toFixed(2)}`;
    }

    function calculateMarketRiskScore(marketData) {
        let score = 50;
        const change7d = Math.abs(Number(marketData.price_change_percentage_7d_in_currency || 0));
        const turnover = Number(marketData.total_volume || 0) / Number(marketData.market_cap || 1);

        if (change7d > 20) score += 15;
        else if (change7d < 5) score -= 10;
        if (turnover < 0.02) score += 15;
        else if (turnover > 0.10) score -= 10;

        return Math.max(1, Math.min(99, Math.trunc(score)));
    }


    async function loadMarketData(ticker) {

        const normalizedTicker = ticker.toUpperCase();
        const coinId = tickerMap[normalizedTicker];
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 10000);
        let resolvedCoinId = coinId;

        try {
            if (!resolvedCoinId) {
                const searchResponse = await fetch(
                    `https://api.coingecko.com/api/v3/search?query=${encodeURIComponent(ticker)}`,
                    { signal: controller.signal }
                );

                if (searchResponse.status === 429) {
                    throw new Error("Market data is rate-limited. Try again shortly.");
                }
                if (!searchResponse.ok) throw new Error("Market search failed.");

                const searchData = await searchResponse.json();
                const coin = (searchData.coins || []).find(
                    (item) => item.symbol.toLowerCase() === ticker.toLowerCase()
                );

                if (!coin) throw new Error("Ticker not found.");
                resolvedCoinId = coin.id;
            }

            const marketResponse = await fetch(
                `https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=${encodeURIComponent(resolvedCoinId)}&price_change_percentage=7d`,
                { signal: controller.signal }
            );

            if (marketResponse.status === 429) {
                throw new Error("Market data is rate-limited. Try again shortly.");
            }
            if (!marketResponse.ok) throw new Error("Market data request failed.");

            const marketData = (await marketResponse.json())[0];

            if (!marketData) throw new Error("Market data request returned no data.");

            if (reportPrice) reportPrice.textContent = formatUsd(marketData.current_price);

            if (reportChange) {
                const change = Number(marketData.price_change_percentage_24h || 0);
                reportChange.textContent = `${change >= 0 ? "+" : ""}${change.toFixed(2)}%`;
                reportChange.classList.toggle("positive", change >= 0);
                reportChange.classList.toggle("negative", change < 0);
            }

            if (reportVolume) reportVolume.innerHTML = `24H VOL <strong>${formatUsd(marketData.total_volume)}</strong>`;
            if (reportRiskScore) {
                const score = calculateMarketRiskScore(marketData);
                reportRiskScore.querySelector("strong").textContent = score;
                reportRiskScore.classList.remove("risk-score-green", "risk-score-yellow", "risk-score-red");
                reportRiskScore.classList.add(score <= 35 ? "risk-score-green" : score <= 69 ? "risk-score-yellow" : "risk-score-red");
            }
        } finally {
            clearTimeout(timeout);
        }

    }


    async function loadDashboard() {
        const response = await fetch(apiUrl("/api/dashboard"), {
            credentials: "include",
        });

        if (response.status === 401) {
            window.location.href = apiUrl("/auth/google");
            return;
        }

        if (!response.ok) throw new Error("Unable to load dashboard.");

        const payload = await response.json();
        renderDashboard(payload);
        renderHistory(payload.history || []);
    }

    function updateProgress(stageData) {

        if (!progressFill) {
            return;
        }

        progressFill.style.width =
            `${stageData.percent}%`;

        if (progressPercent) {
            progressPercent.textContent =
                `${stageData.percent}%`;
        }

        if (progressMessage) {
            progressMessage.textContent =
                stageData.message;
        }

        if (progressStage) {
            progressStage.textContent =
                stageData.stage;
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

        if (!overlay) {
            return;
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

        progressTimer = setInterval(
            () => {

                if (
                    currentStage <
                    progressStages.length - 1
                ) {

                    currentStage++;

                    updateProgress(
                        progressStages[
                            currentStage
                        ]
                    );

                } else {

                    clearInterval(
                        progressTimer
                    );

                }

            },
            1600
        );

    }


    /*
    ==========================================================
    ANALYSIS FORM
    ==========================================================
    */

    if (form) {

        form.addEventListener("submit", async (event) => {
            event.preventDefault();

            const button = form.querySelector(".analyze-button");
            const token = input?.value.trim() || "";
            if (!button || !token || form.dataset.submitting === "true") return;

            form.dataset.submitting = "true";
            button.disabled = true;
            button.classList.add("is-loading");
            button.querySelector("span:first-child").textContent = "Analyzing";
            startProgress();

            try {
                const response = await fetch(apiUrl("/api/dashboard"), {
                    method: "POST",
                    credentials: "include",
                    headers: {
                        "Content-Type": "application/json",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    body: JSON.stringify({ token_symbol: token }),
                });

                const payload = await response.json();
                if (!response.ok || !payload.success) {
                    throw new Error(payload.message || "Analysis failed.");
                }

                renderDashboard(payload);
                renderHistory(payload.history || []);
                await loadMarketData(token);
            } catch (error) {
                console.error(error);
                window.alert(error.message || "Unable to complete analysis.");
            } finally {
                form.dataset.submitting = "false";
                button.disabled = false;
                button.classList.remove("is-loading");
                button.querySelector("span:first-child").textContent = "Analyze";
            }
        });

        loadDashboard().catch((error) => console.error(error));

    }


    /*
    ==========================================================
    DELETE CONFIRMATION
    ==========================================================
    */

    const historyBody = document.querySelector("#history-tbody");

    if (historyBody) {
        historyBody.addEventListener("click", async (event) => {
            const button = event.target.closest("[data-delete-report]");
            if (!button) return;
            if (!window.confirm("Delete this analysis report? This cannot be undone.")) return;

            button.disabled = true;

            try {
                const response = await fetch(
                    apiUrl(`/api/history/${button.dataset.deleteReport}/delete`),
                    { method: "POST", credentials: "include" }
                );

                if (!response.ok) throw new Error("Unable to delete report.");
                await loadDashboard();
            } catch (error) {
                console.error(error);
                button.disabled = false;
                window.alert(error.message);
            }
        });
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

                    /*
                    Keep the effect subtle.
                    It enhances the existing CSS
                    instead of fighting it.
                    */

                    const rect =
                        card.getBoundingClientRect();

                    const x =
                        event.clientX -
                        rect.left;

                    const y =
                        event.clientY -
                        rect.top;

                    const rotateX =
                        (
                            (y / rect.height) -
                            0.5
                        ) * -2;

                    const rotateY =
                        (
                            (x / rect.width) -
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
    AUTO HIDE FLASH MESSAGES
    ==========================================================
    */

    const flashes =
        document.querySelectorAll(
            ".flash"
        );


    flashes.forEach(
        (flash) => {

            setTimeout(
                () => {

                    flash.style.opacity =
                        "0";

                    flash.style.transform =
                        "translateY(-8px)";

                    setTimeout(
                        () => {
                            flash.remove();
                        },
                        400
                    );

                },
                7000
            );

        }
    );

});