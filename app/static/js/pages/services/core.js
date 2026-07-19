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



function setServicesStaticText(selector, key) {
    const element = $(selector);

    if (element.length) {
        element.text(i18n.t(key));
    }
}

function setServicesStaticPlaceholder(selector, key) {
    const element = $(selector);

    if (element.length) {
        element.attr("placeholder", i18n.t(key));
    }
}

function setServicesTabLabel(tab, key) {
    const button = $('[data-services-tab="' + tab + '"]');

    if (!button.length) {
        return;
    }

    const count = button.find(".page-tab-count").detach();
    button.text(i18n.t(key));

    if (count.length) {
        button.append(" ").append(count);
    }
}

function translateServicesWorkspace() {
    setServicesStaticText("#services-summary-total-title", "services.summary.total");
    setServicesStaticText("#services-summary-total-hint", "services.summary.services_in_scope");
    setServicesStaticText("#services-summary-operational-title", "services.summary.operational");
    setServicesStaticText("#services-summary-operational-hint", "services.summary.effective_status");
    setServicesStaticText("#services-summary-degraded-title", "services.summary.affected");
    setServicesStaticText("#services-summary-degraded-hint", "services.summary.not_operational");
    setServicesStaticText("#services-summary-critical-title", "services.summary.major_outage");

    setServicesTabLabel("services", "services.tabs.services");
    setServicesTabLabel("links", "services.tabs.links");
    setServicesTabLabel("runbooks", "services.tabs.runbooks");
    setServicesTabLabel("dependencies", "services.tabs.dependencies");
    setServicesTabLabel("impact", "services.tabs.impact");
    setServicesTabLabel("standards", "services.tabs.standards");
    setServicesTabLabel("analytics", "services.tabs.analytics");
    setServicesTabLabel("reliability", "services.tabs.reliability");

    setServicesStaticText("#services-tab-services h2", "services.section.services");
    setServicesStaticText("#open-service-create-modal", "services.actions.new_service");
    setServicesStaticText("#reload-services", "services.actions.reload");
    setServicesStaticPlaceholder("#services-search", "services.search.services");

    setServicesStaticText("#services-status-filter option[value='']", "services.filters.all_statuses");
    setServicesStaticText("#services-status-filter option[value='operational']", "services.status.operational");
    setServicesStaticText("#services-status-filter option[value='degraded']", "services.status.degraded");
    setServicesStaticText("#services-status-filter option[value='partial_outage']", "services.status.partial_outage");
    setServicesStaticText("#services-status-filter option[value='major_outage']", "services.status.major_outage");
    setServicesStaticText("#services-status-filter option[value='maintenance']", "services.status.maintenance");
    setServicesStaticText("#services-status-filter option[value='disabled']", "services.status.disabled");
    setServicesStaticText("#services-status-filter option[value='unknown']", "services.status.unknown");

    setServicesStaticText("#services-criticality-filter option[value='']", "services.filters.all_criticalities");
    setServicesStaticText("#services-criticality-filter option[value='critical']", "services.criticality.critical");
    setServicesStaticText("#services-criticality-filter option[value='high']", "services.criticality.high");
    setServicesStaticText("#services-criticality-filter option[value='medium']", "services.criticality.medium");
    setServicesStaticText("#services-criticality-filter option[value='low']", "services.criticality.low");

    setServicesStaticText("#services-readiness-filter option[value='']", "services.filters.all_readiness");
    setServicesStaticText("#services-readiness-filter option[value='ready']", "services.readiness.ready");
    setServicesStaticText("#services-readiness-filter option[value='warning']", "services.readiness.warning");
    setServicesStaticText("#services-readiness-filter option[value='not_ready']", "services.readiness.not_ready");
    setServicesStaticText("#services-readiness-filter option[value='not_applicable']", "services.readiness.not_applicable");
    setServicesStaticText("#services-readiness-filter option[value='not_evaluated']", "services.readiness.not_evaluated");

    const serviceHeaders = [
        "services.table.service",
        "services.table.team",
        "services.table.status",
        "services.table.readiness",
        "services.table.criticality",
        "services.table.environment",
        "services.table.defaults",
        "services.table.actions",
    ];
    $("#services-table-view thead th").each(function (index) {
        if (serviceHeaders[index]) {
            $(this).text(i18n.t(serviceHeaders[index]));
        }
    });
    $("#services-table .empty-cell").text(i18n.t("services.empty.services_loaded"));

    setServicesStaticText("#services-tab-links h2", "services.section.links");
    setServicesStaticText("#services-tab-links .card-subtitle", "services.section.links_subtitle");
    setServicesStaticText("#open-service-link-create-modal", "services.actions.new_link");
    setServicesStaticPlaceholder("#service-links-search", "services.search.links");

    const linkHeaders = [
        "services.table.link",
        "services.table.service",
        "services.table.team",
        "services.table.type",
        "services.table.priority",
        "services.table.status",
        "services.table.actions",
    ];
    $("#services-tab-links thead th").each(function (index) {
        if (linkHeaders[index]) {
            $(this).text(i18n.t(linkHeaders[index]));
        }
    });
    $("#service-links-table .empty-cell").text(i18n.t("services.empty.links"));

    setServicesStaticText("#services-tab-runbooks h2", "services.section.runbooks");
    setServicesStaticText("#services-tab-runbooks .card-subtitle", "services.section.runbooks_subtitle");
    setServicesStaticText("#open-service-runbook-create-modal", "services.actions.new_runbook");
    setServicesStaticPlaceholder("#service-runbooks-search", "services.search.runbooks");

    const runbookHeaders = [
        "services.table.runbook",
        "services.table.service",
        "services.table.team",
        "services.table.severity",
        "services.table.priority",
        "services.table.status",
        "services.table.actions",
    ];
    $("#services-tab-runbooks thead th").each(function (index) {
        if (runbookHeaders[index]) {
            $(this).text(i18n.t(runbookHeaders[index]));
        }
    });
    $("#service-runbooks-table .empty-cell").text(i18n.t("services.empty.runbooks"));

    setServicesStaticText("#services-tab-dependencies h2", "services.section.dependencies");
    setServicesStaticText("#services-tab-dependencies .card-header .card-subtitle", "services.section.dependencies_subtitle");
    setServicesStaticText("#open-service-dependency-create-modal", "services.actions.new_dependency");
    setServicesStaticText('[id="reload-service-context"]', "services.actions.reload");
    setServicesStaticPlaceholder("#service-dependencies-search", "services.search.dependencies");
    setServicesStaticPlaceholder("#service-dependency-graph-search", "services.search.graph");

    setServicesStaticText("#service-dependencies-view-table", "services.dependencies.table");
    setServicesStaticText("#service-dependencies-view-graph", "services.dependencies.graph");
    $(".service-dependencies-view-tabs").attr("aria-label", i18n.t("services.dependencies.view"));

    setServicesStaticText("#service-dependency-graph-mode option[value='overview']", "services.dependencies.overview");
    setServicesStaticText("#service-dependency-graph-mode option[value='impact']", "services.dependencies.impact_only");
    setServicesStaticText("#service-dependency-graph-mode option[value='full']", "services.dependencies.full_graph");
    $("#service-dependency-graph-mode").attr("title", i18n.t("services.dependencies.graph_mode"));

    setServicesStaticText("#service-dependency-graph-collapse option[value='healthy_leaves']", "services.dependencies.hide_healthy_leaves");
    setServicesStaticText("#service-dependency-graph-collapse option[value='team']", "services.dependencies.collapse_team");
    setServicesStaticText("#service-dependency-graph-collapse option[value='prefix']", "services.dependencies.collapse_prefix");
    setServicesStaticText("#service-dependency-graph-collapse option[value='none']", "services.dependencies.no_collapse");
    $("#service-dependency-graph-collapse").attr("title", i18n.t("services.dependencies.collapse_sections"));

    [1, 2, 3, 5].forEach(function (depth) {
        setServicesStaticText(
            "#service-dependency-graph-depth option[value='" + depth + "']",
            "services.dependencies.depth"
        );
        $("#service-dependency-graph-depth option[value='" + depth + "']").text(
            i18n.t("services.dependencies.depth", {value: depth})
        );
    });
    setServicesStaticText("#service-dependency-graph-depth option[value='all']", "services.dependencies.depth_all");
    $("#service-dependency-graph-depth").attr("title", i18n.t("services.dependencies.focus_depth"));

    setServicesStaticText("#service-dependency-graph-focus option[value='']", "services.filters.all_services");
    setServicesStaticText("#service-dependency-graph-direction option[value='connected']", "services.dependencies.connected");
    setServicesStaticText("#service-dependency-graph-direction option[value='outgoing']", "services.dependencies.outgoing");
    setServicesStaticText("#service-dependency-graph-direction option[value='incoming']", "services.dependencies.incoming");
    setServicesStaticText("#service-dependency-graph-direction option[value='all']", "services.dependencies.all");
    setServicesStaticText("#service-dependency-graph-layout option[value='breadthfirst']", "services.dependencies.hierarchy");
    setServicesStaticText("#service-dependency-graph-layout option[value='cose']", "services.dependencies.force_directed");
    setServicesStaticText("#service-dependency-graph-layout option[value='circle']", "services.dependencies.circle");
    setServicesStaticText("#service-dependency-graph-layout option[value='grid']", "services.dependencies.grid");
    setServicesStaticText("#service-dependency-graph-fit", "services.dependencies.fit");
    $("#service-dependency-graph .empty-state").text(i18n.t("services.dependencies.no_graph"));

    const dependencyHeaders = [
        "services.table.service",
        "services.table.depends_on",
        "services.table.type",
        "services.table.criticality",
        "services.table.target_status",
        "services.table.description",
        "services.table.actions",
    ];
    $("#service-dependencies-table-view thead th").each(function (index) {
        if (dependencyHeaders[index]) {
            $(this).text(i18n.t(dependencyHeaders[index]));
        }
    });
    $("#service-dependencies-table .empty-cell").text(i18n.t("services.empty.dependencies"));
}


