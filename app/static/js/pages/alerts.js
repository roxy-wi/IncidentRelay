let currentDetailsAlertId = null;
let currentDetailsAlertCanRespond = false;
let currentDetailsActiveTab = "summary";
let currentDetailsExplainLoadedAlertId = null;
let currentDetailsExplainTraceId = null;
let alertsCache = [];
let alertsAutoRefreshTimer = null;
let alertsLastAppliedQueryString = null;
let alertsCurrentPage = 1;
let alertsPageSize = 25;
let alertsSortState = createTableSortState("activity", "desc");
let alertsServiceFilterApplying = false;
let alertsServiceFilterLoaded = false;
let alertsServiceFilterTeamKey = null;
const ALERTS_QUERY_STORAGE_KEY = "incidentrelay.alerts.query";
let selectedAlertGroupIds = new Set();
let manualIncidentTeams = [];
let manualIncidentPermissionsLoaded = false;
let manualIncidentPriorities = [];
let manualIncidentServices = [];
let alertsPagination = {
    page: 1,
    page_size: 25,
    total_items: 0,
    total_pages: 1,
    from: 0,
    to: 0,
    has_prev: false,
    has_next: false,
};
let alertsSummary = {
    firing: 0,
    acknowledged: 0,
    resolved: 0,
    silenced: 0,
    reminders: 0,
    total: 0,
};

const alertsSortColumns = {
    status: { type: "rank", defaultDirection: "asc" },
    id: { path: "id", type: "number", defaultDirection: "desc" },
    title: { path: "title", type: "text", defaultDirection: "asc" },
    severity: { type: "rank", defaultDirection: "desc" },
    priority: {
        value: function (alert) {
            return alertPriorityOrder(alert);
        },
        type: "number",
        defaultDirection: "asc",
    },
    team: {
        value: function (alert) { return alert.team_slug || ""; },
        type: "text",
        defaultDirection: "asc",
    },
    assignee: {
        value: function (alert) { return alert.assignee || ""; },
        type: "text",
        defaultDirection: "asc",
    },
    created: {
        value: function (alert) { return alertCreatedValue(alert); },
        type: "datetime",
        defaultDirection: "desc",
    },
    last_seen: { path: "last_seen_at", type: "datetime", defaultDirection: "desc" },
    reminders: { path: "reminder_count", type: "number", defaultDirection: "desc" },
    activity: {
        value: function (alert) { return alertActivityValue(alert); },
        type: "datetime",
        defaultDirection: "desc",
    },
};
function isAlertGroup(alert) {
    return alert && alert.type === "alert_group";
}

function alertGroupCountLabel(alert) {
    const total = Number(alert.alert_count || 0);
    const firing = Number(alert.firing_count || 0);
    const resolved = Number(alert.resolved_count || 0);
    const silenced = Number(alert.silenced_count || 0);

    if (!isAlertGroup(alert)) {
        return "";
    }

    const parts = [];

    parts.push(total + " total");

    if (firing) {
        parts.push(firing + " firing");
    }

    if (resolved) {
        parts.push(resolved + " resolved");
    }

    if (silenced) {
        parts.push(silenced + " silenced");
    }

    return parts.join(" / ");
}

function alertGroupTargetIdFromSelection() {
    const selected = alertsCache
        .filter(function (item) {
            return selectedAlertGroupIds.has(Number(item.id));
        })
        .sort(function (left, right) {
            const leftDate = new Date(left.first_seen_at || left.created_at || 0).getTime();
            const rightDate = new Date(right.first_seen_at || right.created_at || 0).getTime();

            if (leftDate !== rightDate) {
                return leftDate - rightDate;
            }

            return Number(left.id || 0) - Number(right.id || 0);
        });

    return selected.length ? Number(selected[0].id) : null;
}

function selectedAlertGroups() {
    return alertsCache.filter(function (item) {
        return selectedAlertGroupIds.has(Number(item.id));
    });
}


function selectedAlertGroupsForBulkAction(action) {
    return selectedAlertGroups().filter(function (alert) {
        const status = normalizeAlertValue(alert.status);

        if (!canRespondObject(alert) || !isAlertGroup(alert)) {
            return false;
        }

        if (action === "ack") {
            return status === "firing";
        }

        if (action === "resolve") {
            return status !== "resolved" && status !== "merged";
        }

        return false;
    });
}

function ensureAlertsBulkActionsBar() {
    let bar = $("#alerts-bulk-actions");

    if (bar.length) {
        return bar;
    }

    bar = $("<div>")
        .attr("id", "alerts-bulk-actions")
        .addClass("alerts-bulk-actions")
        .hide()
        .append(
            $("<span>")
                .attr("id", "alerts-bulk-selected-count")
                .addClass("alerts-bulk-selected-count")
                .text("0 selected")
        )
        .append(
            $("<button>")
                .attr("type", "button")
                .attr("id", "alerts-ack-selected")
                .addClass("btn btn-warning btn-small")
                .text("Ack selected")
        )
        .append(
            $("<button>")
                .attr("type", "button")
                .attr("id", "alerts-resolve-selected")
                .addClass("btn btn-resolve btn-small")
                .text("Resolve selected")
        )
        .append(
            $("<button>")
                .attr("type", "button")
                .attr("id", "alerts-merge-selected")
                .addClass("btn btn-small")
                .text("Merge selected")
        )
        .append(
            $("<button>")
                .attr("type", "button")
                .attr("id", "alerts-clear-selection")
                .addClass("btn btn-secondary btn-small")
                .text("Clear")
        );

    $("#alerts-table-view").before(bar);

    return bar;
}

function renderAlertsBulkActions() {
    const bar = ensureAlertsBulkActionsBar();
    const count = selectedAlertGroupIds.size;
    const ackCount = selectedAlertGroupsForBulkAction("ack").length;
    const resolveCount = selectedAlertGroupsForBulkAction("resolve").length;

    bar.toggle(count > 0);
    bar.find("#alerts-bulk-selected-count").text(count + " selected");
    bar.find("#alerts-ack-selected")
        .prop("disabled", ackCount < 1)
        .text(ackCount > 0 ? "Ack selected (" + ackCount + ")" : "Ack selected");
    bar.find("#alerts-resolve-selected")
        .prop("disabled", resolveCount < 1)
        .text(resolveCount > 0 ? "Resolve selected (" + resolveCount + ")" : "Resolve selected");
    bar.find("#alerts-merge-selected").prop("disabled", count < 2);
}

function clearAlertGroupSelection() {
    selectedAlertGroupIds.clear();
    renderAlertsTable(alertsCache);
    renderAlertsBulkActions();
}
function initAlertsTableSorting() {
    bindSortableTableHeaders(
        "#alerts-table-view",
        alertsSortState,
        alertsSortColumns,
        function () {
            resetAlertsPagination();
            writeAlertsQueryParams();
            loadAlerts();
        }
    );
}

function normalizeAlertValue(value) {
    return String(value || "").toLowerCase();
}

function alertCreatedValue(alert) {
    return alert.first_seen_at || alert.created_at || null;
}

function alertActivityValue(alert) {
    return alert.last_seen_at || alert.updated_at || alert.created_at || alert.first_seen_at || null;
}

function getAlertIdFromPath(pathname) {
    const match = String(pathname || "").match(/^\/alerts\/(\d+)\/?$/);
    if (!match) {
        return null;
    }
    return Number(match[1]);
}

function buildAlertDetailsUrl(alertId) {
    const query = window.location.search || buildAlertsQueryString();

    return "/alerts/" + encodeURIComponent(alertId) + query;
}
function buildAlertListUrl() {
    const query = (
        normalizeAlertsQueryString(window.location.search || "") ||
        readStoredAlertsQueryString() ||
        buildAlertsQueryString()
    );

    return "/alerts" + query;
}

function isAlertBoolQueryParamEnabled(params, name) {
    return ["1", "true", "yes", "on"].indexOf(
        String(params.get(name) || "").toLowerCase()
    ) !== -1;
}
function normalizeAlertsQueryString(queryString) {
    queryString = String(queryString || "");

    if (!queryString) {
        return "";
    }

    return queryString.charAt(0) === "?"
        ? queryString
        : "?" + queryString;
}

function readStoredAlertsQueryString() {
    try {
        return normalizeAlertsQueryString(
            sessionStorage.getItem(ALERTS_QUERY_STORAGE_KEY) || ""
        );
    } catch (error) {
        return "";
    }
}

function storeAlertsQueryString(queryString) {
    queryString = normalizeAlertsQueryString(queryString);

    try {
        if (queryString) {
            sessionStorage.setItem(ALERTS_QUERY_STORAGE_KEY, queryString);
        } else {
            sessionStorage.removeItem(ALERTS_QUERY_STORAGE_KEY);
        }
    } catch (error) {
        // Ignore storage errors, for example private mode restrictions.
    }
}

function getAlertsQueryStringForApply() {
    let queryString = normalizeAlertsQueryString(window.location.search || "");

    if (queryString) {
        return queryString;
    }

    if (getAlertIdFromPath(window.location.pathname)) {
        return "";
    }

    queryString = readStoredAlertsQueryString();

    if (
        queryString &&
        window.location.pathname === "/alerts"
    ) {
        history.replaceState(
            Object.assign({}, history.state || {}, {
                path: window.location.pathname + queryString,
                alerts_state: true
            }),
            "",
            window.location.pathname + queryString
        );
    }

    return queryString;
}

function buildAlertsStateParams() {
    const params = new URLSearchParams();

    appendTableFilterParams(params, "status", getTableFilterValues("#status-filter"));
    appendTableFilterParams(params, "severity", getTableFilterValues("#severity-filter"));
    appendTableFilterParams(params, "priority", getTableFilterValues("#priority-filter"));
    appendTableFilterParams(params, "service_id", getTableFilterValues("#alerts-service-filter"));

    const search = String($("#alerts-search").val() || "").trim();

    if (search) {
        params.set("search", search);
    }

    if ($("#assigned-to-me-filter").is(":checked")) {
        params.set("assigned_to_me", "1");
    }

    params.set("page", String(alertsCurrentPage || 1));
    params.set("page_size", String(alertsPageSize || 25));
    params.set("sort", alertsSortState.column || "activity");
    params.set("order", alertsSortState.direction || "desc");

    return params;
}


function buildAlertsQueryString() {
    const query = buildAlertsStateParams().toString();

    return query ? "?" + query : "";
}


