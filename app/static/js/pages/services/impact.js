// Service impact current/history views and impact rendering helpers.

function buildServiceImpactQuery() {
    const existingQuery = selectedTeamQuery();
    const params = new URLSearchParams(
        existingQuery ? existingQuery.replace(/^\?/, "") : ""
    );

    params.set("include_operational", "true");
    params.set("include_explanation", "true");
    params.set("include_root_causes", "true");
    params.set("include_blast_radius", "true");
    params.set("include_paths", "true");
    params.set("max_depth", "5");
    params.set("sort", "effective_status");
    params.set("order", "desc");

    return params.toString() ? "?" + params.toString() : "";
}


function updateServiceImpactTabCount(summary) {
    summary = summary || {};

    const affected = Number(
        summary.affected !== undefined
            ? summary.affected
            : serviceImpactCache.filter(isImpactItemAffected).length
    );

    $("#services-impact-count").text(affected);
}

function refreshServiceImpact(options) {
    options = options || {};

    apiGet("/api/services/impact" + buildServiceImpactQuery(), function (payload) {
        serviceImpactPayload = payload || {};
        serviceImpactCache = asArray(serviceImpactPayload.items);

        updateServiceImpactTabCount(serviceImpactPayload.summary || {});

        if (typeof scheduleRenderServiceDependencyGraph === "function") {
            scheduleRenderServiceDependencyGraph(100);
        }

        if (servicesPageTab === "impact" && serviceImpactView === "current") {
            renderImpactSummary(serviceImpactPayload.summary || {});
            renderServiceImpactTable();
        }

        if (options.refreshDetails !== false) {
            refreshSelectedServiceDetails();
        }
    });
}


function applyServiceImpactView(view) {
    serviceImpactView = view === "history" ? "history" : "current";

    $(".service-impact-view-tab").removeClass("is-active");
    $('.service-impact-view-tab[data-service-impact-view="' + serviceImpactView + '"]')
        .addClass("is-active");

    const isCurrentView = serviceImpactView === "current";
    const isHistoryView = serviceImpactView === "history";

    $("#service-impact-current-view").toggle(isCurrentView);
    $("#service-impact-history-view").toggle(isHistoryView);

    if (servicesPageTab !== "impact") {
        return;
    }

    if (isCurrentView) {
        renderImpactSummary(serviceImpactPayload ? (serviceImpactPayload.summary || {}) : {});
        renderServiceImpactTable();
        return;
    }

    if (serviceImpactHistoryPayload) {
        renderServiceImpactHistorySummary();
        renderServiceImpactHistoryCharts();
        renderServiceImpactHistoryTable();
        return;
    }

    refreshServiceImpactHistory();
}


function buildServiceImpactHistoryQuery() {
    const existingQuery = selectedTeamQuery();
    const params = new URLSearchParams(
        existingQuery ? existingQuery.replace(/^\?/, "") : ""
    );

    params.set("days", String(Number($("#service-impact-history-days").val() || 30)));
    params.set("bucket", Number($("#service-impact-history-days").val() || 30) <= 7 ? "hour" : "day");
    params.set("limit", "25");

    return params.toString() ? "?" + params.toString() : "";
}


function refreshServiceImpactHistory() {
    if (servicesPageTab !== "impact" || serviceImpactView !== "history") {
        return;
    }

    apiGet("/api/services/impact/history" + buildServiceImpactHistoryQuery(), function (payload) {
        serviceImpactHistoryPayload = payload || {};
        serviceImpactHistoryCache = asArray(serviceImpactHistoryPayload.top_services);

        renderServiceImpactHistorySummary();
        renderServiceImpactHistoryCharts();
        renderServiceImpactHistoryTable();
    });
}


function invalidateServiceImpactHistory() {
    serviceImpactHistoryPayload = null;
    serviceImpactHistoryCache = [];
}


