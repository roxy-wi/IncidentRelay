let serviceDependencyGraphCy = null;
let serviceDependencyGraphRenderTimer = null;
let serviceDependencyGraphSearchTimer = null;
const SERVICE_DEPENDENCIES_VIEW_STORAGE_KEY = "incidentrelay.services.dependencies.view";
let serviceDependenciesView = getStoredServiceDependenciesView();

function getStoredServiceDependenciesView() {
    try {
        const value = localStorage.getItem(SERVICE_DEPENDENCIES_VIEW_STORAGE_KEY);
        return value === "graph" ? "graph" : "table";
    } catch (error) {
        return "table";
    }
}

function storeServiceDependenciesView(view) {
    try {
        localStorage.setItem(SERVICE_DEPENDENCIES_VIEW_STORAGE_KEY, view);
    } catch (error) {
        // Ignore storage errors.
    }
}

function applyServiceDependenciesView(view, options) {
    options = options || {};

    serviceDependenciesView = view === "graph" ? "graph" : "table";

    if (options.persist !== false) {
        storeServiceDependenciesView(serviceDependenciesView);
    }

    $(".service-dependencies-view-tab").removeClass("is-active");
    $('.service-dependencies-view-tab[data-service-dependencies-view="' + serviceDependenciesView + '"]')
        .addClass("is-active");

    const isTableView = serviceDependenciesView === "table";
    const isGraphView = serviceDependenciesView === "graph";

    $("#service-dependencies-table-view").toggle(isTableView);
    $("#service-dependencies-graph-view").toggle(isGraphView);

    $(".service-dependencies-table-search").toggle(isTableView);

    if (isTableView) {
        renderAllServiceDependenciesTable();
        return;
    }

    scheduleRenderServiceDependencyGraph(100);
}

function scheduleRenderServiceDependencyGraph(delay) {
    clearTimeout(serviceDependencyGraphRenderTimer);

    serviceDependencyGraphRenderTimer = setTimeout(function () {
        renderServiceDependencyGraph();
    }, delay || 0);
}


function serviceDependencyGraphValue(value) {
    if (value === null || value === undefined) {
        return "";
    }
    return String(value);
}

function serviceDependencyGraphPick(object, paths) {
    if (!object) {
        return null;
    }

    for (let i = 0; i < paths.length; i += 1) {
        const parts = paths[i].split(".");
        let value = object;

        for (let j = 0; j < parts.length; j += 1) {
            if (value === null || value === undefined) {
                break;
            }
            value = value[parts[j]];
        }

        if (value !== null && value !== undefined && value !== "") {
            return value;
        }
    }

    return null;
}

function serviceDependencyGraphId(value) {
    if (value === null || value === undefined || value === "") {
        return "";
    }

    if (typeof value === "object") {
        return serviceDependencyGraphId(
            value.id ||
            value.service_id ||
            value.serviceId ||
            value.pk
        );
    }

    const stringValue = String(value).trim();
    return stringValue ? stringValue : "";
}

function serviceDependencyGraphSourceId(dependency) {
    return serviceDependencyGraphId(serviceDependencyGraphPick(dependency, [
        "service_id",
        "source_service_id",
        "source_id",
        "from_service_id",
        "from_id",
        "dependent_service_id",
        "consumer_service_id",
        "service.id",
        "source_service.id",
        "source.id",
        "from_service.id",
        "dependent_service.id",
        "consumer_service.id",
        "service",
        "source_service",
        "source",
        "from_service",
        "dependent_service",
        "consumer_service"
    ]));
}

function serviceDependencyGraphTargetId(dependency) {
    return serviceDependencyGraphId(serviceDependencyGraphPick(dependency, [
        "depends_on_service_id",
        "dependency_service_id",
        "target_service_id",
        "target_id",
        "to_service_id",
        "to_id",
        "provider_service_id",
        "upstream_service_id",
        "depends_on_id",
        "depends_on.id",
        "depends_on_service.id",
        "dependency_service.id",
        "target_service.id",
        "target.id",
        "to_service.id",
        "provider_service.id",
        "upstream_service.id",
        "depends_on",
        "depends_on_service",
        "dependency_service",
        "target_service",
        "target",
        "to_service",
        "provider_service",
        "upstream_service"
    ]));
}