function buildAlertsApiUrl() {
    const params = buildAlertsStateParams();

    if (typeof selectedTeamId === "function" && selectedTeamId()) {
        params.set("team_id", selectedTeamId());
    }

    const query = params.toString();

    return "/api/alerts" + (query ? "?" + query : "");
}


function writeAlertsQueryParams() {
    const queryString = buildAlertsQueryString();
    const nextUrl = window.location.pathname + queryString;

    history.replaceState(
        Object.assign({}, history.state || {}, {
            path: nextUrl,
            alerts_state: true
        }),
        "",
        nextUrl
    );

    alertsLastAppliedQueryString = window.location.search || "";

    if (
        window.location.pathname === "/alerts" ||
        getAlertIdFromPath(window.location.pathname)
    ) {
        storeAlertsQueryString(queryString);
    }
}

function openAlertDetailsPage(alertId) {
    writeAlertsQueryParams();

    const url = buildAlertDetailsUrl(alertId);

    history.pushState(
        {
            path: url,
            alert_id: alertId,
            alerts_state: true
        },
        "",
        url
    );

    showAlertDetails(alertId);
}

function syncAlertDetailsFromUrl() {
    const alertId = getAlertIdFromPath(window.location.pathname);
    if (!alertId) {
        if (alertDetailsModal().hasClass("is-open")) {
            closeAlertDetailsModal({ updateUrl: false });
        }
        return;
    }
    if (currentDetailsAlertId === alertId && alertDetailsModal().hasClass("is-open")) {
        return;
    }
    showAlertDetails(alertId);
}

function alertDuration(alert) {
    const startedRaw = alertCreatedValue(alert);
    if (!startedRaw) {
        return "-";
    }

    const started = new Date(startedRaw);
    if (Number.isNaN(started.getTime())) {
        return "-";
    }

    let seconds = Math.max(0, Math.floor((Date.now() - started.getTime()) / 1000));
    const days = Math.floor(seconds / 86400);
    seconds -= days * 86400;
    const hours = Math.floor(seconds / 3600);
    seconds -= hours * 3600;
    const minutes = Math.floor(seconds / 60);

    if (days > 0) {
        return days + "d " + hours + "h";
    }
    if (hours > 0) {
        return hours + "h " + minutes + "m";
    }
    return Math.max(minutes, 1) + "m";
}

function severityLabel(severity) {
    const value = normalizeAlertValue(severity);
    if (value === "critical") {
        return "Critical";
    }
    if (value === "high") {
        return "High";
    }
    if (value === "medium") {
        return "Medium";
    }
    if (value === "low") {
        return "Low";
    }
    return severity || "-";
}
function alertPrioritySlug(alert) {
    if (!alert) {
        return "p3";
    }

    if (alert.priority && alert.priority.slug) {
        return normalizeAlertValue(alert.priority.slug);
    }

    return normalizeAlertValue(alert.priority_slug || "p3");
}


function alertPriorityLabel(alert) {
    const slug = alertPrioritySlug(alert);
    const priority = alert && alert.priority ? alert.priority : null;

    if (priority && priority.name) {
        return slug.toUpperCase() + " " + priority.name;
    }

    if (slug === "p1") {
        return "P1 Critical";
    }
    if (slug === "p2") {
        return "P2 High";
    }
    if (slug === "p3") {
        return "P3 Medium";
    }
    if (slug === "p4") {
        return "P4 Low";
    }
    if (slug === "p5") {
        return "P5 Informational";
    }

    return slug ? slug.toUpperCase() : "P3 Medium";
}


function alertPriorityShortLabel(alert) {
    return alertPrioritySlug(alert).toUpperCase();
}


function alertPriorityOrder(alert) {
    if (alert && alert.priority && alert.priority.level) {
        return Number(alert.priority.level) || 3;
    }

    if (alert && alert.priority_order) {
        return Number(alert.priority_order) || 3;
    }

    const slug = alertPrioritySlug(alert);
    const match = slug.match(/^p([1-5])$/);

    return match ? Number(match[1]) : 3;
}


function priorityBadgeClass(alert) {
    const slug = alertPrioritySlug(alert);

    if (slug === "p1") {
        return "ui-pill-critical";
    }
    if (slug === "p2") {
        return "ui-pill-high";
    }
    if (slug === "p3") {
        return "ui-pill-medium";
    }
    if (slug === "p4") {
        return "ui-pill-low";
    }
    if (slug === "p5") {
        return "ui-pill-info";
    }

    return "ui-pill-muted";
}


function priorityFilterLabel(priority) {
    const slug = normalizeAlertValue(priority);

    if (slug === "p1") {
        return "P1 Critical";
    }
    if (slug === "p2") {
        return "P2 High";
    }
    if (slug === "p3") {
        return "P3 Medium";
    }
    if (slug === "p4") {
        return "P4 Low";
    }
    if (slug === "p5") {
        return "P5 Informational";
    }

    return priority || "-";
}


function statusLabel(status) {
    const value = normalizeAlertValue(status);
    if (value === "firing") {
        return "Firing";
    }
    if (value === "acknowledged") {
        return "Acknowledged";
    }
    if (value === "resolved") {
        return "Resolved";
    }
    if (value === "silenced") {
        return "Silenced";
    }
    return status || "-";
}

function severityBadgeClass(severity) {
    const value = normalizeAlertValue(severity);
    if (value === "critical") {
        return "ui-pill-critical";
    }
    if (value === "high") {
        return "ui-pill-high";
    }
    if (value === "warning" || value === "medium") {
        return "ui-pill-medium";
    }
    if (value === "low") {
        return "ui-pill-low";
    }
    if (value === "info") {
        return "ui-pill-info";
    }
    return "ui-pill-muted";
}

function statusBadgeClass(status) {
    const value = normalizeAlertValue(status);
    if (value === "firing") {
        return "ui-pill-firing";
    }
    if (value === "acknowledged") {
        return "ui-pill-acknowledged";
    }
    if (value === "resolved") {
        return "ui-pill-resolved";
    }
    if (value === "silenced") {
        return "ui-pill-silenced";
    }
    return "ui-pill-muted";
}

function makeAlertBadge(text, cssClass) {
    return makeUiPill(text, cssClass);
}

function alertCorrelationSummary(alert) {
    return alert && alert.correlation_summary
        ? alert.correlation_summary
        : {
            total: 0,
            root_candidates: 0,
            downstream_impacts: 0,
            best_score: 0,
            roles: [],
            has_correlation: false
        };
}


function renderAlertCorrelationBadges(alert) {
    const summary = alertCorrelationSummary(alert);
    const wrapper = $("<div>").addClass("alert-correlation-badges");

    if (!summary.has_correlation) {
        return wrapper;
    }

    if (Number(summary.root_candidates || 0) > 0) {
        wrapper.append(
            makeAlertBadge(
                "Symptom",
                "ui-pill-medium"
            ).attr(
                "title",
                "This alert has possible upstream root cause alerts"
            )
        );
    }

    if (Number(summary.downstream_impacts || 0) > 0) {
        wrapper.append(
            makeAlertBadge(
                "Root cause",
                "ui-pill-critical"
            ).attr(
                "title",
                "This alert may impact downstream alerts"
            )
        );
    }

    wrapper.append(
        makeAlertBadge(
            "Correlated " + Number(summary.total || 0),
            "ui-pill-info"
        ).attr(
            "title",
            "Best correlation score: " + Number(summary.best_score || 0)
        )
    );

    return wrapper;
}

function loadAlerts() {
    applyAlertsQueryParams();
    initAlertsTableSorting();

    loadAlertServiceFilter(function () {
        apiGet(buildAlertsApiUrl(), function (response) {
            alertsCache = alertsResponseItems(response);
            alertsPagination = alertsResponsePagination(response);
            alertsSummary = alertsResponseSummary(response);

            alertsCurrentPage = alertsPagination.page || alertsCurrentPage || 1;
            alertsPageSize = alertsPagination.page_size || alertsPageSize || 25;

            renderAlertsPage();
            writeAlertsQueryParams();
            updateSortableTableHeaders("#alerts-table-view", alertsSortState);
        });
    });
}

function renderAlertsPage() {
    renderAlertsSummaryGrid(
        "#alerts-alerts-summary",
        alertsSummary
    );

    renderActiveAlertFilters(alertsPagination);
    renderAlertsTable(alertsCache);
    renderAlertsPagination(alertsPagination);

    // Pagination renderer may recreate elements using
    // the same "alerts" prefix, so update the counter last.
    renderAlertsInboxCounter(alertsPagination);

    syncAlertDetailsFromUrl();
    renderAlertsBulkActions();
    renderManualIncidentCreateButton();
}

function renderAlertsPagination(pagination) {
    pagination = pagination || {};

    renderTablePaginationControls({
        id: "alerts-pagination",
        prefix: "alerts",
        tableSelector: "#alerts-table-view",
        pagination: pagination,
        pageSize: alertsPageSize,
        rowsLabel: "Rows per page",
        pageSizeOptions: [10, 25, 50, 100],
        alwaysVisible: true,
    });
}

function resetAlertsPagination() {
    alertsCurrentPage = 1;
}

function renderActiveAlertFilters() {
    const chips = [];
    const search = String($("#alerts-search").val() || "").trim();
    const statuses = getTableFilterValues("#status-filter");
    const severities = getTableFilterValues("#severity-filter");
    const priorities = getTableFilterValues("#priority-filter");
    const serviceIds = getTableFilterValues("#alerts-service-filter");
    const assignedToMe = $("#assigned-to-me-filter").is(":checked");

    if (search) {
        chips.push({label: "Search", value: search});
    }

    if (statuses.length) {
        chips.push({
            label: "Status",
            value: statuses
                .map(function (status) {
                    return statusLabel(status);
                })
                .join(", ")
        });
    }

    if (severities.length) {
        chips.push({
            label: "Severity",
            value: severities
                .map(function (severity) {
                    return severityLabel(severity);
                })
                .join(", ")
        });
    }

    if (priorities.length) {
        chips.push({
            label: "Priority",
            value: priorities
                .map(function (priority) {
                    return priorityFilterLabel(priority);
                })
                .join(", ")
        });
    }

    if (serviceIds.length) {
        chips.push({
            label: "Service",
            value: serviceIds
                .map(function (serviceId) {
                    return tableSelectOptionLabel("#alerts-service-filter", serviceId);
                })
                .join(", ")
        });
    }
    if (assignedToMe) {
        chips.push({
            label: "Assignee",
            value: "Me"
        });
    }

    if (typeof selectedTeamId === "function" && selectedTeamId()) {
        chips.push({label: "Team", value: getSelectedTeamLabel()});
    }

    renderTableFilterChips("#alerts-active-filters", chips);
    $("#alerts-active-filters").toggle(chips.length > 0);
}
function getSelectedTeamLabel() {
    const teamId = typeof selectedTeamId === "function"
        ? selectedTeamId()
        : null;

    if (!teamId) {
        return "-";
    }

    const teamSelect = $("#global-team-filter").filter(function () {
        return $(this).length && $(this).find("option").length;
    }).first();

    if (teamSelect.length) {
        const option = teamSelect.find("option").filter(function () {
            return String($(this).val()) === String(teamId);
        }).first();

        if (option.length && option.text()) {
            return option.text();
        }
    }

    return String(teamId);
}
function renderAlertsTable(alerts) {
    const tbody = $("#alerts-table");
    tbody.empty();

    if (!alerts.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>").attr("colspan", "10").addClass("empty-table-cell").text("No alerts found")
            )
        );
        return;
    }

    alerts.forEach(function (alert) {
        tbody.append(renderAlertPageRow(alert));
    });
}

