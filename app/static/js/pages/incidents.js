let incidentsCurrentPage = 1;
let incidentsPageSize = 25;
let incidentsPagination = {page: 1, pages: 0, total: 0};
let incidentsLoadGeneration = 0;
let incidentsTeams = [];
let incidentsPriorities = [];
let currentIncident = null;
let currentIncidentLinks = [];
let currentIncidentEvents = [];

const INCIDENT_ACTIVE_STATUSES = ["declared", "investigating", "identified", "monitoring"];
const INCIDENT_STATUSES = ["declared", "investigating", "identified", "monitoring", "resolved", "closed", "cancelled"];

function incidentAsArray(value) {
    if (Array.isArray(value)) {
        return value;
    }
    if (value && Array.isArray(value.items)) {
        return value.items;
    }
    return [];
}

function incidentCanRespond(incident) {
    const permissions = (incident && incident.permissions) || {};
    return Boolean(permissions.can_respond);
}

function incidentCanCreateForTeam(team) {
    const permissions = (team && team.permissions) || {};
    return Boolean(
        permissions.can_create_incident
        || permissions.can_create_manual_alert_group
    );
}

function incidentStatusLabel(status) {
    return i18n.t("incidents.status." + String(status || "declared"), {}, status || "-");
}

function incidentStatusPill(status) {
    return $("<span>")
        .addClass("incident-status-pill")
        .toggleClass("is-resolved", status === "resolved")
        .toggleClass("is-closed", status === "closed")
        .toggleClass("is-cancelled", status === "cancelled")
        .text(incidentStatusLabel(status));
}

function incidentPriorityBadge(priority) {
    const slug = String(priority || "p3").toLowerCase();
    const cls = typeof priorityBadgeClass === "function"
        ? priorityBadgeClass({priority_slug: slug})
        : "badge-info";
    return makeAlertBadge(slug.toUpperCase(), cls);
}

function incidentSelectedTeamId() {
    if (typeof selectedTeamId !== "function") {
        return null;
    }
    const value = selectedTeamId();
    return value ? Number(value) : null;
}

function incidentListParams() {
    const params = new URLSearchParams();
    const teamId = incidentSelectedTeamId();
    const status = $("#incidents-status-filter").val();
    const search = $.trim($("#incidents-search").val() || "");

    params.set("page", incidentsCurrentPage);
    params.set("page_size", incidentsPageSize);
    if (teamId) {
        params.set("team_id", teamId);
    }
    if (status) {
        params.set("status", status);
    }
    if (search) {
        params.set("search", search);
    }
    return params;
}

function loadIncidents() {
    const generation = ++incidentsLoadGeneration;
    const params = incidentListParams();

    if (window.AppLoading) {
        AppLoading.showTableSkeleton("#incidents-table-body", {columns: 9, rows: 6});
    }

    apiGet("/api/incidents?" + params.toString(), function (response) {
        if (generation !== incidentsLoadGeneration) {
            return;
        }
        const items = incidentAsArray(response);
        incidentsPagination = response.pagination || {page: 1, pages: 0, total: items.length};
        renderIncidentsTable(items);
        renderIncidentsPagination();
        loadIncidentsSummary(generation);
        loadIncidentCreatePermissions();
        syncIncidentDetailsFromUrl();
    }, function (xhr) {
        if (generation !== incidentsLoadGeneration) {
            return;
        }
        $("#incidents-table-body").empty().append(
            $("<tr>").append(
                $("<td>")
                    .attr("colspan", 9)
                    .addClass("empty-table-cell")
                    .text(i18n.t("incidents.empty.failed"))
            )
        );
        showApiError(xhr);
    });
}

