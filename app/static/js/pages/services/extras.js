// Service details extras: maintenance, timeline, charts, owners and page exports.
function normalizeServiceExternalUrl(value) {
    if (!value) {
        return "#";
    }

    try {
        const parsed = new URL(String(value), window.location.origin);
        if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
            return "#";
        }
        return parsed.href;
    } catch (error) {
        return "#";
    }
}


function renderServiceDetailsMaintenance(payload) {
    const windows = asArray(payload.maintenance_windows);
    const section = serviceDetailsSection(
        "Maintenance windows",
        "Active and upcoming maintenance that can affect this service."
    );
    const rows = windows.slice(0, 8).map(function (item) {
        return [
            item.name || ("Window #" + item.id),
            item.status || "scheduled",
            item.behavior || "-",
            (item.starts_at || "-") + " → " + (item.ends_at || "-"),
            item.timezone || "UTC",
        ];
    });

    section.append(
        serviceDetailsTableCard(
            "Windows",
            ["Window", "Status", "Behavior", "Time", "TZ"],
            rows,
            "No active or upcoming maintenance windows."
        )
    );

    return section;
}

function serviceDetailsSafeExternalUrl(value) {
    const raw = String(value || "").trim();

    if (!raw) {
        return "";
    }

    try {
        const url = new URL(raw, window.location.origin);

        if (url.protocol === "http:" || url.protocol === "https:" || url.protocol === "mailto:") {
            return url.href;
        }
    } catch (error) {
        return "";
    }

    return "";
}


function serviceDetailsExternalLink(url, label, fallback) {
    const text = label || url || fallback || "-";
    const safeUrl = serviceDetailsSafeExternalUrl(url);

    if (!safeUrl) {
        return $("<span>").text(text);
    }

    return $("<a>")
        .attr("href", safeUrl)
        .attr("target", "_blank")
        .attr("rel", "noopener noreferrer")
        .text(text);
}

function renderServiceDetailsRunbooks(payload) {
    const runbooks = asArray(payload.runbooks);
    const section = serviceDetailsSection(
        "Runbooks",
        "Response instructions for this service."
    );
    const rows = runbooks.slice(0, 8).map(function (runbook) {
        return [
            serviceDetailsExternalLink(
                runbook.url,
                runbook.title || runbook.url,
                "Runbook #" + runbook.id
            ),
            runbook.severity || "any",
            runbook.priority || 0,
            runbook.matcher_preset ? runbook.matcher_preset.name : "-",
            renderStatusBadge(runbook.enabled !== false, "Enabled", "Disabled"),
        ];
    });

    section.append(
        serviceDetailsTableCard(
            "Runbooks",
            ["Runbook", "Severity", "Priority", "Matcher preset", "Status"],
            rows,
            "No runbooks."
        )
    );

    return section;
}

function renderServiceDetailsLinks(payload) {
    const links = asArray(payload.links);
    const section = serviceDetailsSection(
        "Links",
        "Dashboards, logs, traces, repositories and documentation."
    );
    const rows = links.slice(0, 10).map(function (link) {
        return [
            serviceDetailsExternalLink(
                link.url,
                link.label || link.url,
                "Link #" + link.id
            ),
            link.link_type || "other",
            link.priority || 0,
            link.description || "-",
        ];
    });

    section.append(
        serviceDetailsTableCard(
            "Links",
            ["Link", "Type", "Priority", "Description"],
            rows,
            "No links."
        )
    );

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

    section.append(
        $("<div>")
            .addClass("grid-two")
            .append(renderServiceDependencyList("Depends on", upstream, true))
            .append(renderServiceDependencyList("Used by", downstream, false))
    );

    return section;
}



function renderServiceDependencyList(title, rows, upstream) {
    const tableRows = rows.slice(0, 10).map(function (dependency) {
        const name = upstream
            ? (dependency.depends_on_service_name || dependency.depends_on_service_slug || "-")
            : (dependency.service_name || dependency.service_slug || "-");

        const status = upstream
            ? dependency.depends_on_service_status
            : dependency.service_status;

        return [
            name,
            dependency.dependency_type || "dependency",
            dependency.criticality || "important",
            status || "unknown",
            dependency.description || "-",
        ];
    });

    const correlationLabel = dependency.correlation_enabled === false
        ? "Correlation off"
        : "Correlation " + (dependency.propagation_delay_seconds || 300) + "s";

    return [
        name,
        dependency.dependency_type || "dependency",
        dependency.criticality || "important",
        status || "unknown",
        $("<div>")
            .append($("<div>").text(dependency.description || "-"))
            .append($("<div>").addClass("row-subtitle").text(correlationLabel)),
    ];
}



function renderServiceDetailsAnalytics(analytics) {
    const section = serviceDetailsSection(
        "Analytics",
        "Service-level counters for the selected analytics window."
    );
    const widgets = analytics.widgets || {};
    const alertVolume = widgets.alert_volume || {};
    const status = widgets.status || {};

    section.append(
        serviceDetailsCompactCard("Counters", [
            ["Recent alerts", alertVolume.recent || 0],
            ["Total alerts", alertVolume.total || 0],
            ["Status changes", status.changes || 0],
            ["Analytics version", analytics.version || 1],
        ])
    );

    return section;
}



