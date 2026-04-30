function normalizeSummaryStatus(status) {
    /*
     * Normalize alert status for summary counters.
     */
    return String(status || "").toLowerCase();
}


function renderAlertsSummaryGrid(containerSelector, alerts) {
    /*
     * Render reusable alert summary cards.
     *
     * The same function is used by Overview and Alerts pages.
     * It updates only values inside the passed container, so multiple grids
     * can safely exist in DOM at the same time.
     */
    const container = $(containerSelector);

    if (!container.length) {
        return;
    }

    alerts = Array.isArray(alerts) ? alerts : [];

    const counters = {
        firing: 0,
        acknowledged: 0,
        resolved: 0,
        reminders: 0,
        total: alerts.length
    };

    alerts.forEach(function (alert) {
        const status = normalizeSummaryStatus(alert.status);

        if (status === "firing") {
            counters.firing += 1;
        }

        if (status === "acknowledged") {
            counters.acknowledged += 1;
        }

        if (status === "resolved") {
            counters.resolved += 1;
        }

        counters.reminders += Number(alert.reminder_count || 0);
    });

    container.find('[data-summary-value="firing"]').text(counters.firing);
    container.find('[data-summary-value="acknowledged"]').text(counters.acknowledged);
    container.find('[data-summary-value="resolved"]').text(counters.resolved);
    container.find('[data-summary-value="reminders"]').text(counters.reminders);
    container.find('[data-summary-value="total"]').text(counters.total);
}
