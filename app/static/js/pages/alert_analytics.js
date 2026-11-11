let alertAnalyticsChart = null;
let alertAnalyticsLoaded = false;
let alertAnalyticsLoadGeneration = 0;
let alertAnalyticsSelection = null;
let alertAnalyticsSelectionGeneration = 0;
const ALERTS_PAGE_TAB_STORAGE_KEY = "incidentrelay.alerts.active_tab";


function alertAnalyticsPanelVisible() {
    return !$("#alert-analytics-panel").hasClass("is-hidden");
}


function buildAlertAnalyticsApiUrl() {
    const params = new URLSearchParams();
    const days = Number($("#alert-analytics-days").val()) || 30;

    params.set("days", String(days));
    params.set("limit", "10");
    params.set("timezone", $("#alert-analytics-timezone").val() || "UTC");

    if (typeof selectedTeamId === "function" && selectedTeamId()) {
        params.set("team_id", String(selectedTeamId()));
    }

    return "/api/alert-groups/analytics?" + params.toString();
}


function loadAlertAnalytics() {
    if (!$("#alert-analytics-panel").length) {
        return;
    }

    const generation = ++alertAnalyticsLoadGeneration;
    closeAlertAnalyticsSelection();
    $(".alert-analytics-interactive").attr("inert", "");
    $("#alert-analytics-loading").removeClass("is-hidden");
    $("#refresh-alert-analytics").prop("disabled", true);

    apiGet(
        buildAlertAnalyticsApiUrl(),
        function (payload) {
            if (generation !== alertAnalyticsLoadGeneration) {
                return;
            }

            alertAnalyticsLoaded = true;
            renderAlertAnalytics(payload || {});
            $(".alert-analytics-interactive").removeAttr("inert");
            $("#alert-analytics-loading").addClass("is-hidden");
            $("#refresh-alert-analytics").prop("disabled", false);
        },
        function (xhr) {
            if (generation !== alertAnalyticsLoadGeneration) {
                return;
            }

            $("#alert-analytics-loading").addClass("is-hidden");
            $("#refresh-alert-analytics").prop("disabled", false);
            showApiError(xhr, i18n.t("alerts.analytics.load_failed"));
        }
    );
}


function renderAlertAnalytics(payload) {
    const summary = payload.summary || {};

    setAlertAnalyticsMetric("groups", formatAlertAnalyticsNumber(summary.alert_groups));
    setAlertAnalyticsMetric("occurrences", formatAlertAnalyticsNumber(summary.occurrences));
    setAlertAnalyticsMetric("open", formatAlertAnalyticsNumber(summary.open_now));
    setAlertAnalyticsMetric("unacknowledged", formatAlertAnalyticsNumber(summary.unacknowledged));
    setAlertAnalyticsMetric("ack-rate", formatAlertAnalyticsPercent(summary.ack_rate));
    setAlertAnalyticsMetric("resolved-without-ack", formatAlertAnalyticsNumber(summary.resolved_without_ack));
    setAlertAnalyticsMetric(
        "mtta",
        formatAlertAnalyticsDurationPair(summary.mtta_seconds_p50, summary.mtta_seconds_p95)
    );
    setAlertAnalyticsMetric(
        "mttr",
        formatAlertAnalyticsDurationPair(summary.mttr_seconds_p50, summary.mttr_seconds_p95)
    );

    renderAlertAnalyticsComparison(payload);
    renderAlertAnalyticsHeatmap(payload);
    renderAlertAnalyticsGrowth(payload);
    renderAlertAnalyticsNoisy(payload.top_noisy || []);
    renderAlertAnalyticsOldest(payload.oldest_unresolved || []);
    renderAlertAnalyticsAcknowledgementHealth(payload.attention || {});
    renderAlertAnalyticsLifecycle((payload.series || {}).lifecycle_by_day || []);
}


