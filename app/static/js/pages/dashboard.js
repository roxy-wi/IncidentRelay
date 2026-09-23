let dashboardHasLoaded = false;
let dashboardLoadGeneration = 0;
let dashboardImpactHasLoaded = false;
let dashboardImpactLoadGeneration = 0;
let dashboardCharts = {};
let dashboardLastAlerts = [];
let dashboardLastServiceRows = [];

const dashboardDoughnutCenterPlugin = {
    id: "dashboardDoughnutCenter",
    afterDraw: function (chart, args, options) {
        if (!options || options.text === undefined || options.text === null) {
            return;
        }

        const area = chart.chartArea;
        if (!area) {
            return;
        }

        const ctx = chart.ctx;
        const centerX = (area.left + area.right) / 2;
        const centerY = (area.top + area.bottom) / 2;
        const textColor = dashboardThemeToken("--md-text", "#0f172a");
        const mutedColor = dashboardThemeToken("--md-muted", "#64748b");

        ctx.save();
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillStyle = textColor;
        ctx.font = "800 24px system-ui, -apple-system, BlinkMacSystemFont, sans-serif";
        ctx.fillText(String(options.text), centerX, centerY - 7);

        if (options.label) {
            ctx.fillStyle = mutedColor;
            ctx.font = "700 11px system-ui, -apple-system, BlinkMacSystemFont, sans-serif";
            ctx.fillText(String(options.label), centerX, centerY + 15);
        }
        ctx.restore();
    },
};

function dashboardAsArray(value) {
    /*
     * Return alerts from both old array responses and new paginated responses.
     */
    if (Array.isArray(value)) {
        return value;
    }
    if (value && Array.isArray(value.items)) {
        return value.items;
    }
    return [];
}

function dashboardDateValue(alert) {
    return alert.updated_at || alert.last_seen_at || alert.first_seen_at || alert.created_at || null;
}

function dashboardSortByActivity(alerts) {
    return alerts.slice().sort(function (left, right) {
        const leftDate = new Date(dashboardDateValue(left) || 0).getTime();
        const rightDate = new Date(dashboardDateValue(right) || 0).getTime();
        return rightDate - leftDate;
    });
}

function dashboardGroupCount(alerts, fieldName, fallback) {
    const result = {};
    alerts.forEach(function (alert) {
        const key = alert[fieldName] || fallback || "-";
        result[key] = (result[key] || 0) + 1;
    });
    return result;
}
function dashboardPrioritySlug(alert) {
    if (!alert) {
        return "p3";
    }

    if (alert.priority && alert.priority.slug) {
        return normalizeAlertValue(alert.priority.slug);
    }

    return normalizeAlertValue(alert.priority_slug || "p3");
}


function dashboardPriorityLabel(priority) {
    const slug = normalizeAlertValue(priority);
    const labels = {
        p1: "alerts.priority.p1",
        p2: "alerts.priority.p2",
        p3: "alerts.priority.p3",
        p4: "alerts.priority.p4",
        p5: "alerts.priority.p5",
    };

    return labels[slug]
        ? i18n.t(labels[slug])
        : (slug ? slug.toUpperCase() : i18n.t("alerts.priority.p3"));
}

function dashboardSeverityDisplayLabel(severity) {
    const normalized = normalizeAlertValue(severity);
    if (!normalized || normalized === "unknown") {
        return i18n.t("overview.labels.unknown");
    }
    return typeof severityLabel === "function" ? severityLabel(severity) : severity;
}

function dashboardAlertStatusLabel(status) {
    return typeof statusLabel === "function" ? statusLabel(status) : (status || "-");
}


function dashboardPriorityShortLabel(alert) {
    return dashboardPrioritySlug(alert).toUpperCase();
}


function dashboardPriorityCounts(alerts) {
    const result = {};

    alerts.forEach(function (alert) {
        const slug = dashboardPrioritySlug(alert);

        result[slug] = (result[slug] || 0) + 1;
    });

    return result;
}
function dashboardActiveAlerts(alerts) {
    return alerts.filter(function (alert) {
        return alert.status === "firing" || alert.status === "acknowledged";
    });
}

function dashboardAlertIsShelved(alert) {
    return Boolean(
        alert
        && (
            alert.shelved
            || (alert.shelve && alert.shelve.active)
        )
    );
}

function dashboardRunAlertAction(alertId, action) {
    apiPost(
        "/api/alert-groups/" + encodeURIComponent(alertId) + "/" + action,
        {},
        function () {
            loadDashboard();
        },
        function (xhr) {
            showApiError(xhr);
        }
    );
}

function dashboardShelveAlert(alert) {
    if (typeof window.openAlertShelveModal !== "function") {
        return;
    }

    window.openAlertShelveModal(alert.id, {
        canRespond: true,
        onSuccess: function () {
            loadDashboard();
        },
    });
}
function dashboardEscalationText(alert) {
    if (alert.escalation_policy_name) {
        const rule = alert.escalation_rule_position
            ? i18n.t("overview.escalation.rule", {position: alert.escalation_rule_position})
            : "";
        return i18n.t("overview.escalation.policy", {
            name: alert.escalation_policy_name,
            rule: rule,
        });
    }
    return i18n.t("overview.escalation.rotation", {name: alert.rotation_name || "-"});
}
function dashboardThemeToken(name, fallback) {
    const value = window.getComputedStyle(document.documentElement)
        .getPropertyValue(name)
        .trim();

    return value || fallback;
}

