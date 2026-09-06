/* =========================================================
   CryptoRisk AI — Frontend Configuration
   ========================================================= */

(() => {
    "use strict";

    const CONFIG = {
        // Backend
        API_BASE_URL: "https://crypto-risk-ai-j1ag.onrender.com",

        // API behavior
        API_TIMEOUT: 30000,

        // Live market refresh
        LIVE_REFRESH_INTERVAL: 15000,

        // Authentication
        AUTH_TOKEN_KEY: "cryptorisk_auth_token",

        // App metadata
        APP_NAME: "CryptoRisk AI",
        APP_VERSION: "1.0.0",

        // Frontend behavior
        MAX_HISTORY_ITEMS: 50,
        DEFAULT_CURRENCY: "USD",

        // Analysis
        ANALYSIS_TIMEOUT: 60000
    };

    // Remove accidental trailing slash from API URL
    CONFIG.API_BASE_URL = CONFIG.API_BASE_URL.replace(/\/+$/, "");

    // Freeze configuration so other scripts cannot accidentally modify it
    window.CONFIG = Object.freeze(CONFIG);
})();s