function alertAnalyticsSelectionButton(text, payload, window, filters, enabled = true) {
    return $("<button>", {type: "button", class: "alerts-analytics-alert-link", text, disabled: !enabled})
        .on("click", function () {
            alertAnalyticsSelection = {
                ...filters, since: window.since, until: window.until,
                timezone: payload.heatmap?.timezone || "UTC", page: 1, page_size: 25,
            };
            if (payload.filters?.team_id) alertAnalyticsSelection.team_id = payload.filters.team_id;
            $("#alert-analytics-selection-title").text(i18n.t("alerts.analytics.selection.title"));
            const description = [
                i18n.t("alerts.analytics.summary." + ({mtta: "mtta", mttr: "mttr"}[filters.metric] || filters.metric)),
                filters.alertname,
                formatAlertAnalyticsTimestamp(window.since) + " — " + formatAlertAnalyticsTimestamp(window.until),
            ];
            if (filters.weekday !== undefined) {
                description.push(alertAnalyticsWeekday(filters.weekday) + " " + String(filters.hour).padStart(2, "0") + ":00, " + alertAnalyticsSelection.timezone);
            }
            $("#alert-analytics-selection-description").text(description.filter(Boolean).join(" · "));
            $("#alert-analytics-selection").removeClass("is-hidden")[0].scrollIntoView({block: "start"});
            $("#alert-analytics-selection-title").trigger("focus");
            loadAlertAnalyticsSelection();
        });
}


function closeAlertAnalyticsSelection() {
    alertAnalyticsSelectionGeneration += 1;
    alertAnalyticsSelection = null;
    $("#alert-analytics-selection").addClass("is-hidden");
}


function loadAlertAnalyticsSelection() {
    const generation = ++alertAnalyticsSelectionGeneration;
    $("#alert-analytics-selection-table").empty();
    $("#alert-analytics-selection-status").text(i18n.t("alerts.analytics.loading"));
    $("#alert-analytics-selection-prev, #alert-analytics-selection-next").prop("disabled", true);
    apiGet("/api/alert-groups/analytics/selection?" + new URLSearchParams(alertAnalyticsSelection), function (data) {
        if (generation !== alertAnalyticsSelectionGeneration) return;
        const body = $("#alert-analytics-selection-table").empty();
        data.items.forEach(row => body.append($("<tr>")
            .append($("<td>").append(alertAnalyticsGroupButton(row)))
            .append($("<td>").text(alertAnalyticsServiceLabel(row)))
            .append($("<td>").text(alertAnalyticsStatusLabel(row.status)))
            .append($("<td>").text(formatAlertAnalyticsTimestamp(row.first_seen_at)))
            .append($("<td>").text(row.occurrences === null ? "—" : row.occurrences))));
        if (!data.items.length) appendAlertAnalyticsEmptyRow(body, 5);
        $("#alert-analytics-selection-status").text(data.unlinked_occurrences
            ? i18n.t("alerts.analytics.selection.unlinked", {count: data.unlinked_occurrences}) : "");
        const paging = data.pagination;
        alertAnalyticsSelection.page = paging.page;
        $("#alert-analytics-selection-page").text(i18n.t("alerts.analytics.selection.page", {
            page: paging.page, pages: paging.total_pages, count: paging.total_items,
        }));
        $("#alert-analytics-selection-prev").prop("disabled", !paging.has_prev);
        $("#alert-analytics-selection-next").prop("disabled", !paging.has_next);
    }, function (xhr) {
        if (generation !== alertAnalyticsSelectionGeneration) return;
        $("#alert-analytics-selection-status").text(i18n.t("alerts.analytics.load_failed"));
        showApiError(xhr);
    });
}