function dashboardDestroyChart(key) {
    if (dashboardCharts[key]) {
        dashboardCharts[key].destroy();
        delete dashboardCharts[key];
    }
}

function dashboardChartState(selector, hasData) {
    const canvas = $(selector);
    const empty = $(selector + "-empty");

    canvas.toggleClass("is-hidden", !hasData);
    empty.toggleClass("is-hidden", hasData);
}

function dashboardChartOptions() {
    return {
        responsive: true,
        maintainAspectRatio: false,
        animation: {
            duration: 240,
        },
        interaction: {
            mode: "index",
            intersect: false,
        },
        plugins: {
            legend: {
                display: true,
                position: "bottom",
                labels: {
                    usePointStyle: true,
                    pointStyle: "circle",
                    boxWidth: 8,
                    boxHeight: 8,
                    padding: 16,
                },
            },
            tooltip: {
                enabled: true,
            },
        },
    };
}

function dashboardDoughnutOptions(total, label) {
    const options = dashboardChartOptions();

    options.cutout = "72%";
    options.interaction = {
        mode: "nearest",
        intersect: true,
    };
    options.plugins.dashboardDoughnutCenter = {
        text: total,
        label: label,
    };

    return options;
}

function dashboardRenderChart(key, selector, config, hasData) {
    const canvas = $(selector).get(0);

    dashboardDestroyChart(key);
    dashboardChartState(selector, Boolean(hasData));

    if (!hasData || !canvas || typeof Chart === "undefined") {
        return;
    }

    dashboardCharts[key] = new Chart(canvas, config);
}

function dashboardActivityBuckets(alerts) {
    const points = alerts.map(function (alert) {
        return {
            alert: alert,
            time: new Date(dashboardDateValue(alert) || 0).getTime(),
        };
    }).filter(function (item) {
        return Number.isFinite(item.time) && item.time > 0;
    });

    if (!points.length) {
        return null;
    }

    const bucketCount = 8;
    const windowMs = 24 * 60 * 60 * 1000;
    const end = Math.max.apply(null, points.map(function (item) { return item.time; }));
    const start = end - windowMs;
    const bucketMs = windowMs / bucketCount;
    const labels = [];
    const data = {
        firing: Array(bucketCount).fill(0),
        acknowledged: Array(bucketCount).fill(0),
        resolved: Array(bucketCount).fill(0),
    };
    const formatter = new Intl.DateTimeFormat(document.documentElement.lang || undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
    });

    for (let index = 0; index < bucketCount; index += 1) {
        labels.push(formatter.format(new Date(start + (index + 1) * bucketMs)));
    }

    points.forEach(function (item) {
        if (item.time < start || item.time > end) {
            return;
        }

        const index = Math.min(
            bucketCount - 1,
            Math.max(0, Math.floor((item.time - start) / bucketMs))
        );
        const status = normalizeAlertValue(item.alert.status);

        if (data[status]) {
            data[status][index] += 1;
        }
    });

    return {
        labels: labels,
        data: data,
    };
}

function renderDashboardActivityTrend(alerts) {
    const series = dashboardActivityBuckets(alerts);
    const hasData = Boolean(series);
    const options = dashboardChartOptions();

    options.scales = {
        x: {
            grid: {display: false},
            ticks: {
                maxRotation: 0,
                autoSkip: true,
                maxTicksLimit: 6,
            },
        },
        y: {
            beginAtZero: true,
            ticks: {precision: 0},
        },
    };

    dashboardRenderChart(
        "activity",
        "#dashboard-activity-chart",
        {
            type: "line",
            data: {
                labels: series ? series.labels : [],
                datasets: series ? [
                    {
                        label: dashboardAlertStatusLabel("firing"),
                        data: series.data.firing,
                        borderColor: dashboardThemeToken("--md-danger", "#dc2626"),
                        backgroundColor: dashboardThemeToken("--md-danger", "#dc2626"),
                        borderWidth: 2,
                        tension: 0.35,
                        pointRadius: 2,
                        pointHoverRadius: 4,
                    },
                    {
                        label: dashboardAlertStatusLabel("acknowledged"),
                        data: series.data.acknowledged,
                        borderColor: dashboardThemeToken("--md-warning", "#d97706"),
                        backgroundColor: dashboardThemeToken("--md-warning", "#d97706"),
                        borderWidth: 2,
                        tension: 0.35,
                        pointRadius: 2,
                        pointHoverRadius: 4,
                    },
                    {
                        label: dashboardAlertStatusLabel("resolved"),
                        data: series.data.resolved,
                        borderColor: dashboardThemeToken("--md-success", "#16a34a"),
                        backgroundColor: dashboardThemeToken("--md-success", "#16a34a"),
                        borderWidth: 2,
                        tension: 0.35,
                        pointRadius: 2,
                        pointHoverRadius: 4,
                    },
                ] : [],
            },
            options: options,
        },
        hasData
    );
}