function captureServiceImpactSnapshot() {
    const params = new URLSearchParams(
        selectedTeamQuery() ? selectedTeamQuery().replace(/^\?/, "") : ""
    );

    const payload = {
        include_disabled: false,
        include_operational: true,
        include_explanation: true,
        include_root_causes: true,
        include_blast_radius: true,
        include_paths: true,
        max_depth: 5,
    };

    if (params.get("team_id")) {
        payload.team_id = Number(params.get("team_id"));
    }

    if (params.get("service_id")) {
        payload.service_id = Number(params.get("service_id"));
    }

    apiPost("/api/services/impact/snapshots", payload, function () {
        if (typeof showToast === "function") {
            showToast("Impact snapshot captured", "success");
        }

        refreshServiceImpactHistory();
    });
}


function renderServiceImpactHistorySummary() {
    const summary = serviceImpactHistoryPayload ? (serviceImpactHistoryPayload.summary || {}) : {};
    const latestAt = summary.latest_snapshot_at ? formatDateTimeMinutes(summary.latest_snapshot_at) : "no snapshots";

    $("#services-summary-total").text(Number(summary.snapshots || 0));
    $("#services-summary-operational").text(Number(summary.latest_affected_services || 0));
    $("#services-summary-degraded").text(Number(summary.max_affected_services || 0));
    $("#services-summary-critical").text(Number(summary.max_critical_services || 0));

    $(".summary-card").eq(0).find(".summary-title").text("Snapshots");
    $(".summary-card").eq(0).find(".summary-hint").text("Historical impact");

    $(".summary-card").eq(1).find(".summary-title").text("Latest affected");
    $(".summary-card").eq(1).find(".summary-hint").text(latestAt);

    $(".summary-card").eq(2).find(".summary-title").text("Peak affected");
    $(".summary-card").eq(2).find(".summary-hint").text("selected window");

    $(".summary-card").eq(3).find(".summary-title").text("Peak critical");
    $(".summary-card").eq(3).find(".summary-hint").text("major outages");
}


function renderServiceImpactHistoryCharts() {
    if (!window.Chart) {
        $("#service-impact-history-panel .analytics-chart-grid").hide();
        return;
    }

    $("#service-impact-history-panel .analytics-chart-grid").show();

    const payload = serviceImpactHistoryPayload || {};
    const series = payload.series || {};
    const impactRows = asArray(series.impact_by_bucket);
    const reasonRows = asArray(series.reason_by_bucket);

    renderAnalyticsChart(
        "impactHistoryAffected",
        "#service-impact-history-affected-chart",
        {
            type: "line",
            labels: impactRows.map(function (row) {
                return formatAnalyticsBucketLabel(row.bucket);
            }),
            datasets: [
                {
                    label: "Avg affected",
                    data: impactRows.map(function (row) {
                        return Number(row.affected_avg || 0);
                    }),
                    tension: 0.3,
                },
                {
                    label: "Peak affected",
                    data: impactRows.map(function (row) {
                        return Number(row.affected_max || 0);
                    }),
                    tension: 0.3,
                },
                {
                    label: "Peak critical",
                    data: impactRows.map(function (row) {
                        return Number(row.critical_max || 0);
                    }),
                    tension: 0.3,
                },
            ],
        }
    );

    renderAnalyticsChart(
        "impactHistoryReasons",
        "#service-impact-history-reasons-chart",
        {
            type: "bar",
            labels: reasonRows.map(function (row) {
                return formatAnalyticsBucketLabel(row.bucket);
            }),
            datasets: [
                {
                    label: "Alert groups",
                    data: reasonRows.map(function (row) {
                        return Number(row.alert_group || 0);
                    }),
                },
                {
                    label: "Upstream dependency",
                    data: reasonRows.map(function (row) {
                        return Number(row.upstream_dependency || 0);
                    }),
                },
                {
                    label: "Own status",
                    data: reasonRows.map(function (row) {
                        return Number(row.own_status || 0);
                    }),
                },
            ],
        }
    );
}