function serviceDependencyGraphServiceMap() {
    const map = {};

    asArray(servicesCache).forEach((service) => {
        if (!service || service.id === null || service.id === undefined) {
            return;
        }
        map[String(service.id)] = service;
    });

    return map;
}

function serviceDependencyGraphImpactMap() {
    const map = {};

    if (typeof serviceImpactCache === "undefined") {
        return map;
    }

    asArray(serviceImpactCache).forEach(function (row) {
        const serviceId = serviceDependencyGraphId(row.service_id);
        if (!serviceId) {
            return;
        }

        map[serviceId] = row;
    });

    return map;
}

function serviceDependencyGraphAlertStatus(service, impactMap) {
    const serviceId = serviceDependencyGraphId(service && service.id);
    const impact = serviceId ? impactMap[serviceId] : null;

    if (!impact) {
        return null;
    }

    if (Number(impact.critical_open_alert_groups || 0) > 0) {
        return "major_outage";
    }

    if (impact.alert_impact_status && impact.alert_impact_status !== "operational") {
        return impact.alert_impact_status;
    }

    if (Number(impact.open_alert_groups || 0) > 0) {
        return "degraded";
    }

    return null;
}


const SERVICE_DEPENDENCY_GRAPH_STATUS_RANK = {
    disabled: -1,
    operational: 0,
    unknown: 0,
    maintenance: 1,
    degraded: 2,
    partial_outage: 3,
    major_outage: 4
};

const SERVICE_DEPENDENCY_GRAPH_TYPE_RANK = {
    informational: 0,
    external: 1,
    soft: 2,
    hard: 3
};

const SERVICE_DEPENDENCY_GRAPH_CRITICALITY_RANK = {
    optional: 1,
    important: 2,
    required: 3
};

function serviceDependencyGraphNormalizeStatus(status) {
    const value = serviceDependencyGraphValue(status || "unknown")
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9_]+/g, "_");

    return Object.prototype.hasOwnProperty.call(SERVICE_DEPENDENCY_GRAPH_STATUS_RANK, value)
        ? value
        : "unknown";
}

function serviceDependencyGraphStatusRank(status) {
    const key = serviceDependencyGraphNormalizeStatus(status);
    return Object.prototype.hasOwnProperty.call(SERVICE_DEPENDENCY_GRAPH_STATUS_RANK, key)
        ? SERVICE_DEPENDENCY_GRAPH_STATUS_RANK[key]
        : 0;
}

function serviceDependencyGraphMaxStatus() {
    const statuses = Array.prototype.slice.call(arguments).map(serviceDependencyGraphNormalizeStatus);
    return statuses.reduce(function (best, status) {
        return serviceDependencyGraphStatusRank(status) > serviceDependencyGraphStatusRank(best)
            ? status
            : best;
    }, "operational");
}

function serviceDependencyGraphNormalizeDependencyType(value) {
    return serviceDependencyGraphValue(value || "hard")
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9_]+/g, "_");
}

function serviceDependencyGraphNormalizeDependencyCriticality(value) {
    return serviceDependencyGraphValue(value || "important")
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9_]+/g, "_");
}

