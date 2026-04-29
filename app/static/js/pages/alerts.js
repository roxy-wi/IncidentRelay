function loadAlerts() {
    /* Load alerts page data. */
    const params = [];
    if (selectedTeamId()) { params.push("team_id=" + selectedTeamId()); }
    if ($("#status-filter").val()) { params.push("status=" + $("#status-filter").val()); }
    apiGet("/api/alerts" + (params.length ? "?" + params.join("&") : ""), function (alerts) {
        const tbody = $("#alerts-table");
        tbody.empty();
        alerts.forEach(function (alert) { tbody.append(renderDetailedAlertRow(alert)); });
    });
}

function renderDetailedAlertRow(alert) {
    /* Render one detailed alert row. */
    const row = $("<tr>");
    row.append($("<td>").text(alert.id));
    row.append($("<td>").text(alert.team_slug || "-"));
    row.append($("<td>").text(alert.source || "-"));
    row.append($("<td>").text(alert.severity || "-"));
    row.append($("<td>").text(alert.title));
    row.append($("<td>").text(alert.status).addClass("status-" + alert.status));
    row.append($("<td>").text(alert.route_name || "-"));
    row.append($("<td>").text(alert.rotation_name || "-"));
    row.append($("<td>").text(alert.assignee || "-"));
    row.append($("<td>").text(alert.last_seen_at || "-"));
    row.append($("<td>").text(alert.reminder_count || 0));
    row.append($("<td>").text(alert.escalation_level || 0));

    const actions = $("<td>").addClass("actions");
    actions.append($("<button>").addClass("btn btn-info btn-small").text("Details").on("click", function () { showAlertDetails(alert.id); }));

    if (alert.status === "firing") {
        actions.append($("<button>").attr("type", "button").addClass("btn btn-warning btn-small").text("Acknowledge").on("click", function () { apiPost("/api/alerts/" + alert.id + "/ack", {}, loadAlerts); }));
    }
    if (alert.status !== "resolved") {
        actions.append($("<button>").attr("type", "button").addClass("btn btn-resolve btn-small").text("Resolve").on("click", function () { apiPost("/api/alerts/" + alert.id + "/resolve", {}, loadAlerts); }));
    }

    row.append(actions);
    return row;
}

function showAlertDetails(alertId) {
    /* Load and render full alert details. */
    apiGet("/api/alerts/" + alertId, function (alert) {
        $("#alert-details-card").show();
        $("#alert-details-title").text("Alert #" + alert.id + ": " + alert.title);
        $("#alert-details-subtitle").text((alert.team_slug || "-") + " / " + (alert.status || "-") + " / " + (alert.severity || "-"));

        const summary = $("#alert-details-summary");
        summary.empty();
        summary.append(detailItem("Source", alert.source));
        summary.append(detailItem("External ID", alert.external_id));
        summary.append(detailItem("Route", alert.route_name));
        summary.append(detailItem("Rotation", alert.rotation_name));
        summary.append(detailItem("Assignee", alert.assignee));
        summary.append(detailItem("Acknowledged by", alert.acknowledged_by));
        summary.append(detailItem("First seen", alert.first_seen_at));
        summary.append(detailItem("Last seen", alert.last_seen_at));
        summary.append(detailItem("Last notification", alert.last_notification_at));
        summary.append(detailItem("Group key", alert.group_key));
        summary.append(detailItem("Dedup key", alert.dedup_key));
        summary.append(detailItem("Reminder interval", alert.rotation_reminder_interval_seconds ? alert.rotation_reminder_interval_seconds + "s" : "-"));

        $("#alert-details-labels").text(JSON.stringify(alert.labels || {}, null, 2));
        $("#alert-details-payload").text(JSON.stringify(alert.payload || {}, null, 2));
        renderEvents(alert.events || []);
        renderNotifications(alert.notifications || []);
    });
}

function detailItem(label, value) {
    /* Render one key/value item. */
    return $("<div>").addClass("detail-item")
        .append($("<div>").addClass("detail-label").text(label))
        .append($("<div>").addClass("detail-value").text(value || "-"));
}

function renderEvents(events) {
    /* Render alert events. */
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
                .append($("<div>").text(event.created_at + " " + (event.message || "")))
        );
    });
}

function renderNotifications(notifications) {
    /* Render notification delivery records. */
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
                .append($("<div>").text(item.provider + " / " + status))
                .append($("<div>").text("message_id: " + (item.external_message_id || "-")))
        );
    });
}

$(document).on("click", "#reload-alerts", loadAlerts);
$(document).on("change", "#status-filter", loadAlerts);
$(document).on("click", "#close-alert-details", function () { $("#alert-details-card").hide(); });
