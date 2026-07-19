// Service details, SLI/SLO forms, readiness, compact cards and helper renderers.


function isServiceDetailsModalOpen() {
    return $("#service-details-modal").is(":visible");
}


function openServiceDetailsModal(serviceId) {
    const service = getServiceById(serviceId);

    if (!service) {
        return;
    }

    selectedServiceDetailsId = service.id;
    window.selectedServiceId = selectedServiceDetailsId;

    openAppModal("#service-details-modal");
    loadServiceDetails(service.id);
}


function closeServiceDetailsModal() {
    closeAppModal("#service-details-modal");
}


function loadServiceDetails(serviceId) {
    const service = getServiceById(serviceId);

    if (!service) {
        return;
    }

    selectedServiceDetailsId = service.id;
    window.selectedServiceId = selectedServiceDetailsId;

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
    const body = $("#service-details-modal-body");

    $("#service-details-modal-title").text(service.name || service.slug || "Service details");
    $("#service-details-modal-subtitle").text(
        (service.team_name || service.team_slug || "-") +
        " / " +
        (service.status || "unknown")
    );

    body.empty();
    body.append(
        $("<div>")
            .addClass("empty-state")
            .text("Loading service details for " + (service.name || service.slug || "service") + "...")
    );
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
    const body = $("#service-details-modal-body");

    $("#service-details-modal-title").text(service.name || service.slug || "Service details");
    $("#service-details-modal-subtitle").text(
        (service.team_name || service.team_slug || "-") +
        " / " +
        (service.status || "unknown")
    );

    body.empty();

    body.append(renderServiceDetailsHero(payload));

    body.append(renderServiceDetailsMetrics(payload));
    body.append(renderServiceDetailsQuickActions(payload));
    body.append(renderServiceDetailsOwners(payload));
    body.append(renderServiceDetailsReadiness(payload));
    body.append(renderServiceDetailsSliSlo(payload));
    body.append(renderServiceDetailsImpact(payload));
    body.append(renderServiceDetailsMaintenance(payload));
    body.append(renderServiceDetailsRunbooks(payload));
    body.append(renderServiceDetailsLinks(payload));
    body.append(renderServiceDetailsDependencies(payload));
    body.append(renderServiceDetailsAnalytics(analytics));
    body.append(renderServiceDetailsTimeline(payload));
}

function renderServiceDetailsMetrics(payload) {
    const summary = payload.summary || {};
    const alerts = summary.alerts || {};
    const section = serviceDetailsSection("Metrics", null);

    const table = $("<table>").addClass("data-table");
    const tbody = $("<tbody>");

    tbody.append(
        $("<tr>")
            .append($("<th>").text("Open alerts"))
            .append($("<td>").text(Number(alerts.open || 0)))
            .append($("<th>").text("Critical open"))
            .append($("<td>").text(Number(alerts.critical_open || 0)))
    );

    tbody.append(
        $("<tr>")
            .append($("<th>").text("Maintenance"))
            .append($("<td>").text(Number(summary.maintenance_windows || 0)))
            .append($("<th>").text("Dependencies"))
            .append(
                $("<td>").text(
                    Number(summary.upstream_dependencies || 0) +
                    " / " +
                    Number(summary.downstream_dependencies || 0) +
                    " upstream / downstream"
                )
            )
    );

    table.append(tbody);

    section.append(
        $("<div>")
            .addClass("table-wrapper")
            .append(table)
    );

    return section;
}


function renderServiceDetailsSliSlo(payload) {
    const service = payload.service || {};
    const sliSlo = payload.sli_slo || {};
    const slis = asArray(sliSlo.slis);
    const slos = asArray(sliSlo.slos);
    const section = serviceDetailsSection(
        "SLI / SLO",
        "Indicators describe what is measured. Objectives define the target for those indicators."
    );
    const actions = $("<div>").addClass("details-actions");

    appendIconActionIfAllowed(actions, service, {
        required: "write",
        icon: "fas fa-chart-line",
        label: "Add SLI",
        onClick: function () {
            openServiceSliModal(service, null);
        },
    });

    appendIconActionIfAllowed(actions, service, {
        required: "write",
        icon: "fas fa-bullseye",
        label: "Add SLO",
        onClick: function () {
            openServiceSloModal(service, null, slis);
        },
    });

    section.append(actions);

    if (!slis.length && !slos.length) {
        section.append(
            $("<div>")
                .addClass("empty-state compact")
                .text("No SLI/SLO configured for this service.")
        );

        return section;
    }

    section.append(renderServiceSlisTable(service, slis));
    section.append(renderServiceSlosTable(service, slos, slis));

    return section;
}


function renderServiceSlisTable(service, slis) {
    if (!slis.length) {
        return serviceDetailsTableCard("SLIs", ["Name", "Type", "Source", "Scope"], [], "No SLIs configured.");
    }

    const table = $("<table>").addClass("data-table");
    const tbody = $("<tbody>");

    table.append(
        $("<thead>").append(
            $("<tr>")
                .append($("<th>").text("SLI"))
                .append($("<th>").text("Type"))
                .append($("<th>").text("Source"))
                .append($("<th>").text("Scope"))
                .append($("<th>").addClass("actions-th").text("Actions"))
        )
    );

    slis.forEach(function (sli) {
        tbody.append(
            $("<tr>").toggleClass("row-disabled", !sli.enabled)
                .append(
                    $("<td>")
                        .addClass("table-cell-truncate")
                        .append($("<strong>").text(sli.name || ("SLI #" + sli.id)))
                        .append($("<div>").addClass("row-subtitle").text(sli.slug || sli.description || "-"))
                )
                .append($("<td>").text(formatServiceSliType(sli.sli_type)))
                .append($("<td>").text(formatServiceSliSource(sli.source)))
                .append($("<td>").text(formatServiceSliScope(sli)))
                .append($("<td>").addClass("actions-cell").append(renderServiceSliActions(service, sli)))
        );
    });

    table.append(tbody);

    return $("<div>").addClass("table-wrapper").append(table);
}


function renderServiceSlosTable(service, slos, slis) {
    if (!slos.length) {
        return serviceDetailsTableCard("SLOs", ["Name", "SLI", "Target", "Current", "Status"], [], "No SLOs configured.");
    }

    const table = $("<table>").addClass("data-table");
    const tbody = $("<tbody>");

    table.append(
        $("<thead>").append(
            $("<tr>")
                .append($("<th>").text("SLO"))
                .append($("<th>").text("SLI"))
                .append($("<th>").text("Target"))
                .append($("<th>").text("Current"))
                .append($("<th>").text("Status"))
                .append($("<th>").addClass("actions-th").text("Actions"))
        )
    );

    slos.forEach(function (slo) {
        tbody.append(renderServiceSloRow(service, slo, slis));
    });

    table.append(tbody);

    return $("<div>").addClass("table-wrapper").append(table);
}


