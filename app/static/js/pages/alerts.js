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

    const parts = [i18n.t("alerts.group_count.total", {count: total})];

    if (firing) {
        parts.push(i18n.t("alerts.group_count.firing", {count: firing}));
    }
    if (resolved) {
        parts.push(i18n.t("alerts.group_count.resolved", {count: resolved}));
    }
    if (silenced) {
        parts.push(i18n.t("alerts.group_count.silenced", {count: silenced}));
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

        if (action === i18n.t("alert_details.bulk.resolve_action")) {
            return status !== "resolved" && status !== "merged";
        }

        return false;
    });
}

function currentPageSelectableAlertGroupIds(alerts) {
    return asArray(alerts || alertsCache)
        .filter(function (alert) {
            return (
                alert
                && isAlertGroup(alert)
                && canRespondObject(alert)
                && normalizeAlertValue(alert.status) !== "merged"
                && alert.id !== null
                && alert.id !== undefined
            );
        })
        .map(function (alert) {
            return Number(alert.id);
        })
        .filter(Boolean);
}

function pruneAlertGroupSelectionToCurrentPage(alerts) {
    const selectableIds = new Set(currentPageSelectableAlertGroupIds(alerts));

    selectedAlertGroupIds.forEach(function (id) {
        if (!selectableIds.has(Number(id))) {
            selectedAlertGroupIds.delete(id);
        }
    });
}

function updateAlertsPageSelectAllState() {
    const checkbox = $("#alerts-select-page");

    if (!checkbox.length) {
        return;
    }

    const ids = currentPageSelectableAlertGroupIds(alertsCache);
    const selectedCount = ids.filter(function (id) {
        return selectedAlertGroupIds.has(Number(id));
    }).length;

    checkbox
        .prop("disabled", ids.length < 1)
        .prop("checked", ids.length > 0 && selectedCount === ids.length)
        .prop("indeterminate", selectedCount > 0 && selectedCount < ids.length)
        .attr(
            "title",
            ids.length > 0
                ? i18n.t("alerts.select_all.page")
                : i18n.t("alerts.select_all.none")
        );
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
                .text(i18n.t("alerts.bulk.selected", {count: 0}))
        )
        .append(
            $("<button>")
                .attr("type", "button")
                .attr("id", "alerts-ack-selected")
                .addClass("btn btn-warning btn-small")
                .text(i18n.t("alerts.bulk.ack"))
        )
        .append(
            $("<button>")
                .attr("type", "button")
                .attr("id", "alerts-resolve-selected")
                .addClass("btn btn-resolve btn-small")
                .text(i18n.t("alerts.bulk.resolve"))
        )
        .append(
            $("<button>")
                .attr("type", "button")
                .attr("id", "alerts-merge-selected")
                .addClass("btn btn-small")
                .text(i18n.t("alerts.bulk.merge"))
        )
        .append(
            $("<button>")
                .attr("type", "button")
                .attr("id", "alerts-clear-selection")
                .addClass("btn btn-secondary btn-small")
                .text(i18n.t("alerts.bulk.clear"))
        );

    $("#alerts-table-view").before(bar);

    return bar;
}

function renderAlertsBulkActions() {
    const bar = ensureAlertsBulkActionsBar();
    const count = selectedAlertGroupIds.size;
    const ackCount = selectedAlertGroupsForBulkAction("ack").length;
    const resolveCount = selectedAlertGroupsForBulkAction(i18n.t("alert_details.bulk.resolve_action")).length;

    bar.toggle(count > 0);
    bar.find("#alerts-bulk-selected-count").text(i18n.t("alerts.bulk.selected", {count: count}));
    bar.find("#alerts-ack-selected")
        .prop("disabled", ackCount < 1)
        .text(ackCount > 0 ? i18n.t("alerts.bulk.ack_count", {count: ackCount}) : i18n.t("alerts.bulk.ack"));
    bar.find("#alerts-resolve-selected")
        .prop("disabled", resolveCount < 1)
        .text(resolveCount > 0 ? i18n.t("alerts.bulk.resolve_count", {count: resolveCount}) : i18n.t("alerts.bulk.resolve"));
    bar.find("#alerts-merge-selected").prop("disabled", count < 2);
    updateAlertsPageSelectAllState();
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
    const labels = {
        critical: "alerts.severity.critical",
        high: "alerts.severity.high",
        warning: "alerts.severity.warning",
        medium: "alerts.severity.medium",
        low: "alerts.severity.low",
        info: "alerts.severity.info",
    };

    return labels[value] ? i18n.t(labels[value]) : (severity || "-");
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

    const labels = {
        p1: "alerts.priority.p1",
        p2: "alerts.priority.p2",
        p3: "alerts.priority.p3",
        p4: "alerts.priority.p4",
        p5: "alerts.priority.p5",
    };

    return labels[slug] ? i18n.t(labels[slug]) : i18n.t("alerts.priority.p3");
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
    const labels = {
        p1: "alerts.priority.p1",
        p2: "alerts.priority.p2",
        p3: "alerts.priority.p3",
        p4: "alerts.priority.p4",
        p5: "alerts.priority.p5",
    };

    return labels[slug] ? i18n.t(labels[slug]) : (priority || "-");
}


