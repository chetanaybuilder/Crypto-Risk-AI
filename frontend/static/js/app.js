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
    const googleLinks = $all('a[href="/api/auth/google"]');
    googleLinks.forEach((link) => {
        link.addEventListener("click", () => {
            clearAnalysisError();
        });
    });
}
