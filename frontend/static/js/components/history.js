/**
 * Analysis History View Component.
 * Populates historical analysis audits, summary badges, action triggers, and empty-state placeholders.
 */

import { firstDefined, isPlainObject } from '../utils/dom.js';
import { normalizeSeverity, applyRiskClass } from '../utils/formatters.js';
import { state } from '../state/store.js';
import { formatDate, formatScore } from '../utils/formatters.js';
import { setText } from '../utils/dom.js';
import { loadHistoryReport, deleteReport } from '../api/history.js';

export function renderHistory(
    history
) {
    const tbody =
        $("#history-tbody");

    if (!tbody) return;

    tbody.replaceChildren();

    const records =
        Array.isArray(history)
            ? history
            : [];

    setText(
        "#history-count",
        String(records.length)
    );

    if (!records.length) {
        const row =
            document.createElement(
                "tr"
            );

        const cell =
            document.createElement(
                "td"
            );

        cell.colSpan = 6;
        cell.className =
            "empty-history";

        cell.textContent =
            "No analyses yet.";

        row.appendChild(
            cell
        );

        tbody.appendChild(
            row
        );

        return;
    }

    records.forEach(
        (record) => {
            const safeRecord =
                isPlainObject(record)
                    ? record
                    : {};

            const id =
                firstDefined(
                    safeRecord.id,
                    safeRecord.analysis_id
                );

            const row =
                document.createElement(
                    "tr"
                );

            row.dataset.reportId =
                String(
                    id ?? ""
                );

            const assetCell =
                createHistoryCell(
                    firstDefined(
                        safeRecord.token_symbol,
                        safeRecord.asset?.symbol,
                        safeRecord.symbol,
                        "—"
                    )
                );

            const riskCell =
                document.createElement(
                    "td"
                );

            const riskValue =
                firstDefined(
                    safeRecord.risk_label,
                    safeRecord.risk_severity,
                    safeRecord.label,
                    safeRecord.severity
                );

            const risk =
                normalizeSeverity(
                    riskValue
                );

            const riskBadge =
                document.createElement(
                    "span"
                );

            riskBadge.className =
                "risk-badge";

            riskBadge.textContent =
                risk;

            applyRiskClass(
                riskBadge,
                risk
            );

            riskCell.appendChild(
                riskBadge
            );

            const outlookCell =
                createHistoryCell(
                    firstDefined(
                        safeRecord.outlook,
                        safeRecord.trend,
                        "—"
                    )
                );

            const score =
                firstDefined(
                    safeRecord.risk_score,
                    safeRecord.composite_score,
                    safeRecord.risk_profile
                        ?.composite_score
                );

            const scoreCell =
                createHistoryCell(
                    score !== null
                        ? `${formatScore(
                            score
                        )}/100`
                        : "—"
                );

            const dateValue =
                firstDefined(
                    safeRecord.created_at,
                    safeRecord.timestamp,
                    safeRecord.generated_at,
                    safeRecord.updated_at
                );

            const dateCell =
                createHistoryCell(
                    dateValue
                        ? formatDate(
                            dateValue
                        )
                        : "—"
                );

            const actionCell =
                document.createElement(
                    "td"
                );

            const viewButton =
                document.createElement(
                    "button"
                );

            viewButton.type =
                "button";

            viewButton.className =
                "history-view";

            viewButton.textContent =
                "View";

            viewButton.dataset.action =
                "view-history";

            viewButton.dataset.id =
                String(id ?? "");

            const deleteButton =
                document.createElement(
                    "button"
                );

            deleteButton.type =
                "button";

            deleteButton.className =
                "history-delete";

            deleteButton.textContent =
                "Delete";

            deleteButton.dataset.action =
                "delete-history";

            deleteButton.dataset.id =
                String(id ?? "");

            actionCell.appendChild(
                viewButton
            );

            actionCell.appendChild(
                deleteButton
            );

            row.appendChild(
                assetCell
            );

            row.appendChild(
                riskCell
            );

            row.appendChild(
                outlookCell
            );

            row.appendChild(
                scoreCell
            );

            row.appendChild(
                dateCell
            );

            row.appendChild(
                actionCell
            );

            tbody.appendChild(
                row
            );
        }
    );
}

export function createHistoryCell(
    value
) {
    const cell =
        document.createElement(
            "td"
        );

    cell.textContent =
        value === null ||
            value === undefined ||
            value === ""
            ? "—"
            : String(value);

    return cell;
}




/* ============================================================
   HISTORY EVENT DELEGATION
   ============================================================ */

export function handleHistoryClick(
    event
) {
    const target =
        event.target.closest(
            "[data-action]"
        );

    if (!target) return;

    const action =
        target.dataset.action;

    const id =
        target.dataset.id;

    if (!id) return;

    event.preventDefault();
    event.stopPropagation();

    if (
        action ===
        "view-history"
    ) {
        loadHistoryReport(id);
        return;
    }

    if (
        action ===
        "delete-history"
    ) {
        deleteReport(id);
    }
}




