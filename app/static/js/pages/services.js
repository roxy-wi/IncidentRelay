let servicesCache = [];
let selectedServiceDetailsId = null;
let servicesPageTab = "services";
let allServiceLinksCache = [];
let allServiceRunbooksCache = [];
let allServiceDependenciesCache = [];
let serviceAnalyticsCache = [];
let serviceImpactCache = [];
let serviceDetailsCache = {};
let serviceImpactPayload = null;
let serviceAnalyticsPayload = null;
let serviceSloAnalyticsPayload = null;
let serviceSloAnalyticsCache = [];
let serviceAnalyticsCharts = {};
let serviceRunbookMatcherPresetsCache = [];

const SERVICE_TYPE_OPTIONS = [
    ["api", "API"],
    ["web", "Web"],
    ["database", "Database"],
    ["queue", "Queue"],
    ["cache", "Cache"],
    ["worker", "Worker"],
    ["cron", "Cron"],
    ["network", "Network"],
    ["storage", "Storage"],
    ["infrastructure", "Infrastructure"],
    ["external", "External"],
    ["other", "Other"],
];

const SERVICE_ENVIRONMENT_OPTIONS = [
    ["production", "Production"],
    ["staging", "Staging"],
    ["development", "Development"],
    ["testing", "Testing"],
    ["shared", "Shared"],
];

const SERVICE_CRITICALITY_OPTIONS = [
    ["critical", "Critical"],
    ["high", "High"],
    ["medium", "Medium"],
    ["low", "Low"],
];

const SERVICE_TIER_OPTIONS = [
    ["tier_1", "Tier 1"],
    ["tier_2", "Tier 2"],
    ["tier_3", "Tier 3"],
    ["tier_4", "Tier 4"],
];

const SERVICE_KIND_OPTIONS = [
    ["technical", "Technical"],
    ["business", "Business"],
];

const SERVICE_LIFECYCLE_OPTIONS = [
    ["experimental", "Experimental"],
    ["development", "Development"],
    ["production", "Production"],
    ["deprecated", "Deprecated"],
    ["retired", "Retired"],
];

window.ServiceCatalogOptions = {
    serviceTypes: SERVICE_TYPE_OPTIONS,
    environments: SERVICE_ENVIRONMENT_OPTIONS,
    criticalities: SERVICE_CRITICALITY_OPTIONS,
    tiers: SERVICE_TIER_OPTIONS,
    kinds: SERVICE_KIND_OPTIONS,
    lifecycles: SERVICE_LIFECYCLE_OPTIONS,
};



function fillOptionSelect(selector, options, selectedValue) {
    const select = $(selector);

    if (!select.length) {
        return;
    }

    select.empty();

    options.forEach(function (option) {
        select.append(
            $("<option>")
                .val(option[0])
                .text(option[1])
        );
    });

    if (selectedValue !== undefined && selectedValue !== null) {
        select.val(String(selectedValue));
    }
}


function initializeServiceClassificationSelects() {
    fillOptionSelect("#service-type", SERVICE_TYPE_OPTIONS, "other");
    fillOptionSelect("#service-environment", SERVICE_ENVIRONMENT_OPTIONS, "production");
    fillOptionSelect("#service-criticality", SERVICE_CRITICALITY_OPTIONS, "medium");
    fillOptionSelect("#service-tier", SERVICE_TIER_OPTIONS, "tier_3");
}


function initializeServiceMatcherEditors() {
    enhanceMatcherEditor("#service-runbook-matchers", {
        label: "Additional matchers JSON",
        header: "Additional matchers",
        helpText: "Use {} when the preset alone should determine whether the runbook matches.",
        context: function () {
            const serviceId = Number($("#service-runbook-service").val()) || null;
            const service = serviceId ? getServiceById(serviceId) : null;

            return {
                scope: "service_runbook",
                teamId: service ? service.team_id : null,
                serviceId: serviceId,
                matcherPresetId: Number($("#service-runbook-matcher-preset").val()) || null,
            };
        },
    });
}

function loadServices() {
    initializeServiceClassificationSelects();
    initializeServiceMatcherEditors();
    if (window.AppSlug) {
        window.AppSlug.bind("#service-name", "#service-slug", {
            manualWhenHasValue: true,
        });
    }
    fillTeamSelect("#service-team", false, function () {
        resetServiceForm();
    });

    switchServicesPageTab(servicesPageTab || "services");
    refreshServices();
}


function refreshServices() {
    serviceDetailsCache = {};
    apiGet("/api/services" + selectedTeamQuery(), function (services) {
        servicesCache = asArray(services);
        window.servicesCache = servicesCache;

        renderServicesSummary();
        renderServicesTable();

        if (typeof window.loadServiceStandards === "function") {
            window.loadServiceStandards();
        }

        refreshAllServiceContext();
        refreshServiceImpact({ refreshDetails: false });
        refreshServiceAnalytics();
    });
}


function renderServicesSummary() {
    const total = servicesCache.length;

    const operational = servicesCache.filter(function (service) {
        return service.status === "operational" && service.enabled;
    }).length;

    const affected = servicesCache.filter(function (service) {
        if (!service.enabled || service.status === "disabled") {
            return false;
        }

        return service.status && service.status !== "operational";
    }).length;

    const major = servicesCache.filter(function (service) {
        return service.status === "major_outage";
    }).length;

    renderServiceSummaryTiles({
        total: total,
        operational: operational,
        affected: affected,
        major: major,
        totalHint: "services in current scope",
        operationalHint: "own status",
        affectedHint: "own status not operational",
        majorHint: "own status",
    });
}


function renderServiceSummaryTiles(summary) {
    summary = summary || {};

    $("#services-summary-total-title").text(summary.totalTitle || "Total");
    $("#services-summary-operational-title").text(summary.operationalTitle || "Operational");
    $("#services-summary-degraded-title").text(summary.affectedTitle || "Affected");
    $("#services-summary-critical-title").text(summary.majorTitle || "Major outage");

    $("#services-summary-total").text(summary.total === undefined ? 0 : summary.total);
    $("#services-summary-operational").text(summary.operational === undefined ? 0 : summary.operational);
    $("#services-summary-degraded").text(summary.affected === undefined ? 0 : summary.affected);
    $("#services-summary-critical").text(summary.major === undefined ? 0 : summary.major);

    $("#services-summary-total-hint").text(summary.totalHint || "services in scope");
    $("#services-summary-operational-hint").text(summary.operationalHint || "effective status");
    $("#services-summary-degraded-hint").text(summary.affectedHint || "not operational");
    $("#services-summary-critical-hint").text(summary.majorHint || "effective status");
}


function getServiceSearchText(service) {
    const readiness = service.readiness || {};
    return [
        service.id,
        service.name,
        service.slug,
        service.description,
        service.team_name,
        service.team_slug,
        service.service_type,
        service.environment,
        service.criticality,
        service.tier,
        service.status,
        service.kind,
        service.lifecycle,
        readiness.status,
        readiness.score,
        service.default_rotation_name,
        service.default_escalation_policy_name,
        service.notification_policy_name,
        service.priority_policy_name,
        service.enabled ? "enabled" : "disabled",
    ].join(" ").toLowerCase();
}


function getFilteredServices() {
    const query = String($("#services-search").val() || "").trim().toLowerCase();
    const status = String($("#services-status-filter").val() || "");
    const criticality = String($("#services-criticality-filter").val() || "");
    const readinessStatus = String($("#services-readiness-filter").val() || "");

    return servicesCache.filter(function (service) {
        if (status && service.status !== status) {
            return false;
        }

        if (criticality && service.criticality !== criticality) {
            return false;
        }

        if (readinessStatus && getServiceReadinessStatus(service) !== readinessStatus) {
            return false;
        }

        if (!query) {
            return true;
        }

        return getServiceSearchText(service).indexOf(query) !== -1;
    });
}


function renderServicesTable() {
    const tbody = $("#services-table");
    const services = getFilteredServices();

    tbody.empty();

    $("#services-filtered-count").text(services.length);
    $("#services-total-count").text(servicesCache.length);

    if (!services.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>")
                    .attr("colspan", "8")
                    .addClass("empty-cell")
                    .text("No services")
            )
        );
        return;
    }

    services.forEach(function (service) {
        tbody.append(renderServiceRow(service));
    });
}


function renderServiceRow(service) {
    const row = $("<tr>").toggleClass("row-disabled", !service.enabled);

    row.append(
        $("<td>")
            .addClass("table-cell-truncate")
            .attr("title", service.name || service.slug || "-")
            .append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("name-button")
                    .text(service.name || service.slug || "-")
                    .on("click", function () {
                        openServiceDetailsModal(service.id);
                    })
            )
            .append(
                $("<div>")
                    .addClass("row-subtitle")
                    .text(service.description || service.slug || ("Service #" + service.id))
            )
    );

    row.append(
        $("<td>")
            .addClass("table-cell-truncate")
            .attr("title", service.team_name || service.team_slug || "-")
            .text(service.team_name || service.team_slug || "-")
    );

    row.append(
        window.AppMaintenanceBadges.statusCell(
            renderServiceStatusBadge(service),
            service
        )
    );
    row.append(
        $("<td>").append(renderServiceReadinessBadge(service))
    );
    row.append($("<td>").text(service.criticality || "-"));
    row.append($("<td>").text(service.environment || "-"));

    row.append(
        $("<td>")
            .addClass("table-cell-truncate-wide")
            .attr("title", getServiceDefaultsLabel(service))
            .text(getServiceDefaultsLabel(service))
    );

    row.append(
        $("<td>")
            .addClass("actions-cell")
            .append(renderServiceActions(service))
    );

    return row;
}

function renderServiceStatusBadge(service) {
    if (!service.enabled || service.status === "disabled") {
        return renderStatusBadge(false, "Operational", "Disabled");
    }

    const status = service.status || "unknown";
    const label = status.replace(/_/g, " ");

    if (status === "operational") {
        return $("<span>").addClass("status-pill status-active").text("Operational");
    }

    if (status === "maintenance") {
        return $("<span>").addClass("status-pill status-scheduled").text("Maintenance");
    }

    if (["degraded", "partial_outage", "major_outage"].indexOf(status) !== -1) {
        return $("<span>").addClass("status-pill status-inactive").text(label);
    }

    return $("<span>").addClass("status-pill status-neutral").text(label);
}

function getServiceReadinessStatus(service) {
    if (!service.readiness) {
        return "not_evaluated";
    }

    return service.readiness.status || "not_evaluated";
}

function formatServiceReadinessStatus(status) {
    const labels = {
        ready: "Ready",
        warning: "Warning",
        not_ready: "Not ready",
        not_applicable: "Not applicable",
        not_evaluated: "Not evaluated",
    };

    return labels[status] || String(status || "Not evaluated").replace(/_/g, " ");
}

function renderServiceReadinessBadge(service) {
    const readiness = service.readiness || null;
    const status = getServiceReadinessStatus(service);
    const score = readiness && readiness.score !== undefined ? readiness.score : null;
    let label = formatServiceReadinessStatus(status);

    if (readiness && status !== "not_applicable" && readiness.score !== undefined) {
        label = readiness.score + "/100";
    }

    if (status === "ready") {
        return $("<span>").addClass("status-pill status-active").attr("title", "Ready").text(label);
    }

    if (status === "warning") {
        return $("<span>").addClass("status-pill status-scheduled").attr("title", "Warning").text(label);
    }

    if (status === "not_ready") {
        return $("<span>").addClass("status-pill status-inactive").attr("title", "Not ready").text(label);
    }

    return $("<span>").addClass("status-pill status-neutral").attr("title", formatServiceReadinessStatus(status)).text(label);
}

function getServiceDefaultsLabel(service) {
    const defaults = [];

    if (service.default_rotation_name) {
        defaults.push("Rotation: " + service.default_rotation_name);
    }

    if (service.default_escalation_policy_name) {
        defaults.push("Policy: " + service.default_escalation_policy_name);
    }

    if (service.notification_policy_name) {
        defaults.push(
            "Notifications: " + service.notification_policy_name
        );
    }
    if (service.priority_policy_name) {
        defaults.push(
            "Priority: " + service.priority_policy_name
        );
    }

    return defaults.join(" / ") || "-";
}


function renderServiceActions(service) {
    return makeActionMenu({
        object: service,
        items: [
            {
                label: "Details",
                icon: "fas fa-info-circle",
                onClick: function () {
                    openServiceDetailsModal(service.id);
                }
            },
            {
                label: "Edit",
                icon: "fas fa-edit",
                required: "write",
                denyMessage: "Team manager role is required to edit this service.",
                onClick: function () {
                    editService(service.id);
                }
            },
            {
                label: service.enabled ? "Disable" : "Enable",
                icon: service.enabled ? "fas fa-pause" : "fas fa-play",
                required: "write",
                danger: service.enabled,
                denyMessage: "Team manager role is required to enable or disable this service.",
                onClick: function () {
                    setServiceEnabled(service, !service.enabled);
                }
            },
            {
                label: "Delete",
                icon: "fas fa-trash",
                required: "delete",
                danger: true,
                denyMessage: "Delete permission is required to delete this service.",
                onClick: function () {
                    deleteService(service);
                }
            }
        ]
    });
}


function serviceDetailsItem(label, value) {
    return $("<div>")
        .addClass("details-item")
        .append($("<div>").addClass("details-label").text(label))
        .append($("<div>").addClass("details-value").text(value || "-"));
}


function isServiceDetailsModalOpen() {
    return $("#service-details-modal").is(":visible");
}


function openServiceDetailsModal(serviceId) {
    const service = getServiceById(serviceId);

    if (!service) {
        return;
    }

    selectedServiceDetailsId = service.id;
    window.selectedServiceId = selectedServiceDetailsId;

    openAppModal("#service-details-modal");
    loadServiceDetails(service.id);
}


function closeServiceDetailsModal() {
    closeAppModal("#service-details-modal");
}


function loadServiceDetails(serviceId) {
    const service = getServiceById(serviceId);

    if (!service) {
        return;
    }

    selectedServiceDetailsId = service.id;
    window.selectedServiceId = selectedServiceDetailsId;

    renderServiceDetailsLoading(service);

    const days = Number($("#service-analytics-days").val() || 30);
    const cacheKey = String(service.id) + ":" + String(days);

    if (serviceDetailsCache[cacheKey]) {
        renderServiceDetailsPayload(serviceDetailsCache[cacheKey]);
        return;
    }

    apiGet(
        "/api/services/" + encodeURIComponent(service.id) +
        "/details?days=" + encodeURIComponent(days),
        function (payload) {
            serviceDetailsCache[cacheKey] = payload;
            renderServiceDetailsPayload(payload);
        }
    );
}


function renderServiceDetails(service) {
    openServiceDetailsModal(service.id);
}


function renderServiceDetailsLoading(service) {
    const body = $("#service-details-modal-body");

    $("#service-details-modal-title").text(service.name || service.slug || "Service details");
    $("#service-details-modal-subtitle").text(
        (service.team_name || service.team_slug || "-") +
        " / " +
        (service.status || "unknown")
    );

    body.empty();
    body.append(
        $("<div>")
            .addClass("empty-state")
            .text("Loading service details for " + (service.name || service.slug || "service") + "...")
    );
}