function loadIncidentsSummary(generation) {
    const teamId = incidentSelectedTeamId();
    const base = new URLSearchParams({page: "1", page_size: "1"});
    if (teamId) {
        base.set("team_id", teamId);
    }

    const counts = {resolved: 0, closed: 0, cancelled: 0};
    const statuses = Object.keys(counts);
    let remaining = statuses.length;

    $("#incidents-summary-total").text(incidentsPagination.total || 0);

    statuses.forEach(function (status) {
        const params = new URLSearchParams(base.toString());
        params.set("status", status);
        apiGet("/api/incidents?" + params.toString(), function (response) {
            if (generation !== incidentsLoadGeneration) {
                return;
            }
            counts[status] = Number((response.pagination || {}).total || 0);
            remaining -= 1;
            if (!remaining) {
                const total = Number(incidentsPagination.total || 0);
                const active = Math.max(total - counts.resolved - counts.closed - counts.cancelled, 0);
                $("#incidents-summary-active").text(active);
                $("#incidents-summary-resolved").text(counts.resolved);
                $("#incidents-summary-closed").text(counts.closed);
            }
        });
    });
}

function renderIncidentsTable(items) {
    const body = $("#incidents-table-body");
    body.empty();

    if (!items.length) {
        body.append(
            $("<tr>").append(
                $("<td>")
                    .attr("colspan", 9)
                    .addClass("empty-table-cell")
                    .text(i18n.t("incidents.empty.none"))
            )
        );
        return;
    }

    items.forEach(function (incident) {
        const row = $("<tr>");
        row.append($("<td>").text("#" + incident.id));
        row.append(
            $("<td>").append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("incident-title-button")
                    .text(incident.title || "-")
                    .on("click", function () {
                        openIncidentDetailsPage(incident.id);
                    })
            )
        );
        row.append($("<td>").append(incidentStatusPill(incident.workflow_status)));
        row.append($("<td>").append(incidentPriorityBadge(incident.priority)));
        row.append($("<td>").text(incident.team_name || incident.team_slug || "-"));
        row.append($("<td>").text(incident.service_name || incident.service_slug || "-"));
        row.append($("<td>").text(
            incident.assignee
                ? (incident.assignee.display_name || incident.assignee.username || "-")
                : i18n.t("incidents.labels.unassigned")
        ));
        row.append($("<td>").text(formatDateTimeMinutes(incident.updated_at)));
        row.append(
            $("<td>")
                .addClass("actions-cell")
                .append(
                    $("<button>")
                        .attr("type", "button")
                        .addClass("btn btn-small")
                        .text(i18n.t("incidents.actions.open"))
                        .on("click", function () {
                            openIncidentDetailsPage(incident.id);
                        })
                )
        );
        body.append(row);
    });
}

function renderIncidentsPagination() {
    const page = Number(incidentsPagination.page || incidentsCurrentPage || 1);
    const pages = Number(incidentsPagination.pages || 0);
    const total = Number(incidentsPagination.total || 0);
    incidentsCurrentPage = page;

    $("#incidents-pagination-summary").text(
        i18n.t("incidents.pagination.total", {count: total})
    );
    $("#incidents-pagination-page").text(
        pages
            ? i18n.t("incidents.pagination.page", {page: page, pages: pages})
            : ""
    );
    $("#incidents-prev-page").prop("disabled", page <= 1);
    $("#incidents-next-page").prop("disabled", !pages || page >= pages);
}

function loadIncidentCreatePermissions() {
    apiGet("/api/teams", function (response) {
        incidentsTeams = incidentAsArray(response);
        $("#open-incident-create-modal").toggleClass(
            "is-hidden",
            !incidentsTeams.some(incidentCanCreateForTeam)
        );
    });
}

function loadIncidentPriorities(callback) {
    apiGet("/api/incidents/priorities", function (items) {
        incidentsPriorities = incidentAsArray(items);
        if (typeof callback === "function") {
            callback(incidentsPriorities);
        }
    });
}

function renderIncidentCreateTeamOptions() {
    const select = $("#incident-create-team");
    const teams = incidentsTeams.filter(incidentCanCreateForTeam);
    select.empty().append(
        $("<option>").val("").text(i18n.t("incidents.form.select_team"))
    );
    teams.forEach(function (team) {
        select.append(
            $("<option>").val(team.id).text(team.name || team.slug || ("#" + team.id))
        );
    });
    const selected = incidentSelectedTeamId();
    if (selected && teams.some(function (team) { return Number(team.id) === selected; })) {
        select.val(String(selected));
    } else if (teams.length === 1) {
        select.val(String(teams[0].id));
    }
}