function serviceStatusLabel(status) {
    const value = String(status || "unknown").toLowerCase();
    const labels = {
        operational: "services.status.operational",
        degraded: "services.status.degraded",
        partial_outage: "services.status.partial_outage",
        major_outage: "services.status.major_outage",
        maintenance: "services.status.maintenance",
        disabled: "services.status.disabled",
        unknown: "services.status.unknown",
    };

    return labels[value] ? i18n.t(labels[value]) : String(status || "-").replace(/_/g, " ");
}

function serviceReadinessLabel(status) {
    const value = String(status || "not_evaluated").toLowerCase();
    const labels = {
        ready: "services.readiness.ready",
        warning: "services.readiness.warning",
        not_ready: "services.readiness.not_ready",
        not_applicable: "services.readiness.not_applicable",
        not_evaluated: "services.readiness.not_evaluated",
    };

    return labels[value] ? i18n.t(labels[value]) : String(status || "-").replace(/_/g, " ");
}

function serviceCriticalityLabel(value) {
    const normalized = String(value || "").toLowerCase();
    const labels = {
        critical: "services.criticality.critical",
        high: "services.criticality.high",
        medium: "services.criticality.medium",
        low: "services.criticality.low",
        required: "services.dependencies.required",
        important: "services.dependencies.important",
        optional: "services.dependencies.optional",
    };

    return labels[normalized] ? i18n.t(labels[normalized]) : (value || "-");
}

