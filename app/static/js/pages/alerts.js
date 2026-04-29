let currentDetailsAlertId = null;

function formatAlertDateTime(value) {
    /*
     * Format alert datetime for table view.
     */

    if (!value) {
        return "-";
    }

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return value;
    }

    return date.toLocaleString();
}

function loadAlerts() {
    /*
     * Load alerts page data.
     */

    const params = [];

    if (selectedTeamId()) {
        params.push("team_id=" + selectedTeamId());
    }

    if ($("#status-filter").val()) {
        params.push("status=" + $("#status-filter").val());
    }

    apiGet("/api/alerts" + (params.length ? "?" + params.join("&") : ""), function (alerts) {
        const tbody = $("#alerts-table");
        tbody.empty();

        alerts = Array.isArray(alerts) ? alerts : [];

        if (!alerts.length) {
            tbody.append(
                $("<tr>").append(
                    $("<td>")
                        .attr("colspan", "8")
                        .addClass("empty-table-cell")
                        .text("No alerts")
                )
            );
            return;
        }

        alerts.forEach(function (alert) {
            tbody.append(renderAlertPageRow(alert));
        });
    });
}

function renderAlertPageRow(alert) {
    /*
     * Render one alert row.
     */

    const row = $("<tr>");

    row.append($("<td>").text(alert.id));
    row.append($("<td>").text(alert.team_slug || "-"));
    row.append($("<td>").text(alert.severity || "-"));
    row.append($("<td>").addClass("alert-title-cell").text(alert.title || "-"));
    row.append($("<td>").text(formatAlertDateTime(alert.first_seen_at || alert.created_at)));
    row.append($("<td>").text(alert.status || "-").addClass("status-" + alert.status));
    row.append($("<td>").text(alert.assignee || "-"));

    const actionsCell = $("<td>").addClass("actions-cell");
    const actions = $("<div>").addClass("table-actions");

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-info btn-small")
            .text("Details")
            .on("click", function () {
                showAlertDetails(alert.id);
            })
    );

    if (alert.status === "firing") {
        actions.append(
            $("<button>")
                .attr("type", "button")
                .addClass("btn btn-warning btn-small")
                .text("Acknowledge")
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

function openAlertDetailsModal() {
    /*
     * Open alert details modal.
     */

    $("#alert-details-modal").attr("style", "display: flex;");
}

function closeAlertDetailsModal() {
    /*
     * Close alert details modal.
     */

    $("#alert-details-modal").attr("style", "display: none;");
    currentDetailsAlertId = null;
}

function showAlertDetails(alertId) {
    /*
     * Load and render full alert details in modal.
     */

    currentDetailsAlertId = alertId;

    apiGet("/api/alerts/" + alertId, function (alert) {
        currentDetailsAlertId = alert.id;

        $("#alert-details-title").text("Alert #" + alert.id + ": " + (alert.title || "-"));
        $("#alert-details-subtitle").text(
            (alert.team_slug || "-")
            + " / "
            + (alert.status || "-")
            + " / "
            + (alert.severity || "-")
        );

        renderAlertDetailsSummary(alert);
        $("#alert-details-labels").text(JSON.stringify(alert.labels || {}, null, 2));
        $("#alert-details-payload").text(JSON.stringify(alert.payload || {}, null, 2));
        renderEvents(alert.events || []);
        renderNotifications(alert.notifications || []);

        if (alert.status === "resolved") {
            $("#modal-alert-ack").attr("style", "display: none;");
            $("#modal-alert-resolve").attr("style", "display: none;");
        } else {
            if (alert.status === "firing") {
                $("#modal-alert-ack").attr("style", "display: inline-block;");
            } else {
                $("#modal-alert-ack").attr("style", "display: none;");
            }

            $("#modal-alert-resolve").attr("style", "display: inline-block;");
        }

        openAlertDetailsModal();
    });
}

function renderAlertDetailsSummary(alert) {
    /*
     * Render alert summary block.
     */

    const summary = $("#alert-details-summary");
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
    summary.append(detailItem("Reminder interval", alert.rotation_reminder_interval_seconds ? alert.rotation_reminder_interval_seconds + "s" : "-"));
}

function detailItem(label, value) {
    /*
     * Render one key/value item.
     */

    return $("<div>").addClass("detail-item")
        .append($("<div>").addClass("detail-label").text(label))
        .append($("<div>").addClass("detail-value").text(value || "-"));
}

function renderEvents(events) {
    /*
     * Render alert events.
     */

    const target = $("#alert-details-events");
    target.empty();

    if (!events.length) {
        target.append($("<div>").addClass("help-text").text("No events."));
        return;
    }

    events.forEach(function (event) {
        target.append(
            $("<div>").addClass("event-item")
                .append($("<strong>").text("#" + event.id + " " + event.event_type))
                .append($("<div>").text(formatAlertDateTime(event.created_at) + " " + (event.message || "")))
        );
    });
}

function renderNotifications(notifications) {
    /*
     * Render notification delivery records.
     */

    const target = $("#alert-details-notifications");
    target.empty();

    if (!notifications.length) {
        target.append($("<div>").addClass("help-text").text("No delivery records."));
        return;
    }

    notifications.forEach(function (item) {
        const channel = item.channel ? item.channel.name + " (" + item.channel.channel_type + ")" : "-";
        const status = item.last_error ? "failed: " + item.last_error : (item.last_event_type || "sent");

        target.append(
            $("<div>").addClass("event-item")
                .append($("<strong>").text("#" + item.id + " " + channel))
                .append($("<div>").text((item.provider || "-") + " / " + status))
                .append($("<div>").text("message_id: " + (item.external_message_id || "-")))
        );
    });
}

$(document).on("click", "#reload-alerts", loadAlerts);
$(document).on("change", "#status-filter", loadAlerts);

$(document).on("click", "#close-alert-details", closeAlertDetailsModal);
$(document).on("click", "#close-alert-details-footer", closeAlertDetailsModal);

$(document).on("click", "#alert-details-modal", function (event) {
    if (event.target && event.target.id === "alert-details-modal") {
        closeAlertDetailsModal();
    }
});

$(document).on("keydown", function (event) {
    if (event.key === "Escape") {
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