function renderIncidentPriorityOptions(selectSelector, selectedPriority) {
    const select = $(selectSelector);
    select.empty();
    incidentsPriorities
        .filter(function (priority) { return priority.enabled !== false; })
        .forEach(function (priority) {
            select.append(
                $("<option>")
                    .val(priority.slug)
                    .text(String(priority.slug || "").toUpperCase() + (priority.name ? " — " + priority.name : ""))
            );
        });
    select.val(selectedPriority || "p3");
}

function loadIncidentAssignees(teamId, assigneeSelector, callback) {
    const assignees = $(assigneeSelector);
    assignees.empty().append($("<option>").val("").text(i18n.t("incidents.labels.unassigned")));
    if (!teamId) {
        if (typeof callback === "function") { callback(); }
        return;
    }
    apiGet("/api/teams/" + encodeURIComponent(teamId) + "/users", function (memberships) {
        incidentAsArray(memberships).filter(function (membership) {
            return membership.active !== false;
        }).forEach(function (membership) {
            assignees.append(
                $("<option>")
                    .val(membership.user_id)
                    .text(membership.display_name || membership.username || ("#" + membership.user_id))
            );
        });
        if (typeof callback === "function") { callback(); }
    }, function () {
        if (typeof callback === "function") { callback(); }
    });
}

function loadIncidentTeamOptions(teamId, serviceSelector, assigneeSelector, callback) {
    const services = $(serviceSelector);
    const assignees = $(assigneeSelector);
    services.empty().append($("<option>").val("").text(i18n.t("incidents.form.no_service")));
    assignees.empty().append($("<option>").val("").text(i18n.t("incidents.labels.unassigned")));

    if (!teamId) {
        if (typeof callback === "function") { callback(); }
        return;
    }

    let pending = 2;
    function done() {
        pending -= 1;
        if (!pending && typeof callback === "function") { callback(); }
    }

    apiGet("/api/services?team_id=" + encodeURIComponent(teamId), function (response) {
        incidentAsArray(response).filter(function (service) {
            return service.enabled !== false;
        }).forEach(function (service) {
            services.append($("<option>").val(service.id).text(service.name || service.slug || ("#" + service.id)));
        });
        done();
    }, done);

    apiGet("/api/teams/" + encodeURIComponent(teamId) + "/users", function (memberships) {
        incidentAsArray(memberships).filter(function (membership) {
            return membership.active !== false;
        }).forEach(function (membership) {
            assignees.append(
                $("<option>")
                    .val(membership.user_id)
                    .text(membership.display_name || membership.username || ("#" + membership.user_id))
            );
        });
        done();
    }, done);
}

function openIncidentCreateModal() {
    $("#incident-create-error").addClass("is-hidden").text("");
    $("#incident-create-title").val("");
    $("#incident-create-description").val("");

    const afterTeams = function () {
        renderIncidentCreateTeamOptions();
        loadIncidentPriorities(function () {
            renderIncidentPriorityOptions("#incident-create-priority", "p3");
            const teamId = Number($("#incident-create-team").val() || 0);
            loadIncidentTeamOptions(teamId, "#incident-create-service", "#incident-create-assignee", function () {
                openAppModal("#incident-create-modal");
                $("#incident-create-title").trigger("focus");
            });
        });
    };

    if (incidentsTeams.length) {
        afterTeams();
        return;
    }
    apiGet("/api/teams", function (response) {
        incidentsTeams = incidentAsArray(response);
        afterTeams();
    });
}