function serviceDetailsMetric(label, value, hint) {
    const item = $("<div>").addClass("metric-card service-detail-metric");

    item.append($("<div>").addClass("metric-value").text(value === undefined || value === null ? "-" : value));
    item.append($("<div>").addClass("metric-label").text(label));

    if (hint) {
        item.append($("<div>").addClass("metric-hint").text(hint));
    }

    return item;
}


function serviceDetailsSection(title, subtitle) {
    const section = $("<section>").addClass("service-detail-section");

    section.append(
        $("<div>")
            .addClass("section-header")
            .append($("<h3>").text(title))
            .append(subtitle ? $("<p>").text(subtitle) : null)
    );

    return section;
}


function renderServiceDetailsPayload(payload) {
    const service = payload.service || {};
    const summary = payload.summary || {};
    const alerts = summary.alerts || {};
    const analytics = payload.analytics || {};
    const body = $("#service-details-modal-body");

    $("#service-details-modal-title").text(service.name || service.slug || "Service details");
    $("#service-details-modal-subtitle").text(
        (service.team_name || service.team_slug || "-") +
        " / " +
        (service.status || "unknown")
    );

    body.empty();

    body.append(renderServiceDetailsHero(payload));

    body.append(renderServiceDetailsMetrics(payload));
    body.append(renderServiceDetailsQuickActions(payload));
    body.append(renderServiceDetailsOwners(payload));
    body.append(renderServiceDetailsReadiness(payload));
    body.append(renderServiceDetailsSliSlo(payload));
    body.append(renderServiceDetailsImpact(payload));
    body.append(renderServiceDetailsMaintenance(payload));
    body.append(renderServiceDetailsRunbooks(payload));
    body.append(renderServiceDetailsLinks(payload));
    body.append(renderServiceDetailsDependencies(payload));
    body.append(renderServiceDetailsAnalytics(analytics));
    body.append(renderServiceDetailsTimeline(payload));
}

function renderServiceDetailsMetrics(payload) {
    const summary = payload.summary || {};
    const alerts = summary.alerts || {};
    const section = serviceDetailsSection("Metrics", null);

    const table = $("<table>").addClass("data-table");
    const tbody = $("<tbody>");

    tbody.append(
        $("<tr>")
            .append($("<th>").text("Open alerts"))
            .append($("<td>").text(Number(alerts.open || 0)))
            .append($("<th>").text("Critical open"))
            .append($("<td>").text(Number(alerts.critical_open || 0)))
    );

    tbody.append(
        $("<tr>")
            .append($("<th>").text("Maintenance"))
            .append($("<td>").text(Number(summary.maintenance_windows || 0)))
            .append($("<th>").text("Dependencies"))
            .append(
                $("<td>").text(
                    Number(summary.upstream_dependencies || 0) +
                    " / " +
                    Number(summary.downstream_dependencies || 0) +
                    " upstream / downstream"
                )
            )
    );

    table.append(tbody);

    section.append(
        $("<div>")
            .addClass("table-wrapper")
            .append(table)
    );

    return section;
}


function renderServiceDetailsSliSlo(payload) {
    const service = payload.service || {};
    const sliSlo = payload.sli_slo || {};
    const slis = asArray(sliSlo.slis);
    const slos = asArray(sliSlo.slos);
    const section = serviceDetailsSection(
        "SLI / SLO",
        "Indicators describe what is measured. Objectives define the target for those indicators."
    );
    const actions = $("<div>").addClass("details-actions");

    appendIconActionIfAllowed(actions, service, {
        required: "write",
        icon: "fas fa-chart-line",
        label: "Add SLI",
        onClick: function () {
            openServiceSliModal(service, null);
        },
    });

    appendIconActionIfAllowed(actions, service, {
        required: "write",
        icon: "fas fa-bullseye",
        label: "Add SLO",
        onClick: function () {
            openServiceSloModal(service, null, slis);
        },
    });

    section.append(actions);

    if (!slis.length && !slos.length) {
        section.append(
            $("<div>")
                .addClass("empty-state compact")
                .text("No SLI/SLO configured for this service.")
        );

        return section;
    }

    section.append(renderServiceSlisTable(service, slis));
    section.append(renderServiceSlosTable(service, slos, slis));

    return section;
}


function renderServiceSlisTable(service, slis) {
    if (!slis.length) {
        return serviceDetailsTableCard("SLIs", ["Name", "Type", "Source", "Scope"], [], "No SLIs configured.");
    }

    const table = $("<table>").addClass("data-table");
    const tbody = $("<tbody>");

    table.append(
        $("<thead>").append(
            $("<tr>")
                .append($("<th>").text("SLI"))
                .append($("<th>").text("Type"))
                .append($("<th>").text("Source"))
                .append($("<th>").text("Scope"))
                .append($("<th>").addClass("actions-th").text("Actions"))
        )
    );

    slis.forEach(function (sli) {
        tbody.append(
            $("<tr>").toggleClass("row-disabled", !sli.enabled)
                .append(
                    $("<td>")
                        .addClass("table-cell-truncate")
                        .append($("<strong>").text(sli.name || ("SLI #" + sli.id)))
                        .append($("<div>").addClass("row-subtitle").text(sli.slug || sli.description || "-"))
                )
                .append($("<td>").text(formatServiceSliType(sli.sli_type)))
                .append($("<td>").text(formatServiceSliSource(sli.source)))
                .append($("<td>").text(formatServiceSliScope(sli)))
                .append($("<td>").addClass("actions-cell").append(renderServiceSliActions(service, sli)))
        );
    });

    table.append(tbody);

    return $("<div>").addClass("table-wrapper").append(table);
}


function renderServiceSlosTable(service, slos, slis) {
    if (!slos.length) {
        return serviceDetailsTableCard("SLOs", ["Name", "SLI", "Target", "Current", "Status"], [], "No SLOs configured.");
    }

    const table = $("<table>").addClass("data-table");
    const tbody = $("<tbody>");

    table.append(
        $("<thead>").append(
            $("<tr>")
                .append($("<th>").text("SLO"))
                .append($("<th>").text("SLI"))
                .append($("<th>").text("Target"))
                .append($("<th>").text("Current"))
                .append($("<th>").text("Status"))
                .append($("<th>").addClass("actions-th").text("Actions"))
        )
    );

    slos.forEach(function (slo) {
        tbody.append(renderServiceSloRow(service, slo, slis));
    });

    table.append(tbody);

    return $("<div>").addClass("table-wrapper").append(table);
}


function renderServiceSloRow(service, slo, slis) {
    const evaluation = slo.evaluation || {};

    return $("<tr>").toggleClass("row-disabled", !slo.enabled)
        .append(
            $("<td>")
                .addClass("table-cell-truncate")
                .append($("<strong>").text(slo.name || ("SLO #" + slo.id)))
                .append($("<div>").addClass("row-subtitle").text((slo.window_days || 30) + " day window"))
        )
        .append($("<td>").text(slo.sli_name || formatServiceSliType(slo.sli_type)))
        .append($("<td>").append(renderServiceSloTarget(slo)))
        .append($("<td>").append(renderServiceSloCurrent(evaluation, slo.sli_type)))
        .append($("<td>").append(renderServiceSloStatusBadge(evaluation.status, slo.enabled)))
        .append($("<td>").addClass("actions-cell").append(renderServiceSloActions(service, slo, slis)));
}


function renderServiceSliActions(service, sli) {
    if (typeof window.makeActionMenu === "function") {
        return window.makeActionMenu({
            object: service,
            items: [
                {
                    label: "Edit",
                    icon: "fas fa-edit",
                    required: "write",
                    onClick: function () { openServiceSliModal(service, sli); },
                },
                {
                    label: "Delete",
                    icon: "fas fa-trash",
                    required: "write",
                    danger: true,
                    onClick: function () { deleteServiceSli(service, sli); },
                },
            ],
        });
    }

    const wrapper = $("<div>").addClass("action-buttons");
    appendIconActionIfAllowed(wrapper, service, {required: "write", icon: "fas fa-edit", label: "Edit", onClick: function () { openServiceSliModal(service, sli); }});
    appendIconActionIfAllowed(wrapper, service, {required: "write", icon: "fas fa-trash", label: "Delete", danger: true, onClick: function () { deleteServiceSli(service, sli); }});
    return wrapper;
}


function renderServiceSloActions(service, slo, slis) {
    if (typeof window.makeActionMenu === "function") {
        return window.makeActionMenu({
            object: service,
            items: [
                {
                    label: "Edit",
                    icon: "fas fa-edit",
                    required: "write",
                    onClick: function () { openServiceSloModal(service, slo, slis); },
                },
                {
                    label: "Delete",
                    icon: "fas fa-trash",
                    required: "write",
                    danger: true,
                    onClick: function () { deleteServiceSlo(service, slo); },
                },
            ],
        });
    }

    const wrapper = $("<div>").addClass("action-buttons");
    appendIconActionIfAllowed(wrapper, service, {required: "write", icon: "fas fa-edit", label: "Edit", onClick: function () { openServiceSloModal(service, slo, slis); }});
    appendIconActionIfAllowed(wrapper, service, {required: "write", icon: "fas fa-trash", label: "Delete", danger: true, onClick: function () { deleteServiceSlo(service, slo); }});
    return wrapper;
}


function renderServiceSloTarget(slo) {
    const wrapper = $("<div>").addClass("compact-list");

    if (slo.target_percent_basis_points !== null && slo.target_percent_basis_points !== undefined) {
        wrapper.append($("<div>").addClass("compact-list-item").text("Target ≥ " + formatBasisPoints(slo.target_percent_basis_points)));
    }

    if (slo.threshold_seconds) {
        wrapper.append($("<div>").addClass("compact-list-item").text("Threshold ≤ " + formatDurationSeconds(slo.threshold_seconds)));
    }

    if (slo.threshold_count !== null && slo.threshold_count !== undefined) {
        wrapper.append($("<div>").addClass("compact-list-item").text("Max incidents ≤ " + slo.threshold_count));
    }

    if (slo.exclude_maintenance) {
        wrapper.append($("<div>").addClass("compact-list-item").text("Maintenance excluded"));
    }

    if (!wrapper.children().length) {
        wrapper.text("-");
    }

    return wrapper;
}


function renderServiceSloCurrent(evaluation, sliType) {
    const wrapper = $("<div>").addClass("compact-list");

    if (sliType === "incident_availability") {
        return renderServiceSloAvailabilityCurrent(evaluation);
    }

    if (sliType === "incident_count") {
        return renderServiceSloIncidentCountCurrent(evaluation);
    }

    if (evaluation.value_percent !== null && evaluation.value_percent !== undefined) {
        wrapper.append(serviceSloMetricLine("Current compliance", evaluation.value_percent + "%"));
    }

    if (evaluation.good_count !== undefined && evaluation.total_count !== undefined && Number(evaluation.total_count || 0) > 0) {
        wrapper.append(serviceSloMetricLine("Good alert groups", Number(evaluation.good_count || 0)));
        wrapper.append(serviceSloMetricLine("Total alert groups", Number(evaluation.total_count || 0)));
    }

    if (evaluation.bad_count !== undefined && Number(evaluation.bad_count || 0) > 0) {
        wrapper.append(serviceSloMetricLine("Breached alert groups", Number(evaluation.bad_count || 0)));
    }

    if (evaluation.pending_count !== undefined && Number(evaluation.pending_count || 0) > 0) {
        wrapper.append(serviceSloMetricLine("Pending alert groups", Number(evaluation.pending_count || 0)));
    }

    if (evaluation.message) {
        wrapper.append($("<div>").addClass("compact-list-meta").text(evaluation.message));
    }

    if (!wrapper.children().length) {
        wrapper.text("No data");
    }

    return wrapper;
}


function renderServiceSloAvailabilityCurrent(evaluation) {
    const wrapper = $("<div>").addClass("compact-list");
    const goodSeconds = Number(evaluation.good_count || 0);
    const totalSeconds = Number(evaluation.total_count || 0);
    const downtimeSeconds = Number(evaluation.downtime_seconds || evaluation.bad_count || 0);

    if (evaluation.value_percent !== null && evaluation.value_percent !== undefined) {
        wrapper.append(serviceSloMetricLine("Current availability", evaluation.value_percent + "%"));
    }

    if (totalSeconds > 0) {
        wrapper.append(serviceSloMetricLine("Good time", formatDurationSeconds(goodSeconds, {maxParts: 3})));
        wrapper.append(serviceSloMetricLine("Total window", formatDurationSeconds(totalSeconds, {maxParts: 3})));
    }

    wrapper.append(serviceSloMetricLine("Downtime", formatDurationSeconds(downtimeSeconds, {maxParts: 3})));

    if (evaluation.message) {
        wrapper.append($("<div>").addClass("compact-list-meta").text(evaluation.message));
    }

    if (!wrapper.children().length) {
        wrapper.text("No data");
    }

    return wrapper;
}


function renderServiceSloIncidentCountCurrent(evaluation) {
    const wrapper = $("<div>").addClass("compact-list");

    if (evaluation.value_count !== null && evaluation.value_count !== undefined) {
        wrapper.append(serviceSloMetricLine("Impact incidents", Number(evaluation.value_count || 0)));
    } else if (evaluation.bad_count !== undefined) {
        wrapper.append(serviceSloMetricLine("Impact incidents", Number(evaluation.bad_count || 0)));
    }

    if (evaluation.total_count !== undefined && Number(evaluation.total_count || 0) > 0) {
        wrapper.append(serviceSloMetricLine("Total matching alert groups", Number(evaluation.total_count || 0)));
    }

    if (evaluation.message) {
        wrapper.append($("<div>").addClass("compact-list-meta").text(evaluation.message));
    }

    if (!wrapper.children().length) {
        wrapper.text("No data");
    }

    return wrapper;
}


function serviceSloMetricLine(label, value) {
    return $("<div>")
        .addClass("compact-list-item")
        .append($("<strong>").text(label + ": "))
        .append(document.createTextNode(value));
}


function renderServiceSloStatusBadge(status, enabled) {
    if (!enabled) {
        return $("<span>").addClass("status-pill status-neutral").text("Disabled");
    }

    if (status === "met") {
        return $("<span>").addClass("status-pill status-active").text("Met");
    }

    if (status === "at_risk") {
        return $("<span>").addClass("status-pill status-scheduled").text("At risk");
    }

    if (status === "breached") {
        return $("<span>").addClass("status-pill status-inactive").text("Breached");
    }

    return $("<span>").addClass("status-pill status-neutral").text("No data");
}


const SERVICE_SLI_IMPACT_TYPES = ["incident_availability", "incident_count"];
const SERVICE_SLI_PRIORITY_OPTIONS = [
    ["p1", "P1"],
    ["p2", "P2"],
    ["p3", "P3"],
    ["p4", "P4"],
];


function isImpactServiceSliType(type) {
    return SERVICE_SLI_IMPACT_TYPES.indexOf(type) !== -1;
}