function statusLabel(status) {
    const value = normalizeAlertValue(status);
    const labels = {
        firing: "alerts.status.firing",
        acknowledged: "alerts.status.acknowledged",
        resolved: "alerts.status.resolved",
        silenced: "alerts.status.silenced",
    };

    return labels[value] ? i18n.t(labels[value]) : (status || "-");
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
                i18n.t("alert_details.correlation.symptom"),
                "ui-pill-medium"
            ).attr(
                "title",
                i18n.t("alert_details.correlation.symptom_help")
            )
        );
    }

    if (Number(summary.downstream_impacts || 0) > 0) {
        wrapper.append(
            makeAlertBadge(
                i18n.t("alert_details.correlation.root_cause"),
                "ui-pill-critical"
            ).attr(
                "title",
                i18n.t("alert_details.correlation.root_cause_help")
            )
        );
    }

    wrapper.append(
        makeAlertBadge(
            i18n.t("alert_details.correlation.correlated", {count: Number(summary.total || 0)}),
            "ui-pill-info"
        ).attr(
            "title",
            i18n.t("alert_details.correlation.best_score", {score: Number(summary.best_score || 0)})
        )
    );

    return wrapper;
}


function alertBusinessImpactSummary(alert) {
    return alert && alert.business_impact_summary
        ? alert.business_impact_summary
        : {
            has_business_impact: false,
            total: 0,
            highest_status: null,
            highest_score: 0,
            services: []
        };
}


function businessImpactBadgeLabel(status) {
    const labels = {
        unknown: i18n.t("alert_details.business.unknown"),
        operational: i18n.t("alert_details.business.operational"),
        degraded: i18n.t("alert_details.business.degraded"),
        partial_outage: i18n.t("alert_details.business.partial_outage"),
        major_outage: i18n.t("alert_details.business.major_outage"),
        maintenance: i18n.t("alert_details.business.maintenance")
    };

    return labels[status] || status || i18n.t("alert_details.business.impact");
}


function businessImpactBadgeClass(status) {
    const value = normalizeAlertValue(status);

    if (value === "major_outage") {
        return "ui-pill-critical";
    }

    if (value === "partial_outage") {
        return "ui-pill-high";
    }

    if (value === "degraded" || value === "maintenance") {
        return "ui-pill-medium";
    }

    return "ui-pill-info";
}


function renderAlertBusinessImpactBadges(alert) {
    const summary = alertBusinessImpactSummary(alert);
    const wrapper = $("<div>").addClass("alert-correlation-badges alert-business-impact-badges");

    if (!summary.has_business_impact) {
        return wrapper;
    }

    const services = asArray(summary.services);
    const first = services.length ? services[0] : null;
    const title = services.map(function (item) {
        return (item.public_name || item.business_service_name || item.business_service_slug || "-")
            + " / "
            + businessImpactBadgeLabel(item.impact_status)
            + i18n.t("alert_details.business.score_separator")
            + Number(item.impact_score || 0);
    }).join("\n");

    wrapper.append(
        makeAlertBadge(
            first
                ? i18n.t("alert_details.business.badge", {name: first.public_name || first.business_service_name || first.business_service_slug})
                : i18n.t("alert_details.business.impact"),
            businessImpactBadgeClass(summary.highest_status)
        ).attr("title", title || i18n.t("alert_details.business.impact"))
    );

    if (Number(summary.total || 0) > 1) {
        wrapper.append(
            makeAlertBadge(i18n.t("alert_details.business.impacted", {count: Number(summary.total || 0)}), "ui-pill-info")
                .attr("title", title || i18n.t("alert_details.business.impact"))
        );
    }

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
        rowsLabel: i18n.t("alerts.table.rows_per_page"),
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
        chips.push({label: i18n.t("alerts.filters.search"), value: search});
    }

    if (statuses.length) {
        chips.push({
            label: i18n.t("alerts.filters.status"),
            value: statuses
                .map(function (status) {
                    return statusLabel(status);
                })
                .join(", ")
        });
    }

    if (severities.length) {
        chips.push({
            label: i18n.t("alerts.filters.severity"),
            value: severities
                .map(function (severity) {
                    return severityLabel(severity);
                })
                .join(", ")
        });
    }

    if (priorities.length) {
        chips.push({
            label: i18n.t("alerts.filters.priority"),
            value: priorities
                .map(function (priority) {
                    return priorityFilterLabel(priority);
                })
                .join(", ")
        });
    }

    if (serviceIds.length) {
        chips.push({
            label: i18n.t("alerts.filters.service"),
            value: serviceIds
                .map(function (serviceId) {
                    return tableSelectOptionLabel("#alerts-service-filter", serviceId);
                })
                .join(", ")
        });
    }
    if (assignedToMe) {
        chips.push({
            label: i18n.t("alerts.filters.assignee"),
            value: i18n.t("alerts.filters.me")
        });
    }

    if (typeof selectedTeamId === "function" && selectedTeamId()) {
        chips.push({label: i18n.t("alerts.filters.team"), value: getSelectedTeamLabel()});
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

    pruneAlertGroupSelectionToCurrentPage(alerts);

    if (!alerts.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>").attr("colspan", "10").addClass("empty-table-cell").text(i18n.t("alerts.table.empty"))
            )
        );
        updateAlertsPageSelectAllState();
        return;
    }

    alerts.forEach(function (alert) {
        tbody.append(renderAlertPageRow(alert));
    });

    updateAlertsPageSelectAllState();
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
                    updateAlertsPageSelectAllState();
                })
        );
    }

    idContent.append(
        $("<a>")
            .attr("href", buildAlertDetailsUrl(alert.id))
            .attr("title", i18n.t("alerts.table.view_details"))
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
            .append(renderAlertBusinessImpactBadges(alert))
            .append($("<div>").addClass("table-age").text(i18n.t("alerts.table.age", {value: alertDuration(alert)})))
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
            .append($("<div>").addClass("table-subtitle").text(alert.route_name || i18n.t("alerts.table.no_route")))
            .append(
                $("<div>")
                    .addClass("table-subtitle")
                    .text(alert.service_id ? i18n.t("alerts.table.service", {name: alertServiceLabel(alert)}) : i18n.t("alerts.table.no_service"))
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
        parts.push(i18n.t("alerts.table.group"));
    }
    if (alert.source) {
        parts.push(alert.source);
    }
    if (alert.group_key) {
        parts.push(alert.group_key);
    }

    return parts.length ? parts.join(" · ") : i18n.t("alerts.table.routed_alert");
}

