
/* ============================================================
   DOM HELPERS
   ============================================================ */

function $(selector) {
    return document.querySelector(selector);
}

function $all(selector) {
    return Array.from(document.querySelectorAll(selector));
}

export function setText(selector, value, fallback = "—") {
    const element = $(selector);

    if (!element) return;

    let finalValue = value;

    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        finalValue = fallback;
    }

    const strValue = String(finalValue);
    element.textContent = strValue;

    if (strValue === "N/A" || strValue === "—" || strValue === "-") {
        element.style.opacity = "0.5";
    } else {
        element.style.opacity = "1";
    }
}

export function setHTML(selector, html) {
    const element = $(selector);

    if (element) {
        element.innerHTML = html;
    }
}

export function show(element) {
    if (!element) return;

    element.hidden = false;
    element.style.display = "";
}

export function hide(element) {
    if (!element) return;

    element.hidden = true;
    element.style.display = "none";
}

export function toggle(element, visible) {
    if (visible) {
        show(element);
    } else {
        hide(element);
    }
}




/* ============================================================
   SAFE VALUE HELPERS
   ============================================================ */

export function firstDefined(...values) {
    for (const value of values) {
        if (
            value !== undefined &&
            value !== null &&
            value !== ""
        ) {
            return value;
        }
    }

    return null;
}

export function isPlainObject(value) {
    return (
        value !== null &&
        typeof value === "object" &&
        !Array.isArray(value)
    );
}

export function normalizeSymbol(symbol) {
    if (symbol === null || symbol === undefined) {
        return null;
    }

    const normalized = String(symbol)
        .trim()
        .toUpperCase();

    return normalized || null;
}

export function normalizeSource(source) {
    if (
        source === null ||
        source === undefined ||
        source === ""
    ) {
        return "Backend market feed";
    }

    const text = String(source).trim();

    const normalized = text.toLowerCase();

    if (
        normalized.includes("coingecko") ||
        normalized === "coin gecko"
    ) {
        return "CoinGecko";
    }

    if (
        normalized.includes("coinmarketcap") ||
        normalized === "cmc"
    ) {
        return "CoinMarketCap";
    }


    if (normalized.includes("backend")) {
        return "Backend market feed";
    }

    return text;
}




