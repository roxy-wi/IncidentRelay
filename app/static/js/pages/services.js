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
let serviceAnalyticsCharts = {};


function loadServices() {
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

        renderServicesSummary();
        renderServicesTable();
        restoreServiceDetails();
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
        service.default_rotation_name,
        service.default_escalation_policy_name,
        service.enabled ? "enabled" : "disabled",
    ].join(" ").toLowerCase();
}


function getFilteredServices() {
    const query = String($("#services-search").val() || "").trim().toLowerCase();
    const status = String($("#services-status-filter").val() || "");
    const criticality = String($("#services-criticality-filter").val() || "");

    return servicesCache.filter(function (service) {
        if (status && service.status !== status) {
            return false;
        }

        if (criticality && service.criticality !== criticality) {
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
                    .attr("colspan", "7")
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
                        renderServiceDetails(service);
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


function getServiceDefaultsLabel(service) {
    const defaults = [];

    if (service.default_rotation_name) {
        defaults.push("Rotation: " + service.default_rotation_name);
    }

    if (service.default_escalation_policy_name) {
        defaults.push("Policy: " + service.default_escalation_policy_name);
    }

    return defaults.join(" / ") || "-";
}


function renderServiceActions(service) {
    return makeActionMenu({
        object: service,
        items: [
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


function renderServiceDetails(service) {
    selectedServiceDetailsId = service.id;

    $("#service-details-subtitle").text(
        (service.team_name || service.team_slug || "-") +
        " / " +
        (service.status || "unknown")
    );

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

function renderServiceDetailsLoading(service) {
    const body = $("#service-details-body");

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
    const body = $("#service-details-body");

    $("#service-details-subtitle").text(
        (service.team_name || service.team_slug || "-") +
        " / " +
        (service.status || "unknown")
    );

    body.empty();

    body.append(renderServiceDetailsHero(payload));

    body.append(
        $("<div>")
            .addClass("metric-grid service-detail-metrics")
            .append(serviceDetailsMetric("Open alerts", alerts.open || 0, "firing + acknowledged"))
            .append(serviceDetailsMetric("Critical open", alerts.critical_open || 0, "critical severity"))
            .append(serviceDetailsMetric("Maintenance", summary.maintenance_windows || 0, "active or upcoming"))
            .append(serviceDetailsMetric(
                "Dependencies",
                (summary.upstream_dependencies || 0) + " / " + (summary.downstream_dependencies || 0),
                "upstream / downstream"
            ))
    );

    body.append(renderServiceDetailsQuickActions(payload));
    body.append(renderServiceDetailsOwners(payload));
    body.append(renderServiceDetailsImpact(payload));
    body.append(renderServiceDetailsMaintenance(payload));
    body.append(renderServiceDetailsRunbooks(payload));
    body.append(renderServiceDetailsLinks(payload));
    body.append(renderServiceDetailsDependencies(payload));
    body.append(renderServiceDetailsAnalytics(analytics));
    body.append(renderServiceDetailsStatusHistory(payload));
}


function renderServiceDetailsImpact(payload) {
    const impact = payload.impact || {};
    const section = serviceDetailsSection(
        "Impact",
        "Effective status, primary reason, root cause and downstream blast radius."
    );

    section.append(
        $("<div>")
            .addClass("metric-grid service-detail-metrics")
            .append(serviceDetailsMetric(
                "Effective status",
                formatImpactStatusText(impact.effective_status || "unknown"),
                formatImpactReasonText(impact.primary_reason || "unknown")
            ))
            .append(serviceDetailsMetric(
                "Alert impact",
                formatImpactStatusText(impact.alert_impact_status || "operational"),
                "open " + Number(impact.open_alert_groups || 0) +
                " / critical " + Number(impact.critical_open_alert_groups || 0)
            ))
            .append(serviceDetailsMetric(
                "Dependency impact",
                formatImpactStatusText(impact.dependency_impact_status || "operational"),
                "upstream issues " + Number(impact.upstream_issues_count || 0)
            ))
            .append(serviceDetailsMetric(
                "Blast radius",
                Number((impact.blast_radius || {}).transitive_downstream || 0),
                "total downstream"
            ))
    );

    section.append(renderImpactExplanationPanel(impact, { compact: false }));
    section.append(renderImpactBlastRadiusPanel(impact, { compact: false }));

    return section;
}


function renderServiceDetailsHero(payload) {
    const service = payload.service || {};
    const section = $("<section>").addClass("service-detail-hero");

    const title = $("<div>")
        .addClass("service-detail-hero-title")
        .append($("<h3>").text(service.name || service.slug || ("Service #" + service.id)))
        .append($("<p>").text(service.description || service.slug || "No description"));

    const badges = $("<div>").addClass("service-detail-badges");

    badges.append(renderServiceStatusBadge(service));
    badges.append($("<span>").addClass("status-pill status-neutral").text(service.criticality || "unknown"));
    badges.append($("<span>").addClass("status-pill status-neutral").text(service.environment || "unknown"));
    badges.append($("<span>").addClass("status-pill status-neutral").text(service.tier || "unknown"));

    section.append(title);
    section.append(badges);

    section.append(
        $("<div>")
            .addClass("details-list")
            .append(serviceDetailsItem("Team", service.team_name || service.team_slug))
            .append(serviceDetailsItem("Type", service.service_type))
            .append(serviceDetailsItem("Status message", service.status_message))
            .append(serviceDetailsItem("Maintenance", window.AppMaintenanceBadges.text(service, "-")))
            .append(serviceDetailsItem("Default rotation", service.default_rotation_name))
            .append(serviceDetailsItem("Default policy", service.default_escalation_policy_name))
            .append(serviceDetailsItem("Enabled", service.enabled ? "Yes" : "No"))
    );

    return section;
}


function renderServiceDetailsQuickActions(payload) {
    const service = payload.service || {};
    const section = serviceDetailsSection(
        "Quick actions",
        "Common actions for this affected system."
    );

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
        label: "Create maintenance window",
        onClick: function () {
            openServiceMaintenanceWindow(service);
        },
    });

    appendIconActionIfAllowed(actions, service, {
        required: "write",
        icon: "fas fa-book",
        label: "Add runbook",
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
        label: "Add link",
        onClick: function () {
            resetServiceLinkForm();
            fillServiceSelect("#service-link-service", service.id);
            $("#service-link-service").prop("disabled", true);
            openAppModal("#service-link-modal");
        },
    });

    appendIconActionIfAllowed(actions, service, {
        required: "write",
        icon: "fas fa-users",
        label: "Add stakeholder",
        onClick: function () {
            openCreateServiceOwnerModal(service);
        },
    });

    appendIconActionIfAllowed(actions, service, {
        required: "write",
        icon: "fas fa-project-diagram",
        label: "Add dependency",
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
            .text("Open alerts")
            .on("click", function () {
                openServiceAlerts(service, {
                    onlyOpen: true,
                });
            })
    );

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn")
            .text("Open impact")
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
    $("#service-details-subtitle").text("Select a service");
    $("#service-details-body").html("<p>Click a service name to inspect ownership, defaults and status.</p>");
}


function restoreServiceDetails() {
    if (!servicesCache.length) {
        renderServiceDetailsEmpty();
        return;
    }

    if (selectedServiceDetailsId) {
        const selected = servicesCache.find(function (service) {
            return Number(service.id) === Number(selectedServiceDetailsId);
        });

        if (selected) {
            renderServiceDetails(selected);
            return;
        }
    }

    renderServiceDetails(servicesCache[0]);
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

    const isServicesTab = servicesPageTab === "services";

    $("#service-details-card").toggle(isServicesTab);
    $("#services-page-layout").toggleClass("is-full-width", !isServicesTab);

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
    } else if (servicesPageTab === "analytics") {
        if (!serviceAnalyticsCache.length) {
            refreshServiceAnalytics();
        } else {
            renderServiceAnalyticsSummary();
            renderServiceAnalyticsCharts();
            renderServiceAnalyticsTable();
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
    const policySelect = $("#service-default-policy");

    rotationSelect.empty().append($("<option>").val("").text("No default rotation"));
    policySelect.empty().append($("<option>").val("").text("No default policy"));

    if (!teamId) {
        if (typeof callback === "function") {
            callback();
        }
        return;
    }

    let rotationsLoaded = false;
    let policiesLoaded = false;

    function finishWhenReady() {
        if (!rotationsLoaded || !policiesLoaded) {
            return;
        }

        if (typeof callback === "function") {
            callback();
        }
    }

    apiGet("/api/rotations?team_id=" + encodeURIComponent(teamId), function (rotations) {
        asArray(rotations).forEach(function (rotation) {
            if (!rotation.enabled) {
                return;
            }

            rotationSelect.append(
                $("<option>")
                    .val(String(rotation.id))
                    .text(rotation.name)
            );
        });

        rotationsLoaded = true;
        finishWhenReady();
    });

    apiGet("/api/escalation-policies?team_id=" + encodeURIComponent(teamId), function (policies) {
        asArray(policies).forEach(function (policy) {
            if (!policy.enabled) {
                return;
            }

            policySelect.append(
                $("<option>")
                    .val(String(policy.id))
                    .text(policy.name)
            );
        });

        policiesLoaded = true;
        finishWhenReady();
    });
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
    $("#service-description").val("");
    $("#service-type").val("other");
    $("#service-environment").val("production");
    $("#service-criticality").val("medium");
    $("#service-tier").val("tier_3");
    $("#service-status").val("operational");
    $("#service-status-message").val("");
    $("#service-default-rotation").val("");
    $("#service-default-policy").val("");
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
        $("#service-description").val(service.description || "");
        $("#service-type").val(service.service_type || "other");
        $("#service-environment").val(service.environment || "production");
        $("#service-criticality").val(service.criticality || "medium");
        $("#service-tier").val(service.tier || "tier_3");
        $("#service-status").val(service.status || "operational");
        $("#service-status-message").val(service.status_message || "");
        $("#service-default-rotation").val(service.default_rotation_id || "");
        $("#service-default-policy").val(service.default_escalation_policy_id || "");
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
    $("#service-runbook-matchers").val(JSON.stringify({}, null, 2));
    $("#service-runbook-enabled").prop("checked", true);
}


function openCreateServiceRunbookModal() {
    resetServiceRunbookForm();
    openAppModal("#service-runbook-modal");
}


function editServiceRunbook(runbook) {
    $("#service-runbook-form-title").text("Edit runbook");
    $("#service-runbook-id").val(runbook.id);
    fillServiceSelect("#service-runbook-service", runbook.service_id);
    $("#service-runbook-service").prop("disabled", true);

    $("#service-runbook-title").val(runbook.title || "");
    $("#service-runbook-url").val(runbook.url || "");
    $("#service-runbook-severity").val(runbook.severity || "");
    $("#service-runbook-priority").val(runbook.priority || 100);
    $("#service-runbook-description").val(runbook.description || "");
    $("#service-runbook-matchers").val(JSON.stringify(runbook.matchers || {}, null, 2));
    $("#service-runbook-enabled").prop("checked", !!runbook.enabled);

    openAppModal("#service-runbook-modal");
}


function collectServiceRunbookPayload() {
    return {
        title: $("#service-runbook-title").val(),
        url: $("#service-runbook-url").val(),
        severity: $("#service-runbook-severity").val() || null,
        priority: Number($("#service-runbook-priority").val() || 100),
        description: $("#service-runbook-description").val() || null,
        matchers: parseJsonInput("#service-runbook-matchers", {}),
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
$(document).on("click", "#format-service-runbook-matchers", function () {
    formatJsonTextarea("#service-runbook-matchers", {}, "Runbook matchers JSON");
});

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

$(document).on(
    "click",
    "#service-form-modal, #service-link-modal, #service-runbook-modal, #service-dependency-modal, #service-owner-modal",
    function (event) {
        if (event.target !== this) {
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
                            const service = getServiceById(row.service_id);

                            if (service) {
                                selectedServiceDetailsId = service.id;
                                switchServicesPageTab("services");
                                renderServiceDetails(service);
                            }
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
$(document).on("input", "#service-analytics-search", renderServiceAnalyticsTable);
$(document).on("change", "#service-analytics-days", function () {
    invalidateServiceDetailsCache();
    refreshServiceAnalytics();
    refreshSelectedServiceDetails();
});
$(document).on("click", "#reload-service-analytics", refreshServiceAnalytics);
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

    const service = getServiceById(serviceId);

    if (!service) {
        return;
    }

    selectedServiceDetailsId = service.id;
    switchServicesPageTab("services");
    renderServiceDetails(service);
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

    if (!windows.length) {
        section.append($("<div>").addClass("empty-state compact").text("No active or upcoming maintenance windows."));
        return section;
    }

    const list = $("<div>").addClass("compact-list");

    windows.slice(0, 5).forEach(function (item) {
        list.append(
            $("<div>")
                .addClass("compact-list-item")
                .append(
                    $("<div>")
                        .addClass("compact-list-title")
                        .text(item.name || ("Window #" + item.id))
                )
                .append(
                    $("<div>")
                        .addClass("compact-list-meta")
                        .text(
                            (item.status || "scheduled") +
                            " / " +
                            (item.behavior || "-") +
                            " / " +
                            (item.starts_at || "-") +
                            " → " +
                            (item.ends_at || "-") +
                            " " +
                            (item.timezone || "UTC")
                        )
                )
        );
    });

    section.append(list);
    return section;
}


function renderServiceDetailsRunbooks(payload) {
    const runbooks = asArray(payload.runbooks);
    const section = serviceDetailsSection(
        "Runbooks",
        "Response instructions for this service."
    );

    if (!runbooks.length) {
        section.append($("<div>").addClass("empty-state compact").text("No runbooks."));
        return section;
    }

    const list = $("<div>").addClass("compact-list");

    runbooks.slice(0, 5).forEach(function (runbook) {
        list.append(
            $("<div>")
                .addClass("compact-list-item")
                .append(
                    $("<a>")
                        .addClass("compact-list-title")
                        .attr("href", runbook.url)
                        .attr("target", "_blank")
                        .attr("rel", "noopener noreferrer")
                        .text(runbook.title || runbook.url)
                )
                .append(
                    $("<div>")
                        .addClass("compact-list-meta")
                        .text((runbook.severity || "any severity") + " / priority " + (runbook.priority || 0))
                )
        );
    });

    section.append(list);
    return section;
}


function renderServiceDetailsLinks(payload) {
    const links = asArray(payload.links);
    const section = serviceDetailsSection(
        "Links",
        "Dashboards, logs, traces, repositories and documentation."
    );

    if (!links.length) {
        section.append($("<div>").addClass("empty-state compact").text("No links."));
        return section;
    }

    const list = $("<div>").addClass("compact-list");

    links.slice(0, 6).forEach(function (link) {
        list.append(
            $("<div>")
                .addClass("compact-list-item")
                .append(
                    $("<a>")
                        .addClass("compact-list-title")
                        .attr("href", link.url)
                        .attr("target", "_blank")
                        .attr("rel", "noopener noreferrer")
                        .text(link.label || link.url)
                )
                .append(
                    $("<div>")
                        .addClass("compact-list-meta")
                        .text((link.link_type || "other") + " / priority " + (link.priority || 0))
                )
        );
    });

    section.append(list);
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

    if (!upstream.length && !downstream.length) {
        section.append($("<div>").addClass("empty-state compact").text("No dependencies."));
        return section;
    }

    const wrapper = $("<div>").addClass("dependency-split");

    wrapper.append(renderServiceDependencyList("Depends on", upstream, true));
    wrapper.append(renderServiceDependencyList("Used by", downstream, false));

    section.append(wrapper);
    return section;
}


function renderServiceDependencyList(title, rows, upstream) {
    const box = $("<div>").addClass("dependency-box");

    box.append($("<h4>").text(title));

    if (!rows.length) {
        box.append($("<div>").addClass("empty-state compact").text("None"));
        return box;
    }

    const list = $("<div>").addClass("compact-list");

    rows.slice(0, 6).forEach(function (dependency) {
        const name = upstream
            ? (dependency.depends_on_service_name || dependency.depends_on_service_slug || "-")
            : (dependency.service_name || dependency.service_slug || "-");

        const status = upstream
            ? dependency.depends_on_service_status
            : dependency.service_status;

        list.append(
            $("<div>")
                .addClass("compact-list-item")
                .append($("<div>").addClass("compact-list-title").text(name))
                .append(
                    $("<div>")
                        .addClass("compact-list-meta")
                        .text(
                            (dependency.dependency_type || "dependency") +
                            " / " +
                            (dependency.criticality || "important") +
                            " / " +
                            (status || "unknown")
                        )
                )
        );
    });

    box.append(list);
    return box;
}


function renderServiceDetailsAnalytics(analytics) {
    const section = serviceDetailsSection(
        "Analytics",
        "Versioned analytics block prepared for charts and future widgets."
    );

    const widgets = analytics.widgets || {};
    const alertVolume = widgets.alert_volume || {};
    const status = widgets.status || {};

    section.append(
        $("<div>")
            .addClass("metric-grid service-detail-metrics")
            .append(serviceDetailsMetric("Recent alerts", alertVolume.recent || 0, "selected window"))
            .append(serviceDetailsMetric("Total alerts", alertVolume.total || 0, "all time"))
            .append(serviceDetailsMetric("Status changes", status.changes || 0, "recent history"))
            .append(serviceDetailsMetric("Analytics version", analytics.version || 1, "payload contract"))
    );

    return section;
}


function renderServiceDetailsStatusHistory(payload) {
    const history = asArray(payload.status_history);
    const section = serviceDetailsSection(
        "Status history",
        "Recent manual, alert-driven or maintenance-driven status changes."
    );

    if (!history.length) {
        section.append($("<div>").addClass("empty-state compact").text("No status history."));
        return section;
    }

    const list = $("<div>").addClass("compact-list");

    history.slice(0, 8).forEach(function (item) {
        list.append(
            $("<div>")
                .addClass("compact-list-item")
                .append(
                    $("<div>")
                        .addClass("compact-list-title")
                        .text((item.old_status || "-") + " → " + (item.new_status || "-"))
                )
                .append(
                    $("<div>")
                        .addClass("compact-list-meta")
                        .text((item.source || "manual") + " / " + (formatDateTime(item.created_at) || "-"))
                )
        );
    });

    section.append(list);
    return section;
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
    if (!selectedServiceDetailsId) {
        return;
    }

    const service = getServiceById(selectedServiceDetailsId);

    if (!service) {
        return;
    }

    renderServiceDetails(service);
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

    const section = serviceDetailsSection(
        "Default stakeholders",
        "Service owners copied to new incidents as incident stakeholders."
    );

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
                .addClass("empty-state")
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
                .append($("<th>").text("Active"))
                .append($("<th>").text("Actions"))
        )
    );

    const tbody = $("<tbody>");

    owners.forEach(function (owner) {
        tbody.append(renderServiceOwnerRow(service, owner));
    });

    table.append(tbody);

    section.append(
        $("<div>")
            .addClass("table-wrapper")
            .append(table)
    );

    return section;
}

function renderServiceOwnerRow(service, owner) {
    const row = $("<tr>");

    row.append(
        $("<td>")
            .addClass("table-cell-truncate")
            .attr("title", serviceOwnerDisplayName(owner))
            .text(serviceOwnerDisplayName(owner))
    );

    row.append(
        $("<td>").text(owner.role || "owner")
    );

    row.append(
        $("<td>").text(serviceOwnerNotificationText(owner))
    );

    row.append(
        $("<td>").append(
            renderStatusBadge(
                !!owner.active,
                "Active",
                "Inactive"
            )
        )
    );

    row.append(
        $("<td>")
            .addClass("actions-cell")
            .append(renderServiceOwnerActions(service, owner))
    );

    return row;
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
