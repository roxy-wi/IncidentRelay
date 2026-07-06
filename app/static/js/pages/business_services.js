let businessServicesCache = [];
let businessServiceDetailsCache = null;
let businessServiceTeamsCache = [];
let businessServiceGroupsCache = [];
let businessServiceTechnicalServicesCache = [];
let selectedBusinessServiceId = null;
let businessServicesLoadSerial = 0;
let businessServiceDetailsLoadSerial = 0;


function businessServiceUserIsAdmin() {
    return !!(currentUser && currentUser.is_admin);
}


function initializeBusinessServiceSlugBinding() {
    if (!window.AppSlug) {
        return;
    }

    window.AppSlug.bind("#business-service-name", "#business-service-slug", {
        manualWhenHasValue: true,
    });
}


function normalizeBusinessServiceId(value) {
    const numberValue = Number(value);

    return Number.isFinite(numberValue) && numberValue > 0 ? numberValue : null;
}


function businessServiceUniqueById(items) {
    const seen = {};
    const result = [];

    asArray(items).forEach(function (item) {
        const id = normalizeBusinessServiceId(item.id || item.group_id);

        if (!id || seen[id]) {
            return;
        }

        seen[id] = true;
        result.push(item);
    });

    return result;
}


function refreshBusinessServiceGroupsCache() {
    const groups = [];

    asArray(currentUser ? currentUser.groups : []).forEach(function (group) {
        const groupId = normalizeBusinessServiceId(group.group_id || group.id);

        if (!groupId) {
            return;
        }

        groups.push({
            id: groupId,
            slug: group.group_slug || group.slug || "",
            name: group.group_name || group.name || group.group_slug || group.slug || ("Group " + groupId)
        });
    });

    businessServiceTeamsCache.forEach(function (team) {
        const groupId = normalizeBusinessServiceId(team.group_id);

        if (!groupId) {
            return;
        }

        groups.push({
            id: groupId,
            slug: team.group_slug || "",
            name: team.group_name || team.group_slug || ("Group " + groupId)
        });
    });

    businessServiceGroupsCache = businessServiceUniqueById(groups);
}


function selectedBusinessServiceListGroupId() {
    const selectedTeam = normalizeBusinessServiceId($("#global-team-filter").val());

    if (selectedTeam) {
        const team = businessServiceTeamsCache.find(function (item) {
            return Number(item.id) === selectedTeam;
        });

        return team ? normalizeBusinessServiceId(team.group_id) : null;
    }

    if (businessServiceUserIsAdmin()) {
        return null;
    }

    if (currentUser && currentUser.active_group_id) {
        return normalizeBusinessServiceId(currentUser.active_group_id);
    }

    const groups = asArray(currentUser ? currentUser.groups : []);

    return groups.length ? normalizeBusinessServiceId(groups[0].group_id || groups[0].id) : null;
}


function selectedBusinessServiceFormGroupId() {
    const selectedGroup = normalizeBusinessServiceId($("#business-service-group").val());

    if (selectedGroup) {
        return selectedGroup;
    }

    const listGroup = selectedBusinessServiceListGroupId();

    if (listGroup) {
        return listGroup;
    }

    if (currentUser && currentUser.active_group_id) {
        return normalizeBusinessServiceId(currentUser.active_group_id);
    }

    return businessServiceGroupsCache.length ? normalizeBusinessServiceId(businessServiceGroupsCache[0].id) : null;
}


function businessServiceListQuery() {
    const groupId = selectedBusinessServiceListGroupId();

    return groupId ? "?group_id=" + encodeURIComponent(groupId) : "";
}


function businessServiceStatusLabel(status) {
    const labels = {
        unknown: "Unknown",
        operational: "Operational",
        degraded: "Degraded",
        partial_outage: "Partial outage",
        major_outage: "Major outage",
        maintenance: "Maintenance"
    };

    return labels[status] || status || "-";
}


function businessServiceStatusBadgeVariant(status) {
    return uiStatusBadgeVariantForStatus(status || "unknown");
}


function businessServiceStatusPill(status) {
    const normalized = status || "unknown";

    return uiStatusBadge(
        businessServiceStatusLabel(normalized),
        businessServiceStatusBadgeVariant(normalized)
    );
}