function renderAlertPageRow(alert) {
    const row = $("<tr>").addClass("alerts-row alerts-row-" + normalizeAlertValue(alert.status));

    const canRespond = canRespondObject(alert);
    const isMerged = normalizeAlertValue(alert.status) === "merged";
    const selectable = isAlertGroup(alert) && canRespond && !isMerged;

    const idCell = $("<td>");

    const idContent = $("<span>").addClass("alerts-id-content");

    if (selectable) {
        idContent.append(
            $("<input>")
                .attr("type", "checkbox")
                .addClass("alerts-group-select")
                .attr("data-alert-group-id", alert.id)
                .prop("checked", selectedAlertGroupIds.has(Number(alert.id)))
                .on("click", function (event) {
                    event.stopPropagation();
                })
                .on("change", function () {
                    const id = Number($(this).attr("data-alert-group-id"));

                    if ($(this).is(":checked")) {
                        selectedAlertGroupIds.add(id);
                    } else {
                        selectedAlertGroupIds.delete(id);
                    }

                    renderAlertsBulkActions();
                })
        );
    }

    idContent.append(
        $("<a>")
            .attr("href", buildAlertDetailsUrl(alert.id))
            .attr("title", "View alert group details")
            .addClass("alerts-id-link")
            .text("#" + alert.id)
            .on("click", function (event) {
                event.preventDefault();
                openAlertDetailsPage(alert.id);
            })
    );

    idCell.append(idContent);
    row.append(idCell);

    row.append(
        window.AppMaintenanceBadges.statusCell(
            [
                $("<span>").addClass("status-dot dot-" + normalizeAlertValue(alert.status)),
                makeAlertBadge(statusLabel(alert.status), statusBadgeClass(alert.status)),
            ],
            alert
        )
    );

    row.append(
        $("<td>")
            .addClass("alert-title-cell")
            .append($("<div>").addClass("table-title").text(alert.title || "-"))
            .append(
                $("<div>").addClass("table-subtitle").text(buildAlertSubtitle(alert))
            )
            .append(
                $("<div>")
                    .addClass("table-subtitle")
                    .text(alertGroupCountLabel(alert))
                    .toggle(isAlertGroup(alert))
            )
            .append(renderAlertCorrelationBadges(alert))
            .append($("<div>").addClass("table-age").text("Age: " + alertDuration(alert)))
    );

    row.append(
        $("<td>").append(
            makeAlertBadge(severityLabel(alert.severity), severityBadgeClass(alert.severity))
        )
    );
    row.append(
        $("<td>").append(
            makeAlertBadge(alertPriorityShortLabel(alert), priorityBadgeClass(alert))
                .attr("title", alertPriorityLabel(alert))
        )
    );

    row.append(
        $("<td>")
            .append($("<div>").addClass("alerts-team").text(alert.team_name || alert.team_slug || "-"))
            .append($("<div>").addClass("table-subtitle").text(alert.route_name || "No route"))
            .append(
                $("<div>")
                    .addClass("table-subtitle")
                    .text(alert.service_id ? "Service: " + alertServiceLabel(alert) : "No service")
            )
    );

    row.append($("<td>").text(alert.assignee || "-"));
    row.append($("<td>").text(formatDateTimeMinutes(alertCreatedValue(alert))));
    row.append($("<td>").text(formatDateTimeMinutes(alert.last_seen_at)));
    row.append($("<td>").append(renderEscalationCell(alert)));

    return row;
}

function buildAlertSubtitle(alert) {
    const parts = [];

    if (isAlertGroup(alert)) {
        parts.push("Group");
    }

    if (alert.source) {
        parts.push(alert.source);
    }

    if (alert.group_key) {
        parts.push(alert.group_key);
    }

    return parts.length ? parts.join(" · ") : "Routed alert";
}

function alertServiceLabel(alert) {
    if (!alert.service_id) {
        return "No service";
    }

    return alert.service_name || alert.service_slug || ("Service #" + alert.service_id);
}


function alertServiceDetailsLabel(alert) {
    if (!alert.service_id) {
        return "-";
    }

    const parts = [];

    parts.push(alertServiceLabel(alert));

    if (alert.service_criticality) {
        parts.push(alert.service_criticality);
    }

    if (alert.service_status) {
        parts.push(alert.service_status);
    }

    return parts.join(" / ");
}
// function renderReminderCount(alert) {
//     const count = alert.reminder_count || 0;
//     return $("<span>")
//         .addClass("counter-badge")
//         .toggleClass("is-active", count > 0)
//         .text(count);
// }
function renderEscalationModeBadge(alert) {
    const isPolicy = !!alert.escalation_policy_name;
    const label = isPolicy ? "Policy" : "Rotation";

    return $("<span>")
        .addClass("pill")
        .addClass(isPolicy ? "alerts-badge-info" : "badge-muted")
        .attr("title", isPolicy
            ? "Escalation policy: " + alert.escalation_policy_name
            : "Simple rotation escalation")
        .text(label);
}
function renderEscalationCell(alert) {
    const wrapper = $("<div>").addClass("alerts-escalation-cell");

    wrapper.append(renderEscalationModeBadge(alert));

    if (alert.escalation_policy_name) {
        wrapper.append(
            $("<div>")
                .addClass("alerts-subtitle")
                .text(alert.escalation_policy_name)
        );

        if (alert.escalation_rule_position) {
            wrapper.append(
                $("<div>")
                    .addClass("alerts-subtitle")
                    .text(
                        "Rule #" + alert.escalation_rule_position +
                        " / " + (alert.escalation_rule_target_type || "-")
                    )
            );
        }

        if (alert.next_escalation_at) {
            wrapper.append(
                $("<div>")
                    .addClass("alerts-age")
                    .text("Next: " + formatDateTimeMinutes(alert.next_escalation_at))
            );
        }

        return wrapper;
    }

    wrapper.append(
        $("<div>")
            .addClass("alerts-subtitle")
            .text("Level: " + (alert.escalation_level || 0))
    );

    if (alert.team_escalation_enabled) {
        wrapper.append(
            $("<div>")
                .addClass("alerts-age")
                .text("After " + (alert.team_escalation_after_reminders || 0) + " reminders")
        );
    }

    return wrapper;
}
function alertEscalationModeLabel(alert) {
    if (alert.escalation_policy_name) {
        return "Policy";
    }

    return "Simple rotation";
}

function alertPolicyRuleLabel(alert) {
    if (!alert.escalation_rule_position) {
        return "-";
    }

    const targetType = alert.escalation_rule_target_type || "-";

    return "#" + alert.escalation_rule_position + " / " + targetType;
}
function alertTeamEscalationLabel(alert) {
    if (alert.escalation_policy_name) {
        return "Used only when escalation mode is Rotation";
    }

    if (alert.team_escalation_enabled) {
        return "After " + (alert.team_escalation_after_reminders || 0) + " reminders";
    }

    return "Disabled";
}

function setAlertDetailsTab(tabName) {
    tabName = tabName || "summary";
    currentDetailsActiveTab = tabName;

    const modal = alertDetailsModal();

    modal.find("[data-alert-details-tab]").each(function () {
        const button = $(this);
        const isActive = button.data("alert-details-tab") === tabName;

        button
            .toggleClass("is-active", isActive)
            .toggleClass("active", isActive)
            .attr("aria-selected", isActive ? "true" : "false");
    });

    modal.find("[data-alert-details-panel]").each(function () {
        const panel = $(this);
        const isActive = panel.data("alert-details-panel") === tabName;

        panel
            .toggleClass("is-active", isActive)
            .toggleClass("active", isActive)
            .prop("hidden", !isActive);
    });

    if (tabName === "explain") {
        loadAlertExplainForCurrentDetails();
    }
}

function resetAlertDetailsTabs(alertId) {
    currentDetailsActiveTab = "summary";
    currentDetailsExplainLoadedAlertId = null;
    currentDetailsExplainTraceId = null;

    renderAlertExplainEmpty("Open the Explain tab to load routing trace.");
    setAlertDetailsTab("summary");
}

function renderAlertExplainEmpty(message) {
    const modal = alertDetailsModal();

    modal.find("#alert-explain-summary")
        .empty()
        .append(
            $("<div>")
                .addClass("help-text")
                .text(message || "No explain trace.")
        );

    modal.find("#alert-explain-steps").empty();
}

function renderAlertExplainLoading(message) {
    renderAlertExplainEmpty(message || "Loading explain trace...");
}

function alertExplainStatusBadge(status) {
    const normalized = normalizeAlertValue(status);

    if (normalized === "success" || normalized === "completed") {
        return makeUiPill(status || "success", "ui-pill-resolved");
    }

    if (normalized === "warning") {
        return makeUiPill(status || "warning", "ui-pill-medium");
    }

    if (normalized === "error" || normalized === "failed") {
        return makeUiPill(status || "error", "ui-pill-critical");
    }

    if (normalized === "scheduled") {
        return makeUiPill(status || "scheduled", "ui-pill-info");
    }

    if (normalized === "stopped" || normalized === "skipped") {
        return makeUiPill(status || normalized, "ui-pill-muted");
    }

    return makeUiPill(status || "info", "ui-pill-muted");
}

