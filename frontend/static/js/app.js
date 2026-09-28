/**
 * Application Entrypoint & Lifecycle Controller.
 * Handles auth token bootstrapping and view-level event binding.
 */

import { loadDashboard } from './api/analysis.js';
import { consumeQueryToken, getTokenFromStorage, redirectToHome } from './api/auth.js';
import { clearAnalysisError } from './api/client.js';
import { state } from './state/store.js';
import { $all } from './utils/dom.js';

export async function initializeDashboard() {
    const queryToken = consumeQueryToken();

    const token = queryToken || state.token || getTokenFromStorage();
    state.token = token;

    if (!state.token) {
        redirectToHome();
        return;
    }

    await loadDashboard();
}

export function initializeIndexPage() {
    const params = new URLSearchParams(window.location.search);
    if (params.get("error") === "google_not_configured") {
        alert("Google OAuth is not configured. Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.");
        window.history.replaceState({}, document.title, window.location.pathname);
    }

    const googleLinks = $all('a[href="/api/auth/google"]');
    googleLinks.forEach((link) => {
        link.addEventListener("click", () => {
            clearAnalysisError();
        });
    });
}

// Automatically initialize based on the current page context
if (document.body.classList.contains('dashboard-page')) {
    initializeDashboard();
} else if (document.body.classList.contains('landing-page')) {
    initializeIndexPage();
}

// Delay non-essential animations until after first paint
const enableAnimations = () => {
    document.body.classList.remove('animations-paused');
};

if (window.requestIdleCallback) {
    window.requestIdleCallback(enableAnimations);
} else {
    setTimeout(enableAnimations, 0);
}