function saveIncidentCreate() {
    const payload = {
        team_id: Number($("#incident-create-team").val() || 0),
        service_id: $("#incident-create-service").val() ? Number($("#incident-create-service").val()) : null,
        title: $.trim($("#incident-create-title").val() || ""),
        description: $.trim($("#incident-create-description").val() || "") || null,
        priority: $("#incident-create-priority").val() || null,
        assignee_id: $("#incident-create-assignee").val() ? Number($("#incident-create-assignee").val()) : null,
    };

    if (!payload.team_id || !payload.title) {
        $("#incident-create-error")
            .removeClass("is-hidden")
            .text(i18n.t("incidents.create.required"));
        return;
    }

    const button = $("#save-incident-create");
    if (window.AppLoading) { AppLoading.setButtonLoading(button, true); }
    apiPost("/api/incidents", payload, function (incident) {
        if (window.AppLoading) { AppLoading.setButtonLoading(button, false); }
        closeAppModal("#incident-create-modal");
        loadIncidents();
        if (incident && incident.id) {
            openIncidentDetailsPage(incident.id);
        }
    }, function (xhr) {
        if (window.AppLoading) { AppLoading.setButtonLoading(button, false); }
        $("#incident-create-error").removeClass("is-hidden").text(getApiErrorMessage(xhr));
    });
}

function openIncidentDetailsPage(incidentId) {
    const target = appUrlWithGlobalTeamScope("/incidents/" + encodeURIComponent(incidentId));
    navigate(target, true);
}

function incidentIdFromLocation() {
    const match = String(window.location.pathname || "").match(/^\/incidents\/(\d+)\/?$/);
    return match ? Number(match[1]) : null;
}

function syncIncidentDetailsFromUrl() {
    const incidentId = incidentIdFromLocation();
    if (!incidentId) {
        if ($("#incident-details-modal").hasClass("is-open")) {
            closeAppModal("#incident-details-modal");
        }
        return;
    }
    loadIncidentDetails(incidentId);
}

function closeIncidentDetails(options) {
    const settings = $.extend({updateUrl: true}, options || {});
    closeAppModal("#incident-details-modal");
    currentIncident = null;
    currentIncidentLinks = [];
    currentIncidentEvents = [];
    if (settings.updateUrl && incidentIdFromLocation()) {
        const target = appUrlWithGlobalTeamScope("/incidents");
        history.pushState({path: target}, "", target);
    }
}

function loadIncidentDetails(incidentId) {
    clearIncidentDetailsErrors();
    if (window.AppLoading) {
        AppLoading.showInline("#incidents-loading-indicator", i18n.t("common.loading"));
    }
    apiGet("/api/incidents/" + encodeURIComponent(incidentId), function (incident) {
        if (window.AppLoading) { AppLoading.clear("#incidents-loading-indicator"); }
        currentIncident = incident;
        renderIncidentDetails(incident);
        loadIncidentDetailCollections(incident);
        openAppModal("#incident-details-modal");
    }, function (xhr) {
        if (window.AppLoading) { AppLoading.clear("#incidents-loading-indicator"); }
        showApiError(xhr);
        closeIncidentDetails({updateUrl: true});
    });
}

function loadIncidentDetailCollections(incident) {
    const incidentId = Number(incident && incident.id);
    if (!incidentId) {
        return;
    }

    const canRespond = incidentCanRespond(incident);
    const encodedIncidentId = encodeURIComponent(incidentId);

    $("#incident-linked-alert-groups")
        .empty()
        .append($("<div>").addClass("overview-empty").text(i18n.t("common.loading")));
    $("#incident-events")
        .empty()
        .append($("<div>").addClass("overview-empty").text(i18n.t("common.loading")));

    apiGet(
        "/api/incidents/" + encodedIncidentId + "/alert-groups",
        function (links) {
            if (!currentIncident || Number(currentIncident.id) !== incidentId) {
                return;
            }
            currentIncidentLinks = Array.isArray(links) ? links : [];
            renderIncidentLinks(currentIncidentLinks, canRespond);
        },
        function (xhr) {
            if (!currentIncident || Number(currentIncident.id) !== incidentId) {
                return;
            }
            $("#incident-linked-alert-groups")
                .empty()
                .append($("<div>").addClass("overview-empty").text(getApiErrorMessage(xhr)));
        }
    );

    loadIncidentEvents(incident, true);
}