function loadDashboard() {
    const params = [];
    const generation = ++dashboardLoadGeneration;
    let delayedIndicator = null;

    if (typeof selectedTeamId === "function" && selectedTeamId()) {
        params.push("team_id=" + encodeURIComponent(selectedTeamId()));
    }
    params.push("page=1");
    params.push("page_size=100");
    params.push("sort=activity");
    params.push("order=desc");

    if (window.AppLoading) {
        if (!dashboardHasLoaded) {
            AppLoading.showTableSkeleton("#dashboard-alerts", {columns: 9, rows: 6});
        } else {
            AppLoading.clear("#dashboard-loading-indicator");
            delayedIndicator = AppLoading.delayed(function () {
                if (generation === dashboardLoadGeneration) {
                    AppLoading.showInline(
                        "#dashboard-loading-indicator",
                        i18n.t("common.updating")
                    );
                }
            });
        }
    }

    function finishDashboardLoading() {
        if (generation !== dashboardLoadGeneration || !window.AppLoading) {
            return;
        }

        AppLoading.clearTableBusy("#dashboard-alerts");
        if (delayedIndicator) {
            delayedIndicator.finish(function () {
                AppLoading.clear("#dashboard-loading-indicator");
            });
        } else {
            AppLoading.clear("#dashboard-loading-indicator");
        }
    }

    apiGet("/api/alert-groups?" + params.join("&"), function (response) {
        if (generation !== dashboardLoadGeneration) {
            return;
        }

        const alerts = dashboardAsArray(response);
        const activeAlerts = dashboardActiveAlerts(alerts);
        const sortedActiveAlerts = dashboardSortByActivity(activeAlerts);

        dashboardHasLoaded = true;
        dashboardLastAlerts = alerts.slice();
        finishDashboardLoading();
        renderAlertsSummaryGrid("#overview-alerts-summary", alerts);
        renderDashboardActivityTrend(alerts);
        renderDashboardAlertsTable(sortedActiveAlerts.slice(0, 8));
        renderDashboardSeveritySplit(alerts);
        renderDashboardPrioritySplit(alerts);
        renderDashboardTeamSummary(alerts);
        renderDashboardSystemStatus(alerts, activeAlerts);
    }, function (xhr) {
        if (generation !== dashboardLoadGeneration) {
            return;
        }

        finishDashboardLoading();
        if (!dashboardHasLoaded) {
            $("#dashboard-alerts").empty();
        }
        showApiError(xhr);
    });
    loadDashboardServiceImpact();
    loadDashboardOncall();
    loadDashboardActivity(generation);
}

function renderDashboardAlertsTable(alerts) {
    const tbody = $("#dashboard-alerts");
    tbody.empty();

    if (!alerts.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>")
                    .attr("colspan", "9")
                    .addClass("empty-table-cell")
                    .text(i18n.t("overview.empty.no_active_incidents"))
            )
        );
        return;
    }

    alerts.forEach(function (alert) {
        tbody.append(renderDashboardAlertRow(alert));
    });
}

function renderDashboardAlertRow(alert) {
    const row = $("<tr>");

    row.append(
        $("<td>").append(
            $("<button>")
                .attr("type", "button")
                .attr("title", i18n.t("overview.alert.show_details"))
                .addClass("overview-id-link")
                .text("#" + alert.id)
                .on("click", function () {
                    if (typeof showAlertDetails === "function") {
                        showAlertDetails(alert.id);
                    }
                })
        )
    );
    row.append(
        $("<td>")
            .addClass("overview-alert-title-cell")
            .append($("<div>").addClass("overview-alert-title").text(alert.title || "-"))
            .append($("<div>").addClass("overview-alert-meta").text((alert.source || alert.route_name || i18n.t("overview.alert.fallback")) + " · " + dashboardEscalationText(alert)))
    );
    row.append(
        $("<td>").append(
            makeAlertBadge(
                dashboardSeverityDisplayLabel(alert.severity),
                severityBadgeClass(alert.severity)
            )
        )
    );

    row.append(
        $("<td>").append(
            makeAlertBadge(
                dashboardPriorityShortLabel(alert),
                priorityBadgeClass(alert)
            ).attr("title", dashboardPriorityLabel(dashboardPrioritySlug(alert)))
        )
    );

    row.append(
        $("<td>").append(
            makeAlertBadge(dashboardAlertStatusLabel(alert.status), statusBadgeClass(alert.status))
        )
    );
    row.append($("<td>").text(alert.team_name || alert.team_slug || "-"));
    row.append($("<td>").addClass("overview-duration-cell").text(alertDuration(alert)));
    row.append($("<td>").text(formatDateTimeMinutes(dashboardDateValue(alert))));

    const actionsCell = $("<td>").addClass("actions-cell");
    const actions = $("<div>").addClass("table-actions");

    if (canRespondObject(alert) && typeof makeActionMenu === "function") {
        const shelved = dashboardAlertIsShelved(alert);
        const items = [];

        if (alert.status === "firing" && !shelved) {
            items.push({
                label: i18n.t("overview.actions.ack"),
                icon: "fas fa-check",
                onClick: function () {
                    dashboardRunAlertAction(alert.id, "acknowledge");
                },
            });
        }

        if (shelved) {
            items.push({
                label: i18n.t("alert_details.actions.unshelve"),
                icon: "fas fa-box-open",
                onClick: function () {
                    dashboardRunAlertAction(alert.id, "unshelve");
                },
            });
        } else {
            items.push({
                label: i18n.t("alert_details.actions.shelve"),
                icon: "fas fa-box-archive",
                onClick: function () {
                    dashboardShelveAlert(alert);
                },
            });
        }

        if (alert.status !== "resolved") {
            items.push({
                label: i18n.t("overview.actions.resolve"),
                icon: "fas fa-check-double",
                onClick: function () {
                    dashboardRunAlertAction(alert.id, "resolve");
                },
            });
        }

        actions.append(
            makeActionMenu({
                object: alert,
                label: i18n.t("shared.actions"),
                items: items,
            })
        );
    }

    actionsCell.append(actions);
    row.append(actionsCell);
    return row;
}

