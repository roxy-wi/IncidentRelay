let currentDetailsAlertId = null;
let alertsCache = [];
let alertsAutoRefreshTimer = null;

let alertsCurrentPage = 1;
let alertsPageSize = 25;

function alertsAsArray(value) {
    /*
     * Return value as array.
     * API errors or empty responses should not break rendering.
     */
    return Array.isArray(value) ? value : [];
}

function normalizeAlertValue(value) {
    /*
     * Convert any value to normalized lowercase string.
     */
    return String(value || "").toLowerCase();
}

function formatAlertDateTime(value) {
    /*
     * Format alert datetime in European date format and 24h time.
     */
    if (!value) {
        return "-";
    }

    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return value;
    }

    return date.toLocaleString("en-GB", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false
    });
}

function alertCreatedValue(alert) {
    /*
     * Return the best available creation timestamp.
     */
    return alert.first_seen_at || alert.created_at || null;
}

function alertActivityValue(alert) {
    /*
     * Return the best available activity timestamp.
     */
    return alert.last_seen_at || alert.updated_at || alert.created_at || alert.first_seen_at || null;
}

function alertTimestamp(value) {
    /*
     * Convert date value to timestamp for sorting.
     */
    if (!value) {
        return 0;
    }

    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return 0;
    }

    return date.getTime();
}

function alertDuration(alert) {
    /*
     * Calculate alert age from created/first_seen_at to now.
     */
    const startedRaw = alertCreatedValue(alert);

    if (!startedRaw) {
        return "-";
    }

    const started = new Date(startedRaw);
    if (Number.isNaN(started.getTime())) {
        return "-";
    }

    let seconds = Math.max(0, Math.floor((Date.now() - started.getTime()) / 1000));

    const days = Math.floor(seconds / 86400);
    seconds -= days * 86400;

    const hours = Math.floor(seconds / 3600);
    seconds -= hours * 3600;

    const minutes = Math.floor(seconds / 60);

    if (days > 0) {
        return days + "d " + hours + "h";
    }

    if (hours > 0) {
        return hours + "h " + minutes + "m";
    }

    return Math.max(minutes, 1) + "m";
}

function severityRank(severity) {
    /*
     * Return severity rank for sorting.
     */
    const value = normalizeAlertValue(severity);

    if (value === "critical") {
        return 4;
    }

    if (value === "high") {
        return 3;
    }

    if (value === "medium") {
        return 2;
    }

    if (value === "low") {
        return 1;
    }

    return 0;
}

function statusRank(status) {
    /*
     * Return status rank for sorting.
     */
    const value = normalizeAlertValue(status);

    if (value === "firing") {
        return 1;
    }

    if (value === "acknowledged") {
        return 2;
    }

    if (value === "silenced") {
        return 3;
    }

    if (value === "resolved") {
        return 4;
    }

    return 9;
}

function severityLabel(severity) {
    const value = normalizeAlertValue(severity);

    if (value === "critical") {
        return "Critical";
    }

    if (value === "high") {
        return "High";
    }

    if (value === "medium") {
        return "Medium";
    }

    if (value === "low") {
        return "Low";
    }

    return severity || "-";
}

function statusLabel(status) {
    const value = normalizeAlertValue(status);

    if (value === "firing") {
        return "Firing";
    }

    if (value === "acknowledged") {
        return "Acknowledged";
    }

    if (value === "resolved") {
        return "Resolved";
    }

    if (value === "silenced") {
        return "Silenced";
    }

    return status || "-";
}

function severityBadgeClass(severity) {
    const value = normalizeAlertValue(severity);

    if (value === "critical") {
        return "alerts-badge-critical";
    }

    if (value === "high") {
        return "alerts-badge-high";
    }

    if (value === "medium") {
        return "alerts-badge-medium";
    }

    if (value === "low") {
        return "alerts-badge-low";
    }

    return "alerts-badge-muted";
}

function statusBadgeClass(status) {
    const value = normalizeAlertValue(status);

    if (value === "firing") {
        return "alerts-badge-firing";
    }

    if (value === "acknowledged") {
        return "alerts-badge-acknowledged";
    }

    if (value === "resolved") {
        return "alerts-badge-resolved";
    }

    if (value === "silenced") {
        return "alerts-badge-silenced";
    }

    return "alerts-badge-muted";
}

