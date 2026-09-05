document.addEventListener("DOMContentLoaded", () => {
    const backendUrl = (window.CONFIG?.API_BASE_URL || "").replace(/\/$/, "");
    const apiUrl = (path) => `${backendUrl}${path}`;

    const getAuthToken = () =>
        localStorage.getItem("token") || localStorage.getItem("auth_token");

    let hasSignedOut = false;

    function logoutAndStop() {
        if (hasSignedOut) return;
        hasSignedOut = true;
        localStorage.removeItem("token");
        localStorage.removeItem("auth_token");
        window.location.href = "index.html";
    }

    const isDashboardPage = document.body.classList.contains("dashboard-page");
    const queryToken = new URLSearchParams(window.location.search).get("token");

    if (isDashboardPage && queryToken) {
        localStorage.setItem("token", queryToken);
        window.history.replaceState({}, document.title, window.location.pathname);
    }

    if (isDashboardPage && !getAuthToken()) {
        logoutAndStop();
        return;
    }

    const requestOptions = (options = {}) => ({
        ...options,
        credentials: "include",
        headers: {
            ...(options.headers || {}),
            ...(getAuthToken() ? { Authorization: `Bearer ${getAuthToken()}` } : {}),
        },
    });

    const logoutButton = document.getElementById("logout-button");
    if (logoutButton) {
        logoutButton.addEventListener("click", () => {
            localStorage.removeItem("token");
            localStorage.removeItem("auth_token");
            window.location.href = apiUrl("/logout");
        });
    }

    const input = document.querySelector('input[name="token_symbol"]');
    if (input) {
        input.addEventListener("input", () => {
            input.value = input.value.toUpperCase().replace(/[^A-Z0-9._-]/g, "");
        });
    }

    let currentReportId = null;

    function setText(selector, value) {
        const element = document.querySelector(selector);
        if (element) element.textContent = value ?? "—";
    }

    function renderPillar(key, value) {
        const score = Math.max(0, Math.min(100, Number(value) || 0));
        setText(`#pillar-${key}-value`, `${Math.round(score)}/100`);
        const bar = document.querySelector(`#pillar-${key}-bar`);
        if (bar) {
            bar.style.width = `${score}%`;
            bar.style.background = score > 65 ? "#f43f5e" : score > 35 ? "#f59e0b" : "#38bdf8";
        }
    }

    function renderForensicCards(cards, fatalFlaws) {
        const container = document.querySelector("#forensic-cards");
        if (!container) return;

        const defaultTitles = [
            "Momentum & Drawdown Risk",
            "Liquidity Depth & Slippage Risk",
            "Macro & Contract Sensitivity"
        ];

        let finalCards = [];

        if (Array.isArray(cards) && cards.length > 0) {
            finalCards = cards;
        } else if (Array.isArray(fatalFlaws) && fatalFlaws.length > 0) {
            finalCards = fatalFlaws.map((flaw, idx) => ({
                title: defaultTitles[idx] || `Forensic factor 0${idx + 1}`,
                body: flaw
            }));
        }

        container.replaceChildren();

        if (finalCards.length === 0) {
            finalCards = [
                { title: defaultTitles[0], body: "Momentum analysis awaiting execution." },
                { title: defaultTitles[1], body: "Liquidity and turnover analysis awaiting execution." },
                { title: defaultTitles[2], body: "Macro beta shock assessment pending." }
            ];
        }

        finalCards.slice(0, 3).forEach((card, index) => {
            const article = document.createElement("article");
            article.className = "forensic-card";
            article.innerHTML = `
                <span class="forensic-index">${String(index + 1).padStart(2, "0")}</span>
                <h4>${card.title || defaultTitles[index]}</h4>
                <p>${card.body || card.explanation || "Awaiting live evidence."}</p>
            `;
            container.appendChild(article);
        });
    }

    function renderDashboard(payload) {
        const latest = payload.latest;
        const user = payload.user || {};

        document.querySelectorAll(".user-name").forEach((el) => {
            el.textContent = user.name || user.username || "User";
        });

        if (!latest) return;

        currentReportId = latest.id || currentReportId;

        const profile = latest.risk_profile || {};
        const stress = latest.stress_test || {};
        const autopsy = latest.autopsy || {};

        // Top KPIs
        setText("#report-token", latest.token);
        setText("#report-outlook", latest.trend || "Neutral");

        const riskScoreBadge = document.getElementById("report-risk-score");
        if (riskScoreBadge) {
            const score = latest.risk_score_value ?? latest.risk ?? 50;
            const strong = riskScoreBadge.querySelector("strong");
            if (strong) strong.textContent = score;

            riskScoreBadge.classList.remove("risk-score-green", "risk-score-yellow", "risk-score-red");
            riskScoreBadge.classList.add(score >= 70 ? "risk-score-red" : score >= 40 ? "risk-score-yellow" : "risk-score-green");
        }

        // Price, Volume, 24h Change
        setText("#report-price", latest.current_price_display || latest.price || "—");

        const changeVal = latest.change_24h_display || (latest.market_data?.price_change_percentage_24h ? `${latest.market_data.price_change_percentage_24h.toFixed(2)}%` : null);
        if (changeVal) {
            const reportChange = document.getElementById("report-change");
            if (reportChange) {
                reportChange.textContent = changeVal.startsWith("-") ? changeVal : `+${changeVal}`;
                reportChange.classList.toggle("negative", changeVal.startsWith("-"));
                reportChange.classList.toggle("positive", !changeVal.startsWith("-"));
            }
        }

        const volVal = latest.volume_24h_display || latest.market_data?.volume_24h_display;
        if (volVal) {
            const reportVolume = document.getElementById("report-volume");
            if (reportVolume) reportVolume.innerHTML = `24H VOL <strong>${volVal}</strong>`;
        }

        // Four-Pillar Radar
        renderPillar("volatility", profile.volatility_risk ?? 50);
        renderPillar("liquidity", profile.liquidity_risk ?? 50);
        renderPillar("contract", profile.contract_risk ?? 15);
        renderPillar("composite", profile.composite_score ?? latest.risk_score_value ?? 50);

        // Downside Simulator
        setText("#stress-beta", `${Number(stress.beta || 1.0).toFixed(2)}x`);
        setText("#stress-drawdown", `${Number(stress.expected_drawdown ?? -10.0).toFixed(2)}%`);
        setText("#stress-resilience", stress.resilience_label || "Moderate");

        // Autopsy & Forensic Cards
        setText("#autopsy-token", `${latest.token || "ASSET"} / LIVE EVIDENCE`);
        setText("#autopsy-summary", autopsy.autopsy_summary || latest.autopsy_summary || latest.summary || "Awaiting live evidence.");
        setText("#stress-verdict", autopsy.stress_verdict || latest.stress_verdict || "Awaiting modeled BTC shock.");

        renderForensicCards(latest.forensic_cards || autopsy.cards, latest.fatal_flaws);
    }

    function renderHistory(history) {
        const body = document.querySelector("#history-tbody");
        const count = document.querySelector(".history-count");
        if (!body) return;

        body.replaceChildren();
        if (count) count.textContent = `${history.length} ${history.length === 1 ? "REPORT" : "REPORTS"}`;

        currentReportId = history[0]?.id || currentReportId;

        history.forEach((item) => {
            const row = document.createElement("tr");
            row.innerHTML = `
                <td><strong class="history-token">${item.token_symbol}</strong></td>
                <td><span class="outlook-pill">${item.trend || "Neutral"}</span></td>
                <td><span class="risk-pill">${item.risk_score ?? "—"}</span></td>
                <td>${item.predicted_price ?? "—"}</td>
                <td>${item.created_at || "—"}</td>
                <td><button type="button" class="history-delete-button" data-delete-report="${item.id}" title="Delete report" aria-label="Delete report">×</button></td>
            `;
            body.appendChild(row);
        });
    }

    async function loadDashboard() {
        try {
            const response = await fetch(apiUrl("/api/dashboard"), requestOptions());
            if (response.status === 401) {
                logoutAndStop();
                return null;
            }
            if (!response.ok) throw new Error("Unable to load dashboard data.");

            const payload = await response.json();
            renderDashboard(payload);
            renderHistory(payload.history || []);
            return payload;
        } catch (error) {
            console.error("Dashboard data load failed:", error);
        }
    }

    // Form Handling
    const form = document.querySelector("#analysis-form") || document.querySelector(".search-card form");
    if (form) {
        form.addEventListener("submit", async (event) => {
            event.preventDefault();

            const button = document.getElementById("analyze-button");
            const token = input?.value.trim() || "";
            if (!button || !token || form.dataset.submitting === "true") return;

            form.dataset.submitting = "true";
            button.disabled = true;
            const originalText = button.innerHTML;
            button.innerHTML = `<span>Analyzing...</span>`;

            try {
                const response = await fetch(apiUrl("/api/dashboard"), requestOptions({
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    body: JSON.stringify({ token_symbol: token }),
                }));

                if (response.status === 401) {
                    logoutAndStop();
                    return;
                }

                const payload = await response.json();
                if (!response.ok || !payload.success) {
                    throw new Error(payload.message || "Analysis failed.");
                }

                renderDashboard(payload);
                renderHistory(payload.history || []);
            } catch (error) {
                console.error(error);
                window.alert(error.message || "Unable to complete analysis.");
            } finally {
                form.dataset.submitting = "false";
                button.disabled = false;
                button.innerHTML = originalText;
            }
        });
    }

    // Delete Report Action Handlers
    const historyBody = document.querySelector("#history-tbody");
    if (historyBody) {
        historyBody.addEventListener("click", async (event) => {
            const button = event.target.closest("[data-delete-report]");
            if (!button) return;
            if (!window.confirm("Delete this analysis report?")) return;

            button.disabled = true;
            try {
                const response = await fetch(
                    apiUrl(`/api/history/${button.dataset.deleteReport}/delete`),
                    requestOptions({ method: "POST" })
                );
                if (response.status === 401) return logoutAndStop();
                if (!response.ok) throw new Error("Unable to delete report.");
                await loadDashboard();
            } catch (err) {
                console.error(err);
                button.disabled = false;
            }
        });
    }

    const deleteCurrentButton = document.querySelector("#delete-current-report");
    if (deleteCurrentButton) {
        deleteCurrentButton.addEventListener("click", async (event) => {
            event.preventDefault();
            if (!currentReportId || !window.confirm("Delete this report?")) return;

            deleteCurrentButton.disabled = true;
            try {
                const response = await fetch(
                    apiUrl(`/api/history/${currentReportId}/delete`),
                    requestOptions({ method: "POST" })
                );
                if (response.status === 401) return logoutAndStop();
                if (!response.ok) throw new Error("Unable to delete report.");
                await loadDashboard();
            } catch (err) {
                console.error(err);
                deleteCurrentButton.disabled = false;
            }
        });
    }

    loadDashboard();
});