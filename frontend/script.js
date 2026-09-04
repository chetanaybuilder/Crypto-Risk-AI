document.addEventListener("DOMContentLoaded", () => {

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
        "analysisProgress"
    );

    const progressFill = document.getElementById(
        "progressFill"
    );

    const progressPercent = document.getElementById(
        "progressPercent"
    );

    const progressMessage = document.getElementById(
        "progressMessage"
    );

    const progressStage = document.getElementById(
        "progressStage"
    );

    const progressStatuses =
        document.querySelectorAll(
            ".progress-status"
        );


    async function fetchUserAudits() {

        const historyBody = document.getElementById(
            "history-tbody"
        );

        if (!historyBody || !window.supabaseClient) {
            return;
        }

        const { data: userData, error: userError } =
            await window.supabaseClient.auth.getUser();

        if (userError) {
            throw userError;
        }

        if (!userData.user) {
            historyBody.innerHTML =
                '<tr><td colspan="6">Sign in to view your audit history.</td></tr>';
            return;
        }

        const { data: audits, error: auditError } =
            await window.supabaseClient
                .from("risk_audits")
                .select("ticker, risk_score, outlook, price, created_at")
                .eq("user_id", userData.user.id)
                .order("created_at", { ascending: false });

        if (auditError) {
            throw auditError;
        }

        historyBody.innerHTML = "";

        if (!audits || audits.length === 0) {
            historyBody.innerHTML =
                '<tr><td colspan="6">No saved audits yet.</td></tr>';
        } else {
            audits.forEach((audit) => {
                const row = document.createElement("tr");
                const createdAt = audit.created_at
                    ? new Date(audit.created_at).toLocaleString()
                    : "—";

                row.innerHTML = `
                    <td><strong class="history-token">${audit.ticker || "—"}</strong></td>
                    <td><span class="${String(audit.outlook || "").toLowerCase()}">${audit.outlook || "—"}</span></td>
                    <td><span class="${String(audit.risk_score || "").toLowerCase()}">${audit.risk_score ?? "—"}</span></td>
                    <td>${audit.price ?? "—"}</td>
                    <td>${createdAt}</td>
                    <td>—</td>
                `;

                historyBody.appendChild(row);
            });
        }

        const historyCount = document.querySelector(
            ".history-count"
        );

        if (historyCount) {
            historyCount.textContent =
                `${audits ? audits.length : 0} REPORT${audits && audits.length === 1 ? "" : "S"}`;
        }

    }


    fetchUserAudits().catch((error) => {
        console.error("Unable to fetch user audits:", error);
    });


    async function handleLogout() {

        if (!window.supabaseClient) {
            console.error("Supabase client is unavailable.");
            return;
        }

        const { error } =
            await window.supabaseClient.auth.signOut();

        if (error) {
            console.error("Unable to sign out:", error);
            return;
        }

        window.location.href = "login.html";

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

    async function analyzeRisk(ticker) {

        const response = await fetch(
            "https://wcowwebrwowbcakngyeg.supabase.co/functions/v1/Analyze-Risk",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "Authorization": `Bearer ${window.supabaseAnonKey}`
                },
                body: JSON.stringify({ ticker })
            }
        );

        if (!response.ok) {
            throw new Error(
                `Risk analysis request failed (${response.status}).`
            );
        }

        return response.json();
    }

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

        form.addEventListener(
            "submit",
            (event) => {

                const button =
                    form.querySelector(
                        ".analyze-button"
                    );

                if (!button) {
                    return;
                }


                const token =
                    input
                        ? input.value.trim()
                        : "";


                if (!token) {
                    return;
                }


                /*
                Prevent double submissions.
                */

                if (
                    form.dataset.submitting ===
                    "true"
                ) {

                    event.preventDefault();

                    return;

                }


                form.dataset.submitting =
                    "true";


                button.classList.add(
                    "is-loading"
                );

                button.disabled = true;


                const text =
                    button.querySelector(
                        "span:first-child"
                    );

                if (text) {
                    text.textContent =
                        "Analyzing";
                }


                startProgress();

                if (report) {
                    report.classList.add("is-loading");
                }

                analyzeRisk(token)
                    .then((data) => {
                        console.log("Risk analysis response:", data);
                    })
                    .catch((error) => {
                        console.error("Risk analysis failed:", error);
                    });

                loadMarketData(token).catch(() => {
                    if (reportPrice) {
                        reportPrice.textContent = "—";
                    }
                }).finally(() => {
                    if (report) {
                        report.classList.remove("is-loading");
                    }
                });


    const initialTicker = input?.value.trim()
        || document.getElementById("report-token")?.textContent.trim();

    if (report && initialTicker) {
        loadMarketData(initialTicker).catch(() => {});
    }
            }
        );

    }


    const financialAuditForm = document.getElementById(
        "financial-audit-form"
    );

    if (financialAuditForm) {

        financialAuditForm.addEventListener(
            "submit",
            async (event) => {

                event.preventDefault();

                const getFieldValue = (name, id) => {
                    const field =
                        financialAuditForm.elements.namedItem(name)
                        || document.getElementById(id);

                    return field ? field.value.trim() : "";
                };

                const ticker = getFieldValue("ticker", "ticker");
                const riskScore = getFieldValue("risk_score", "risk-score");
                const outlook = getFieldValue("outlook", "outlook");
                const price = getFieldValue("price", "price");

                try {
                    await saveRiskAudit({
                        ticker,
                        riskScore,
                        outlook,
                        price
                    });
                } catch (error) {
                    console.error("Unable to save financial audit:", error);
                }

            }
        );

    }


    /*
    ==========================================================
    DELETE CONFIRMATION
    ==========================================================
    */

    const deleteButtons =
        document.querySelectorAll(
            "[data-delete-report]"
        );


    deleteButtons.forEach(
        (button) => {

            button.addEventListener(
                "click",
                (event) => {

                    const confirmed =
                        window.confirm(
                            "Delete this analysis report? This cannot be undone."
                        );


                    if (!confirmed) {

                        event.preventDefault();

                        return;

                    }


                    button.disabled = true;

                    button.textContent =
                        "Deleting...";

                }
            );

        }
    );


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