function makeAlertBadge(text, cssClass) {
    /*
     * Build a pill badge.
     */
    return $("<span>")
        .addClass("alerts-pill")
        .addClass(cssClass)
        .text(text || "-");
}

function buildAlertsApiUrl() {
    /*
     * Build alerts API URL using existing global team filter and status filter.
     */
    const params = [];

    if (typeof selectedTeamId === "function" && selectedTeamId()) {
        params.push("team_id=" + encodeURIComponent(selectedTeamId()));
    }

    if ($("#status-filter").val()) {
        params.push("status=" + encodeURIComponent($("#status-filter").val()));
    }

    return "/api/alerts" + (params.length ? "?" + params.join("&") : "");
}

function loadAlerts() {
    /*
     * Load alerts page data.
     */
    apiGet(buildAlertsApiUrl(), function (response) {
        alertsCache = alertsAsArray(response);
        renderAlertsPage();
    });
}

function renderAlertsPage() {
    /*
     * Render all alert page widgets from cached API response.
     */
    const filteredAlerts = getFilteredAlerts();
    const pagination = getAlertsPagination(filteredAlerts);

    renderAlertsSummaryGrid("#alerts-alerts-summary", alertsCache);
    renderAlertsInboxCounter(alertsCache, filteredAlerts, pagination);
    renderActiveAlertFilters(filteredAlerts);
    renderAlertsTable(pagination.items);
    renderAlertsPagination(pagination);
}

function getAlertsPagination(alerts) {
    /*
     * Return pagination state and alerts for the current page.
     */
    alerts = Array.isArray(alerts) ? alerts : [];

    const totalItems = alerts.length;
    const totalPages = Math.max(1, Math.ceil(totalItems / alertsPageSize));

    if (alertsCurrentPage > totalPages) {
        alertsCurrentPage = totalPages;
    }

    if (alertsCurrentPage < 1) {
        alertsCurrentPage = 1;
    }

    const startIndex = (alertsCurrentPage - 1) * alertsPageSize;
    const endIndex = startIndex + alertsPageSize;

    return {
        totalItems: totalItems,
        totalPages: totalPages,
        startIndex: startIndex,
        endIndex: Math.min(endIndex, totalItems),
        items: alerts.slice(startIndex, endIndex)
    };
}


function renderAlertsInboxCounter(allAlerts, filteredAlerts, pagination) {
    /*
     * Render "Showing X-Y of Z alerts / N total" counter.
     */
    allAlerts = Array.isArray(allAlerts) ? allAlerts : [];
    filteredAlerts = Array.isArray(filteredAlerts) ? filteredAlerts : [];

    const from = pagination.totalItems ? pagination.startIndex + 1 : 0;
    const to = pagination.totalItems ? pagination.endIndex : 0;

    $("#alerts-page-from").text(from);
    $("#alerts-page-to").text(to);
    $("#alerts-filtered-count").text(filteredAlerts.length);
    $("#alerts-total-count").text(allAlerts.length);

    $("#alerts-total-wrapper").toggle(allAlerts.length !== filteredAlerts.length);
}


function renderAlertsPagination(pagination) {
    /*
     * Render pagination controls state.
     */
    $("#alerts-current-page").text(alertsCurrentPage);
    $("#alerts-total-pages").text(pagination.totalPages);

    $("#alerts-prev-page").prop("disabled", alertsCurrentPage <= 1);
    $("#alerts-next-page").prop("disabled", alertsCurrentPage >= pagination.totalPages);

    $("#alerts-page-size").val(String(alertsPageSize));

    $(".alerts-pagination").toggle(pagination.totalItems > 0);
}


function resetAlertsPagination() {
    /*
     * Reset pagination to the first page after filters/search/API reload.
     */
    alertsCurrentPage = 1;
}

