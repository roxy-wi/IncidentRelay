let maintenanceWindowsCache = [];
let maintenanceReferenceCache = {
    groups: [],
    teams: [],
    services: [],
    routes: [],
};
let selectedMaintenanceWindowId = null;

const maintenanceBehaviorLabels = {
    suppress_notifications: i18n.t("maintenance.behavior.suppress_notifications"),
    suppress_incident: i18n.t("maintenance.behavior.suppress_incident"),
    create_maintenance_incident: i18n.t("maintenance.behavior.create_maintenance_incident"),
    pause_escalation_only: i18n.t("maintenance.behavior.pause_escalation_only"),
};

const maintenanceStatusLabels = {
    scheduled: i18n.t("maintenance.status.scheduled"),
    active: i18n.t("maintenance.status.active"),
    finished: i18n.t("maintenance.status.finished"),
    cancelled: i18n.t("maintenance.status.cancelled"),
};

function getMaintenanceCreateParamsFromUrl() {
    const params = new URLSearchParams(window.location.search || "");

    return {
        serviceId: parsePositiveInt(params.get("service_id")),
        teamId: parsePositiveInt(params.get("team_id")),
        routeId: parsePositiveInt(params.get("route_id")),
        groupId: parsePositiveInt(params.get("group_id")),
    };
}


function openMaintenanceCreateModalFromUrl() {
    const params = getMaintenanceCreateParamsFromUrl();

    if (!params.serviceId && !params.teamId && !params.routeId && !params.groupId) {
        return;
    }

    openMaintenanceCreateModal();

    if (params.serviceId) {
        prefillMaintenanceScope("service", params.serviceId);
    } else if (params.routeId) {
        prefillMaintenanceScope("route", params.routeId);
    } else if (params.teamId) {
        prefillMaintenanceScope("team", params.teamId);
    } else if (params.groupId) {
        prefillMaintenanceScope("group", params.groupId);
    }

    prefillMaintenanceDefaultTimes();
    removeMaintenanceCreateParamsFromUrl();
}


function prefillMaintenanceScope(scopeType, targetId) {
    $("#maintenance-scope-type").val(scopeType);
    updateMaintenanceScopeTargetSelect();
    $("#maintenance-scope-target").val(String(targetId));
}


function prefillMaintenanceDefaultTimes() {
    if ($("#maintenance-starts-at").val() || $("#maintenance-ends-at").val()) {
        return;
    }

    const now = new Date();
    now.setMinutes(0, 0, 0);
    now.setHours(now.getHours() + 1);

    const end = new Date(now.getTime());
    end.setHours(end.getHours() + 1);

    $("#maintenance-starts-at").val(formatMaintenanceLocalInput(now));
    $("#maintenance-ends-at").val(formatMaintenanceLocalInput(end));
    updateMaintenanceTimeWarning();
}


function formatMaintenanceLocalInput(date) {
    return [
        date.getFullYear(),
        String(date.getMonth() + 1).padStart(2, "0"),
        String(date.getDate()).padStart(2, "0"),
    ].join("-") + "T" + [
        String(date.getHours()).padStart(2, "0"),
        String(date.getMinutes()).padStart(2, "0"),
    ].join(":");
}


function removeMaintenanceCreateParamsFromUrl() {
    if (!window.history || !window.history.replaceState) {
        return;
    }

    const url = new URL(window.location.href);

    url.searchParams.delete("service_id");
    url.searchParams.delete("team_id");
    url.searchParams.delete("route_id");
    url.searchParams.delete("group_id");

    window.history.replaceState({}, document.title, url.pathname + url.search + url.hash);
}

function loadMaintenanceWindows() {
    fillMaintenanceReferences(function () {
        refreshMaintenanceWindows();
        openMaintenanceCreateModalFromUrl();
    });
}

function refreshMaintenanceWindows() {
    apiGet("/api/maintenance-windows?include_finished=1", function (items) {
        maintenanceWindowsCache = asArraySafe(items);
        renderMaintenanceSummary();
        renderMaintenanceWindowsTable();
        restoreMaintenanceDetails();
    });
}

function fillMaintenanceReferences(callback) {
    let remaining = 4;

    function done() {
        remaining -= 1;
        if (remaining === 0 && typeof callback === "function") {
            callback();
        }
    }

    apiGet("/api/groups", function (payload) {
        maintenanceReferenceCache.groups = normalizeItems(payload).map(function (item) {
            return {
                id: item.id,
                label: item.name || item.slug || i18n.t("maintenance.values.group_number", {id: item.id}),
            };
        });
        done();
    });

    apiGet("/api/teams", function (payload) {
        maintenanceReferenceCache.teams = normalizeItems(payload).map(function (item) {
            return {
                id: item.id,
                label: teamLabel(item),
            };
        });
        done();
    });

    apiGet("/api/services", function (payload) {
        maintenanceReferenceCache.services = normalizeItems(payload).map(function (item) {
            return {
                id: item.id,
                label: serviceLabel(item),
            };
        });
        done();
    });

    apiGet("/api/routes", function (payload) {
        maintenanceReferenceCache.routes = normalizeItems(payload).map(function (item) {
            return {
                id: item.id,
                label: routeLabel(item),
            };
        });
        done();
    });
}