function renderAlertExplainSummary(trace) {
    const modal = alertDetailsModal();
    const target = modal.find("#alert-explain-summary");

    target.empty();
    target.append(detailItem("Trace", trace.trace_id));
    target.append(
        $("<div>")
            .addClass("detail-item")
            .append($("<div>").addClass("detail-label").text("Status"))
            .append(
                $("<div>")
                    .addClass("detail-value")
                    .append(alertExplainStatusBadge(trace.status))
            )
    );
    target.append(detailItem("Outcome", trace.outcome));
    target.append(detailItem("Source", trace.source));
    target.append(detailItem("Dedup key", trace.dedup_key));
    target.append(detailItem("Started", formatDateTimeMinutes(trace.started_at)));
    target.append(detailItem("Finished", formatDateTimeMinutes(trace.finished_at)));

    if (trace.reason) {
        target.append(detailItem("Reason", trace.reason));
    }
}

function renderAlertExplainSteps(steps) {
    const modal = alertDetailsModal();
    const target = modal.find("#alert-explain-steps");

    steps = asArray(steps);
    target.empty();

    if (!steps.length) {
        target.append($("<div>").addClass("help-text").text("No explain steps recorded."));
        return;
    }

    steps.forEach(function (step) {
        const item = $("<div>").addClass("event-item");
        const header = $("<div>")
            .addClass("alert-explain-step-header")
            .append(
                $("<strong>").text(
                    "#" + (step.position || "-") + " " + (step.title || step.code || "Step")
                )
            )
            .append(" ")
            .append(alertExplainStatusBadge(step.status));

        item.append(header);
        item.append(
            $("<div>")
                .addClass("table-subtitle")
                .text([
                    step.stage || null,
                    step.code || null,
                    formatDateTimeMinutes(step.created_at) || null,
                ].filter(Boolean).join(" / ") || "-")
        );

        if (step.message) {
            item.append($("<div>").text(step.message));
        }

        if (step.data && Object.keys(step.data).length) {
            item.append(
                $("<details>")
                    .addClass("alert-explain-step-data")
                    .append($("<summary>").text("Data"))
                    .append(
                        $("<pre>")
                            .addClass("details-code")
                            .text(JSON.stringify(step.data, null, 2))
                    )
            );
        }

        target.append(item);
    });
}

function pickLatestAlertExplainTrace(traces) {
    traces = asArray(traces);

    if (!traces.length) {
        return null;
    }

    return traces
        .slice()
        .sort(function (left, right) {
            return Number(right.id || 0) - Number(left.id || 0);
        })[0];
}

function loadAlertExplainTrace(traceId) {
    if (!traceId) {
        renderAlertExplainEmpty("No explain trace selected.");
        return;
    }

    renderAlertExplainLoading("Loading explain trace...");

    apiGet("/api/alerts/explain/" + encodeURIComponent(traceId), function (trace) {
        currentDetailsExplainTraceId = trace.trace_id;
        renderAlertExplainSummary(trace);
        renderAlertExplainSteps(trace.steps || []);
    });
}

function loadAlertExplainForCurrentDetails() {
    if (!currentDetailsAlertId) {
        if (currentDetailsExplainTraceId) {
            return;
        }

        renderAlertExplainEmpty("No incident selected.");
        return;
    }

    if (currentDetailsExplainLoadedAlertId === currentDetailsAlertId) {
        return;
    }

    currentDetailsExplainLoadedAlertId = currentDetailsAlertId;
    renderAlertExplainLoading("Loading explain traces...");

    apiGet("/api/alerts/" + encodeURIComponent(currentDetailsAlertId) + "/explain", function (traces) {
        const latestTrace = pickLatestAlertExplainTrace(traces);

        if (!latestTrace) {
            renderAlertExplainEmpty("No explain trace recorded for this incident.");
            return;
        }

        loadAlertExplainTrace(latestTrace.trace_id);
    });
}

function showAlertDetails(alertId) {
    currentDetailsAlertId = alertId;

    apiGet("/api/alerts/" + alertId, function (alert) {
        const modal = alertDetailsModal();

        if (!modal.length) {
            console.error("Alert details modal not found");
            return;
        }

        currentDetailsAlertId = alert.id;
        currentDetailsAlertCanRespond = canRespondObject(alert);
        resetAlertDetailsTabs(alert.id);

        modal.find("#alert-details-title").text(alert.title || "Alert #" + alert.id);
        modal.find("#alert-details-subtitle").text(buildAlertDetailsSubtitle(alert));

        renderAlertPrimaryDetails(alert, modal);
        renderAlertServiceContext(alert, modal);
        renderAlertCorrelation(alert, modal);
        renderAlertDetailsSummary(alert, modal);

        modal.find("#alert-details-labels").text(
            JSON.stringify(alert.common_labels || alert.labels || {}, null, 2)
        );

        modal.find("#alert-details-payload").text(
            JSON.stringify(alert.payload_summary || alert.payload || {}, null, 2)
        );

        renderAlertGroupChildren(alert.alerts || [], modal);
        renderEvents(alert.events || [], modal);
        renderNotifications(alert.notifications || [], modal);
        prepareAlertComments(alert, modal);

        if (window.AlertIncidentManagement) {
            window.AlertIncidentManagement.render(alert, modal, {
                onChange: loadAlerts,
            });
        }

        if (!currentDetailsAlertCanRespond || normalizeAlertValue(alert.status) === "resolved") {
            modal.find("#modal-alert-ack").hide();
            modal.find("#modal-alert-resolve").hide();
        } else {
            modal.find("#modal-alert-ack").toggle(normalizeAlertValue(alert.status) === "firing");
            modal.find("#modal-alert-resolve").show();
        }

        openAlertDetailsModal();
    });
}
function buildAlertDetailsSubtitle(alert) {
    return [
        alert.source || null,
        alert.team_slug || null,
        alert.status || null,
        alert.severity || null,
        alertPriorityShortLabel(alert)
    ].filter(Boolean).join(" / ");
}


function ensureAlertPrimaryDetails(modal) {
    let target = modal.find("#alert-primary-details");

    if (target.length) {
        return target;
    }

    target = $("<section>")
        .attr("id", "alert-primary-details")
        .addClass("alert-primary-details");

    const overview = modal.find("#alert-details-overview");

    if (overview.length) {
        overview.append(target);
    } else {
        modal.find("#alert-details-summary").before(target);
    }

    return target;
}


function renderAlertPrimaryDetails(alert, modal) {
    const target = ensureAlertPrimaryDetails(modal);
    const message = alert.message || alert.description || alert.summary || "";
    const labels = alert.labels || {};
    const eventLink = alert.event_link || (labels && labels.event_link);

    target.empty();

    const header = $("<div>").addClass("alert-primary-header");

    const primaryBadges = $("<div>")
    .addClass("badge-success")
    .append(makeAlertBadge(statusLabel(alert.status), statusBadgeClass(alert.status)))
    .append(makeAlertBadge(severityLabel(alert.severity), severityBadgeClass(alert.severity)))
    .append($("<span>").addClass("pill badge-muted").text("#" + alert.id));

    window.AppMaintenanceBadges.appendTo(primaryBadges, alert);

    header.append(primaryBadges);

    header.append(
        $("<div>")
            .addClass("alert-primary-time")
            .text(buildAlertPrimaryTimeLine(alert))
    );

    target.append(header);

    target.append(
        $("<div>")
            .addClass("alert-primary-title")
            .text(alert.title || "Alert #" + alert.id)
    );

    if (message) {
        target.append(
            $("<pre>")
                .addClass("alert-primary-message")
                .text(message)
        );
    } else {
        target.append(
            $("<div>")
                .addClass("help-text")
                .text("No alert message was provided by the integration.")
        );
    }

    if (eventLink) {
        target.append(
            $("<div>")
                .addClass("alert-primary-links")
                .append(
                    $("<a>")
                        .attr("href", eventLink)
                        .attr("target", "_blank")
                        .attr("rel", "noopener noreferrer")
                        .addClass("btn btn-secondary btn-sm")
                        .text("Open source event")
                )
        );
    }

    target.append(renderAlertPrimaryLabels(labels));

    const context = buildAlertPrimaryContext(alert);

    if (context.length) {
        const contextGrid = $("<div>").addClass("alert-primary-context");

        context.forEach(function (item) {
            contextGrid.append(
                $("<div>")
                    .addClass("alert-primary-context-item")
                    .append($("<span>").addClass("detail-label").text(item.label))
                    .append($("<span>").addClass("detail-value").text(item.value || "-"))
            );
        });

        target.append(contextGrid);
    }
}


function buildAlertPrimaryTimeLine(alert) {
    const parts = [];

    if (alert.first_seen_at || alert.created_at) {
        parts.push("Created: " + formatDateTimeMinutes(alert.first_seen_at || alert.created_at));
    }

    if (alert.last_seen_at) {
        parts.push("Last seen: " + formatDateTimeMinutes(alert.last_seen_at));
    }

    return parts.join(" · ");
}


function buildAlertPrimaryContext(alert) {
    const context = [
        {
            label: "Assignee",
            value: alert.assignee || "-"
        },
        {
            label: "Route",
            value: alert.route_name || "-"
        },
        {
            label: "Service",
            value: alertServiceDetailsLabel(alert)
        },
        {
            label: "Next escalation",
            value: formatDateTimeMinutes(alert.next_escalation_at)
        }
    ];

    if (window.AppMaintenanceBadges && window.AppMaintenanceBadges.has(alert)) {
        context.push({
            label: "Maintenance",
            value: window.AppMaintenanceBadges.text(alert)
        });
    }

    return context;
}


function renderAlertPrimaryLabels(labels) {
    const wrapper = $("<div>").addClass("alert-primary-labels");
    const preferredKeys = [
        "alertname",
        "event_name",
        "problem_name",
        "instance",
        "host",
        "hostname",
        "job",
        "service",
        "team",
        "severity"
    ];

    const rendered = new Set();

    preferredKeys.forEach(function (key) {
        if (labels[key] === undefined || labels[key] === null || labels[key] === "") {
            return;
        }

        rendered.add(key);
        wrapper.append(renderAlertLabelChip(key, labels[key]));
    });

    Object.keys(labels).sort().forEach(function (key) {
        if (rendered.has(key)) {
            return;
        }

        if (wrapper.children().length >= 12) {
            return;
        }

        wrapper.append(renderAlertLabelChip(key, labels[key]));
    });

    if (!wrapper.children().length) {
        wrapper.append(
            $("<span>")
                .addClass("help-text")
                .text("No labels.")
        );
    }

    return wrapper;
}