function serviceDependencyGraphPropagateDependencyStatus(dependency, upstreamStatus) {
    upstreamStatus = serviceDependencyGraphNormalizeStatus(upstreamStatus);

    if (["operational", "maintenance", "disabled"].includes(upstreamStatus)) {
        return "operational";
    }

    if (upstreamStatus === "unknown") {
        return "unknown";
    }

    const dependencyType = serviceDependencyGraphNormalizeDependencyType(dependency.dependency_type || dependency.type || dependency.kind);
    const criticality = serviceDependencyGraphNormalizeDependencyCriticality(dependency.criticality || dependency.dependency_criticality);
    const typeRank = Object.prototype.hasOwnProperty.call(SERVICE_DEPENDENCY_GRAPH_TYPE_RANK, dependencyType)
        ? SERVICE_DEPENDENCY_GRAPH_TYPE_RANK[dependencyType]
        : SERVICE_DEPENDENCY_GRAPH_TYPE_RANK.soft;
    const criticalityRank = Object.prototype.hasOwnProperty.call(SERVICE_DEPENDENCY_GRAPH_CRITICALITY_RANK, criticality)
        ? SERVICE_DEPENDENCY_GRAPH_CRITICALITY_RANK[criticality]
        : SERVICE_DEPENDENCY_GRAPH_CRITICALITY_RANK.important;

    if (typeRank <= SERVICE_DEPENDENCY_GRAPH_TYPE_RANK.informational) {
        return "operational";
    }

    if (upstreamStatus === "major_outage") {
        if (dependencyType === "hard" || criticality === "required") {
            return "major_outage";
        }
        if (dependencyType === "soft" || criticality === "important") {
            return "partial_outage";
        }
        return "degraded";
    }

    if (upstreamStatus === "partial_outage") {
        if (dependencyType === "hard" || criticalityRank >= SERVICE_DEPENDENCY_GRAPH_CRITICALITY_RANK.important) {
            return "partial_outage";
        }
        return "degraded";
    }

    if (upstreamStatus === "degraded") {
        if (criticalityRank >= SERVICE_DEPENDENCY_GRAPH_CRITICALITY_RANK.important) {
            return "degraded";
        }
        return "operational";
    }

    return "operational";
}

function serviceDependencyGraphNodeBaseStatus(service, impactMap) {
    if (!service || service.enabled === false) {
        return "disabled";
    }

    const id = serviceDependencyGraphId(service.id);
    const impact = id ? (impactMap[id] || {}) : {};
    const alertStatus = serviceDependencyGraphAlertStatus(service, impactMap) || impact.alert_impact_status || "operational";

    return serviceDependencyGraphMaxStatus(
        impact.own_status || service.status || "unknown",
        alertStatus
    );
}

function serviceDependencyGraphBusinessServiceNodeId(businessServiceId) {
    return "business-service-" + serviceDependencyGraphId(businessServiceId);
}

function serviceDependencyGraphServicesForImpact(serviceMap, impactMap) {
    const servicesById = Object.assign({}, serviceMap);

    Object.keys(impactMap || {}).forEach(function (id) {
        if (servicesById[id]) {
            return;
        }

        const impact = impactMap[id] || {};
        servicesById[id] = {
            id: id,
            name: impact.service_name || ("Service #" + id),
            slug: impact.service_slug || "",
            status: impact.own_status || impact.effective_status || "unknown",
            enabled: impact.effective_status !== "disabled",
            team_name: impact.team_name || impact.team_slug || ""
        };
    });

    asArray(allServiceDependenciesCache).forEach(function (dependency) {
        if (!dependency) {
            return;
        }

        const sourceId = serviceDependencyGraphSourceId(dependency);
        const targetId = serviceDependencyGraphTargetId(dependency);

        if (sourceId && !servicesById[sourceId]) {
            servicesById[sourceId] = serviceDependencyGraphServiceFromDependency(dependency, "source", sourceId, serviceMap);
        }

        if (targetId && !servicesById[targetId]) {
            servicesById[targetId] = serviceDependencyGraphServiceFromDependency(dependency, "target", targetId, serviceMap);
        }
    });

    return servicesById;
}


function serviceDependencyGraphBusinessComponentSearchText(component) {
    return [
        component.business_service_name,
        component.business_service_slug,
        component.business_service_status,
        component.service_name,
        component.service_slug,
        component.criticality,
        component.component_type,
        component.description
    ]
        .map(serviceDependencyGraphValue)
        .join(" ")
        .toLowerCase();
}

function serviceDependencyGraphNodeDisplayStatus(service, impactMap) {
    const serviceId = serviceDependencyGraphId(service && service.id);
    const impact = serviceId ? impactMap[serviceId] : null;

    if (impact && impact.effective_status) {
        return serviceDependencyGraphNormalizeStatus(impact.effective_status);
    }

    return serviceDependencyGraphNodeStatus(service);
}