function renderMaintenanceSummary() {
    $("#maintenance-total-count").text(maintenanceWindowsCache.length);
    $("#maintenance-active-count").text(countMaintenanceByStatus("active"));
    $("#maintenance-scheduled-count").text(countMaintenanceByStatus("scheduled"));
    $("#maintenance-cancelled-count").text(countMaintenanceByStatus("cancelled"));
}

function countMaintenanceByStatus(status) {
    return maintenanceWindowsCache.filter(function (item) {
        return item.status === status;
    }).length;
}
function getFilteredMaintenanceWindows() {
    const query = String($("#maintenance-window-search").val() || "").trim().toLowerCase();
    const status = String($("#maintenance-window-status-filter").val() || "");
    const behavior = String($("#maintenance-window-behavior-filter").val() || "");

    return maintenanceWindowsCache.filter(function (item) {
        if (status && item.status !== status) {
            return false;
        }

        if (behavior && item.behavior !== behavior) {
            return false;
        }

        if (!query) {
            return true;
        }

        return getMaintenanceSearchText(item).indexOf(query) !== -1;
    });
}

function getMaintenanceSearchText(item) {
    return [
        item.id,
        item.name,
        item.description,
        item.status,
        item.behavior,
        item.timezone,
        item.rrule,
        getMaintenanceScopeText(item),
    ].join(" ").toLowerCase();
}

function renderMaintenanceWindowsTable() {
    const tbody = $("#maintenance-windows-table");
    const items = getFilteredMaintenanceWindows();

    tbody.empty();

    $("#maintenance-filtered-count").text(items.length);
    $("#maintenance-total-list-count").text(maintenanceWindowsCache.length);

    if (!items.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>")
                    .attr("colspan", "8")
                    .addClass("empty-cell")
                    .text(i18n.t("maintenance.empty.found"))
            )
        );
        return;
    }

    items.forEach(function (item) {
        tbody.append(renderMaintenanceRow(item));
    });
}

function renderMaintenanceRow(item) {
    const row = $("<tr>").toggleClass("row-disabled", item.enabled === false || item.status === "cancelled");

    row.append(
        $("<td>")
            .addClass("table-cell-truncate")
            .attr("title", item.name || "-")
            .append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("name-button")
                    .text(item.name || i18n.t("maintenance.values.window_number", {id: item.id}))
                    .on("click", function () {
                        renderMaintenanceDetails(item);
                    })
            )
            .append(
                $("<div>")
                    .addClass("row-subtitle")
                    .text(item.description || item.timezone || "UTC")
            )
    );

    row.append(
        $("<td>")
            .addClass("table-cell-truncate")
            .attr("title", getMaintenanceScopeText(item))
            .text(getMaintenanceScopeText(item))
    );

    row.append($("<td>").append(renderMaintenanceStatusBadge(item)));
    row.append($("<td>").text(maintenanceBehaviorLabels[item.behavior] || item.behavior || "-"));
    row.append($("<td>").text(formatMaintenanceRepeat(item.rrule)));
    row.append($("<td>").text(
        window.AppTimezones.formatPlainDatetime(
            getMaintenanceDisplayStart(item),
            getMaintenanceDisplayTimezone(item)
        )
    ));

    row.append($("<td>").text(
        window.AppTimezones.formatPlainDatetime(
            getMaintenanceDisplayEnd(item),
            getMaintenanceDisplayTimezone(item)
        )
    ));

    row.append(
        $("<td>")
            .addClass("actions-cell")
            .append(renderMaintenanceActions(item))
    );

    return row;
}

function renderMaintenanceStatusBadge(item) {
    const status = item.status || "scheduled";
    const label = maintenanceStatusLabels[status] || status;

    if (status === "active") {
        return $("<span>").addClass("status-pill status-active").text(label);
    }

    if (status === "scheduled") {
        return $("<span>").addClass("status-pill status-scheduled").text(label);
    }

    if (status === "cancelled") {
        return $("<span>").addClass("status-pill status-inactive").text(label);
    }

    return $("<span>").addClass("status-pill status-neutral").text(label);
}

function renderMaintenanceActions(item) {
    const actions = [
        {
            label: i18n.t("maintenance.actions.edit"),
            icon: "fas fa-edit",
            required: "write",
            denyMessage: i18n.t("maintenance.permissions.edit"),
            onClick: function () {
                editMaintenanceWindow(item.id);
            },
        },
        {
            label: i18n.t("maintenance.actions.extend"),
            icon: "fas fa-clock",
            required: "write",
            hidden: item.deleted || item.status === "cancelled",
            denyMessage: i18n.t("maintenance.permissions.extend"),
            onClick: function () {
                extendMaintenanceWindow(item, 1);
            },
        },
        {
            label: i18n.t("maintenance.actions.duplicate"),
            icon: "fas fa-copy",
            required: "write",
            denyMessage: i18n.t("maintenance.permissions.duplicate"),
            onClick: function () {
                duplicateMaintenanceWindow(item);
            },
        },
        {
            label: i18n.t("maintenance.actions.cancel"),
            icon: "fas fa-ban",
            required: "write",
            danger: true,
            hidden: item.deleted || item.status === "cancelled",
            denyMessage: i18n.t("maintenance.permissions.cancel"),
            onClick: function () {
                cancelMaintenanceWindow(item);
            },
        },
        {
            label: i18n.t("maintenance.actions.delete"),
            icon: "fas fa-trash",
            required: "delete",
            danger: true,
            denyMessage: i18n.t("maintenance.permissions.delete"),
            onClick: function () {
                deleteMaintenanceWindow(item);
            },
        },
    ];

    return makeActionMenu({
        object: item,
        items: actions.filter(function (action) {
            return !action.hidden;
        }),
    });
}