function renderServiceDetailsTimeline(payload) {
    const service = payload.service || {};
    const events = asArray(payload.timeline);
    const pageSize = 20;
    const section = serviceDetailsSection(
        "Timeline",
        "Recent service, readiness and configuration events."
    );
    const table = $("<table>").addClass("data-table");
    const tbody = $("<tbody>").attr("id", "service-details-timeline-body");
    const visibleEvents = events.slice(0, pageSize);

    table.append(
        $("<thead>").append(
            $("<tr>")
                .append($("<th>").text("Time"))
                .append($("<th>").text("Event"))
                .append($("<th>").text("Category"))
                .append($("<th>").text("Actor"))
        )
    );

    if (!visibleEvents.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>")
                    .attr("colspan", 4)
                    .addClass("empty-cell")
                    .text("No timeline events.")
            )
        );
    } else {
        visibleEvents.forEach(function (event) {
            tbody.append(renderServiceTimelineRow(event));
        });
    }

    table.append(tbody);

    section.append(
        $("<div>")
            .addClass("table-wrapper")
            .append(table)
    );

    if (service.id && visibleEvents.length === pageSize) {
        section.append(renderServiceTimelineLoadMoreButton(service.id, visibleEvents[visibleEvents.length - 1]));
    }

    return section;
}

function renderServiceTimelineRow(event) {
    const actor = event.actor || {};

    return $("<tr>")
        .append(serviceDetailsTableCell(formatServiceTimelineTime(event.occurred_at), false))
        .append(serviceDetailsTableCell(renderServiceTimelineEventCell(event), true))
        .append(serviceDetailsTableCell(renderServiceTimelineCategoryBadge(event.category), false))
        .append(serviceDetailsTableCell(formatServiceTimelineActor(actor), false));
}

function renderServiceTimelineEventCell(event) {
    const wrapper = $("<div>");
    const title = $("<div>").append(
        $("<strong>").text(event.title || event.event_type || "Event")
    );

    if (event.status) {
        title.append(" ").append(renderServiceTimelineStatusBadge(event.status));
    }

    wrapper.append(title);

    wrapper.append(
        $("<div>")
            .addClass("row-subtitle")
            .text(event.event_type || "-")
    );

    if (event.summary && event.summary !== event.event_type) {
        wrapper.append(
            $("<div>")
                .addClass("row-subtitle")
                .text(event.summary)
        );
    }

    return wrapper;
}

function renderServiceTimelineCategoryBadge(category) {
    return $("<span>")
        .addClass("status-pill status-neutral")
        .text(formatServiceTimelineCategory(category));
}

function renderServiceTimelineStatusBadge(status) {
    return $("<span>")
        .addClass(getServiceTimelineStatusClass(status))
        .text(formatServiceTimelineCategory(status));
}

function getServiceTimelineStatusClass(status) {
    if (status === "ready" || status === "operational" || status === "passed") {
        return "status-pill status-active";
    }

    if (status === "warning" || status === "degraded" || status === "maintenance") {
        return "status-pill status-scheduled";
    }

    if (status === "not_ready" || status === "failed" || status === "critical" || status === "down") {
        return "status-pill status-inactive";
    }

    return "status-pill status-neutral";
}

function formatServiceTimelineTime(value) {
    if (!value) {
        return "-";
    }

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return value;
    }

    const options = {
        month: "short",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
    };

    if (date.getFullYear() !== new Date().getFullYear()) {
        options.year = "numeric";
    }

    return date.toLocaleString(undefined, options);
}

function formatServiceTimelineCategory(value) {
    return String(value || "-").replace(/_/g, " ");
}

function formatServiceTimelineActor(actor) {
    if (!actor) {
        return "-";
    }

    if (actor.display_name) {
        return actor.display_name;
    }

    if (actor.label) {
        return actor.label;
    }

    if (actor.email) {
        return actor.email;
    }

    if (actor.user_id) {
        return "User #" + actor.user_id;
    }

    return actor.type || "-";
}

function renderServiceTimelineLoadMoreButton(serviceId, lastEvent) {
    const cursor = serviceTimelineCursorFromEvent(lastEvent);
    const actions = $("<div>").addClass("form-actions");
    const button = $("<button>")
        .attr("type", "button")
        .addClass("btn")
        .text("Load more")
        .on("click", function () {
            loadMoreServiceTimelineEvents(serviceId, $(this));
        });

    if (cursor) {
        button.data("before", cursor.before);
        button.data("before-id", cursor.before_id);
    }

    actions.append(button);

    return actions;
}

function serviceTimelineCursorFromEvent(event) {
    if (!event || !event.occurred_at) {
        return null;
    }

    return {
        before: event.occurred_at,
        before_id: event.id || "",
    };
}