function renderServiceSloRow(service, slo, slis) {
    const evaluation = slo.evaluation || {};

    return $("<tr>").toggleClass("row-disabled", !slo.enabled)
        .append(
            $("<td>")
                .addClass("table-cell-truncate")
                .append($("<strong>").text(slo.name || ("SLO #" + slo.id)))
                .append($("<div>").addClass("row-subtitle").text((slo.window_days || 30) + " day window"))
        )
        .append($("<td>").text(slo.sli_name || formatServiceSliType(slo.sli_type)))
        .append($("<td>").append(renderServiceSloTarget(slo)))
        .append($("<td>").append(renderServiceSloCurrent(evaluation, slo.sli_type)))
        .append($("<td>").append(renderServiceSloStatusBadge(evaluation.status, slo.enabled)))
        .append($("<td>").addClass("actions-cell").append(renderServiceSloActions(service, slo, slis)));
}


function renderServiceSliActions(service, sli) {
    if (typeof window.makeActionMenu === "function") {
        return window.makeActionMenu({
            object: service,
            items: [
                {
                    label: "Edit",
                    icon: "fas fa-edit",
                    required: "write",
                    onClick: function () { openServiceSliModal(service, sli); },
                },
                {
                    label: "Delete",
                    icon: "fas fa-trash",
                    required: "write",
                    danger: true,
                    onClick: function () { deleteServiceSli(service, sli); },
                },
            ],
        });
    }

    const wrapper = $("<div>").addClass("action-buttons");
    appendIconActionIfAllowed(wrapper, service, {required: "write", icon: "fas fa-edit", label: "Edit", onClick: function () { openServiceSliModal(service, sli); }});
    appendIconActionIfAllowed(wrapper, service, {required: "write", icon: "fas fa-trash", label: "Delete", danger: true, onClick: function () { deleteServiceSli(service, sli); }});
    return wrapper;
}


function renderServiceSloActions(service, slo, slis) {
    if (typeof window.makeActionMenu === "function") {
        return window.makeActionMenu({
            object: service,
            items: [
                {
                    label: "Edit",
                    icon: "fas fa-edit",
                    required: "write",
                    onClick: function () { openServiceSloModal(service, slo, slis); },
                },
                {
                    label: "Delete",
                    icon: "fas fa-trash",
                    required: "write",
                    danger: true,
                    onClick: function () { deleteServiceSlo(service, slo); },
                },
            ],
        });
    }

    const wrapper = $("<div>").addClass("action-buttons");
    appendIconActionIfAllowed(wrapper, service, {required: "write", icon: "fas fa-edit", label: "Edit", onClick: function () { openServiceSloModal(service, slo, slis); }});
    appendIconActionIfAllowed(wrapper, service, {required: "write", icon: "fas fa-trash", label: "Delete", danger: true, onClick: function () { deleteServiceSlo(service, slo); }});
    return wrapper;
}


function renderServiceSloTarget(slo) {
    const wrapper = $("<div>").addClass("compact-list");

    if (slo.target_percent_basis_points !== null && slo.target_percent_basis_points !== undefined) {
        wrapper.append($("<div>").addClass("compact-list-item").text("Target ≥ " + formatBasisPoints(slo.target_percent_basis_points)));
    }

    if (slo.threshold_seconds) {
        wrapper.append($("<div>").addClass("compact-list-item").text("Threshold ≤ " + formatDurationSeconds(slo.threshold_seconds)));
    }

    if (slo.threshold_count !== null && slo.threshold_count !== undefined) {
        wrapper.append($("<div>").addClass("compact-list-item").text("Max incidents ≤ " + slo.threshold_count));
    }

    if (slo.exclude_maintenance) {
        wrapper.append($("<div>").addClass("compact-list-item").text("Maintenance excluded"));
    }

    if (!wrapper.children().length) {
        wrapper.text("-");
    }

    return wrapper;
}


function renderServiceSloCurrent(evaluation, sliType) {
    const wrapper = $("<div>").addClass("compact-list");

    if (sliType === "incident_availability") {
        return renderServiceSloAvailabilityCurrent(evaluation);
    }

    if (sliType === "incident_count") {
        return renderServiceSloIncidentCountCurrent(evaluation);
    }

    if (evaluation.value_percent !== null && evaluation.value_percent !== undefined) {
        wrapper.append(serviceSloMetricLine("Current compliance", evaluation.value_percent + "%"));
    }

    if (evaluation.good_count !== undefined && evaluation.total_count !== undefined && Number(evaluation.total_count || 0) > 0) {
        wrapper.append(serviceSloMetricLine("Good alert groups", Number(evaluation.good_count || 0)));
        wrapper.append(serviceSloMetricLine("Total alert groups", Number(evaluation.total_count || 0)));
    }

    if (evaluation.bad_count !== undefined && Number(evaluation.bad_count || 0) > 0) {
        wrapper.append(serviceSloMetricLine("Breached alert groups", Number(evaluation.bad_count || 0)));
    }

    if (evaluation.pending_count !== undefined && Number(evaluation.pending_count || 0) > 0) {
        wrapper.append(serviceSloMetricLine("Pending alert groups", Number(evaluation.pending_count || 0)));
    }

    if (evaluation.message) {
        wrapper.append($("<div>").addClass("compact-list-meta").text(evaluation.message));
    }

    if (!wrapper.children().length) {
        wrapper.text("No data");
    }

    return wrapper;
}


function renderServiceSloAvailabilityCurrent(evaluation) {
    const wrapper = $("<div>").addClass("compact-list");
    const goodSeconds = Number(evaluation.good_count || 0);
    const totalSeconds = Number(evaluation.total_count || 0);
    const downtimeSeconds = Number(evaluation.downtime_seconds || evaluation.bad_count || 0);

    if (evaluation.value_percent !== null && evaluation.value_percent !== undefined) {
        wrapper.append(serviceSloMetricLine("Current availability", evaluation.value_percent + "%"));
    }

    if (totalSeconds > 0) {
        wrapper.append(serviceSloMetricLine("Good time", formatDurationSeconds(goodSeconds, {maxParts: 3})));
        wrapper.append(serviceSloMetricLine("Total window", formatDurationSeconds(totalSeconds, {maxParts: 3})));
    }

    wrapper.append(serviceSloMetricLine("Downtime", formatDurationSeconds(downtimeSeconds, {maxParts: 3})));

    if (evaluation.message) {
        wrapper.append($("<div>").addClass("compact-list-meta").text(evaluation.message));
    }

    if (!wrapper.children().length) {
        wrapper.text("No data");
    }

    return wrapper;
}