function renderServiceImpactHistoryTable() {
    const tbody = $("#service-impact-history-table");
    const rows = serviceImpactHistoryCache;

    tbody.empty();

    if (!rows.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>")
                    .attr("colspan", 9)
                    .addClass("empty-cell")
                    .text("No historical impact snapshots. Use Capture snapshot or wait for the scheduler.")
            )
        );
        return;
    }

    rows.forEach(function (row) {
        tbody.append(renderServiceImpactHistoryRow(row));
    });
}


function renderServiceImpactHistoryRow(row) {
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
                            openServiceFromImpact(row.service_id);
                        })
                )
                .append(
                    $("<div>")
                        .addClass("row-subtitle")
                        .text("samples " + Number(row.samples || 0))
                )
        )
        .append($("<td>").text(row.team_name || row.team_slug || "-"))
        .append($("<td>").text(Number(row.affected_samples || 0)))
        .append($("<td>").text(Number(row.affected_percent || 0).toFixed(1) + "%"))
        .append($("<td>").append(renderImpactStatusBadge(row.worst_effective_status || "unknown")))
        .append($("<td>").append(renderImpactStatusBadge(row.last_effective_status || "unknown")))
        .append($("<td>").text(Number(row.max_open_alert_groups || 0)))
        .append($("<td>").text(Number(row.max_upstream_issues || 0)))
        .append($("<td>").text(formatDateTimeMinutes(row.last_affected_at) || "-"));
}


function renderImpactSummary(summary) {
    summary = summary || {};

    const byStatus = summary.by_effective_status || {};
    const total = Number(
        summary.total !== undefined
            ? summary.total
            : serviceImpactCache.length
    );
    const affected = Number(
        summary.affected !== undefined
            ? summary.affected
            : serviceImpactCache.filter(isImpactItemAffected).length
    );
    const operational = Number(
        byStatus.operational !== undefined
            ? byStatus.operational
            : serviceImpactCache.filter(function (row) {
                return row.effective_status === "operational";
            }).length
    );
    const major = Number(
        byStatus.major_outage !== undefined
            ? byStatus.major_outage
            : serviceImpactCache.filter(function (row) {
                return row.effective_status === "major_outage";
            }).length
    );
    const cycleCount = Number(summary.cycle_detected || 0);
    const depthCount = Number(summary.depth_limited || 0);

    updateServiceImpactTabCount(summary);

    renderServiceSummaryTiles({
        total: total,
        operational: operational,
        affected: affected,
        major: major,
        totalHint: "services in impact scope",
        operationalHint: "effective status",
        affectedHint: "not operational",
        majorHint: "cycles/depth " + cycleCount + "/" + depthCount,
    });
}


function getFilteredServiceImpact() {
    const query = String($("#service-impact-search").val() || "").trim().toLowerCase();
    const effectiveStatus = String($("#service-impact-effective-filter").val() || "");
    const reason = String($("#service-impact-reason-filter").val() || "");
    const includeOperational = $("#service-impact-include-operational").length
        ? $("#service-impact-include-operational").is(":checked")
        : true;

    return serviceImpactCache.filter(function (row) {
        if (!includeOperational && !isImpactItemAffected(row)) {
            return false;
        }

        if (effectiveStatus && row.effective_status !== effectiveStatus) {
            return false;
        }

        if (reason && row.primary_reason !== reason) {
            return false;
        }

        if (!query) {
            return true;
        }

        return getImpactSearchText(row).indexOf(query) !== -1;
    });
}


function getImpactSearchText(row) {
    return [
        row.service_name,
        row.service_slug,
        row.team_name,
        row.team_slug,
        row.own_status,
        row.alert_impact_status,
        row.dependency_impact_status,
        row.effective_status,
        row.primary_reason,
        row.criticality,
        row.tier,
        getImpactRootCausesLabel(row),
        getImpactPathsLabel(row),
        getImpactBlastRadiusLabel(row),
        row.explanation ? row.explanation.title : "",
        row.explanation ? row.explanation.message : "",
    ].join(" ").toLowerCase();
}