function dashboardActivityEventLabel(eventType) {
    if (typeof alertEventTypeLabel === "function") {
        const existing = alertEventTypeLabel(eventType);
        if (existing && existing !== eventType) {
            return existing;
        }
    }

    return String(eventType || "-")
        .replace(/_/g, " ")
        .replace(/\b\w/g, function (letter) {
            return letter.toUpperCase();
        });
}

function dashboardActivityDotClass(eventType) {
    const normalized = String(eventType || "").toLowerCase();

    if (["resolved", "alert_group_unshelved"].includes(normalized)) {
        return "overview-dot-resolved";
    }
    if ([
        "acknowledged",
        "priority_changed",
        "priority_auto_updated",
        "priority_auto_recalculated",
        "maintenance_applied",
        "maintenance_released",
    ].includes(normalized)) {
        return "overview-dot-acknowledged";
    }
    if (["reopened", "escalated", "routing_error"].includes(normalized)) {
        return "overview-dot-firing";
    }
    if ([
        "alert_group_shelved",
        "alert_group_shelve_expired",
        "silenced",
        "unsilenced",
        "merged",
        "merge_target_updated",
    ].includes(normalized)) {
        return "overview-dot-silenced";
    }

    return "overview-dot-activity";
}

function dashboardActivityActor(event) {
    const user = event && event.user ? event.user : {};
    return user.display_name || user.username || i18n.t("overview.activity.system");
}

function loadDashboardActivity(generation) {
    const params = ["limit=6"];
    if (typeof selectedTeamId === "function" && selectedTeamId()) {
        params.push("team_id=" + encodeURIComponent(selectedTeamId()));
    }

    apiGet(
        "/api/alert-groups/activity?" + params.join("&"),
        function (response) {
            if (generation !== dashboardLoadGeneration) {
                return;
            }
            renderDashboardActivity(dashboardAsArray(response));
        },
        function () {
            if (generation !== dashboardLoadGeneration) {
                return;
            }
            renderDashboardActivity([], true);
        }
    );
}

function renderDashboardActivity(events, unavailable) {
    const target = $("#dashboard-recent-activity");
    target.empty();

    if (!events.length) {
        target.append(
            $("<div>")
                .addClass("overview-empty")
                .text(
                    unavailable
                        ? i18n.t("overview.activity.unavailable")
                        : i18n.t("overview.activity.none")
                )
        );
        return;
    }

    events.forEach(function (event) {
        const group = event.alert_group || {};
        const item = $("<button>")
            .attr("type", "button")
            .addClass("overview-list-item overview-list-button dashboard-activity-item")
            .on("click", function () {
                if (group.id && typeof showAlertDetails === "function") {
                    showAlertDetails(group.id);
                }
            });

        item.append(
            $("<span>")
                .addClass("overview-list-dot")
                .addClass(dashboardActivityDotClass(event.event_type))
        );

        const main = $("<div>").addClass("list-main dashboard-activity-copy");
        main.append(
            $("<div>")
                .addClass("list-title")
                .text((group.id ? "#" + group.id + " " : "") + (group.title || i18n.t("overview.alert.fallback")))
        );
        main.append(
            $("<div>")
                .addClass("list-subtitle")
                .text(
                    dashboardActivityEventLabel(event.event_type)
                    + " · "
                    + dashboardActivityActor(event)
                )
        );

        if (event.message) {
            main.append(
                $("<div>")
                    .addClass("dashboard-activity-message")
                    .text(event.message)
            );
        }

        item.append(main);
        item.append(
            $("<span>")
                .addClass("overview-list-time dashboard-activity-time")
                .text(formatDateTimeMinutes(event.created_at))
        );
        target.append(item);
    });
}

function loadDashboardOncall() {
    apiGet(
        "/api/rotations" + dashboardSelectedTeamQuery(),
        function (rotations) {
            renderDashboardOncall(rotations);
        },
        function () {
            renderDashboardOncall([]);
        }
    );
}

function dashboardOncallInitials(value) {
    const text = String(value || "?").trim();
    const parts = text.split(/\s+/).filter(Boolean);

    if (!parts.length) {
        return "?";
    }

    if (parts.length > 1) {
        return (parts[0][0] + parts[1][0]).toUpperCase();
    }

    return parts[0].slice(0, 2).toUpperCase();
}