function serviceSliPriorityScope(sli) {
    const configuration = sli && sli.configuration ? sli.configuration : {};
    let scope = configuration.priority_scope || null;

    if (!scope && sli && sli.priority) {
        scope = [sli.priority];
    }

    if (!scope && sli && isImpactServiceSliType(sli.sli_type)) {
        scope = ["p1", "p2"];
    }

    if (typeof scope === "string") {
        scope = [scope];
    }

    if (!Array.isArray(scope)) {
        return [];
    }

    return scope.map(function (value) {
        return String(value || "").toLowerCase();
    }).filter(function (value, index, values) {
        return ["p1", "p2", "p3", "p4"].indexOf(value) !== -1 && values.indexOf(value) === index;
    });
}


function formatServiceSliType(type) {
    const labels = {
        alert_ack_latency: "Ack latency",
        alert_resolve_latency: "Resolve latency",
        incident_availability: "Incident availability",
        incident_count: "Incident count",
    };

    return labels[type] || type || "-";
}


function formatServiceSliSource(source) {
    const labels = {
        incidentrelay_alert_groups: "Alert groups",
        incidentrelay_service_status: "Service status",
    };

    return labels[source] || source || "-";
}


function formatServiceSliScope(sli) {
    const parts = [];
    const priorityScope = serviceSliPriorityScope(sli);

    if (priorityScope.length) {
        parts.push("priority: " + priorityScope.map(function (value) {
            return value.toUpperCase();
        }).join(", "));
    }

    if (sli.severity) {
        parts.push("severity: " + sli.severity);
    }

    return parts.length ? parts.join(" / ") : "all matching alert groups";
}


function formatBasisPoints(value) {
    if (value === null || value === undefined) {
        return "-";
    }

    return (Number(value) / 100).toFixed(Number(value) % 100 === 0 ? 0 : 2) + "%";
}


function formatDurationSeconds(value, options) {
    options = options || {};

    const numericValue = Number(value || 0);
    let seconds = Math.floor(Math.abs(numericValue));
    const maxParts = options.maxParts || 2;
    const parts = [];
    const units = [
        ["d", 86400],
        ["h", 3600],
        ["m", 60],
        ["s", 1],
    ];

    if (!seconds) {
        return "0s";
    }

    units.forEach(function (unit) {
        const label = unit[0];
        const unitSeconds = unit[1];
        const amount = Math.floor(seconds / unitSeconds);

        if (amount > 0 && parts.length < maxParts) {
            parts.push(amount + label);
        }

        seconds %= unitSeconds;
    });

    return parts.join(" ");
}


function secondsToMinutes(value) {
    return value ? Math.round(Number(value) / 60) : "";
}


function minutesToSeconds(value) {
    const minutes = Number(value || 0);
    return minutes > 0 ? minutes * 60 : null;
}


function basisPointsToPercent(value) {
    return value !== null && value !== undefined ? Number(value) / 100 : "";
}


function percentToBasisPoints(value) {
    if (value === null || value === undefined || value === "") {
        return null;
    }

    return Math.round(Number(value) * 100);
}