function serviceDependencyGraphServiceFromDependency(dependency, side, id, serviceMap) {
    if (serviceMap[id]) {
        return serviceMap[id];
    }

    const objectCandidates = side === "source"
        ? [
            "service",
            "source_service",
            "source",
            "from_service",
            "dependent_service",
            "consumer_service"
        ]
        : [
            "depends_on_service",
            "dependency_service",
            "target_service",
            "target",
            "to_service",
            "provider_service",
            "upstream_service",
            "depends_on"
        ];

    for (let i = 0; i < objectCandidates.length; i += 1) {
        const candidate = dependency[objectCandidates[i]];
        if (candidate && typeof candidate === "object") {
            return Object.assign({}, candidate, { id: id });
        }
    }

    if (side === "source") {
        return {
            id: id,
            name: serviceDependencyGraphPick(dependency, [
                "service_name",
                "source_service_name",
                "source_name",
                "from_service_name",
                "dependent_service_name",
                "consumer_service_name"
            ]) || `Service #${id}`,
            slug: serviceDependencyGraphPick(dependency, [
                "service_slug",
                "source_service_slug",
                "source_slug",
                "from_service_slug",
                "dependent_service_slug",
                "consumer_service_slug"
            ]) || "",
            status: serviceDependencyGraphPick(dependency, [
                "service_status",
                "source_service_status",
                "source_status",
                "from_service_status",
                "dependent_service_status",
                "consumer_service_status"
            ]) || "unknown",
            enabled: serviceDependencyGraphPick(dependency, [
                "service_enabled",
                "source_service_enabled",
                "source_enabled",
                "from_service_enabled",
                "dependent_service_enabled",
                "consumer_service_enabled"
            ]) !== false,
            team_name: serviceDependencyGraphPick(dependency, [
                "service_team_name",
                "source_team_name",
                "from_service_team_name",
                "dependent_service_team_name",
                "consumer_service_team_name"
            ]) || ""
        };
    }

    return {
        id: id,
        name: serviceDependencyGraphPick(dependency, [
            "depends_on_service_name",
            "dependency_service_name",
            "target_service_name",
            "target_name",
            "to_service_name",
            "provider_service_name",
            "upstream_service_name"
        ]) || `Service #${id}`,
        slug: serviceDependencyGraphPick(dependency, [
            "depends_on_service_slug",
            "dependency_service_slug",
            "target_service_slug",
            "target_slug",
            "to_service_slug",
            "provider_service_slug",
            "upstream_service_slug"
        ]) || "",
        status: serviceDependencyGraphPick(dependency, [
            "depends_on_service_status",
            "dependency_service_status",
            "target_service_status",
            "target_status",
            "to_service_status",
            "provider_service_status",
            "upstream_service_status"
        ]) || "unknown",
        enabled: serviceDependencyGraphPick(dependency, [
            "depends_on_service_enabled",
            "dependency_service_enabled",
            "target_service_enabled",
            "target_enabled",
            "to_service_enabled",
            "provider_service_enabled",
            "upstream_service_enabled"
        ]) !== false,
        team_name: serviceDependencyGraphPick(dependency, [
            "depends_on_service_team_name",
            "dependency_service_team_name",
            "target_team_name",
            "to_service_team_name",
            "provider_service_team_name",
            "upstream_service_team_name"
        ]) || ""
    };
}

function serviceDependencyGraphNodeStatus(service) {
    if (!service || service.enabled === false) {
        return "disabled";
    }

    return serviceDependencyGraphValue(service.status || "unknown")
        .toLowerCase()
        .replace(/[^a-z0-9_]+/g, "_");
}

function serviceDependencyGraphNodeLabel(service) {
    return serviceDependencyGraphValue(service.name || service.slug || `Service #${service.id}`);
}


function serviceDependencyGraphDependencySearchText(dependency, sourceService, targetService) {
    return [
        dependency.dependency_type,
        dependency.type,
        dependency.kind,
        dependency.criticality,
        dependency.description,
        sourceService && sourceService.name,
        sourceService && sourceService.slug,
        targetService && targetService.name,
        targetService && targetService.slug
    ]
        .map(serviceDependencyGraphValue)
        .join(" ")
        .toLowerCase();
}