function renderDashboardOncall(rotations) {
    const target = $("#dashboard-oncall-now");
    target.empty();

    const items = dashboardAsArray(rotations)
        .filter(function (rotation) {
            return rotation && rotation.enabled !== false;
        })
        .sort(function (left, right) {
            return String(left.team_name || left.team_slug || "").localeCompare(
                String(right.team_name || right.team_slug || "")
            ) || String(left.name || "").localeCompare(String(right.name || ""));
        });

    if (!items.length) {
        target.append(
            $("<div>")
                .addClass("overview-empty")
                .text(i18n.t("overview.oncall.none"))
        );
        return;
    }

    items.slice(0, 6).forEach(function (rotation) {
        const userName = rotation.current_oncall || i18n.t("overview.oncall.unassigned");
        const hasOncall = Boolean(rotation.current_oncall);
        const teamName = rotation.team_name || rotation.team_slug || "-";
        const rotationName = rotation.name || i18n.t(
            "overview.oncall.rotation_fallback",
            {id: rotation.id}
        );

        target.append(
            $("<button>")
                .attr("type", "button")
                .addClass("list-item overview-list-button dashboard-oncall-item")
                .on("click", function () {
                    navigate(
                        "/calendar?team_id="
                        + encodeURIComponent(rotation.team_id)
                        + "&rotation_id="
                        + encodeURIComponent(rotation.id),
                        true
                    );
                })
                .append(
                    $("<span>")
                        .addClass("avatar")
                        .text(dashboardOncallInitials(userName))
                )
                .append(
                    $("<span>")
                        .addClass("list-main")
                        .append(
                            $("<span>")
                                .addClass("list-title")
                                .text(userName)
                        )
                        .append(
                            $("<span>")
                                .addClass("list-subtitle")
                                .text(teamName + " · " + rotationName)
                        )
                )
                .append(
                    $("<span>")
                        .addClass("dashboard-oncall-status")
                        .toggleClass("is-gap", !hasOncall)
                        .text(
                            hasOncall
                                ? i18n.t("overview.oncall.now")
                                : i18n.t("overview.oncall.gap")
                        )
                )
        );
    });

    if (items.length > 6) {
        target.append(
            $("<button>")
                .attr("type", "button")
                .addClass("overview-list-item overview-list-button dashboard-impact-more")
                .text(i18n.t("overview.oncall.more", {count: items.length - 6}))
                .on("click", function () {
                    navigate("/calendar", true);
                })
        );
    }
}

function dashboardDoughnutData(counts, order, labelFunction, colorFunction) {
    const labels = [];
    const values = [];
    const colors = [];

    order.forEach(function (key) {
        const count = Number(counts[key] || 0);
        if (!count) {
            return;
        }
        labels.push(labelFunction(key));
        values.push(count);
        colors.push(colorFunction(key));
    });

    return {
        labels: labels,
        values: values,
        colors: colors,
    };
}

function dashboardSeverityColor(value) {
    const normalized = normalizeAlertValue(value);
    const colors = {
        critical: dashboardThemeToken("--md-danger", "#dc2626"),
        high: dashboardThemeToken("--md-warning", "#d97706"),
        warning: dashboardThemeToken("--md-warning", "#d97706"),
        medium: dashboardThemeToken("--md-info", "#0284c7"),
        info: dashboardThemeToken("--md-info", "#0284c7"),
        low: dashboardThemeToken("--md-primary", "#2563eb"),
        unknown: dashboardThemeToken("--md-muted", "#64748b"),
    };

    return colors[normalized] || colors.unknown;
}

function renderDashboardSeveritySplit(alerts) {
    const counts = dashboardGroupCount(alerts, "severity", "unknown");
    const order = ["critical", "high", "warning", "medium", "info", "low", "unknown"];
    const chartData = dashboardDoughnutData(
        counts,
        order,
        dashboardSeverityDisplayLabel,
        dashboardSeverityColor
    );
    const total = chartData.values.reduce(function (sum, value) { return sum + value; }, 0);

    dashboardRenderChart(
        "severity",
        "#dashboard-severity-chart",
        {
            type: "doughnut",
            data: {
                labels: chartData.labels,
                datasets: [{
                    data: chartData.values,
                    backgroundColor: chartData.colors,
                    borderWidth: 0,
                    hoverOffset: 5,
                }],
            },
            options: dashboardDoughnutOptions(
                total,
                i18n.t("overview.charts.alerts_label")
            ),
            plugins: [dashboardDoughnutCenterPlugin],
        },
        total > 0
    );
}

function dashboardPriorityColor(value) {
    const colors = {
        p1: dashboardThemeToken("--md-danger", "#dc2626"),
        p2: dashboardThemeToken("--md-warning", "#d97706"),
        p3: dashboardThemeToken("--md-info", "#0284c7"),
        p4: dashboardThemeToken("--md-primary", "#2563eb"),
        p5: dashboardThemeToken("--md-muted", "#64748b"),
    };

    return colors[normalizeAlertValue(value)] || colors.p5;
}

function renderDashboardPrioritySplit(alerts) {
    const counts = dashboardPriorityCounts(alerts);
    const order = ["p1", "p2", "p3", "p4", "p5"];
    const chartData = dashboardDoughnutData(
        counts,
        order,
        dashboardPriorityLabel,
        dashboardPriorityColor
    );
    const total = chartData.values.reduce(function (sum, value) { return sum + value; }, 0);

    dashboardRenderChart(
        "priority",
        "#dashboard-priority-chart",
        {
            type: "doughnut",
            data: {
                labels: chartData.labels,
                datasets: [{
                    data: chartData.values,
                    backgroundColor: chartData.colors,
                    borderWidth: 0,
                    hoverOffset: 5,
                }],
            },
            options: dashboardDoughnutOptions(
                total,
                i18n.t("overview.charts.alerts_label")
            ),
            plugins: [dashboardDoughnutCenterPlugin],
        },
        total > 0
    );
}