function simpleSlug(value) {
    if (window.AppSlug && typeof window.AppSlug.slugify === "function") {
        return window.AppSlug.slugify(value);
    }

    return String(value || "")
        .toLowerCase()
        .trim()
        .replace(/['"`]/g, "")
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "")
        .replace(/-{2,}/g, "-");
}


function openServiceSliModal(service, sli) {
    $("#service-sli-modal").remove();
    $("body").append(renderServiceSliModal(service, sli));
    openAppModal("#service-sli-modal");

    if (!sli && window.AppSlug) {
        window.AppSlug.bind("#service-sli-name", "#service-sli-slug", {manualWhenHasValue: true});
    }
}


function renderServiceSliModal(service, sli) {
    sli = sli || {
        slug: "",
        name: "",
        description: "",
        sli_type: "alert_ack_latency",
        source: "incidentrelay_alert_groups",
        severity: "critical",
        priority: "",
        enabled: true,
    };

    return $("<div>")
        .attr("id", "service-sli-modal")
        .addClass("app-modal")
        .hide()
        .append(
            $("<div>")
                .addClass("app-modal-dialog app-modal-dialog-wide")
                .append(
                    $("<div>")
                        .addClass("app-modal-header")
                        .append(
                            $("<div>")
                                .append($("<h2>").text(sli.id ? "Edit SLI" : "New SLI"))
                                .append($("<div>").addClass("card-subtitle").text(service.name || service.slug || "Service"))
                        )
                        .append($("<button>").attr("type", "button").addClass("app-modal-close").attr("aria-label", "Close").text("×").on("click", function () { closeAppModal("#service-sli-modal"); }))
                )
                .append($("<div>").addClass("app-modal-body").append(renderServiceSliForm(service, sli)))
        );
}


function renderServiceSliForm(service, sli) {
    const body = $("<div>").addClass("form-body");

    body.append($("<input>").attr("type", "hidden").attr("id", "service-sli-service-id").val(service.id));
    body.append($("<input>").attr("type", "hidden").attr("id", "service-sli-id").val(sli.id || ""));

    body.append($("<label>").attr("for", "service-sli-name").text("SLI name"));
    body.append($("<input>").attr("id", "service-sli-name").attr("type", "text").addClass("input").attr("placeholder", "Critical alert acknowledgement latency").val(sli.name || "").on("input", function () {
        if (!$("#service-sli-slug").data("slug-manual")) {
            $("#service-sli-slug").val(simpleSlug($(this).val()));
        }
    }));

    body.append($("<label>").attr("for", "service-sli-slug").text("Slug"));
    body.append($("<input>").attr("id", "service-sli-slug").attr("type", "text").addClass("input").val(sli.slug || "").on("input", function () { $(this).data("slug-manual", true); }));

    body.append($("<label>").attr("for", "service-sli-description").text("Description"));
    body.append($("<textarea>").attr("id", "service-sli-description").attr("rows", 3).addClass("input").val(sli.description || ""));

    body.append($("<label>").attr("for", "service-sli-type").text("SLI type"));
    body.append(
        $("<select>").attr("id", "service-sli-type").addClass("input")
            .append($("<option>").val("alert_ack_latency").text("Alert acknowledgement latency"))
            .append($("<option>").val("alert_resolve_latency").text("Alert resolution latency"))
            .append($("<option>").val("incident_availability").text("Incident-based availability"))
            .append($("<option>").val("incident_count").text("Impact incident count"))
            .val(sli.sli_type || "alert_ack_latency")
            .on("change", updateServiceSliScopeVisibility)
    );

    body.append(
        $("<div>")
            .attr("id", "service-sli-severity-field")
            .append($("<label>").attr("for", "service-sli-severity").text("Severity scope"))
            .append(
                $("<select>").attr("id", "service-sli-severity").addClass("input")
                    .append($("<option>").val("").text("All severities"))
                    .append($("<option>").val("critical").text("Critical"))
                    .append($("<option>").val("high").text("High"))
                    .append($("<option>").val("warning").text("Warning"))
                    .append($("<option>").val("info").text("Info"))
                    .val(sli.severity || "")
            )
    );

    body.append(renderServiceSliPriorityScopeField(sli));

    body.append($("<label>").addClass("md-checkbox").append($("<input>").attr("id", "service-sli-enabled").attr("type", "checkbox").prop("checked", sli.enabled !== false)).append($("<span>").text("Enabled")));

    updateServiceSliScopeVisibility(body);

    body.append(
        $("<div>").addClass("form-actions")
            .append($("<button>").attr("type", "button").addClass("btn").text("Cancel").on("click", function () { closeAppModal("#service-sli-modal"); }))
            .append($("<button>").attr("type", "button").addClass("btn btn-primary").text("Save SLI").on("click", saveServiceSli))
    );

    return body;
}


function renderServiceSliPriorityScopeField(sli) {
    const wrapper = $("<div>").attr("id", "service-sli-priority-field");
    const selected = serviceSliPriorityScope(sli);

    wrapper.append($("<label>").text("Priority scope"));
    wrapper.append(
        $("<div>").addClass("form-grid-3").append(
            SERVICE_SLI_PRIORITY_OPTIONS.map(function (option) {
                return $("<label>")
                    .addClass("md-checkbox")
                    .append(
                        $("<input>")
                            .attr("type", "checkbox")
                            .attr("name", "service-sli-priority-scope")
                            .val(option[0])
                            .prop("checked", selected.indexOf(option[0]) !== -1)
                    )
                    .append($("<span>").text(option[1]));
            })
        )
    );

    wrapper.append(
        $("<div>")
            .addClass("row-subtitle")
            .text("Incident availability and incident count are calculated from impact priorities. Default: P1/P2.")
    );

    return wrapper;
}


function checkedInputValues(name) {
    return $("input[name='" + name + "']:checked").map(function () {
        return $(this).val();
    }).get();
}


function updateServiceSliScopeVisibility() {
    const type = $("#service-sli-type").val();
    const impact = isImpactServiceSliType(type);

    $("#service-sli-severity-field").toggle(!impact);
    $("#service-sli-priority-field").show();

    if (impact && !checkedInputValues("service-sli-priority-scope").length) {
        $("input[name='service-sli-priority-scope'][value='p1']").prop("checked", true);
        $("input[name='service-sli-priority-scope'][value='p2']").prop("checked", true);
    }
}


function collectServiceSliPayload() {
    const type = $("#service-sli-type").val();
    const priorityScope = checkedInputValues("service-sli-priority-scope");
    const impact = isImpactServiceSliType(type);
    const configuration = {};

    if (priorityScope.length) {
        configuration.priority_scope = priorityScope;
    } else if (impact) {
        configuration.priority_scope = ["p1", "p2"];
    }

    return {
        slug: $("#service-sli-slug").val().trim() || simpleSlug($("#service-sli-name").val()),
        name: $("#service-sli-name").val().trim(),
        description: $("#service-sli-description").val().trim() || null,
        sli_type: type,
        source: "incidentrelay_alert_groups",
        configuration: configuration,
        severity: impact ? null : ($("#service-sli-severity").val() || null),
        priority: configuration.priority_scope && configuration.priority_scope.length === 1
            ? configuration.priority_scope[0]
            : null,
        enabled: $("#service-sli-enabled").is(":checked"),
    };
}


function saveServiceSli() {
    const serviceId = Number($("#service-sli-service-id").val());
    const sliId = $("#service-sli-id").val();
    const payload = collectServiceSliPayload();

    if (!serviceId || !payload.name || !payload.slug) {
        showAppError("SLI name and slug are required.");
        return;
    }

    if (sliId) {
        apiPut("/api/services/slis/" + encodeURIComponent(sliId), payload, function () {
            closeAppModal("#service-sli-modal");
            refreshServiceContextAfterDetailsChange();
        });
        return;
    }

    apiPost("/api/services/" + encodeURIComponent(serviceId) + "/slis", payload, function () {
        closeAppModal("#service-sli-modal");
        refreshServiceContextAfterDetailsChange();
    });
}


function deleteServiceSli(service, sli) {
    showAppConfirm({
        title: "Delete this SLI?",
        message: "Delete SLI \"" + (sli.name || sli.id) + "\"? SLOs attached to it will be deleted by the database.",
        confirmText: "Delete",
        confirmClass: "btn-danger",
    }).done(function () {
        apiDelete("/api/services/slis/" + encodeURIComponent(sli.id), function () {
            refreshServiceContextAfterDetailsChange();
        });
    });
}


function openServiceSloModal(service, slo, slis) {
    slis = asArray(slis);

    if (!slis.length) {
        showAppError("Create an SLI first, then add an SLO for it.");
        return;
    }

    $("#service-slo-modal").remove();
    $("body").append(renderServiceSloModal(service, slo, slis));
    openAppModal("#service-slo-modal");
    updateServiceSloFormForSli();
}


function renderServiceSloModal(service, slo, slis) {
    slo = slo || {
        sli_id: slis[0].id,
        name: "",
        description: "",
        comparison: "percent_good_gte",
        target_percent_basis_points: 9500,
        threshold_seconds: 15 * 60,
        threshold_count: null,
        window_days: 30,
        exclude_maintenance: true,
        include_open_alerts: true,
        enabled: true,
    };

    return $("<div>")
        .attr("id", "service-slo-modal")
        .addClass("app-modal")
        .hide()
        .append(
            $("<div>")
                .addClass("app-modal-dialog app-modal-dialog-wide")
                .append(
                    $("<div>")
                        .addClass("app-modal-header")
                        .append(
                            $("<div>")
                                .append($("<h2>").text(slo.id ? "Edit SLO" : "New SLO"))
                                .append($("<div>").addClass("card-subtitle").text(service.name || service.slug || "Service"))
                        )
                        .append($("<button>").attr("type", "button").addClass("app-modal-close").attr("aria-label", "Close").text("×").on("click", function () { closeAppModal("#service-slo-modal"); }))
                )
                .append($("<div>").addClass("app-modal-body").append(renderServiceSloForm(service, slo, slis)))
        );
}


function renderServiceSloForm(service, slo, slis) {
    const body = $("<div>").addClass("form-body");

    body.append($("<input>").attr("type", "hidden").attr("id", "service-slo-service-id").val(service.id));
    body.append($("<input>").attr("type", "hidden").attr("id", "service-slo-id").val(slo.id || ""));

    body.append($("<label>").attr("for", "service-slo-sli").text("SLI"));
    const sliSelect = $("<select>").attr("id", "service-slo-sli").addClass("input").on("change", updateServiceSloFormForSli);
    slis.forEach(function (sli) {
        sliSelect.append($("<option>").val(sli.id).attr("data-sli-type", sli.sli_type).text((sli.name || sli.slug) + " · " + formatServiceSliType(sli.sli_type)));
    });
    sliSelect.val(slo.sli_id || (slis[0] && slis[0].id));
    body.append(sliSelect);

    body.append($("<label>").attr("for", "service-slo-name").text("SLO name"));
    body.append($("<input>").attr("id", "service-slo-name").attr("type", "text").addClass("input").attr("placeholder", "95% critical alerts acknowledged within 15 minutes").val(slo.name || ""));

    body.append($("<label>").attr("for", "service-slo-description").text("Description"));
    body.append($("<textarea>").attr("id", "service-slo-description").attr("rows", 3).addClass("input").val(slo.description || ""));

    body.append($("<div>").addClass("card-subtitle").text("Targets and evaluation window"));

    body.append($("<div>").addClass("form-grid-3")
        .append(renderServiceSloNumberField("service-slo-window-days", "Window, days", slo.window_days || 30, "30"))
        .append(renderServiceSloNumberField("service-slo-target-percent", "Target, %", basisPointsToPercent(slo.target_percent_basis_points), "95", "0.01"))
        .append(renderServiceSloNumberField("service-slo-threshold-minutes", "Threshold, minutes", secondsToMinutes(slo.threshold_seconds), "15"))
    );

    body.append($("<div>").addClass("form-grid-3")
        .append(renderServiceSloNumberField("service-slo-threshold-count", "Max incidents", slo.threshold_count, "3"))
        .append($("<div>").addClass("form-field").append($("<label>").text("Comparison")).append($("<input>").attr("id", "service-slo-comparison-label").addClass("input").prop("disabled", true)))
    );

    body.append($("<label>").addClass("md-checkbox").append($("<input>").attr("id", "service-slo-exclude-maintenance").attr("type", "checkbox").prop("checked", slo.exclude_maintenance !== false)).append($("<span>").text("Exclude maintenance from availability calculations")));
    body.append($("<label>").addClass("md-checkbox").append($("<input>").attr("id", "service-slo-include-open-alerts").attr("type", "checkbox").prop("checked", slo.include_open_alerts !== false)).append($("<span>").text("Track open alerts as pending/breached")));
    body.append($("<label>").addClass("md-checkbox").append($("<input>").attr("id", "service-slo-enabled").attr("type", "checkbox").prop("checked", slo.enabled !== false)).append($("<span>").text("Enabled")));

    body.append(
        $("<div>").addClass("form-actions")
            .append($("<button>").attr("type", "button").addClass("btn").text("Cancel").on("click", function () { closeAppModal("#service-slo-modal"); }))
            .append($("<button>").attr("type", "button").addClass("btn btn-primary").text("Save SLO").on("click", saveServiceSlo))
    );

    return body;
}


function renderServiceSloNumberField(id, label, value, placeholder, step) {
    return $("<div>")
        .addClass("form-field")
        .append($("<label>").attr("for", id).text(label))
        .append($("<input>").attr("id", id).attr("type", "number").attr("min", 0).attr("step", step || "1").addClass("input").attr("placeholder", placeholder || "").val(value === null || value === undefined ? "" : value));
}


function selectedServiceSloSliType() {
    return $("#service-slo-sli option:selected").attr("data-sli-type") || "alert_ack_latency";
}


function updateServiceSloFormForSli() {
    const type = selectedServiceSloSliType();
    const latency = type === "alert_ack_latency" || type === "alert_resolve_latency";
    const availability = type === "incident_availability";
    const count = type === "incident_count";

    $("#service-slo-target-percent").closest(".form-field").toggle(latency || availability);
    $("#service-slo-threshold-minutes").closest(".form-field").toggle(latency);
    $("#service-slo-threshold-count").closest(".form-field").toggle(count);
    $("#service-slo-exclude-maintenance").closest("label").toggle(availability);
    $("#service-slo-comparison-label").val(count ? "value_lte" : "percent_good_gte");
}


function collectServiceSloPayload() {
    const type = selectedServiceSloSliType();
    const count = type === "incident_count";

    return {
        sli_id: Number($("#service-slo-sli").val()),
        name: $("#service-slo-name").val().trim(),
        description: $("#service-slo-description").val().trim() || null,
        comparison: count ? "value_lte" : "percent_good_gte",
        target_percent_basis_points: count ? null : percentToBasisPoints($("#service-slo-target-percent").val()),
        threshold_seconds: (type === "alert_ack_latency" || type === "alert_resolve_latency") ? minutesToSeconds($("#service-slo-threshold-minutes").val()) : null,
        threshold_count: count ? Number($("#service-slo-threshold-count").val() || 0) : null,
        window_days: Number($("#service-slo-window-days").val() || 30),
        exclude_maintenance: $("#service-slo-exclude-maintenance").is(":checked"),
        include_open_alerts: $("#service-slo-include-open-alerts").is(":checked"),
        enabled: $("#service-slo-enabled").is(":checked"),
    };
}


function saveServiceSlo() {
    const serviceId = Number($("#service-slo-service-id").val());
    const sloId = $("#service-slo-id").val();
    const payload = collectServiceSloPayload();
    const type = selectedServiceSloSliType();

    if (!serviceId || !payload.name || !payload.sli_id) {
        showAppError("SLO name and SLI are required.");
        return;
    }

    if (type === "incident_count" && payload.threshold_count === null) {
        showAppError("Incident count SLO requires Max incidents.");
        return;
    }

    if (type !== "incident_count" && payload.target_percent_basis_points === null) {
        showAppError("SLO target percent is required.");
        return;
    }

    if ((type === "alert_ack_latency" || type === "alert_resolve_latency") && !payload.threshold_seconds) {
        showAppError("Latency SLO requires threshold minutes.");
        return;
    }

    if (sloId) {
        apiPut("/api/services/slos/" + encodeURIComponent(sloId), payload, function () {
            closeAppModal("#service-slo-modal");
            refreshServiceContextAfterDetailsChange();
        });
        return;
    }

    apiPost("/api/services/" + encodeURIComponent(serviceId) + "/slos", payload, function () {
        closeAppModal("#service-slo-modal");
        refreshServiceContextAfterDetailsChange();
    });
}


function deleteServiceSlo(service, slo) {
    showAppConfirm({
        title: "Delete this SLO?",
        message: "Delete SLO \"" + (slo.name || slo.id) + "\"?",
        confirmText: "Delete",
        confirmClass: "btn-danger",
    }).done(function () {
        apiDelete("/api/services/slos/" + encodeURIComponent(slo.id), function () {
            refreshServiceContextAfterDetailsChange();
        });
    });
}

function renderServiceDetailsImpact(payload) {
    const impact = payload.impact || {};
    const blastRadius = impact.blast_radius || {};
    const section = serviceDetailsSection(
        "Impact",
        "Effective status, root cause and downstream blast radius."
    );

    section.append(
        $("<div>")
            .addClass("grid-two")
            .append(
                serviceDetailsCompactCard("Status", [
                    ["Effective status", formatImpactStatusText(impact.effective_status || "unknown")],
                    ["Primary reason", formatImpactReasonText(impact.primary_reason || "unknown")],
                    ["Alert impact", formatImpactStatusText(impact.alert_impact_status || "operational")],
                    ["Open alert groups", Number(impact.open_alert_groups || 0)],
                    ["Critical open", Number(impact.critical_open_alert_groups || 0)],
                    ["Dependency impact", formatImpactStatusText(impact.dependency_impact_status || "operational")],
                    ["Upstream issues", Number(impact.upstream_issues_count || 0)],
                ])
            )
            .append(
                serviceDetailsCompactCard("Blast radius", [
                    ["Direct downstream", Number(blastRadius.direct_downstream || 0)],
                    ["Total downstream", Number(blastRadius.transitive_downstream || 0)],
                    ["Critical downstream", Number(blastRadius.critical_downstream || 0)],
                    ["Tier 1 downstream", Number(blastRadius.tier_1_downstream || 0)],
                    ["Cycle detected", blastRadius.cycle_detected ? "Yes" : "No"],
                    ["Depth limited", blastRadius.depth_limited ? "Yes" : "No"],
                ])
            )
    );

    section.append(renderImpactExplanationPanel(impact, { compact: true }));

    return section;
}

function renderServiceDetailsReadiness(payload) {
    const service = payload.service || {};
    const readiness = payload.readiness || {};
    const state = readiness.state || null;
    const evaluations = asArray(readiness.evaluations);
    const section = serviceDetailsSection("Readiness", null);

    const headerActions = $("<div>").addClass("details-actions");

    appendIconActionIfAllowed(headerActions, service, {
        required: "write",
        icon: "fas fa-sync",
        label: "Evaluate",
        onClick: function () {
            evaluateServiceReadiness(service);
        },
    });

    section.append(headerActions);

    if (!state) {
        section.append(
            $("<div>")
                .addClass("empty-state compact")
                .text("Readiness has not been evaluated.")
        );

        return section;
    }

    const scoreLabel = state.status !== "not_applicable" ? state.score + "/100" : "—";

    section.append(renderReadinessSummaryTable(state, scoreLabel));

    if (!evaluations.length) {
        section.append(
            $("<div>")
                .addClass("empty-state compact")
                .text("No standards apply to this service.")
        );

        return section;
    }

    section.append(renderReadinessStandardsTable(evaluations));

    return section;
}

function renderReadinessSummaryTable(state, scoreLabel) {
    const table = $("<table>").addClass("data-table");
    const tbody = $("<tbody>");

    tbody.append(
        $("<tr>")
            .append($("<th>").text("Score"))
            .append($("<td>").text(scoreLabel + " · " + formatServiceReadinessStatus(state.status)))
            .append($("<th>").text("Standards"))
            .append($("<td>").text(Number(state.standards_count || 0)))
    );

    tbody.append(
        $("<tr>")
            .append($("<th>").text("Checks"))
            .append($("<td>").text(Number(state.checks_count || 0)))
            .append($("<th>").text("Failed"))
            .append(
                $("<td>").text(
                    Number(state.failed_count || 0) +
                    " total / " +
                    Number(state.failed_required_count || 0) +
                    " required / " +
                    Number(state.failed_critical_count || 0) +
                    " critical"
                )
            )
    );

    table.append(tbody);

    return $("<div>").addClass("table-wrapper").append(table);
}


function renderReadinessStandardsTable(evaluations) {
    const table = $("<table>").addClass("data-table");
    const tbody = $("<tbody>");

    table.append(
        $("<thead>").append(
            $("<tr>")
                .append($("<th>").text("Standard"))
                .append($("<th>").text("Score"))
                .append($("<th>").text("Status"))
                .append($("<th>").text("Failed checks"))
        )
    );

    evaluations.forEach(function (evaluation) {
        const standard = evaluation.standard || {};
        const results = asArray(evaluation.results);
        const failed = results.filter(function (result) {
            return result.status !== "passed";
        });

        tbody.append(
            $("<tr>")
                .append(
                    $("<td>")
                        .addClass("table-cell-truncate-wide")
                        .append($("<strong>").text(standard.name || standard.slug || "Standard"))
                        .append($("<div>").addClass("row-subtitle").text(standard.slug || "-"))
                )
                .append($("<td>").text(evaluation.score + "/100"))
                .append($("<td>").append($("<span>").addClass(getReadinessStatusClass(evaluation.status)).text(formatServiceReadinessStatus(evaluation.status))))
                .append($("<td>").append(renderReadinessFailedChecks(failed)))
        );
    });

    table.append(tbody);

    return $("<div>").addClass("table-wrapper").append(table);
}


function renderReadinessFailedChecks(failed) {
    const wrapper = $("<div>").addClass("compact-list");

    if (!failed.length) {
        return $("<span>").text("-");
    }

    failed.slice(0, 4).forEach(function (result) {
        wrapper.append(
            $("<div>")
                .addClass("compact-list-item")
                .append(
                    $("<div>")
                        .addClass("compact-list-title")
                        .text(result.check_name || result.check_slug || result.check_type || "Check")
                )
                .append(
                    $("<div>")
                        .addClass("compact-list-meta")
                        .text((result.message || result.status || "failed") + " / " + Number(result.weight || 0) + " pt")
                )
        );
    });

    if (failed.length > 4) {
        wrapper.append(
            $("<div>")
                .addClass("compact-list-meta")
                .text("+" + (failed.length - 4) + " more")
        );
    }

    return wrapper;
}

function getReadinessStatusClass(status) {
    if (status === "ready") {
        return "status-pill status-active";
    }

    if (status === "warning") {
        return "status-pill status-scheduled";
    }

    if (status === "not_ready") {
        return "status-pill status-inactive";
    }

    return "status-pill status-neutral";
}

function evaluateServiceReadiness(service) {
    apiPost(
        "/api/services/" + encodeURIComponent(service.id) + "/readiness/evaluate",
        {},
        function () {
            serviceDetailsCache = {};
            refreshServices();

            if ($("#service-details-modal").is(":visible")) {
                loadServiceDetails(service.id);
            }
        }
    );
}


function serviceDetailsCompactRow(label, value) {
    return $("<tr>")
        .append(
            $("<td>")
                .addClass("table-cell-truncate")
                .append($("<strong>").text(label))
        )
        .append(
            $("<td>")
                .addClass("table-cell-truncate-wide")
                .attr("title", value || "-")
                .text(value || "-")
        );
}


function serviceDetailsCompactCard(title, rows) {
    const card = $("<section>").addClass("card");
    const tbody = $("<tbody>");

    rows.forEach(function (row) {
        tbody.append(serviceDetailsCompactRow(row[0], row[1]));
    });

    card.append(
        $("<div>")
            .addClass("card-header")
            .append($("<div>").append($("<h2>").text(title)))
    );

    card.append(
        $("<div>")
            .addClass("table-wrapper")
            .append(
                $("<table>")
                    .addClass("data-table")
                    .append(tbody)
            )
    );

    return card;
}




function serviceDetailsTableCell(value, wide) {
    const cell = $("<td>");

    if (wide) {
        cell.addClass("table-cell-truncate-wide");
    } else {
        cell.addClass("table-cell-truncate");
    }

    if (value && value.jquery) {
        cell.append(value);
        return cell;
    }

    cell.attr("title", value === undefined || value === null || value === "" ? "-" : String(value));
    cell.text(value === undefined || value === null || value === "" ? "-" : value);

    return cell;
}


function serviceDetailsTableCard(title, headers, rows, emptyMessage) {
    const card = $("<section>").addClass("card");
    const table = $("<table>").addClass("data-table");
    const tbody = $("<tbody>");

    card.append(
        $("<div>")
            .addClass("card-header")
            .append($("<div>").append($("<h2>").text(title)))
    );

    if (headers && headers.length) {
        table.append(
            $("<thead>").append(
                $("<tr>").append(headers.map(function (header) {
                    return $("<th>").text(header);
                }))
            )
        );
    }

    if (!rows.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>")
                    .attr("colspan", headers && headers.length ? headers.length : 1)
                    .addClass("empty-cell")
                    .text(emptyMessage || "No data")
            )
        );
    } else {
        rows.forEach(function (row) {
            const tr = $("<tr>");

            row.forEach(function (value, index) {
                tr.append(serviceDetailsTableCell(value, index === row.length - 1));
            });

            tbody.append(tr);
        });
    }

    table.append(tbody);
    card.append($("<div>").addClass("table-wrapper").append(table));

    return card;
}


function renderServiceDetailsHero(payload) {
    const service = payload.service || {};
    const section = serviceDetailsSection(
        "Overview",
        service.description || service.slug || "No description"
    );

    const badges = $("<div>").addClass("service-detail-badges");

    badges.append(renderServiceStatusBadge(service));
    badges.append(renderServiceReadinessBadge(service));
    badges.append($("<span>").addClass("status-pill status-neutral").text(service.criticality || "unknown"));
    badges.append($("<span>").addClass("status-pill status-neutral").text(service.environment || "unknown"));
    badges.append($("<span>").addClass("status-pill status-neutral").text(service.tier || "unknown"));

    section.append(badges);

    section.append(
        $("<div>")
            .addClass("grid-two")
            .append(
                serviceDetailsCompactCard("Identity", [
                    ["Team", service.team_name || service.team_slug],
                    ["Type", service.service_type],
                    ["Kind", service.kind],
                    ["Lifecycle", service.lifecycle],
                    ["Enabled", service.enabled ? "Yes" : "No"],
                    ["Status message", service.status_message],
                ])
            )
            .append(
                serviceDetailsCompactCard("Defaults", [
                    ["Default rotation", service.default_rotation_name],
                    ["Escalation policy", service.default_escalation_policy_name],
                    ["Notification policy", service.notification_policy_name],
                    ["Priority policy", service.priority_policy_name || "Team default"],
                    ["Maintenance", window.AppMaintenanceBadges.text(service, "-")],
                ])
            )
    );

    return section;
}