function businessServiceComponentCount(item) {
    if (typeof item.components_count === "number") {
        return item.components_count;
    }

    if (Array.isArray(item.components)) {
        return item.components.length;
    }

    return 0;
}



function fillBusinessServiceGroupSelect(selectedId) {
    const select = $("#business-service-group");

    select.empty();

    businessServiceGroupsCache.forEach(function (group) {
        select.append(
            $("<option>")
                .val(String(group.id))
                .text(group.name || group.slug || ("Group " + group.id))
        );
    });

    if (selectedId) {
        select.val(String(selectedId));
    } else if (businessServiceGroupsCache.length) {
        select.val(String(businessServiceGroupsCache[0].id));
    }
}


function loadBusinessServiceTeams(callback) {
    businessServiceTeamsCache = [];

    apiGet("/api/teams", function (teams) {
        businessServiceTeamsCache = asArray(teams);
        refreshBusinessServiceGroupsCache();

        if (typeof callback === "function") {
            callback();
        }
    });
}


function loadBusinessServiceTechnicalServices(groupId, callback) {
    businessServiceTechnicalServicesCache = [];

    apiGet("/api/services", function (services) {
        businessServiceTechnicalServicesCache = asArray(services).filter(function (service) {
            return !groupId || Number(service.group_id) === Number(groupId);
        });

        if (typeof callback === "function") {
            callback();
        }
    });
}


function fillBusinessServiceOwnerTeamSelect(selectedId) {
    const select = $("#business-service-owner-team");
    const groupId = selectedBusinessServiceFormGroupId();

    select.empty();
    select.append($("<option>").val("").text("No owner team"));

    businessServiceTeamsCache.forEach(function (team) {
        if (!team.active || (groupId && Number(team.group_id) !== Number(groupId))) {
            return;
        }

        select.append(
            $("<option>")
                .val(String(team.id))
                .text((team.slug || team.name || "team") + " / " + (team.name || team.slug || ""))
        );
    });

    if (selectedId) {
        select.val(String(selectedId));
    }
}


function fillBusinessServiceComponentServiceSelect(selectedId) {
    const select = $("#business-service-component-service");
    const groupId = businessServiceDetailsCache ? businessServiceDetailsCache.group_id : selectedBusinessServiceFormGroupId();

    select.empty();
    select.append($("<option>").val("").text("Select technical service"));

    businessServiceTechnicalServicesCache.forEach(function (service) {
        if (!service.enabled || (groupId && Number(service.group_id) !== Number(groupId))) {
            return;
        }

        select.append(
            $("<option>")
                .val(String(service.id))
                .text((service.team_slug || service.team_name || "-") + " / " + service.name + " (" + service.slug + ")")
        );
    });

    if (selectedId) {
        select.val(String(selectedId));
    }
}

function loadBusinessServices() {
    const serial = ++businessServicesLoadSerial;

    initializeBusinessServiceSlugBinding();

    loadBusinessServiceTeams(function () {
        const groupId = selectedBusinessServiceListGroupId();

        loadBusinessServiceTechnicalServices(groupId, function () {
            apiGet("/api/business-services" + businessServiceListQuery(), function (items) {
                if (serial !== businessServicesLoadSerial) {
                    return;
                }

                businessServicesCache = asArray(items);
                renderBusinessServicesSummary();
                renderBusinessServicesTable();
            });
        });
    });
}


function getFilteredBusinessServices() {
    const query = String($("#business-services-search").val() || "").trim().toLowerCase();
    const status = $("#business-services-status-filter").val();
    const publicFilter = $("#business-services-public-filter").val();

    return businessServicesCache.filter(function (item) {
        if (status && item.status !== status) {
            return false;
        }

        if (publicFilter === "public" && !item.public) {
            return false;
        }

        if (publicFilter === "private" && item.public) {
            return false;
        }

        if (!query) {
            return true;
        }

        return [
            item.name,
            item.slug,
            item.description,
            item.group_name,
            item.group_slug,
            item.owner_team_name,
            item.owner_team_slug,
            item.status,
            item.criticality,
            item.tier,
            item.public_name,
            item.public_description
        ].join(" ").toLowerCase().indexOf(query) !== -1;
    });
}