function serviceDependencyGraphPopulateFocusSelect(serviceMap) {
    const $select = $("#service-dependency-graph-focus");
    if (!$select.length) {
        return;
    }

    const selectedValue = $select.val() || "";
    const services = Object.values(serviceMap)
        .filter((service) => service && service.id !== null && service.id !== undefined)
        .sort((a, b) => serviceDependencyGraphNodeLabel(a).localeCompare(serviceDependencyGraphNodeLabel(b)));

    const options = ['<option value="">All services</option>'];

    services.forEach((service) => {
        const id = serviceDependencyGraphId(service.id);
        const label = escapeHtml(serviceDependencyGraphNodeLabel(service));
        options.push(`<option value="${id}">${label}</option>`);
    });

    $select.html(options.join(""));

    if (selectedValue && $select.find(`option[value="${selectedValue}"]`).length) {
        $select.val(selectedValue);
    }
}

function serviceDependencyGraphLayoutOptions() {
    const layoutName = $("#service-dependency-graph-layout").val() || "breadthfirst";

    if (layoutName === "breadthfirst") {
        return {
            name: "breadthfirst",
            directed: true,
            circle: false,
            grid: true,
            spacingFactor: 1.35,
            padding: 50,
            animate: true
        };
    }

    if (layoutName === "circle") {
        return {
            name: "circle",
            padding: 40,
            animate: true
        };
    }

    if (layoutName === "grid") {
        return {
            name: "grid",
            padding: 40,
            animate: true
        };
    }

    return {
        name: "cose",
        randomize: false,
        idealEdgeLength: 120,
        nodeOverlap: 20,
        refresh: 20,
        fit: true,
        padding: 40,
        animate: true
    };
}