function renderServiceDetailsQuickActions(payload) {
    const service = payload.service || {};
    const section = serviceDetailsSection("Quick actions", null);
    const actions = $("<div>").addClass("details-actions");

    appendIconActionIfAllowed(actions, service, {
        required: "write",
        icon: "fas fa-edit",
        label: "Edit service",
        onClick: function () {
            editService(service.id);
        },
    });

    appendIconActionIfAllowed(actions, service, {
        required: "write",
        icon: "fas fa-tools",
        label: "Maintenance",
        onClick: function () {
            openServiceMaintenanceWindow(service);
        },
    });

    appendIconActionIfAllowed(actions, service, {
        required: "write",
        icon: "fas fa-book",
        label: "Runbook",
        onClick: function () {
            resetServiceRunbookForm();
            fillServiceSelect("#service-runbook-service", service.id);
            $("#service-runbook-service").prop("disabled", true);
            openAppModal("#service-runbook-modal");
        },
    });

    appendIconActionIfAllowed(actions, service, {
        required: "write",
        icon: "fas fa-link",
        label: "Link",
        onClick: function () {
            resetServiceLinkForm();
            fillServiceSelect("#service-link-service", service.id);
            $("#service-link-service").prop("disabled", true);
            openAppModal("#service-link-modal");
        },
    });

    appendIconActionIfAllowed(actions, service, {
        required: "write",
        icon: "fas fa-bullseye",
        label: "SLI",
        onClick: function () {
            openServiceSliModal(service, null);
        },
    });

    appendIconActionIfAllowed(actions, service, {
        required: "write",
        icon: "fas fa-users",
        label: "Stakeholder",
        onClick: function () {
            openCreateServiceOwnerModal(service);
        },
    });

    appendIconActionIfAllowed(actions, service, {
        required: "write",
        icon: "fas fa-project-diagram",
        label: "Dependency",
        onClick: function () {
            resetServiceDependencyForm();
            fillServiceSelect("#service-dependency-source", service.id);
            $("#service-dependency-source").prop("disabled", true);
            loadServiceDependencyTargets(function () {
                openAppModal("#service-dependency-modal");
            });
        },
    });

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn")
            .text("Alerts")
            .on("click", function () {
                openServiceAlerts(service, { onlyOpen: true });
            })
    );

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn")
            .text("Impact")
            .on("click", function () {
                switchServicesPageTab("impact");
                $("#service-impact-search").val(service.slug || service.name || "");
                renderServiceImpactTable();
            })
    );

    section.append(actions);
    return section;
}


function openServiceMaintenanceWindow(service) {
    window.location.href = "/maintenance-windows?service_id=" + encodeURIComponent(service.id);
}


function renderServiceDetailsEmpty() {
    selectedServiceDetailsId = null;
    window.selectedServiceId = null;
    $("#service-details-modal-title").text("Service details");
    $("#service-details-modal-subtitle").text("");
    $("#service-details-modal-body").html(
        $("<div>").addClass("empty-state").text("Select a service to view details.")
    );
}



function restoreServiceDetails() {
    if (!isServiceDetailsModalOpen() || !selectedServiceDetailsId) {
        return;
    }

    const selected = servicesCache.find(function (service) {
        return Number(service.id) === Number(selectedServiceDetailsId);
    });

    if (selected) {
        loadServiceDetails(selected.id);
        return;
    }

    renderServiceDetailsEmpty();
}



function getServiceById(serviceId) {
    return servicesCache.find(function (service) {
        return Number(service.id) === Number(serviceId);
    }) || null;
}


function getDefaultServiceIdForCreate() {
    if (selectedServiceDetailsId && getServiceById(selectedServiceDetailsId)) {
        return selectedServiceDetailsId;
    }

    const firstEnabled = servicesCache.find(function (service) {
        return !!service.enabled;
    });

    return firstEnabled ? firstEnabled.id : null;
}


function fillServiceSelect(selectSelector, selectedId) {
    const select = $(selectSelector);
    select.empty();

    select.append($("<option>").val("").text("Select service"));

    servicesCache.forEach(function (service) {
        if (!service.enabled) {
            return;
        }

        select.append(
            $("<option>")
                .val(String(service.id))
                .text(
                    (service.team_name || service.team_slug || "-")
                    + " / "
                    + service.name
                    + " ("
                    + service.slug
                    + ")"
                )
        );
    });

    if (selectedId) {
        select.val(String(selectedId));
    }
}


function switchServicesPageTab(tab) {
    servicesPageTab = tab || "services";

    $("#services-page-tabs .page-tab").removeClass("is-active");
    $('#services-page-tabs .page-tab[data-services-tab="' + servicesPageTab + '"]').addClass("is-active");

    $(".services-tab-panel").hide();
    $("#services-tab-" + servicesPageTab).show();

    $("#services-page-layout").addClass("is-full-width");

    if (servicesPageTab === "links") {
        renderAllServiceLinksTable();
    } else if (servicesPageTab === "runbooks") {
        renderAllServiceRunbooksTable();
    } else if (servicesPageTab === "dependencies") {
        renderAllServiceDependenciesTable();
    } else if (servicesPageTab === "impact") {
        if (!serviceImpactCache.length) {
            refreshServiceImpact();
        } else {
            renderServiceImpactTable();
        }
    } else if (servicesPageTab === "standards") {
        if (typeof window.loadServiceStandards === "function") {
            window.loadServiceStandards();
        }
    } else if (servicesPageTab === "analytics") {
        if (!serviceAnalyticsCache.length) {
            refreshServiceAnalytics();
        } else {
            renderServiceAnalyticsSummary();
            renderServiceAnalyticsCharts();
            renderServiceAnalyticsTable();
        }
    } else if (servicesPageTab === "reliability") {
        if (serviceSloAnalyticsPayload) {
            renderServiceSloAnalytics();
        } else {
            refreshServiceSloAnalytics();
        }
    }
    if (servicesPageTab === "services") {
        renderServicesSummary();
    }
}


function refreshAllServiceContext() {
    allServiceLinksCache = [];
    allServiceRunbooksCache = [];
    allServiceDependenciesCache = [];

    $("#services-links-count").text("0");
    $("#services-runbooks-count").text("0");
    $("#services-dependencies-count").text("0");

    const query = selectedTeamQuery();
    let pending = 3;

    function done() {
        pending -= 1;

        if (pending > 0) {
            return;
        }

        $("#services-links-count").text(allServiceLinksCache.length);
        $("#services-runbooks-count").text(allServiceRunbooksCache.length);
        $("#services-dependencies-count").text(allServiceDependenciesCache.length);

        renderAllServiceLinksTable();
        renderAllServiceRunbooksTable();
        renderAllServiceDependenciesTable();
    }

    apiGet("/api/services/links" + query, function (links) {
        allServiceLinksCache = asArray(links).map(function (link) {
            link._service = getServiceById(link.service_id);
            return link;
        });
        done();
    });

    apiGet("/api/services/runbooks" + query, function (runbooks) {
        allServiceRunbooksCache = asArray(runbooks).map(function (runbook) {
            runbook._service = getServiceById(runbook.service_id);
            return runbook;
        });
        done();
    });

    apiGet("/api/services/dependencies" + query, function (dependencies) {
        allServiceDependenciesCache = asArray(dependencies).map(function (dependency) {
            dependency._service = getServiceById(dependency.service_id);
            return dependency;
        });
        done();
    });
}


function loadServiceDefaults(callback) {
    const teamId = $("#service-team").val();
    const rotationSelect = $("#service-default-rotation");
    const escalationSelect = $("#service-default-policy");
    const notificationSelect = $("#service-notification-policy");
    const prioritySelect = $("#service-priority-policy");

    rotationSelect.empty().append(
        $("<option>").val("").text("No default rotation")
    );
    escalationSelect.empty().append(
        $("<option>").val("").text("No default policy")
    );
    notificationSelect.empty().append(
        $("<option>").val("").text("No notification policy")
    );
    prioritySelect.empty().append(
        $("<option>").val("").text("Use team default")
    );

    if (!teamId) {
        if (typeof callback === "function") {
            callback();
        }
        return;
    }

    let rotationsLoaded = false;
    let escalationsLoaded = false;
    let notificationsLoaded = false;
    let prioritiesLoaded = false;

    function finishWhenReady() {
        if (
            !rotationsLoaded
            || !escalationsLoaded
            || !notificationsLoaded
            || !prioritiesLoaded
        ) {
            return;
        }

        if (typeof callback === "function") {
            callback();
        }
    }

    apiGet(
        "/api/rotations?team_id=" + encodeURIComponent(teamId),
        function (rotations) {
            asArray(rotations).forEach(function (rotation) {
                if (!rotation.enabled) {
                    return;
                }

                rotationSelect.append(
                    $("<option>").val(String(rotation.id)).text(rotation.name)
                );
            });

            rotationsLoaded = true;
            finishWhenReady();
        }
    );

    apiGet(
        "/api/escalation-policies?team_id=" + encodeURIComponent(teamId),
        function (policies) {
            asArray(policies).forEach(function (policy) {
                if (!policy.enabled) {
                    return;
                }

                escalationSelect.append(
                    $("<option>").val(String(policy.id)).text(policy.name)
                );
            });

            escalationsLoaded = true;
            finishWhenReady();
        }
    );

    apiGet(
        "/api/notification-policies?team_id="
        + encodeURIComponent(teamId)
        + "&enabled_only=1",
        function (policies) {
            asArray(policies).forEach(function (policy) {
                notificationSelect.append(
                    $("<option>").val(String(policy.id)).text(policy.name)
                );
            });

            notificationsLoaded = true;
            finishWhenReady();
        }
    );
    apiGet(
        "/api/priority-policies?team_id="
        + encodeURIComponent(teamId)
        + "&enabled_only=1",
        function (policies) {
            asArray(policies).forEach(function (policy) {
                prioritySelect.append(
                    $("<option>")
                        .val(String(policy.id))
                        .text(
                            policy.name
                            + (policy.default_for_team ? " · Team default" : "")
                        )
                );
            });

            prioritiesLoaded = true;
            finishWhenReady();
        }
    );
}


function resetServiceForm() {
    $("#service-form-title").text("Create service");
    $("#service-id").val("");

    const selectedTeam = $("#global-team-filter").val();
    if (selectedTeam) {
        $("#service-team").val(selectedTeam);
    }

    $("#service-name").val("");
    $("#service-slug").val("");
    if (window.AppSlug) {
        window.AppSlug.reset("#service-slug", {manual: false});
    }
    $("#service-description").val("");
    $("#service-type").val("other");
    $("#service-environment").val("production");
    $("#service-criticality").val("medium");
    $("#service-tier").val("tier_3");
    $("#service-status").val("operational");
    $("#service-status-message").val("");
    $("#service-default-rotation").val("");
    $("#service-default-policy").val("");
    $("#service-notification-policy").val("");
    $("#service-priority-policy").val("");
    $("#service-enabled").prop("checked", true);
    $("#service-public").prop("checked", false);

    loadServiceDefaults();
}


function collectServicePayload() {
    return {
        team_id: Number($("#service-team").val()),
        name: $("#service-name").val(),
        slug: $("#service-slug").val(),
        description: $("#service-description").val() || null,
        service_type: $("#service-type").val() || "other",
        environment: $("#service-environment").val() || "production",
        criticality: $("#service-criticality").val() || "medium",
        tier: $("#service-tier").val() || "tier_3",
        status: $("#service-status").val() || "operational",
        status_source: "manual",
        status_message: $("#service-status-message").val() || null,
        default_rotation_id: $("#service-default-rotation").val()
            ? Number($("#service-default-rotation").val())
            : null,
        default_escalation_policy_id: $("#service-default-policy").val()
            ? Number($("#service-default-policy").val())
            : null,
        notification_policy_id: $("#service-notification-policy").val()
            ? Number($("#service-notification-policy").val())
            : null,
        priority_policy_id: $("#service-priority-policy").val()
            ? Number($("#service-priority-policy").val())
            : null,
        labels: {},
        tags: [],
        metadata: {},
        enabled: $("#service-enabled").is(":checked"),
        public: $("#service-public").is(":checked"),
        public_name: null,
        public_description: null,
        public_order: 100,
    };
}


function saveService() {
    const id = $("#service-id").val();
    const payload = collectServicePayload();

    if (!payload.team_id) {
        showAppError("Team is required.");
        return;
    }

    if (id) {
        apiPut("/api/services/" + id, payload, function () {
            closeAppModal("#service-form-modal");
            resetServiceForm();
            refreshServices();
        });
        return;
    }

    apiPost("/api/services", payload, function () {
        closeAppModal("#service-form-modal");
        resetServiceForm();
        refreshServices();
    });
}


function editService(id) {
    const service = getServiceById(id);

    if (!service) {
        return;
    }

    if (!canWriteObject(service)) {
        showAppError("You do not have permission to edit this service.");
        return;
    }

    $("#service-form-title").text("Edit service");
    $("#service-id").val(service.id);
    $("#service-team").val(service.team_id);

    loadServiceDefaults(function () {
        $("#service-name").val(service.name || "");
        $("#service-slug").val(service.slug || "");
        if (window.AppSlug) {
            window.AppSlug.reset("#service-slug", {manual: true});
        }
        $("#service-description").val(service.description || "");
        $("#service-type").val(service.service_type || "other");
        $("#service-environment").val(service.environment || "production");
        $("#service-criticality").val(service.criticality || "medium");
        $("#service-tier").val(service.tier || "tier_3");
        $("#service-status").val(service.status || "operational");
        $("#service-status-message").val(service.status_message || "");
        $("#service-default-rotation").val(service.default_rotation_id || "");
        $("#service-default-policy").val(service.default_escalation_policy_id || "");
        $("#service-notification-policy").val(service.notification_policy_id || "");
        $("#service-priority-policy").val(service.priority_policy_id || "");
        $("#service-enabled").prop("checked", !!service.enabled);
        $("#service-public").prop("checked", !!service.public);

        openAppModal("#service-form-modal");
    });
}

function normalizeServiceStatusForEnabledState(status, enabled) {
    status = status || "operational";

    if (!enabled) {
        return "disabled";
    }

    if (status === "disabled") {
        return "operational";
    }

    return status;
}
function setServiceEnabled(service, enabled) {
    if (!canWriteObject(service)) {
        showAppError("You do not have permission to update this service.");
        return;
    }

    const payload = {
        team_id: service.team_id,
        name: service.name,
        slug: service.slug,
        description: service.description || null,
        service_type: service.service_type || "other",
        environment: service.environment || "production",
        criticality: service.criticality || "medium",
        tier: service.tier || "tier_3",
        status: normalizeServiceStatusForEnabledState(service.status, enabled),
        status_source: service.status_source || "manual",
        status_message: service.status_message || null,
        default_rotation_id: service.default_rotation_id || null,
        default_escalation_policy_id: service.default_escalation_policy_id || null,
        notification_policy_id: service.notification_policy_id || null,
        priority_policy_id: service.priority_policy_id || null,
        labels: service.labels || {},
        tags: service.tags || [],
        metadata: service.metadata || {},
        enabled: enabled,
        public: !!service.public,
        public_name: service.public_name || null,
        public_description: service.public_description || null,
        public_order: service.public_order || 100,
    };

    apiPut("/api/services/" + service.id, payload, function () {
        refreshServices();
    });
}