function isImpactItemAffected(row) {
    return row &&
        row.effective_status &&
        row.effective_status !== "operational" &&
        row.effective_status !== "disabled";
}


function renderServiceImpactTable() {
    const tbody = $("#service-impact-table");
    const rows = getFilteredServiceImpact();

    tbody.empty();

    if (!rows.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>")
                    .attr("colspan", 8)
                    .addClass("empty-cell")
                    .text("No impact data")
            )
        );
        return;
    }

    rows.forEach(function (row) {
        tbody.append(renderServiceImpactRow(row));
    });
}


function renderServiceImpactRow(row) {
    return $("<tr>")
        .toggleClass("row-disabled", row.effective_status === "disabled")
        .append(renderImpactServiceCell(row))
        .append($("<td>").append(renderImpactReasonCell(row)))
        .append($("<td>").append(renderImpactStatusStack(row.own_status, row.service_status_message)))
        .append($("<td>").append(renderImpactAlertCell(row)))
        .append($("<td>").append(renderImpactDependencyCell(row)))
        .append($("<td>").append(renderImpactStatusBadge(row.effective_status)))
        .append(
            $("<td>")
                .addClass("table-cell-truncate-wide impact-explanation-td")
                .attr("title", getImpactExplanationTitle(row))
                .append(renderImpactExplanationPanel(row, { compact: true }))
        )
        .append($("<td>").append(renderImpactBlastRadiusPanel(row, { compact: true })));
}


function renderImpactServiceCell(row) {
    return $("<td>")
        .addClass("table-cell-truncate")
        .attr("title", getImpactServiceDisplayName(row))
        .append(
            $("<button>")
                .attr("type", "button")
                .addClass("name-button")
                .text(getImpactServiceDisplayName(row))
                .on("click", function () {
                    openServiceFromImpact(row.service_id);
                })
        )
        .append(
            $("<div>")
                .addClass("row-subtitle")
                .text((row.service_slug || "-") + " / " + (row.team_name || row.team_slug || "-"))
        );
}


function renderImpactReasonCell(row) {
    const reason = row.primary_reason || "unknown";
    const rootCause = asArray(row.root_causes)[0];
    const wrapper = $("<div>").addClass("impact-reason-cell");

    wrapper.append(
        $("<span>")
            .addClass("impact-reason-pill")
            .addClass("impact-reason-" + reason)
            .text(formatImpactReasonText(reason))
    );

    if (rootCause && rootCause.service_id && Number(rootCause.service_id) !== Number(row.service_id)) {
        wrapper.append(
            $("<button>")
                .attr("type", "button")
                .addClass("impact-reason-source")
                .text(displayName(rootCause.service_name, rootCause.service_slug))
                .on("click", function () {
                    openServiceFromImpact(rootCause.service_id);
                })
        );
    }

    return wrapper;
}


function renderImpactStatusStack(status, hint) {
    return $("<div>")
        .addClass("impact-status-stack")
        .append(renderImpactStatusBadge(status))
        .append(
            hint
                ? $("<div>").addClass("impact-status-hint").text(hint)
                : null
        );
}


function renderImpactAlertCell(row) {
    const wrapper = $("<div>").addClass("impact-alert-cell");

    wrapper.append(renderImpactStatusBadge(row.alert_impact_status));

    const counters = $("<div>").addClass("impact-mini-counters");

    counters.append(
        $("<span>")
            .addClass("impact-mini-counter")
            .text("open " + Number(row.open_alert_groups || 0))
    );

    counters.append(
        $("<span>")
            .addClass("impact-mini-counter")
            .text("critical " + Number(row.critical_open_alert_groups || 0))
    );

    wrapper.append(counters);
    return wrapper;
}


function renderImpactDependencyCell(row) {
    const wrapper = $("<div>").addClass("impact-alert-cell");

    wrapper.append(renderImpactStatusBadge(row.dependency_impact_status));

    const counters = $("<div>").addClass("impact-mini-counters");

    counters.append(
        $("<span>")
            .addClass("impact-mini-counter")
            .text("upstream " + Number(row.upstream_issues_count || 0))
    );

    const rootCauses = asArray(row.root_causes).length;

    counters.append(
        $("<span>")
            .addClass("impact-mini-counter")
            .text("root " + rootCauses)
    );

    wrapper.append(counters);
    return wrapper;
}