function serviceDependencyGraphElements() {
    const serviceMap = serviceDependencyGraphServiceMap();
    const impactMap = serviceDependencyGraphImpactMap();
    const focusId = serviceDependencyGraphId($("#service-dependency-graph-focus").val());
    const direction = $("#service-dependency-graph-direction").val() || "connected";
    const query = serviceDependencyGraphValue($("#service-dependency-graph-search").val()).trim().toLowerCase();

    const nodesById = {};
    const edges = [];

    function addNode(service, extraClasses) {
        if (!service || service.id === null || service.id === undefined) {
            return;
        }

        const id = serviceDependencyGraphId(service.id);
        if (!id) {
            return;
        }

        const impact = impactMap[id] || {};
        const baseLabel = serviceDependencyGraphNodeLabel(service);
        const openAlertGroups = Number(impact.open_alert_groups || 0);
        const criticalOpenAlertGroups = Number(impact.critical_open_alert_groups || 0);
        const displayStatus = serviceDependencyGraphNodeDisplayStatus(service, impactMap);
        const alertStatus = serviceDependencyGraphAlertStatus(service, impactMap);
        const effectiveImpactScore = Number(impact.effective_impact_score || impact.impact_score || 0);
        const dependencyImpactScore = Number(impact.dependency_impact_score || 0);
        const hasDependencyImpact = (impact.primary_reason === "upstream_dependency") || dependencyImpactScore > 0;

        const classes = [
            `status-${displayStatus}`
        ];

        if (alertStatus) {
            classes.push("has-own-alerts");
        }

        if (hasDependencyImpact) {
            classes.push("has-dependency-impact");
        }

        if (focusId && id === focusId) {
            classes.push("focused");
        }

        if (extraClasses) {
            classes.push(extraClasses);
        }

        nodesById[id] = {
            data: {
                id: id,
                nodeType: "technical_service",
                serviceId: id,
                label: baseLabel,
                displayLabel: openAlertGroups > 0
                    ? baseLabel + "\n⚠ " + openAlertGroups
                    : effectiveImpactScore > 0
                        ? baseLabel + "\nimpact " + effectiveImpactScore
                        : baseLabel,
                status: service.status || "unknown",
                displayStatus: displayStatus,
                alertStatus: alertStatus || "operational",
                dependencyImpactStatus: hasDependencyImpact ? displayStatus : "operational",
                effectiveImpactScore: effectiveImpactScore,
                dependencyImpactScore: dependencyImpactScore,
                primaryReason: impact.primary_reason || "none",
                openAlertGroups: openAlertGroups,
                criticalOpenAlertGroups: criticalOpenAlertGroups,
                team: service.team_name || service.team || "",
                enabled: service.enabled !== false
            },
            classes: classes.join(" ")
        };
    }

    asArray(allServiceDependenciesCache).forEach((dependency) => {
        if (!dependency) {
            return;
        }

        const sourceId = serviceDependencyGraphSourceId(dependency);
        const targetId = serviceDependencyGraphTargetId(dependency);

        if (!sourceId || !targetId || sourceId === targetId) {
            return;
        }

        const sourceService = serviceDependencyGraphServiceFromDependency(dependency, "source", sourceId, serviceMap);
        const targetService = serviceDependencyGraphServiceFromDependency(dependency, "target", targetId, serviceMap);

        if (focusId) {
            if (direction === "outgoing" && sourceId !== focusId) {
                return;
            }

            if (direction === "incoming" && targetId !== focusId) {
                return;
            }

            if (direction === "connected" && sourceId !== focusId && targetId !== focusId) {
                return;
            }
        }

        if (query) {
            const haystack = serviceDependencyGraphDependencySearchText(dependency, sourceService, targetService);
            if (!haystack.includes(query)) {
                return;
            }
        }

        addNode(sourceService);
        addNode(targetService);

        const criticality = serviceDependencyGraphNormalizeDependencyCriticality(
            dependency.criticality ||
            dependency.dependency_criticality ||
            dependency.impact ||
            "important"
        );

        const dependencyType = serviceDependencyGraphNormalizeDependencyType(
            dependency.dependency_type ||
            dependency.type ||
            dependency.kind ||
            "dependency"
        );

        const classes = [
            `criticality-${criticality}`,
            `dependency-type-${dependencyType}`
        ];

        if (dependency.enabled === false) {
            classes.push("disabled");
        }

        edges.push({
            data: {
                id: `dependency-${dependency.id || `${sourceId}-${targetId}`}`,
                source: sourceId,
                target: targetId,
                label: dependency.dependency_type || dependency.type || dependency.kind || "",
                displayLabel: dependency.dependency_type || dependency.type || dependency.kind || "",
                criticality: dependency.criticality || "",
                description: dependency.description || ""
            },
            classes: classes.join(" ")
        });
    });

    asArray(businessServiceComponentsCache).forEach(function (component) {
        if (!component || component.enabled === false) {
            return;
        }

        const serviceId = serviceDependencyGraphId(component.service_id);
        const businessServiceId = serviceDependencyGraphId(component.business_service_id);

        if (!serviceId || !businessServiceId) {
            return;
        }

        const componentMatchesQuery = query
            && serviceDependencyGraphBusinessComponentSearchText(component).includes(query);

        if (!nodesById[serviceId]) {
            if (!componentMatchesQuery || !serviceMap[serviceId]) {
                return;
            }

            addNode(serviceMap[serviceId]);
        }

        const businessNodeId = serviceDependencyGraphBusinessServiceNodeId(businessServiceId);
        const businessStatus = serviceDependencyGraphNormalizeStatus(component.business_service_status || "unknown");
        const businessLabel = serviceDependencyGraphValue(
            component.business_service_name || component.business_service_slug || ("Business service #" + businessServiceId)
        );
        const componentCriticality = serviceDependencyGraphNormalizeDependencyCriticality(component.criticality || "required");

        if (!nodesById[businessNodeId]) {
            nodesById[businessNodeId] = {
                data: {
                    id: businessNodeId,
                    nodeType: "business_service",
                    businessServiceId: businessServiceId,
                    label: businessLabel,
                    displayLabel: businessLabel + "\nBusiness",
                    status: component.business_service_status || "unknown",
                    displayStatus: businessStatus,
                    team: component.owner_team_name || component.team_name || "",
                    enabled: true
                },
                classes: [
                    "business-service",
                    `status-${businessStatus}`
                ].join(" ")
            };
        }

        edges.push({
            data: {
                id: `business-component-${component.id || `${businessServiceId}-${serviceId}`}`,
                source: businessNodeId,
                target: serviceId,
                label: component.criticality || "component",
                displayLabel: component.criticality || "component",
                criticality: component.criticality || "",
                description: component.description || ""
            },
            classes: [
                "business-component",
                `criticality-${componentCriticality}`
            ].join(" ")
        });
    });

    if (focusId && serviceMap[focusId] && !nodesById[focusId]) {
        addNode(serviceMap[focusId], "focused");
    }

    return {
        nodes: Object.values(nodesById),
        edges: edges
    };
}

