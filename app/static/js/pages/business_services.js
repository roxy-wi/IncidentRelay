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
            name: group.group_name || group.name || group.group_slug || group.slug || i18n.t("business_services.fallback.group", {id: groupId})
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
            name: team.group_name || team.group_slug || i18n.t("business_services.fallback.group", {id: groupId})
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
    const normalized = status || "unknown";
    const key = "business_services.status." + normalized;

    return i18n.t(key, {}, normalized || "-");
}


function businessServiceCriticalityLabel(value) {
    if (!value) {
        return "-";
    }

    return i18n.t("business_services.criticality." + value, {}, value);
}


function businessServiceTierLabel(value) {
    if (!value) {
        return "-";
    }

    return i18n.t("business_services.tier." + value, {}, value);
}


function businessServiceStatusMessageLabel(message) {
    if (!message) {
        return "-";
    }

    if (message === "Calculated status: no enabled components") {
        return i18n.t("business_services.status_message.no_components");
    }

    let match = /^Affected components: (.+)\. Calculated status: ([a-z_]+), impact score=(\d+)$/.exec(message);

    if (match) {
        return i18n.t("business_services.status_message.affected", {
            components: match[1],
            status: businessServiceStatusLabel(match[2]),
            score: match[3],
        });
    }

    match = /^Calculated status: ([a-z_]+), impact score=(\d+)$/.exec(message);

    if (match) {
        return i18n.t("business_services.status_message.calculated", {
            status: businessServiceStatusLabel(match[1]),
            score: match[2],
        });
    }

    return message;
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
                .text(group.name || group.slug || i18n.t("business_services.fallback.group", {id: group.id}))
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
    select.append($("<option>").val("").text(i18n.t("business_services.form.no_owner")));

    businessServiceTeamsCache.forEach(function (team) {
        if (!team.active || (groupId && Number(team.group_id) !== Number(groupId))) {
            return;
        }

        select.append(
            $("<option>")
                .val(String(team.id))
                .text((team.slug || team.name || i18n.t("business_services.fallback.team")) + " / " + (team.name || team.slug || ""))
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
    select.append($("<option>").val("").text(i18n.t("business_services.component.select_service")));

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
                $("<td>").attr("colspan", 9).addClass("empty-cell").text(i18n.t("business_services.empty.services"))
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
                .append($("<td>").text(businessServiceCriticalityLabel(item.criticality)))
                .append($("<td>").text(businessServiceTierLabel(item.tier)))
                .append($("<td>").text(businessServiceComponentCount(item)))
                .append($("<td>").append(renderStatusBadge(!!item.public, i18n.t("business_services.visibility.public"), i18n.t("business_services.visibility.private"))))
                .append($("<td>").addClass("actions-cell").append(renderBusinessServiceActions(item)))
        );
    });
}