function loadIncidentEvents(incident, showLoading) {
    const incidentId = Number(incident && incident.id);
    if (!incidentId) {
        return;
    }

    if (showLoading !== false) {
        $("#incident-events")
            .empty()
            .append($("<div>").addClass("overview-empty").text(i18n.t("common.loading")));
    }

    apiGet(
        "/api/incidents/" + encodeURIComponent(incidentId) + "/events",
        function (events) {
            if (!currentIncident || Number(currentIncident.id) !== incidentId) {
                return;
            }
            currentIncidentEvents = Array.isArray(events) ? events : [];
            renderIncidentEvents(currentIncidentEvents);
        },
        function (xhr) {
            if (!currentIncident || Number(currentIncident.id) !== incidentId) {
                return;
            }
            if (showLoading !== false) {
                $("#incident-events")
                    .empty()
                    .append($("<div>").addClass("overview-empty").text(getApiErrorMessage(xhr)));
            }
        }
    );
}

function incidentDetailItem(label, value) {
    return $("<div>")
        .addClass("details-card")
        .append($("<div>").addClass("details-label").text(label))
        .append($("<div>").addClass("details-value").text(value === null || value === undefined || value === "" ? "-" : value));
}

function renderIncidentDetails(incident) {
    $("#incident-details-title").text("#" + incident.id + " " + (incident.title || i18n.t("incidents.details.title")));
    $("#incident-details-subtitle").text(
        (incident.team_name || incident.team_slug || "-") + " · " + incidentStatusLabel(incident.workflow_status)
    );

    const summary = $("#incident-details-summary").empty();
    summary.append(incidentDetailItem(i18n.t("incidents.form.status"), incidentStatusLabel(incident.workflow_status)));
    summary.append(incidentDetailItem(i18n.t("incidents.form.priority"), String(incident.priority || "p3").toUpperCase()));
    summary.append(incidentDetailItem(i18n.t("incidents.form.team"), incident.team_name || incident.team_slug || "-"));
    summary.append(incidentDetailItem(i18n.t("incidents.form.service"), incident.service_name || incident.service_slug || "-"));
    summary.append(incidentDetailItem(i18n.t("incidents.form.assignee"), incident.assignee ? (incident.assignee.display_name || incident.assignee.username) : i18n.t("incidents.labels.unassigned")));
    summary.append(incidentDetailItem(i18n.t("incidents.details.declared_at"), formatDateTimeMinutes(incident.declared_at)));
    if (incident.description) {
        summary.append(incidentDetailItem(i18n.t("incidents.form.description"), incident.description));
    }

    const canRespond = incidentCanRespond(incident);
    renderIncidentStatusControl(incident, canRespond);
    renderIncidentAssignmentControl(incident, canRespond);

    $("#incident-link-controls").toggleClass("is-hidden", !canRespond);
    $("#incident-close-action").toggle(canRespond && incident.workflow_status !== "closed" && incident.workflow_status !== "cancelled");
    $("#incident-reopen-action").toggle(canRespond && (incident.workflow_status === "closed" || incident.workflow_status === "resolved"));
}

function renderIncidentStatusControl(incident, canRespond) {
    const select = $("#incident-details-status").empty();
    INCIDENT_STATUSES.forEach(function (status) {
        select.append($("<option>").val(status).text(incidentStatusLabel(status)));
    });
    select.val(incident.workflow_status).prop("disabled", !canRespond);
}

function renderIncidentAssignmentControl(incident, canRespond) {
    const select = $("#incident-details-assignee");
    loadIncidentAssignees(incident.team_id, "#incident-details-assignee", function () {
        select.val(incident.assignee_id ? String(incident.assignee_id) : "");
        select.prop("disabled", !canRespond);
    });
    $("#incident-assign-me, #incident-unassign").prop("disabled", !canRespond);
}

function renderIncidentLinks(links, canRespond) {
    const target = $("#incident-linked-alert-groups").empty();
    $("#incident-linked-alert-groups-count").text(String(links.length));
    if (!links.length) {
        target.append($("<div>").addClass("overview-empty").text(i18n.t("incidents.links.none")));
        return;
    }
    links.forEach(function (link) {
        const group = link.alert_group || {};
        const item = $("<div>").addClass("incident-linked-group");
        item.append(
            $("<div>")
                .addClass("incident-linked-group-main")
                .append($("<div>").addClass("incident-linked-group-title").text("#" + link.alert_group_id + " " + (group.title || "")))
                .append($("<div>").addClass("incident-linked-group-meta").text(
                    (link.relation_type || "related") + " · " + (group.status || "-") + " · " + (group.source || "-")
                ))
        );
        item.append(
            $("<button>")
                .attr("type", "button")
                .addClass("btn btn-small")
                .text(i18n.t("incidents.actions.open_alert"))
                .on("click", function () { navigate("/alerts/" + link.alert_group_id, true); })
        );
        if (canRespond) {
            item.append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("btn btn-danger btn-small")
                    .text(i18n.t("incidents.actions.unlink"))
                    .on("click", function () { unlinkIncidentAlertGroup(link.alert_group_id); })
            );
        }
        target.append(item);
    });
}