function deleteService(service) {
    showAppConfirm({
        title: "Delete this service?",
        message: "Delete service \"" + (service.name || service.slug || service.id) + "\"?",
        confirmText: "Delete service",
        confirmClass: "btn-danger",
    }).done(function () {
        apiDelete("/api/services/" + service.id, function () {
            if (Number(selectedServiceDetailsId) === Number(service.id)) {
                closeServiceDetailsModal();
                renderServiceDetailsEmpty();
            }

            refreshServices();
        });
    });
}


function openCreateServiceModal() {
    resetServiceForm();
    openAppModal("#service-form-modal");
}


function getFilteredServiceLinks() {
    const query = String($("#service-links-search").val() || "").trim().toLowerCase();

    if (!query) {
        return allServiceLinksCache;
    }

    return allServiceLinksCache.filter(function (link) {
        return [
            link.label,
            link.url,
            link.description,
            link.link_type,
            link.service_name,
            link.service_slug,
            link.team_name,
            link.team_slug,
        ].join(" ").toLowerCase().indexOf(query) !== -1;
    });
}


function renderAllServiceLinksTable() {
    const tbody = $("#service-links-table");
    const links = getFilteredServiceLinks();

    tbody.empty();

    if (!links.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>").attr("colspan", 7).addClass("empty-cell").text("No links")
            )
        );
        return;
    }

    links.forEach(function (link) {
        const service = link._service || getServiceById(link.service_id);

        tbody.append(
            $("<tr>")
                .toggleClass("row-disabled", !link.enabled)
                .append(
                    $("<td>")
                        .addClass("table-cell-truncate-wide")
                        .append(
                            $("<a>")
                                .attr("href", link.url)
                                .attr("target", "_blank")
                                .attr("rel", "noopener noreferrer")
                                .text(link.label || link.url)
                        )
                        .append($("<div>").addClass("row-subtitle").text(link.url || ""))
                )
                .append($("<td>").text(link.service_name || link.service_slug || "-"))
                .append($("<td>").text(link.team_name || link.team_slug || "-"))
                .append($("<td>").text(link.link_type || "-"))
                .append($("<td>").text(link.priority || 0))
                .append($("<td>").append(renderStatusBadge(link.enabled, "Enabled", "Disabled")))
                .append($("<td>").addClass("actions-cell").append(renderServiceLinkActions(service, link)))
        );
    });
}


function getFilteredServiceRunbooks() {
    const query = String($("#service-runbooks-search").val() || "").trim().toLowerCase();

    if (!query) {
        return allServiceRunbooksCache;
    }

    return allServiceRunbooksCache.filter(function (runbook) {
        return [
            runbook.title,
            runbook.url,
            runbook.description,
            runbook.severity,
            runbook.service_name,
            runbook.service_slug,
            runbook.team_name,
            runbook.team_slug,
            runbook.matcher_preset ? runbook.matcher_preset.name : "",
        ].join(" ").toLowerCase().indexOf(query) !== -1;
    });
}


function renderAllServiceRunbooksTable() {
    const tbody = $("#service-runbooks-table");
    const runbooks = getFilteredServiceRunbooks();

    tbody.empty();

    if (!runbooks.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>").attr("colspan", 7).addClass("empty-cell").text("No runbooks")
            )
        );
        return;
    }

    runbooks.forEach(function (runbook) {
        const service = runbook._service || getServiceById(runbook.service_id);

        tbody.append(
            $("<tr>")
                .toggleClass("row-disabled", !runbook.enabled)
                .append(
                    $("<td>")
                        .addClass("table-cell-truncate-wide")
                        .append(
                            $("<a>")
                                .attr("href", runbook.url)
                                .attr("target", "_blank")
                                .attr("rel", "noopener noreferrer")
                                .text(runbook.title || runbook.url)
                        )
                        .append($("<div>").addClass("row-subtitle").text(runbook.description || runbook.url || ""))
                )
                .append($("<td>").text(runbook.service_name || runbook.service_slug || "-"))
                .append($("<td>").text(runbook.team_name || runbook.team_slug || "-"))
                .append($("<td>").text(runbook.severity || "-"))
                .append($("<td>").text(runbook.priority || 0))
                .append($("<td>").append(renderStatusBadge(runbook.enabled, "Enabled", "Disabled")))
                .append($("<td>").addClass("actions-cell").append(renderServiceRunbookActions(service, runbook)))
        );
    });
}


function getFilteredServiceDependencies() {
    const query = String($("#service-dependencies-search").val() || "").trim().toLowerCase();

    if (!query) {
        return allServiceDependenciesCache;
    }

    return allServiceDependenciesCache.filter(function (dependency) {
        return [
            dependency.service_name,
            dependency.service_slug,
            dependency.team_name,
            dependency.team_slug,
            dependency.depends_on_service_name,
            dependency.depends_on_service_slug,
            dependency.dependency_type,
            dependency.criticality,
            dependency.depends_on_service_status,
            dependency.description,
        ].join(" ").toLowerCase().indexOf(query) !== -1;
    });
}


function renderAllServiceDependenciesTable() {
    const tbody = $("#service-dependencies-table");
    const dependencies = getFilteredServiceDependencies();

    tbody.empty();

    if (!dependencies.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>").attr("colspan", 7).addClass("empty-cell").text("No dependencies")
            )
        );
        return;
    }

    dependencies.forEach(function (dependency) {
        const service = dependency._service || getServiceById(dependency.service_id);

        tbody.append(
            $("<tr>")
                .toggleClass("row-disabled", !dependency.enabled)
                .append(
                    $("<td>")
                        .addClass("table-cell-truncate")
                        .text(
                            (dependency.team_slug || dependency.team_name || "-")
                            + " / "
                            + (dependency.service_name || dependency.service_slug || "-")
                        )
                )
                .append(
                    $("<td>")
                        .addClass("table-cell-truncate")
                        .attr(
                            "title",
                            (dependency.depends_on_team_slug || dependency.depends_on_team_name || "-")
                            + " / "
                            + (dependency.depends_on_service_name || dependency.depends_on_service_slug || "-")
                        )
                        .text(
                            (dependency.depends_on_team_slug || dependency.depends_on_team_name || "-")
                            + " / "
                            + (dependency.depends_on_service_name || dependency.depends_on_service_slug || "-")
                        )
                )
                .append($("<td>").text(dependency.dependency_type || "-"))
                .append($("<td>").text(dependency.criticality || "-"))
                .append($("<td>").text(dependency.depends_on_service_status || "-"))
                .append($("<td>").addClass("table-cell-truncate-wide").text(dependency.description || "-"))
                .append($("<td>").addClass("actions-cell").append(renderServiceDependencyActions(service, dependency)))
        );
    });
}


function renderServiceLinkActions(service, link) {
    return makeActionMenu({
        object: service,
        items: [
            {
                label: "Edit",
                icon: "fas fa-edit",
                required: "write",
                onClick: function () {
                    editServiceLink(link);
                }
            },
            {
                label: "Delete",
                icon: "fas fa-trash",
                required: "write",
                danger: true,
                onClick: function () {
                    deleteServiceLink(link);
                }
            }
        ]
    });
}


function renderServiceRunbookActions(service, runbook) {
    return makeActionMenu({
        object: service,
        items: [
            {
                label: "Edit",
                icon: "fas fa-edit",
                required: "write",
                onClick: function () {
                    editServiceRunbook(runbook);
                }
            },
            {
                label: "Delete",
                icon: "fas fa-trash",
                required: "write",
                danger: true,
                onClick: function () {
                    deleteServiceRunbook(runbook);
                }
            }
        ]
    });
}


function renderServiceDependencyActions(service, dependency) {
    return makeActionMenu({
        object: service,
        items: [
            {
                label: "Edit",
                icon: "fas fa-edit",
                required: "write",
                onClick: function () {
                    editServiceDependency(dependency);
                }
            },
            {
                label: "Delete",
                icon: "fas fa-trash",
                required: "write",
                danger: true,
                onClick: function () {
                    deleteServiceDependency(dependency);
                }
            }
        ]
    });
}


function resetServiceLinkForm() {
    $("#service-link-form-title").text("Create link");
    $("#service-link-id").val("");
    $("#service-link-service").prop("disabled", false);
    fillServiceSelect("#service-link-service", getDefaultServiceIdForCreate());

    $("#service-link-type").val("dashboard");
    $("#service-link-label").val("");
    $("#service-link-url").val("");
    $("#service-link-description").val("");
    $("#service-link-priority").val("100");
    $("#service-link-enabled").prop("checked", true);
}


function openCreateServiceLinkModal() {
    resetServiceLinkForm();
    openAppModal("#service-link-modal");
}


function editServiceLink(link) {
    $("#service-link-form-title").text("Edit link");
    $("#service-link-id").val(link.id);
    fillServiceSelect("#service-link-service", link.service_id);
    $("#service-link-service").prop("disabled", true);

    $("#service-link-type").val(link.link_type || "other");
    $("#service-link-label").val(link.label || "");
    $("#service-link-url").val(link.url || "");
    $("#service-link-description").val(link.description || "");
    $("#service-link-priority").val(link.priority || 100);
    $("#service-link-enabled").prop("checked", !!link.enabled);

    openAppModal("#service-link-modal");
}


function collectServiceLinkPayload() {
    return {
        link_type: $("#service-link-type").val() || "other",
        label: $("#service-link-label").val(),
        url: $("#service-link-url").val(),
        description: $("#service-link-description").val() || null,
        priority: Number($("#service-link-priority").val() || 100),
        enabled: $("#service-link-enabled").is(":checked"),
    };
}


function saveServiceLink() {
    const serviceId = Number($("#service-link-service").val());
    const service = getServiceById(serviceId);
    const id = $("#service-link-id").val();
    const payload = collectServiceLinkPayload();

    if (!service) {
        showAppError("Service is required.");
        return;
    }

    if (id) {
        apiPut("/api/services/links/" + id, payload, function () {
            closeAppModal("#service-link-modal");
            refreshServiceContextAfterDetailsChange();
        });
        return;
    }

    apiPost("/api/services/" + service.id + "/links", payload, function () {
        closeAppModal("#service-link-modal");
        refreshServiceContextAfterDetailsChange();
    });
}


function deleteServiceLink(link) {
    showAppConfirm({
        title: "Delete this link?",
        message: "Delete link \"" + (link.label || link.url || link.id) + "\"?",
        confirmText: "Delete",
        confirmClass: "btn-danger",
    }).done(function () {
        apiDelete("/api/services/links/" + link.id, function () {
            refreshServiceContextAfterDetailsChange();
        });
    });
}


function resetServiceRunbookForm() {
    $("#service-runbook-form-title").text("Create runbook");
    $("#service-runbook-id").val("");
    $("#service-runbook-service").prop("disabled", false);
    fillServiceSelect("#service-runbook-service", getDefaultServiceIdForCreate());

    $("#service-runbook-title").val("");
    $("#service-runbook-url").val("");
    $("#service-runbook-severity").val("");
    $("#service-runbook-priority").val("100");
    $("#service-runbook-description").val("");
    setMatcherEditorValue("#service-runbook-matchers", {});
    $("#service-runbook-enabled").prop("checked", true);
    fillMatcherPresetSelect(
        "#service-runbook-matcher-preset",
        [],
        null
    );
    updateServiceRunbookMatcherPresetHint();
}


function openCreateServiceRunbookModal() {
    resetServiceRunbookForm();

    loadServiceRunbookMatcherPresets(
        Number($("#service-runbook-service").val()) || null,
        null,
        function () {
            openAppModal("#service-runbook-modal");
        }
    );
}


function editServiceRunbook(runbook) {
    const matcherPresetId = runbook.matcher_preset_id || (runbook.matcher_preset ? runbook.matcher_preset.id : null);

    $("#service-runbook-form-title").text("Edit runbook");
    $("#service-runbook-id").val(runbook.id);
    fillServiceSelect("#service-runbook-service", runbook.service_id);
    $("#service-runbook-service").prop("disabled", true);

    $("#service-runbook-title").val(runbook.title || "");
    $("#service-runbook-url").val(runbook.url || "");
    $("#service-runbook-severity").val(runbook.severity || "");
    $("#service-runbook-priority").val(runbook.priority ?? 100);
    $("#service-runbook-description").val(runbook.description || "");
    setMatcherEditorValue("#service-runbook-matchers", runbook.matchers || {});
    $("#service-runbook-enabled").prop("checked", runbook.enabled !== false);

    loadServiceRunbookMatcherPresets(runbook.service_id, matcherPresetId, function () {
        openAppModal("#service-runbook-modal");
    });
}


function collectServiceRunbookPayload() {
    return {
        title: $("#service-runbook-title").val(),
        url: $("#service-runbook-url").val(),
        severity: $("#service-runbook-severity").val() || null,
        priority: Number($("#service-runbook-priority").val() || 100),
        description: $("#service-runbook-description").val() || null,
        matcher_preset_id: $("#service-runbook-matcher-preset").val()
            ? Number($("#service-runbook-matcher-preset").val())
            : null,
        matchers: getMatcherEditorValue("#service-runbook-matchers", {}),
        enabled: $("#service-runbook-enabled").is(":checked"),
    };
}


function saveServiceRunbook() {
    const serviceId = Number($("#service-runbook-service").val());
    const service = getServiceById(serviceId);
    const id = $("#service-runbook-id").val();
    const payload = collectServiceRunbookPayload();

    if (!service) {
        showAppError("Service is required.");
        return;
    }

    if (id) {
        apiPut("/api/services/runbooks/" + id, payload, function () {
            closeAppModal("#service-runbook-modal");
            refreshServiceContextAfterDetailsChange();
        });
        return;
    }

    apiPost("/api/services/" + service.id + "/runbooks", payload, function () {
        closeAppModal("#service-runbook-modal");
        refreshServiceContextAfterDetailsChange();
    });
}


function deleteServiceRunbook(runbook) {
    showAppConfirm({
        title: "Delete this runbook?",
        message: "Delete runbook \"" + (runbook.title || runbook.id) + "\"?",
        confirmText: "Delete",
        confirmClass: "btn-danger",
    }).done(function () {
        apiDelete("/api/services/runbooks/" + runbook.id, function () {
            refreshServiceContextAfterDetailsChange();
        });
    });
}


function resetServiceDependencyForm() {
    $("#service-dependency-form-title").text("Create dependency");
    $("#service-dependency-id").val("");
    $("#service-dependency-source").prop("disabled", false);
    fillServiceSelect("#service-dependency-source", getDefaultServiceIdForCreate());

    $("#service-dependency-target").val("");
    $("#service-dependency-type").val("hard");
    $("#service-dependency-criticality").val("important");
    $("#service-dependency-description").val("");
    $("#service-dependency-enabled").prop("checked", true);
}


function openCreateServiceDependencyModal() {
    resetServiceDependencyForm();
    loadServiceDependencyTargets(function () {
        openAppModal("#service-dependency-modal");
    });
}