function renderServiceSloIncidentCountCurrent(evaluation) {
    const wrapper = $("<div>").addClass("compact-list");

    if (evaluation.value_count !== null && evaluation.value_count !== undefined) {
        wrapper.append(serviceSloMetricLine("Impact incidents", Number(evaluation.value_count || 0)));
    } else if (evaluation.bad_count !== undefined) {
        wrapper.append(serviceSloMetricLine("Impact incidents", Number(evaluation.bad_count || 0)));
    }

    if (evaluation.total_count !== undefined && Number(evaluation.total_count || 0) > 0) {
        wrapper.append(serviceSloMetricLine("Total matching alert groups", Number(evaluation.total_count || 0)));
    }

    if (evaluation.message) {
        wrapper.append($("<div>").addClass("compact-list-meta").text(evaluation.message));
    }

    if (!wrapper.children().length) {
        wrapper.text("No data");
    }

    return wrapper;
}


function serviceSloMetricLine(label, value) {
    return $("<div>")
        .addClass("compact-list-item")
        .append($("<strong>").text(label + ": "))
        .append(document.createTextNode(value));
}


function renderServiceSloStatusBadge(status, enabled) {
    if (!enabled) {
        return $("<span>").addClass("status-pill status-neutral").text("Disabled");
    }

    if (status === "met") {
        return $("<span>").addClass("status-pill status-active").text("Met");
    }

    if (status === "at_risk") {
        return $("<span>").addClass("status-pill status-scheduled").text("At risk");
    }

    if (status === "breached") {
        return $("<span>").addClass("status-pill status-inactive").text("Breached");
    }

    return $("<span>").addClass("status-pill status-neutral").text("No data");
}


const SERVICE_SLI_IMPACT_TYPES = ["incident_availability", "incident_count"];
const SERVICE_SLI_PRIORITY_OPTIONS = [
    ["p1", "P1"],
    ["p2", "P2"],
    ["p3", "P3"],
    ["p4", "P4"],
];


function isImpactServiceSliType(type) {
    return SERVICE_SLI_IMPACT_TYPES.indexOf(type) !== -1;
}


function serviceSliPriorityScope(sli) {
    const configuration = sli && sli.configuration ? sli.configuration : {};
    let scope = configuration.priority_scope || null;

    if (!scope && sli && sli.priority) {
        scope = [sli.priority];
    }

    if (!scope && sli && isImpactServiceSliType(sli.sli_type)) {
        scope = ["p1", "p2"];
    }

    if (typeof scope === "string") {
        scope = [scope];
    }

    if (!Array.isArray(scope)) {
        return [];
    }

    return scope.map(function (value) {
        return String(value || "").toLowerCase();
    }).filter(function (value, index, values) {
        return ["p1", "p2", "p3", "p4"].indexOf(value) !== -1 && values.indexOf(value) === index;
    });
}


function formatServiceSliType(type) {
    const labels = {
        alert_ack_latency: "Ack latency",
        alert_resolve_latency: "Resolve latency",
        incident_availability: "Incident availability",
        incident_count: "Incident count",
    };

    return labels[type] || type || "-";
}


function formatServiceSliSource(source) {
    const labels = {
        incidentrelay_alert_groups: "Alert groups",
        incidentrelay_service_status: "Service status",
    };

    return labels[source] || source || "-";
}


function formatServiceSliScope(sli) {
    const parts = [];
    const priorityScope = serviceSliPriorityScope(sli);

    if (priorityScope.length) {
        parts.push("priority: " + priorityScope.map(function (value) {
            return value.toUpperCase();
        }).join(", "));
    }

    if (sli.severity) {
        parts.push("severity: " + sli.severity);
    }

    return parts.length ? parts.join(" / ") : "all matching alert groups";
}


function formatBasisPoints(value) {
    if (value === null || value === undefined) {
        return "-";
    }

    return (Number(value) / 100).toFixed(Number(value) % 100 === 0 ? 0 : 2) + "%";
}


function formatDurationSeconds(value, options) {
    options = options || {};

    const numericValue = Number(value || 0);
    let seconds = Math.floor(Math.abs(numericValue));
    const maxParts = options.maxParts || 2;
    const parts = [];
    const units = [
        ["d", 86400],
        ["h", 3600],
        ["m", 60],
        ["s", 1],
    ];

    if (!seconds) {
        return "0s";
    }

    units.forEach(function (unit) {
        const label = unit[0];
        const unitSeconds = unit[1];
        const amount = Math.floor(seconds / unitSeconds);

        if (amount > 0 && parts.length < maxParts) {
            parts.push(amount + label);
        }

        seconds %= unitSeconds;
    });

    return parts.join(" ");
}


function secondsToMinutes(value) {
    return value ? Math.round(Number(value) / 60) : "";
}


function minutesToSeconds(value) {
    const minutes = Number(value || 0);
    return minutes > 0 ? minutes * 60 : null;
}


function basisPointsToPercent(value) {
    return value !== null && value !== undefined ? Number(value) / 100 : "";
}


function percentToBasisPoints(value) {
    if (value === null || value === undefined || value === "") {
        return null;
    }

    return Math.round(Number(value) * 100);
}