function renderBusinessServiceActions(item) {
    return makeActionMenu({
        object: item,
        items: [
            {
                label: i18n.t("business_services.actions.details"),
                icon: "fas fa-info-circle",
                onClick: function () {
                    openBusinessServiceDetailsModal(item.id);
                }
            },
            {
                label: i18n.t("business_services.actions.edit"),
                icon: "fas fa-edit",
                required: "write",
                onClick: function () {
                    editBusinessService(item);
                }
            },
            {
                label: item.enabled ? i18n.t("business_services.actions.disable") : i18n.t("business_services.actions.enable"),
                icon: item.enabled ? "fas fa-pause" : "fas fa-play",
                required: "write",
                danger: item.enabled,
                onClick: function () {
                    setBusinessServiceEnabled(item, !item.enabled);
                }
            },
            {
                label: i18n.t("business_services.actions.delete"),
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
                label: i18n.t("business_services.actions.edit"),
                icon: "fas fa-edit",
                required: "write",
                onClick: function () {
                    editBusinessServiceComponent(component);
                }
            },
            {
                label: component.enabled ? i18n.t("business_services.actions.disable") : i18n.t("business_services.actions.enable"),
                icon: component.enabled ? "fas fa-pause" : "fas fa-play",
                required: "write",
                danger: component.enabled,
                onClick: function () {
                    setBusinessServiceComponentEnabled(component, !component.enabled);
                }
            },
            {
                label: i18n.t("business_services.actions.delete"),
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

    apiGet("/api/business-services/" + id, function (item) {
        if (serial !== businessServiceDetailsLoadSerial) {
            return;
        }

        if (!item || !item.id) {
            showBusinessServiceDetailsLoadError(i18n.t("business_services.errors.details_not_found"));
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

        showBusinessServiceDetailsLoadError(apiErrorMessage(xhr, i18n.t("business_services.errors.details_load")));
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

    $("#business-service-details-title").text(item.name || item.slug || i18n.t("business_services.details.fallback"));
    $("#business-service-details-subtitle").text(
        (item.public_name || item.name || "") + " · " + businessServiceStatusLabel(item.status)
    );
    $("#business-service-recalculate").prop("disabled", false);
    $("#open-business-service-component-modal").prop("disabled", false);

    body.empty();
    body.append(detailItem(i18n.t("business_services.table.status"), businessServiceStatusLabel(item.status)));
    body.append(detailItem(i18n.t("business_services.details.status_message"), businessServiceStatusMessageLabel(item.status_message)));
    body.append(detailItem(i18n.t("business_services.table.group"), item.group_name || item.group_slug || "-"));
    body.append(detailItem(i18n.t("business_services.table.owner_team"), item.owner_team_name || item.owner_team_slug || "-"));
    body.append(detailItem(i18n.t("business_services.table.criticality"), businessServiceCriticalityLabel(item.criticality)));
    body.append(detailItem(i18n.t("business_services.table.tier"), businessServiceTierLabel(item.tier)));
    body.append(detailItem(i18n.t("business_services.table.visibility"), item.public ? i18n.t("business_services.visibility.public") : i18n.t("business_services.visibility.private")));
    body.append(detailItem(i18n.t("business_services.table.components"), components.length || businessServiceComponentCount(item)));

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
                $("<td>").attr("colspan", 7).addClass("empty-cell").text(i18n.t("business_services.empty.components"))
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
                .append($("<td>").text(businessServiceCriticalityLabel(component.criticality)))
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
                $("<td>").attr("colspan", 5).addClass("empty-cell").text(i18n.t("business_services.empty.history"))
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
                .append($("<td>").addClass("table-cell-truncate-wide").text(businessServiceStatusMessageLabel(item.message)))
        );
    });
}


function resetBusinessServiceForm() {
    const groupId = selectedBusinessServiceFormGroupId();

    $("#business-service-form-title").text(i18n.t("business_services.form.create"));
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

    $("#business-service-form-title").text(i18n.t("business_services.form.edit"));
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
        showAppError(i18n.t("business_services.validation.group"));
        return;
    }

    if (!payload.name) {
        showAppError(i18n.t("business_services.validation.name"));
        return;
    }

    if (!payload.slug) {
        showAppError(i18n.t("business_services.validation.slug"));
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
        title: i18n.t("business_services.confirm.delete_title"),
        message: i18n.t("business_services.confirm.delete_message", {name: item.name || item.slug || item.id}),
        confirmText: i18n.t("business_services.confirm.delete_confirm"),
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
    $("#business-service-component-form-title").text(i18n.t("business_services.component.add"));
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
        showAppError(i18n.t("business_services.validation.select_first"));
        return;
    }

    loadBusinessServiceTechnicalServices(businessServiceDetailsCache.group_id, function () {
        resetBusinessServiceComponentForm();
        openAppModal("#business-service-component-modal");
    });
}


function editBusinessServiceComponent(component) {
    loadBusinessServiceTechnicalServices(businessServiceDetailsCache ? businessServiceDetailsCache.group_id : null, function () {
        $("#business-service-component-form-title").text(i18n.t("business_services.component.edit"));
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
        showAppError(i18n.t("business_services.validation.select_first"));
        return;
    }

    const id = $("#business-service-component-id").val();
    const payload = collectBusinessServiceComponentPayload();

    if (!payload.service_id) {
        showAppError(i18n.t("business_services.validation.technical_service"));
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
        title: i18n.t("business_services.confirm.component_title"),
        message: i18n.t("business_services.confirm.component_message", {name: component.service_name || component.service_slug || component.id}),
        confirmText: i18n.t("business_services.confirm.component_confirm"),
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
        source === "manual" ? i18n.t("business_services.details.manual") : i18n.t("business_services.details.calculated")
    );

    $("#business-service-details-manual-status").text(
        manualActive
            ? businessServiceStatusLabel(details.manual_status)
            : i18n.t("business_services.details.no_override")
    );

    $("#business-service-details-manual-message").text(
        details.manual_status_message || "-"
    );

    $("#business-service-details-manual-until").text(
        details.manual_status_until
            ? businessServiceFormatDateTime(details.manual_status_until)
            : i18n.t("business_services.details.until_cleared")
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
        showBusinessServiceManualStatusError(i18n.t("business_services.validation.not_selected"));
        return;
    }

    const until = businessServiceManualStatusIsoValue();

    if ($("#business-service-manual-status-until").val() && !until) {
        showBusinessServiceManualStatusError(i18n.t("business_services.validation.expiration_invalid"));
        return;
    }

    if (until && new Date(until).getTime() <= Date.now()) {
        showBusinessServiceManualStatusError(i18n.t("business_services.validation.expiration_future"));
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
        showBusinessServiceManualStatusError(apiErrorMessage(xhr, i18n.t("business_services.errors.manual_set")));
    });
}


function clearBusinessServiceManualStatus() {
    const id = selectedBusinessServiceDetailsId();

    if (!id) {
        showBusinessServiceManualStatusError(i18n.t("business_services.validation.not_selected"));
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
        showBusinessServiceManualStatusError(apiErrorMessage(xhr, i18n.t("business_services.errors.manual_clear")));
    });
}

$(document).on("click", "#set-business-service-manual-status", function () {
    setBusinessServiceManualStatus();
});


$(document).on("click", "#clear-business-service-manual-status", function () {
    clearBusinessServiceManualStatus();
});