function maintenanceDetailsItem(label, value) {
    return $("<div>")
        .addClass("details-item")
        .append($("<div>").addClass("details-label").text(label))
        .append($("<div>").addClass("details-value").text(value || "-"));
}

function renderMaintenanceDetails(item) {
    selectedMaintenanceWindowId = item.id;

    $("#maintenance-details-subtitle").text(
        (maintenanceStatusLabels[item.status] || item.status || "scheduled") +
        " / " +
        (maintenanceBehaviorLabels[item.behavior] || item.behavior || "-")
    );

    const body = $("#maintenance-details-body");
    body.empty();

    body.append(
        $("<div>")
            .addClass("details-list")
            .append(maintenanceDetailsItem(i18n.t("maintenance.details.name"), item.name))
            .append(maintenanceDetailsItem(i18n.t("maintenance.details.description"), item.description))
            .append(maintenanceDetailsItem(i18n.t("maintenance.details.status"), maintenanceStatusLabels[item.status] || item.status))
            .append(maintenanceDetailsItem(i18n.t("maintenance.details.behavior"), maintenanceBehaviorLabels[item.behavior] || item.behavior))
            .append(maintenanceDetailsItem(i18n.t("maintenance.details.repeat"), formatMaintenanceRepeat(item.rrule)))
            .append(maintenanceDetailsItem(i18n.t("maintenance.details.scope"), getMaintenanceScopeText(item)))
            .append(maintenanceDetailsItem(
                i18n.t("maintenance.details.starts"),
                window.AppTimezones.formatPlainDatetime(item.starts_at, item.timezone)
            ))
            .append(maintenanceDetailsItem(
                i18n.t("maintenance.details.ends"),
                window.AppTimezones.formatPlainDatetime(item.ends_at, item.timezone)
            ))
            .append(maintenanceDetailsItem(i18n.t("maintenance.details.timezone"), item.timezone || "UTC"))
            .append(maintenanceDetailsItem(i18n.t("maintenance.details.rrule"), item.rrule))
            .append(maintenanceDetailsItem(i18n.t("maintenance.details.enabled"), item.enabled !== false ? i18n.t("maintenance.values.yes") : i18n.t("maintenance.values.no")))
            .append(maintenanceDetailsItem(
                i18n.t("maintenance.details.apply_to_existing"),
                item.apply_to_existing ? i18n.t("maintenance.values.yes") : i18n.t("maintenance.values.no")
            ))
            .append(maintenanceDetailsItem(
                i18n.t("maintenance.details.reactivate_on_end"),
                item.reactivate_on_end !== false ? i18n.t("maintenance.values.yes") : i18n.t("maintenance.values.no")
            ))
    );

    const actions = $("<div>").addClass("details-actions");

    actions
        .append(
            $("<button>")
                .attr("type", "button")
                .addClass("btn")
                .text(i18n.t("maintenance.actions.edit_window"))
                .on("click", function () {
                    editMaintenanceWindow(item.id);
                })
        )
        .append(
            $("<button>")
                .attr("type", "button")
                .addClass("btn")
                .text(i18n.t("maintenance.actions.cancel_window"))
                .on("click", function () {
                    cancelMaintenanceWindow(item);
                })
        );

    body.append(actions);
}

function renderMaintenanceDetailsEmpty() {
    selectedMaintenanceWindowId = null;
    $("#maintenance-details-subtitle").text(i18n.t("maintenance.details.select"));
    $("#maintenance-details-body").empty().append($("<p>").text(i18n.t("maintenance.details.help")));
}

function restoreMaintenanceDetails() {
    if (!selectedMaintenanceWindowId) {
        renderMaintenanceDetailsEmpty();
        return;
    }

    const item = findMaintenanceWindow(selectedMaintenanceWindowId);

    if (!item) {
        renderMaintenanceDetailsEmpty();
        return;
    }

    renderMaintenanceDetails(item);
}

function openMaintenanceCreateModal() {
    resetMaintenanceForm();
    $("#maintenance-window-modal-title").text(i18n.t("maintenance.form.create"));
    window.AppTimezones.initSelect(
        "#maintenance-timezone",
        window.AppTimezones.getBrowserDefaultTimezone(),
        "#maintenance-window-modal"
    );
    openAppModal($("#maintenance-window-modal"));
}

function editMaintenanceWindow(windowId) {
    const item = findMaintenanceWindow(windowId);

    if (!item) {
        showMaintenanceErrorDialog(i18n.t("maintenance.errors.not_found"));
        return;
    }

    resetMaintenanceForm();
    fillMaintenanceForm(item);
    $("#maintenance-window-modal-title").text(i18n.t("maintenance.form.edit"));
    openAppModal($("#maintenance-window-modal"));
}