function renderBusinessServicesSummary() {
    const total = businessServicesCache.length;
    const filtered = getFilteredBusinessServices().length;
    const operational = businessServicesCache.filter(function (item) {
        return item.status === "operational";
    }).length;
    const affected = businessServicesCache.filter(function (item) {
        return ["degraded", "partial_outage", "major_outage", "maintenance"].indexOf(item.status) !== -1;
    }).length;
    const publicCount = businessServicesCache.filter(function (item) {
        return !!item.public;
    }).length;

    $("#business-services-total").text(total);
    $("#business-services-operational").text(operational);
    $("#business-services-affected").text(affected);
    $("#business-services-public").text(publicCount);
    $("#business-services-total-count").text(total);
    $("#business-services-filtered-count").text(filtered);
}


function renderBusinessServicesTable() {
    const tbody = $("#business-services-table");
    const items = getFilteredBusinessServices();

    $("#business-services-filtered-count").text(items.length);
    $("#business-services-total-count").text(businessServicesCache.length);

    tbody.empty();

    if (!items.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>").attr("colspan", 9).addClass("empty-cell").text("No business services")
            )
        );
        return;
    }

    items.forEach(function (item) {
        tbody.append(
            $("<tr>")
                .toggleClass("row-disabled", !item.enabled)
                .append(
                    $("<td>")
                        .addClass("table-cell-truncate-wide")
                        .append(
                            $("<button>")
                                .attr("type", "button")
                                .addClass("name-button")
                                .text(item.name || item.slug || ("#" + item.id))
                                .on("click", function () {
                                    openBusinessServiceDetailsModal(item.id);
                                })
                        )
                        .append($("<div>").addClass("row-subtitle").text(item.description || item.slug || ""))
                )
                .append($("<td>").text(item.group_name || item.group_slug || "-"))
                .append($("<td>").text(item.owner_team_name || item.owner_team_slug || "-"))
                .append($("<td>").append(businessServiceStatusPill(item.status)))
                .append($("<td>").text(item.criticality || "-"))
                .append($("<td>").text(item.tier || "-"))
                .append($("<td>").text(businessServiceComponentCount(item)))
                .append($("<td>").append(renderStatusBadge(!!item.public, "Public", "Private")))
                .append($("<td>").addClass("actions-cell").append(renderBusinessServiceActions(item)))
        );
    });
}


function renderBusinessServiceActions(item) {
    return makeActionMenu({
        object: item,
        items: [
            {
                label: "Details",
                icon: "fas fa-info-circle",
                onClick: function () {
                    openBusinessServiceDetailsModal(item.id);
                }
            },
            {
                label: "Edit",
                icon: "fas fa-edit",
                required: "write",
                onClick: function () {
                    editBusinessService(item);
                }
            },
            {
                label: item.enabled ? "Disable" : "Enable",
                icon: item.enabled ? "fas fa-pause" : "fas fa-play",
                required: "write",
                danger: item.enabled,
                onClick: function () {
                    setBusinessServiceEnabled(item, !item.enabled);
                }
            },
            {
                label: "Delete",
                icon: "fas fa-trash",
                required: "write",
                danger: true,
                onClick: function () {
                    deleteBusinessService(item);
                }
            }
        ]
    });
}


function renderBusinessServiceComponentActions(component) {
    return makeActionMenu({
        object: businessServiceDetailsCache || component,
        items: [
            {
                label: "Edit",
                icon: "fas fa-edit",
                required: "write",
                onClick: function () {
                    editBusinessServiceComponent(component);
                }
            },
            {
                label: component.enabled ? "Disable" : "Enable",
                icon: component.enabled ? "fas fa-pause" : "fas fa-play",
                required: "write",
                danger: component.enabled,
                onClick: function () {
                    setBusinessServiceComponentEnabled(component, !component.enabled);
                }
            },
            {
                label: "Delete",
                icon: "fas fa-trash",
                required: "write",
                danger: true,
                onClick: function () {
                    deleteBusinessServiceComponent(component);
                }
            }
        ]
    });
}

