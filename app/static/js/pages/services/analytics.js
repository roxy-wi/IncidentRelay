// Service analytics and SLO analytics rendering.

function refreshServiceAnalytics() {
    const days = Number($("#service-analytics-days").val() || 30);
    const separator = selectedTeamQuery() ? "&" : "?";
    const url = "/api/services/analytics" + selectedTeamQuery()
        + separator
        + [
            "days=" + encodeURIComponent(days),
            "include_series=true",
            "include_noise=true",
            "include_response=true",
            "include_maintenance=true",
            "include_impact=true",
            "include_operational=true",
            "sort=open_alert_groups",
            "order=desc",
        ].join("&");

    apiGet(url, function (payload) {
        serviceAnalyticsPayload = payload || {};
        serviceAnalyticsCache = asArray(serviceAnalyticsPayload.items);

        renderServiceAnalyticsSummary();
        renderServiceAnalyticsCharts();
        renderServiceAnalyticsTable();
    });
}

function renderServiceAnalyticsSummary() {
    const summary = serviceAnalyticsPayload ? (serviceAnalyticsPayload.summary || {}) : {};
    const windowInfo = serviceAnalyticsPayload ? (serviceAnalyticsPayload.window || {}) : {};

    $("#services-summary-total").text(Number(summary.services || serviceAnalyticsCache.length || 0));
    $("#services-summary-operational").text(Number(summary.open_alert_groups || 0));
    $("#services-summary-degraded").text(Number(summary.affected_services || 0));
    $("#services-summary-critical").text(Number(summary.critical_open_alert_groups || 0));

    $(".summary-card").eq(0).find(".summary-title").text("Services");
    $(".summary-card").eq(0).find(".summary-hint").text("Analytics window");

    $(".summary-card").eq(1).find(".summary-title").text("Open groups");
    $(".summary-card").eq(1).find(".summary-hint").text("Grouped open alerts");

    $(".summary-card").eq(2).find(".summary-title").text("Affected");
    $(".summary-card").eq(2).find(".summary-hint").text("Current impact");

    $(".summary-card").eq(3).find(".summary-title").text("Critical open");
    $(".summary-card").eq(3).find(".summary-hint").text(
        "Last " + Number(windowInfo.days || $("#service-analytics-days").val() || 30) + " days"
    );
}
function getFilteredServiceAnalytics() {
    const query = String($("#service-analytics-search").val() || "").trim().toLowerCase();

    if (!query) {
        return serviceAnalyticsCache;
    }

    return serviceAnalyticsCache.filter(function (row) {
        const alertGroups = row.alert_groups || {};
        const noise = row.noise || {};
        const response = row.response || {};
        const maintenance = row.maintenance || {};
        const impact = row.impact || {};

        return [
            row.service_name,
            row.service_slug,
            row.team_name,
            row.team_slug,
            row.service_status,
            row.service_criticality,
            row.service_environment,
            row.service_tier,
            impact.effective_status,
            impact.primary_reason,
            alertGroups.total,
            alertGroups.open,
            alertGroups.critical_open,
            noise.raw_alerts,
            noise.dedup_ratio,
            response.mtta_seconds_avg,
            response.mttr_seconds_avg,
            maintenance.suppressed_alert_groups,
        ].join(" ").toLowerCase().indexOf(query) !== -1;
    });
}


function renderServiceAnalyticsTable() {
    const tbody = $("#service-analytics-table");
    const rows = getFilteredServiceAnalytics();

    tbody.empty();

    if (!rows.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>")
                    .attr("colspan", 11)
                    .addClass("empty-cell")
                    .text("No analytics")
            )
        );
        return;
    }

    rows.forEach(function (row) {
        tbody.append(renderServiceAnalyticsRow(row));
    });
}


