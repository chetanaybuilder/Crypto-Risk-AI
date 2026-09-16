import { firstDefined } from './dom.js';

/* ============================================================
   FORMATTERS
   ============================================================ */

export function formatNumber(
    value,
    decimals = 2
) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "—";
    }

    const number = Number(value);

    if (!Number.isFinite(number)) {
        return "—";
    }

    return number.toLocaleString(
        undefined,
        {
            maximumFractionDigits:
                decimals
        }
    );
}

export function formatUsd(value) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "—";
    }

    const number = Number(value);

    if (!Number.isFinite(number)) {
        return "—";
    }

    if (
        Math.abs(number) >=
        1_000_000_000
    ) {
        return `$${formatNumber(
            number / 1_000_000_000,
            2
        )}B`;
    }

    if (
        Math.abs(number) >=
        1_000_000
    ) {
        return `$${formatNumber(
            number / 1_000_000,
            2
        )}M`;
    }

    if (
        Math.abs(number) >=
        1_000
    ) {
        return `$${formatNumber(
            number / 1_000,
            2
        )}K`;
    }

    if (
        Math.abs(number) >= 1
    ) {
        return `$${formatNumber(
            number,
            2
        )}`;
    }

    return `$${number.toFixed(6)}`;
}

export function formatPercent(value) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "—";
    }

    const number = Number(value);

    if (!Number.isFinite(number)) {
        return "—";
    }

    const sign =
        number > 0 ? "+" : "";

    return `${sign}${number.toFixed(
        2
    )}%`;
}

export function formatScore(value) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "—";
    }

    const number = Number(value);

    if (!Number.isFinite(number)) {
        return "—";
    }

    return Math.round(number);
}

export function formatConfidence(value) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "—";
    }

    const number = Number(value);

    if (!Number.isFinite(number)) {
        return "—";
    }

    /*
     * Supports both:
     * 0.82  -> 82.0%
     * 82    -> 82.0%
     */
    const normalized =
        number >= 0 &&
            number <= 1
            ? number * 100
            : number;

    return `${normalized.toFixed(
        1
    )}%`;
}

export function formatDate(value) {
    if (!value) return "—";

    const date =
        new Date(value);

    if (
        Number.isNaN(
            date.getTime()
        )
    ) {
        return String(value);
    }

    return date.toLocaleString(
        undefined,
        {
            dateStyle: "medium",
            timeStyle: "short"
        }
    );
}

export function formatRelativeTime(value) {
    if (!value) return "—";

    const date =
        new Date(value);

    if (
        Number.isNaN(
            date.getTime()
        )
    ) {
        return formatDate(value);
    }

    const seconds = Math.floor(
        (Date.now() -
            date.getTime()) /
        1000
    );

    if (seconds < 10) {
        return "just now";
    }

    if (seconds < 60) {
        return `${seconds}s ago`;
    }

    const minutes =
        Math.floor(
            seconds / 60
        );

    if (minutes < 60) {
        return `${minutes}m ago`;
    }

    const hours =
        Math.floor(
            minutes / 60
        );

    if (hours < 24) {
        return `${hours}h ago`;
    }

    return `${Math.floor(
        hours / 24
    )}d ago`;
}

export function clampScore(value) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return null;
    }

    const number = Number(value);

    if (!Number.isFinite(number)) {
        return null;
    }

    return Math.max(
        0,
        Math.min(100, number)
    );
}




/* ============================================================
   RISK SEVERITY
   ============================================================ */

export function normalizeSeverity(value) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "Unavailable";
    }

    const text =
        String(value)
            .trim()
            .toLowerCase();

    if (
        text.includes("critical")
    ) {
        return "Critical";
    }

    if (
        text.includes("high") ||
        text.includes("elevated")
    ) {
        return "High";
    }

    if (
        text.includes("moderate") ||
        text.includes("medium")
    ) {
        return "Moderate";
    }

    if (
        text.includes("low") ||
        text.includes("minimal")
    ) {
        return "Low";
    }

    if (
        text.includes("unavailable")
    ) {
        return "Unavailable";
    }

    return String(value);
}

export function severityClass(
    severity
) {
    const normalized =
        normalizeSeverity(
            severity
        ).toLowerCase();

    if (
        normalized ===
        "critical"
    ) {
        return "risk-critical";
    }

    if (
        normalized === "high"
    ) {
        return "risk-high";
    }

    if (
        normalized === "moderate"
    ) {
        return "risk-moderate";
    }

    if (
        normalized === "low"
    ) {
        return "risk-low";
    }

    return "";
}

export function applyRiskClass(
    element,
    severity
) {
    if (!element) return;

    element.classList.remove(
        "risk-low",
        "risk-moderate",
        "risk-high",
        "risk-critical"
    );

    const className =
        severityClass(
            severity
        );

    if (className) {
        element.classList.add(
            className
        );
    }
}