function setBusinessServiceComponentEnabled(component, enabled) {
    const payload = {
        service_id: component.service_id,
        component_type: component.component_type || "technical_service",
        criticality: component.criticality || "required",
        impact_weight: Number(component.impact_weight || 100),
        position: Number(component.position || 0),
        status_rule: component.status_rule || "inherit",
        description: component.description || null,
        enabled: enabled
    };

    apiPut("/api/business-services/components/" + component.id, payload, function () {
        if (selectedBusinessServiceId) {
            openBusinessServiceDetailsModal(selectedBusinessServiceId);
        }
    });
}


function showBusinessServiceDetailsLoadError(message) {
    if (typeof showAppError === "function") {
        showAppError(message);
        return;
    }

    console.error(message);
}


function openBusinessServiceDetailsModal(id) {
    if (!id) {
        return;
    }

    const serial = ++businessServiceDetailsLoadSerial;

    selectedBusinessServiceId = item.id;
    businessServiceDetailsCache = item;

    replaceBusinessServiceInCache(item);
    renderBusinessServicesSummary();
    renderBusinessServicesTable();

    renderBusinessServiceDetails(item);
    showBusinessServiceDetailsModal();

    apiGet("/api/business-services/" + id, function (item) {
        if (serial !== businessServiceDetailsLoadSerial) {
            return;
        }

        if (!item || !item.id) {
            showBusinessServiceDetailsLoadError("Business service details were not found.");
            return;
        }

        selectedBusinessServiceId = item.id;
        businessServiceDetailsCache = item;

        renderBusinessServiceDetails(item);
        showBusinessServiceDetailsModal();
    }, function (xhr) {
        if (serial !== businessServiceDetailsLoadSerial) {
            return;
        }

        showBusinessServiceDetailsLoadError(apiErrorMessage(xhr, "Failed to load business service details."));
    });
}


function showBusinessServiceDetailsModal() {
    const modal = $("#business-service-details-modal");
    const dialog = modal.find(".app-modal-dialog");

    dialog.css({
        width: "calc(100vw - 48px)",
        maxWidth: "calc(100vw - 48px)"
    });

    modal.find(".table-wrapper").css({
        width: "100%"
    });

    openAppModal("#business-service-details-modal");

    if (typeof scheduleStickyTableScrollbars === "function") {
        setTimeout(scheduleStickyTableScrollbars, 0);
        setTimeout(scheduleStickyTableScrollbars, 250);
    }
}


function renderBusinessServiceDetails(item) {
    if (!item || !item.id) {
        return;
    }

    businessServiceDetailsCache = item;

    const body = $("#business-service-details-body");
    const components = Object.prototype.hasOwnProperty.call(item, "components")
        ? asArray(item.components)
        : [];
    const history = Object.prototype.hasOwnProperty.call(item, "status_history")
        ? asArray(item.status_history)
        : [];

    $("#business-service-details-title").text(item.name || item.slug || "Business service");
    $("#business-service-details-subtitle").text(
        (item.public_name || item.name || "") + " · " + businessServiceStatusLabel(item.status)
    );
    $("#business-service-recalculate").prop("disabled", false);
    $("#open-business-service-component-modal").prop("disabled", false);

    body.empty();
    body.append(detailItem("Status", businessServiceStatusLabel(item.status)));
    body.append(detailItem("Status message", item.status_message || "-"));
    body.append(detailItem("Group", item.group_name || item.group_slug || "-"));
    body.append(detailItem("Owner team", item.owner_team_name || item.owner_team_slug || "-"));
    body.append(detailItem("Criticality", item.criticality || "-"));
    body.append(detailItem("Tier", item.tier || "-"));
    body.append(detailItem("Visibility", item.public ? "Public" : "Private"));
    body.append(detailItem("Components", components.length || businessServiceComponentCount(item)));

    renderBusinessServiceManualStatus(item);
    renderBusinessServiceComponents(components);
    renderBusinessServiceHistory(history);
}


function detailItem(label, value) {
    return $("<div>")
        .addClass("details-item")
        .append($("<div>").addClass("details-label").text(label))
        .append($("<div>").addClass("details-value").text(value));
}


