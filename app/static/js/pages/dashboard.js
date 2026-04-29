function loadDashboard() {
    /* Load dashboard page data. */
    apiGet("/api/alerts" + selectedTeamQuery(), function (alerts) {
        let firing = 0, ack = 0, resolved = 0, reminders = 0;
        const tbody = $("#dashboard-alerts");
        tbody.empty();
        alerts.forEach(function (alert) {
            if (alert.status === "firing") { firing += 1; }
            if (alert.status === "acknowledged") { ack += 1; }
            if (alert.status === "resolved") { resolved += 1; }
            reminders += alert.reminder_count || 0;
        });
        alerts.slice(0, 20).forEach(function (alert) { tbody.append(renderAlertRow(alert, loadDashboard)); });
        $("#metric-firing").text(firing);
        $("#metric-acknowledged").text(ack);
        $("#metric-resolved").text(resolved);
        $("#metric-reminders").text(reminders);
    });
}

function renderAlertRow(alert, reloadCallback) {
    /* Render one compact alert row. */
    const row = $("<tr>");
    row.append($("<td>").text(alert.id));
    row.append($("<td>").text(alert.team_slug || "-"));
    row.append($("<td>").text(alert.severity || "-"));
    row.append($("<td>").text(alert.title));
    row.append($("<td>").text(alert.status).addClass("status-" + alert.status));
    row.append($("<td>").text(alert.assignee || "-"));
    row.append($("<td>").text(alert.first_seen_at || "-"));
    const actions = $("<td>").addClass("actions");
    if (alert.status === "firing") {
        actions.append($("<button>").attr("type", "button").addClass("btn btn-warning btn-small").css('margin-right', '5px').text("Acknowledge").on("click", function () { apiPost("/api/alerts/" + alert.id + "/ack", {}, reloadCallback); }));
    }
    if (alert.status !== "resolved") {
        actions.append($("<button>").attr("type", "button").addClass("btn btn-resolve btn-small").text("Resolve").on("click", function () { apiPost("/api/alerts/" + alert.id + "/resolve", {}, reloadCallback); }));
    }
    row.append(actions);
    return row;
}
$(document).on("click", "#reload-dashboard", loadDashboard);