function alertServiceLabel(alert) {
    if (!alert.service_id) {
        return i18n.t("alerts.table.no_service");
    }

    return (
        alert.service_name
        || alert.service_slug
        || i18n.t("alerts.table.service_number", {id: alert.service_id})
    );
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
    const label = isPolicy ? i18n.t("alert_details.escalation.policy") : i18n.t("alert_details.target.rotation");

    return $("<span>")
        .addClass("pill")
        .addClass(isPolicy ? "alerts-badge-info" : "badge-muted")
        .attr("title", isPolicy
            ? i18n.t("alert_details.escalation.policy_title", {name: alert.escalation_policy_name})
            : i18n.t("alert_details.escalation.simple"))
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
                        i18n.t("alert_details.escalation.rule", {position: alert.escalation_rule_position, target: alert.escalation_rule_target_type || "-"})
                    )
            );
        }

        if (alert.next_escalation_at) {
            wrapper.append(
                $("<div>")
                    .addClass("alerts-age")
                    .text(i18n.t("alert_details.escalation.next", {time: formatDateTimeMinutes(alert.next_escalation_at)}))
            );
        }

        return wrapper;
    }

    wrapper.append(
        $("<div>")
            .addClass("alerts-subtitle")
            .text(i18n.t("alert_details.escalation.level", {level: alert.escalation_level || 0}))
    );

    if (alert.team_escalation_enabled) {
        wrapper.append(
            $("<div>")
                .addClass("alerts-age")
                .text(i18n.t("alert_details.escalation.after_reminders", {count: alert.team_escalation_after_reminders || 0}))
        );
    }

    return wrapper;
}
function alertEscalationModeLabel(alert) {
    if (alert.escalation_policy_name) {
        return i18n.t("alert_details.escalation.policy");
    }

    return i18n.t("alert_details.escalation.simple_rotation");
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
        return i18n.t("alert_details.escalation.rotation_only");
    }

    if (alert.team_escalation_enabled) {
        return i18n.t("alert_details.escalation.after_reminders", {count: alert.team_escalation_after_reminders || 0});
    }

    return i18n.t("alert_details.status.disabled");
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

    renderAlertExplainEmpty(i18n.t("alert_details.explain.open_tab"));
    setAlertDetailsTab("summary");
}

function renderAlertExplainEmpty(message) {
    const modal = alertDetailsModal();

    modal.find("#alert-explain-summary")
        .empty()
        .append(
            $("<div>")
                .addClass("help-text")
                .text(message || i18n.t("alert_details.explain.empty"))
        );

    modal.find("#alert-explain-steps").empty();
}

function renderAlertExplainLoading(message) {
    renderAlertExplainEmpty(message || i18n.t("alert_details.explain.loading"));
}

function alertExplainStatusBadge(status) {
    const normalized = normalizeAlertValue(status);

    if (normalized === "success" || normalized === "completed") {
        return makeUiPill(i18n.t("alert_details.explain.status.success"), "ui-pill-resolved");
    }

    if (normalized === "warning") {
        return makeUiPill(i18n.t("alert_details.explain.status.warning"), "ui-pill-medium");
    }

    if (normalized === "error" || normalized === "failed") {
        return makeUiPill(i18n.t("alert_details.explain.status.error"), "ui-pill-critical");
    }

    if (normalized === "scheduled") {
        return makeUiPill(i18n.t("alert_details.explain.status.scheduled"), "ui-pill-info");
    }

    if (normalized === "stopped" || normalized === "skipped") {
        return makeUiPill(i18n.t("alert_details.explain.status." + normalized, {}, status || normalized), "ui-pill-muted");
    }

    return makeUiPill(i18n.t("alert_details.explain.status.info"), "ui-pill-muted");
}