function renderBusinessServiceComponents(components) {
    const tbody = $("#business-service-components-table");

    tbody.empty();

    if (!components.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>").attr("colspan", 7).addClass("empty-cell").text("No components")
            )
        );
        return;
    }

    components.forEach(function (component) {
        tbody.append(
            $("<tr>")
                .toggleClass("row-disabled", !component.enabled)
                .append(
                    $("<td>")
                        .addClass("table-cell-truncate-wide")
                        .text(component.service_name || component.service_slug || "-")
                        .append($("<div>").addClass("row-subtitle").text(component.service_slug || ""))
                )
                .append($("<td>").text(component.team_name || component.team_slug || "-"))
                .append($("<td>").append(businessServiceStatusPill(component.effective_status || component.service_status)))
                .append($("<td>").text(component.criticality || "-"))
                .append($("<td>").text(component.impact_weight || 0))
                .append($("<td>").addClass("table-cell-truncate-wide").text(component.description || "-"))
                .append($("<td>").addClass("actions-cell").append(renderBusinessServiceComponentActions(component)))
        );
    });
}


function renderBusinessServiceHistory(history) {
    const tbody = $("#business-service-history-table");

    tbody.empty();

    if (!history.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>").attr("colspan", 5).addClass("empty-cell").text("No status history")
            )
        );
        return;
    }

    history.forEach(function (item) {
        tbody.append(
            $("<tr>")
                .append($("<td>").text(formatDateTimeMinutes(item.created_at)))
                .append($("<td>").text(businessServiceStatusLabel(item.old_status)))
                .append($("<td>").append(businessServiceStatusPill(item.new_status)))
                .append($("<td>").text(item.impact_score || 0))
                .append($("<td>").addClass("table-cell-truncate-wide").text(item.message || "-"))
        );
    });
}


function resetBusinessServiceForm() {
    const groupId = selectedBusinessServiceFormGroupId();

    $("#business-service-form-title").text("Create business service");
    $("#business-service-id").val("");
    fillBusinessServiceGroupSelect(groupId);
    fillBusinessServiceOwnerTeamSelect(null);
    $("#business-service-name").val("");
    $("#business-service-slug").val("");

    if (window.AppSlug) {
        window.AppSlug.reset("#business-service-slug", {manual: false});
    }

    $("#business-service-description").val("");
    $("#business-service-criticality").val("important");
    $("#business-service-tier").val("tier_2");
    $("#business-service-public-name").val("");
    $("#business-service-public-description").val("");
    $("#business-service-public-order").val("100");
    $("#business-service-public").prop("checked", true);
    $("#business-service-enabled").prop("checked", true);
}


function openCreateBusinessServiceModal() {
    resetBusinessServiceForm();
    openAppModal("#business-service-modal");
}


function editBusinessService(item) {
    const groupId = Number(item.group_id);

    $("#business-service-form-title").text("Edit business service");
    $("#business-service-id").val(item.id);
    fillBusinessServiceGroupSelect(groupId);
    fillBusinessServiceOwnerTeamSelect(item.owner_team_id);

    $("#business-service-name").val(item.name || "");
    $("#business-service-slug").val(item.slug || "");

    if (window.AppSlug) {
        window.AppSlug.reset("#business-service-slug", {manual: true});
    }

    $("#business-service-description").val(item.description || "");
    $("#business-service-criticality").val(item.criticality || "important");
    $("#business-service-tier").val(item.tier || "tier_2");
    $("#business-service-public-name").val(item.public_name || "");
    $("#business-service-public-description").val(item.public_description || "");
    $("#business-service-public-order").val(item.public_order || 100);
    $("#business-service-public").prop("checked", item.public !== false);
    $("#business-service-enabled").prop("checked", item.enabled !== false);
    openAppModal("#business-service-modal");
}


function collectBusinessServicePayload() {
    return {
        group_id: Number($("#business-service-group").val()),
        owner_team_id: $("#business-service-owner-team").val() ? Number($("#business-service-owner-team").val()) : null,
        slug: $("#business-service-slug").val(),
        name: $("#business-service-name").val(),
        description: $("#business-service-description").val() || null,
        criticality: $("#business-service-criticality").val() || "important",
        tier: $("#business-service-tier").val() || "tier_2",
        public: $("#business-service-public").is(":checked"),
        public_name: $("#business-service-public-name").val() || null,
        public_description: $("#business-service-public-description").val() || null,
        public_order: Number($("#business-service-public-order").val() || 100),
        labels: {},
        metadata: {},
        enabled: $("#business-service-enabled").is(":checked")
    };
}


