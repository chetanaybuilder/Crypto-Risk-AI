/**
 * Master UI Interaction Controller.
 * Manages view transitions, form event listeners, accordion collapsibles, and visual report resets.
 */

import { initializeDashboard, initializeIndexPage } from '../app.js';
import { syncJobPollCeiling } from '../api/analysis.js';
import { logout, handleAnalysisSubmit, handleAuthForm, consumeQueryToken } from '../api/auth.js';
import { deleteCurrentReport } from '../api/history.js';
import { renderMissingSignals } from './dataQuality.js';
import { handleHistoryClick } from './history.js';
import { state } from '../state/store.js';
import { hide, show, setText } from '../utils/dom.js';
import { stopLivePolling, startLivePolling } from '../api/market.js';
import { stopJobPolling } from '../api/analysis.js';

export function clearReportView() {
    state.latestReport = null;
    document.body.classList.remove('report-active');

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
   DELETE BUTTON STATE
   ============================================================ */

export function updateCurrentReportDeleteButton() {
    const button =
        $("#delete-current-report");

    if (!button) return;

    button.disabled =
        !state.currentReportId;
}




/* ============================================================
   KEYBOARD UX
   ============================================================ */

export function setupKeyboardShortcuts() {
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

export function setupVisibilityHandling() {
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

        if (typeof ParallaxHeist !== "undefined") {
            ParallaxHeist.destroy();
        }
    }
);




/* ============================================================
   DOLLAR-SIGN ANALYSIS BEAM
   ============================================================ */

export const AnalysisBeam = {
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

export const MoneyMeteor = {
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

export function initCardTilt() {
    document.body.addEventListener('mousemove', (e) => {
        const card = e.target.closest('.market-card, .risk-pillar, .stress-card, .stress-verdict-card, .driver-card');
        if (!card) return;

        const rect = card.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;

        const centerX = rect.width / 2;
        const centerY = rect.height / 2;

        const rotateX = ((y - centerY) / centerY) * -10;
        const rotateY = ((x - centerX) / centerX) * 10;

        card.style.transform = `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale3d(1.02, 1.02, 1.02)`;
        card.style.transition = 'none';
        card.style.zIndex = '10';
    });

    document.body.addEventListener('mouseout', (e) => {
        const card = e.target.closest('.market-card, .risk-pillar, .stress-card, .stress-verdict-card, .driver-card');
        if (!card) return;

        // Only reset if we actually left the card, not just a child element
        if (!card.contains(e.relatedTarget)) {
            card.style.transform = '';
            card.style.transition = 'transform 0.5s ease';
            card.style.zIndex = '1';
        }
    });
}

let appBootstrapped = false;

function bootstrapApp() {
    if (appBootstrapped) {
        return;
    }
    appBootstrapped = true;

    // Immediately ingest any OAuth token from URL parameters
    consumeQueryToken();

    const isDashboard = Boolean(document.querySelector("#analysis-form"));

    if (isDashboard) {
        if (typeof ParallaxHeist !== "undefined") {
            ParallaxHeist.init();
        }
        initCardTilt();

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

        const historyToggleHeader = $("#history-toggle-header");
        if (historyToggleHeader) {
            const toggleHistory = () => {
                const section = $("#history-section") || historyToggleHeader.closest(".history-section");
                const content = $("#history-content");
                if (!section || !content) return;

                const isExpanded = section.classList.contains("is-expanded");
                const nextState = !isExpanded;

                section.classList.toggle("is-expanded", nextState);
                content.classList.toggle("is-open", nextState);
                historyToggleHeader.setAttribute("aria-expanded", String(nextState));
                content.setAttribute("aria-hidden", String(!nextState));
            };

            historyToggleHeader.addEventListener("click", toggleHistory);
            historyToggleHeader.addEventListener("keydown", (e) => {
                if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    toggleHistory();
                }
            });
        }

        setupKeyboardShortcuts();
        setupVisibilityHandling();
        initializeDashboard();
        syncJobPollCeiling();
    } else {
        $all("form[data-auth]").forEach((form) => {
            form.addEventListener("submit", handleAuthForm);
        });
        initializeIndexPage();
    }
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootstrapApp);
} else {
    bootstrapApp();
}




