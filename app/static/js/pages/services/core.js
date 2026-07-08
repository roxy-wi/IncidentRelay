// Service catalog core: global state, service list, service form and details modal entry points.

let servicesCache = [];
let selectedServiceDetailsId = null;
let servicesPageTab = "services";
let allServiceLinksCache = [];
let allServiceRunbooksCache = [];
let allServiceDependenciesCache = [];
let allServiceGraphDependenciesCache = [];
let businessServiceComponentsCache = [];
let serviceAnalyticsCache = [];
let serviceImpactCache = [];
let serviceDetailsCache = {};
let serviceImpactPayload = null;
let serviceImpactHistoryPayload = null;
let serviceImpactHistoryCache = [];
let serviceImpactView = "current";
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
    initializeServiceDependencyGraph();
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