function saveBusinessService() {
    const id = $("#business-service-id").val();
    const payload = collectBusinessServicePayload();

    if (!payload.group_id) {
        showAppError("Group is required.");
        return;
    }

    if (!payload.name) {
        showAppError("Name is required.");
        return;
    }

    if (!payload.slug) {
        showAppError("Slug is required.");
        return;
    }

    if (id) {
        apiPut("/api/business-services/" + id, payload, function () {
            closeAppModal("#business-service-modal");
            loadBusinessServices();
        });
        return;
    }

    apiPost("/api/business-services", payload, function (item) {
        closeAppModal("#business-service-modal");
        selectedBusinessServiceId = item.id;
        loadBusinessServices();
    });
}


function deleteBusinessService(item) {
    showAppConfirm({
        title: "Delete this business service?",
        message: "Delete business service \"" + (item.name || item.slug || item.id) + "\"?",
        confirmText: "Delete business service",
        confirmClass: "btn-danger"
    }).done(function () {
        apiDelete("/api/business-services/" + item.id, function () {
            if (Number(selectedBusinessServiceId) === Number(item.id)) {
                selectedBusinessServiceId = null;
                businessServiceDetailsCache = null;
                closeAppModal("#business-service-details-modal");
            }

            loadBusinessServices();
        });
    });
}



function businessServicePayloadFromItem(item, enabled) {
    return {
        group_id: Number(item.group_id),
        owner_team_id: item.owner_team_id ? Number(item.owner_team_id) : null,
        slug: item.slug,
        name: item.name,
        description: item.description || null,
        criticality: item.criticality || "important",
        tier: item.tier || "tier_2",
        public: item.public !== false,
        public_name: item.public_name || null,
        public_description: item.public_description || null,
        public_order: Number(item.public_order || 100),
        labels: item.labels || {},
        metadata: item.metadata || {},
        enabled: enabled
    };
}


function setBusinessServiceEnabled(item, enabled) {
    const payload = businessServicePayloadFromItem(item, enabled);

    apiPut("/api/business-services/" + item.id, payload, function (updatedItem) {
        replaceBusinessServiceInCache(updatedItem || Object.assign({}, item, {enabled: enabled}));
        renderBusinessServicesSummary();
        renderBusinessServicesTable();

        if (Number(selectedBusinessServiceId) === Number(item.id)) {
            openBusinessServiceDetailsModal(item.id);
        } else {
            loadBusinessServices();
        }
    });
}


function resetBusinessServiceComponentForm() {
    $("#business-service-component-form-title").text("Add component");
    $("#business-service-component-id").val("");
    fillBusinessServiceComponentServiceSelect(null);
    $("#business-service-component-criticality").val("required");
    $("#business-service-component-weight").val("100");
    $("#business-service-component-position").val("0");
    $("#business-service-component-description").val("");
    $("#business-service-component-enabled").prop("checked", true);
}


function openBusinessServiceComponentModal() {
    if (!businessServiceDetailsCache) {
        showAppError("Select a business service first.");
        return;
    }

    loadBusinessServiceTechnicalServices(businessServiceDetailsCache.group_id, function () {
        resetBusinessServiceComponentForm();
        openAppModal("#business-service-component-modal");
    });
}


function editBusinessServiceComponent(component) {
    loadBusinessServiceTechnicalServices(businessServiceDetailsCache ? businessServiceDetailsCache.group_id : null, function () {
        $("#business-service-component-form-title").text("Edit component");
        $("#business-service-component-id").val(component.id);
        fillBusinessServiceComponentServiceSelect(component.service_id);
        $("#business-service-component-criticality").val(component.criticality || "required");
        $("#business-service-component-weight").val(component.impact_weight || 100);
        $("#business-service-component-position").val(component.position || 0);
        $("#business-service-component-description").val(component.description || "");
        $("#business-service-component-enabled").prop("checked", component.enabled !== false);
        openAppModal("#business-service-component-modal");
    });
}