function serviceEnvironmentLabel(value) {
    const normalized = String(value || "").toLowerCase();
    const labels = {
        production: "services.environment.production",
        staging: "services.environment.staging",
        development: "services.environment.development",
        testing: "services.environment.testing",
        shared: "services.environment.shared",
    };

    return labels[normalized] ? i18n.t(labels[normalized]) : (value || "-");
}

function serviceDependencyTypeLabel(value) {
    const normalized = String(value || "").toLowerCase();
    const labels = {
        hard: "services.dependencies.hard",
        soft: "services.dependencies.soft",
        external: "services.dependencies.external",
        informational: "services.dependencies.informational",
    };

    return labels[normalized] ? i18n.t(labels[normalized]) : (value || "-");
}


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
    translateServicesWorkspace();
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
        totalHint: i18n.t("services.summary.current_scope"),
        operationalHint: i18n.t("services.summary.own_status"),
        affectedHint: i18n.t("services.summary.own_status_not_operational"),
        majorHint: i18n.t("services.summary.own_status"),
    });
}


function renderServiceSummaryTiles(summary) {
    summary = summary || {};

    $("#services-summary-total-title").text(summary.totalTitle || i18n.t("services.summary.total"));
    $("#services-summary-operational-title").text(summary.operationalTitle || i18n.t("services.summary.operational"));
    $("#services-summary-degraded-title").text(summary.affectedTitle || i18n.t("services.summary.affected"));
    $("#services-summary-critical-title").text(summary.majorTitle || i18n.t("services.summary.major_outage"));

    $("#services-summary-total").text(summary.total === undefined ? 0 : summary.total);
    $("#services-summary-operational").text(summary.operational === undefined ? 0 : summary.operational);
    $("#services-summary-degraded").text(summary.affected === undefined ? 0 : summary.affected);
    $("#services-summary-critical").text(summary.major === undefined ? 0 : summary.major);

    $("#services-summary-total-hint").text(summary.totalHint || i18n.t("services.summary.services_in_scope"));
    $("#services-summary-operational-hint").text(summary.operationalHint || i18n.t("services.summary.effective_status"));
    $("#services-summary-degraded-hint").text(summary.affectedHint || i18n.t("services.summary.not_operational"));
    $("#services-summary-critical-hint").text(summary.majorHint || i18n.t("services.summary.effective_status"));
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
                    .text(i18n.t("services.empty.services"))
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
                    .text(service.description || service.slug || i18n.t("services.service_number", {id: service.id}))
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
    row.append($("<td>").text(serviceCriticalityLabel(service.criticality)));
    row.append($("<td>").text(serviceEnvironmentLabel(service.environment)));

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
        return renderStatusBadge(
            false,
            i18n.t("services.status.operational"),
            i18n.t("services.status.disabled")
        );
    }

    const status = service.status || "unknown";
    const label = serviceStatusLabel(status);

    if (status === "operational") {
        return $("<span>").addClass("status-pill status-active").text(label);
    }

    if (status === "maintenance") {
        return $("<span>").addClass("status-pill status-scheduled").text(label);
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
    return serviceReadinessLabel(status);
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
        return $("<span>").addClass("status-pill status-active").attr("title", i18n.t("services.readiness.ready")).text(label);
    }

    if (status === "warning") {
        return $("<span>").addClass("status-pill status-scheduled").attr("title", i18n.t("services.readiness.warning")).text(label);
    }

    if (status === "not_ready") {
        return $("<span>").addClass("status-pill status-inactive").attr("title", i18n.t("services.readiness.not_ready")).text(label);
    }

    return $("<span>").addClass("status-pill status-neutral").attr("title", formatServiceReadinessStatus(status)).text(label);
}