function renderAlertExplainSummary(trace) {
    const modal = alertDetailsModal();
    const target = modal.find("#alert-explain-summary");

    target.empty();
    target.append(detailItem(i18n.t("alert_details.explain.trace"), trace.trace_id));
    if (trace.trace_level) {
        target.append(
            detailItem(
                i18n.t("alert_details.explain.level"),
                i18n.t(
                    "alert_details.explain.level." + trace.trace_level,
                    {},
                    trace.trace_level
                )
            )
        );
    }
    target.append(
        $("<div>")
            .addClass("detail-item")
            .append($("<div>").addClass("detail-label").text(i18n.t("alert_details.explain.status")))
            .append(
                $("<div>")
                    .addClass("detail-value")
                    .append(alertExplainStatusBadge(trace.status))
            )
    );
    target.append(detailItem(i18n.t("alert_details.explain.outcome"), trace.outcome));
    target.append(detailItem(i18n.t("alert_details.explain.source"), trace.source));
    target.append(detailItem(i18n.t("alert_details.explain.dedup_key"), trace.dedup_key));
    target.append(detailItem(i18n.t("alert_details.explain.started"), formatDateTimeMinutes(trace.started_at)));
    target.append(detailItem(i18n.t("alert_details.explain.finished"), formatDateTimeMinutes(trace.finished_at)));

    if (trace.reason) {
        target.append(detailItem(i18n.t("alert_details.explain.reason"), trace.reason));
    }

    if (trace.trace_level === "compact") {
        target.append(
            $("<div>")
                .addClass("help-text")
                .text(i18n.t("alert_details.explain.compact_notice"))
        );
    }
}