function getFilteredAlerts() {
    /*
     * Apply client-side search, severity filter and sorting.
     * Status is already passed to backend, but also checked here for safety.
     */
    const search = normalizeAlertValue($("#alerts-search").val());
    const statusFilter = normalizeAlertValue($("#status-filter").val());
    const severityFilter = normalizeAlertValue($("#severity-filter").val());
    const sortMode = $("#alerts-sort").val() || "activity_desc";

    let result = alertsCache.filter(function (alert) {
        const status = normalizeAlertValue(alert.status);
        const severity = normalizeAlertValue(alert.severity);

        if (statusFilter && status !== statusFilter) {
            return false;
        }

        if (severityFilter && severity !== severityFilter) {
            return false;
        }

        if (!search) {
            return true;
        }

        const haystack = [
            alert.id,
            alert.title,
            alert.team_slug,
            alert.severity,
            alert.status,
            alert.assignee,
            alert.source,
            alert.external_id,
            alert.route_name,
            alert.rotation_name,
            alert.group_key,
            alert.dedup_key
        ].map(normalizeAlertValue).join(" ");

        return haystack.indexOf(search) !== -1;
    });

    result = result.slice().sort(function (left, right) {
        if (sortMode === "created_asc") {
            return alertTimestamp(alertCreatedValue(left)) - alertTimestamp(alertCreatedValue(right));
        }

        if (sortMode === "created_desc") {
            return alertTimestamp(alertCreatedValue(right)) - alertTimestamp(alertCreatedValue(left));
        }

        if (sortMode === "severity_desc") {
            return severityRank(right.severity) - severityRank(left.severity);
        }

        if (sortMode === "status_asc") {
            return statusRank(left.status) - statusRank(right.status);
        }

        return alertTimestamp(alertActivityValue(right)) - alertTimestamp(alertActivityValue(left));
    });

    return result;
}

function renderActiveAlertFilters(filteredAlerts) {
    /*
     * Render active filter chips.
     */
    const target = $("#alerts-active-filters");
    target.empty();

    const chips = [];

    if ($("#status-filter").val()) {
        chips.push("Status: " + statusLabel($("#status-filter").val()));
    }

    if ($("#severity-filter").val()) {
        chips.push("Severity: " + severityLabel($("#severity-filter").val()));
    }

    if ($("#alerts-search").val()) {
        chips.push("Search: " + $("#alerts-search").val());
    }

    chips.push("Result: " + filteredAlerts.length);

    chips.forEach(function (chip) {
        target.append($("<span>").addClass("alerts-filter-chip").text(chip));
    });
}

function renderAlertsTable(alerts) {
    /*
     * Render alert inbox table.
     */
    const tbody = $("#alerts-table");
    tbody.empty();

    if (!alerts.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>")
                    .attr("colspan", "10")
                    .addClass("empty-table-cell")
                    .text("No alerts found")
            )
        );
        return;
    }

    alerts.forEach(function (alert) {
        tbody.append(renderAlertPageRow(alert));
    });
}

function renderAlertPageRow(alert) {
    /*
     * Render one alert row.
     */
    const row = $("<tr>").addClass("alerts-row alerts-row-" + normalizeAlertValue(alert.status));

    row.append(
        $("<td>").append(
            $("<div>")
                .addClass("alerts-status-cell")
                .append($("<span>").addClass("alerts-status-dot alerts-dot-" + normalizeAlertValue(alert.status)))
                .append(makeAlertBadge(statusLabel(alert.status), statusBadgeClass(alert.status)))
        )
    );

    row.append(
        $("<td>").append(
            $("<button>")
                .attr("type", "button")
                .attr("title", "View alert details")
                .addClass("alerts-id-link")
                .text("#" + alert.id)
                .on("click", function () {
                    showAlertDetails(alert.id);
                })
        )
    );

    row.append(
        $("<td>")
            .addClass("alert-title-cell")
            .append($("<div>").addClass("alerts-title").text(alert.title || "-"))
            .append(
                $("<div>")
                    .addClass("alerts-subtitle")
                    .text(buildAlertSubtitle(alert))
            )
            .append(
                $("<div>")
                    .addClass("alerts-age")
                    .text("Age: " + alertDuration(alert))
            )
    );

    row.append(
        $("<td>").append(
            makeAlertBadge(severityLabel(alert.severity), severityBadgeClass(alert.severity))
        )
    );

    row.append(
        $("<td>")
            .append($("<div>").addClass("alerts-team").text(alert.team_slug || "-"))
            .append($("<div>").addClass("alerts-subtitle").text(alert.route_name || "No route"))
    );

    row.append($("<td>").text(alert.assignee || "-"));
    row.append($("<td>").text(formatAlertDateTime(alertCreatedValue(alert))));
    row.append($("<td>").text(formatAlertDateTime(alert.last_seen_at)));
    row.append($("<td>").append(renderReminderCount(alert)));

    const actionsCell = $("<td>").addClass("actions-cell");
    const actions = $("<div>").addClass("table-actions");

    if (alert.status === "firing") {
        actions.append(
            $("<button>")
                .attr("type", "button")
                .addClass("btn btn-warning btn-small")
                .text("Ack")
                .on("click", function () {
                    apiPost("/api/alerts/" + alert.id + "/ack", {}, loadAlerts);
                })
        );
    }

    if (alert.status !== "resolved") {
        actions.append(
            $("<button>")
                .attr("type", "button")
                .addClass("btn btn-resolve btn-small")
                .text("Resolve")
                .on("click", function () {
                    apiPost("/api/alerts/" + alert.id + "/resolve", {}, loadAlerts);
                })
        );
    }

    actionsCell.append(actions);
    row.append(actionsCell);

    return row;
}