function renderServiceAnalyticsRow(row) {
    const alertGroups = row.alert_groups || {};
    const noise = row.noise || {};
    const response = row.response || {};
    const maintenance = row.maintenance || {};
    const impact = row.impact || {};
    const blastRadius = impact.blast_radius || {};

    return $("<tr>")
        .append(
            $("<td>")
                .addClass("table-cell-truncate")
                .attr("title", row.service_name || row.service_slug || "-")
                .append(
                    $("<button>")
                        .attr("type", "button")
                        .addClass("name-button")
                        .text(row.service_name || row.service_slug || "-")
                        .on("click", function () {
                            openServiceDetailsModal(row.service_id);
                        })
                )
                .append(
                    $("<div>")
                        .addClass("row-subtitle")
                        .text(row.service_environment || row.service_tier || "")
                )
        )
        .append($("<td>").text(row.team_slug || row.team_name || "-"))
        .append($("<td>").append(renderImpactStatusBadge(impact.effective_status || row.service_status)))
        .append($("<td>").text(formatImpactReasonText(impact.primary_reason || "-")))
        .append($("<td>").text(Number(alertGroups.open || 0)))
        .append($("<td>").text(Number(alertGroups.critical_open || 0)))
        .append($("<td>").text(Number(noise.raw_alerts || 0)))
        .append($("<td>").text(formatAnalyticsRatio(noise.dedup_ratio)))
        .append($("<td>").text(formatAnalyticsDuration(response.mtta_seconds_avg)))
        .append($("<td>").text(formatAnalyticsDuration(response.mttr_seconds_avg)))
        .append(
            $("<td>")
                .addClass("table-cell-truncate-wide")
                .attr("title", getAnalyticsMaintenanceAndBlastLabel(maintenance, blastRadius))
                .text(getAnalyticsMaintenanceAndBlastLabel(maintenance, blastRadius))
        );
}

function refreshServiceSloAnalytics() {
    ensureServiceSloAnalyticsPanel();
    renderServiceSloAnalyticsLoading();

    const separator = selectedTeamQuery() ? "&" : "?";
    const url = "/api/services/sli-slo/analytics" + selectedTeamQuery()
        + separator
        + "include_disabled=0";

    apiGet(url, function (payload) {
        serviceSloAnalyticsPayload = payload || {};
        serviceSloAnalyticsCache = asArray(serviceSloAnalyticsPayload.items);
        renderServiceSloAnalytics();
    });
}


function ensureServiceSloAnalyticsPanel() {
    if ($("#service-slo-analytics-panel").length) {
        return;
    }

    const reliabilityContent = $("#service-reliability-content");

    if (!reliabilityContent.length) {
        return;
    }

    reliabilityContent.append(
        $("<div>")
            .attr("id", "service-slo-analytics-panel")
            .append(
                $("<div>")
                    .addClass("card-header")
                    .append(
                        $("<div>")
                            .append($("<h2>").text("SLI / SLO health"))
                            .append(
                                $("<div>")
                                    .addClass("card-subtitle")
                                    .text("Latest SLO measurements for services in the selected scope.")
                            )
                    )
            )
            .append(
                $("<div>")
                    .addClass("table-wrapper")
                    .append(
                        $("<table>")
                            .addClass("data-table")
                            .append(
                                $("<thead>").append(
                                    $("<tr>")
                                        .append($("<th>").text("Total SLOs"))
                                        .append($("<th>").text("Met"))
                                        .append($("<th>").text("At risk"))
                                        .append($("<th>").text("Breached"))
                                        .append($("<th>").text("No data"))
                                        .append($("<th>").text("Services"))
                                )
                            )
                            .append($("<tbody>").attr("id", "service-slo-analytics-summary"))
                    )
            )
            .append(
                $("<div>")
                    .addClass("table-wrapper")
                    .append(
                        $("<table>")
                            .addClass("data-table sortable-table")
                            .append(
                                $("<thead>").append(
                                    $("<tr>")
                                        .append($("<th>").text("Service"))
                                        .append($("<th>").text("SLI"))
                                        .append($("<th>").text("SLO"))
                                        .append($("<th>").text("Current"))
                                        .append($("<th>").text("Target"))
                                        .append($("<th>").text("Status"))
                                        .append($("<th>").text("Window"))
                                        .append($("<th>").text("Budget"))
                                )
                            )
                            .append($("<tbody>").attr("id", "service-slo-analytics-table"))
                    )
            )
    );
}


function renderServiceSloAnalyticsLoading() {
    ensureServiceSloAnalyticsPanel();

    $("#service-slo-analytics-summary").html(
        $("<tr>").append(
            $("<td>")
                .attr("colspan", 6)
                .addClass("empty-cell")
                .text("Loading SLO health...")
        )
    );
    $("#service-slo-analytics-table").html(
        $("<tr>").append(
            $("<td>")
                .attr("colspan", 8)
                .addClass("empty-cell")
                .text("Loading SLO measurements...")
        )
    );
}


