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

$(document).on("click", "#reload-dashboard", loadDashboard);