function saveMaintenanceWindow() {
    if (!validateMaintenanceWindowForm()) {
        return;
    }

    const id = $("#maintenance-window-id").val();
    const payload = buildMaintenancePayload();

    if (id) {
        apiPut(
            "/api/maintenance-windows/" + id,
            payload,
            function () {
                closeAppModal("#maintenance-window-modal");
                refreshMaintenanceWindows();
            },
            function (xhr) {
                showMaintenanceFormError(getApiErrorMessage(xhr));
            }
        );
        return;
    }

    apiPost(
        "/api/maintenance-windows",
        payload,
        function (created) {
            selectedMaintenanceWindowId = created.id;
            closeAppModal("#maintenance-window-modal");
            refreshMaintenanceWindows();
        },
        function (xhr) {
            showMaintenanceFormError(getApiErrorMessage(xhr));
        }
    );
}

function buildMaintenancePayload() {
    const name = getValue("#maintenance-name");
    const startsAt = getValue("#maintenance-starts-at");
    const endsAt = getValue("#maintenance-ends-at");
    const scopeType = getValue("#maintenance-scope-type");
    const scopeTargetId = parsePositiveInt($("#maintenance-scope-target").val());

    clearMaintenanceFormError();

    if (!name) {
        showMaintenanceFormError(i18n.t("maintenance.errors.name_required"));
        return null;
    }

    if (!startsAt || !endsAt) {
        showMaintenanceFormError(i18n.t("maintenance.errors.times_required"));
        return null;
    }

    if (!scopeType || !scopeTargetId) {
        showMaintenanceFormError(i18n.t("maintenance.errors.scope_required"));
        return null;
    }

    return {
        name: name,
        description: getValue("#maintenance-description") || null,
        behavior: $("#maintenance-behavior").val() || "suppress_notifications",
        timezone: window.AppTimezones.getSelectValue("#maintenance-timezone"),
        rrule: buildMaintenanceRrule(),
        starts_at: window.AppTimezones.normalizeDatetimeLocal(startsAt),
        ends_at: window.AppTimezones.normalizeDatetimeLocal(endsAt),
        enabled: $("#maintenance-enabled").is(":checked"),
        apply_to_existing: $("#maintenance-apply-to-existing").is(":checked"),
        reactivate_on_end: $("#maintenance-reactivate-on-end").is(":checked"),
        scopes: [
            buildMaintenanceScope(scopeType, scopeTargetId),
        ],
    };
}

function buildMaintenanceScope(scopeType, scopeTargetId) {
    const scope = {
        scope_type: scopeType,
    };

    scope[scopeType + "_id"] = scopeTargetId;

    return scope;
}

function resetMaintenanceForm() {
    $("#maintenance-window-id").val("");
    $("#maintenance-name").val("");
    $("#maintenance-description").val("");
    $("#maintenance-behavior").val("suppress_notifications");
    $("#maintenance-timezone").val("UTC");
    $("#maintenance-starts-at").val("");
    $("#maintenance-ends-at").val("");
    $("#maintenance-scope-type").val("service");
    $("#maintenance-enabled").prop("checked", true);
    $("#maintenance-apply-to-existing").prop("checked", false);
    $("#maintenance-reactivate-on-end").prop("checked", true);

    updateMaintenanceLifecycleOptions();
    updateMaintenanceTimeWarning();
    fillMaintenanceRepeatFields(null);
    clearMaintenanceFormError();
    updateMaintenanceScopeTargetSelect();
}

function fillMaintenanceForm(item) {
    const scope = firstMaintenanceScope(item);

    $("#maintenance-window-id").val(item.id);
    $("#maintenance-name").val(item.name || "");
    $("#maintenance-description").val(item.description || "");
    $("#maintenance-behavior").val(item.behavior || "suppress_notifications");
    $("#maintenance-timezone").val(item.timezone || "UTC");
    fillMaintenanceRepeatFields(item.rrule);
    $("#maintenance-starts-at").val(
        window.AppTimezones.toDatetimeLocalInput(item.starts_at)
    );

    $("#maintenance-ends-at").val(
        window.AppTimezones.toDatetimeLocalInput(item.ends_at)
    );
    $("#maintenance-enabled").prop("checked", item.enabled !== false);
    $("#maintenance-apply-to-existing").prop("checked", Boolean(item.apply_to_existing));
    $("#maintenance-reactivate-on-end").prop("checked", item.reactivate_on_end !== false);
    updateMaintenanceLifecycleOptions();

    if (scope) {
        $("#maintenance-scope-type").val(scope.scope_type || "service");
        updateMaintenanceScopeTargetSelect();
        $("#maintenance-scope-target").val(getMaintenanceScopeTargetId(scope));
    }
    updateMaintenanceTimeWarning();
    window.AppTimezones.initSelect(
        "#maintenance-timezone",
        item.timezone || window.AppTimezones.getBrowserDefaultTimezone(),
        "#maintenance-window-modal"
    );
}

function updateMaintenanceScopeTargetSelect() {
    const scopeType = $("#maintenance-scope-type").val() || "service";
    const select = $("#maintenance-scope-target");
    const items = getMaintenanceScopeItems(scopeType);

    select.empty();
    select.append($("<option>").val("").text(i18n.t("maintenance.values.select_type", {type: maintenanceScopeTypeLabel(scopeType)})));

    items.forEach(function (item) {
        $("<option>").val(item.id).text(item.label).appendTo(select);
    });
}