function renderAlertLabelChip(key, value) {
    return $("<span>")
        .addClass("alert-label-chip")
        .text(key + "=" + value);
}
function ensureAlertServiceContext(modal) {
    let target = modal.find("#alert-service-context");

    if (target.length) {
        return target;
    }

    target = $("<div>")
        .attr("id", "alert-service-context")
        .addClass("alert-service-context");

    const primary = modal.find("#alert-primary-details");
    const overview = modal.find("#alert-details-overview");

    if (primary.length) {
        primary.after(target);
    } else if (overview.length) {
        overview.append(target);
    } else {
        modal.find("#alert-details-summary").before(target);
    }

    return target;
}


function renderAlertServiceContext(alert, modal) {
    const target = ensureAlertServiceContext(modal);
    target.empty();

    if (!alert.service_id) {
        target.hide();
        return;
    }

    target.show();

    target.append(
        $("<div>")
            .addClass("alert-service-context-header")
            .append($("<h3>").text("Service context"))
            .append(
                $("<div>")
                    .addClass("card-subtitle")
                    .text(alertServiceDetailsLabel(alert))
            )
    );

    const linksList = $("<div>")
        .attr("id", "alert-service-links")
        .addClass("alert-service-context-list")
        .append($("<div>").addClass("help-text").text("Loading links..."));

    const runbooksList = $("<div>")
        .attr("id", "alert-service-runbooks")
        .addClass("alert-service-context-list")
        .append($("<div>").addClass("help-text").text("Loading runbooks..."));

    target.append(
        $("<div>")
            .addClass("alert-service-context-grid")
            .append(
                $("<section>")
                    .addClass("alert-service-context-section")
                    .append($("<h4>").text("Links"))
                    .append(linksList)
            )
            .append(
                $("<section>")
                    .addClass("alert-service-context-section")
                    .append($("<h4>").text("Runbooks"))
                    .append(runbooksList)
            )
    );

    apiGet("/api/services/" + alert.service_id + "/links", function (links) {
        renderAlertServiceLinks(asArray(links));
    });

    apiGet("/api/services/" + alert.service_id + "/runbooks", function (runbooks) {
        renderAlertServiceRunbooks(alert, asArray(runbooks));
    });
}


function renderAlertServiceLinks(links) {
    const target = $("#alert-service-links");
    target.empty();

    const enabledLinks = links.filter(function (link) {
        return !!link.enabled;
    });

    if (!enabledLinks.length) {
        target.append($("<div>").addClass("help-text").text("No links."));
        return;
    }

    enabledLinks.forEach(function (link) {
        target.append(
            $("<a>")
                .addClass("alert-service-context-link")
                .attr("href", link.url)
                .attr("target", "_blank")
                .attr("rel", "noopener noreferrer")
                .append($("<span>").addClass("alert-service-context-title").text(link.label || link.url))
                .append(
                    $("<span>")
                        .addClass("alert-service-context-meta")
                        .text(link.link_type || "other")
                )
        );
    });
}


function renderAlertServiceRunbooks(alert, runbooks) {
    const target = $("#alert-service-runbooks");
    target.empty();

    const matchedRunbooks = runbooks.filter(function (runbook) {
        return !!runbook.enabled && alertMatchesRunbook(alert, runbook);
    });

    if (!matchedRunbooks.length) {
        target.append($("<div>").addClass("help-text").text("No matching runbooks."));
        return;
    }

    matchedRunbooks.forEach(function (runbook) {
        target.append(
            $("<a>")
                .addClass("alert-service-context-link")
                .attr("href", runbook.url)
                .attr("target", "_blank")
                .attr("rel", "noopener noreferrer")
                .append($("<span>").addClass("alert-service-context-title").text(runbook.title || runbook.url))
                .append(
                    $("<span>")
                        .addClass("alert-service-context-meta")
                        .text(
                            [
                                runbook.severity ? "severity: " + runbook.severity : null,
                                runbook.description || null,
                            ].filter(Boolean).join(" / ") || "runbook"
                        )
                )
        );
    });
}


function alertMatchesRunbook(alert, runbook) {
    if (
        runbook.severity &&
        normalizeAlertValue(runbook.severity) !==
        normalizeAlertValue(alert.severity)
    ) {
        return false;
    }

    const preset = runbook.matcher_preset;

    if (preset) {
        if (!preset.enabled) {
            return false;
        }

        if (!alertMatchesSimpleMatchers(alert, preset.matchers || {})) {
            return false;
        }
    }

    return alertMatchesSimpleMatchers(alert, runbook.matchers || {});
}


function alertMatchesSimpleMatchers(alert, matchers) {
    const matcherKeys = Object.keys(matchers || {});

    if (!matcherKeys.length) {
        return true;
    }

    const labels = alert.labels || {};
    const expectedLabels = matchers.labels || {};

    for (const key in expectedLabels) {
        if (!Object.prototype.hasOwnProperty.call(expectedLabels, key)) {
            continue;
        }

        const expected = expectedLabels[key];
        const actual = labels[key];

        if (Array.isArray(expected)) {
            if (expected.map(String).indexOf(String(actual)) === -1) {
                return false;
            }
            continue;
        }

        if (String(actual) !== String(expected)) {
            return false;
        }
    }

    return true;
}

function ensureAlertCorrelationContext(modal) {
    let target = modal.find("#alert-correlation-context");

    if (target.length) {
        return target;
    }

    target = $("<section>")
        .attr("id", "alert-correlation-context")
        .addClass("card alert-correlation-context");

    const serviceContext = modal.find("#alert-service-context");
    const overview = modal.find("#alert-details-overview");

    if (serviceContext.length) {
        serviceContext.after(target);
    } else if (overview.length) {
        overview.append(target);
    } else {
        modal.find("#alert-details-summary").before(target);
    }

    return target;
}


function alertCorrelationRoleLabel(role) {
    const labels = {
        possible_symptom: "Possible symptom",
        possible_root_cause: "Possible root cause",
        related: "Related alert"
    };

    return labels[role] || role || "Related alert";
}


function alertCorrelationRelationLabel(relationType) {
    const labels = {
        possible_root_cause: "Possible root cause",
        possible_downstream_impact: "Possible downstream impact",
        same_dependency_chain: "Same dependency chain"
    };

    return labels[relationType] || relationType || "-";
}


function alertCorrelationGroupLabel(group) {
    if (!group) {
        return "-";
    }

    return [
        "#" + group.id,
        group.service_name || group.service_slug || null,
        group.title || null
    ].filter(Boolean).join(" · ");
}


function alertCorrelationGroupMeta(group) {
    if (!group) {
        return "-";
    }

    return [
        group.status || null,
        group.severity || null,
        group.priority || null,
        group.source || null,
        formatDateTimeMinutes(group.last_seen_at) || null
    ].filter(Boolean).join(" / ");
}


function buildAlertCorrelationItem(item) {
    const peer = item.peer_group || null;

    const row = $("<div>")
        .addClass("event-item alert-correlation-item");

    const title = $("<div>")
        .addClass("alert-correlation-title")
        .append(
            $("<strong>").text(alertCorrelationRoleLabel(item.role))
        )
        .append(
            $("<span>")
                .addClass("pill badge-muted")
                .text("score " + (item.score || 0))
        );

    row.append(title);

    const groupLink = $("<button>")
        .attr("type", "button")
        .addClass("btn-link")
        .text(alertCorrelationGroupLabel(peer));

    if (peer && peer.id) {
        groupLink.on("click", function () {
            showAlertDetails(peer.id);
        });
    } else {
        groupLink.prop("disabled", true);
    }

    row.append(
        $("<div>")
            .addClass("table-subtitle")
            .text(alertCorrelationGroupMeta(peer))
    );

    row.append(
        $("<div>")
            .addClass("alert-correlation-peer")
            .append(groupLink)
    );

    row.append(
        $("<div>")
            .addClass("table-subtitle")
            .text(
                [
                    alertCorrelationRelationLabel(item.relation_type),
                    item.dependency_type || null,
                    item.criticality || null,
                    item.depth ? "depth " + item.depth : null
                ].filter(Boolean).join(" / ")
            )
    );

    if (item.reason) {
        row.append(
            $("<div>")
                .addClass("help-text")
                .text(item.reason)
        );
    }

    return row;
}


function renderAlertCorrelation(alert, modal) {
    const target = ensureAlertCorrelationContext(modal);
    const correlations = alert.correlations || {};
    const rootCandidates = asArray(correlations.root_candidates);
    const downstreamImpacts = asArray(correlations.downstream_impacts);
    const total = rootCandidates.length + downstreamImpacts.length;

    target.empty();

    if (!total) {
        target.addClass("is-hidden");
        return;
    }

    target.removeClass("is-hidden");

    target.append(
        $("<div>")
            .addClass("card-header")
            .append(
                $("<div>")
                    .append($("<h2>").text("Correlation"))
                    .append(
                        $("<div>")
                            .addClass("card-subtitle")
                            .text("Dependency-aware related alert groups.")
                    )
            )
    );

    const body = $("<div>").addClass("form-body");

    if (rootCandidates.length) {
        body.append(
            $("<h3>").text("Possible root cause")
        );

        rootCandidates.forEach(function (item) {
            body.append(buildAlertCorrelationItem(item));
        });
    }

    if (downstreamImpacts.length) {
        body.append(
            $("<h3>").text("Possible downstream impact")
        );

        downstreamImpacts.forEach(function (item) {
            body.append(buildAlertCorrelationItem(item));
        });
    }

    target.append(body);
}

