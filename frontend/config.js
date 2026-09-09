/* ============================================================
   CryptoRisk AI — Frontend Configuration
   ============================================================
   Central configuration module for the standalone frontend.
   All settings are exposed via window.CONFIG (frozen).

   Usage:
     const apiUrl = window.CONFIG.API_BASE_URL;
     const timeout = window.CONFIG.API_TIMEOUT;

   Note: This file uses an IIFE to avoid polluting global scope.
   ============================================================ */

(() => {
    "use strict";

    const CONFIG = {
        // Backend API base URL (Render deployment)
        API_BASE_URL: "https://crypto-risk-ai-j1ag.onrender.com",

        // API request timeout in milliseconds
        API_TIMEOUT: 30000,

        // Live market data refresh interval (15 seconds)
        LIVE_REFRESH_INTERVAL: 15000,

        // LocalStorage key for JWT auth token
        AUTH_TOKEN_KEY: "cryptorisk_auth_token",

        // Application metadata
        APP_NAME: "CryptoRisk AI",
        APP_VERSION: "1.0.0",

        // Maximum history items to display
        MAX_HISTORY_ITEMS: 50,

        // Default currency for price display
        DEFAULT_CURRENCY: "USD",

        // Analysis request timeout (60 seconds)
        ANALYSIS_TIMEOUT: 60000
    };

    // Remove accidental trailing slash from API URL
    CONFIG.API_BASE_URL = CONFIG.API_BASE_URL.replace(/\/+$/, "");

    // Freeze configuration so other scripts cannot accidentally modify it
    window.CONFIG = Object.freeze(CONFIG);
})();