function collectBusinessServiceComponentPayload() {
    return {
        service_id: Number($("#business-service-component-service").val()),
        component_type: "technical_service",
        criticality: $("#business-service-component-criticality").val() || "required",
        impact_weight: Number($("#business-service-component-weight").val() || 100),
        position: Number($("#business-service-component-position").val() || 0),
        status_rule: "inherit",
        description: $("#business-service-component-description").val() || null,
        enabled: $("#business-service-component-enabled").is(":checked")
    };
}


function saveBusinessServiceComponent() {
    if (!businessServiceDetailsCache) {
        showAppError("Select a business service first.");
        return;
    }

    const id = $("#business-service-component-id").val();
    const payload = collectBusinessServiceComponentPayload();

    if (!payload.service_id) {
        showAppError("Technical service is required.");
        return;
    }

    if (id) {
        apiPut("/api/business-services/components/" + id, payload, function () {
            closeAppModal("#business-service-component-modal");
            openBusinessServiceDetailsModal(selectedBusinessServiceId);
        });
        return;
    }

    apiPost("/api/business-services/" + businessServiceDetailsCache.id + "/components", payload, function () {
        closeAppModal("#business-service-component-modal");
        openBusinessServiceDetailsModal(selectedBusinessServiceId);
    });
}


function deleteBusinessServiceComponent(component) {
    showAppConfirm({
        title: "Delete this component?",
        message: "Remove technical service \"" + (component.service_name || component.service_slug || component.id) + "\" from this business service?",
        confirmText: "Delete component",
        confirmClass: "btn-danger"
    }).done(function () {
        apiDelete("/api/business-services/components/" + component.id, function () {
            openBusinessServiceDetailsModal(selectedBusinessServiceId);
        });
    });
}


function recalculateBusinessService() {
    if (!selectedBusinessServiceId) {
        return;
    }

    apiPost("/api/business-services/" + selectedBusinessServiceId + "/recalculate", {}, function (item) {
        businessServiceDetailsCache = item;
        replaceBusinessServiceInCache(item);
        renderBusinessServicesSummary();
        renderBusinessServicesTable();
        renderBusinessServiceDetails(item);
    });
}


$(document).on("click", "#reload-business-services", loadBusinessServices);

$(document).on("input", "#business-services-search", function () {
    renderBusinessServicesTable();
});

$(document).on("change", "#business-services-status-filter", function () {
    renderBusinessServicesTable();
});

$(document).on("change", "#business-services-public-filter", function () {
    renderBusinessServicesTable();
});

$(document).on("click", "#open-business-service-create-modal", openCreateBusinessServiceModal);
$(document).on("click", "#save-business-service", saveBusinessService);
$(document).on("click", "#reset-business-service-form", resetBusinessServiceForm);

$(document).on("click", "#close-business-service-details-modal", function () {
    closeAppModal("#business-service-details-modal");
});

$(document).on("click", "#close-business-service-modal", function () {
    closeAppModal("#business-service-modal");
});

$(document).on("click", "#close-business-service-component-modal", function () {
    closeAppModal("#business-service-component-modal");
});

$(document).on("change", "#business-service-group", function () {
    fillBusinessServiceOwnerTeamSelect(null);
});

$(document).on("click", "#open-business-service-component-modal", openBusinessServiceComponentModal);
$(document).on("click", "#save-business-service-component", saveBusinessServiceComponent);
$(document).on("click", "#reset-business-service-component-form", resetBusinessServiceComponentForm);
$(document).on("click", "#business-service-recalculate", recalculateBusinessService);

$(document).on("app:page-loaded", function () {
    if (!$("#view-business-services").is(":visible")) {
        closeAppModal("#business-service-details-modal");
        closeAppModal("#business-service-modal");
        closeAppModal("#business-service-component-modal");
    }
});

function businessServiceFormatDateTime(value) {
    if (!value) {
        return "-";
    }

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return value;
    }

    return date.toLocaleString();
}


function businessServiceManualStatusIsoValue() {
    const value = $("#business-service-manual-status-until").val();

    if (!value) {
        return null;
    }

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return null;
    }

    return date.toISOString();
}