function editServiceDependency(dependency) {
    $("#service-dependency-form-title").text("Edit dependency");
    $("#service-dependency-id").val(dependency.id);

    fillServiceSelect("#service-dependency-source", dependency.service_id);
    $("#service-dependency-source").prop("disabled", true);

    loadServiceDependencyTargets(function () {
        $("#service-dependency-target").val(dependency.depends_on_service_id || "");
        $("#service-dependency-type").val(dependency.dependency_type || "hard");
        $("#service-dependency-criticality").val(dependency.criticality || "important");
        $("#service-dependency-description").val(dependency.description || "");
        $("#service-dependency-enabled").prop("checked", !!dependency.enabled);
        openAppModal("#service-dependency-modal");
    });
}


function loadServiceDependencyTargets(callback) {
    const sourceId = Number($("#service-dependency-source").val());
    const select = $("#service-dependency-target");

    select.empty();
    select.append($("<option>").val("").text("Select service"));

    apiGet("/api/services", function (services) {
        asArray(services).forEach(function (candidate) {
            if (!candidate.enabled || Number(candidate.id) === sourceId) {
                return;
            }

            select.append(
                $("<option>")
                    .val(String(candidate.id))
                    .text(
                        (candidate.team_slug || candidate.team_name || "-")
                        + " / "
                        + candidate.name
                        + " ("
                        + candidate.slug
                        + ")"
                    )
            );
        });

        if (typeof callback === "function") {
            callback();
        }
    });
}


function collectServiceDependencyPayload() {
    return {
        depends_on_service_id: Number($("#service-dependency-target").val()),
        dependency_type: $("#service-dependency-type").val() || "hard",
        criticality: $("#service-dependency-criticality").val() || "important",
        description: $("#service-dependency-description").val() || null,
        enabled: $("#service-dependency-enabled").is(":checked"),
    };
}


function saveServiceDependency() {
    const serviceId = Number($("#service-dependency-source").val());
    const service = getServiceById(serviceId);
    const id = $("#service-dependency-id").val();
    const payload = collectServiceDependencyPayload();

    if (!service) {
        showAppError("Service is required.");
        return;
    }

    if (!payload.depends_on_service_id) {
        showAppError("Dependency service is required.");
        return;
    }

    if (id) {
        apiPut("/api/services/dependencies/" + id, payload, function () {
            closeAppModal("#service-dependency-modal");
            refreshServiceContextAfterDetailsChange();
        });
        return;
    }

    apiPost("/api/services/" + service.id + "/dependencies", payload, function () {
        closeAppModal("#service-dependency-modal");
        refreshServiceContextAfterDetailsChange();
    });
}


function deleteServiceDependency(dependency) {
    showAppConfirm({
        title: "Delete this dependency?",
        message: "Delete dependency on \"" + (dependency.depends_on_service_name || dependency.id) + "\"?",
        confirmText: "Delete",
        confirmClass: "btn-danger",
    }).done(function () {
        apiDelete("/api/services/dependencies/" + dependency.id, function () {
            refreshServiceContextAfterDetailsChange();
        });
    });
}


$(document).on("click", "#services-page-tabs .page-tab", function () {
    switchServicesPageTab($(this).data("services-tab"));
});

$(document).on("input", "#services-search", renderServicesTable);
$(document).on("change", "#services-status-filter", renderServicesTable);
$(document).on("change", "#services-criticality-filter", renderServicesTable);
$(document).on("change", "#services-readiness-filter", renderServicesTable);
$(document).on("click", "#reload-services", refreshServices);
$(document).on("click", "#open-service-create-modal", openCreateServiceModal);
$(document).on("click", "#save-service", saveService);
$(document).on("click", "#reset-service-form", resetServiceForm);
$(document).on("change", "#service-team", loadServiceDefaults);

$(document).on("input", "#service-links-search", renderAllServiceLinksTable);
$(document).on("input", "#service-runbooks-search", renderAllServiceRunbooksTable);
$(document).on("input", "#service-dependencies-search", renderAllServiceDependenciesTable);
$(document).on("click", "#reload-service-context", refreshAllServiceContext);

$(document).on("click", "#open-service-link-create-modal", openCreateServiceLinkModal);
$(document).on("click", "#save-service-link", saveServiceLink);
$(document).on("click", "#reset-service-link-form", resetServiceLinkForm);

$(document).on("click", "#open-service-runbook-create-modal", openCreateServiceRunbookModal);
$(document).on("click", "#save-service-runbook", saveServiceRunbook);
$(document).on("click", "#reset-service-runbook-form", resetServiceRunbookForm);

$(document).on("click", "#open-service-dependency-create-modal", openCreateServiceDependencyModal);
$(document).on("click", "#save-service-dependency", saveServiceDependency);
$(document).on("click", "#reset-service-dependency-form", resetServiceDependencyForm);
$(document).on("change", "#service-dependency-source", function () {
    loadServiceDependencyTargets();
});

$(document).on("click", "#close-service-form-modal", function () {
    closeAppModal("#service-form-modal");
});

$(document).on("click", "#close-service-link-modal", function () {
    closeAppModal("#service-link-modal");
});

$(document).on("click", "#close-service-runbook-modal", function () {
    closeAppModal("#service-runbook-modal");
});

$(document).on("click", "#close-service-dependency-modal", function () {
    closeAppModal("#service-dependency-modal");
});

$(document).on("click", "#close-service-details-modal", function () {
    closeServiceDetailsModal();
});

$(document).on(
    "click",
    "#service-details-modal, #service-form-modal, #service-link-modal, #service-runbook-modal, #service-dependency-modal, #service-owner-modal",
    function (event) {
        if (event.target !== this) {
            return;
        }

        if (this.id === "service-details-modal") {
            closeServiceDetailsModal();
            return;
        }

        closeAppModal("#" + this.id);
    }
);
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

function refreshServiceImpact(options) {
    options = options || {};

    apiGet("/api/services/impact" + buildServiceImpactQuery(), function (payload) {
        serviceImpactPayload = payload || {};
        serviceImpactCache = asArray(serviceImpactPayload.items);

        renderImpactSummary(serviceImpactPayload.summary || {});
        renderServiceImpactTable();

        if (options.refreshDetails !== false) {
            refreshSelectedServiceDetails();
        }
    });
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

    $("#services-impact-count").text(affected);

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


function renderImpactStatusBadge(status) {
    const normalized = status || "unknown";
    const label = formatImpactStatusText(normalized);

    return $("<span>")
        .addClass("status-pill impact-status-pill")
        .addClass(impactStatusCssClass(normalized))
        .text(
            normalized === "operational"
                ? "Operational"
                : normalized === "maintenance"
                    ? "Maintenance"
                    : label
        );
}


$(document).on("input", "#service-impact-search", renderServiceImpactTable);
$(document).on("change", "#service-impact-effective-filter", renderServiceImpactTable);
$(document).on("change", "#service-impact-reason-filter", renderServiceImpactTable);
$(document).on("change", "#service-impact-include-operational", renderServiceImpactTable);
$(document).on("click", "#reload-service-impact", refreshServiceImpact);


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


function getImpactTeamDisplayName(row) {
    return displayName(row.team_name, row.team_slug);
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


function impactStatusCssClass(status) {
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
function renderServiceDetailsMaintenance(payload) {
    const windows = asArray(payload.maintenance_windows);
    const section = serviceDetailsSection(
        "Maintenance windows",
        "Active and upcoming maintenance that can affect this service."
    );
    const rows = windows.slice(0, 8).map(function (item) {
        return [
            item.name || ("Window #" + item.id),
            item.status || "scheduled",
            item.behavior || "-",
            (item.starts_at || "-") + " → " + (item.ends_at || "-"),
            item.timezone || "UTC",
        ];
    });

    section.append(
        serviceDetailsTableCard(
            "Windows",
            ["Window", "Status", "Behavior", "Time", "TZ"],
            rows,
            "No active or upcoming maintenance windows."
        )
    );

    return section;
}

function renderServiceDetailsRunbooks(payload) {
    const runbooks = asArray(payload.runbooks);
    const section = serviceDetailsSection(
        "Runbooks",
        "Response instructions for this service."
    );
    const rows = runbooks.slice(0, 8).map(function (runbook) {
        return [
            $("<a>")
                .attr("href", runbook.url)
                .attr("target", "_blank")
                .attr("rel", "noopener noreferrer")
                .text(runbook.title || runbook.url || ("Runbook #" + runbook.id)),
            runbook.severity || "any",
            runbook.priority || 0,
            runbook.matcher_preset ? runbook.matcher_preset.name : "-",
            renderStatusBadge(runbook.enabled !== false, "Enabled", "Disabled"),
        ];
    });

    section.append(
        serviceDetailsTableCard(
            "Runbooks",
            ["Runbook", "Severity", "Priority", "Matcher preset", "Status"],
            rows,
            "No runbooks."
        )
    );

    return section;
}

function renderServiceDetailsLinks(payload) {
    const links = asArray(payload.links);
    const section = serviceDetailsSection(
        "Links",
        "Dashboards, logs, traces, repositories and documentation."
    );
    const rows = links.slice(0, 10).map(function (link) {
        return [
            $("<a>")
                .attr("href", link.url)
                .attr("target", "_blank")
                .attr("rel", "noopener noreferrer")
                .text(link.label || link.url || ("Link #" + link.id)),
            link.link_type || "other",
            link.priority || 0,
            link.description || "-",
        ];
    });

    section.append(
        serviceDetailsTableCard(
            "Links",
            ["Link", "Type", "Priority", "Description"],
            rows,
            "No links."
        )
    );

    return section;
}

function renderServiceDetailsDependencies(payload) {
    const dependencies = payload.dependencies || {};
    const upstream = asArray(dependencies.upstream);
    const downstream = asArray(dependencies.downstream);
    const section = serviceDetailsSection(
        "Dependencies",
        "Upstream services this service needs and downstream services that depend on it."
    );

    section.append(
        $("<div>")
            .addClass("grid-two")
            .append(renderServiceDependencyList("Depends on", upstream, true))
            .append(renderServiceDependencyList("Used by", downstream, false))
    );

    return section;
}



function renderServiceDependencyList(title, rows, upstream) {
    const tableRows = rows.slice(0, 10).map(function (dependency) {
        const name = upstream
            ? (dependency.depends_on_service_name || dependency.depends_on_service_slug || "-")
            : (dependency.service_name || dependency.service_slug || "-");

        const status = upstream
            ? dependency.depends_on_service_status
            : dependency.service_status;

        return [
            name,
            dependency.dependency_type || "dependency",
            dependency.criticality || "important",
            status || "unknown",
            dependency.description || "-",
        ];
    });

    return serviceDetailsTableCard(
        title,
        ["Service", "Type", "Criticality", "Status", "Description"],
        tableRows,
        "None"
    );
}



function renderServiceDetailsAnalytics(analytics) {
    const section = serviceDetailsSection(
        "Analytics",
        "Service-level counters for the selected analytics window."
    );
    const widgets = analytics.widgets || {};
    const alertVolume = widgets.alert_volume || {};
    const status = widgets.status || {};

    section.append(
        serviceDetailsCompactCard("Counters", [
            ["Recent alerts", alertVolume.recent || 0],
            ["Total alerts", alertVolume.total || 0],
            ["Status changes", status.changes || 0],
            ["Analytics version", analytics.version || 1],
        ])
    );

    return section;
}



function renderServiceDetailsTimeline(payload) {
    const service = payload.service || {};
    const events = asArray(payload.timeline);
    const pageSize = 20;
    const section = serviceDetailsSection(
        "Timeline",
        "Recent service, readiness and configuration events."
    );
    const table = $("<table>").addClass("data-table");
    const tbody = $("<tbody>").attr("id", "service-details-timeline-body");
    const visibleEvents = events.slice(0, pageSize);

    table.append(
        $("<thead>").append(
            $("<tr>")
                .append($("<th>").text("Time"))
                .append($("<th>").text("Event"))
                .append($("<th>").text("Category"))
                .append($("<th>").text("Actor"))
        )
    );

    if (!visibleEvents.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>")
                    .attr("colspan", 4)
                    .addClass("empty-cell")
                    .text("No timeline events.")
            )
        );
    } else {
        visibleEvents.forEach(function (event) {
            tbody.append(renderServiceTimelineRow(event));
        });
    }

    table.append(tbody);

    section.append(
        $("<div>")
            .addClass("table-wrapper")
            .append(table)
    );

    if (service.id && visibleEvents.length === pageSize) {
        section.append(renderServiceTimelineLoadMoreButton(service.id, visibleEvents[visibleEvents.length - 1]));
    }

    return section;
}

function renderServiceTimelineRow(event) {
    const actor = event.actor || {};

    return $("<tr>")
        .append(serviceDetailsTableCell(formatServiceTimelineTime(event.occurred_at), false))
        .append(serviceDetailsTableCell(renderServiceTimelineEventCell(event), true))
        .append(serviceDetailsTableCell(renderServiceTimelineCategoryBadge(event.category), false))
        .append(serviceDetailsTableCell(formatServiceTimelineActor(actor), false));
}

function renderServiceTimelineEventCell(event) {
    const wrapper = $("<div>");
    const title = $("<div>").append(
        $("<strong>").text(event.title || event.event_type || "Event")
    );

    if (event.status) {
        title.append(" ").append(renderServiceTimelineStatusBadge(event.status));
    }

    wrapper.append(title);

    wrapper.append(
        $("<div>")
            .addClass("row-subtitle")
            .text(event.event_type || "-")
    );

    if (event.summary && event.summary !== event.event_type) {
        wrapper.append(
            $("<div>")
                .addClass("row-subtitle")
                .text(event.summary)
        );
    }

    return wrapper;
}

function renderServiceTimelineCategoryBadge(category) {
    return $("<span>")
        .addClass("status-pill status-neutral")
        .text(formatServiceTimelineCategory(category));
}

function renderServiceTimelineStatusBadge(status) {
    return $("<span>")
        .addClass(getServiceTimelineStatusClass(status))
        .text(formatServiceTimelineCategory(status));
}

function getServiceTimelineStatusClass(status) {
    if (status === "ready" || status === "operational" || status === "passed") {
        return "status-pill status-active";
    }

    if (status === "warning" || status === "degraded" || status === "maintenance") {
        return "status-pill status-scheduled";
    }

    if (status === "not_ready" || status === "failed" || status === "critical" || status === "down") {
        return "status-pill status-inactive";
    }

    return "status-pill status-neutral";
}

function formatServiceTimelineTime(value) {
    if (!value) {
        return "-";
    }

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return value;
    }

    const options = {
        month: "short",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
    };

    if (date.getFullYear() !== new Date().getFullYear()) {
        options.year = "numeric";
    }

    return date.toLocaleString(undefined, options);
}

function formatServiceTimelineCategory(value) {
    return String(value || "-").replace(/_/g, " ");
}

function formatServiceTimelineActor(actor) {
    if (!actor) {
        return "-";
    }

    if (actor.display_name) {
        return actor.display_name;
    }

    if (actor.label) {
        return actor.label;
    }

    if (actor.email) {
        return actor.email;
    }

    if (actor.user_id) {
        return "User #" + actor.user_id;
    }

    return actor.type || "-";
}