function renderImpactExplanationPanel(row, options) {
    options = options || {};

    const explanation = row.explanation || {};
    const rootCauses = asArray(row.root_causes);
    const rules = asArray(explanation.rules);
    const paths = getImpactPaths(row);
    const wrapper = $("<div>").addClass("impact-explanation-card");

    wrapper.append(
        $("<div>")
            .addClass("impact-explanation-title")
            .text(explanation.title || getFallbackImpactExplanationTitle(row))
    );

    if (explanation.message) {
        wrapper.append(
            $("<div>")
                .addClass("impact-explanation-message")
                .text(explanation.message)
        );
    }

    if (rootCauses.length) {
        wrapper.append(renderImpactRootCauseStrip(rootCauses, options));
    }

    if (!options.compact && rules.length) {
        wrapper.append(renderImpactRuleList(rules));
    }

    if (paths.length) {
        wrapper.append(renderImpactPaths(paths, options));
    }

    const flags = renderImpactFlags(row);

    if (flags.children().length) {
        wrapper.append(flags);
    }

    return wrapper;
}


function renderImpactRootCauseStrip(rootCauses, options) {
    options = options || {};

    const limit = options.compact ? 2 : 5;
    const strip = $("<div>").addClass("impact-root-cause-strip");

    asArray(rootCauses).slice(0, limit).forEach(function (cause) {
        const label = displayName(cause.service_name, cause.service_slug);
        const chip = $("<button>")
            .attr("type", "button")
            .addClass("impact-root-cause-chip")
            .text(label + " / " + formatImpactStatusText(cause.effective_status || cause.status || "unknown"));

        if (cause.service_id) {
            chip.on("click", function () {
                openServiceFromImpact(cause.service_id);
            });
        }

        strip.append(chip);
    });

    if (rootCauses.length > limit) {
        strip.append(
            $("<span>")
                .addClass("impact-more-chip")
                .text("+" + (rootCauses.length - limit) + " more")
        );
    }

    return strip;
}


function renderImpactRuleList(rules) {
    const list = $("<ul>").addClass("impact-rule-list");

    asArray(rules).slice(0, 6).forEach(function (rule) {
        list.append(
            $("<li>")
                .addClass("impact-rule-item")
                .text(rule)
        );
    });

    return list;
}


function renderImpactPaths(paths, options) {
    options = options || {};

    const limit = options.compact ? 2 : 5;
    const wrapper = $("<div>").addClass("impact-paths-wrapper");

    wrapper.append(
        $("<div>")
            .addClass("impact-path-title")
            .text("Path")
    );

    asArray(paths).slice(0, limit).forEach(function (path) {
        wrapper.append(renderImpactPathNodes(path));
    });

    if (paths.length > limit) {
        wrapper.append(
            $("<div>")
                .addClass("impact-upstream-description")
                .text("+" + (paths.length - limit) + " more path(s)")
        );
    }

    return wrapper;
}


function renderImpactPathNodes(path) {
    const nodes = normalizeImpactPathNodes(path);
    const wrapper = $("<div>").addClass("impact-path");

    if (!nodes.length) {
        return wrapper.text("-");
    }

    nodes.forEach(function (node, index) {
        if (index > 0) {
            wrapper.append(
                $("<span>")
                    .addClass("impact-path-arrow")
                    .text("→")
            );
        }

        wrapper.append(renderImpactServiceNode(node));
    });

    return wrapper;
}