function showBusinessServiceManualStatusError(message) {
    const node = $("#business-service-manual-status-error");

    if (!message) {
        node.hide().text("");
        return;
    }

    node.text(message).show();
}


function replaceBusinessServiceInCache(item) {
    if (!item || !item.id) {
        return;
    }

    let replaced = false;

    businessServicesCache = asArray(businessServicesCache).map(function (existing) {
        if (Number(existing.id) !== Number(item.id)) {
            return existing;
        }

        replaced = true;
        return item;
    });

    if (!replaced) {
        businessServicesCache.push(item);
    }
}

function renderBusinessServiceManualStatus(details) {
    const source = details.status_source || "calculated";
    const manualActive = Boolean(details.manual_status_active);

    $("#business-service-details-status-source").text(
        source === "manual" ? "Manual" : "Calculated"
    );

    $("#business-service-details-manual-status").text(
        manualActive
            ? businessServiceStatusLabel(details.manual_status)
            : "No active override"
    );

    $("#business-service-details-manual-message").text(
        details.manual_status_message || "-"
    );

    $("#business-service-details-manual-until").text(
        details.manual_status_until
            ? businessServiceFormatDateTime(details.manual_status_until)
            : "Until cleared manually"
    );

    $("#business-service-manual-status").val(
        details.manual_status || details.status || "degraded"
    );

    $("#business-service-manual-status-message").val(
        details.manual_status_message || ""
    );

    $("#business-service-manual-status-until").val("");

    $("#clear-business-service-manual-status").prop("disabled", !manualActive);

    showBusinessServiceManualStatusError(null);
}

function selectedBusinessServiceDetailsId() {
    if (businessServiceDetailsCache && businessServiceDetailsCache.id) {
        return businessServiceDetailsCache.id;
    }

    return selectedBusinessServiceId;
}


function setBusinessServiceManualStatus() {
    const id = selectedBusinessServiceDetailsId();

    if (!id) {
        showBusinessServiceManualStatusError("Business service is not selected.");
        return;
    }

    const until = businessServiceManualStatusIsoValue();

    if ($("#business-service-manual-status-until").val() && !until) {
        showBusinessServiceManualStatusError("Manual status expiration time is invalid.");
        return;
    }

    if (until && new Date(until).getTime() <= Date.now()) {
        showBusinessServiceManualStatusError("Manual status expiration must be in the future.");
        return;
    }

    showBusinessServiceManualStatusError(null);

    const payload = {
        status: $("#business-service-manual-status").val(),
        message: $("#business-service-manual-status-message").val() || null,
        until: until
    };

    $("#set-business-service-manual-status").prop("disabled", true);

    apiPost("/api/business-services/" + id + "/manual-status", payload, function (item) {
        $("#set-business-service-manual-status").prop("disabled", false);

        businessServiceDetailsCache = item;
        replaceBusinessServiceInCache(item);

        renderBusinessServicesSummary();
        renderBusinessServicesTable();
        renderBusinessServiceDetails(item);
    }, function (xhr) {
        $("#set-business-service-manual-status").prop("disabled", false);
        showBusinessServiceManualStatusError(apiErrorMessage(xhr, "Failed to set manual status."));
    });
}


function clearBusinessServiceManualStatus() {
    const id = selectedBusinessServiceDetailsId();

    if (!id) {
        showBusinessServiceManualStatusError("Business service is not selected.");
        return;
    }

    showBusinessServiceManualStatusError(null);

    $("#clear-business-service-manual-status").prop("disabled", true);

    apiDelete("/api/business-services/" + id + "/manual-status", function (item) {
        $("#clear-business-service-manual-status").prop("disabled", false);

        businessServiceDetailsCache = item;
        replaceBusinessServiceInCache(item);

        renderBusinessServicesSummary();
        renderBusinessServicesTable();
        renderBusinessServiceDetails(item);
    }, function (xhr) {
        $("#clear-business-service-manual-status").prop("disabled", false);
        showBusinessServiceManualStatusError(apiErrorMessage(xhr, "Failed to clear manual status."));
    });
}

$(document).on("click", "#set-business-service-manual-status", function () {
    setBusinessServiceManualStatus();
});


$(document).on("click", "#clear-business-service-manual-status", function () {
    clearBusinessServiceManualStatus();
});