function buildAlertSubtitle(alert) {
    /*
     * Build secondary text for alert row.
     */
    const parts = [];

    if (alert.source) {
        parts.push(alert.source);
    }

    if (alert.external_id) {
        parts.push(alert.external_id);
    }

    if (alert.group_key) {
        parts.push(alert.group_key);
    }

    return parts.length ? parts.join(" · ") : "Routed alert";
}

function renderReminderCount(alert) {
    /*
     * Render reminder counter badge.
     */
    const count = alert.reminder_count || 0;

    return $("<span>")
        .addClass("alerts-reminder-badge")
        .toggleClass("is-active", count > 0)
        .text(count);
}

function showAlertDetails(alertId) {
    /*
     * Load and render full alert details in modal.
     */
    currentDetailsAlertId = alertId;

    apiGet("/api/alerts/" + alertId, function (alert) {
        const modal = alertDetailsModal();

        if (!modal.length) {
            console.error("Alert details modal not found");
            return;
        }

        currentDetailsAlertId = alert.id;

        modal.find("#alert-details-title").text(
            "Alert #" + alert.id + ": " + (alert.title || "-")
        );

        modal.find("#alert-details-subtitle").text(
            (alert.team_slug || "-") + " / " + (alert.status || "-") + " / " + (alert.severity || "-")
        );

        renderAlertDetailsSummary(alert, modal);

        modal.find("#alert-details-labels").text(JSON.stringify(alert.labels || {}, null, 2));
        modal.find("#alert-details-payload").text(JSON.stringify(alert.payload || {}, null, 2));

        renderEvents(alert.events || [], modal);
        renderNotifications(alert.notifications || [], modal);

        if (alert.status === "resolved") {
            modal.find("#modal-alert-ack").hide();
            modal.find("#modal-alert-resolve").hide();
        } else {
            if (alert.status === "firing") {
                modal.find("#modal-alert-ack").show();
            } else {
                modal.find("#modal-alert-ack").hide();
            }

            modal.find("#modal-alert-resolve").show();
        }

        openAlertDetailsModal();
    });
}

function renderAlertDetailsSummary(alert, modal) {
    /*
     * Render alert summary block.
     */
    const summary = modal.find("#alert-details-summary");
    summary.empty();

    summary.append(detailItem("Source", alert.source));
    summary.append(detailItem("External ID", alert.external_id));
    summary.append(detailItem("Route", alert.route_name));
    summary.append(detailItem("Rotation", alert.rotation_name));
    summary.append(detailItem("Assignee", alert.assignee));
    summary.append(detailItem("Acknowledged by", alert.acknowledged_by));
    summary.append(detailItem("Created", formatAlertDateTime(alert.first_seen_at || alert.created_at)));
    summary.append(detailItem("Last seen", formatAlertDateTime(alert.last_seen_at)));
    summary.append(detailItem("Last notification", formatAlertDateTime(alert.last_notification_at)));
    summary.append(detailItem("Group key", alert.group_key));
    summary.append(detailItem("Dedup key", alert.dedup_key));
    summary.append(detailItem("Reminder count", alert.reminder_count || 0));
    summary.append(detailItem(
        "Reminder interval",
        alert.rotation_reminder_interval_seconds ? alert.rotation_reminder_interval_seconds + "s" : "-"
    ));
}


function renderEvents(events, modal) {
    /*
     * Render alert events.
     */
    const target = modal.find("#alert-details-events");
    target.empty();

    if (!events.length) {
        target.append($("<div>").addClass("help-text").text("No events."));
        return;
    }

    events.forEach(function (event) {
        target.append(
            $("<div>")
                .addClass("event-item")
                .append($("<strong>").text("#" + event.id + " " + event.event_type))
                .append(
                    $("<div>").text(
                        formatAlertDateTime(event.created_at) + " " + (event.message || "")
                    )
                )
        );
    });
}