function renderAlertAnalyticsComparison(payload) {
    const comparison = payload.comparison;
    const body = $("#alert-analytics-comparison-table").empty();
    if (!comparison) return;
    $("#alert-analytics-comparison-window").text(
        i18n.t("alerts.analytics.comparison.previous") + ": " + formatAlertAnalyticsTimestamp(comparison.previous_window.since) + " — " + formatAlertAnalyticsTimestamp(comparison.previous_window.until)
        + " · " + i18n.t("alerts.analytics.comparison.current") + ": " + formatAlertAnalyticsTimestamp(payload.window.since) + " — " + formatAlertAnalyticsTimestamp(payload.window.until));
    const metrics = [
        ["alert_groups", "alert_groups"], ["occurrences", "occurrences"], ["ack_rate", "ack_rate"],
        ["resolved_without_ack", "resolved_without_ack"], ["mtta_seconds_p50", "mtta"], ["mttr_seconds_p50", "mttr"],
    ];
    metrics.forEach(([key, metric]) => {
        const label = i18n.t("alerts.analytics.summary." + metric) + (key.endsWith("p50") ? " p50" : "");
        const row = $("<tr>").append($("<td>").text(label));
        ["previous", "current"].forEach(period => {
            const values = comparison[period];
            const value = values[key];
            const text = key.endsWith("p50") ? formatAlertAnalyticsDuration(value)
                : key === "ack_rate" ? formatAlertAnalyticsPercent(value) : formatAlertAnalyticsNumber(value);
            const window = period === "previous" ? comparison.previous_window : payload.window;
            const samplesKey = key.endsWith("p50") ? metric + "_samples" : key === "ack_rate" ? "ack_eligible" : null;
            const enabled = samplesKey ? values[samplesKey] > 0 : value !== null && value > 0;
            const cell = $("<td>").append(alertAnalyticsSelectionButton(text, payload, window, {metric}, enabled));
            if (samplesKey) cell.append($("<small>", {class: "alerts-analytics-sample-size", text: i18n.t("alerts.analytics.comparison.samples", {count: values[samplesKey] || 0})}));
            row.append(cell);
        });
        const delta = comparison.deltas[key];
        let change = "—";
        if (delta.absolute !== null) {
            if (key === "ack_rate") change = (delta.absolute > 0 ? "+" : "") + (delta.absolute * 100).toFixed(1) + " " + i18n.t("alerts.analytics.comparison.pp");
            else if (key.endsWith("p50")) change = (delta.absolute > 0 ? "+" : delta.absolute < 0 ? "−" : "") + formatAlertAnalyticsDuration(Math.abs(delta.absolute));
            else change = (delta.absolute > 0 ? "+" : "") + formatAlertAnalyticsNumber(delta.absolute);
            if (delta.percent !== null && key !== "ack_rate") change += " (" + (delta.percent > 0 ? "+" : "") + delta.percent + "%)";
            else if (delta.absolute > 0 && comparison.previous[key] === 0) change += " · " + i18n.t("alerts.analytics.comparison.no_baseline");
        }
        body.append(row.append($("<td>").text(change)));
    });
}


function alertAnalyticsWeekday(day) {
    return new Intl.DateTimeFormat(i18n.locale || "en", {weekday: "short", timeZone: "UTC"})
        .format(new Date(Date.UTC(2024, 0, 1 + day)));
}


function renderAlertAnalyticsHeatmap(payload) {
    const table = $("#alert-analytics-heatmap").empty();
    const cells = payload.heatmap?.cells || [];
    const maximum = Math.max(1, ...cells.map(cell => cell.count));
    const headings = $("<tr>").append($("<th>", {scope: "col", text: i18n.t("alerts.analytics.heatmap.day")}));
    for (let hour = 0; hour < 24; hour++) headings.append($("<th>", {scope: "col", text: String(hour).padStart(2, "0")}));
    table.append($("<thead>").append(headings));
    const body = $("<tbody>").appendTo(table);
    for (let weekday = 0; weekday < 7; weekday++) {
        const row = $("<tr>").append($("<th>", {scope: "row", text: alertAnalyticsWeekday(weekday)}));
        cells.filter(cell => cell.weekday === weekday).forEach(cell => {
            const label = i18n.t("alerts.analytics.heatmap.cell", {day: alertAnalyticsWeekday(weekday), hour: String(cell.hour).padStart(2, "0"), count: cell.count, timezone: payload.heatmap.timezone});
            const button = alertAnalyticsSelectionButton(String(cell.count), payload, payload.window,
                {metric: "alert_groups", weekday, hour: cell.hour}, cell.count > 0)
                .attr({title: label, "aria-label": label, "data-level": cell.count ? Math.ceil(cell.count / maximum * 4) : 0})
                .addClass("alerts-analytics-heat-cell");
            row.append($("<td>").append(button));
        });
        body.append(row);
    }
}


function renderAlertAnalyticsGrowth(payload) {
    const body = $("#alert-analytics-growth-table").empty();
    const rows = payload.noise_growth || [];
    if (!rows.length) return appendAlertAnalyticsEmptyRow(body, 4);
    rows.forEach(row => {
        const filters = {metric: "occurrences", alertname: row.alertname};
        const change = "+" + row.increase + (row.percent === null
            ? " · " + i18n.t("alerts.analytics.comparison.no_baseline") : " (+" + row.percent + "%)");
        body.append($("<tr>")
            .append($("<td>").append(alertAnalyticsSelectionButton(row.alertname, payload, payload.window, filters)))
            .append($("<td>").append(alertAnalyticsSelectionButton(String(row.previous), payload, payload.comparison.previous_window, filters, row.previous > 0)))
            .append($("<td>").append(alertAnalyticsSelectionButton(String(row.current), payload, payload.window, filters)))
            .append($("<td>").text(change)));
    });
}