function renderAlertDetailsSummary(alert, modal) {
    const summary = modal.find("#alert-details-summary");

    summary.empty();

    summary.append(detailItem("Source", alert.source));
    summary.append(detailItem("External ID", alert.external_id));
    summary.append(detailItem("Group key", alert.group_key));
    summary.append(detailItem("Dedup key", alert.dedup_key));

    summary.append(detailItem("Team", alert.team_name || alert.team_slug));
    summary.append(detailItem("Route", alert.route_name));
    summary.append(detailItem("Service", alertServiceDetailsLabel(alert)));
    summary.append(detailItem("Priority", alertPriorityLabel(alert)));
    summary.append(detailItem("Service status", alert.service_status));
    summary.append(detailItem("Service criticality", alert.service_criticality));

    summary.append(detailItem("Escalation mode", alertEscalationModeLabel(alert)));
    summary.append(detailItem("Escalation policy", alert.escalation_policy_name));
    summary.append(detailItem("Policy rule", alertPolicyRuleLabel(alert)));
    summary.append(detailItem("Rotation", alert.rotation_name));
    summary.append(detailItem("Assignee", alert.assignee));
    summary.append(detailItem("Next escalation", formatDateTimeMinutes(alert.next_escalation_at)));
    summary.append(detailItem("Last escalated", formatDateTimeMinutes(alert.last_escalated_at)));
    summary.append(detailItem("Escalation level", alert.escalation_level || 0));
    summary.append(detailItem("Policy repeat count", alert.escalation_repeat_count || 0));
    summary.append(detailItem("Default rotation", alertTeamEscalationLabel(alert)));

    summary.append(detailItem("Acknowledged by", alert.acknowledged_by));
    summary.append(detailItem("Created", formatDateTimeMinutes(alert.first_seen_at || alert.created_at)));
    summary.append(detailItem("Last seen", formatDateTimeMinutes(alert.last_seen_at)));
    summary.append(detailItem("Last notification", formatDateTimeMinutes(alert.last_notification_at)));
    summary.append(detailItem("Reminder count", alert.reminder_count || 0));
    summary.append(detailItem(
        "Reminder interval",
        alert.rotation_reminder_interval_seconds
            ? alert.rotation_reminder_interval_seconds + "s"
            : "-"
    ));
}
function ensureAlertGroupChildrenSection(modal) {
    return modal.find("#alert-group-children-section");
}


function renderAlertGroupChildren(alerts, modal) {
    const section = ensureAlertGroupChildrenSection(modal);
    const target = modal.find("#alert-group-children");

    alerts = asArray(alerts);

    target.empty();
    section.prop("hidden", false);

    if (!alerts.length) {
        target.append(
            $("<div>").addClass("help-text").text("No child alerts in this group.")
        );
        return;
    }

    alerts.forEach(function (alert) {
        const labels = alert.labels || {};
        const createdAt = alert.first_seen_at || alert.created_at || null;
        const lastSeenAt = alert.last_seen_at || alert.updated_at || null;

        const subtitle = [
            alert.status || null,
            alert.severity || null,
            createdAt ? "created=" + formatDateTimeMinutes(createdAt) : null,
            lastSeenAt ? "last_seen=" + formatDateTimeMinutes(lastSeenAt) : null,
            labels.instance ? "instance=" + labels.instance : null,
            alert.dedup_key ? "dedup=" + alert.dedup_key : null,
        ].filter(Boolean).join(" · ");

        target.append(
            $("<div>")
                .addClass("alert-child-item")
                .append(
                    $("<div>")
                        .addClass("alert-child-header")
                        .append(
                            $("<span>").text("#" + alert.id + " " + (alert.title || "Alert"))
                        )
                        .append(
                            $("<span>")
                                .addClass("alert-child-status")
                                .append(makeAlertBadge(statusLabel(alert.status), statusBadgeClass(alert.status)))
                        )
                )
                .append(
                    $("<div>")
                        .addClass("table-subtitle")
                        .text(subtitle || "-")
                )
                .append(
                    $("<div>")
                        .addClass("alert-child-time-row")
                        .append(
                            $("<span>")
                                .addClass("alert-child-time-item")
                                .text("Created: " + (formatDateTimeMinutes(createdAt) || "-"))
                        )
                        .append(
                            $("<span>")
                                .addClass("alert-child-time-item")
                                .text("Last seen: " + (formatDateTimeMinutes(lastSeenAt) || "-"))
                        )
                )
                .append(
                    $("<pre>")
                        .addClass("alert-child-labels")
                        .text(JSON.stringify(labels, null, 2))
                )
        );
    });
}
function alertEventTypeLabel(eventType) {
    const labels = {
        manual_created: "Manual incident created",
        created: "Created",
        acknowledged: "Acknowledged",
        resolved: "Resolved",
        escalated: "Escalated",
        notification_sent: "Notification sent",
        notification_failed: "Notification failed",
        notification_skipped: "Notification skipped",
        priority_updated: "Priority updated",
        priority_reset: "Priority reset",
        responder_added: "Responder added",
        responder_updated: "Responder updated",
        stakeholder_added: "Stakeholder added",
        stakeholder_removed: "Stakeholder removed"
    };

    if (labels[eventType]) {
        return labels[eventType];
    }

    return String(eventType || "event")
        .replace(/_/g, " ")
        .replace(/\b\w/g, function (letter) {
            return letter.toUpperCase();
        });
}

function alertEventUserLabel(event) {
    const user = event && event.user ? event.user : null;

    if (!user) {
        return null;
    }

    return (
        user.display_name ||
        user.username ||
        user.email ||
        null
    );
}

function alertEventTypeLabel(eventType) {
    const labels = {
        correlation_detected: "Correlation detected",
        correlation_deactivated: "Correlation deactivated",
        merged: "Merged",
        merge_target_updated: "Merge target updated",
        acknowledged: "Acknowledged",
        resolved: "Resolved",
        notification: "Notification",
        reminder: "Reminder",
        escalation: "Escalation"
    };

    return labels[eventType] || eventType || "-";
}

function renderEvents(events, modal) {
    const target = modal.find("#alert-details-events");

    target.empty();

    events = asArray(events);

    if (!events.length) {
        target.append(
            $("<div>")
                .addClass("help-text")
                .text("No events.")
        );
        return;
    }

    events.forEach(function (event) {
        target.append(
            $("<div>")
                .addClass("event-item")
                .append(
                    $("<div>")
                        .addClass("event-title")
                        .text(
                            "#" + event.id + " "
                            + alertEventTypeLabel(event.event_type)
                        )
                )
                .append(
                    $("<div>")
                        .addClass("table-subtitle")
                        .text(
                            formatDateTimeMinutes(event.created_at)
                            + " "
                            + (event.message || "")
                        )
                )
        );
    });
}

function renderNotifications(notifications, modal) {
    const target = modal.find("#alert-details-notifications");
    target.empty();

    if (!notifications.length) {
        target.append($("<div>").addClass("help-text").text("No delivery records."));
        return;
    }

    notifications.forEach(function (item) {
        const channel = item.channel ? item.channel.name + " (" + item.channel.channel_type + ")" : "-";
        const status = item.last_error ? "failed: " + item.last_error : (item.last_event_type || "sent");
        const requestedChannelId = item.provider_payload && item.provider_payload.requested_channel_id ? item.provider_payload.requested_channel_id : item.configured_channel_id;

        target.append(
            $("<div>")
                .addClass("event-item")
                .append($("<strong>").text("#" + item.id + " " + channel))
                .append($("<div>").text((item.provider || "-") + " / " + status))
                .append($("<div>").text("configured_channel_id: " + (item.configured_channel_id || "-")))
                .append($("<div>").text("requested_channel_id: " + (requestedChannelId || "-")))
                .append($("<div>").text("external_channel_id: " + (item.external_channel_id || "-")))
                .append($("<div>").text("message_id: " + (item.external_message_id || "-")))
        );
    });
}

function detailItem(label, value) {
    return $("<div>")
        .addClass("detail-item")
        .append($("<div>").addClass("detail-label").text(label))
        .append($("<div>").addClass("detail-value").text(value || "-"));
}

function setAlertsAutoRefresh(enabled) {
    if (alertsAutoRefreshTimer) {
        clearInterval(alertsAutoRefreshTimer);
        alertsAutoRefreshTimer = null;
    }
    if (enabled) {
        alertsAutoRefreshTimer = setInterval(loadAlerts, 30000);
    }
}

function alertDetailsModal() {
    return $("#alert-details-modal");
}


function openAlertDetailsModal() {
    openAppModal("#alert-details-modal");
}

function closeAlertDetailsModal(options) {
    options = options || {};

    closeAppModal("#alert-details-modal");

    currentDetailsAlertId = null;
    currentDetailsAlertCanRespond = false;
    currentDetailsActiveTab = "summary";
    currentDetailsExplainLoadedAlertId = null;
    currentDetailsExplainTraceId = null;

    if (options.updateUrl === false) {
        return;
    }
    if (getAlertIdFromPath(window.location.pathname)) {
        const url = buildAlertListUrl();

        history.pushState(
            {
                path: url,
                alerts_state: true
            },
            "",
            url
        );
    }
}

function alertsResponseItems(response) {
    if (Array.isArray(response)) {
        return response;
    }
    return asArray(response.items);
}

function alertsResponsePagination(response) {
    if (!response || !response.pagination) {
        return {
            page: alertsCurrentPage,
            page_size: alertsPageSize,
            total_items: 0,
            total_pages: 1,
            from: 0,
            to: 0,
            has_prev: false,
            has_next: false,
        };
    }
    return response.pagination;
}

function alertsResponseSummary(response) {
    if (!response || !response.summary) {
        return {
            firing: 0,
            acknowledged: 0,
            resolved: 0,
            silenced: 0,
            reminders: 0,
            total: 0,
        };
    }
    return response.summary;
}

function renderAlertsInboxCounter(pagination) {
    pagination = pagination || {};

    const root = document.getElementById("alerts-inbox-counter");

    if (!root) {
        return;
    }

    const from = Number(pagination.from || 0);
    const to = Number(pagination.to || 0);
    const filteredTotal = Number(pagination.total_items || 0);
    const summaryTotal = Number(alertsSummary.total || filteredTotal);

    const setValue = function (name, value) {
        const element = root.querySelector('[data-alerts-counter="' + name + '"]');

        if (element) {
            element.textContent = String(value);
        }
    };

    setValue("from", from);
    setValue("to", to);
    setValue("filtered", filteredTotal);
    setValue("total", summaryTotal);

    const totalWrapper = root.querySelector(
        '[data-alerts-counter="total-wrapper"]'
    );

    if (totalWrapper) {
        totalWrapper.hidden = (
            summaryTotal === filteredTotal
        );
    }
}

function applyAlertsQueryParams() {
    const queryString = getAlertsQueryStringForApply();
    const params = new URLSearchParams(queryString);

    setTableFilterValues(
        "#status-filter",
        getTableFilterParamValues(params, "status", ["statuses"])
    );

    setTableFilterValues(
        "#severity-filter",
        getTableFilterParamValues(params, "severity", ["severities"])
    );

    setTableFilterValues(
        "#priority-filter",
        getTableFilterParamValues(params, "priority", ["priorities"])
    );

    setTableFilterValues(
        "#alerts-service-filter",
        getTableFilterParamValues(params, "service_id", ["service_ids"])
    );

    $("#alerts-search").val(params.get("search") || "");

    $("#assigned-to-me-filter").prop(
        "checked",
        isAlertBoolQueryParamEnabled(params, "assigned_to_me")
    );

    alertsCurrentPage = parseInt(params.get("page") || "1", 10) || 1;
    alertsPageSize = parseInt(params.get("page_size") || "25", 10) || 25;

    alertsSortState.column = params.get("sort") || "activity";
    alertsSortState.direction = params.get("order") === "asc" ? "asc" : "desc";

    alertsLastAppliedQueryString = queryString;
}