function renderServiceSloAnalytics() {
    ensureServiceSloAnalyticsPanel();
    renderServiceSloAnalyticsSummary();
    renderServiceSloAnalyticsTable();
}


function renderServiceSloAnalyticsSummary() {
    const summary = serviceSloAnalyticsPayload ? (serviceSloAnalyticsPayload.summary || {}) : {};
    const tbody = $("#service-slo-analytics-summary");

    if (!tbody.length) {
        return;
    }

    tbody.empty();
    tbody.append(
        $("<tr>")
            .append($("<td>").text(Number(summary.total || 0)))
            .append($("<td>").append(renderServiceSloStatusBadge("met", true)).append(" ").append(String(Number(summary.met || 0))))
            .append($("<td>").append(renderServiceSloStatusBadge("at_risk", true)).append(" ").append(String(Number(summary.at_risk || 0))))
            .append($("<td>").append(renderServiceSloStatusBadge("breached", true)).append(" ").append(String(Number(summary.breached || 0))))
            .append($("<td>").append(renderServiceSloStatusBadge("no_data", true)).append(" ").append(String(Number(summary.no_data || 0))))
            .append($("<td>").text(Number(summary.services || 0)))
    );
}


function getFilteredServiceSloAnalytics() {
    const query = String($("#service-reliability-search").val() || "").trim().toLowerCase();

    if (!query) {
        return serviceSloAnalyticsCache;
    }

    return serviceSloAnalyticsCache.filter(function (row) {
        const evaluation = row.evaluation || {};

        return [
            row.service_name,
            row.service_slug,
            row.team_name,
            row.team_slug,
            row.sli_name,
            row.sli_slug,
            row.sli_type,
            row.sli_source,
            row.sli_severity,
            row.sli_priority,
            row.slo_name,
            row.status,
            evaluation.message,
        ].join(" ").toLowerCase().indexOf(query) !== -1;
    });
}


function renderServiceSloAnalyticsTable() {
    const tbody = $("#service-slo-analytics-table");
    const rows = getFilteredServiceSloAnalytics();

    if (!tbody.length) {
        return;
    }

    tbody.empty();

    if (!rows.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>")
                    .attr("colspan", 8)
                    .addClass("empty-cell")
                    .text("No SLO measurements")
            )
        );
        return;
    }

    rows.forEach(function (row) {
        tbody.append(renderServiceSloAnalyticsRow(row));
    });
}


function renderServiceSloAnalyticsRow(row) {
    const evaluation = row.evaluation || {};

    return $("<tr>")
        .toggleClass("row-disabled", !row.enabled)
        .append(
            $("<td>")
                .addClass("table-cell-truncate")
                .attr("title", row.service_name || row.service_slug || "-")
                .append(
                    $("<button>")
                        .attr("type", "button")
                        .addClass("name-button")
                        .text(row.service_name || row.service_slug || "-")
                        .on("click", function () {
                            openServiceDetailsModal(row.service_id);
                        })
                )
                .append(
                    $("<div>")
                        .addClass("row-subtitle")
                        .text(row.team_slug || row.team_name || "-")
                )
        )
        .append(
            $("<td>")
                .addClass("table-cell-truncate")
                .append($("<strong>").text(row.sli_name || row.sli_slug || "-"))
                .append(
                    $("<div>")
                        .addClass("row-subtitle")
                        .text(formatServiceSliType(row.sli_type) + " / " + formatServiceSliSource(row.sli_source))
                )
        )
        .append(
            $("<td>")
                .addClass("table-cell-truncate-wide")
                .append($("<strong>").text(row.slo_name || "-"))
                .append(
                    $("<div>")
                        .addClass("row-subtitle")
                        .text(formatServiceSliAnalyticsScope(row))
                )
        )
        .append($("<td>").append(renderServiceSloAnalyticsCurrent(evaluation, row.sli_type)))
        .append($("<td>").append(renderServiceSloAnalyticsTarget(row)))
        .append($("<td>").append(renderServiceSloStatusBadge(row.status, row.enabled)))
        .append($("<td>").text(Number(row.window_days || 0) + "d"))
        .append($("<td>").append(renderServiceSloAnalyticsBudget(evaluation)));
}