function getServiceDefaultsLabel(service) {
    const defaults = [];

    if (service.default_rotation_name) {
        defaults.push(i18n.t("services.defaults.rotation", {name: service.default_rotation_name}));
    }

    if (service.default_escalation_policy_name) {
        defaults.push(i18n.t("services.defaults.policy", {name: service.default_escalation_policy_name}));
    }

    if (service.notification_policy_name) {
        defaults.push(i18n.t("services.defaults.notifications", {name: service.notification_policy_name}));
    }

    if (service.priority_policy_name) {
        defaults.push(i18n.t("services.defaults.priority", {name: service.priority_policy_name}));
    }

    return defaults.join(" / ") || "-";
}


function renderServiceActions(service) {
    return makeActionMenu({
        object: service,
        items: [
            {
                label: i18n.t("services.actions.details"),
                icon: "fas fa-info-circle",
                onClick: function () {
                    openServiceDetailsModal(service.id);
                }
            },
            {
                label: i18n.t("services.actions.edit"),
                icon: "fas fa-edit",
                required: "write",
                denyMessage: i18n.t("services.permissions.edit"),
                onClick: function () {
                    editService(service.id);
                }
            },
            {
                label: service.enabled
                    ? i18n.t("services.actions.disable")
                    : i18n.t("services.actions.enable"),
                icon: service.enabled ? "fas fa-pause" : "fas fa-play",
                required: "write",
                danger: service.enabled,
                denyMessage: i18n.t("services.permissions.toggle"),
                onClick: function () {
                    setServiceEnabled(service, !service.enabled);
                }
            },
            {
                label: i18n.t("services.actions.delete"),
                icon: "fas fa-trash",
                required: "delete",
                danger: true,
                denyMessage: i18n.t("services.permissions.delete"),
                onClick: function () {
                    deleteService(service);
                }
            }
        ]
    });
}