function cancelMaintenanceWindow(item) {
    if (!item || item.status === "cancelled") {
        return;
    }

    showAppConfirm({
        type: "warning",
        title: i18n.t("maintenance.confirm.cancel_title"),
        message: i18n.t("maintenance.confirm.cancel_message", {name: item.name}),
        confirmText: i18n.t("maintenance.actions.cancel_window"),
        confirmClass: "btn-danger",
    }).done(function () {
        apiPost(
            "/api/maintenance-windows/" + item.id + "/cancel",
            { reason: i18n.t("maintenance.confirm.cancel_reason") },
            refreshMaintenanceWindows
        );
    });
}

function deleteMaintenanceWindow(item) {
    if (!item) {
        return;
    }

    showAppConfirm({
        type: "warning",
        title: i18n.t("maintenance.confirm.delete_title"),
        message: i18n.t("maintenance.confirm.delete_message", {name: item.name}),
        confirmText: i18n.t("maintenance.actions.delete"),
        confirmClass: "btn-danger",
    }).done(function () {
        apiDelete("/api/maintenance-windows/" + item.id, refreshMaintenanceWindows);
    });
}

function maintenanceScopeTypeLabel(scopeType) {
    const labels = {
        group: "maintenance.form.group",
        team: "maintenance.form.team",
        service: "maintenance.form.service",
        route: "maintenance.form.route",
    };

    return labels[scopeType] ? i18n.t(labels[scopeType]) : scopeType;
}

function getMaintenanceScopeItems(scopeType) {
    if (scopeType === "group") {
        return maintenanceReferenceCache.groups;
    }

    if (scopeType === "team") {
        return maintenanceReferenceCache.teams;
    }

    if (scopeType === "route") {
        return maintenanceReferenceCache.routes;
    }

    return maintenanceReferenceCache.services;
}

function getMaintenanceScopeText(item) {
    const scope = firstMaintenanceScope(item);

    if (!scope) {
        return "-";
    }

    return maintenanceScopeTypeLabel(scope.scope_type) + ": " + getMaintenanceScopeTargetLabel(scope);
}

function firstMaintenanceScope(item) {
    return Array.isArray(item.scopes) && item.scopes.length ? item.scopes[0] : null;
}

function getMaintenanceScopeTargetLabel(scope) {
    if (scope.scope_type === "group") {
        return labelById(maintenanceReferenceCache.groups, scope.group_id);
    }

    if (scope.scope_type === "team") {
        return labelById(maintenanceReferenceCache.teams, scope.team_id);
    }

    if (scope.scope_type === "route") {
        return labelById(maintenanceReferenceCache.routes, scope.route_id);
    }

    return labelById(maintenanceReferenceCache.services, scope.service_id);
}

function getMaintenanceScopeTargetId(scope) {
    if (scope.scope_type === "group") {
        return scope.group_id;
    }

    if (scope.scope_type === "team") {
        return scope.team_id;
    }

    if (scope.scope_type === "route") {
        return scope.route_id;
    }

    return scope.service_id;
}

function findMaintenanceWindow(windowId) {
    return maintenanceWindowsCache.find(function (item) {
        return Number(item.id) === Number(windowId);
    });
}

function showMaintenanceFormError(message) {
    $("#maintenance-window-error")
        .text(message)
        .removeClass("is-hidden");
}

function clearMaintenanceFormError() {
    $("#maintenance-window-error")
        .text("")
        .addClass("is-hidden");
}

function showMaintenanceErrorDialog(message) {
    if (typeof showAppDialog === "function") {
        showAppDialog({
            type: "error",
            title: "Maintenance windows",
            message: message,
        });
    }
}

function normalizeItems(payload) {
    if (Array.isArray(payload)) {
        return payload;
    }

    if (payload && Array.isArray(payload.items)) {
        return payload.items;
    }

    if (payload && Array.isArray(payload.data)) {
        return payload.data;
    }

    return [];
}

function asArraySafe(value) {
    return Array.isArray(value) ? value : [];
}

function teamLabel(item) {
    if (item.name && item.slug) {
        return item.name + " (" + item.slug + ")";
    }

    return item.name || item.slug || i18n.t("maintenance.values.team_number", {id: item.id});
}

function serviceLabel(item) {
    const name = item.name || item.slug || i18n.t("maintenance.values.service_number", {id: item.id});
    const team = item.team_name || item.team_slug || nestedName(item.team);

    return team ? name + " · " + team : name;
}

function routeLabel(item) {
    const name = item.name || item.slug || item.source || i18n.t("maintenance.values.route_number", {id: item.id});
    const team = item.team_name || item.team_slug || nestedName(item.team);

    return team ? name + " · " + team : name;
}

function nestedName(value) {
    if (!value) {
        return "";
    }

    return value.name || value.slug || "";
}

function labelById(items, id) {
    const match = items.find(function (item) {
        return Number(item.id) === Number(id);
    });

    return match ? match.label : ("#" + id);
}

function getValue(selector) {
    return String($(selector).val() || "").trim();
}

function parsePositiveInt(value) {
    const parsed = parseInt(value, 10);

    if (!Number.isFinite(parsed) || parsed <= 0) {
        return null;
    }

    return parsed;
}

$(document)
    .off("click.maintenance", "#open-maintenance-create-modal")
    .on("click.maintenance", "#open-maintenance-create-modal", openMaintenanceCreateModal);