function setAlertAnalyticsMetric(name, value) {
    $("[data-alert-analytics-metric='" + name + "']").text(value);
}


function formatAlertAnalyticsNumber(value) {
    const number = Number(value || 0);
    try {
        return new Intl.NumberFormat().format(number);
    } catch (error) {
        return String(number);
    }
}


function formatAlertAnalyticsPercent(value) {
    if (value === null || value === undefined) {
        return "-";
    }
    return Math.round(Number(value) * 100) + "%";
}


function formatAlertAnalyticsDurationPair(p50, p95) {
    if (p50 === null || p50 === undefined) {
        return "-";
    }

    return (
        "p50 " + formatAlertAnalyticsDuration(p50) +
        " / p95 " + formatAlertAnalyticsDuration(p95)
    );
}


function formatAlertAnalyticsDuration(value) {
    if (value === null || value === undefined) {
        return "-";
    }

    let seconds = Math.max(0, Math.round(Number(value) || 0));
    if (seconds < 60) {
        return seconds + "s";
    }

    const days = Math.floor(seconds / 86400);
    seconds %= 86400;
    const hours = Math.floor(seconds / 3600);
    seconds %= 3600;
    const minutes = Math.floor(seconds / 60);

    if (days) {
        return days + "d " + hours + "h";
    }
    if (hours) {
        return hours + "h " + minutes + "m";
    }
    return minutes + "m";
}


function renderAlertAnalyticsNoisy(rows) {
    const tbody = $("#alert-analytics-noisy-table").empty();

    if (!rows.length) {
        appendAlertAnalyticsEmptyRow(tbody, 6);
        return;
    }

    rows.forEach(function (row) {
        tbody.append(
            $("<tr>")
                .append($("<td>").append(alertAnalyticsNoisyAlertButton(row.alertname)))
                .append($("<td>").text(formatAlertAnalyticsNumber(row.occurrences)))
                .append($("<td>").text(formatAlertAnalyticsNumber(row.groups)))
                .append($("<td>").text(row.dedup_ratio === null ? "-" : Number(row.dedup_ratio).toFixed(2)))
                .append($("<td>").text(formatAlertAnalyticsNumber(row.open)))
                .append($("<td>").text(formatAlertAnalyticsPercent(row.ack_rate)))
        );
    });
}


function alertAnalyticsNoisyAlertButton(alertname) {
    const value = String(alertname || "").trim();

    if (!value) {
        return $("<span>").text("-");
    }

    return $("<button>")
        .attr("type", "button")
        .addClass("alerts-analytics-alert-link")
        .text(value)
        .on("click", function () {
            openAlertAnalyticsInboxSearch(value);
        });
}


function openAlertAnalyticsInboxSearch(searchValue) {
    const value = String(searchValue || "").trim();

    if (!value) {
        return;
    }

    setAlertsPageTab("inbox");

    if (typeof setTableFilterValues === "function") {
        setTableFilterValues("#status-filter", []);
        setTableFilterValues("#severity-filter", []);
        setTableFilterValues("#priority-filter", []);
        setTableFilterValues("#alerts-service-filter", []);
    }

    $("#assigned-to-me-filter").prop("checked", false);
    $("#shelved-only-filter").prop("checked", false);
    $("#alerts-search").val(value);

    if (typeof resetAlertsPagination === "function") {
        resetAlertsPagination();
    }

    if (typeof writeAlertsQueryParams === "function") {
        writeAlertsQueryParams();
    }

    if (typeof loadAlerts === "function") {
        loadAlerts();
    }
}


function renderAlertAnalyticsOldest(rows) {
    const tbody = $("#alert-analytics-oldest-table").empty();

    if (!rows.length) {
        appendAlertAnalyticsEmptyRow(tbody, 6);
        return;
    }

    rows.forEach(function (row) {
        tbody.append(
            $("<tr>")
                .append($("<td>").append(alertAnalyticsGroupButton(row)))
                .append($("<td>").text(alertAnalyticsServiceLabel(row)))
                .append($("<td>").text(String(row.priority || "-").toUpperCase()))
                .append($("<td>").text(alertAnalyticsStatusLabel(row.status)))
                .append($("<td>").text(formatAlertAnalyticsDuration(row.age_seconds)))
                .append($("<td>").text(formatAlertAnalyticsTimestamp(row.last_seen_at)))
        );
    });
}