$(document).on("click", "#reload-alerts", function () {
    loadAlerts();
});
$(document)
    .off(
        "change.tableFilters",
        "#status-filter, #severity-filter, #priority-filter, #alerts-service-filter, #assigned-to-me-filter"
    )
    .on(
        "change.tableFilters",
        "#status-filter, #severity-filter, #priority-filter, #alerts-service-filter, #assigned-to-me-filter",
        function () {
            if (
                typeof isTableFilterSilent === "function"
                && isTableFilterSilent(this)
            ) {
                return;
            }

            if (alertsServiceFilterApplying) {
                return;
            }

            resetAlertsPagination();
            writeAlertsQueryParams();
            loadAlerts();
        }
    );
$(document).on("input", "#alerts-search", function () {
    resetAlertsPagination();
    writeAlertsQueryParams();
    loadAlerts();
});
$(document)
    .off("change.alertsPageSize", "#alerts-page-size")
    .on("change.alertsPageSize", "#alerts-page-size", function () {
        alertsPageSize = parseInt(
            $(this).val(),
            10
        ) || 25;

        alertsCurrentPage = 1;

        writeAlertsQueryParams();
        loadAlerts();
    });

$(document)
    .off("click.alertsPrevPage", "#alerts-prev-page")
    .on("click.alertsPrevPage", "#alerts-prev-page", function () {
        if (
            !alertsPagination
            || !alertsPagination.has_prev
        ) {
            return;
        }

        alertsCurrentPage = Math.max(
            1,
            alertsCurrentPage - 1
        );

        writeAlertsQueryParams();
        loadAlerts();
    });

$(document)
    .off("click.alertsNextPage", "#alerts-next-page")
    .on("click.alertsNextPage", "#alerts-next-page", function () {
        if (
            !alertsPagination
            || !alertsPagination.has_next
        ) {
            return;
        }

        alertsCurrentPage += 1;

        writeAlertsQueryParams();
        loadAlerts();
    });
$(document)
    .off("click.sort-indicator", "[data-alerts-sort]")
    .on("click.alertsSort", "[data-alerts-sort]", function () {
        const column = $(this).data("alerts-sort");

        if (!column) {
            return;
        }

        if (alertsSortState.column === column) {
            alertsSortState.direction = alertsSortState.direction === "asc" ? "desc" : "asc";
        } else {
            alertsSortState.column = column;
            alertsSortState.direction = "desc";
        }

        alertsCurrentPage = 1;

        writeAlertsQueryParams();
        loadAlerts();
    });
$(document).on("change", "#alerts-auto-refresh", function () {
    setAlertsAutoRefresh($(this).is(":checked"));
});
$(document).on("click", "[data-alert-details-tab]", function () {
    setAlertDetailsTab($(this).data("alert-details-tab"));
});
$(document).on("click", "#alert-explain-refresh", function () {
    currentDetailsExplainLoadedAlertId = null;
    currentDetailsExplainTraceId = null;
    loadAlertExplainForCurrentDetails();
});
$(document).on("click", "#close-alert-details", closeAlertDetailsModal);
$(document).on("click", "#close-alert-details-footer", closeAlertDetailsModal);
$(document).on("click", "#alert-details-modal", function (event) {
    if (event.target === this) {
        closeAlertDetailsModal();
    }
});
$(document).on("keydown", function (event) {
    if (event.key === "Escape" && alertDetailsModal().hasClass("is-open")) {
        closeAlertDetailsModal();
    }
});
$(document).on("click", "#modal-alert-ack", function () {
    if (!currentDetailsAlertId) {
        return;
    }
    if (!currentDetailsAlertCanRespond) {
        showAppError("You do not have permission to acknowledge this alert.");
        return;
    }

    apiPost("/api/alerts/" + currentDetailsAlertId + "/ack", {}, function () {
        showAlertDetails(currentDetailsAlertId);
        loadAlerts();
    });
});
$(document).on("click", "#modal-alert-resolve", function () {
    if (!currentDetailsAlertId) {
        return;
    }
    if (!currentDetailsAlertCanRespond) {
        showAppError("You do not have permission to resolve this alert.");
        return;
    }

    apiPost("/api/alerts/" + currentDetailsAlertId + "/resolve", {}, function () {
        showAlertDetails(currentDetailsAlertId);
        loadAlerts();
    });
});
function loadAlertServiceFilter(callback) {
    const select = $("#alerts-service-filter");

    if (!select.length) {
        if (typeof callback === "function") {
            callback();
        }

        return;
    }

    const teamKey = (
        typeof selectedTeamId === "function" && selectedTeamId()
            ? String(selectedTeamId())
            : "all"
    );

    if (
        alertsServiceFilterLoaded
        && alertsServiceFilterTeamKey === teamKey
    ) {
        refreshTableMultiSelect(select);

        if (typeof callback === "function") {
            callback();
        }

        return;
    }

    alertsServiceFilterApplying = true;

    const params = new URLSearchParams(window.location.search || "");
    const currentValues = getTableFilterValues(select).length
        ? getTableFilterValues(select)
        : getTableFilterParamValues(params, "service_id", ["service_ids"]);

    apiGet("/api/services" + selectedTeamQuery(), function (response) {
        const services = asArray(response && response.items ? response.items : response);

        const serviceOptions = services
            .filter(function (service) {
                return service.enabled !== false;
            })
            .map(function (service) {
                return {
                    value: String(service.id),
                    text: [
                        service.team_slug || service.team_name || null,
                        service.name || service.slug || service.id
                    ].filter(Boolean).join(" / ")
                };
            });

        replaceTableSelectOptions(
            select,
            serviceOptions,
            currentValues
        );

        refreshTableMultiSelect(select);

        alertsServiceFilterLoaded = true;
        alertsServiceFilterTeamKey = teamKey;
        alertsServiceFilterApplying = false;

        if (typeof callback === "function") {
            callback();
        }
    });
}
window.addEventListener("popstate", function () {
    if (getAlertIdFromPath(window.location.pathname)) {
        syncAlertDetailsFromUrl();
        return;
    }

    if (alertDetailsModal().hasClass("is-open")) {
        closeAlertDetailsModal({ updateUrl: false });
    }

    loadAlerts();
});
initTableMultiSelects(document);
loadManualIncidentPermissions();

const initialExplainTraceId =
    getAlertsQueryParam("trace_id") ||
    getAlertsQueryParam("explain_trace_id");

if (initialExplainTraceId) {
    window.setTimeout(function () {
        openAlertDetailsForTrace(initialExplainTraceId);
    }, 100);
}

$(document).on("click", "#alerts-clear-selection", function () {
    clearAlertGroupSelection();
});

$(document).on("click", "#alerts-merge-selected", function () {
    mergeSelectedAlertGroups();
});
$(document).on("click", "#alerts-clear-selection", function () {
    clearAlertGroupSelection();
});

$(document).on("click", "#alerts-ack-selected", function () {
    bulkUpdateSelectedAlertGroups("ack");
});

$(document).on("click", "#alerts-resolve-selected", function () {
    bulkUpdateSelectedAlertGroups("resolve");
});

$(document).on("click", "#alerts-merge-selected", function () {
    mergeSelectedAlertGroups();
});

function runAlertGroupBulkAction(action, ids, onDone) {
    const queue = ids.slice();

    function next() {
        const id = queue.shift();

        if (!id) {
            if (typeof onDone === "function") {
                onDone();
            }
            return;
        }

        apiPost("/api/alerts/" + id + "/" + action, {}, next);
    }

    next();
}


function bulkUpdateSelectedAlertGroups(action) {
    const candidates = selectedAlertGroupsForBulkAction(action);
    const ids = candidates.map(function (alert) {
        return Number(alert.id);
    }).filter(Boolean);

    if (!ids.length) {
        showAppError(
            action === "ack"
                ? "Select at least one firing alert group to acknowledge."
                : "Select at least one unresolved alert group to resolve."
        );
        return;
    }

    const label = action === "ack" ? "acknowledge" : "resolve";
    const title = action === "ack" ? "Acknowledge selected alert groups?" : "Resolve selected alert groups?";
    const confirmText = action === "ack" ? "Acknowledge groups" : "Resolve groups";
    const message = "This will " + label + " " + ids.length + " selected alert group(s).";

    showAppConfirm({
        title: title,
        message: message,
        confirmText: confirmText,
        confirmClass: action === "ack" ? "btn-warning" : "btn-resolve"
    }).done(function () {
        runAlertGroupBulkAction(action, ids, function () {
            selectedAlertGroupIds.clear();
            loadAlerts();
        });
    });
}

function mergeSelectedAlertGroups() {
    const ids = Array.from(selectedAlertGroupIds).map(Number).filter(Boolean);

    if (ids.length < 2) {
        showAppError("Select at least two alert groups to merge.");
        return;
    }

    const targetId = alertGroupTargetIdFromSelection();

    if (!targetId) {
        showAppError("Could not choose merge target.");
        return;
    }

    const sourceIds = ids.filter(function (id) {
        return id !== targetId;
    });

    const target = alertsCache.find(function (item) {
        return Number(item.id) === Number(targetId);
    });

    const message = [
        "Selected groups will be merged into group #" + targetId + ".",
        target && target.title ? "Target: " + target.title : null,
        "Child alerts from other groups will be moved into the target group.",
    ].filter(Boolean).join("\n\n");

    showAppConfirm({
        title: "Merge selected alert groups?",
        message: message,
        confirmText: "Merge groups",
        confirmClass: "btn-warning"
    }).done(function () {
        apiPost("/api/alerts/merge", {
            target_group_id: targetId,
            source_group_ids: sourceIds,
            reason: "Merged from alerts UI"
        }, function () {
            selectedAlertGroupIds.clear();
            loadAlerts();
        });
    });
}
function openAlertExplainLookupModal() {
    $("#alert-explain-trace-id").val("");
    $("#alert-explain-lookup-error").addClass("is-hidden").text("");
    $("#alert-explain-lookup-modal").show();
    $("#alert-explain-trace-id").trigger("focus");
}

