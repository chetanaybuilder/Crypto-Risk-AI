import { runAnalysis } from './analysis.js';
import { showAnalysisError, friendlyErrorMessage } from './client.js';
import { firstDefined } from '../utils/dom.js';
import { state } from '../state/store.js';
import { apiRequest, API } from './client.js';
import { show, hide, setText } from '../utils/dom.js';
import { clearReportView } from '../components/ui.js';
import { stopLivePolling } from './market.js';
import { stopJobPolling } from './analysis.js';
import { refreshHistory } from './history.js';

/* ============================================================
   STORAGE
   ============================================================ */

export const STORAGE_KEYS = {
    token: "token"
};




/* ============================================================
   AUTH
   ============================================================ */

export function getTokenFromStorage() {
    try {
        return localStorage.getItem(STORAGE_KEYS.token);
    } catch (error) {
        console.warn("Unable to read auth token:", error);
        return null;
    }
}

export function saveToken(token) {
    if (!token) return;

    state.token = token;

    try {
        localStorage.setItem(
            STORAGE_KEYS.token,
            token
        );
    } catch (error) {
        console.warn("Unable to save auth token:", error);
    }
}

export function clearToken() {
    state.token = null;

    try {
        localStorage.removeItem(STORAGE_KEYS.token);
    } catch (error) {
        console.warn("Unable to clear auth token:", error);
    }
}

export function consumeQueryToken() {
    const params = new URLSearchParams(
        window.location.search
    );

    const token = params.get("token");

    if (!token) {
        return null;
    }

    saveToken(token);

    const cleanUrl =
        window.location.pathname +
        window.location.hash;

    window.history.replaceState(
        {},
        document.title,
        cleanUrl
    );

    return token;
}

export function getAuthHeaders() {
    const token =
        state.token ||
        getTokenFromStorage();

    if (!token) {
        return {};
    }

    if (!state.token) {
        state.token = token;
    }

    return {
        Authorization: `Bearer ${token}`
    };
}

export function redirectToHome() {
    clearToken();
    stopLivePolling();
    stopJobPolling();

    // FIX: redirect to the public Vercel frontend (consistent with
    // logout()). Using "/" would land on the Flask backend index.html,
    // not the public landing page.
    window.location.href = "https://crypto-risk-ai.vercel.app/";
}




/* ============================================================
   LOGOUT
   ============================================================ */

export async function logout() {
    try {
        if (state.token) {
            await apiRequest(
                API.logout,
                {
                    method: "POST"
                }
            );
        }
    } catch (error) {
        console.warn(
            "Logout request failed:",
            error
        );
    } finally {
        clearToken();
        stopLivePolling();
        stopJobPolling();

        window.location.href = "https://crypto-risk-ai.vercel.app/";
    }
}




/* ============================================================
   FORM HANDLER
   ============================================================ */

export async function handleAnalysisSubmit(
    event
) {
    event.preventDefault();

    const input =
        $("#token-symbol");

    if (!input) return;

    const symbol =
        input.value
            .trim()
            .toUpperCase();

    if (!symbol) {
        showAnalysisError(
            "Enter a token symbol."
        );

        input.focus();
        return;
    }

    if (
        !/^[A-Z0-9]{2,15}$/.test(
            symbol
        )
    ) {
        showAnalysisError(
            "Enter a valid token symbol."
        );

        input.focus();
        return;
    }

    // FIX (Bug 2): optional contract security inputs. The backend
    // runs the GoPlus structural check only when BOTH chain_id and
    // contract_address are provided; leaving them blank is fine and
    // is reported as "not applicable" (not a missing signal).
    const chainIdInput =
        $("#chain-id");

    const contractAddressInput =
        $("#contract-address");

    const chainIdValue = chainIdInput
        ? String(chainIdInput.value || "").trim()
        : "";

    const contractAddressValue = contractAddressInput
        ? String(contractAddressInput.value || "").trim()
        : "";

    if (
        contractAddressValue &&
        !/^0x[a-fA-F0-9]{40}$/.test(
            contractAddressValue
        )
    ) {
        showAnalysisError(
            "Enter a valid contract address (0x followed by 40 hex characters) or leave it blank."
        );

        if (contractAddressInput) {
            contractAddressInput.focus();
        }

        return;
    }

    if (
        contractAddressValue &&
        !chainIdValue
    ) {
        showAnalysisError(
            "Select a chain for the contract security check, or leave the address blank."
        );

        if (chainIdInput) {
            chainIdInput.focus();
        }

        return;
    }

    const button =
        $("#analyze-button");

    if (button) {
        button.disabled = true;

        button.dataset.originalText =
            button.textContent;

        button.textContent =
            "Analyzing…";
    }

    try {
        await runAnalysis(
            symbol,
            {
                chainId: chainIdValue,
                contractAddress: contractAddressValue
            }
        );
    } finally {
        if (button) {
            button.disabled = false;

            button.textContent =
                button.dataset.originalText ||
                "Analyze";
        }
    }
}




/* ============================================================
   LOGIN / SIGNUP
   ============================================================ */

export async function handleAuthForm(
    event
) {
    const form =
        event.currentTarget;

    event.preventDefault();

    const action =
        form.dataset.auth;

    if (
        action !== "login" &&
        action !== "signup"
    ) {
        return;
    }

    const email =
        form.querySelector(
            "[name='email']"
        )?.value?.trim();

    const password =
        form.querySelector(
            "[name='password']"
        )?.value;

    const username =
        form.querySelector(
            "[name='username']"
        )?.value?.trim();

    if (!email || !password) {
        showAnalysisError(
            "Email and password are required."
        );

        return;
    }

    if (
        action === "signup" &&
        !username
    ) {
        showAnalysisError(
            "Username is required."
        );

        return;
    }

    const endpoint =
        action === "signup"
            ? "/api/auth/signup"
            : "/api/auth/login";

    const body =
        action === "signup"
            ? {
                name: username,
                email,
                password
            }
            : {
                email,
                password
            };

    try {
        const payload =
            await apiRequest(
                endpoint,
                {
                    method: "POST",
                    body
                }
            );

        const token =
            firstDefined(
                payload.token,
                payload.access_token,
                payload.data?.token,
                payload.data?.access_token
            );

        if (!token) {
            throw new Error(
                "Authentication succeeded but no session token was returned."
            );
        }

        saveToken(
            token
        );

        window.location.href =
            "/dashboard";
    } catch (error) {
        // FIX (Bug 6): friendly message instead of raw error string.
        showAnalysisError(
            friendlyErrorMessage(error) ||
            "Authentication failed."
        );
    }
}




