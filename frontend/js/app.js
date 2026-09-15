import { state } from './state/store.js';
import { handleAuthForm, checkQueryToken, loadStoredToken } from './api/auth.js';
import { handleAnalysisSubmit } from './api/analysis.js';
import { refreshHistory } from './api/history.js';
import { setupKeyboardShortcuts, setupVisibilityHandling, initCardTilt } from './components/ui.js';
import { handleHistoryClick } from './components/history.js';

/* ============================================================
   INITIALIZATION
   ============================================================ */

export async function initializeDashboard() {
    consumeQueryToken();

    state.token =
        getTokenFromStorage();

    if (!state.token) {
        redirectToHome();
        return;
    }

    await loadDashboard();
}

export function initializeIndexPage() {
    const googleLinks =
        $all(
            'a[href="/api/auth/google"]'
        );

    googleLinks.forEach(
        (link) => {
            link.addEventListener(
                "click",
                () => {
                    clearAnalysisError();
                }
            );
        }
    );
}