function renderImpactBlastRadiusPanel(row, options) {
    options = options || {};

    const blastRadius = row.blast_radius || {};
    const paths = asArray(blastRadius.paths);
    const wrapper = $("<div>").addClass("impact-blast-radius-cell");

    wrapper.append(
        $("<div>")
            .addClass("impact-blast-metrics")
            .append(impactBlastMetric("Direct", blastRadius.direct_downstream || 0))
            .append(impactBlastMetric("Total", blastRadius.transitive_downstream || 0))
            .append(impactBlastMetric("Critical", blastRadius.critical_downstream || 0))
            .append(impactBlastMetric("Tier 1", blastRadius.tier_1_downstream || 0))
    );

    if (paths.length) {
        wrapper.append(renderImpactDownstreamPaths(paths, options));
    } else if (!options.compact) {
        wrapper.append(
            $("<div>")
                .addClass("impact-upstream-description")
                .text("No downstream services in blast radius.")
        );
    }

    if (blastRadius.cycle_detected || blastRadius.depth_limited) {
        wrapper.append(renderImpactFlags(blastRadius));
    }

    return wrapper;
}


function impactBlastMetric(label, value) {
    return $("<div>")
        .addClass("impact-blast-metric")
        .append($("<span>").addClass("impact-blast-value").text(Number(value || 0)))
        .append($("<span>").addClass("impact-blast-label").text(label));
}


function renderImpactDownstreamPaths(paths, options) {
    options = options || {};

    const limit = options.compact ? 2 : 6;
    const list = $("<div>").addClass("impact-downstream-list");

    asArray(paths).slice(0, limit).forEach(function (path) {
        list.append(
            $("<div>")
                .addClass("impact-downstream-item")
                .append(renderImpactPathNodes(path))
        );
    });

    if (paths.length > limit) {
        list.append(
            $("<div>")
                .addClass("impact-upstream-description")
                .text("+" + (paths.length - limit) + " more downstream path(s)")
        );
    }

    return list;
}


function renderImpactFlags(row) {
    const wrapper = $("<div>").addClass("impact-issue-flags");

    if (row.cycle_detected) {
        wrapper.append(
            $("<span>")
                .addClass("impact-flag impact-flag-warning")
                .text("cycle detected")
        );
    }

    if (row.depth_limited) {
        wrapper.append(
            $("<span>")
                .addClass("impact-flag impact-flag-warning")
                .text("depth limit")
        );
    }

    return wrapper;
}


function getImpactPaths(row) {
    const explanationPaths = row.explanation ? asArray(row.explanation.paths) : [];

    if (explanationPaths.length) {
        return explanationPaths;
    }

    return asArray(row.root_causes)
        .map(function (cause) {
            return asArray(cause.path);
        })
        .filter(function (path) {
            return path.length > 0;
        });
}


function normalizeImpactPathNodes(path) {
    return asArray(path).map(function (node) {
        node = node || {};

        return {
            service_id: node.service_id,
            service_name: node.service_name,
            service_slug: node.service_slug,
            service_display: node.service_name || node.service_slug,
            team_id: node.team_id,
            team_name: node.team_name,
            team_slug: node.team_slug,
            team_display: node.team_name || node.team_slug,
            status: node.effective_status || node.status || "unknown",
            effective_status: node.effective_status || node.status || "unknown",
            dependency_id: node.dependency_id || null,
            dependency_type: node.dependency_type || null,
            criticality: node.dependency_criticality || node.criticality || null,
            dependency_criticality: node.dependency_criticality || node.criticality || null,
            cycle: !!node.cycle,
        };
    });
}


function getImpactRootCausesLabel(row) {
    const rootCauses = asArray(row.root_causes);

    if (!rootCauses.length) {
        return "-";
    }

    return rootCauses.map(function (cause) {
        return [
            displayName(cause.service_name, cause.service_slug),
            formatImpactReasonText(cause.reason || "unknown"),
            formatImpactStatusText(cause.effective_status || cause.status || "unknown"),
        ].join(" / ");
    }).join("; ");
}


function getImpactPathsLabel(row) {
    const paths = getImpactPaths(row);

    if (!paths.length) {
        return "-";
    }

    return paths.map(function (path) {
        return normalizeImpactPathNodes(path)
            .map(function (node) {
                return displayName(node.service_name, node.service_slug);
            })
            .join(" → ");
    }).join("; ");
}