function renderIncidentEvents(events) {
    const target = $("#incident-events").empty();
    if (!events.length) {
        target.append($("<div>").addClass("overview-empty").text(i18n.t("incidents.activity.none")));
        return;
    }
    events.slice().reverse().forEach(function (event) {
        target.append(
            $("<div>")
                .addClass("event-item")
                .append($("<div>").addClass("event-dot"))
                .append(
                    $("<div>")
                        .addClass("event-content")
                        .append($("<div>").addClass("event-title").text(event.message || event.event_type || "-"))
                        .append($("<div>").addClass("event-time").text(formatDateTimeMinutes(event.created_at)))
                )
        );
    });
}

function refreshCurrentIncident() {
    if (currentIncident && currentIncident.id) {
        loadIncidentDetails(currentIncident.id);
    }
    loadIncidents();
}

function incidentInlineErrorMessage(xhr) {
    const data = xhr && xhr.responseJSON ? xhr.responseJSON : null;
    let message = data && data.message
        ? data.message
        : (data && data.error ? data.error : getApiErrorMessage(xhr));

    message = String(message || i18n.t("shared.api.request_failed")).trim();
    if (!message) {
        return message;
    }

    message = message.charAt(0).toUpperCase() + message.slice(1);
    if (!/[.!?]$/.test(message)) {
        message += ".";
    }
    return message;
}

function clearIncidentDetailsErrors() {
    $("#incident-details-error").addClass("is-hidden").text("");
    $("#incident-status-error").addClass("is-hidden").text("");
}

function showIncidentDetailsError(xhr) {
    $("#incident-details-error")
        .removeClass("is-hidden")
        .text(incidentInlineErrorMessage(xhr));
}

function showIncidentStatusError(xhr) {
    $("#incident-status-error")
        .removeClass("is-hidden")
        .text(incidentInlineErrorMessage(xhr));
}

function mutateIncident(method, suffix, payload) {
    if (!currentIncident) { return; }
    clearIncidentDetailsErrors();
    apiRequest(
        method,
        "/api/incidents/" + encodeURIComponent(currentIncident.id) + suffix,
        payload,
        refreshCurrentIncident,
        showIncidentDetailsError
    );
}

function transitionIncident(suffix, payload) {
    if (!currentIncident) { return; }

    const statusBeforeRequest = currentIncident.workflow_status;
    clearIncidentDetailsErrors();

    apiRequest(
        "POST",
        "/api/incidents/" + encodeURIComponent(currentIncident.id) + suffix,
        payload,
        refreshCurrentIncident,
        function (xhr) {
            $("#incident-details-status").val(statusBeforeRequest);
            showIncidentStatusError(xhr);
        }
    );
}

function unlinkIncidentAlertGroup(groupId) {
    if (!currentIncident) { return; }
    const incidentId = Number(currentIncident.id);
    apiDelete(
        "/api/incidents/" + encodeURIComponent(incidentId) + "/alert-groups/" + encodeURIComponent(groupId),
        function () {
            if (!currentIncident || Number(currentIncident.id) !== incidentId) {
                return;
            }
            currentIncidentLinks = currentIncidentLinks.filter(function (link) {
                return Number(link.alert_group_id) !== Number(groupId);
            });
            renderIncidentLinks(currentIncidentLinks, incidentCanRespond(currentIncident));
            loadIncidentEvents(currentIncident, false);
        },
        function (xhr) {
            $("#incident-details-error").removeClass("is-hidden").text(getApiErrorMessage(xhr));
        }
    );
}

