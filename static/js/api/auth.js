/**
 * Authentication and Session Management Service.
 * Coordinates JWT token storage, authorization headers, OAuth query param ingestion, and logout teardown.
 */

import { runAnalysis } from './analysis.js';
import { showAnalysisError, friendlyErrorMessage } from './client.js';
import { firstDefined } from '../utils/dom.js';
import { state } from '../state/store.js';
import { apiRequest, API } from './client.js';
import { show, hide, setText, $, $all } from '../utils/dom.js';
import { clearReportView } from '../components/ui.js';
import { stopLivePolling } from './market.js';
import { stopJobPolling } from './analysis.js';
import { refreshHistory } from './history.js';

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

    // Redirect to the Flask index page instead of the old Vercel frontend.
    window.location.href = "/";
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

        window.location.href = "/";
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

    // Optional contract security / network inputs. Supports single
    // cohesive input: 0x contract address, network name, or combined.
    const chainIdInput =
        $("#chain-id");

    const contractAddressInput =
        $("#contract-address");

    const rawContractOrNetwork = contractAddressInput
        ? String(contractAddressInput.value || "").trim()
        : "";

    let chainIdValue = chainIdInput
        ? String(chainIdInput.value || "").trim()
        : "";

    let contractAddressValue = "";

    if (rawContractOrNetwork) {
        const combinedMatch =
            rawContractOrNetwork.match(/^([a-zA-Z0-9_\-]+)[:\s]+(0x[a-fA-F0-9]{40})$/i) ||
            rawContractOrNetwork.match(/^(0x[a-fA-F0-9]{40})[\s\(\[]+([a-zA-Z0-9_\-]+)[\)\]]*$/i);

        if (combinedMatch) {
            if (combinedMatch[1].startsWith("0x")) {
                contractAddressValue = combinedMatch[1];
                chainIdValue = combinedMatch[2].toLowerCase();
            } else {
                chainIdValue = combinedMatch[1].toLowerCase();
                contractAddressValue = combinedMatch[2];
            }
        } else if (/^0x[a-fA-F0-9]{40}$/i.test(rawContractOrNetwork)) {
            contractAddressValue = rawContractOrNetwork;
            if (!chainIdValue) {
                chainIdValue = "eth";
            }
        } else {
            const knownChains = [
                "eth", "ethereum", "bsc", "bnb",
                "polygon", "arbitrum", "optimism",
                "base", "avalanche", "avax"
            ];
            const lower = rawContractOrNetwork.toLowerCase();

            if (knownChains.includes(lower)) {
                chainIdValue = lower;
                contractAddressValue = "";
            } else {
                showAnalysisError(
                    "Enter a valid contract address (0x...) or network, or leave it blank."
                );

                if (contractAddressInput) {
                    contractAddressInput.focus();
                }

                return;
            }
        }
    } else {
        chainIdValue = "";
        contractAddressValue = "";
    }

    if (chainIdInput) {
        chainIdInput.value = chainIdValue;
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
        showAnalysisError(
            friendlyErrorMessage(error) ||
            "Authentication failed."
        );
    }
}