function renderAlertAnalyticsAcknowledgementHealth(attention) {
    renderAlertAnalyticsNeedsAcknowledgement(attention.unacknowledged || []);
    renderAlertAnalyticsResolvedWithoutAck(
        attention.resolved_without_ack_by_alert || []
    );
}


function renderAlertAnalyticsNeedsAcknowledgement(rows) {
    const tbody = $("#alert-analytics-needs-ack-table").empty();

    if (!rows.length) {
        appendAlertAnalyticsEmptyRow(tbody, 5);
        return;
    }

    rows.forEach(function (row) {
        tbody.append(
            $("<tr>")
                .append($("<td>").append(alertAnalyticsGroupButton(row)))
                .append($("<td>").text(alertAnalyticsServiceLabel(row)))
                .append($("<td>").text(String(row.priority || "-").toUpperCase()))
                .append($("<td>").text(formatAlertAnalyticsDuration(row.age_seconds)))
                .append($("<td>").text(formatAlertAnalyticsTimestamp(row.last_seen_at)))
        );
    });
}


function renderAlertAnalyticsResolvedWithoutAck(rows) {
    const tbody = $("#alert-analytics-resolved-without-ack-table").empty();

    if (!rows.length) {
        appendAlertAnalyticsEmptyRow(tbody, 5);
        return;
    }

    rows.forEach(function (row) {
        tbody.append(
            $("<tr>")
                .append($("<td>").append(alertAnalyticsNoisyAlertButton(row.alertname)))
                .append($("<td>").text(formatAlertAnalyticsNumber(row.resolved_groups)))
                .append($("<td>").text(formatAlertAnalyticsNumber(row.resolved_without_ack)))
                .append($("<td>").text(formatAlertAnalyticsPercent(row.rate)))
                .append($("<td>").text(formatAlertAnalyticsDuration(row.median_lifetime_seconds)))
        );
    });
}


function alertAnalyticsStatusLabel(status) {
    const normalized = String(status || "");
    const key = "alerts.status." + normalized;
    return i18n.t(key, {}, normalized || "-");
}


function alertAnalyticsGroupButton(row) {
    return $("<button>")
        .attr("type", "button")
        .addClass("alerts-analytics-alert-link")
        .text(row.title || ("#" + row.id))
        .on("click", function () {
            if (typeof openAlertDetailsPage === "function") {
                openAlertDetailsPage(row.id);
            }
        });
}


function alertAnalyticsServiceLabel(row) {
    return row.service_name || row.service_slug || row.team_name || row.team_slug || "-";
}


function formatAlertAnalyticsTimestamp(value) {
    if (!value) {
        return "-";
    }

    if (typeof formatDateTime === "function") {
        return formatDateTime(value);
    }

    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}


function appendAlertAnalyticsEmptyRow(tbody, colspan) {
    tbody.append(
        $("<tr>").append(
            $("<td>")
                .attr("colspan", colspan)
                .addClass("alerts-analytics-empty")
                .text(i18n.t("alerts.analytics.empty"))
        )
    );
}


function alertAnalyticsThemeColor(token, fallback) {
    const root = document.documentElement;
    const body = document.body;
    const style = window.getComputedStyle(body || root);
    const value = style.getPropertyValue(token).trim();
    return value || fallback;
}