function renderServiceSloAnalyticsCurrent(evaluation, sliType) {
    if (sliType === "incident_availability") {
        return renderServiceSloAvailabilityCurrent(evaluation);
    }

    if (sliType === "incident_count") {
        return renderServiceSloIncidentCountCurrent(evaluation);
    }

    return renderServiceSloCurrent(evaluation, sliType);
}


function renderServiceSloAnalyticsTarget(row) {
    const wrapper = $("<div>").addClass("compact-list");

    if (row.target_percent_basis_points !== null && row.target_percent_basis_points !== undefined) {
        wrapper.append($("<div>").addClass("compact-list-item").text("≥ " + formatBasisPoints(row.target_percent_basis_points)));
    }

    if (row.threshold_seconds) {
        wrapper.append($("<div>").addClass("compact-list-item").text("≤ " + formatDurationSeconds(row.threshold_seconds)));
    }

    if (row.threshold_count !== null && row.threshold_count !== undefined) {
        wrapper.append($("<div>").addClass("compact-list-item").text("≤ " + row.threshold_count + " incidents"));
    }

    if (!wrapper.children().length) {
        wrapper.text("-");
    }

    return wrapper;
}


function renderServiceSloAnalyticsBudget(evaluation) {
    const wrapper = $("<div>").addClass("compact-list");

    if (evaluation.budget_seconds === null || evaluation.budget_seconds === undefined) {
        return $("<span>").text("-");
    }

    wrapper.append(
        $("<div>")
            .addClass("compact-list-item")
            .text(
                "Budget used: " +
                formatDurationSeconds(evaluation.budget_consumed_seconds || 0, {maxParts: 3}) +
                " of " +
                formatDurationSeconds(evaluation.budget_seconds || 0, {maxParts: 3})
            )
    );

    if (evaluation.budget_remaining_seconds !== null && evaluation.budget_remaining_seconds !== undefined) {
        const remaining = Number(evaluation.budget_remaining_seconds || 0);
        const remainingText = remaining >= 0
            ? "remaining " + formatDurationSeconds(remaining)
            : "over budget by " + formatDurationSeconds(Math.abs(remaining));

        wrapper.append(
            $("<div>")
                .addClass("compact-list-meta")
                .text(remainingText)
        );
    }

    return wrapper;
}


function formatServiceSliAnalyticsScope(row) {
    const parts = [];

    if (row.sli_severity) {
        parts.push("severity: " + row.sli_severity);
    }

    if (row.sli_priority) {
        parts.push("priority: " + row.sli_priority);
    }

    if (row.exclude_maintenance) {
        parts.push("maintenance excluded");
    }

    return parts.length ? parts.join(" / ") : "all matching alert groups";
}


function formatAnalyticsRatio(value) {
    const number = Number(value || 0);

    if (!number) {
        return "0";
    }

    return number.toFixed(2);
}


function formatAnalyticsDuration(seconds) {
    if (seconds === undefined || seconds === null || seconds === "") {
        return "-";
    }

    seconds = Number(seconds || 0);

    if (seconds < 60) {
        return seconds + "s";
    }

    if (seconds < 3600) {
        return Math.round(seconds / 60) + "m";
    }

    return Math.round(seconds / 3600) + "h";
}


function getAnalyticsMaintenanceAndBlastLabel(maintenance, blastRadius) {
    maintenance = maintenance || {};
    blastRadius = blastRadius || {};

    return [
        "suppressed " + Number(maintenance.suppressed_alert_groups || 0),
        "windows " + Number(maintenance.windows || 0),
        "blast " + Number(blastRadius.transitive_downstream || 0),
    ].join(" / ");
}
$(document).on("input", "#service-analytics-search", function () {
    renderServiceAnalyticsTable();
});

$(document).on("input", "#service-reliability-search", function () {
    renderServiceSloAnalyticsTable();
});
$(document).on("change", "#service-analytics-days", function () {
    invalidateServiceDetailsCache();
    refreshServiceAnalytics();
    refreshSelectedServiceDetails();
});
$(document).on("click", "#reload-service-reliability", refreshServiceSloAnalytics);