function simpleSlug(value) {
    if (window.AppSlug && typeof window.AppSlug.slugify === "function") {
        return window.AppSlug.slugify(value);
    }

    return String(value || "")
        .toLowerCase()
        .trim()
        .replace(/['"`]/g, "")
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "")
        .replace(/-{2,}/g, "-");
}


function openServiceSliModal(service, sli) {
    $("#service-sli-modal").remove();
    $("body").append(renderServiceSliModal(service, sli));
    openAppModal("#service-sli-modal");

    if (!sli && window.AppSlug) {
        window.AppSlug.bind("#service-sli-name", "#service-sli-slug", {manualWhenHasValue: true});
    }
}


function renderServiceSliModal(service, sli) {
    sli = sli || {
        slug: "",
        name: "",
        description: "",
        sli_type: "alert_ack_latency",
        source: "incidentrelay_alert_groups",
        severity: "critical",
        priority: "",
        enabled: true,
    };

    return $("<div>")
        .attr("id", "service-sli-modal")
        .addClass("app-modal")
        .hide()
        .append(
            $("<div>")
                .addClass("app-modal-dialog app-modal-dialog-wide")
                .append(
                    $("<div>")
                        .addClass("app-modal-header")
                        .append(
                            $("<div>")
                                .append($("<h2>").text(sli.id ? "Edit SLI" : "New SLI"))
                                .append($("<div>").addClass("card-subtitle").text(service.name || service.slug || "Service"))
                        )
                        .append($("<button>").attr("type", "button").addClass("app-modal-close").attr("aria-label", "Close").text("×").on("click", function () { closeAppModal("#service-sli-modal"); }))
                )
                .append($("<div>").addClass("app-modal-body").append(renderServiceSliForm(service, sli)))
        );
}


function renderServiceSliForm(service, sli) {
    const body = $("<div>").addClass("form-body");

    body.append($("<input>").attr("type", "hidden").attr("id", "service-sli-service-id").val(service.id));
    body.append($("<input>").attr("type", "hidden").attr("id", "service-sli-id").val(sli.id || ""));

    body.append($("<label>").attr("for", "service-sli-name").text("SLI name"));
    body.append($("<input>").attr("id", "service-sli-name").attr("type", "text").addClass("input").attr("placeholder", "Critical alert acknowledgement latency").val(sli.name || "").on("input", function () {
        if (!$("#service-sli-slug").data("slug-manual")) {
            $("#service-sli-slug").val(simpleSlug($(this).val()));
        }
    }));

    body.append($("<label>").attr("for", "service-sli-slug").text("Slug"));
    body.append($("<input>").attr("id", "service-sli-slug").attr("type", "text").addClass("input").val(sli.slug || "").on("input", function () { $(this).data("slug-manual", true); }));

    body.append($("<label>").attr("for", "service-sli-description").text("Description"));
    body.append($("<textarea>").attr("id", "service-sli-description").attr("rows", 3).addClass("input").val(sli.description || ""));

    body.append($("<label>").attr("for", "service-sli-type").text("SLI type"));
    body.append(
        $("<select>").attr("id", "service-sli-type").addClass("input")
            .append($("<option>").val("alert_ack_latency").text("Alert acknowledgement latency"))
            .append($("<option>").val("alert_resolve_latency").text("Alert resolution latency"))
            .append($("<option>").val("incident_availability").text("Incident-based availability"))
            .append($("<option>").val("incident_count").text("Impact incident count"))
            .val(sli.sli_type || "alert_ack_latency")
            .on("change", updateServiceSliScopeVisibility)
    );

    body.append(
        $("<div>")
            .attr("id", "service-sli-severity-field")
            .append($("<label>").attr("for", "service-sli-severity").text("Severity scope"))
            .append(
                $("<select>").attr("id", "service-sli-severity").addClass("input")
                    .append($("<option>").val("").text("All severities"))
                    .append($("<option>").val("critical").text("Critical"))
                    .append($("<option>").val("high").text("High"))
                    .append($("<option>").val("warning").text("Warning"))
                    .append($("<option>").val("info").text("Info"))
                    .val(sli.severity || "")
            )
    );

    body.append(renderServiceSliPriorityScopeField(sli));

    body.append($("<label>").addClass("md-checkbox").append($("<input>").attr("id", "service-sli-enabled").attr("type", "checkbox").prop("checked", sli.enabled !== false)).append($("<span>").text("Enabled")));

    updateServiceSliScopeVisibility(body);

    body.append(
        $("<div>").addClass("form-actions")
            .append($("<button>").attr("type", "button").addClass("btn").text("Cancel").on("click", function () { closeAppModal("#service-sli-modal"); }))
            .append($("<button>").attr("type", "button").addClass("btn btn-primary").text("Save SLI").on("click", saveServiceSli))
    );

    return body;
}


function renderServiceSliPriorityScopeField(sli) {
    const wrapper = $("<div>").attr("id", "service-sli-priority-field");
    const selected = serviceSliPriorityScope(sli);

    wrapper.append($("<label>").text("Priority scope"));
    wrapper.append(
        $("<div>").addClass("form-grid-3").append(
            SERVICE_SLI_PRIORITY_OPTIONS.map(function (option) {
                return $("<label>")
                    .addClass("md-checkbox")
                    .append(
                        $("<input>")
                            .attr("type", "checkbox")
                            .attr("name", "service-sli-priority-scope")
                            .val(option[0])
                            .prop("checked", selected.indexOf(option[0]) !== -1)
                    )
                    .append($("<span>").text(option[1]));
            })
        )
    );

    wrapper.append(
        $("<div>")
            .addClass("row-subtitle")
            .text("Incident availability and incident count are calculated from impact priorities. Default: P1/P2.")
    );

    return wrapper;
}


function checkedInputValues(name) {
    return $("input[name='" + name + "']:checked").map(function () {
        return $(this).val();
    }).get();
}


function updateServiceSliScopeVisibility() {
    const type = $("#service-sli-type").val();
    const impact = isImpactServiceSliType(type);

    $("#service-sli-severity-field").toggle(!impact);
    $("#service-sli-priority-field").show();

    if (impact && !checkedInputValues("service-sli-priority-scope").length) {
        $("input[name='service-sli-priority-scope'][value='p1']").prop("checked", true);
        $("input[name='service-sli-priority-scope'][value='p2']").prop("checked", true);
    }
}


function collectServiceSliPayload() {
    const type = $("#service-sli-type").val();
    const priorityScope = checkedInputValues("service-sli-priority-scope");
    const impact = isImpactServiceSliType(type);
    const configuration = {};

    if (priorityScope.length) {
        configuration.priority_scope = priorityScope;
    } else if (impact) {
        configuration.priority_scope = ["p1", "p2"];
    }

    return {
        slug: $("#service-sli-slug").val().trim() || simpleSlug($("#service-sli-name").val()),
        name: $("#service-sli-name").val().trim(),
        description: $("#service-sli-description").val().trim() || null,
        sli_type: type,
        source: "incidentrelay_alert_groups",
        configuration: configuration,
        severity: impact ? null : ($("#service-sli-severity").val() || null),
        priority: configuration.priority_scope && configuration.priority_scope.length === 1
            ? configuration.priority_scope[0]
            : null,
        enabled: $("#service-sli-enabled").is(":checked"),
    };
}


function saveServiceSli() {
    const serviceId = Number($("#service-sli-service-id").val());
    const sliId = $("#service-sli-id").val();
    const payload = collectServiceSliPayload();

    if (!serviceId || !payload.name || !payload.slug) {
        showAppError("SLI name and slug are required.");
        return;
    }

    if (sliId) {
        apiPut("/api/services/slis/" + encodeURIComponent(sliId), payload, function () {
            closeAppModal("#service-sli-modal");
            refreshServiceContextAfterDetailsChange();
        });
        return;
    }

    apiPost("/api/services/" + encodeURIComponent(serviceId) + "/slis", payload, function () {
        closeAppModal("#service-sli-modal");
        refreshServiceContextAfterDetailsChange();
    });
}


function deleteServiceSli(service, sli) {
    showAppConfirm({
        title: "Delete this SLI?",
        message: "Delete SLI \"" + (sli.name || sli.id) + "\"? SLOs attached to it will be deleted by the database.",
        confirmText: "Delete",
        confirmClass: "btn-danger",
    }).done(function () {
        apiDelete("/api/services/slis/" + encodeURIComponent(sli.id), function () {
            refreshServiceContextAfterDetailsChange();
        });
    });
}


function openServiceSloModal(service, slo, slis) {
    slis = asArray(slis);

    if (!slis.length) {
        showAppError("Create an SLI first, then add an SLO for it.");
        return;
    }

    $("#service-slo-modal").remove();
    $("body").append(renderServiceSloModal(service, slo, slis));
    openAppModal("#service-slo-modal");
    updateServiceSloFormForSli();
}


function renderServiceSloModal(service, slo, slis) {
    slo = slo || {
        sli_id: slis[0].id,
        name: "",
        description: "",
        comparison: "percent_good_gte",
        target_percent_basis_points: 9500,
        threshold_seconds: 15 * 60,
        threshold_count: null,
        window_days: 30,
        exclude_maintenance: true,
        include_open_alerts: true,
        enabled: true,
    };

    return $("<div>")
        .attr("id", "service-slo-modal")
        .addClass("app-modal")
        .hide()
        .append(
            $("<div>")
                .addClass("app-modal-dialog app-modal-dialog-wide")
                .append(
                    $("<div>")
                        .addClass("app-modal-header")
                        .append(
                            $("<div>")
                                .append($("<h2>").text(slo.id ? "Edit SLO" : "New SLO"))
                                .append($("<div>").addClass("card-subtitle").text(service.name || service.slug || "Service"))
                        )
                        .append($("<button>").attr("type", "button").addClass("app-modal-close").attr("aria-label", "Close").text("×").on("click", function () { closeAppModal("#service-slo-modal"); }))
                )
                .append($("<div>").addClass("app-modal-body").append(renderServiceSloForm(service, slo, slis)))
        );
}


function renderServiceSloForm(service, slo, slis) {
    const body = $("<div>").addClass("form-body");

    body.append($("<input>").attr("type", "hidden").attr("id", "service-slo-service-id").val(service.id));
    body.append($("<input>").attr("type", "hidden").attr("id", "service-slo-id").val(slo.id || ""));

    body.append($("<label>").attr("for", "service-slo-sli").text("SLI"));
    const sliSelect = $("<select>").attr("id", "service-slo-sli").addClass("input").on("change", updateServiceSloFormForSli);
    slis.forEach(function (sli) {
        sliSelect.append($("<option>").val(sli.id).attr("data-sli-type", sli.sli_type).text((sli.name || sli.slug) + " · " + formatServiceSliType(sli.sli_type)));
    });
    sliSelect.val(slo.sli_id || (slis[0] && slis[0].id));
    body.append(sliSelect);

    body.append($("<label>").attr("for", "service-slo-name").text("SLO name"));
    body.append($("<input>").attr("id", "service-slo-name").attr("type", "text").addClass("input").attr("placeholder", "95% critical alerts acknowledged within 15 minutes").val(slo.name || ""));

    body.append($("<label>").attr("for", "service-slo-description").text("Description"));
    body.append($("<textarea>").attr("id", "service-slo-description").attr("rows", 3).addClass("input").val(slo.description || ""));

    body.append($("<div>").addClass("card-subtitle").text("Targets and evaluation window"));

    body.append($("<div>").addClass("form-grid-3")
        .append(renderServiceSloNumberField("service-slo-window-days", "Window, days", slo.window_days || 30, "30"))
        .append(renderServiceSloNumberField("service-slo-target-percent", "Target, %", basisPointsToPercent(slo.target_percent_basis_points), "95", "0.01"))
        .append(renderServiceSloNumberField("service-slo-threshold-minutes", "Threshold, minutes", secondsToMinutes(slo.threshold_seconds), "15"))
    );

    body.append($("<div>").addClass("form-grid-3")
        .append(renderServiceSloNumberField("service-slo-threshold-count", "Max incidents", slo.threshold_count, "3"))
        .append($("<div>").addClass("form-field").append($("<label>").text("Comparison")).append($("<input>").attr("id", "service-slo-comparison-label").addClass("input").prop("disabled", true)))
    );

    body.append($("<label>").addClass("md-checkbox").append($("<input>").attr("id", "service-slo-exclude-maintenance").attr("type", "checkbox").prop("checked", slo.exclude_maintenance !== false)).append($("<span>").text("Exclude maintenance from availability calculations")));
    body.append($("<label>").addClass("md-checkbox").append($("<input>").attr("id", "service-slo-include-open-alerts").attr("type", "checkbox").prop("checked", slo.include_open_alerts !== false)).append($("<span>").text("Track open alerts as pending/breached")));
    body.append($("<label>").addClass("md-checkbox").append($("<input>").attr("id", "service-slo-enabled").attr("type", "checkbox").prop("checked", slo.enabled !== false)).append($("<span>").text("Enabled")));

    body.append(
        $("<div>").addClass("form-actions")
            .append($("<button>").attr("type", "button").addClass("btn").text("Cancel").on("click", function () { closeAppModal("#service-slo-modal"); }))
            .append($("<button>").attr("type", "button").addClass("btn btn-primary").text("Save SLO").on("click", saveServiceSlo))
    );

    return body;
}


function renderServiceSloNumberField(id, label, value, placeholder, step) {
    return $("<div>")
        .addClass("form-field")
        .append($("<label>").attr("for", id).text(label))
        .append($("<input>").attr("id", id).attr("type", "number").attr("min", 0).attr("step", step || "1").addClass("input").attr("placeholder", placeholder || "").val(value === null || value === undefined ? "" : value));
}


function selectedServiceSloSliType() {
    return $("#service-slo-sli option:selected").attr("data-sli-type") || "alert_ack_latency";
}


function updateServiceSloFormForSli() {
    const type = selectedServiceSloSliType();
    const latency = type === "alert_ack_latency" || type === "alert_resolve_latency";
    const availability = type === "incident_availability";
    const count = type === "incident_count";

    $("#service-slo-target-percent").closest(".form-field").toggle(latency || availability);
    $("#service-slo-threshold-minutes").closest(".form-field").toggle(latency);
    $("#service-slo-threshold-count").closest(".form-field").toggle(count);
    $("#service-slo-exclude-maintenance").closest("label").toggle(availability);
    $("#service-slo-comparison-label").val(count ? "value_lte" : "percent_good_gte");
}


function collectServiceSloPayload() {
    const type = selectedServiceSloSliType();
    const count = type === "incident_count";

    return {
        sli_id: Number($("#service-slo-sli").val()),
        name: $("#service-slo-name").val().trim(),
        description: $("#service-slo-description").val().trim() || null,
        comparison: count ? "value_lte" : "percent_good_gte",
        target_percent_basis_points: count ? null : percentToBasisPoints($("#service-slo-target-percent").val()),
        threshold_seconds: (type === "alert_ack_latency" || type === "alert_resolve_latency") ? minutesToSeconds($("#service-slo-threshold-minutes").val()) : null,
        threshold_count: count ? Number($("#service-slo-threshold-count").val() || 0) : null,
        window_days: Number($("#service-slo-window-days").val() || 30),
        exclude_maintenance: $("#service-slo-exclude-maintenance").is(":checked"),
        include_open_alerts: $("#service-slo-include-open-alerts").is(":checked"),
        enabled: $("#service-slo-enabled").is(":checked"),
    };
}


function saveServiceSlo() {
    const serviceId = Number($("#service-slo-service-id").val());
    const sloId = $("#service-slo-id").val();
    const payload = collectServiceSloPayload();
    const type = selectedServiceSloSliType();

    if (!serviceId || !payload.name || !payload.sli_id) {
        showAppError("SLO name and SLI are required.");
        return;
    }

    if (type === "incident_count" && payload.threshold_count === null) {
        showAppError("Incident count SLO requires Max incidents.");
        return;
    }

    if (type !== "incident_count" && payload.target_percent_basis_points === null) {
        showAppError("SLO target percent is required.");
        return;
    }

    if ((type === "alert_ack_latency" || type === "alert_resolve_latency") && !payload.threshold_seconds) {
        showAppError("Latency SLO requires threshold minutes.");
        return;
    }

    if (sloId) {
        apiPut("/api/services/slos/" + encodeURIComponent(sloId), payload, function () {
            closeAppModal("#service-slo-modal");
            refreshServiceContextAfterDetailsChange();
        });
        return;
    }

    apiPost("/api/services/" + encodeURIComponent(serviceId) + "/slos", payload, function () {
        closeAppModal("#service-slo-modal");
        refreshServiceContextAfterDetailsChange();
    });
}


function deleteServiceSlo(service, slo) {
    showAppConfirm({
        title: "Delete this SLO?",
        message: "Delete SLO \"" + (slo.name || slo.id) + "\"?",
        confirmText: "Delete",
        confirmClass: "btn-danger",
    }).done(function () {
        apiDelete("/api/services/slos/" + encodeURIComponent(slo.id), function () {
            refreshServiceContextAfterDetailsChange();
        });
    });
}

function renderServiceDetailsImpact(payload) {
    const impact = payload.impact || {};
    const blastRadius = impact.blast_radius || {};
    const section = serviceDetailsSection(
        "Impact",
        "Effective status, root cause and downstream blast radius."
    );

    section.append(
        $("<div>")
            .addClass("grid-two")
            .append(
                serviceDetailsCompactCard("Status", [
                    ["Effective status", formatImpactStatusText(impact.effective_status || "unknown")],
                    ["Primary reason", formatImpactReasonText(impact.primary_reason || "unknown")],
                    ["Alert impact", formatImpactStatusText(impact.alert_impact_status || "operational")],
                    ["Open alert groups", Number(impact.open_alert_groups || 0)],
                    ["Critical open", Number(impact.critical_open_alert_groups || 0)],
                    ["Dependency impact", formatImpactStatusText(impact.dependency_impact_status || "operational")],
                    ["Upstream issues", Number(impact.upstream_issues_count || 0)],
                ])
            )
            .append(
                serviceDetailsCompactCard("Blast radius", [
                    ["Direct downstream", Number(blastRadius.direct_downstream || 0)],
                    ["Total downstream", Number(blastRadius.transitive_downstream || 0)],
                    ["Critical downstream", Number(blastRadius.critical_downstream || 0)],
                    ["Tier 1 downstream", Number(blastRadius.tier_1_downstream || 0)],
                    ["Cycle detected", blastRadius.cycle_detected ? "Yes" : "No"],
                    ["Depth limited", blastRadius.depth_limited ? "Yes" : "No"],
                ])
            )
    );

    section.append(renderImpactExplanationPanel(impact, { compact: true }));

    return section;
}

function renderServiceDetailsReadiness(payload) {
    const service = payload.service || {};
    const readiness = payload.readiness || {};
    const state = readiness.state || null;
    const evaluations = asArray(readiness.evaluations);
    const section = serviceDetailsSection(i18n.t("service_standards.readiness.title"), null);

    const headerActions = $("<div>").addClass("details-actions");

    appendIconActionIfAllowed(headerActions, service, {
        required: "write",
        icon: "fas fa-sync",
        label: i18n.t("service_standards.actions.evaluate"),
        onClick: function () {
            evaluateServiceReadiness(service);
        },
    });

    section.append(headerActions);

    if (!state) {
        section.append(
            $("<div>")
                .addClass("empty-state compact")
                .text(i18n.t("service_standards.readiness.not_evaluated"))
        );

        return section;
    }

    const scoreLabel = state.status !== "not_applicable" ? state.score + "/100" : "—";

    section.append(renderReadinessSummaryTable(state, scoreLabel));

    if (!evaluations.length) {
        section.append(
            $("<div>")
                .addClass("empty-state compact")
                .text(i18n.t("service_standards.readiness.no_standards"))
        );

        return section;
    }

    section.append(renderReadinessStandardsTable(evaluations));

    return section;
}

function renderReadinessSummaryTable(state, scoreLabel) {
    const table = $("<table>").addClass("data-table");
    const tbody = $("<tbody>");

    tbody.append(
        $("<tr>")
            .append($("<th>").text(i18n.t("service_standards.readiness.score")))
            .append($("<td>").text(scoreLabel + " · " + serviceStandardReadinessStatus(state.status)))
            .append($("<th>").text(i18n.t("service_standards.readiness.standards")))
            .append($("<td>").text(Number(state.standards_count || 0)))
    );

    tbody.append(
        $("<tr>")
            .append($("<th>").text(i18n.t("service_standards.readiness.checks")))
            .append($("<td>").text(Number(state.checks_count || 0)))
            .append($("<th>").text(i18n.t("service_standards.readiness.failed")))
            .append(
                $("<td>").text(
                    i18n.t("service_standards.readiness.failed_breakdown", {
                        total: Number(state.failed_count || 0),
                        required: Number(state.failed_required_count || 0),
                        critical: Number(state.failed_critical_count || 0),
                    })
                )
            )
    );

    table.append(tbody);

    return $("<div>").addClass("table-wrapper").append(table);
}


function renderReadinessStandardsTable(evaluations) {
    const table = $("<table>").addClass("data-table");
    const tbody = $("<tbody>");

    table.append(
        $("<thead>").append(
            $("<tr>")
                .append($("<th>").text(i18n.t("service_standards.table.standard")))
                .append($("<th>").text(i18n.t("service_standards.readiness.score")))
                .append($("<th>").text(i18n.t("service_standards.table.status")))
                .append($("<th>").text(i18n.t("service_standards.readiness.failed_checks")))
        )
    );

    evaluations.forEach(function (evaluation) {
        const standard = evaluation.standard || {};
        const results = asArray(evaluation.results);
        const failed = results.filter(function (result) {
            return result.status !== "passed";
        });

        tbody.append(
            $("<tr>")
                .append(
                    $("<td>")
                        .addClass("table-cell-truncate-wide")
                        .append($("<strong>").text(serviceStandardDisplayName(standard)))
                        .append($("<div>").addClass("row-subtitle").text(standard.slug || "-"))
                )
                .append($("<td>").text(evaluation.score + "/100"))
                .append($("<td>").append($("<span>").addClass(getReadinessStatusClass(evaluation.status)).text(serviceStandardReadinessStatus(evaluation.status))))
                .append($("<td>").append(renderReadinessFailedChecks(failed)))
        );
    });

    table.append(tbody);

    return $("<div>").addClass("table-wrapper").append(table);
}


function renderReadinessFailedChecks(failed) {
    const wrapper = $("<div>").addClass("compact-list");

    if (!failed.length) {
        return $("<span>").text("-");
    }

    failed.slice(0, 4).forEach(function (result) {
        wrapper.append(
            $("<div>")
                .addClass("compact-list-item")
                .append(
                    $("<div>")
                        .addClass("compact-list-title")
                        .text(serviceStandardCheckDisplayName(result))
                )
                .append(
                    $("<div>")
                        .addClass("compact-list-meta")
                        .text(
                            translateServiceReadinessMessage(result) +
                            " / " +
                            i18n.t("service_standards.readiness.points", {weight: Number(result.weight || 0)})
                        )
                )
        );
    });

    if (failed.length > 4) {
        wrapper.append(
            $("<div>")
                .addClass("compact-list-meta")
                .text(i18n.t("service_standards.readiness.more", {count: failed.length - 4}))
        );
    }

    return wrapper;
}

function serviceStandardDisplayName(standard) {
    standard = standard || {};

    if (standard.slug === "basic-operational-readiness") {
        return i18n.t("service_standards.builtin.standard.basic");
    }

    return standard.name || standard.slug || i18n.t("service_standards.readiness.standard_fallback");
}

function serviceStandardCheckDisplayName(result) {
    result = result || {};
    const builtin = {
        owner: "service_standards.builtin.check.owner",
        "escalation-policy": "service_standards.builtin.check.escalation_policy",
        "notification-policy": "service_standards.builtin.check.notification_policy",
        "alert-route": "service_standards.builtin.check.alert_route",
        runbook: "service_standards.builtin.check.runbook",
        "dependency-cycle": "service_standards.builtin.check.dependency_cycle",
    };

    if (Object.prototype.hasOwnProperty.call(builtin, result.check_slug)) {
        return i18n.t(builtin[result.check_slug]);
    }

    return result.check_name ||
        result.check_slug ||
        translateServiceStandardCheckType(result.check_type) ||
        i18n.t("service_standards.readiness.check_fallback");
}

function serviceStandardReadinessStatus(status) {
    const normalized = String(status || "not_applicable");

    return i18n.t(
        "service_standards.readiness.status." + normalized,
        {},
        normalized.replace(/_/g, " ")
    );
}

function translateServiceStandardCheckType(checkType) {
    const key = String(checkType || "");
    const supported = [
        "field_present",
        "field_equals",
        "owner_exists",
        "active_rotation_exists",
        "escalation_policy_exists",
        "notification_policy_exists",
        "service_channel_exists",
        "route_exists",
        "match_rule_exists",
        "runbook_exists",
        "link_type_exists",
        "dependency_exists",
        "dependency_cycle_absent",
        "metadata_value",
    ];

    return supported.indexOf(key) !== -1
        ? i18n.t("service_standards.check_type." + key)
        : key;
}

function translateServiceReadinessMessage(result) {
    result = result || {};
    const message = String(result.message || "");
    const details = result.details || {};

    if (result.check_type === "owner_exists") {
        return result.status === "passed"
            ? i18n.t("service_standards.result.owner_passed", {count: Number(details.count || 0)})
            : i18n.t("service_standards.result.owner_failed", {minimum: Number(details.minimum || 1)});
    }

    const exactMessages = {
        "Service has no default rotation": "service_standards.result.rotation_missing",
        "Service has an active default rotation": "service_standards.result.rotation_passed",
        "Service default rotation is disabled or deleted": "service_standards.result.rotation_invalid",
        "Service has no default escalation policy": "service_standards.result.escalation_missing",
        "Service escalation policy is disabled or deleted": "service_standards.result.escalation_invalid",
        "Service escalation policy has no active rules": "service_standards.result.escalation_no_rules",
        "Service has an active escalation policy": "service_standards.result.escalation_passed",
        "Service has no notification policy": "service_standards.result.notification_missing",
        "Service notification policy is disabled or deleted": "service_standards.result.notification_invalid",
        "Service notification policy has no active rules": "service_standards.result.notification_no_rules",
        "Service notification policy has no active channels": "service_standards.result.notification_no_channels",
        "Service has an active notification policy": "service_standards.result.notification_passed",
        "Service has an active direct alert route": "service_standards.result.route_direct",
        "Service has an active route through a match rule": "service_standards.result.route_match",
        "Service has no active alert route": "service_standards.result.route_missing",
        "Service is not part of a dependency cycle": "service_standards.result.cycle_absent",
        "Service is part of a dependency cycle": "service_standards.result.cycle_present",
        "Readiness check could not be evaluated": "service_standards.result.evaluation_error",
    };

    if (Object.prototype.hasOwnProperty.call(exactMessages, message)) {
        return i18n.t(exactMessages[message]);
    }

    if (result.check_type === "runbook_exists") {
        return result.status === "passed"
            ? i18n.t("service_standards.result.runbook_passed", {count: Number(details.count || 0)})
            : i18n.t("service_standards.result.runbook_failed", {minimum: Number(details.minimum || 1)});
    }

    return message || result.status || i18n.t("service_standards.readiness.failed_fallback");
}

function getReadinessStatusClass(status) {
    if (status === "ready") {
        return "status-pill status-active";
    }

    if (status === "warning") {
        return "status-pill status-scheduled";
    }

    if (status === "not_ready") {
        return "status-pill status-inactive";
    }

    return "status-pill status-neutral";
}

function evaluateServiceReadiness(service) {
    apiPost(
        "/api/services/" + encodeURIComponent(service.id) + "/readiness/evaluate",
        {},
        function () {
            serviceDetailsCache = {};
            refreshServices();

            if ($("#service-details-modal").is(":visible")) {
                loadServiceDetails(service.id);
            }
        }
    );
}


function serviceDetailsCompactRow(label, value) {
    return $("<tr>")
        .append(
            $("<td>")
                .addClass("table-cell-truncate")
                .append($("<strong>").text(label))
        )
        .append(
            $("<td>")
                .addClass("table-cell-truncate-wide")
                .attr("title", value || "-")
                .text(value || "-")
        );
}


function serviceDetailsCompactCard(title, rows) {
    const card = $("<section>").addClass("card");
    const tbody = $("<tbody>");

    rows.forEach(function (row) {
        tbody.append(serviceDetailsCompactRow(row[0], row[1]));
    });

    card.append(
        $("<div>")
            .addClass("card-header")
            .append($("<div>").append($("<h2>").text(title)))
    );

    card.append(
        $("<div>")
            .addClass("table-wrapper")
            .append(
                $("<table>")
                    .addClass("data-table")
                    .append(tbody)
            )
    );

    return card;
}




function serviceDetailsTableCell(value, wide) {
    const cell = $("<td>");

    if (wide) {
        cell.addClass("table-cell-truncate-wide");
    } else {
        cell.addClass("table-cell-truncate");
    }

    if (value && value.jquery) {
        cell.append(value);
        return cell;
    }

    cell.attr("title", value === undefined || value === null || value === "" ? "-" : String(value));
    cell.text(value === undefined || value === null || value === "" ? "-" : value);

    return cell;
}


function serviceDetailsTableCard(title, headers, rows, emptyMessage) {
    const card = $("<section>").addClass("card");
    const table = $("<table>").addClass("data-table");
    const tbody = $("<tbody>");

    card.append(
        $("<div>")
            .addClass("card-header")
            .append($("<div>").append($("<h2>").text(title)))
    );

    if (headers && headers.length) {
        table.append(
            $("<thead>").append(
                $("<tr>").append(headers.map(function (header) {
                    return $("<th>").text(header);
                }))
            )
        );
    }

    if (!rows.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>")
                    .attr("colspan", headers && headers.length ? headers.length : 1)
                    .addClass("empty-cell")
                    .text(emptyMessage || "No data")
            )
        );
    } else {
        rows.forEach(function (row) {
            const tr = $("<tr>");

            row.forEach(function (value, index) {
                tr.append(serviceDetailsTableCell(value, index === row.length - 1));
            });

            tbody.append(tr);
        });
    }

    table.append(tbody);
    card.append($("<div>").addClass("table-wrapper").append(table));

    return card;
}