function renderDashboardTeamSummary(alerts) {
    const unknownTeam = i18n.t("overview.labels.unknown_team");
    const teamCounts = {};

    dashboardActiveAlerts(alerts).forEach(function (alert) {
        const team = alert.team_slug || alert.team_name || unknownTeam;
        if (!teamCounts[team]) {
            teamCounts[team] = {firing: 0, acknowledged: 0, total: 0};
        }

        if (alert.status === "firing") {
            teamCounts[team].firing += 1;
        } else if (alert.status === "acknowledged") {
            teamCounts[team].acknowledged += 1;
        }
        teamCounts[team].total += 1;
    });

    const order = Object.keys(teamCounts).sort(function (left, right) {
        return teamCounts[right].total - teamCounts[left].total;
    }).slice(0, 8);
    const options = dashboardChartOptions();

    options.indexAxis = "y";
    options.scales = {
        x: {
            beginAtZero: true,
            stacked: true,
            ticks: {precision: 0},
        },
        y: {
            stacked: true,
            grid: {display: false},
        },
    };

    dashboardRenderChart(
        "teams",
        "#dashboard-team-chart",
        {
            type: "bar",
            data: {
                labels: order,
                datasets: [
                    {
                        label: i18n.t("alerts.status.firing"),
                        data: order.map(function (team) { return teamCounts[team].firing; }),
                        backgroundColor: dashboardThemeToken("--md-danger", "#dc2626"),
                        borderRadius: 7,
                        borderSkipped: false,
                        barThickness: 18,
                    },
                    {
                        label: i18n.t("alerts.status.acknowledged"),
                        data: order.map(function (team) { return teamCounts[team].acknowledged; }),
                        backgroundColor: dashboardThemeToken("--md-warning", "#d97706"),
                        borderRadius: 7,
                        borderSkipped: false,
                        barThickness: 18,
                    },
                ],
            },
            options: options,
        },
        order.length > 0
    );
}

function dashboardServiceHealthColor(status) {
    const colors = {
        operational: dashboardThemeToken("--md-operational", "#16a34a"),
        degraded: dashboardThemeToken("--md-degraded", "#f59e0b"),
        partial_outage: dashboardThemeToken("--md-partial-outage", "#f97316"),
        major_outage: dashboardThemeToken("--md-major-outage", "#dc2626"),
        maintenance: dashboardThemeToken("--md-maintenance", "#7c3aed"),
        unknown: dashboardThemeToken("--md-muted", "#64748b"),
    };

    return colors[status] || colors.unknown;
}

function renderDashboardServiceHealth(rows) {
    const counts = {};
    const order = [
        "major_outage",
        "partial_outage",
        "degraded",
        "maintenance",
        "operational",
        "unknown",
    ];

    rows.forEach(function (row) {
        const status = row.effective_status || "unknown";
        if (status === "disabled") {
            return;
        }
        counts[status] = (counts[status] || 0) + 1;
    });

    const chartData = dashboardDoughnutData(
        counts,
        order,
        dashboardImpactStatusLabel,
        dashboardServiceHealthColor
    );
    const total = chartData.values.reduce(function (sum, value) { return sum + value; }, 0);

    dashboardRenderChart(
        "serviceHealth",
        "#dashboard-service-health-chart",
        {
            type: "doughnut",
            data: {
                labels: chartData.labels,
                datasets: [{
                    data: chartData.values,
                    backgroundColor: chartData.colors,
                    borderWidth: 0,
                    hoverOffset: 5,
                }],
            },
            options: dashboardDoughnutOptions(
                total,
                i18n.t("overview.charts.services_label")
            ),
            plugins: [dashboardDoughnutCenterPlugin],
        },
        total > 0
    );
}

function renderDashboardSystemStatus(alerts, activeAlerts) {
    const target = $("#dashboard-system-status");
    const firing = activeAlerts.filter(function (alert) {
        return alert.status === "firing";
    }).length;

    if (!alerts.length) {
        target.text(i18n.t("overview.system.no_alerts"));
        return;
    }
    if (firing > 0) {
        target.text(i18n.t("overview.system.firing", {count: firing}));
        return;
    }
    if (activeAlerts.length > 0) {
        target.text(i18n.t("overview.system.acknowledged", {count: activeAlerts.length}));
        return;
    }
    target.text(i18n.t("overview.system.resolved"));
}

$(document).on("click", "#reload-dashboard", loadDashboard);
function dashboardSelectedTeamQuery() {
    if (typeof selectedTeamId === "function" && selectedTeamId()) {
        return "?team_id=" + encodeURIComponent(selectedTeamId());
    }

    return "";
}

function dashboardDisplayName(name, slug, fallback) {
    return name || slug || fallback || "-";
}

function dashboardImpactStatusRank(status) {
    const ranks = {
        disabled: 0,
        operational: 1,
        unknown: 2,
        maintenance: 3,
        degraded: 4,
        partial_outage: 5,
        major_outage: 6,
    };

    return ranks[status || "unknown"] || 0;
}

function dashboardImpactStatusLabel(status) {
    const normalized = String(status || "unknown").toLowerCase();
    const key = "overview.impact.status." + normalized;
    return i18n.t(key, {}, normalized.replace(/_/g, " "));
}