function renderAlertExplainSteps(steps) {
    const modal = alertDetailsModal();
    const target = modal.find("#alert-explain-steps");

    steps = asArray(steps);
    target.empty();

    if (!steps.length) {
        target.append($("<div>").addClass("help-text").text(i18n.t("alert_details.explain.steps_empty")));
        return;
    }

    steps.forEach(function (step) {
        const item = $("<div>").addClass("event-item");
        const header = $("<div>")
            .addClass("alert-explain-step-header")
            .append(
                $("<strong>").text(
                    "#" + (step.position || "-") + " " + (step.title || step.code || i18n.t("alert_details.explain.step"))
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
                    .append($("<summary>").text(i18n.t("alert_details.explain.data")))
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
        renderAlertExplainEmpty(i18n.t("alert_details.explain.none_selected"));
        return;
    }

    renderAlertExplainLoading(i18n.t("alert_details.explain.loading"));

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

        renderAlertExplainEmpty(i18n.t("alert_details.explain.no_incident"));
        return;
    }

    if (currentDetailsExplainLoadedAlertId === currentDetailsAlertId) {
        return;
    }

    currentDetailsExplainLoadedAlertId = currentDetailsAlertId;
    renderAlertExplainLoading(i18n.t("alert_details.explain.loading_many"));

    apiGet("/api/alerts/" + encodeURIComponent(currentDetailsAlertId) + "/explain", function (traces) {
        const latestTrace = pickLatestAlertExplainTrace(traces);

        if (!latestTrace) {
            renderAlertExplainEmpty(i18n.t("alert_details.explain.no_recorded"));
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
            console.error(i18n.t("alert_details.console.modal_not_found"));
            return;
        }

        currentDetailsAlertId = alert.id;
        currentDetailsAlertCanRespond = canRespondObject(alert);
        resetAlertDetailsTabs(alert.id);

        modal.find("#alert-details-title").text(alert.title || i18n.t("alert_details.entity.alert_number", {id: alert.id}));
        modal.find("#alert-details-subtitle").text(buildAlertDetailsSubtitle(alert));

        renderAlertPrimaryDetails(alert, modal);
        renderAlertServiceContext(alert, modal);
        renderAlertCorrelation(alert, modal);
        renderAlertBusinessImpact(alert, modal);
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

function ensureAlertBusinessImpact(modal) {
    let target = modal.find("#alert-business-impact");

    if (target.length) {
        return target;
    }

    target = $("<div>")
        .attr("id", "alert-business-impact")
        .addClass("alert-service-context alert-business-impact");

    const correlation = modal.find("#alert-correlation-context");
    const serviceContext = modal.find("#alert-service-context");
    const primary = modal.find("#alert-primary-details");
    const overview = modal.find("#alert-details-overview");

    if (correlation.length) {
        correlation.after(target);
    } else if (serviceContext.length) {
        serviceContext.after(target);
    } else if (primary.length) {
        primary.after(target);
    } else if (overview.length) {
        overview.append(target);
    } else {
        modal.find("#alert-details-summary").before(target);
    }

    return target;
}


function businessImpactStatusLabel(status) {
    const labels = {
        unknown: i18n.t("alert_details.business.unknown"),
        operational: i18n.t("alert_details.business.operational"),
        degraded: i18n.t("alert_details.business.degraded"),
        partial_outage: i18n.t("alert_details.business.partial_outage"),
        major_outage: i18n.t("alert_details.business.major_outage"),
        maintenance: i18n.t("alert_details.business.maintenance")
    };

    return labels[status] || status || "-";
}


function businessImpactStatusBadgeClass(status) {
    const value = normalizeAlertValue(status);

    if (value === "major_outage") {
        return "ui-pill-critical";
    }

    if (value === "partial_outage") {
        return "ui-pill-high";
    }

    if (value === "degraded" || value === "maintenance") {
        return "ui-pill-medium";
    }

    if (value === "operational") {
        return "ui-pill-low";
    }

    return "ui-pill-muted";
}


function businessImpactTitle(impact) {
    return (
        impact.public_name
        || impact.business_service_name
        || impact.business_service_slug
        || (i18n.t("alert_details.entity.business_service_number", {id: impact.business_service_id}))
    );
}


function businessImpactMeta(impact) {
    return [
        impact.impact_status ? i18n.t("alert_details.business.status_prefix") + businessImpactStatusLabel(impact.impact_status) : null,
        Number.isFinite(Number(impact.impact_score)) ? i18n.t("alert_details.business.score_prefix") + Number(impact.impact_score) : null,
        impact.service_name ? i18n.t("alert_details.business.via_prefix") + impact.service_name : null,
        impact.relation || null,
    ].filter(Boolean).join(" / ");
}


function renderBusinessImpactComponentSnapshot(impact) {
    const snapshot = asArray(impact.component_snapshot);
    const affected = snapshot.filter(function (item) {
        return item.impact_score > 0 || normalizeAlertValue(item.service_status) !== "operational";
    });

    const list = $("<div>").addClass("alert-service-context-list");

    if (!affected.length) {
        return list.append($("<div>").addClass("help-text").text(i18n.t("alert_details.business.no_components")));
    }

    affected.slice(0, 5).forEach(function (item) {
        list.append(
            $("<div>")
                .addClass("alert-service-context-link")
                .append(
                    $("<div>")
                        .addClass("alert-service-context-title")
                        .text(item.service_name || item.service_slug || i18n.t("alert_details.entity.service_number", {id: item.service_id}))
                )
                .append(
                    $("<div>")
                        .addClass("alert-service-context-meta")
                        .text([
                            item.service_status ? i18n.t("alert_details.business.status_prefix") + item.service_status : null,
                            item.criticality ? i18n.t("alert_details.business.criticality_prefix") + item.criticality : null,
                            Number.isFinite(Number(item.impact_score)) ? i18n.t("alert_details.business.score_prefix") + Number(item.impact_score) : null,
                            Number.isFinite(Number(item.impact_weight)) ? i18n.t("alert_details.business.weight_prefix") + Number(item.impact_weight) : null,
                        ].filter(Boolean).join(" / "))
                )
        );
    });

    if (affected.length > 5) {
        list.append(
            $("<div>")
                .addClass("help-text")
                .text(i18n.t("alert_details.business.more_components", {count: affected.length - 5}))
        );
    }

    return list;
}


function renderAlertBusinessImpact(alert, modal) {
    const target = ensureAlertBusinessImpact(modal);
    const impacts = asArray(alert.business_impacts);

    target.empty();

    if (!impacts.length) {
        target.hide();
        return;
    }

    target.show();

    target.append(
        $("<div>")
            .addClass("alert-service-context-header")
            .append($("<h3>").text(i18n.t("alert_details.business.impact")))
            .append(
                $("<div>")
                    .addClass("card-subtitle")
                    .text(i18n.t("alert_details.business.help"))
            )
    );

    const grid = $("<div>").addClass("alert-service-context-grid");

    impacts.forEach(function (impact) {
        const section = $("<div>")
            .addClass("alert-service-context-section")
            .append(
                $("<div>")
                    .addClass("alert-correlation-title")
                    .append(
                        makeAlertBadge(
                            businessImpactStatusLabel(impact.impact_status),
                            businessImpactStatusBadgeClass(impact.impact_status)
                        )
                    )
                    .append(
                        $("<strong>")
                            .text(businessImpactTitle(impact))
                    )
            )
            .append(
                $("<div>")
                    .addClass("alert-service-context-meta")
                    .text(businessImpactMeta(impact))
            );

        if (impact.reason) {
            section.append(
                $("<div>")
                    .addClass("table-subtitle")
                    .text(impact.reason)
            );
        }

        section.append(renderBusinessImpactComponentSnapshot(impact));
        grid.append(section);
    });

    target.append(grid);
}

function buildAlertDetailsSubtitle(alert) {
    return [
        alert.source || null,
        alert.team_slug || null,
        statusLabel(alert.status) || null,
        severityLabel(alert.severity) || null,
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
            .text(alert.title || i18n.t("alert_details.entity.alert_number", {id: alert.id}))
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
                .text(i18n.t("alert_details.primary.no_message"))
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
                        .text(i18n.t("alert_details.primary.open_source"))
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
        parts.push(i18n.t("alert_details.primary.created", {time: formatDateTimeMinutes(alert.first_seen_at || alert.created_at)}));
    }

    if (alert.last_seen_at) {
        parts.push(i18n.t("alert_details.primary.last_seen", {time: formatDateTimeMinutes(alert.last_seen_at)}));
    }

    return parts.join(" · ");
}


function buildAlertPrimaryContext(alert) {
    const context = [
        {
            label: i18n.t("alert_details.detail.assignee"),
            value: alert.assignee || "-"
        },
        {
            label: i18n.t("alert_details.detail.route"),
            value: alert.route_name || "-"
        },
        {
            label: i18n.t("alert_details.detail.service"),
            value: alertServiceDetailsLabel(alert)
        },
        {
            label: i18n.t("alert_details.detail.next_escalation"),
            value: formatDateTimeMinutes(alert.next_escalation_at)
        }
    ];

    if (window.AppMaintenanceBadges && window.AppMaintenanceBadges.has(alert)) {
        context.push({
            label: i18n.t("alert_details.business.maintenance"),
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
                .text(i18n.t("alert_details.primary.no_labels"))
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
            .append($("<h3>").text(i18n.t("alert_details.service_context.title")))
            .append(
                $("<div>")
                    .addClass("card-subtitle")
                    .text(alertServiceDetailsLabel(alert))
            )
    );

    const linksList = $("<div>")
        .attr("id", "alert-service-links")
        .addClass("alert-service-context-list")
        .append($("<div>").addClass("help-text").text(i18n.t("alert_details.loading.links")));

    const runbooksList = $("<div>")
        .attr("id", "alert-service-runbooks")
        .addClass("alert-service-context-list")
        .append($("<div>").addClass("help-text").text(i18n.t("alert_details.loading.runbooks")));

    target.append(
        $("<div>")
            .addClass("alert-service-context-grid")
            .append(
                $("<section>")
                    .addClass("alert-service-context-section")
                    .append($("<h4>").text(i18n.t("alert_details.service_context.links")))
                    .append(linksList)
            )
            .append(
                $("<section>")
                    .addClass("alert-service-context-section")
                    .append($("<h4>").text(i18n.t("alert_details.service_context.runbooks")))
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
        target.append($("<div>").addClass("help-text").text(i18n.t("alert_details.service_context.no_links")));
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
        target.append($("<div>").addClass("help-text").text(i18n.t("alert_details.service_context.no_runbooks")));
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
                                runbook.severity ? i18n.t("alert_details.service_context.severity_prefix") + runbook.severity : null,
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
        possible_symptom: i18n.t("alert_details.correlation.possible_symptom"),
        possible_root_cause: i18n.t("alert_details.correlation.possible_root"),
        related: i18n.t("alert_details.correlation.related")
    };

    return labels[role] || role || i18n.t("alert_details.correlation.related");
}


function alertCorrelationRelationLabel(relationType) {
    const labels = {
        possible_root_cause: i18n.t("alert_details.correlation.possible_root"),
        possible_downstream_impact: i18n.t("alert_details.correlation.downstream"),
        same_dependency_chain: i18n.t("alert_details.correlation.same_chain")
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
        statusLabel(group.status) || null,
        severityLabel(group.severity) || null,
        alertPriorityLabel(group) || null,
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
                .text(i18n.t("alert_details.correlation.score_prefix") + (item.score || 0))
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
                    item.depth ? i18n.t("alert_details.correlation.depth_prefix") + item.depth : null
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
                    .append($("<h2>").text(i18n.t("alert_details.correlation.title")))
                    .append(
                        $("<div>")
                            .addClass("card-subtitle")
                            .text(i18n.t("alert_details.correlation.help"))
                    )
            )
    );

    const body = $("<div>").addClass("form-body");

    if (rootCandidates.length) {
        body.append(
            $("<h3>").text(i18n.t("alert_details.correlation.possible_root"))
        );

        rootCandidates.forEach(function (item) {
            body.append(buildAlertCorrelationItem(item));
        });
    }

    if (downstreamImpacts.length) {
        body.append(
            $("<h3>").text(i18n.t("alert_details.correlation.downstream"))
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

    summary.append(detailItem(i18n.t("alert_details.explain.source"), alert.source));
    summary.append(detailItem(i18n.t("alert_details.detail.external_id"), alert.external_id));
    summary.append(detailItem(i18n.t("alert_details.detail.group_key"), alert.group_key));
    summary.append(detailItem(i18n.t("alert_details.explain.dedup_key"), alert.dedup_key));

    summary.append(detailItem(i18n.t("alert_details.target.team"), alert.team_name || alert.team_slug));
    summary.append(detailItem(i18n.t("alert_details.detail.route"), alert.route_name));
    summary.append(detailItem(i18n.t("alert_details.detail.service"), alertServiceDetailsLabel(alert)));
    summary.append(detailItem(i18n.t("alert_details.form.priority"), alertPriorityLabel(alert)));
    summary.append(detailItem(i18n.t("alert_details.detail.service_status"), alert.service_status));
    summary.append(detailItem(i18n.t("alert_details.detail.service_criticality"), alert.service_criticality));

    summary.append(detailItem(i18n.t("alert_details.detail.escalation_mode"), alertEscalationModeLabel(alert)));
    summary.append(detailItem(i18n.t("alert_details.target.escalation_policy"), alert.escalation_policy_name));
    summary.append(detailItem(i18n.t("alert_details.detail.policy_rule"), alertPolicyRuleLabel(alert)));
    summary.append(detailItem(i18n.t("alert_details.target.rotation"), alert.rotation_name));
    summary.append(detailItem(i18n.t("alert_details.detail.assignee"), alert.assignee));
    summary.append(detailItem(i18n.t("alert_details.detail.next_escalation"), formatDateTimeMinutes(alert.next_escalation_at)));
    summary.append(detailItem(i18n.t("alert_details.detail.last_escalated"), formatDateTimeMinutes(alert.last_escalated_at)));
    summary.append(detailItem(i18n.t("alert_details.detail.escalation_level"), alert.escalation_level || 0));
    summary.append(detailItem(i18n.t("alert_details.detail.policy_repeat"), alert.escalation_repeat_count || 0));
    summary.append(detailItem(i18n.t("alert_details.detail.default_rotation"), alertTeamEscalationLabel(alert)));

    summary.append(detailItem(i18n.t("alert_details.detail.acknowledged_by"), alert.acknowledged_by));
    summary.append(detailItem(i18n.t("alert_details.detail.created"), formatDateTimeMinutes(alert.first_seen_at || alert.created_at)));
    summary.append(detailItem(i18n.t("alert_details.detail.last_seen"), formatDateTimeMinutes(alert.last_seen_at)));
    summary.append(detailItem(i18n.t("alert_details.detail.last_notification"), formatDateTimeMinutes(alert.last_notification_at)));
    summary.append(detailItem(i18n.t("alert_details.detail.reminder_count"), alert.reminder_count || 0));
    summary.append(detailItem(
        i18n.t("alert_details.detail.reminder_interval"),
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
            $("<div>").addClass("help-text").text(i18n.t("alert_details.children.empty"))
        );
        return;
    }

    alerts.forEach(function (alert) {
        const labels = alert.labels || {};
        const createdAt = alert.first_seen_at || alert.created_at || null;
        const lastSeenAt = alert.last_seen_at || alert.updated_at || null;

        const subtitle = [
            statusLabel(alert.status) || null,
            severityLabel(alert.severity) || null,
            createdAt ? i18n.t("alert_details.children.created_prefix") + formatDateTimeMinutes(createdAt) : null,
            lastSeenAt ? i18n.t("alert_details.children.last_seen_prefix") + formatDateTimeMinutes(lastSeenAt) : null,
            labels.instance ? i18n.t("alert_details.children.instance_prefix") + labels.instance : null,
            alert.dedup_key ? i18n.t("alert_details.children.dedup_prefix") + alert.dedup_key : null,
        ].filter(Boolean).join(" · ");

        target.append(
            $("<div>")
                .addClass("alert-child-item")
                .append(
                    $("<div>")
                        .addClass("alert-child-header")
                        .append(
                            $("<span>").text("#" + alert.id + " " + (alert.title || i18n.t("alert_details.entity.alert")))
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
                                .text(i18n.t("alert_details.primary.created", {time: formatDateTimeMinutes(createdAt) || "-"}))
                        )
                        .append(
                            $("<span>")
                                .addClass("alert-child-time-item")
                                .text(i18n.t("alert_details.primary.last_seen", {time: formatDateTimeMinutes(lastSeenAt) || "-"}))
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
        correlation_detected: i18n.t("alert_details.events.correlation_detected"),
        correlation_deactivated: i18n.t("alert_details.events.correlation_deactivated"),
        business_impact_detected: i18n.t("alert_details.events.business_detected"),
        business_impact_updated: i18n.t("alert_details.events.business_updated"),
        business_impact_deactivated: i18n.t("alert_details.events.business_deactivated"),
        merged: i18n.t("alert_details.events.merged"),
        merge_target_updated: i18n.t("alert_details.events.merge_target_updated"),
        acknowledged: i18n.t("alert_details.events.acknowledged"),
        resolved: i18n.t("alert_details.responder.resolved"),
        notification: i18n.t("alert_details.events.notification"),
        reminder: i18n.t("alert_details.events.reminder"),
        escalation: i18n.t("alert_details.events.escalation")
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
                .text(i18n.t("alert_details.events.empty"))
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
        target.append($("<div>").addClass("help-text").text(i18n.t("alert_details.delivery.empty")));
        return;
    }

    notifications.forEach(function (item) {
        const channel = item.channel ? item.channel.name + " (" + item.channel.channel_type + ")" : "-";
        const status = item.last_error ? i18n.t("alert_details.delivery.failed_prefix") + item.last_error : (item.last_event_type || i18n.t("alert_details.delivery.sent"));
        const requestedChannelId = item.provider_payload && item.provider_payload.requested_channel_id ? item.provider_payload.requested_channel_id : item.configured_channel_id;

        target.append(
            $("<div>")
                .addClass("event-item")
                .append($("<strong>").text("#" + item.id + " " + channel))
                .append($("<div>").text((item.provider || "-") + " / " + status))
                .append($("<div>").text(i18n.t("alert_details.delivery.configured_channel") + ": " + (item.configured_channel_id || "-")))
                .append($("<div>").text(i18n.t("alert_details.delivery.requested_channel") + ": " + (requestedChannelId || "-")))
                .append($("<div>").text(i18n.t("alert_details.delivery.external_channel") + ": " + (item.external_channel_id || "-")))
                .append($("<div>").text(i18n.t("alert_details.delivery.message_id") + ": " + (item.external_message_id || "-")))
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
        showAppError(i18n.t("alert_details.permissions.ack"));
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
        showAppError(i18n.t("alert_details.permissions.resolve"));
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
                        service.team_name || service.team_slug || null,
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

$(document).on("click", "#alerts-select-page", function (event) {
    event.stopPropagation();
});

$(document).on("change", "#alerts-select-page", function (event) {
    event.stopPropagation();

    const checked = $(this).is(":checked");
    const ids = currentPageSelectableAlertGroupIds(alertsCache);

    ids.forEach(function (id) {
        if (checked) {
            selectedAlertGroupIds.add(Number(id));
        } else {
            selectedAlertGroupIds.delete(Number(id));
        }
    });

    renderAlertsTable(alertsCache);
    renderAlertsBulkActions();
});

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
    bulkUpdateSelectedAlertGroups(i18n.t("alert_details.bulk.resolve_action"));
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
                ? i18n.t("alert_details.bulk.ack_required")
                : i18n.t("alert_details.bulk.resolve_required")
        );
        return;
    }

    const label = action === "ack" ? i18n.t("alert_details.bulk.ack_action") : i18n.t("alert_details.bulk.resolve_action");
    const title = action === "ack" ? i18n.t("alert_details.bulk.ack_title") : i18n.t("alert_details.bulk.resolve_title");
    const confirmText = action === "ack" ? i18n.t("alert_details.bulk.ack_confirm") : i18n.t("alert_details.bulk.resolve_confirm");
    const message = i18n.t("alert_details.bulk.message", {action: label, count: ids.length});

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
        showAppError(i18n.t("alert_details.merge.minimum"));
        return;
    }

    const targetId = alertGroupTargetIdFromSelection();

    if (!targetId) {
        showAppError(i18n.t("alert_details.merge.no_target"));
        return;
    }

    const sourceIds = ids.filter(function (id) {
        return id !== targetId;
    });

    const target = alertsCache.find(function (item) {
        return Number(item.id) === Number(targetId);
    });

    const message = [
        i18n.t("alert_details.merge.target_group", {id: targetId}),
        target && target.title ? i18n.t("alert_details.merge.target", {title: target.title}) : null,
        i18n.t("alert_details.merge.children"),
    ].filter(Boolean).join("\n\n");

    showAppConfirm({
        title: i18n.t("alert_details.merge.title"),
        message: message,
        confirmText: i18n.t("alert_details.merge.confirm"),
        confirmClass: "btn-warning"
    }).done(function () {
        apiPost("/api/alerts/merge", {
            target_group_id: targetId,
            source_group_ids: sourceIds,
            reason: i18n.t("alert_details.merge.reason")
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
        .text(message || i18n.t("alert_details.trace.open_failed"));
}

function openAlertDetailsForTrace(traceId) {
    if (!traceId) {
        showAlertExplainLookupError(i18n.t("alert_details.trace.required"));
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

            modal.find("#alert-details-title").text(i18n.t("alert_details.trace.details_title"));
            modal.find("#alert-details-subtitle").text(
                trace.group_id
                    ? `Alert group #${trace.group_id}`
                    : i18n.t("alert_details.trace.no_group")
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
                payload.message || i18n.t("alert_details.trace.not_found")
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
        .text(message || i18n.t("alert_details.manual.failed"));
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
                .text(i18n.t("alert_details.manual.no_teams"))
        );
        select.prop("disabled", true);
        return;
    }

    select.prop("disabled", false);

    select.append(
        $("<option>")
            .attr("value", "")
            .text(i18n.t("alert_details.manual.select_team"))
    );

    allowedTeams.forEach(function (team) {
        select.append(
            $("<option>")
                .attr("value", team.id)
                .text(team.name || team.slug || i18n.t("alert_details.entity.team_number", {id: team.id}))
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
            .text(i18n.t("alert_details.priority.automatic"))
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
                    .text(label || slug || i18n.t("alert_details.form.priority"))
            );
        });
}

function renderManualIncidentServiceOptions() {
    const select = $("#manual-incident-service");

    select.empty();

    select.append(
        $("<option>")
            .attr("value", "")
            .text(i18n.t("alert_details.manual.no_service"))
    );

    manualIncidentServices
        .filter(function (service) {
            return service.enabled !== false;
        })
        .forEach(function (service) {
            select.append(
                $("<option>")
                    .attr("value", service.id)
                    .text(service.name || service.slug || i18n.t("alert_details.entity.service_number", {id: service.id}))
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
            .text(i18n.t("alert_details.manual.no_service"))
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
        return i18n.t("alert_details.manual.select_team_error");
    }

    if (!payload.title) {
        return i18n.t("alert_details.manual.title_required");
    }

    const team = manualIncidentTeams.find(function (item) {
        return Number(item.id) === Number(payload.team_id);
    });

    if (!canCreateManualIncidentForTeam(team)) {
        return i18n.t("alert_details.manual.permission");
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