function serviceDependencyGraphStyle() {
    return [
        {
            selector: "node",
            style: {
                "label": "data(displayLabel)",
                "text-wrap": "wrap",
                "text-max-width": 120,
                "font-size": 12,
                "font-weight": 600,
                "color": "#0f172a",
                "text-valign": "bottom",
                "text-halign": "center",
                "text-margin-y": 8,
                "background-color": "#64748b",
                "border-width": 2,
                "border-color": "#ffffff",
                "width": 42,
                "height": 42,
                "overlay-opacity": 0
            }
        },
        {
            selector: "node.status-operational",
            style: {
                "background-color": "#16a34a"
            }
        },
        {
            selector: "node.status-degraded",
            style: {
                "background-color": "#f59e0b"
            }
        },
        {
            selector: "node.status-partial_outage",
            style: {
                "background-color": "#f97316"
            }
        },
        {
            selector: "node.status-major_outage",
            style: {
                "background-color": "#dc2626"
            }
        },
        {
            selector: "node.has-own-alerts",
            style: {
                "border-width": 4,
                "border-color": "#991b1b"
            }
        },
        {
            selector: "node.has-dependency-impact",
            style: {
                "border-style": "double",
                "border-width": 5,
                "border-color": "#7c3aed"
            }
        },
        {
            selector: "node.has-own-alerts.has-dependency-impact",
            style: {
                "border-color": "#991b1b"
            }
        },
        {
            selector: "node.business-service",
            style: {
                "shape": "round-rectangle",
                "width": 92,
                "height": 44,
                "font-size": 11,
                "text-valign": "center",
                "text-halign": "center",
                "text-margin-y": 0,
                "border-width": 3,
                "border-color": "#0f172a"
            }
        },
        {
            selector: "node.status-maintenance",
            style: {
                "background-color": "#2563eb"
            }
        },
        {
            selector: "node.status-disabled",
            style: {
                "background-color": "#94a3b8",
                "opacity": 0.65
            }
        },
        {
            selector: "node.focused",
            style: {
                "width": 56,
                "height": 56,
                "border-width": 4,
                "border-color": "#0f172a",
                "z-index": 20
            }
        },
        {
            selector: "edge",
            style: {
                "curve-style": "bezier",
                "target-arrow-shape": "triangle",
                "line-color": "#94a3b8",
                "target-arrow-color": "#94a3b8",
                "width": 2,
                "font-size": 10,
                "color": "#475569",
                "text-background-color": "#ffffff",
                "text-background-opacity": 0.85,
                "text-background-padding": 3,
                "label": "data(displayLabel)",
                "overlay-opacity": 0
            }
        },
        {
            selector: "edge.criticality-required",
            style: {
                "line-color": "#dc2626",
                "target-arrow-color": "#dc2626",
                "width": 4
            }
        },
        {
            selector: "edge.criticality-important",
            style: {
                "line-color": "#f59e0b",
                "target-arrow-color": "#f59e0b",
                "width": 3
            }
        },
        {
            selector: "edge.criticality-optional",
            style: {
                "line-color": "#94a3b8",
                "target-arrow-color": "#94a3b8",
                "width": 2
            }
        },
        {
            selector: "edge.disabled",
            style: {
                "line-style": "dashed",
                "opacity": 0.45
            }
        },
        {
            selector: "edge.business-component",
            style: {
                "line-style": "dotted",
                "line-color": "#0f172a",
                "target-arrow-color": "#0f172a",
                "width": 2
            }
        },
        {
            selector: ":selected",
            style: {
                "border-width": 4,
                "border-color": "#0f172a",
                "line-color": "#0f172a",
                "target-arrow-color": "#0f172a"
            }
        }
    ];
}