function renderNotifications(notifications, modal) {
    /*
     * Render notification delivery records.
     */
    const target = modal.find("#alert-details-notifications");
    target.empty();

    if (!notifications.length) {
        target.append($("<div>").addClass("help-text").text("No delivery records."));
        return;
    }

    notifications.forEach(function (item) {
        const channel = item.channel
            ? item.channel.name + " (" + item.channel.channel_type + ")"
            : "-";

        const status = item.last_error
            ? "failed: " + item.last_error
            : (item.last_event_type || "sent");

        target.append(
            $("<div>")
                .addClass("event-item")
                .append($("<strong>").text("#" + item.id + " " + channel))
                .append($("<div>").text((item.provider || "-") + " / " + status))
                .append($("<div>").text("message_id: " + (item.external_message_id || "-")))
        );
    });
}

function detailItem(label, value) {
    /*
     * Render one key/value item.
     */
    return $("<div>")
        .addClass("detail-item")
        .append($("<div>").addClass("detail-label").text(label))
        .append($("<div>").addClass("detail-value").text(value || "-"));
}

function setAlertsAutoRefresh(enabled) {
    /*
     * Enable or disable alerts auto-refresh.
     */
    if (alertsAutoRefreshTimer) {
        clearInterval(alertsAutoRefreshTimer);
        alertsAutoRefreshTimer = null;
    }

    if (enabled) {
        alertsAutoRefreshTimer = setInterval(loadAlerts, 30000);
    }
}

$(document).on("click", "#reload-alerts", function () {
    resetAlertsPagination();
    loadAlerts();
});

$(document).on("change", "#status-filter", function () {
    resetAlertsPagination();
    loadAlerts();
});

$(document).on("change", "#severity-filter, #alerts-sort", function () {
    resetAlertsPagination();
    renderAlertsPage();
});

$(document).on("input", "#alerts-search", function () {
    resetAlertsPagination();
    renderAlertsPage();
});

$(document).on("change", "#alerts-page-size", function () {
    alertsPageSize = Number($(this).val() || 25);
    resetAlertsPagination();
    renderAlertsPage();
});

$(document).on("click", "#alerts-prev-page", function () {
    alertsCurrentPage -= 1;
    renderAlertsPage();
});

$(document).on("click", "#alerts-next-page", function () {
    alertsCurrentPage += 1;
    renderAlertsPage();
});

$(document).on("change", "#alerts-auto-refresh", function () {
    setAlertsAutoRefresh($(this).is(":checked"));
});

$(document).on("click", "#close-alert-details", closeAlertDetailsModal);
$(document).on("click", "#close-alert-details-footer", closeAlertDetailsModal);

$(document).on("click", "#alert-details-modal", function (event) {
    if (event.target === this) {
        closeAlertDetailsModal();
    }
});

$(document).on("keydown", function (event) {
    if (event.key === "Escape" && alertDetailsModal().hasClass("is-open")) {
        closeAlertDetailsModal();
    }
});

$(document).on("click", "#modal-alert-ack", function () {
    if (!currentDetailsAlertId) {
        return;
    }

    apiPost("/api/alerts/" + currentDetailsAlertId + "/ack", {}, function () {
        showAlertDetails(currentDetailsAlertId);
        loadAlerts();
    });
});

$(document).on("click", "#modal-alert-resolve", function () {
    if (!currentDetailsAlertId) {
        return;
    }

    apiPost("/api/alerts/" + currentDetailsAlertId + "/resolve", {}, function () {
        showAlertDetails(currentDetailsAlertId);
        loadAlerts();
    });
});
function alertDetailsModal() {
    /*
     * Return the single global alert details modal.
     * The modal must be included only once in index.html.
     */
    return $("#alert-details-modal");
}


function openAlertDetailsModal() {
    /*
     * Open alert details modal.
     */
    const modal = alertDetailsModal();

    if (!modal.length) {
        console.error("Alert details modal not found");
        return;
    }

    modal.css("display", "flex").addClass("is-open");
    $("body").addClass("modal-open");
}


function closeAlertDetailsModal() {
    /*
     * Close alert details modal.
     */
    alertDetailsModal()
        .css("display", "none")
        .removeClass("is-open");

    $("body").removeClass("modal-open");
    currentDetailsAlertId = null;
}