function dashboardImpactStatusCssClass(status) {
    const normalized = status || "unknown";

    return {
        major_outage: "impact-status-major",
        partial_outage: "impact-status-partial",
        degraded: "impact-status-degraded",
        maintenance: "impact-status-maintenance",
        operational: "impact-status-operational",
        disabled: "impact-status-neutral",
        unknown: "impact-status-neutral"
    }[normalized] || "impact-status-neutral";
}

function dashboardImpactBadge(status) {
    const normalized = status || "unknown";

    return $("<span>")
        .addClass("status-pill impact-status-pill")
        .addClass(dashboardImpactStatusCssClass(normalized))
        .text(dashboardImpactStatusLabel(normalized));
}

function dashboardImpactIssueRootCause(issue) {
    return dashboardDisplayName(
        issue.root_cause_service_name,
        issue.root_cause_service_slug,
        issue.root_cause_service_display
    );
}

function dashboardImpactIssuePath(issue) {
    const path = dashboardAsArray(issue.path);

    if (!path.length) {
        return dashboardDisplayName(
            issue.service_name,
            issue.service_slug,
            issue.service_display
        );
    }

    return path.map(function (node) {
        return dashboardDisplayName(
            node.service_name,
            node.service_slug,
            node.service_display
        );
    }).join(" → ");
}

function dashboardBestImpactIssue(row) {
    const issues = dashboardImpactIssues(row);

    if (!issues.length) {
        return null;
    }

    return issues
        .slice()
        .sort(function (left, right) {
            return dashboardImpactStatusRank(right.impact_status || right.status)
                - dashboardImpactStatusRank(left.impact_status || left.status);
        })[0];
}

function dashboardImpactRows(rows) {
    return dashboardAsArray(rows)
        .filter(function (row) {
            return row.effective_status
                && row.effective_status !== "operational"
                && row.effective_status !== "disabled";
        })
        .sort(function (left, right) {
            return dashboardImpactStatusRank(right.effective_status)
                - dashboardImpactStatusRank(left.effective_status)
                || Number(right.critical_open_alerts || 0) - Number(left.critical_open_alerts || 0)
                || Number(right.open_alerts || 0) - Number(left.open_alerts || 0);
        });
}

function loadDashboardServiceImpact() {
    const generation = ++dashboardImpactLoadGeneration;

    if (window.AppLoading && !dashboardImpactHasLoaded) {
        AppLoading.showBlock(
            "#dashboard-service-impact",
            i18n.t("common.loading"),
            {compact: true}
        );
    }

    apiGet("/api/services/impact" + dashboardSelectedTeamQuery(), function (rows) {
        if (generation !== dashboardImpactLoadGeneration) {
            return;
        }

        const serviceRows = dashboardAsArray(rows);

        dashboardImpactHasLoaded = true;
        dashboardLastServiceRows = serviceRows.slice();
        renderDashboardServiceHealth(serviceRows);
        renderDashboardServiceImpact(dashboardImpactRows(serviceRows));
    }, function (xhr) {
        if (generation !== dashboardImpactLoadGeneration) {
            return;
        }

        if (!dashboardImpactHasLoaded && window.AppLoading) {
            AppLoading.clear("#dashboard-service-impact");
        }
        showApiError(xhr);
    });
}

function renderDashboardServiceImpact(rows) {
    const target = $("#dashboard-service-impact");
    target.empty();

    $("#dashboard-impacted-services-count").text(rows.length);

    if (!rows.length) {
        target.append(
            $("<div>")
                .addClass("overview-empty")
                .text(i18n.t("overview.impact.none"))
        );
        return;
    }

    rows.slice(0, 5).forEach(function (row) {
        target.append(renderDashboardServiceImpactItem(row));
    });

    if (rows.length > 5) {
        target.append(
            $("<button>")
                .attr("type", "button")
                .addClass("overview-list-item overview-list-button dashboard-impact-more")
                .text(i18n.t("overview.impact.more", {count: rows.length - 5}))
                .on("click", function () {
                    navigate("/services", true);
                })
        );
    }
}

function renderDashboardServiceImpactItem(row) {
    const serviceName = dashboardDisplayName(
        row.service_name,
        row.service_slug,
        i18n.t("overview.impact.service_number", {id: row.service_id})
    );

    const teamName = dashboardDisplayName(row.team_name, row.team_slug);
    const issue = dashboardBestImpactIssue(row);

    const item = $("<button>")
        .attr("type", "button")
        .addClass("overview-list-item overview-list-button dashboard-impact-item")
        .addClass(
            "dashboard-impact-item-"
            + String(row.effective_status || "unknown").replace(/_/g, "-")
        )
        .on("click", function () {
            navigate("/services", true);
        });

    item.append(
        $("<span>")
            .addClass("overview-list-dot")
            .addClass("overview-dot-" + String(row.effective_status || "unknown").replace(/_/g, "-"))
    );

    const main = $("<div>").addClass("list-main");

    main.append(
        $("<div>")
            .addClass("overview-list-title dashboard-impact-title")
            .text(serviceName)
    );

    const subtitleParts = [
        teamName,
        i18n.t("overview.impact.open", {count: Number(row.open_alert_groups || 0)}),
    ];

    if (Number(row.critical_open_alert_groups || 0) > 0) {
        subtitleParts.push(i18n.t("overview.impact.critical", {count: Number(row.critical_open_alert_groups || 0)}));
    }

    main.append(
        $("<div>")
            .addClass("list-subtitle")
            .text(subtitleParts.join(" · "))
    );

    if (issue) {
        main.append(
            $("<div>")
                .addClass("dashboard-impact-root")
                .text(i18n.t("overview.impact.root_cause", {
                    root: dashboardImpactIssueRootCause(issue),
                    path: dashboardImpactIssuePath(issue),
                }))
        );
    } else if (dashboardHasAlertImpact(row)) {
        main.append(
            $("<div>")
                .addClass("dashboard-impact-root")
                .text(i18n.t("overview.impact.caused_by_alerts"))
        );
    }

    item.append(main);

    item.append(
        $("<div>")
            .addClass("dashboard-impact-status")
            .append(dashboardImpactBadge(row.effective_status))
    );

    return item;
}
function dashboardHasAlertImpact(row) {
    return !!(
        row &&
        row.alert_impact_status &&
        row.alert_impact_status !== "operational"
    );
}