function getImpactBlastRadiusLabel(row) {
    const blastRadius = row.blast_radius || {};

    return [
        "direct " + Number(blastRadius.direct_downstream || 0),
        "total " + Number(blastRadius.transitive_downstream || 0),
        "critical " + Number(blastRadius.critical_downstream || 0),
        "tier1 " + Number(blastRadius.tier_1_downstream || 0),
    ].join(" / ");
}


function getImpactExplanationTitle(row) {
    const explanation = row.explanation || {};

    return [
        explanation.title,
        explanation.message,
        getImpactRootCausesLabel(row),
        getImpactPathsLabel(row),
        getImpactBlastRadiusLabel(row),
    ].filter(Boolean).join(" / ") || "-";
}


function getFallbackImpactExplanationTitle(row) {
    if (row.primary_reason === "none") {
        return "No impact detected";
    }

    return formatImpactReasonText(row.primary_reason || "unknown");
}


function impactStatusBadgeLabel(status) {
    const normalized = status || "unknown";

    if (normalized === "operational") {
        return "Operational";
    }

    if (normalized === "maintenance") {
        return "Maintenance";
    }

    return formatImpactStatusText(normalized);
}


function renderImpactStatusBadge(status) {
    const normalized = status || "unknown";

    return uiStatusBadge(
        impactStatusBadgeLabel(normalized),
        uiStatusBadgeVariantForStatus(normalized)
    ).addClass("impact-status-pill");
}


$(document).on("input", "#service-impact-search", renderServiceImpactTable);
$(document).on("change", "#service-impact-effective-filter", renderServiceImpactTable);
$(document).on("change", "#service-impact-reason-filter", renderServiceImpactTable);
$(document).on("change", "#service-impact-include-operational", renderServiceImpactTable);
$(document).on("click", "#reload-service-impact", function () {
    if (serviceImpactView === "history") {
        invalidateServiceImpactHistory();
        refreshServiceImpactHistory();
        return;
    }

    refreshServiceImpact();
});
$(document).on("click", ".service-impact-view-tab", function () {
    applyServiceImpactView($(this).data("service-impact-view") || "current");
});
$(document).on("change", "#service-impact-history-days", function () {
    invalidateServiceImpactHistory();
    refreshServiceImpactHistory();
});
$(document).on("click", "#capture-service-impact-snapshot", captureServiceImpactSnapshot);


function displayName(name, slug, fallback) {
    const resolvedFallback = fallback === undefined ? "-" : fallback;

    if (name) {
        return name;
    }

    if (slug) {
        return slug;
    }

    return resolvedFallback;
}


function formatImpactStatusText(status) {
    return String(status || "unknown").replace(/_/g, " ");
}


function formatImpactReasonText(reason) {
    return String(reason || "unknown").replace(/_/g, " ");
}


function getImpactServiceDisplayName(row) {
    return displayName(row.service_name, row.service_slug);
}


function openServiceFromImpact(serviceId) {
    if (!serviceId) {
        return;
    }

    openServiceDetailsModal(serviceId);
}



function renderImpactServiceNode(node) {
    const label = displayName(node.service_name, node.service_slug, node.service_display || "-");
    const service = getServiceById(node.service_id);

    const element = service
        ? $("<button>")
            .attr("type", "button")
            .addClass("impact-path-node impact-path-node-link")
            .on("click", function () {
                openServiceFromImpact(node.service_id);
            })
        : $("<span>").addClass("impact-path-node");

    element
        .toggleClass("impact-path-node-cycle", !!node.cycle)
        .attr("title", [
            displayName(node.team_name, node.team_slug, node.team_display || "-"),
            node.effective_status || node.status || "unknown",
            node.dependency_type || "",
            node.dependency_criticality || node.criticality || "",
        ].filter(Boolean).join(" / "))
        .text(label);

    return element;
}
