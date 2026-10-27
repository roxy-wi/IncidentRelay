let incidentsCurrentPage = 1;
let incidentsPageSize = 25;
let incidentsPagination = {page: 1, pages: 0, total: 0};
let incidentsLoadGeneration = 0;
let incidentsSearchTimer = null;
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
        incidentsPageSize = Number(incidentsPagination.page_size || incidentsPageSize || 25);
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
        ["total", "active", "resolved", "closed"].forEach(function (name) {
            $("#incidents-summary-" + name).text("—");
        });
        showApiError(xhr);
    });
}

function loadIncidentsSummary(generation) {
    // Every summary counter uses the same team scope, independently of list
    // search/status filters and pagination. Never subtract unfiltered counts
    // from a filtered list total.
    const base = new URLSearchParams({page: "1", page_size: "1"});
    const teamId = incidentSelectedTeamId();
    if (teamId) { base.set("team_id", teamId); }

    const statuses = ["total", "resolved", "closed", "cancelled"];
    const counts = {};
    let pending = statuses.length;
    let failed = false;
    ["total", "active", "resolved", "closed"].forEach(function (name) {
        $("#incidents-summary-" + name).text("—");
    });

    function finish() {
        if (generation !== incidentsLoadGeneration) { return; }
        pending -= 1;
        if (pending !== 0 || failed) { return; }
        $("#incidents-summary-total").text(counts.total);
        $("#incidents-summary-active").text(Math.max(
            counts.total - counts.resolved - counts.closed - counts.cancelled, 0
        ));
        $("#incidents-summary-resolved").text(counts.resolved);
        $("#incidents-summary-closed").text(counts.closed);
    }

    statuses.forEach(function (status) {
        const params = new URLSearchParams(base.toString());
        if (status !== "total") { params.set("status", status); }
        apiGet("/api/incidents?" + params.toString(), function (response) {
            if (generation !== incidentsLoadGeneration) { return; }
            counts[status] = Number((response.pagination || {}).total || 0);
            finish();
        }, function () {
            failed = true;
            finish();
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
        row.append(
            $("<td>").append(
                $("<a>")
                    .attr("href", buildIncidentDetailsUrl(incident.id))
                    .attr("title", i18n.t("incidents.actions.open"))
                    .addClass("alerts-id-link")
                    .text("#" + incident.id)
                    .on("click", function (event) {
                        event.preventDefault();
                        openIncidentDetailsPage(incident.id);
                    })
            )
        );
        row.append($("<td>").append(incidentStatusPill(incident.workflow_status)));
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

    $("#incidents-list-subtitle").text(
        i18n.t("incidents.pagination.total", {count: total})
    );
    $("#incidents-page-size").val(String(incidentsPageSize));
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

function buildIncidentDetailsUrl(incidentId) {
    return appUrlWithGlobalTeamScope("/incidents/" + encodeURIComponent(incidentId));
}

function openIncidentDetailsPage(incidentId) {
    navigate(buildIncidentDetailsUrl(incidentId), true);
}

function incidentIdFromLocation() {
    const match = String(window.location.pathname || "").match(/^\/incidents\/(\d+)\/?$/);
    return match ? Number(match[1]) : null;
}

function syncIncidentDetailsFromUrl() {
    const incidentId = incidentIdFromLocation();
    if (!incidentId) {
        $("#incident-details-modal").addClass("is-hidden");
        $("#incidents-list-view").removeClass("is-hidden");
        return;
    }
    loadIncidentDetails(incidentId);
}

function closeIncidentDetails(options) {
    const settings = $.extend({updateUrl: true}, options || {});
    $("#incident-details-modal").addClass("is-hidden");
    $("#incidents-list-view").removeClass("is-hidden");
    currentIncident = null;
    currentIncidentLinks = [];
    currentIncidentEvents = [];
    if (settings.updateUrl && incidentIdFromLocation()) {
        const target = appUrlWithGlobalTeamScope("/incidents");
        history.pushState({path: target}, "", target);
    }
}

function loadIncidentDetails(incidentId) {
    if (!currentIncident || Number(currentIncident.id) !== Number(incidentId)) {
        currentIncidentLinks = [];
        currentIncidentEvents = [];
    }
    clearIncidentDetailsErrors();
    if (window.AppLoading) {
        AppLoading.showInline("#incidents-loading-indicator", i18n.t("common.loading"));
    }
    apiGet("/api/incidents/" + encodeURIComponent(incidentId), function (incident) {
        if (window.AppLoading) { AppLoading.clear("#incidents-loading-indicator"); }
        currentIncident = incident;
        renderIncidentDetails(incident);
        loadIncidentDetailCollections(incident);
        $("#incidents-list-view").addClass("is-hidden");
        $("#incident-details-modal").removeClass("is-hidden");
    }, function (xhr) {
        if (window.AppLoading) { AppLoading.clear("#incidents-loading-indicator"); }
        showApiError(xhr);
        $("#incident-details-modal").addClass("is-hidden");
        $("#incidents-list-view").removeClass("is-hidden");
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
            // Link metadata may arrive after events. Re-render so the source
            // navigation is only shown for a currently visible linked group.
            if (currentIncidentEvents.length) { renderIncidentEvents(currentIncidentEvents); }
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
    loadIncidentCollaboration(incident);
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
        "/api/incidents/" + encodeURIComponent(incidentId) + "/activity",
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
    $("#incident-root-cause").val(incident.root_cause || "").prop("disabled", !canRespond);
    $("#incident-resolution-summary").val(incident.resolution_summary || "").prop("disabled", !canRespond);
    $("#incident-resolution-save").toggleClass("is-hidden", !canRespond);
    ["#incident-participants-controls", "#incident-stakeholders-controls", "#incident-services-controls", "#incident-comments-controls"]
        .forEach(function (selector) { $(selector).toggleClass("is-hidden", !canRespond); });
    renderIncidentStatusControl(incident, canRespond);
    renderIncidentAssignmentControl(incident, canRespond);

    $("#incident-link-controls").toggleClass("is-hidden", !canRespond);
    if (canRespond) {
        const picker = initIncidentAlertGroupLinkPicker();
        if (picker) {
            picker.clear(true);
            picker.clearOptions();
            picker.loadedSearches = {};
        }
    }
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
    events.forEach(function (event) {
        const reopened = event.event_type === "incident_reopened_by_alert_group";
        const data = event.data || {};
        const detail = $("<div>")
            .addClass("event-content")
            .append($("<div>")
                .addClass("event-title")
                .text(reopened
                    ? i18n.t("incidents.activity.reopened_by_alert")
                    : (event.message || event.event_type || "-")))
            .append($("<div>").addClass("event-time").text(
                (event.source_type || "Incident") + " #" + (event.source_id || currentIncident.id)
                + " · " + formatDateTimeMinutes(event.created_at)
            ));

        if (reopened) {
            if (data.from && data.to) {
                detail.append(
                    $("<div>")
                        .addClass("table-subtitle")
                        .text(incidentStatusLabel(data.from) + " → " + incidentStatusLabel(data.to))
                );
            }
            const linkedGroup = currentIncidentLinks.find(function (link) {
                return Number(link.alert_group_id) === Number(data.alert_group_id);
            });
            if (linkedGroup && linkedGroup.alert_group) {
                detail.append(
                    $("<button>")
                        .attr("type", "button")
                        .addClass("btn btn-secondary btn-small")
                        .text(i18n.t("incidents.activity.open_reopened_alert", {id: data.alert_group_id}))
                        .on("click", function () {
                            navigate("/alerts/" + encodeURIComponent(data.alert_group_id), true);
                        })
                );
            }
        }
        target.append(
            $("<div>").addClass("event-item")
                .append($("<div>").addClass("event-dot"))
                .append(detail)
        );
    });
}

// Incident-owned collaboration. Every mutation is permission-checked by the API.
function incidentUserLabel(user, fallbackId) {
    if (user) {
        const name = user.display_name || user.username || user.email;
        if (name) { return name; }
    }
    return fallbackId ? ("User #" + fallbackId) : i18n.t("incidents.workspace.unknown_user");
}

function loadIncidentStakeholderUsers(incident) {
    const incidentId = Number(incident.id);
    const select = $("#incident-stakeholder-user");
    select.empty().append($("<option>").val("").text(i18n.t("incidents.workspace.picker_placeholder")));
    if (!incident.team_id) { return; }
    apiGet("/api/teams/" + encodeURIComponent(incident.team_id) + "/users", function (memberships) {
        if (!currentIncident || Number(currentIncident.id) !== incidentId) { return; }
        const seen = new Set();
        incidentAsArray(memberships).forEach(function (member) {
            const user = member.user || member;
            const id = Number(member.user_id || user.id);
            if (!id || member.active === false || seen.has(id)) { return; }
            seen.add(id);
            const label = user.display_name || member.display_name || user.username || member.username || ("User #" + id);
            const email = user.email || member.email || "";
            select.append($("<option>").val(String(id)).text(label + (email ? " · " + email : "")));
        });
        // Tom Select supports searching names and email within option text.
        if (select[0] && typeof TomSelect !== "undefined") {
            if (select[0].tomselect) { select[0].tomselect.destroy(); }
            new TomSelect(select[0], {create: false, allowEmptyOption: true, maxOptions: 1000,
                placeholder: i18n.t("incidents.workspace.picker_search"), searchField: ["text"]});
        }
    });
}
function incidentCollectionMessage(selector, message) {
    $(selector).empty().append($("<div>").addClass("overview-empty").text(message));
}

function incidentCollaborationGet(incident, suffix, selector, render) {
    const id = Number(incident.id);
    incidentCollectionMessage(selector, i18n.t("common.loading"));
    apiGet("/api/incidents/" + encodeURIComponent(id) + suffix, function (items) {
        if (!currentIncident || Number(currentIncident.id) !== id) { return; }
        render(incidentAsArray(items));
    }, function (xhr) {
        if (!currentIncident || Number(currentIncident.id) !== id) { return; }
        incidentCollectionMessage(selector, getApiErrorMessage(xhr));
    });
}

function incidentListRows(selector, items, title, canDelete, onDelete) {
    const target = $(selector).empty();
    if (!items.length) { incidentCollectionMessage(selector, i18n.t("incidents.workspace.empty_entries")); return; }
    items.forEach(function (item) {
        const row = $("<div>").addClass("incidents-collection-row");
        row.append($("<span>").addClass("incidents-collection-label").text(title(item)));
        if (canDelete) {
            row.append($("<button>").attr("type", "button").addClass("btn btn-small")
                .text(i18n.t("incidents.workspace.remove")).on("click", function () { onDelete(item); }));
        }
        target.append(row);
    });
}
function renderIncidentComments(items) {
    const target = $("#incident-comments-list").empty();
    if (!items.length) { incidentCollectionMessage("#incident-comments-list", i18n.t("incidents.workspace.empty_comments")); return; }
    items.forEach(function (item) {
        const author = incidentUserLabel(item.author, item.author_id);
        const initial = String(author).trim().charAt(0).toUpperCase() || "?";
        const article = $("<article>").addClass("incidents-comment");
        article.append($("<span>").addClass("incidents-comment-avatar").text(initial));
        const content = $("<div>").addClass("incidents-comment-content");
        const header = $("<div>").addClass("incidents-comment-meta");
        header.append($("<strong>").text(author));
        if (item.created_at) { header.append($("<time>").text(formatDateTimeMinutes(item.created_at))); }
        content.append(header).append($("<div>").addClass("incidents-comment-text").text(item.body || ""));
        article.append(content);
        target.append(article);
    });
}

function loadIncidentCollaboration(incident) {
    const id = Number(incident.id);
    const canWrite = incidentCanRespond(incident);
    incidentCollaborationGet(incident, "/participants", "#incident-participants-list", function (items) {
        incidentListRows("#incident-participants-list", items, function (item) {
            return incidentUserLabel(item.user, item.user_id || item.target_user_id)
                + " · " + (item.role || "responder");
        }, canWrite, function (item) {
            incidentCollaborationDelete("/participants/" + item.id);
        });
    });
    incidentCollaborationGet(incident, "/stakeholders", "#incident-stakeholders-list", function (items) {
        incidentListRows("#incident-stakeholders-list", items, function (item) {
            return (item.user ? incidentUserLabel(item.user, item.user_id) : (item.display_name || item.email || "—"))
                + " · " + (item.role || "stakeholder");
        }, canWrite, function (item) { incidentCollaborationDelete("/stakeholders/" + item.id); });
    });
    incidentCollaborationGet(incident, "/affected-services", "#incident-services-list", function (items) {
        const target = $("#incident-services-list").empty();
        if (!items.length) { incidentCollectionMessage("#incident-services-list", i18n.t("incidents.workspace.empty_services")); return; }
        items.forEach(function (item) {
            const id = Number(item.service_id);
            const row = $("<div>").addClass("incidents-collection-row incidents-service-context");
            const content = $("<div>").addClass("incidents-service-context-main");
            const name = item.service_name || item.service_slug || (i18n.t("incidents.workspace.service") + " #" + id);
            const heading = $("<div>").addClass("incidents-service-context-heading");
            if (id > 0) {
                heading.append($("<a>").addClass("incidents-service-link")
                    .attr("href", "/services?service_id=" + encodeURIComponent(id))
                    .text(name).on("click", function (event) {
                        event.preventDefault(); navigate("/services?service_id=" + encodeURIComponent(id), true);
                    }));
            } else { heading.append($("<span>").text(name)); }
            const meta = [item.status, item.criticality, item.tier, item.environment].filter(Boolean);
            if (meta.length) { heading.append($("<span>").addClass("incidents-service-meta").text(meta.join(" · "))); }
            content.append(heading);
            const resources = $("<div>").addClass("incidents-service-resources");
            (item.runbooks || []).forEach(function (resource) {
                resources.append($("<a>").attr({href: resource.url, target: "_blank", rel: "noopener noreferrer"})
                    .text(i18n.t("incidents.workspace.runbook") + ": " + resource.title));
            });
            (item.links || []).forEach(function (resource) {
                resources.append($("<a>").attr({href: resource.url, target: "_blank", rel: "noopener noreferrer"})
                    .text(resource.label || resource.type || i18n.t("incidents.workspace.service_link")));
            });
            (item.dependencies || []).forEach(function (dependency) {
                const url = "/services?service_id=" + encodeURIComponent(dependency.service_id);
                resources.append($("<a>").attr("href", url)
                    .text(i18n.t("incidents.workspace.depends_on") + ": " + dependency.name).on("click", function (event) {
                        event.preventDefault(); navigate(url, true);
                    }));
            });
            if (resources.children().length) { content.append(resources); }
            row.append(content);
            if (canWrite) {
                row.append($("<button>").attr("type", "button").addClass("btn btn-small")
                    .text(i18n.t("incidents.workspace.remove")).on("click", function () { incidentCollaborationDelete("/affected-services/" + id); }));
            }
            target.append(row);
        });
    });
    incidentCollaborationGet(incident, "/comments", "#incident-comments-list", renderIncidentComments);
    if (canWrite) {
        loadIncidentAssignees(incident.team_id, "#incident-participant-user");
        loadIncidentStakeholderUsers(incident);
        const select = $("#incident-service-select").empty().append($("<option>").val("").text(i18n.t("incidents.workspace.choose_service")));
        apiGet("/api/services", function (response) {
            if (!currentIncident || Number(currentIncident.id) !== id) { return; }
            incidentAsArray(response).filter(function (service) { return service.enabled !== false; })
                .forEach(function (service) {
                    select.append($("<option>").val(service.id).text(service.name || service.slug || ("#" + service.id)));
                });
        });
    }
}

function incidentCollaborationPost(suffix, payload, onSuccess) {
    if (!currentIncident || !incidentCanRespond(currentIncident)) { return; }
    const id = Number(currentIncident.id);
    apiPost("/api/incidents/" + encodeURIComponent(id) + suffix, payload, function () {
        if (!currentIncident || Number(currentIncident.id) !== id) { return; }
        if (typeof onSuccess === "function") { onSuccess(); }
        refreshCurrentIncident();
    }, showIncidentDetailsError);
}

function incidentCollaborationDelete(suffix) {
    if (!currentIncident || !incidentCanRespond(currentIncident)) { return; }
    const id = Number(currentIncident.id);
    apiDelete("/api/incidents/" + encodeURIComponent(id) + suffix, function () {
        if (currentIncident && Number(currentIncident.id) === id) { refreshCurrentIncident(); }
    }, showIncidentDetailsError);
}

$(document).on("click", "#incident-participant-add", function () {
    const userId = Number($("#incident-participant-user").val());
    if (!userId) { return; }
    incidentCollaborationPost("/participants", {user_id: userId, role: $("#incident-participant-role").val()});
});
$(document).on("click", "#incident-stakeholder-add", function () {
    const userId = Number($("#incident-stakeholder-user").val() || 0);
    const email = String($("#incident-stakeholder-email").val() || "").trim();
    if (!userId && !email) {
        showIncidentDetailsError({responseJSON: {message: i18n.t("incidents.workspace.select_user_or_email")}});
        return;
    }
    if (!userId && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
        $("#incident-stakeholder-email").trigger("focus");
        showIncidentDetailsError({responseJSON: {message: i18n.t("incidents.workspace.invalid_email")}});
        return;
    }
    incidentCollaborationPost("/stakeholders", userId
        ? {user_id: userId, role: "stakeholder"}
        : {email: email, role: "stakeholder"});
});
$(document).on("click", "#incident-service-add", function () {
    const serviceId = Number($("#incident-service-select").val());
    if (serviceId) { incidentCollaborationPost("/affected-services", {service_id: serviceId}); }
});
$(document).on("click", "#incident-resolution-save", function () {
    if (!currentIncident || !incidentCanRespond(currentIncident)) { return; }
    mutateIncident("PATCH", "", {
        row_version: currentIncident.row_version,
        root_cause: String($("#incident-root-cause").val() || ""),
        resolution_summary: String($("#incident-resolution-summary").val() || "")
    });
});
$(document).on("click", "#incident-comment-add", function () {
    const body = String($("#incident-comment-input").val() || "").trim();
    if (!body) { return; }
    const input = $("#incident-comment-input");
    const submit = $("#incident-comment-add");
    if (submit.prop("disabled")) { return; }
    submit.prop("disabled", true);
    const id = Number(currentIncident && currentIncident.id);
    apiPost("/api/incidents/" + encodeURIComponent(id) + "/comments", {body: body}, function () {
        submit.prop("disabled", false);
        if (!currentIncident || Number(currentIncident.id) !== id) { return; }
        if (String(input.val() || "").trim() === body) { input.val(""); }
        refreshCurrentIncident();
    }, function (xhr) {
        submit.prop("disabled", false);
        if (currentIncident && Number(currentIncident.id) === id) { showIncidentDetailsError(xhr); }
    });
});

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

function initIncidentAlertGroupLinkPicker() {
    const element = document.getElementById("incident-link-alert-group-id");
    if (!element || typeof window.TomSelect === "undefined") {
        return null;
    }
    if (element.tomselect) {
        return element.tomselect;
    }

    return new TomSelect(element, {
        create: false,
        allowEmptyOption: false,
        valueField: "id",
        labelField: "label",
        searchField: ["label"], // Never show unrelated cached results.
        maxItems: 1,
        maxOptions: 40,
        loadThrottle: 250,
        placeholder: i18n.t("incidents.links.search_alert_group"),
        shouldLoad: function (query) {
            const text = String(query || "").trim();
            return text.length >= 2 || /^#?\d+$/.test(text);
        },
        onType: function () {
            // Tom Select caches remote results, which otherwise stay in the
            // dropdown after a different search query is entered.
            this.clearOptions();
            this.loadedSearches = {};
        },
        render: {
            no_results: function () {
                return '<div class="no-results">'
                    + escapeIncidentAlertGroupPickerText(i18n.t("incidents.links.no_matches"))
                    + '</div>';
            },
            not_loading: function () {
                return '<div class="no-results">'
                    + escapeIncidentAlertGroupPickerText(i18n.t("incidents.links.type_to_search"))
                    + '</div>';
            },
        },
        load: function (query, callback) {
            const incident = currentIncident;
            if (!incident || !incident.team_id) {
                callback([]);
                return;
            }
            const incidentId = Number(incident.id);
            const search = String(query || "").trim();
            const exactIdSearch = /^#?\d+$/.test(search);
            const params = new URLSearchParams({
                team_id: String(incident.team_id),
                page: "1",
                page_size: "40",
                search: search.replace(/^#(?=\d+$)/, ""),
            });
            const picker = this;
            // A numeric ID is an exact lookup. List search can match many
            // unrelated payload fields before reaching a particular ID.
            const url = exactIdSearch
                ? "/api/alert-groups/" + encodeURIComponent(search.replace(/^#/, ""))
                    + "?events_page=1&events_page_size=1"
                : "/api/alert-groups?" + params.toString();
            $.getJSON(url)
                .done(function (response) {
                    if (!currentIncident || Number(currentIncident.id) !== incidentId
                        || String(picker.control_input.value || "").trim() !== search) {
                        callback([]);
                        return;
                    }
                    const linked = new Set(currentIncidentLinks.map(function (item) {
                        return Number(item.alert_group_id);
                    }));
                    const queryText = search.replace(/^#/, "").toLocaleLowerCase();
                    const candidates = exactIdSearch ? [response] : incidentAsArray(response);
                    const options = candidates.filter(function (group) {
                        return Number(group.team_id) === Number(incident.team_id)
                            && !linked.has(Number(group.id))
                            && !group.merged_into_id;
                    }).map(function (group) {
                        const label = "#" + group.id + " · " + (group.title || "-")
                            + " · " + (group.status || "-")
                            + " · " + (group.service_name || group.service_slug || "-");
                        return {id: String(group.id), label: label};
                    }).filter(function (option) {
                        // Backend search also matches payload/labels which are
                        // not shown here; visible matches are less confusing.
                        return exactIdSearch
                            ? option.id === queryText
                            : option.label.toLocaleLowerCase().includes(queryText);
                    });
                    callback(options);
                })
                .fail(function () { callback([]); });
        },
    });
}

function escapeIncidentAlertGroupPickerText(value) {
    return String(value || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
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
            const picker = document.getElementById("incident-link-alert-group-id");
            if (picker && picker.tomselect) {
                picker.tomselect.clear(true);
                picker.tomselect.clearOptions();
                picker.tomselect.loadedSearches = {};
            } else {
                $("#incident-link-alert-group-id").val("");
            }
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
$(document).on("input", "#incidents-search", function () {
    clearTimeout(incidentsSearchTimer);
    incidentsSearchTimer = setTimeout(function () {
        incidentsCurrentPage = 1;
        loadIncidents();
    }, 250);
});
$(document).on("change", "#incidents-status-filter", function () { incidentsCurrentPage = 1; loadIncidents(); });
$(document).on("change", "#incidents-page-size", function () {
    incidentsPageSize = parseInt($(this).val(), 10) || 25;
    incidentsCurrentPage = 1;
    loadIncidents();
});
$(document).on("click", "#incidents-prev-page", function () { if (incidentsCurrentPage > 1) { incidentsCurrentPage -= 1; loadIncidents(); } });
$(document).on("click", "#incidents-next-page", function () { if (incidentsCurrentPage < Number(incidentsPagination.pages || 0)) { incidentsCurrentPage += 1; loadIncidents(); } });

$(document).on("click", "#open-incident-create-modal", openIncidentCreateModal);
$(document).on("click", "#close-incident-create-modal, #cancel-incident-create", function () { closeAppModal("#incident-create-modal"); });
$(document).on("change", "#incident-create-team", function () {
    loadIncidentTeamOptions(Number($(this).val() || 0), "#incident-create-service", "#incident-create-assignee");
});
$(document).on("click", "#save-incident-create", saveIncidentCreate);

$(document).on("click", "#close-incident-details, #close-incident-details-footer", function () { closeIncidentDetails(); });
// The Incident workspace is a page, not a dismissible modal overlay.

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