function loadMoreServiceTimelineEvents(serviceId, button) {
    const before = button.data("before");
    const beforeId = button.data("before-id");

    if (!before) {
        button.closest(".form-actions").remove();
        return;
    }

    button.prop("disabled", true).text("Loading...");

    let url = "/api/services/" + encodeURIComponent(serviceId) + "/timeline?limit=20&before=" + encodeURIComponent(before);

    if (beforeId) {
        url += "&before_id=" + encodeURIComponent(beforeId);
    }

    apiGet(url, function (payload) {
        const items = asArray(payload.items);
        const tbody = $("#service-details-timeline-body");

        if (!items.length) {
            button.closest(".form-actions").remove();
            return;
        }

        items.forEach(function (event) {
            tbody.append(renderServiceTimelineRow(event));
        });

        if (payload.next_cursor) {
            button
                .data("before", payload.next_cursor.before)
                .data("before-id", payload.next_cursor.before_id)
                .prop("disabled", false)
                .text("Load more");
            return;
        }

        button.closest(".form-actions").remove();
    });
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
    if (!selectedServiceDetailsId || !isServiceDetailsModalOpen()) {
        return;
    }

    loadServiceDetails(selectedServiceDetailsId);
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

    config = window.servicesI18nTranslateChartConfig
        ? window.servicesI18nTranslateChartConfig(config)
        : config;

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

    const stringValue = String(value);

    if (stringValue.indexOf("T") !== -1) {
        const datePart = stringValue.split("T")[0];
        const hourPart = stringValue.split("T")[1].slice(0, 2);
        const dateParts = datePart.split("-");

        if (dateParts.length === 3) {
            return dateParts[1] + "/" + dateParts[2] + " " + hourPart + ":00";
        }
    }

    const parts = stringValue.split("-");

    if (parts.length === 3) {
        return parts[1] + "/" + parts[2];
    }

    return stringValue;
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
    const section = serviceDetailsSection("Default stakeholders", null);
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
                .addClass("empty-state compact")
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
                .append($("<th>").text("Status"))
                .append($("<th>").addClass("actions-th").text("Actions"))
        )
    );

    const tbody = $("<tbody>");

    owners.forEach(function (owner) {
        tbody.append(renderServiceOwnerCompactRow(service, owner));
    });

    table.append(tbody);

    section.append(
        $("<div>")
            .addClass("table-wrapper")
            .append(table)
    );

    return section;
}

function renderServiceOwnerCompactRow(service, owner) {
    return $("<tr>")
        .toggleClass("row-disabled", !owner.active)
        .append(
            $("<td>")
                .addClass("table-cell-truncate")
                .attr("title", serviceOwnerDisplayName(owner))
                .append($("<strong>").text(serviceOwnerDisplayName(owner)))
                .append($("<div>").addClass("row-subtitle").text(owner.user_email || owner.username || ""))
        )
        .append($("<td>").text(owner.role || "owner"))
        .append($("<td>").text(serviceOwnerNotificationText(owner)))
        .append(
            $("<td>").append(
                renderStatusBadge(!!owner.active, "Active", "Inactive")
            )
        )
        .append(
            $("<td>")
                .addClass("actions-cell")
                .append(renderServiceOwnerActions(service, owner))
        );
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
function updateServiceRunbookMatcherPresetHint() {
    const preset = findMatcherPresetById(
        serviceRunbookMatcherPresetsCache,
        $("#service-runbook-matcher-preset").val()
    );

    $("#service-runbook-matcher-preset-hint").text(
        matcherPresetAndLocalHint(preset)
    );
}


function loadServiceRunbookMatcherPresets(serviceId, selectedPresetId, callback) {
    const service = getServiceById(serviceId);
    serviceRunbookMatcherPresetsCache = [];

    fillMatcherPresetSelect(
        "#service-runbook-matcher-preset",
        [],
        null
    );
    updateServiceRunbookMatcherPresetHint();

    if (!service) {
        if (typeof callback === "function") {
            callback([]);
        }
        return;
    }

    loadMatcherPresetsForTeam(service.team_id, function (presets) {
        serviceRunbookMatcherPresetsCache = presets;

        fillMatcherPresetSelect(
            "#service-runbook-matcher-preset",
            presets,
            selectedPresetId
        );
        updateServiceRunbookMatcherPresetHint();

        if (typeof callback === "function") {
            callback(presets);
        }
    });
}
$(document).on("change", "#service-runbook-service", function () {
    loadServiceRunbookMatcherPresets(
        Number($(this).val()) || null,
        null
    );
});

$(document).on(
    "change",
    "#service-runbook-matcher-preset",
    updateServiceRunbookMatcherPresetHint
);

window.refreshServices = refreshServices;
window.loadServiceDetails = loadServiceDetails;
window.openServiceDetailsModal = openServiceDetailsModal;
window.getServiceById = getServiceById;
window.servicesCache = servicesCache;
window.selectedServiceId = selectedServiceDetailsId;