function renderServiceDetailsHero(payload) {
    const service = payload.service || {};
    const section = serviceDetailsSection(
        "Overview",
        service.description || service.slug || "No description"
    );

    const badges = $("<div>").addClass("service-detail-badges");

    badges.append(renderServiceStatusBadge(service));
    badges.append(renderServiceReadinessBadge(service));
    badges.append($("<span>").addClass("status-pill status-neutral").text(service.criticality || "unknown"));
    badges.append($("<span>").addClass("status-pill status-neutral").text(service.environment || "unknown"));
    badges.append($("<span>").addClass("status-pill status-neutral").text(service.tier || "unknown"));

    section.append(badges);

    section.append(
        $("<div>")
            .addClass("grid-two")
            .append(
                serviceDetailsCompactCard("Identity", [
                    ["Team", service.team_name || service.team_slug],
                    ["Type", service.service_type],
                    ["Kind", service.kind],
                    ["Lifecycle", service.lifecycle],
                    ["Enabled", service.enabled ? "Yes" : "No"],
                    ["Status message", service.status_message],
                ])
            )
            .append(
                serviceDetailsCompactCard("Defaults", [
                    ["Default rotation", service.default_rotation_name],
                    ["Escalation policy", service.default_escalation_policy_name],
                    ["Notification policy", service.notification_policy_name],
                    ["Priority policy", service.priority_policy_name || "Team default"],
                    ["Maintenance", window.AppMaintenanceBadges.text(service, "-")],
                ])
            )
    );

    return section;
}

