import { loadDashboard } from './api/analysis.js';
import { getTokenFromStorage, consumeQueryToken, redirectToHome } from './api/auth.js';
import { clearAnalysisError } from './api/client.js';
import { state } from './state/store.js';


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