function renderServiceTimelineLoadMoreButton(serviceId, lastEvent) {
    const cursor = serviceTimelineCursorFromEvent(lastEvent);
    const actions = $("<div>").addClass("form-actions");
    const button = $("<button>")
        .attr("type", "button")
        .addClass("btn")
        .text("Load more")
        .on("click", function () {
            loadMoreServiceTimelineEvents(serviceId, $(this));
        });

    if (cursor) {
        button.data("before", cursor.before);
        button.data("before-id", cursor.before_id);
    }

    actions.append(button);

    return actions;
}

function serviceTimelineCursorFromEvent(event) {
    if (!event || !event.occurred_at) {
        return null;
    }

    return {
        before: event.occurred_at,
        before_id: event.id || "",
    };
}

function loadMoreServiceTimelineEvents(serviceId, button) {
    const before = button.data("before");
    const beforeId = button.data("before-id");

    if (!before) {
        button.closest(".form-actions").remove();
        return;
    }

    button.prop("disabled", true).text("Loading...");

    let url = "/api/services/" + encodeURIComponent(serviceId) + "/timeline?limit=20&before=" + encodeURIComponent(before);

    if (beforeId) {
        url += "&before_id=" + encodeURIComponent(beforeId);
    }

    apiGet(url, function (payload) {
        const items = asArray(payload.items);
        const tbody = $("#service-details-timeline-body");

        if (!items.length) {
            button.closest(".form-actions").remove();
            return;
        }

        items.forEach(function (event) {
            tbody.append(renderServiceTimelineRow(event));
        });

        if (payload.next_cursor) {
            button
                .data("before", payload.next_cursor.before)
                .data("before-id", payload.next_cursor.before_id)
                .prop("disabled", false)
                .text("Load more");
            return;
        }

        button.closest(".form-actions").remove();
    });
}

function openServiceAlerts(service, options) {
    options = options || {};

    const params = new URLSearchParams();

    if (service && service.id) {
        params.append("service_id", String(service.id));
    }

    if (options.onlyOpen !== false) {
        params.append("status", "firing");
        params.append("status", "acknowledged");
    }

    params.set("sort", "activity");
    params.set("order", "desc");
    params.set("page", "1");
    params.set("page_size", "25");

    window.location.href = "/alerts?" + params.toString();
}
function invalidateServiceDetailsCache() {
    serviceDetailsCache = {};
}


function refreshSelectedServiceDetails() {
    if (!selectedServiceDetailsId || !isServiceDetailsModalOpen()) {
        return;
    }

    loadServiceDetails(selectedServiceDetailsId);
}



function refreshServiceContextAfterDetailsChange() {
    invalidateServiceDetailsCache();
    refreshAllServiceContext();
    refreshServiceImpact({ refreshDetails: false });
    refreshServiceAnalytics();
    refreshSelectedServiceDetails();
}
function renderServiceAnalyticsCharts() {
    if (!window.Chart) {
        $("#service-analytics-charts").hide();
        return;
    }

    $("#service-analytics-charts").show();

    const payload = serviceAnalyticsPayload || {};
    const series = payload.series || {};
    const alertGroups = asArray(series.alert_groups_by_day);
    const rawAlerts = asArray(series.raw_alerts_by_day);

    renderAnalyticsChart(
    "alertGroups",
    "#service-analytics-alert-groups-chart",
    {
        type: "line",
        labels: alertGroups.map(function (row) {
            return formatAnalyticsBucketLabel(row.bucket);
        }),
        datasets: [
            {
                label: "Total groups",
                data: alertGroups.map(function (row) {
                    return Number(row.total || 0);
                }),
                tension: 0.3,
            },
            {
                label: "Firing",
                data: alertGroups.map(function (row) {
                    return Number(row.firing || 0);
                }),
                tension: 0.3,
            },
            {
                label: "Acknowledged",
                data: alertGroups.map(function (row) {
                    return Number(row.acknowledged || 0);
                }),
                tension: 0.3,
            },
            {
                label: "Resolved",
                data: alertGroups.map(function (row) {
                    return Number(row.resolved || 0);
                }),
                tension: 0.3,
            },
            {
                label: "Critical",
                data: alertGroups.map(function (row) {
                    return Number(row.critical || 0);
                }),
                tension: 0.3,
            },
        ],
    }
);

    renderAnalyticsChart(
        "rawAlerts",
        "#service-analytics-raw-alerts-chart",
        {
            type: "bar",
            labels: rawAlerts.map(function (row) {
                return formatAnalyticsBucketLabel(row.bucket);
            }),
            datasets: [
                {
                    label: "Raw alerts",
                    data: rawAlerts.map(function (row) {
                        return Number(row.raw_alerts || 0);
                    }),
                },
            ],
        }
    );

    renderAnalyticsChart(
        "firingGroups",
        "#service-analytics-firing-chart",
        {
            type: "bar",
            labels: alertGroups.map(function (row) {
                return formatAnalyticsBucketLabel(row.bucket);
            }),
            datasets: [
                {
                    label: "Firing groups",
                    data: alertGroups.map(function (row) {
                        return Number(row.firing || 0);
                    }),
                },
            ],
        }
    );
}


function renderAnalyticsChart(key, selector, config) {
    const canvas = $(selector).get(0);

    if (!canvas) {
        return;
    }

    if (serviceAnalyticsCharts[key]) {
        serviceAnalyticsCharts[key].destroy();
    }

    serviceAnalyticsCharts[key] = new Chart(canvas, {
        type: config.type,
        data: {
            labels: config.labels,
            datasets: config.datasets,
        },
        options: analyticsChartOptions(),
    });
}


function analyticsChartOptions() {
    return {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
            mode: "index",
            intersect: false,
        },
        plugins: {
            legend: {
                display: true,
                position: "bottom",
            },
            tooltip: {
                enabled: true,
            },
        },
        scales: {
            x: {
                ticks: {
                    maxRotation: 0,
                    autoSkip: true,
                    maxTicksLimit: 8,
                },
                grid: {
                    display: false,
                },
            },
            y: {
                beginAtZero: true,
                ticks: {
                    precision: 0,
                },
            },
        },
    };
}


function formatAnalyticsBucketLabel(value) {
    if (!value) {
        return "-";
    }

    const parts = String(value).split("-");

    if (parts.length === 3) {
        return parts[1] + "/" + parts[2];
    }

    return String(value);
}

function serviceOwnerDisplayName(owner) {
    return (
        owner.user_display_name
        || owner.username
        || owner.user_email
        || ("User #" + owner.user_id)
        || "-"
    );
}


function serviceOwnerNotificationText(owner) {
    const flags = [];

    if (owner.notify_on_created) {
        flags.push("created");
    }
    if (owner.notify_on_priority_change) {
        flags.push("priority");
    }
    if (owner.notify_on_status_change) {
        flags.push("status");
    }
    if (owner.notify_on_resolved) {
        flags.push("resolved");
    }
    if (owner.notify_on_comment) {
        flags.push("comments");
    }

    return flags.length ? flags.join(", ") : "off";
}


function renderServiceDetailsOwners(payload) {
    const service = payload.service || {};
    const owners = asArray(service.owners || payload.owners);
    const section = serviceDetailsSection("Default stakeholders", null);
    const actions = $("<div>").addClass("details-actions");

    appendIconActionIfAllowed(actions, service, {
        required: "write",
        icon: "fas fa-plus",
        label: "Add stakeholder",
        onClick: function () {
            openCreateServiceOwnerModal(service);
        },
    });

    section.append(actions);

    if (!owners.length) {
        section.append(
            $("<div>")
                .addClass("empty-state compact")
                .text("No default stakeholders.")
        );

        return section;
    }

    const table = $("<table>").addClass("data-table");

    table.append(
        $("<thead>").append(
            $("<tr>")
                .append($("<th>").text("User"))
                .append($("<th>").text("Role"))
                .append($("<th>").text("Notifications"))
                .append($("<th>").text("Status"))
                .append($("<th>").addClass("actions-th").text("Actions"))
        )
    );

    const tbody = $("<tbody>");

    owners.forEach(function (owner) {
        tbody.append(renderServiceOwnerCompactRow(service, owner));
    });

    table.append(tbody);

    section.append(
        $("<div>")
            .addClass("table-wrapper")
            .append(table)
    );

    return section;
}

function renderServiceOwnerCompactRow(service, owner) {
    return $("<tr>")
        .toggleClass("row-disabled", !owner.active)
        .append(
            $("<td>")
                .addClass("table-cell-truncate")
                .attr("title", serviceOwnerDisplayName(owner))
                .append($("<strong>").text(serviceOwnerDisplayName(owner)))
                .append($("<div>").addClass("row-subtitle").text(owner.user_email || owner.username || ""))
        )
        .append($("<td>").text(owner.role || "owner"))
        .append($("<td>").text(serviceOwnerNotificationText(owner)))
        .append(
            $("<td>").append(
                renderStatusBadge(!!owner.active, "Active", "Inactive")
            )
        )
        .append(
            $("<td>")
                .addClass("actions-cell")
                .append(renderServiceOwnerActions(service, owner))
        );
}

function renderServiceOwnerActions(service, owner) {
    return makeActionMenu({
        object: service,
        items: [
            {
                label: "Edit",
                icon: "fas fa-edit",
                required: "write",
                onClick: function () {
                    editServiceOwner(service, owner);
                },
            },
            {
                label: "Delete",
                icon: "fas fa-trash",
                required: "write",
                danger: true,
                onClick: function () {
                    deleteServiceOwner(service, owner);
                },
            },
        ],
    });
}


function resetServiceOwnerForm() {
    $("#service-owner-form-title").text("Add default stakeholder");
    $("#service-owner-id").val("");
    $("#service-owner-service-id").val("");
    $("#service-owner-role").val("owner");
    $("#service-owner-active").prop("checked", true);
    $("#service-owner-notify-created").prop("checked", true);
    $("#service-owner-notify-priority").prop("checked", true);
    $("#service-owner-notify-status").prop("checked", true);
    $("#service-owner-notify-resolved").prop("checked", true);
    $("#service-owner-notify-comment").prop("checked", true);

    fillUserSelect("#service-owner-user", null, "/api/users?all=1");
}


function openCreateServiceOwnerModal(service) {
    resetServiceOwnerForm();

    $("#service-owner-service-id").val(service.id);
    $("#service-owner-user").prop("disabled", false);

    openAppModal("#service-owner-modal");
}


function editServiceOwner(service, owner) {
    resetServiceOwnerForm();

    $("#service-owner-form-title").text("Edit default stakeholder");
    $("#service-owner-id").val(owner.id);
    $("#service-owner-service-id").val(service.id);
    $("#service-owner-role").val(owner.role || "owner");
    $("#service-owner-active").prop("checked", !!owner.active);
    $("#service-owner-notify-created").prop("checked", !!owner.notify_on_created);
    $("#service-owner-notify-priority").prop(
        "checked",
        !!owner.notify_on_priority_change
    );
    $("#service-owner-notify-status").prop(
        "checked",
        !!owner.notify_on_status_change
    );
    $("#service-owner-notify-resolved").prop(
        "checked",
        !!owner.notify_on_resolved
    );
    $("#service-owner-notify-comment").prop(
        "checked",
        !!owner.notify_on_comment
    );

    fillUserSelect("#service-owner-user", function () {
        $("#service-owner-user").val(String(owner.user_id || ""));
    }, "/api/users?all=1");

    openAppModal("#service-owner-modal");
}


function collectServiceOwnerPayload() {
    return {
        user_id: Number($("#service-owner-user").val()),
        role: $("#service-owner-role").val() || "owner",
        active: $("#service-owner-active").is(":checked"),
        notify_on_created: $("#service-owner-notify-created").is(":checked"),
        notify_on_priority_change: $("#service-owner-notify-priority").is(":checked"),
        notify_on_status_change: $("#service-owner-notify-status").is(":checked"),
        notify_on_resolved: $("#service-owner-notify-resolved").is(":checked"),
        notify_on_comment: $("#service-owner-notify-comment").is(":checked"),
    };
}


function saveServiceOwner() {
    const serviceId = Number($("#service-owner-service-id").val());
    const ownerId = $("#service-owner-id").val();
    const payload = collectServiceOwnerPayload();

    if (!serviceId) {
        showAppError("Service is required.");
        return;
    }

    if (!payload.user_id) {
        showAppError("User is required.");
        return;
    }

    if (ownerId) {
        apiPut(
            "/api/services/" + encodeURIComponent(serviceId)
            + "/owners/" + encodeURIComponent(ownerId),
            payload,
            function () {
                closeAppModal("#service-owner-modal");
                refreshServiceContextAfterDetailsChange();
            }
        );

        return;
    }

    apiPost(
        "/api/services/" + encodeURIComponent(serviceId) + "/owners",
        payload,
        function () {
            closeAppModal("#service-owner-modal");
            refreshServiceContextAfterDetailsChange();
        }
    );
}


function deleteServiceOwner(service, owner) {
    showAppConfirm({
        title: "Delete this default stakeholder?",
        message: (
            "Delete default stakeholder \""
            + serviceOwnerDisplayName(owner)
            + "\" from service \""
            + (service.name || service.slug || service.id)
            + "\"?"
        ),
        confirmText: "Delete",
        confirmClass: "btn-danger",
    }).done(function () {
        apiDelete(
            "/api/services/" + encodeURIComponent(service.id)
            + "/owners/" + encodeURIComponent(owner.id),
            function () {
                refreshServiceContextAfterDetailsChange();
            }
        );
    });
}
$(document).on("click", "#save-service-owner", saveServiceOwner);
$(document).on("click", "#reset-service-owner-form", resetServiceOwnerForm);

$(document).on("click", "#close-service-owner-modal", function () {
    closeAppModal("#service-owner-modal");
});
function updateServiceRunbookMatcherPresetHint() {
    const preset = findMatcherPresetById(
        serviceRunbookMatcherPresetsCache,
        $("#service-runbook-matcher-preset").val()
    );

    $("#service-runbook-matcher-preset-hint").text(
        matcherPresetAndLocalHint(preset)
    );
}


function loadServiceRunbookMatcherPresets(serviceId, selectedPresetId, callback) {
    const service = getServiceById(serviceId);
    serviceRunbookMatcherPresetsCache = [];

    fillMatcherPresetSelect(
        "#service-runbook-matcher-preset",
        [],
        null
    );
    updateServiceRunbookMatcherPresetHint();

    if (!service) {
        if (typeof callback === "function") {
            callback([]);
        }
        return;
    }

    loadMatcherPresetsForTeam(service.team_id, function (presets) {
        serviceRunbookMatcherPresetsCache = presets;

        fillMatcherPresetSelect(
            "#service-runbook-matcher-preset",
            presets,
            selectedPresetId
        );
        updateServiceRunbookMatcherPresetHint();

        if (typeof callback === "function") {
            callback(presets);
        }
    });
}
$(document).on("change", "#service-runbook-service", function () {
    loadServiceRunbookMatcherPresets(
        Number($(this).val()) || null,
        null
    );
});

$(document).on(
    "change",
    "#service-runbook-matcher-preset",
    updateServiceRunbookMatcherPresetHint
);

window.refreshServices = refreshServices;
window.loadServiceDetails = loadServiceDetails;
window.openServiceDetailsModal = openServiceDetailsModal;
window.getServiceById = getServiceById;
window.servicesCache = servicesCache;
window.selectedServiceId = selectedServiceDetailsId;