function renderServiceDependencyGraph() {
    const container = document.getElementById("service-dependency-graph");
    if (!container) {
        return;
    }

    if (serviceDependenciesView !== "graph") {
        return;
    }

    const dependenciesCount = asArray(allServiceDependenciesCache).length;
    const servicesCount = asArray(servicesCache).length;

    if (typeof cytoscape !== "function") {
        container.innerHTML = '<div class="empty-state">Cytoscape.js is not loaded</div>';
        return;
    }

    if (!dependenciesCount) {
        if (serviceDependencyGraphCy) {
            serviceDependencyGraphCy.destroy();
            serviceDependencyGraphCy = null;
        }

        container.innerHTML =
            '<div class="empty-state">' +
            '<div>' +
            '<strong>No dependencies to visualize</strong>' +
            '<div class="row-subtitle">Services: ' + servicesCount + ', dependencies: 0</div>' +
            '</div>' +
            '</div>';
        return;
    }

    const serviceMap = serviceDependencyGraphServiceMap();
    serviceDependencyGraphPopulateFocusSelect(serviceMap);

    const graphElements = serviceDependencyGraphElements();

    if (!graphElements.nodes.length) {
        if (serviceDependencyGraphCy) {
            serviceDependencyGraphCy.destroy();
            serviceDependencyGraphCy = null;
        }

        const sample = JSON.stringify(allServiceDependenciesCache[0], null, 2);

        container.innerHTML =
            '<div class="empty-state">' +
            '<div>' +
            '<strong>No graph nodes were built</strong>' +
            '<div class="row-subtitle">Services: ' + servicesCount + ', dependencies: ' + dependenciesCount + '</div>' +
            '<pre style="max-width:720px;white-space:pre-wrap;text-align:left;margin-top:12px;">' + escapeHtml(sample) + '</pre>' +
            '</div>' +
            '</div>';

        return;
    }

    container.innerHTML = "";

    if (serviceDependencyGraphCy) {
        serviceDependencyGraphCy.destroy();
        serviceDependencyGraphCy = null;
    }

    serviceDependencyGraphCy = cytoscape({
        container: container,
        elements: graphElements.nodes.concat(graphElements.edges),
        style: serviceDependencyGraphStyle(),
        layout: serviceDependencyGraphLayoutOptions(),
        minZoom: 0.15,
        maxZoom: 2.5,
        wheelSensitivity: 0.18
    });

    serviceDependencyGraphCy.on("tap", "node", function (event) {
        const nodeType = event.target.data("nodeType");

        if (nodeType === "business_service") {
            const businessServiceId = event.target.data("businessServiceId");

            if (typeof openBusinessServiceDetailsModal === "function") {
                openBusinessServiceDetailsModal(businessServiceId);
            }

            return;
        }

        const serviceId = event.target.data("serviceId");

        if (typeof openServiceDetailsModal === "function") {
            openServiceDetailsModal(serviceId);
            return;
        }

        if (typeof openServiceDetails === "function") {
            openServiceDetails(serviceId);
        }
    });

    serviceDependencyGraphCy.on("tap", "edge", function (event) {
        event.target.select();
    });

    setTimeout(function () {
        if (!serviceDependencyGraphCy) {
            return;
        }

        serviceDependencyGraphCy.resize();
        serviceDependencyGraphCy.layout(serviceDependencyGraphLayoutOptions()).run();
        serviceDependencyGraphCy.fit(undefined, 40);
    }, 100);
}

function initializeServiceDependencyGraph() {
    $(".service-dependencies-view-tab")
        .off("click.dependenciesView")
        .on("click.dependenciesView", function () {
            const view = $(this).data("service-dependencies-view") || "table";
            applyServiceDependenciesView(view);
        });

    applyServiceDependenciesView(serviceDependenciesView, { persist: false });

    $("#service-dependency-graph-focus, #service-dependency-graph-direction, #service-dependency-graph-layout")
        .off("change.dependencyGraph")
        .on("change.dependencyGraph", function () {
            if (serviceDependenciesView === "graph") {
                scheduleRenderServiceDependencyGraph(50);
            }
        });

    $("#service-dependency-graph-search")
        .off("input.dependencyGraph")
        .on("input.dependencyGraph", function () {
            clearTimeout(serviceDependencyGraphSearchTimer);
            serviceDependencyGraphSearchTimer = setTimeout(function () {
                if (serviceDependenciesView === "graph") {
                    scheduleRenderServiceDependencyGraph(0);
                }
            }, 150);
        });

    $("#service-dependency-graph-fit")
        .off("click.dependencyGraph")
        .on("click.dependencyGraph", function () {
            if (serviceDependencyGraphCy) {
                serviceDependencyGraphCy.fit(undefined, 40);
            }
        });
}