function linkIncidentAlertGroup(groupId, relationType) {
    if (!currentIncident) { return; }

    const incidentId = Number(currentIncident.id);
    const button = $("#incident-link-alert-group");
    if (window.AppLoading) {
        AppLoading.setButtonLoading(button, true);
    }

    apiPost(
        "/api/incidents/" + encodeURIComponent(incidentId) + "/alert-groups",
        {
            alert_group_id: Number(groupId),
            relation_type: relationType || "related",
        },
        function (link) {
            if (window.AppLoading) {
                AppLoading.setButtonLoading(button, false);
            }
            if (!currentIncident || Number(currentIncident.id) !== incidentId) {
                return;
            }

            currentIncidentLinks = currentIncidentLinks.filter(function (item) {
                return Number(item.alert_group_id) !== Number(link.alert_group_id);
            });
            currentIncidentLinks.push(link);
            renderIncidentLinks(currentIncidentLinks, incidentCanRespond(currentIncident));
            $("#incident-link-alert-group-id").val("");
            $("#incident-details-error").addClass("is-hidden").text("");
            loadIncidentEvents(currentIncident, false);
        },
        function (xhr) {
            if (window.AppLoading) {
                AppLoading.setButtonLoading(button, false);
            }
            $("#incident-details-error").removeClass("is-hidden").text(getApiErrorMessage(xhr));
        }
    );
}

$(document).on("click", "#reload-incidents", function () { loadIncidents(); });
$(document).on("input", "#incidents-search", function () { incidentsCurrentPage = 1; loadIncidents(); });
$(document).on("change", "#incidents-status-filter", function () { incidentsCurrentPage = 1; loadIncidents(); });
$(document).on("click", "#incidents-prev-page", function () { if (incidentsCurrentPage > 1) { incidentsCurrentPage -= 1; loadIncidents(); } });
$(document).on("click", "#incidents-next-page", function () { if (incidentsCurrentPage < Number(incidentsPagination.pages || 0)) { incidentsCurrentPage += 1; loadIncidents(); } });

$(document).on("click", "#open-incident-create-modal", openIncidentCreateModal);
$(document).on("click", "#close-incident-create-modal, #cancel-incident-create", function () { closeAppModal("#incident-create-modal"); });
$(document).on("change", "#incident-create-team", function () {
    loadIncidentTeamOptions(Number($(this).val() || 0), "#incident-create-service", "#incident-create-assignee");
});
$(document).on("click", "#save-incident-create", saveIncidentCreate);

$(document).on("click", "#close-incident-details, #close-incident-details-footer", function () { closeIncidentDetails(); });
$(document).on("click", "#incident-details-modal", function (event) { if (event.target === this) { closeIncidentDetails(); } });

$(document).on("change", "#incident-details-status", function () {
    if (!currentIncident || $(this).val() === currentIncident.workflow_status) { return; }
    transitionIncident("/status", {
        row_version: currentIncident.row_version,
        status: $(this).val(),
    });
});
$(document).on("change", "#incident-details-assignee", function () {
    mutateIncident("PUT", "/assignee", {
        row_version: currentIncident.row_version,
        assignee_id: $(this).val() ? Number($(this).val()) : null,
    });
});
$(document).on("click", "#incident-assign-me", function () {
    mutateIncident("PUT", "/assignee/me", {row_version: currentIncident.row_version});
});
$(document).on("click", "#incident-unassign", function () {
    mutateIncident("PUT", "/assignee", {row_version: currentIncident.row_version, assignee_id: null});
});
$(document).on("click", "#incident-close-action", function () {
    transitionIncident("/close", {row_version: currentIncident.row_version});
});
$(document).on("click", "#incident-reopen-action", function () {
    transitionIncident("/reopen", {row_version: currentIncident.row_version});
});
$(document).on("click", "#incident-link-alert-group", function () {
    const groupId = Number($("#incident-link-alert-group-id").val() || 0);
    if (!groupId) { return; }
    linkIncidentAlertGroup(
        groupId,
        $("#incident-link-relation").val() || "related"
    );
});
