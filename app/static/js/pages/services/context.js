// Service page tabs, shared context loading, links, runbooks and dependencies CRUD.

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
       applyServiceDependenciesView(serviceDependenciesView, { persist: false });
    } else if (servicesPageTab === "impact") {
        applyServiceImpactView(serviceImpactView);

        if (!serviceImpactCache.length) {
            refreshServiceImpact();
        } else if (serviceImpactView === "current") {
            renderImpactSummary(serviceImpactPayload ? (serviceImpactPayload.summary || {}) : {});
            renderServiceImpactTable();
        } else {
            refreshServiceImpactHistory();
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

        if (servicesPageTab === "dependencies") {
            applyServiceDependenciesView(serviceDependenciesView, {persist: false});
        } else {
            renderAllServiceDependenciesTable();
        }
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
            [
                dependency.service_name,
                dependency.service_slug,
                dependency.team_name,
                dependency.team_slug,
                dependency.depends_on_service_name,
                dependency.depends_on_service_slug,
                dependency.dependency_type,
                dependency.criticality,
                dependency.depends_on_service_status,
                dependency.correlation_enabled === false ? "correlation off" : "correlation on",
                dependency.propagation_delay_seconds,
                dependency.description,
            ]
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
        const correlationLabel = dependency.correlation_enabled === false
            ? "Correlation off"
            : "Correlation " + (dependency.propagation_delay_seconds || 300) + "s";

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
                .append(
                    $("<td>")
                        .addClass("table-cell-truncate-wide")
                        .append($("<div>").text(dependency.description || "-"))
                        .append($("<div>").addClass("row-subtitle").text(correlationLabel))
                )
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
    $("#service-dependency-correlation-enabled").prop("checked", true);
    $("#service-dependency-propagation-delay-seconds").val("300");
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
        $("#service-dependency-correlation-enabled").prop("checked", dependency.correlation_enabled !== false);
        $("#service-dependency-propagation-delay-seconds").val(dependency.propagation_delay_seconds || 300);
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
        correlation_enabled: $("#service-dependency-correlation-enabled").is(":checked"),
        propagation_delay_seconds: Number($("#service-dependency-propagation-delay-seconds").val() || 300),
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