function dashboardImpactIssues(row) {
    const rootCauses = dashboardAsArray(row.root_causes);
    const paths = row.explanation ? dashboardAsArray(row.explanation.paths) : [];

    if (paths.length) {
        return paths.map(function (path, index) {
            const nodes = dashboardNormalizeImpactPath(path);
            const rootCause = dashboardFindRootCauseForPath(rootCauses, nodes) ||
                rootCauses[index] ||
                rootCauses[0] ||
                {};

            return dashboardBuildImpactIssue(row, rootCause, nodes, index);
        });
    }

    return rootCauses.map(function (rootCause, index) {
        const path = dashboardNormalizeImpactPath(rootCause.path);

        return dashboardBuildImpactIssue(
            row,
            rootCause,
            path.length ? path : [dashboardRootCauseToPathNode(rootCause)],
            index
        );
    });
}


function dashboardNormalizeImpactPath(path) {
    return dashboardAsArray(path).map(function (node) {
        node = node || {};

        return {
            service_id: node.service_id,
            service_name: node.service_name,
            service_slug: node.service_slug,
            service_display: node.service_name || node.service_slug,
            status: node.effective_status || node.status || "unknown",
            dependency_type: node.dependency_type || null,
            criticality: node.dependency_criticality || node.criticality || null,
        };
    });
}


function dashboardFindRootCauseForPath(rootCauses, nodes) {
    if (!rootCauses.length || !nodes.length) {
        return null;
    }

    const lastNode = nodes[nodes.length - 1];

    return rootCauses.find(function (cause) {
        return Number(cause.service_id) === Number(lastNode.service_id);
    }) || null;
}


function dashboardRootCauseToPathNode(rootCause) {
    rootCause = rootCause || {};

    return {
        service_id: rootCause.service_id,
        service_name: rootCause.service_name,
        service_slug: rootCause.service_slug,
        service_display: rootCause.service_name || rootCause.service_slug,
        status: rootCause.effective_status || rootCause.status || "unknown",
        dependency_type: null,
        criticality: null,
    };
}


function dashboardBuildImpactIssue(row, rootCause, path, index) {
    path = dashboardNormalizeImpactPath(path);
    rootCause = rootCause || {};

    const directNode = path.length ? path[0] : dashboardRootCauseToPathNode(rootCause);

    return {
        service_id: directNode.service_id || rootCause.service_id || row.service_id,
        service_name: directNode.service_name || rootCause.service_name || row.service_name,
        service_slug: directNode.service_slug || rootCause.service_slug || row.service_slug,
        service_display: directNode.service_display ||
            directNode.service_name ||
            directNode.service_slug ||
            rootCause.service_name ||
            rootCause.service_slug,

        status: rootCause.effective_status ||
            rootCause.status ||
            directNode.status ||
            row.effective_status ||
            "unknown",

        impact_status: row.dependency_impact_status ||
            row.effective_status ||
            "unknown",

        dependency_type: directNode.dependency_type || "dependency",
        criticality: directNode.criticality || "important",

        root_cause_service_id: rootCause.service_id || directNode.service_id || row.service_id,
        root_cause_service_name: rootCause.service_name || directNode.service_name || row.service_name,
        root_cause_service_slug: rootCause.service_slug || directNode.service_slug || row.service_slug,
        root_cause_service_display: rootCause.service_name || rootCause.service_slug,

        path: path,
        depth: Math.max(path.length - 1, 0),

        cycle_detected: !!row.cycle_detected,
        depth_limited: !!row.depth_limited,
        contributes_to_impact: row.primary_reason !== "none",

        description: row.explanation ? row.explanation.message : null,
        _index: index,
    };
}

document.addEventListener("incidentrelay:theme-change", function () {
    if (dashboardLastAlerts.length) {
        renderDashboardActivityTrend(dashboardLastAlerts);
        renderDashboardSeveritySplit(dashboardLastAlerts);
        renderDashboardPrioritySplit(dashboardLastAlerts);
        renderDashboardTeamSummary(dashboardLastAlerts);
    }

    if (dashboardLastServiceRows.length) {
        renderDashboardServiceHealth(dashboardLastServiceRows);
    }
});