$(document)
    .off("click.maintenance", "#reload-maintenance-windows")
    .on("click.maintenance", "#reload-maintenance-windows", refreshMaintenanceWindows);

$(document)
    .off("click.maintenance", "#save-maintenance-window")
    .on("click.maintenance", "#save-maintenance-window", saveMaintenanceWindow);

$(document)
    .off("click.maintenance", "#reset-maintenance-window-form")
    .on("click.maintenance", "#reset-maintenance-window-form", resetMaintenanceForm);

$(document)
    .off("click.maintenance", "#close-maintenance-window-modal")
    .on("click.maintenance", "#close-maintenance-window-modal", function () {
        closeAppModal($("#maintenance-window-modal"));
    });

$(document)
    .off("change.maintenance", "#maintenance-scope-type")
    .on("change.maintenance", "#maintenance-scope-type", updateMaintenanceScopeTargetSelect);

$(document)
    .off(
        "input.maintenance change.maintenance",
        "#maintenance-window-search, #maintenance-window-status-filter, #maintenance-window-behavior-filter"
    )
    .on(
        "input.maintenance change.maintenance",
        "#maintenance-window-search, #maintenance-window-status-filter, #maintenance-window-behavior-filter",
        renderMaintenanceWindowsTable
    );
$(document).on("change", "#maintenance-repeat", updateMaintenanceRepeatFields);
function updateMaintenanceRepeatFields() {
    const repeat = $("#maintenance-repeat").val();

    $("#maintenance-repeat-count-row").toggle(
        repeat === "daily" || repeat === "weekly" || repeat === "monthly"
    );

    $("#maintenance-custom-rrule-row").toggle(repeat === "custom");
}

function buildMaintenanceRrule() {
    const repeat = $("#maintenance-repeat").val();
    const count = parseInt($("#maintenance-repeat-count").val(), 10) || 1;

    if (!repeat) {
        return null;
    }

    if (repeat === "daily") {
        return "FREQ=DAILY;COUNT=" + count;
    }

    if (repeat === "weekly") {
        return "FREQ=WEEKLY;COUNT=" + count;
    }

    if (repeat === "monthly") {
        return "FREQ=MONTHLY;COUNT=" + count;
    }

    if (repeat === "custom") {
        return getValue("#maintenance-rrule") || null;
    }

    return null;
}

function fillMaintenanceRepeatFields(rrule) {
    const text = String(rrule || "").trim();

    $("#maintenance-repeat").val("");
    $("#maintenance-repeat-count").val("1");
    $("#maintenance-rrule").val("");

    if (!text) {
        updateMaintenanceRepeatFields();
        return;
    }

    const normalized = text.replace(/^RRULE:/i, "");
    const countMatch = normalized.match(/(?:^|;)COUNT=(\d+)(?:;|$)/i);
    const count = countMatch ? countMatch[1] : "1";

    if (/^FREQ=DAILY(?:;COUNT=\d+)?$/i.test(normalized)) {
        $("#maintenance-repeat").val("daily");
        $("#maintenance-repeat-count").val(count);
        updateMaintenanceRepeatFields();
        return;
    }

    if (/^FREQ=WEEKLY(?:;COUNT=\d+)?$/i.test(normalized)) {
        $("#maintenance-repeat").val("weekly");
        $("#maintenance-repeat-count").val(count);
        updateMaintenanceRepeatFields();
        return;
    }

    if (/^FREQ=MONTHLY(?:;COUNT=\d+)?$/i.test(normalized)) {
        $("#maintenance-repeat").val("monthly");
        $("#maintenance-repeat-count").val(count);
        updateMaintenanceRepeatFields();
        return;
    }

    $("#maintenance-repeat").val("custom");
    $("#maintenance-rrule").val(normalized);
    updateMaintenanceRepeatFields();
}
function formatMaintenanceRepeat(rrule) {
    const text = String(rrule || "").trim();

    if (!text) {
        return i18n.t("maintenance.repeat.no");
    }

    const normalized = text.replace(/^RRULE:/i, "");
    const countMatch = normalized.match(/(?:^|;)COUNT=(\d+)(?:;|$)/i);
    const count = countMatch ? countMatch[1] : null;

    if (/^FREQ=DAILY(?:;COUNT=\d+)?$/i.test(normalized)) {
        return count ? i18n.t("maintenance.repeat.with_count", {period: i18n.t("maintenance.repeat.daily"), count: count}) : i18n.t("maintenance.repeat.daily");
    }

    if (/^FREQ=WEEKLY(?:;COUNT=\d+)?$/i.test(normalized)) {
        return count ? i18n.t("maintenance.repeat.with_count", {period: i18n.t("maintenance.repeat.weekly"), count: count}) : i18n.t("maintenance.repeat.weekly");
    }

    if (/^FREQ=MONTHLY(?:;COUNT=\d+)?$/i.test(normalized)) {
        return count ? i18n.t("maintenance.repeat.with_count", {period: i18n.t("maintenance.repeat.monthly"), count: count}) : i18n.t("maintenance.repeat.monthly");
    }

    return normalized;
}
function getMaintenanceOccurrence(item) {
    return item && item.occurrence ? item.occurrence : null;
}

function getMaintenanceDisplayStart(item) {
    const occurrence = getMaintenanceOccurrence(item);

    if (occurrence && occurrence.starts_at) {
        return occurrence.starts_at;
    }

    return item.starts_at;
}