function renderServiceDetailsQuickActions(payload) {
    const service = payload.service || {};
    const section = serviceDetailsSection("Quick actions", null);
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
        label: "Maintenance",
        onClick: function () {
            openServiceMaintenanceWindow(service);
        },
    });

    appendIconActionIfAllowed(actions, service, {
        required: "write",
        icon: "fas fa-book",
        label: "Runbook",
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
        label: "Link",
        onClick: function () {
            resetServiceLinkForm();
            fillServiceSelect("#service-link-service", service.id);
            $("#service-link-service").prop("disabled", true);
            openAppModal("#service-link-modal");
        },
    });

    appendIconActionIfAllowed(actions, service, {
        required: "write",
        icon: "fas fa-bullseye",
        label: "SLI",
        onClick: function () {
            openServiceSliModal(service, null);
        },
    });

    appendIconActionIfAllowed(actions, service, {
        required: "write",
        icon: "fas fa-users",
        label: "Stakeholder",
        onClick: function () {
            openCreateServiceOwnerModal(service);
        },
    });

    appendIconActionIfAllowed(actions, service, {
        required: "write",
        icon: "fas fa-project-diagram",
        label: "Dependency",
        onClick: function () {
            resetServiceDependencyForm();
            fillServiceSelect("#service-dependency-source", service.id);
            setServiceDependencySelectDisabled("#service-dependency-source", true);
            loadServiceDependencyTargets(function () {
                openAppModal("#service-dependency-modal");
            });
        },
    });

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn")
            .text("Alerts")
            .on("click", function () {
                openServiceAlerts(service, { onlyOpen: true });
            })
    );

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn")
            .text("Impact")
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
    window.selectedServiceId = null;
    $("#service-details-modal-title").text("Service details");
    $("#service-details-modal-subtitle").text("");
    $("#service-details-modal-body").html(
        $("<div>").addClass("empty-state").text("Select a service to view details.")
    );
}