function renderAlertAnalyticsLifecycle(series) {
    const canvas = document.getElementById("alert-analytics-lifecycle-chart");
    if (!canvas || typeof Chart === "undefined") {
        return;
    }

    if (alertAnalyticsChart) {
        alertAnalyticsChart.destroy();
        alertAnalyticsChart = null;
    }

    const createdColor = alertAnalyticsThemeColor("--md-primary", "#2563eb");
    const acknowledgedColor = alertAnalyticsThemeColor("--md-warning", "#f59e0b");
    const resolvedColor = alertAnalyticsThemeColor("--md-operational", "#16a34a");

    alertAnalyticsChart = new Chart(canvas, {
        type: "line",
        data: {
            labels: series.map(function (row) { return row.bucket; }),
            datasets: [
                {
                    label: i18n.t("alerts.analytics.lifecycle.created"),
                    data: series.map(function (row) { return row.created || 0; }),
                    borderColor: createdColor,
                    backgroundColor: createdColor,
                    pointBackgroundColor: createdColor,
                    pointBorderColor: createdColor,
                    pointRadius: 3,
                    pointHoverRadius: 5,
                    borderWidth: 2,
                    tension: 0.25,
                    fill: false,
                },
                {
                    label: i18n.t("alerts.analytics.lifecycle.acknowledged"),
                    data: series.map(function (row) { return row.acknowledged || 0; }),
                    borderColor: acknowledgedColor,
                    backgroundColor: acknowledgedColor,
                    pointBackgroundColor: acknowledgedColor,
                    pointBorderColor: acknowledgedColor,
                    pointRadius: 3,
                    pointHoverRadius: 5,
                    borderWidth: 2,
                    tension: 0.25,
                    fill: false,
                },
                {
                    label: i18n.t("alerts.analytics.lifecycle.resolved"),
                    data: series.map(function (row) { return row.resolved || 0; }),
                    borderColor: resolvedColor,
                    backgroundColor: resolvedColor,
                    pointBackgroundColor: resolvedColor,
                    pointBorderColor: resolvedColor,
                    pointRadius: 3,
                    pointHoverRadius: 5,
                    borderWidth: 2,
                    tension: 0.25,
                    fill: false,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: "index",
                intersect: false,
            },
            plugins: {
                legend: {
                    labels: {
                        usePointStyle: true,
                        pointStyle: "line",
                    },
                },
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {precision: 0},
                },
            },
        },
    });
}


function setAlertsPageTabButtonState(selector, active) {
    $(selector)
        .toggleClass("is-active", active)
        .attr("aria-selected", active ? "true" : "false");
}


function setAlertsPageTab(tabName, options) {
    const settings = $.extend({persist: true}, options || {});
    const selected = tabName === "analytics" ? "analytics" : "inbox";
    const showAnalytics = selected === "analytics";

    $("#alerts-inbox-panel")
        .toggleClass("is-hidden", showAnalytics)
        .attr("aria-hidden", showAnalytics ? "true" : "false");
    $("#alert-analytics-panel")
        .toggleClass("is-hidden", !showAnalytics)
        .attr("aria-hidden", showAnalytics ? "false" : "true");

    setAlertsPageTabButtonState("#alerts-tab-inbox", !showAnalytics);
    setAlertsPageTabButtonState("#alerts-tab-analytics", showAnalytics);

    if (settings.persist) {
        try {
            localStorage.setItem(ALERTS_PAGE_TAB_STORAGE_KEY, selected);
        } catch (error) {
            // Ignore storage errors, for example private mode restrictions.
        }
    }

    if (showAnalytics) {
        if (!alertAnalyticsLoaded) {
            loadAlertAnalytics();
        } else if (alertAnalyticsChart) {
            window.setTimeout(function () {
                alertAnalyticsChart.resize();
            }, 0);
        }
    }
}


function restoreAlertsPageTab() {
    let selected = "inbox";

    try {
        const stored = localStorage.getItem(ALERTS_PAGE_TAB_STORAGE_KEY);
        if (stored === "analytics") {
            selected = "analytics";
        }
    } catch (error) {
        // Ignore storage errors.
    }

    setAlertsPageTab(selected, {persist: false});
}


$(document).ready(function () {
    AppTimezones.fillSelect("#alert-analytics-timezone", AppTimezones.getDisplayTimezone());
    $(document).on("change", "#alert-analytics-timezone", loadAlertAnalytics);
    $(document).on("click", "#alert-analytics-selection-close", closeAlertAnalyticsSelection);
    $(document).on("click", "#alert-analytics-selection-prev, #alert-analytics-selection-next", function () {
        if (!alertAnalyticsSelection) return;
        alertAnalyticsSelection.page += this.id.endsWith("prev") ? -1 : 1;
        loadAlertAnalyticsSelection();
    });
    $(document).on("click", "[data-alerts-page-tab]", function () {
        setAlertsPageTab($(this).attr("data-alerts-page-tab"));
    });
    $(document).on("click", "#refresh-alert-analytics", loadAlertAnalytics);
    $(document).on("change", "#alert-analytics-days", loadAlertAnalytics);
    $(document).on("change", "#global-team-filter", function () {
        alertAnalyticsLoaded = false;
        if (alertAnalyticsPanelVisible()) {
            loadAlertAnalytics();
        }
    });

    restoreAlertsPageTab();
});