function getMaintenanceDisplayEnd(item) {
    const occurrence = getMaintenanceOccurrence(item);

    if (occurrence && occurrence.ends_at) {
        return occurrence.ends_at;
    }

    return item.ends_at;
}

function getMaintenanceDisplayTimezone(item) {
    const occurrence = getMaintenanceOccurrence(item);

    if (occurrence && occurrence.timezone) {
        return occurrence.timezone;
    }

    return item.timezone;
}

function parseMaintenanceInputDate(value) {
    const text = String(value || "").trim();

    if (!text) {
        return null;
    }

    const normalized = text.length === 16 ? text + ":00" : text;
    const match = normalized.match(
        /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/
    );

    if (!match) {
        return null;
    }

    return new Date(
        Number(match[1]),
        Number(match[2]) - 1,
        Number(match[3]),
        Number(match[4]),
        Number(match[5]),
        Number(match[6] || 0)
    );
}

function addHoursToMaintenanceDate(value, hours) {
    const date = parseMaintenanceInputDate(value);

    if (!date) {
        return value;
    }

    date.setHours(date.getHours() + hours);

    return [
        date.getFullYear(),
        String(date.getMonth() + 1).padStart(2, "0"),
        String(date.getDate()).padStart(2, "0"),
    ].join("-") + "T" + [
        String(date.getHours()).padStart(2, "0"),
        String(date.getMinutes()).padStart(2, "0"),
    ].join(":");
}

function isMaintenanceInputDateInPast(value) {
    const date = parseMaintenanceInputDate(value);

    if (!date) {
        return false;
    }

    return date.getTime() < Date.now();
}

function updateMaintenanceTimeWarning() {
    const startsAt = $("#maintenance-starts-at").val();
    const endsAt = $("#maintenance-ends-at").val();
    const warnings = [];

    if (isMaintenanceInputDateInPast(startsAt)) {
        warnings.push(i18n.t("maintenance.errors.start_past"));
    }

    if (isMaintenanceInputDateInPast(endsAt)) {
        warnings.push(i18n.t("maintenance.errors.end_past"));
    }

    const warning = $("#maintenance-time-warning");

    if (!warning.length) {
        return;
    }

    if (!warnings.length) {
        warning.hide().text("");
        return;
    }

    warning.text(warnings.join(" ")).show();
}
function extendMaintenanceWindow(item, hours) {
    const windowItem = item || {};
    const endsAt = window.AppTimezones.toDatetimeLocalInput(windowItem.ends_at);

    const payload = {
        ends_at: window.AppTimezones.normalizeDatetimeLocal(
            addHoursToMaintenanceDate(endsAt, hours)
        ),
    };

    apiPut(
        "/api/maintenance-windows/" + windowItem.id,
        payload,
        function () {
            refreshMaintenanceWindows();
        },
        function (xhr) {
            showAppDialog(
                i18n.t("maintenance.errors.extend_failed"),
                getApiErrorMessage(xhr)
            );
        }
    );
}
function duplicateMaintenanceWindow(item) {
    const source = item || {};
    const startsAt = window.AppTimezones.toDatetimeLocalInput(source.starts_at);
    const endsAt = window.AppTimezones.toDatetimeLocalInput(source.ends_at);

    const payload = {
        name: i18n.t("maintenance.values.copy_suffix", {name: source.name || i18n.t("maintenance.values.default_name")}),
        description: source.description || null,
        behavior: source.behavior || "suppress_notifications",
        timezone: source.timezone || window.AppTimezones.getBrowserDefaultTimezone(),
        rrule: source.rrule || null,
        starts_at: window.AppTimezones.normalizeDatetimeLocal(startsAt),
        ends_at: window.AppTimezones.normalizeDatetimeLocal(endsAt),
        enabled: false,
        apply_to_existing: Boolean(source.apply_to_existing),
        reactivate_on_end: source.reactivate_on_end !== false,
        scopes: normalizeMaintenanceScopesForPayload(source.scopes || []),
    };

    apiPost(
        "/api/maintenance-windows",
        payload,
        function (created) {
            selectedMaintenanceWindowId = created.id;
            refreshMaintenanceWindows();
        },
        function (xhr) {
            showAppDialog(
                i18n.t("maintenance.errors.duplicate_failed"),
                getApiErrorMessage(xhr)
            );
        }
    );
}

function normalizeMaintenanceScopesForPayload(scopes) {
    return (scopes || []).map(function (scope) {
        const item = {
            scope_type: scope.scope_type,
        };

        if (scope.scope_type === "group") {
            item.group_id = scope.group_id;
        }

        if (scope.scope_type === "team") {
            item.team_id = scope.team_id;
        }

        if (scope.scope_type === "service") {
            item.service_id = scope.service_id;
        }

        if (scope.scope_type === "route") {
            item.route_id = scope.route_id;
        }

        return item;
    }).filter(function (scope) {
        if (scope.scope_type === "group") {
            return Boolean(scope.group_id);
        }

        if (scope.scope_type === "team") {
            return Boolean(scope.team_id);
        }

        if (scope.scope_type === "service") {
            return Boolean(scope.service_id);
        }

        if (scope.scope_type === "route") {
            return Boolean(scope.route_id);
        }

        return false;
    });
}