function closeAlertExplainLookupModal() {
    $("#alert-explain-lookup-modal").hide();
}

function showAlertExplainLookupError(message) {
    $("#alert-explain-lookup-error")
        .removeClass("is-hidden")
        .text(message || "Failed to open explain trace.");
}

function openAlertDetailsForTrace(traceId) {
    if (!traceId) {
        showAlertExplainLookupError("Trace ID is required.");
        return;
    }

    $.getJSON(`/api/alerts/explain/${encodeURIComponent(traceId)}`)
        .done((trace) => {
            closeAlertExplainLookupModal();

            const modal = alertDetailsModal();

            currentDetailsAlertId = trace.group_id || null;
            currentDetailsAlertCanRespond = false;
            currentDetailsActiveTab = "explain";
            currentDetailsExplainTraceId = trace.trace_id;
            currentDetailsExplainLoadedAlertId = trace.group_id || null;

            modal.find("#alert-details-title").text("Explain trace");
            modal.find("#alert-details-subtitle").text(
                trace.group_id
                    ? `Alert group #${trace.group_id}`
                    : "No alert group was created"
            );

            modal.find("#alert-details-overview").html("");
            modal.find("#alert-details-summary").html("");
            modal.find("#alert-details-alerts").html("");
            modal.find("#alert-details-events").html("");
            modal.find("#alert-details-notifications").html("");

            modal.find("#modal-alert-ack").hide();
            modal.find("#modal-alert-resolve").hide();

            renderAlertExplainSummary(trace);
            renderAlertExplainSteps(trace.steps || []);

            openAlertDetailsModal();
            setAlertDetailsTab("explain");

            const url = new URL(window.location.href);
            url.searchParams.delete("trace_id");
            url.searchParams.delete("explain_trace_id");
            window.history.replaceState({}, document.title, url.toString());
        })
        .fail((xhr) => {
            const payload = xhr.responseJSON || {};
            showAlertExplainLookupError(
                payload.message || "Explain trace not found."
            );
        });
}
$(document).on("click", "#open-alert-explain-trace", function () {
    openAlertExplainLookupModal();
});

$(document).on("click", "[data-alert-explain-lookup-close]", function () {
    closeAlertExplainLookupModal();
});

$(document).on("click", "#alert-explain-lookup-submit", function () {
    openAlertDetailsForTrace(
        $.trim($("#alert-explain-trace-id").val())
    );
});

$(document).on("keydown", "#alert-explain-trace-id", function (event) {
    if (event.key === "Enter") {
        event.preventDefault();

        openAlertDetailsForTrace(
            $.trim($("#alert-explain-trace-id").val())
        );
    }
});
function getAlertsQueryParam(name) {
    const params = new URLSearchParams(window.location.search);

    return params.get(name);
}

function showManualIncidentError(message) {
    $("#manual-incident-error")
        .removeClass("is-hidden")
        .text(message || "Failed to create incident.");
}

function clearManualIncidentError() {
    $("#manual-incident-error")
        .addClass("is-hidden")
        .text("");
}

function selectedManualIncidentTeamId() {
    const value = $("#manual-incident-team").val();

    if (!value) {
        return null;
    }

    return Number(value) || null;
}

function renderManualIncidentTeamOptions() {
    const select = $("#manual-incident-team");

    select.empty();

    const allowedTeams = manualIncidentTeams.filter(canCreateManualIncidentForTeam);

    if (!allowedTeams.length) {
        select.append(
            $("<option>")
                .attr("value", "")
                .text("No teams available")
        );
        select.prop("disabled", true);
        return;
    }

    select.prop("disabled", false);

    select.append(
        $("<option>")
            .attr("value", "")
            .text("Select team")
    );

    allowedTeams.forEach(function (team) {
        select.append(
            $("<option>")
                .attr("value", team.id)
                .text(team.name || team.slug || ("Team #" + team.id))
        );
    });

    const activeTeamId = (
        typeof selectedTeamId === "function"
        && selectedTeamId()
    )
        ? Number(selectedTeamId())
        : null;

    if (
        activeTeamId
        && allowedTeams.some(function (team) {
            return Number(team.id) === Number(activeTeamId);
        })
    ) {
        select.val(String(activeTeamId));
    } else if (allowedTeams.length === 1) {
        select.val(String(allowedTeams[0].id));
    }
}

function renderManualIncidentPriorityOptions() {
    const select = $("#manual-incident-priority");

    select.empty();

    select.append(
        $("<option>")
            .attr("value", "")
            .text("Automatic")
    );

    manualIncidentPriorities
        .filter(function (priority) {
            return priority.enabled !== false;
        })
        .forEach(function (priority) {
            const slug = priority.slug || "";
            const label = [
                slug ? String(slug).toUpperCase() : null,
                priority.name || null
            ].filter(Boolean).join(" ");

            select.append(
                $("<option>")
                    .attr("value", slug)
                    .text(label || slug || "Priority")
            );
        });
}

function renderManualIncidentServiceOptions() {
    const select = $("#manual-incident-service");

    select.empty();

    select.append(
        $("<option>")
            .attr("value", "")
            .text("No service")
    );

    manualIncidentServices
        .filter(function (service) {
            return service.enabled !== false;
        })
        .forEach(function (service) {
            select.append(
                $("<option>")
                    .attr("value", service.id)
                    .text(service.name || service.slug || ("Service #" + service.id))
            );
        });
}

function loadManualIncidentTeams(callback) {
    apiGet("/api/teams", function (response) {
        manualIncidentTeams = asArray(response && response.items ? response.items : response);
        renderManualIncidentTeamOptions();

        if (typeof callback === "function") {
            callback();
        }
    });
}

function loadManualIncidentPriorities(callback) {
    apiGet("/api/incidents/priorities", function (response) {
        manualIncidentPriorities = asArray(response);
        renderManualIncidentPriorityOptions();

        if (typeof callback === "function") {
            callback();
        }
    });
}

function loadManualIncidentServices(teamId, callback) {
    manualIncidentServices = [];
    renderManualIncidentServiceOptions();

    if (!teamId) {
        if (typeof callback === "function") {
            callback();
        }
        return;
    }

    apiGet("/api/services?team_id=" + encodeURIComponent(teamId), function (response) {
        manualIncidentServices = asArray(response && response.items ? response.items : response);
        renderManualIncidentServiceOptions();

        if (typeof callback === "function") {
            callback();
        }
    });
}

function resetManualIncidentForm() {
    clearManualIncidentError();

    $("#manual-incident-title").val("");
    $("#manual-incident-message").val("");
    $("#manual-incident-severity").val("critical");
    $("#manual-incident-priority").val("");
    $("#manual-incident-notify").prop("checked", true);
    $("#manual-incident-service").empty().append(
        $("<option>")
            .attr("value", "")
            .text("No service")
    );
}

function openManualIncidentModal() {
    resetManualIncidentForm();

    loadManualIncidentTeams(function () {
        loadManualIncidentPriorities(function () {
            loadManualIncidentServices(selectedManualIncidentTeamId(), function () {
                openAppModal("#manual-incident-modal");
                $("#manual-incident-title").trigger("focus");
            });
        });
    });
}

function validateManualIncidentPayload(payload) {
    if (!payload.team_id) {
        return "Select a team.";
    }

    if (!payload.title) {
        return "Incident title is required.";
    }

    const team = manualIncidentTeams.find(function (item) {
        return Number(item.id) === Number(payload.team_id);
    });

    if (!canCreateManualIncidentForTeam(team)) {
        return "You do not have permission to create incidents for this team.";
    }

    return null;
}

function collectManualIncidentPayload() {
    const serviceValue = $("#manual-incident-service").val();
    const priorityValue = $("#manual-incident-priority").val();

    return {
        team_id: selectedManualIncidentTeamId(),
        service_id: serviceValue ? Number(serviceValue) : null,
        title: $.trim($("#manual-incident-title").val()),
        message: $.trim($("#manual-incident-message").val()),
        severity: $("#manual-incident-severity").val() || "critical",
        priority: priorityValue || null,
        notify: $("#manual-incident-notify").is(":checked")
    };
}

function saveManualIncident() {
    clearManualIncidentError();

    const payload = collectManualIncidentPayload();
    const validationError = validateManualIncidentPayload(payload);

    if (validationError) {
        showManualIncidentError(validationError);
        return;
    }

    apiPost("/api/incidents", payload, function (incident) {
        closeAppModal("#manual-incident-modal");

        if (incident && incident.id) {
            openAlertDetailsPage(incident.id);
            loadAlerts();
            return;
        }

        loadAlerts();
    });
}
$(document).on("click", "#open-manual-incident-modal", function () {
    openManualIncidentModal();
});

$(document).on("click", "#close-manual-incident-modal", function () {
    closeAppModal("#manual-incident-modal");
});

$(document).on("click", "#manual-incident-modal", function (event) {
    if (event.target === this) {
        closeAppModal("#manual-incident-modal");
    }
});

$(document).on("keydown", function (event) {
    if (
        event.key === "Escape"
        && $("#manual-incident-modal").hasClass("is-open")
    ) {
        closeAppModal("#manual-incident-modal");
    }
});

$(document).on("click", "#reset-manual-incident-form", function () {
    resetManualIncidentForm();
});

$(document).on("click", "#save-manual-incident", function () {
    saveManualIncident();
});

$(document).on("keydown", "#manual-incident-title, #manual-incident-message", function (event) {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        saveManualIncident();
    }
});

function canCreateManualIncidentForTeam(team) {
    const permissions = (team && team.permissions) || {};

    return Boolean(permissions.can_create_manual_incident);
}

function loadManualIncidentPermissions(callback) {
    apiGet("/api/teams", function (response) {
        manualIncidentTeams = asArray(
            response && response.items ? response.items : response
        );

        manualIncidentPermissionsLoaded = true;
        renderManualIncidentCreateButton();

        if (typeof callback === "function") {
            callback();
        }
    });
}

function userCanCreateManualIncident() {
    return manualIncidentTeams.some(canCreateManualIncidentForTeam);
}

function renderManualIncidentCreateButton() {
    const button = $("#open-manual-incident-modal");

    if (!button.length) {
        return;
    }

    button.toggleClass(
        "is-hidden",
        !manualIncidentPermissionsLoaded || !userCanCreateManualIncident()
    );
}