$(document).on(
    "change input",
    "#maintenance-starts-at, #maintenance-ends-at",
    updateMaintenanceTimeWarning
);
function clearMaintenanceValidationErrors() {
    $("#maintenance-window-modal .field-error").removeClass("field-error");
    $("#maintenance-window-modal .field-error-text").remove();
    clearMaintenanceFormError();
}

function setMaintenanceFieldError(selector, message) {
    const field = $(selector);

    if (!field.length) {
        return;
    }

    field.addClass("field-error");
    field.attr("aria-invalid", "true");

    const existing = field.next(".field-error-text");

    if (existing.length) {
        existing.text(message);
        return;
    }

    $("<div>")
        .addClass("field-error-text")
        .text(message)
        .insertAfter(field);
}

function focusFirstMaintenanceError() {
    const first = $("#maintenance-window-modal .field-error").first();

    if (first.length) {
        first.trigger("focus");
    }
}

function validateMaintenanceWindowForm() {
    clearMaintenanceValidationErrors();

    let isValid = true;

    const name = getValue("#maintenance-name");
    const startsAt = $("#maintenance-starts-at").val();
    const endsAt = $("#maintenance-ends-at").val();
    const scopeType = $("#maintenance-scope-type").val();
    const scopeTargetId = $("#maintenance-scope-target").val();
    const repeat = $("#maintenance-repeat").val();
    const customRrule = getValue("#maintenance-rrule");

    if (!name) {
        setMaintenanceFieldError("#maintenance-name", i18n.t("maintenance.errors.name_required"));
        isValid = false;
    }

    if (!startsAt) {
        setMaintenanceFieldError("#maintenance-starts-at", i18n.t("maintenance.errors.start_required"));
        isValid = false;
    }

    if (!endsAt) {
        setMaintenanceFieldError("#maintenance-ends-at", i18n.t("maintenance.errors.end_required"));
        isValid = false;
    }

    if (startsAt && endsAt) {
        const startDate = parseMaintenanceInputDate(startsAt);
        const endDate = parseMaintenanceInputDate(endsAt);

        if (startDate && endDate && endDate.getTime() <= startDate.getTime()) {
            setMaintenanceFieldError(
                "#maintenance-ends-at",
                i18n.t("maintenance.errors.end_after_start")
            );
            isValid = false;
        }
    }

    if (!scopeType) {
        setMaintenanceFieldError("#maintenance-scope-type", i18n.t("maintenance.errors.scope_type_required"));
        isValid = false;
    }

    if (!scopeTargetId) {
        setMaintenanceFieldError(
            "#maintenance-scope-target",
            getMaintenanceScopeTargetRequiredMessage(scopeType)
        );
        isValid = false;
    }

    if (repeat === "custom" && !customRrule) {
        setMaintenanceFieldError(
            "#maintenance-rrule",
            i18n.t("maintenance.errors.rrule_required")
        );
        isValid = false;
    }

    if (!isValid) {
        showMaintenanceFormError(i18n.t("maintenance.errors.fix_fields"));
        focusFirstMaintenanceError();
    }

    return isValid;
}

function getMaintenanceScopeTargetRequiredMessage(scopeType) {
    if (scopeType === "group") {
        return i18n.t("maintenance.errors.group_required");
    }

    if (scopeType === "team") {
        return i18n.t("maintenance.errors.team_required");
    }

    if (scopeType === "service") {
        return i18n.t("maintenance.errors.service_required");
    }

    if (scopeType === "route") {
        return i18n.t("maintenance.errors.route_required");
    }

    return i18n.t("maintenance.errors.scope_required");
}
$(document).on(
    "input change",
    "#maintenance-window-modal input, #maintenance-window-modal select, #maintenance-window-modal textarea",
    function () {
        $(this).removeClass("field-error");
        $(this).attr("aria-invalid", "false");
        $(this).next(".field-error-text").remove();

        if (!$("#maintenance-window-modal .field-error").length) {
            clearMaintenanceFormError();
        }
    }
);
$(document).on("change", "#maintenance-scope-type", function () {
    updateMaintenanceScopeTargetSelect();

    $("#maintenance-scope-target")
        .removeClass("field-error")
        .attr("aria-invalid", "false")
        .next(".field-error-text")
        .remove();
});


function updateMaintenanceLifecycleOptions() {
    const suppressIncident = $("#maintenance-behavior").val() === "suppress_incident";
    const applyCheckbox = $("#maintenance-apply-to-existing");

    applyCheckbox.prop("disabled", suppressIncident);
    if (suppressIncident) {
        applyCheckbox.prop("checked", false);
        $("#maintenance-apply-to-existing-help").text(
            i18n.t("maintenance.form.apply_to_existing_unavailable")
        );
    } else {
        $("#maintenance-apply-to-existing-help").text(
            i18n.t("maintenance.form.apply_to_existing_help")
        );
    }

    $("#maintenance-reactivate-warning").toggleClass(
        "is-hidden",
        $("#maintenance-reactivate-on-end").is(":checked")
    );
}

$(document)
    .off("change.maintenanceLifecycle", "#maintenance-behavior, #maintenance-reactivate-on-end")
    .on(
        "change.maintenanceLifecycle",
        "#maintenance-behavior, #maintenance-reactivate-on-end",
        updateMaintenanceLifecycleOptions
    );
