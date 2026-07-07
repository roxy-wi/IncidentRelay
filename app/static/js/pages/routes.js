let routesCache = [];
let selectedRouteDetailsId = null;
let routesSortState = createTableSortState("id", "desc");
const routesSortColumns = {
    name: {path: "name", type: "text", defaultDirection: "asc"},
    team: {
        value: function (route) {
            return getRouteTeamLabel(route);
        },
        type: "text",
        defaultDirection: "asc"
    },
    source: {path: "source", type: "text", defaultDirection: "asc"},
    rotation: {
        value: function (route) {
            return route.escalation_policy_name || route.rotation_name || "";
        },
        type: "text",
        defaultDirection: "asc"
    },
    channels: {
        value: function (route) {
            return asArray(route.channels).map(function (channel) {
                return channel.name || "";
            }).join(", ");
        },
        type: "text",
        defaultDirection: "asc",
    },
    enabled: {path: "enabled", type: "boolean", defaultDirection: "desc"},
};
let selectedRouteForServiceRules = null;
let routeServiceRulesCache = [];
function getRouteTeamLabel(route) {
    return route.team_name || route.team_slug || "-";
}
function getRouteEscalationLabel(route) {
    if (route.escalation_policy_name) {
        return "Policy: " + route.escalation_policy_name;
    }

    if (route.rotation_name) {
        return "Rotation: " + route.rotation_name;
    }

    return "-";
}
let routeMatcherPresetsCache = [];
let routeServiceRuleMatcherPresetsCache = [];

function updateRouteMatcherPresetHint() {
    const preset = findMatcherPresetById(routeMatcherPresetsCache, $("#route-matcher-preset").val());
    $("#route-matcher-preset-hint").text(matcherPresetAndLocalHint(preset));
}


function updateServiceRuleMatcherPresetHint() {
    const preset = findMatcherPresetById(routeServiceRuleMatcherPresetsCache, $("#service-rule-matcher-preset").val());
    $("#service-rule-matcher-preset-hint").text(matcherPresetAndLocalHint(preset));
}

function getRouteNotificationModeLabel(route) {
    const mode = route.notification_channel_mode || "route_only";

    if (mode === "service_policy") {
        return "Service notification policy";
    }

    if (mode === "service_policy_plus_route") {
        return "Service policy + route channels";
    }

    return "Route channels only";
}

function updateRouteNotificationChannelModeUi() {
    const mode = (
        $("#route-notification-channel-mode").val()
        || "route_only"
    );
    const routeChannelsDisabled = mode === "service_policy";

    $("#route-channels")
        .prop("disabled", routeChannelsDisabled)
        .closest(".form-group")
        .toggleClass("is-muted", routeChannelsDisabled);

    let helpText;

    if (mode === "service_policy") {
        helpText = (
            "Only channels selected by the matched service notification "
            + "policy will receive shared notifications."
        );
    } else if (mode === "service_policy_plus_route") {
        helpText = (
            "Channels selected by the service policy are combined with "
            + "the channels configured on this route."
        );
    } else {
        helpText = (
            "Only channels configured directly on this route are used."
        );
    }

    $("#route-notification-channel-mode-help").text(helpText);
}

function getRouteTeamEscalationLabel(route) {
    if (route.escalation_policy_name) {
        return "Ignored for policy mode";
    }

    if (route.team_escalation_enabled) {
        return "After " + (route.team_escalation_after_reminders || 0) + " reminders";
    }

    return "Disabled";
}
function initializeRouteMatcherEditors() {
    enhanceMatcherEditor("#route-matchers", {
        label: "Additional matchers JSON",
        header: "Additional matchers",
        context: function () {
            return {
                scope: "route",
                teamId: Number($("#route-team").val()) || null,
                routeId: Number($("#route-id").val()) || null,
                matcherPresetId: Number($("#route-matcher-preset").val()) || null,
            };
        },
    });

    enhanceMatcherEditor("#service-rule-matchers", {
        label: "Additional matchers",
        context: function () {
            const route = getSelectedRouteForServiceRules();

            return {
                scope: "service_rule",
                teamId: route ? route.team_id : null,
                routeId: route ? route.id : null,
                serviceId: Number($("#service-rule-service").val()) || null,
                matcherPresetId: Number($("#service-rule-matcher-preset").val()) || null,
            };
        },
    });
}

function loadRoutes() {
    initializeRouteMatcherEditors();
    fillTeamSelect("#route-team", false, loadRouteDependencies);
    initRoutesTableSorting();
    refreshRoutes();
}

function loadRouteDependencies(callback, selectedMatcherPresetId) {
    const teamId = $("#route-team").val();

    const rotationSelect = $("#route-rotation");
    const channelSelect = $("#route-channels");
    const policySelect = $("#route-escalation-policy");
    const serviceSelect = $("#route-service");
    const matcherPresetSelect = $("#route-matcher-preset");

    rotationSelect.empty().append($("<option>").val("").text("No rotation"));
    channelSelect.empty();

    if (policySelect.length) {
        policySelect.empty().append($("<option>").val("").text("No policy"));
    }

    if (serviceSelect.length) {
        serviceSelect.empty().append($("<option>").val("").text("No default service"));
    }

    if (!teamId) {
        if (typeof callback === "function") {
            callback();
        }
        return;
    }

    routeMatcherPresetsCache = [];
    fillMatcherPresetSelect(matcherPresetSelect, [], selectedMatcherPresetId);
    updateRouteMatcherPresetHint();

    let rotationsLoaded = false;
    let channelsLoaded = false;
    let policiesLoaded = !policySelect.length;
    let servicesLoaded = !serviceSelect.length;
    let matcherPresetsLoaded = !matcherPresetSelect.length;

    function finishWhenReady() {
        if (!rotationsLoaded || !channelsLoaded || !policiesLoaded || !servicesLoaded || !matcherPresetsLoaded) {
            return;
        }

        if (typeof callback === "function") {
            callback();
        }
    }

    apiGet("/api/rotations?team_id=" + encodeURIComponent(teamId), function (rotations) {
        rotationSelect.empty().append($("<option>").val("").text("No rotation"));

        asArray(rotations).forEach(function (rotation) {
            if (!rotation.enabled) {
                return;
            }

            rotationSelect.append(
                $("<option>")
                    .val(String(rotation.id))
                    .text(rotation.name)
            );
        });

        rotationsLoaded = true;
        finishWhenReady();
    });

    apiGet("/api/channels?team_id=" + encodeURIComponent(teamId), function (channels) {
        channelSelect.empty();

        asArray(channels).forEach(function (channel) {
            if (!channel.enabled) {
                return;
            }

            channelSelect.append(
                $("<option>")
                    .val(String(channel.id))
                    .text(channel.name + " (" + channel.channel_type + ")")
            );
        });

        channelsLoaded = true;
        finishWhenReady();
    });

    if (policySelect.length) {
        apiGet("/api/escalation-policies?team_id=" + encodeURIComponent(teamId), function (policies) {
            policySelect.empty().append($("<option>").val("").text("No policy"));

            asArray(policies).forEach(function (policy) {
                if (!policy.enabled) {
                    return;
                }

                policySelect.append(
                    $("<option>")
                        .val(String(policy.id))
                        .text(policy.name)
                );
            });

            policiesLoaded = true;
            finishWhenReady();
        });
    }

    if (serviceSelect.length) {
        apiGet("/api/services?team_id=" + encodeURIComponent(teamId), function (services) {
            serviceSelect.empty().append($("<option>").val("").text("No default service"));

            asArray(services).forEach(function (service) {
                if (!service.enabled) {
                    return;
                }

                serviceSelect.append(
                    $("<option>")
                        .val(String(service.id))
                        .text(service.name + " (" + service.slug + ")")
                );
            });

            servicesLoaded = true;
            finishWhenReady();
        });
    }
    if (matcherPresetSelect.length) {
        loadMatcherPresetsForTeam(teamId, function (presets) {
            routeMatcherPresetsCache = presets;
            fillMatcherPresetSelect(matcherPresetSelect, presets, selectedMatcherPresetId);
            updateRouteMatcherPresetHint();
            matcherPresetsLoaded = true;
            finishWhenReady();
        });
    }
}

function refreshRoutes() {
    apiGet("/api/routes" + selectedTeamQuery(), function (routes) {
        routesCache = asArray(routes);
        renderRoutesSummary(routesCache);
        fillRouteSourceFilter(routesCache);
        renderRoutesTable();
        restoreRouteDetails();
    });
}

function renderRoutesSummary(routes) {
    routes = asArray(routes);

    const enabled = routes.filter(function (route) {
        return !!route.enabled;
    }).length;

    const withEscalation = routes.filter(function (route) {
        return !!route.rotation_id || !!route.rotation_name ||
            !!route.escalation_policy_id || !!route.escalation_policy_name;
    }).length;

    $("#routes-summary-total").text(routes.length);
    $("#routes-summary-enabled").text(enabled);
    $("#routes-summary-disabled").text(routes.length - enabled);
    $("#routes-summary-rotation").text(withEscalation);
}

function fillRouteSourceFilter(routes) {
    const filter = $("#routes-source-filter");
    const selected = filter.val();
    const sources = {
        alertmanager: true,
        aws_sns: true,
        grafana: true,
        rmon: true,
        zabbix: true,
        webhook: true,
        sentry: true,
        librenms: true
    };

    asArray(routes).forEach(function (route) {
        if (route.source) {
            sources[route.source] = true;
        }
    });

    filter.empty();
    filter.append($("<option>").val("").text("All sources"));
    Object.keys(sources).sort().forEach(function (source) {
        filter.append($("<option>").val(source).text(source));
    });
    if (selected && sources[selected]) {
        filter.val(selected);
    }
}

function getRouteSearchText(route) {
    const channels = asArray(route.channels).map(function (channel) {
        return channel.name + " " + channel.channel_type;
    }).join(" ");

    return [
        route.id,
        route.team_name,
        route.team_slug,
        route.name,
        route.source,
        route.rotation_name,
        route.escalation_policy_name,
        route.intake_token_prefix,
        route.enabled ? "enabled" : "disabled",
        channels,
        route.service_name,
        route.service_slug,
        route.notification_channel_mode,
        route.matcher_preset ? route.matcher_preset.name : "",
        getRouteNotificationModeLabel(route),
    ].join(" ").toLowerCase();
}

function renderRoutesCounter(filteredRoutes, allRoutes) {
    filteredRoutes = asArray(filteredRoutes);
    allRoutes = asArray(allRoutes);
    $("#routes-filtered-count").text(filteredRoutes.length);
    $("#routes-total-count").text(allRoutes.length);
}

function renderRoutesTable() {
    const tbody = $("#routes-table");
    const routes = getFilteredRoutes();
    tbody.empty();
    renderRoutesCounter(routes, routesCache);

    if (!routes.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>").attr("colspan", "8").addClass("empty-cell").text("No routes")
            )
        );
        return;
    }

    routes.forEach(function (route) {
        tbody.append(renderRouteRow(route));
    });
}

function renderRouteRow(route) {
    const row = $("<tr>");

    row.append(
        $("<td>")
            .append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("name-button")
                    .text(route.name || "-")
                    .on("click", function () {
                        renderRouteDetails(route);
                    })
            )
            .append($("<div>").addClass("row-subtitle").text("Route #" + route.id))
    );
    row.append($("<td>").append($("<span>").addClass("route-pill").text(getRouteTeamLabel(route))));
    row.append($("<td>").text(route.source || "-"));
    row.append($("<td>").text(getRouteEscalationLabel(route)));
    row.append($("<td>").append(renderRouteChannels(route)));
    row.append($("<td>").append($("<span>").addClass("token-pill").text(route.intake_token_prefix || "-")));
    row.append(
        window.AppMaintenanceBadges.statusCell(
            renderStatusBadge(route.enabled, "Enabled", "Disabled"),
            route
        )
    );
    row.append($("<td>").addClass("actions-cell").append(renderRouteActions(route)));
    return row;
}

function renderRouteChannels(route) {
    const wrapper = $("<div>").addClass("route-channels-list");
    const mode = route.notification_channel_mode || "route_only";
    const channels = asArray(route.channels);

    if (mode === "service_policy") {
        return wrapper.append(
            $("<span>")
                .addClass("route-channel-chip")
                .text("Service policy")
        );
    }

    if (mode === "service_policy_plus_route") {
        wrapper.append(
            $("<span>")
                .addClass("route-channel-chip")
                .text("Service policy")
        );
    }

    channels.forEach(function (channel) {
        wrapper.append(
            $("<span>")
                .addClass("route-channel-chip")
                .text(channel.name || channel.id)
        );
    });

    if (!wrapper.children().length) {
        wrapper.append($("<span>").text("-"));
    }

    return wrapper;
}

function renderRouteActions(route) {
    const items = [
        {
            label: "Edit",
            icon: "fas fa-edit",
            required: "write",
            denyMessage: "Team manager or group editor/admin role is required to edit this route.",
            onClick: function () {
                editRoute(route.id);
            }
        }
    ];

    if (!["sentry", "aws_sns"].includes(route.source)) {
        items.push({
            label: "Regenerate token",
            icon: "fas fa-sync-alt",
            required: "write",
            denyMessage: "Team manager or group editor/admin role is required to regenerate route tokens.",
            onClick: function () {
                regenerateRouteToken(route.id);
            }
        });
    }

    items.push(
        {
            label: "Service rules",
            icon: "fas fa-project-diagram",
            required: "write",
            denyMessage: "Team manager or group editor/admin role is required to manage service rules.",
            onClick: function () {
                openRouteServiceRules(route.id);
            }
        },
        {
            label: route.enabled ? "Disable" : "Enable",
            icon: route.enabled ? "fas fa-pause" : "fas fa-play",
            required: "write",
            danger: route.enabled,
            denyMessage: "Team manager or group editor/admin role is required to enable or disable this route.",
            onClick: function () {
                if (route.enabled) {
                    disableRoute(route);
                } else {
                    enableRoute(route);
                }
            }
        },
        {
            label: "Delete",
            icon: "fas fa-trash",
            required: "delete",
            danger: true,
            denyMessage: "Delete permission is required to delete this route.",
            onClick: function () {
                deleteRoute(route);
            }
        }
    );

    return makeActionMenu({
        object: route,
        items: items
    });
}
function getSelectedRouteForServiceRules() {
    if (!selectedRouteForServiceRules) {
        return null;
    }

    return routesCache.find(function (route) {
        return Number(route.id) === Number(selectedRouteForServiceRules);
    }) || null;
}

function openRouteServiceRules(routeId) {
    const route = routesCache.find(function (item) {
        return Number(item.id) === Number(routeId);
    });

    if (!route) {
        return;
    }

    if (!canWriteObject(route)) {
        showAppError("You do not have permission to manage service rules for this route.");
        return;
    }

    selectedRouteForServiceRules = route.id;

    $("#route-service-rules-title").text("Service rules / " + (route.name || ("Route #" + route.id)));
    $("#service-rule-team").val(route.team_id);
    $("#service-rule-route").val(route.id);

    resetServiceRuleForm();

    loadServiceRuleServices(route.team_id, function () {
        loadServiceRuleMatcherPresets(route.team_id, null, function () {
            refreshRouteServiceRules();
            openAppModal("#route-service-rules-modal");
        });
    });
}

function loadServiceRuleServices(teamId, callback) {
    const select = $("#service-rule-service");

    select.empty();
    select.append($("<option>").val("").text("Select service"));

    if (!teamId) {
        if (typeof callback === "function") {
            callback();
        }
        return;
    }

    apiGet("/api/services?team_id=" + encodeURIComponent(teamId), function (services) {
        select.empty();
        select.append($("<option>").val("").text("Select service"));

        asArray(services).forEach(function (service) {
            if (!service.enabled) {
                return;
            }

            select.append(
                $("<option>")
                    .val(String(service.id))
                    .text(service.name + " (" + service.slug + ")")
            );
        });

        if (typeof callback === "function") {
            callback();
        }
    });
}

function loadServiceRuleMatcherPresets(teamId, selectedPresetId, callback) {
    routeServiceRuleMatcherPresetsCache = [];
    fillMatcherPresetSelect("#service-rule-matcher-preset", [], null);
    updateServiceRuleMatcherPresetHint();

    loadMatcherPresetsForTeam(teamId, function (presets) {
        routeServiceRuleMatcherPresetsCache = presets;
        fillMatcherPresetSelect("#service-rule-matcher-preset", presets, selectedPresetId);
        updateServiceRuleMatcherPresetHint();

        if (typeof callback === "function") {
            callback();
        }
    });
}

function refreshRouteServiceRules() {
    const route = getSelectedRouteForServiceRules();

    if (!route) {
        routeServiceRulesCache = [];
        renderRouteServiceRulesTable();
        return;
    }

    apiGet(
        "/api/services/match-rules?route_id=" + encodeURIComponent(route.id),
        function (rules) {
            routeServiceRulesCache = asArray(rules);
            renderRouteServiceRulesTable();
        }
    );
}

function renderRouteServiceRulesTable() {
    const tbody = $("#route-service-rules-table");

    tbody.empty();

    if (!routeServiceRulesCache.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>")
                    .attr("colspan", "6")
                    .addClass("empty-cell")
                    .text("No service rules")
            )
        );
        return;
    }

    routeServiceRulesCache.forEach(function (rule) {
        tbody.append(renderRouteServiceRuleRow(rule));
    });
}

function renderRouteServiceRuleRow(rule) {
    const row = $("<tr>");

    row.append($("<td>").text(rule.position || 0));

    row.append(
        $("<td>")
            .addClass("table-cell-truncate")
            .attr("title", rule.name || "-")
            .text(rule.name || "-")
    );

    row.append(
        $("<td>")
            .addClass("table-cell-truncate")
            .attr("title", rule.service_name || rule.service_slug || "-")
            .text(rule.service_name || rule.service_slug || "-")
    );

    const matchersCell = $("<td>");
    const matcherPreset = rule.matcher_preset;

    if (matcherPreset) {
        matchersCell.append(
            $("<div>")
                .addClass("row-subtitle")
                .text("Preset: " + formatMatcherPresetOption(matcherPreset))
        );
    }

    matchersCell.append(
        $("<code>")
            .addClass("inline-code")
            .text(JSON.stringify(rule.matchers || {}))
    );

    row.append(matchersCell);

    row.append(
        $("<td>").append(
            renderStatusBadge(rule.enabled, "Enabled", "Disabled")
        )
    );

    row.append(
        $("<td>")
            .addClass("actions-cell")
            .append(
                makeActionMenu({
                    object: getSelectedRouteForServiceRules(),
                    items: [
                        {
                            label: "Edit",
                            icon: "fas fa-edit",
                            required: "write",
                            onClick: function () {
                                editRouteServiceRule(rule);
                            }
                        },
                        {
                            label: "Delete",
                            icon: "fas fa-trash",
                            required: "write",
                            danger: true,
                            onClick: function () {
                                deleteRouteServiceRule(rule);
                            }
                        }
                    ]
                })
            )
    );

    return row;
}

function resetServiceRuleForm() {
    $("#service-rule-id").val("");
    $("#service-rule-name").val("");
    $("#service-rule-service").val("");
    $("#service-rule-position").val("0");
    $("#service-rule-enabled").prop("checked", true);

    fillMatcherPresetSelect("#service-rule-matcher-preset", routeServiceRuleMatcherPresetsCache, null);
    updateServiceRuleMatcherPresetHint();

    setMatcherEditorValue("#service-rule-matchers", {});
}

function editRouteServiceRule(rule) {
    $("#service-rule-id").val(rule.id);
    $("#service-rule-name").val(rule.name || "");
    $("#service-rule-service").val(rule.service_id || "");
    $("#service-rule-position").val(rule.position || 0);
    $("#service-rule-enabled").prop("checked", rule.enabled !== false);

    const matcherPresetId = rule.matcher_preset_id || (rule.matcher_preset ? rule.matcher_preset.id : null);

    fillMatcherPresetSelect("#service-rule-matcher-preset", routeServiceRuleMatcherPresetsCache, matcherPresetId);
    updateServiceRuleMatcherPresetHint();

    setMatcherEditorValue("#service-rule-matchers", rule.matchers || {});
}

function collectRouteServiceRulePayload() {
    return {
        team_id: Number($("#service-rule-team").val()),
        route_id: $("#service-rule-route").val() ? Number($("#service-rule-route").val()) : null,
        service_id: Number($("#service-rule-service").val()),
        position: Number($("#service-rule-position").val() || 0),
        name: $("#service-rule-name").val(),
        description: null,
        matcher_preset_id: $("#service-rule-matcher-preset").val() ? Number($("#service-rule-matcher-preset").val()) : null,
        matchers: getMatcherEditorValue("#service-rule-matchers", {}),
        enabled: $("#service-rule-enabled").is(":checked"),
    };
}

function saveRouteServiceRule() {
    const id = $("#service-rule-id").val();
    const payload = collectRouteServiceRulePayload();

    if (!payload.service_id) {
        showAppError("Service is required.");
        return;
    }

    if (!payload.matcher_preset_id && !Object.keys(payload.matchers || {}).length) {
        showAppError("Select a matcher preset or define additional matchers.");
        return;
    }

    if (id) {
        apiPut("/api/services/match-rules/" + id, payload, function () {
            resetServiceRuleForm();
            refreshRouteServiceRules();
        });
        return;
    }

    apiPost(
        "/api/services/" + payload.service_id + "/match-rules",
        payload,
        function () {
            resetServiceRuleForm();
            refreshRouteServiceRules();
        }
    );
}

function deleteRouteServiceRule(rule) {
    showAppConfirm({
        title: "Delete this service rule?",
        message: "Delete service rule \"" + (rule.name || ("#" + rule.id)) + "\"?",
        confirmText: "Delete",
        confirmClass: "btn-danger",
    }).done(function () {
        apiDelete("/api/services/match-rules/" + rule.id, function () {
            refreshRouteServiceRules();
        });
    });
}
function routeDetailsItem(label, value) {
    return $("<div>")
        .addClass("details-item")
        .append($("<div>").addClass("details-label").text(label))
        .append($("<div>").addClass("details-value").text(value || "-"));
}

function routeDetailsCode(label, value) {
    return $("<div>")
        .addClass("details-item")
        .append($("<div>").addClass("details-label").text(label))
        .append($("<pre>").addClass("details-code").text(JSON.stringify(value || {}, null, 2)));
}

function renderRouteDetails(route) {
    selectedRouteDetailsId = route.id;

    $("#route-details-subtitle").text(getRouteTeamLabel(route) + " / " + (route.enabled ? "Enabled" : "Disabled"));

    const body = $("#route-details-body");
    body.empty();
    body.append(
        $("<div>")
            .addClass("details-list")
            .append(routeDetailsItem("Name", route.name))
            .append(routeDetailsItem("Team", getRouteTeamLabel(route)))
            .append(routeDetailsItem("Source", route.source))
            .append(
                route.source === "sentry"
                    ? routeDetailsItem("Sentry webhook URL", getSentryWebhookUrl(route))
                    : $()
            )
            .append(
                route.source === "sentry"
                    ? routeDetailsItem(
                        "Sentry secret",
                        getRouteSentryConfig(route).has_webhook_secret
                            ? "Configured"
                            : "Not configured"
                    )
                    : $()
            )
            .append(
                route.source === "sentry"
                    ? routeDetailsItem(
                        "Sentry base URL",
                        getRouteSentryConfig(route).base_url || "-"
                    )
                    : $()
            )
            .append(
                route.source === "sentry"
                    ? routeDetailsItem(
                        "Sentry organization",
                        getRouteSentryConfig(route).organization_slug || "-"
                    )
                    : $()
            )
            .append(
                routeDetailsItem(
                    route.source === "aws_sns"
                        ? "SNS webhook URL"
                        : "Webhook URL",
                    getRouteIntakeUrl(route)
                )
            )
            .append(routeDetailsItem("Maintenance", window.AppMaintenanceBadges.text(route, "-")))
            .append(routeDetailsItem("Escalation", getRouteEscalationLabel(route)))
            .append(routeDetailsItem("Team escalation", getRouteTeamEscalationLabel(route)))
            .append(routeDetailsItem("Notification channel source", getRouteNotificationModeLabel(route)))
            .append(routeDetailsItem("Channels", asArray(route.channels).map(function (channel) {
                return channel.name;
            }).join(", ") || "-"))
            .append(
                !["sentry", "aws_sns"].includes(route.source)
                    ? routeDetailsItem(
                        "Token prefix",
                        route.intake_token_prefix
                    )
                    : $()
            )
            .append(routeDetailsItem("Status", route.enabled ? "Enabled" : "Disabled"))
            .append(
                routeDetailsItem(
                    "Matcher preset",
                    route.matcher_preset ? formatMatcherPresetOption(route.matcher_preset) : "No preset"
                )
            )
            .append(routeDetailsCode("Additional matchers", route.matchers || {}))
            .append(routeDetailsCode("Group by", asArray(route.group_by)))
            .append(routeDetailsItem("Service", route.service_name || route.service_slug || "-"))
    );

    if (route.source === "aws_sns") {
        const awsSnsConfig = getRouteAwsSnsConfig(route);

        body.find(".details-list").append(
            routeDetailsItem(
                "SNS Topic ARN",
                awsSnsConfig.topic_arn
            )
        );
    }

    const actions = $("<div>").addClass("details-actions");
    appendIconActionIfAllowed(actions, route, {
        required: "write",
        icon: "fas fa-edit",
        label: "Edit route",
        onClick: function () {
            editRoute(route.id);
        },
    });
    if (!["sentry", "aws_sns"].includes(route.source)) {
        appendIconActionIfAllowed(actions, route, {
            required: "write",
            icon: "fas fa-sync-alt",
            label: "Regenerate route token",
            onClick: function () {
                regenerateRouteToken(route.id);
            },
        });
    }
    appendIconActionIfAllowed(actions, route, {
        required: "write",
        icon: route.enabled ? "fas fa-pause" : "fas fa-play",
        label: route.enabled ? "Disable route" : "Enable route",
        className: route.enabled ? "btn-warning" : "btn-success",
        onClick: function () {
            if (route.enabled) {
                disableRoute(route);
            } else {
                enableRoute(route);
            }
        },
    });
    appendIconActionIfAllowed(actions, route, {
        required: "delete",
        icon: "fas fa-trash-alt",
        label: "Delete route",
        className: "btn-danger",
        onClick: function () {
            deleteRoute(route);
        },
    });

    if (actions.children().length) {
        body.append(actions);
    }
}

function renderRouteDetailsEmpty() {
    selectedRouteDetailsId = null;
    $("#route-details-subtitle").text("Select a route");
    $("#route-details-body").html("<p class=\"muted\">Click a route name to inspect matchers, group by, channels and intake token prefix.</p>");
}

function restoreRouteDetails() {
    if (!routesCache.length) {
        renderRouteDetailsEmpty();
        return;
    }

    if (selectedRouteDetailsId) {
        const selected = routesCache.find(function (route) {
            return Number(route.id) === Number(selectedRouteDetailsId);
        });
        if (selected) {
            renderRouteDetails(selected);
            return;
        }
    }

    renderRouteDetails(routesCache[0]);
}
function getRouteSentryConfig(route) {
    const integrationConfig = route && route.integration_config
        ? route.integration_config
        : {};

    return integrationConfig.sentry || {};
}

function getSentryWebhookUrl(route) {
    const sentryConfig = getRouteSentryConfig(route);
    const path = sentryConfig.webhook_path;

    if (!path) {
        return "";
    }

    return window.location.origin + path;
}

function getRouteAwsSnsConfig(route) {
    const integrationConfig = (
        route && route.integration_config
            ? route.integration_config
            : {}
    );

    return integrationConfig.aws_sns || {};
}

function updateRouteSourceUi() {
    const source = String(
        $("#route-source").val() || ""
    );

    const isSentry = source === "sentry";
    const isAwsSns = source === "aws_sns";

    $("#route-sentry-settings").toggleClass("is-hidden", !isSentry);

    $("#route-aws-sns-settings").toggleClass("is-hidden", !isAwsSns);

    $("#route-aws-sns-topic-arn").prop("required", isAwsSns);

    const hasAwsSnsWebhook = Boolean(
        String(
            $("#route-aws-sns-webhook-url").val() || ""
        ).trim()
    );

    $("#route-aws-sns-webhook-group").toggleClass(
        "is-hidden",
        !isAwsSns || !hasAwsSnsWebhook
    );

    if (!$("#route-id").val()) {
        if (source === "sentry") {
            $("#route-group-by").val(
                '["project_slug","issue_id"]'
            );
        } else if (source === "grafana") {
            $("#route-group-by").val(
                '["alertname","grafana_folder","instance"]'
            );
        } else if (source === "rmon") {
            $("#route-group-by").val(
                '["rmon_check_id","rmon_check_type"]'
            );
        } else if (source === "aws_sns") {
            $("#route-group-by").val(
                '["cloudwatch_alarm_arn"]'
            );
        }
    }
}

function collectRouteIntegrationConfig() {
    const source = $("#route-source").val();

    if (source === "aws_sns") {
        return {
            aws_sns: {
                topic_arn: String(
                    $("#route-aws-sns-topic-arn").val() || ""
                ).trim()
            }
        };
    }

    if (source === "sentry") {
        const secret = String(
            $("#route-sentry-webhook-secret").val() || ""
        ).trim();

        const baseUrl = String(
            $("#route-sentry-base-url").val() || ""
        ).trim();

        const organizationSlug = String(
            $("#route-sentry-organization-slug").val() || ""
        ).trim();

        const sentry = {};

        if (secret) {
            sentry.webhook_secret = secret;
        }

        if (baseUrl) {
            sentry.base_url = baseUrl;
        }

        if (organizationSlug) {
            sentry.organization_slug = organizationSlug;
        }

        return {
            sentry: sentry
        };
    }
    return {};
}

function updateSentrySecretHelp(route) {
    const sentryConfig = getRouteSentryConfig(route);

    if (route && sentryConfig.has_webhook_secret) {
        $("#route-sentry-secret-help").text(
            "Sentry webhook secret is configured. Leave empty to keep the existing secret."
        );
        return;
    }

    if (route && route.id) {
        $("#route-sentry-secret-help").text(
            "Paste Sentry Client Secret here. Until it is configured, Sentry webhooks will be rejected."
        );
        return;
    }

    $("#route-sentry-secret-help").text(
        "Create the route first to get the Sentry webhook URL. Then create a Sentry Internal Integration and paste its Client Secret here."
    );
}

function getRouteGroupByValue() {
    const value = parseJsonInput(
        "#route-group-by",
        []
    );

    if (!Array.isArray(value)) {
        const message = "Route group by must be a JSON array, for example [\"alertname\", \"instance\"]. Use [] to disable cross-alert grouping.";

        if (typeof showAppError === "function") {
            showAppError(message);
        } else {
            alert(message);
        }

        throw new Error(message);
    }

    return value;
}

function collectRoutePayload() {
    const mode = $("#route-escalation-mode").val() || "rotation";
    const usePolicy = mode === "policy";

    return {
        team_id: Number($("#route-team").val()),
        name: $("#route-name").val(),
        source: $("#route-source").val(),
        escalation_mode: mode,
        rotation_id: (
            !usePolicy && $("#route-rotation").val()
                ? Number($("#route-rotation").val())
                : null
        ),

        escalation_policy_id: (
            usePolicy && $("#route-escalation-policy").val()
                ? Number($("#route-escalation-policy").val())
                : null
        ),
        channel_ids: ($("#route-channels").val() || []).map(Number),
        notification_channel_mode: ($("#route-notification-channel-mode").val() || "route_only"),
        service_id: $("#route-service").val() ? Number($("#route-service").val()) : null,
        matcher_preset_id: $("#route-matcher-preset").val() ? Number($("#route-matcher-preset").val()) : null,
        matchers: getMatcherEditorValue("#route-matchers", {}),
        group_by: getRouteGroupByValue(),

        integration_config: collectRouteIntegrationConfig(),

        enabled: $("#route-enabled").is(":checked")
    };
}

function saveRoute() {
    const id = $("#route-id").val();
    const existing = id ? routesCache.find(function (item) {
        return Number(item.id) === Number(id);
    }) : null;
    if (existing && !canWriteObject(existing)) {
        showAppError("Team manager or group editor/admin role is required to edit this route.");
        return;
    }

    if (id) {
        apiPut("/api/routes/" + id, collectRoutePayload(), function () {
            closeAppModal("#route-form-modal");
            resetRouteForm();
            refreshRoutes();
        });
        return;
    }

    const payload = collectRoutePayload();

    apiPost("/api/routes", payload, function (response) {
        closeAppModal("#route-form-modal");
        resetRouteForm();
        refreshRoutes();

        if (payload.source === "aws_sns") {
            showAppSuccess(
                "AWS SNS route created. Copy the webhook URL from route details."
            );
            return;
        }

        showRouteIntakeDetails(response);
    });
}

function editRoute(id) {
    const route = routesCache.find(function (item) {
        return Number(item.id) === Number(id);
    });
    if (!route) {
        return;
    }
    if (!canWriteObject(route)) {
        showAppError("You do not have permission to edit this route.");
        return;
    }

    $("#route-form-title").text("Edit route #" + id);
    $("#route-id").val(route.id);
    $("#route-team").val(route.team_id);
    $("#route-name").val(route.name);
    $("#route-source").val(route.source);
    const integrationConfig = (
        route.integration_config || {}
    );

    const awsSnsConfig = (
        integrationConfig.aws_sns || {}
    );

    const sentryConfig = (
        integrationConfig.sentry || {}
    );

    $("#route-aws-sns-topic-arn").val(
        awsSnsConfig.topic_arn || ""
    );

    const awsSnsWebhookPath = (
        awsSnsConfig.webhook_path || ""
    );

    if (route.source === "aws_sns" && awsSnsWebhookPath) {
        $("#route-aws-sns-webhook-url").val(
            window.location.origin + awsSnsWebhookPath
        );

        $("#route-aws-sns-webhook-group")
            .removeClass("is-hidden");
    } else {
        $("#route-aws-sns-webhook-url").val("");

        $("#route-aws-sns-webhook-group")
            .addClass("is-hidden");
    }

    setMatcherEditorValue("#route-matchers", route.matchers || {});
    $("#route-group-by").val(JSON.stringify(asArray(route.group_by), null, 2));
    $("#route-enabled").prop("checked", !!route.enabled);
    $("#route-sentry-webhook-secret").val("");
    $("#route-sentry-base-url").val(sentryConfig.base_url || "");
    $("#route-sentry-organization-slug").val(sentryConfig.organization_slug || "");

    updateSentrySecretHelp(route);
    updateRouteSourceUi();

    loadRouteDependencies(function () {
        const usePolicy = !!route.escalation_policy_id;

        $("#route-escalation-mode").val(usePolicy ? "policy" : "rotation");
        $("#route-rotation").val(route.rotation_id || "");
        $("#route-escalation-policy").val(route.escalation_policy_id || "");

        $("#route-channels").val(asArray(route.channels).map(function (channel) {
            return String(channel.id);
        }));

        $("#route-service").val(route.service_id || "");
        $("#route-notification-channel-mode").val(route.notification_channel_mode || "route_only");

        updateRouteNotificationChannelModeUi();
        updateRouteEscalationModeUi();
        updateRouteSourceUi();
    }, route.matcher_preset_id || (route.matcher_preset ? route.matcher_preset.id : null));

    openAppModal("#route-form-modal");
}

function disableRoute(route) {
    if (!canWriteObject(route)) {
        showAppError("You do not have permission to disable this route.");
        return;
    }

    const routeName = route.name || ("Route #" + route.id);
    showAppConfirm({
        title: "Disable this route?",
        message: "Disable route \"" + routeName + "\"?\n\nThe route will stop accepting incoming alerts, but it will stay visible and can be enabled again.",
        confirmText: "Disable",
        confirmClass: "btn-warning",
    }).done(function () {
        apiPost("/api/routes/" + route.id + "/disable", {}, function () {
            refreshRoutes();
        });
    });
}

function enableRoute(route) {
    if (!canWriteObject(route)) {
        showAppError("You do not have permission to enable this route.");
        return;
    }

    apiPost("/api/routes/" + route.id + "/enable", {}, function () {
        refreshRoutes();
    });
}

function deleteRoute(route) {
    if (!canDeleteObject(route)) {
        showAppError("You do not have permission to delete this route.");
        return;
    }

    const routeName = route.name || ("Route #" + route.id);
    showAppConfirm({
        title: "Delete this route?",
        message: "Delete route \"" + routeName + "\"?\n\nThis will remove the route from active route lists and stop alert intake for this route. Historical alerts will be preserved.",
        confirmText: "Delete",
        confirmClass: "btn-danger",
    }).done(function () {
        apiDelete("/api/routes/" + route.id, function () {
            if (Number(selectedRouteDetailsId) === Number(route.id)) {
                selectedRouteDetailsId = null;
                renderRouteDetailsEmpty();
            }
            refreshRoutes();
        });
    });
}

function resetRouteForm() {
    $("#route-form-title").text("Create route");
    $("#route-id").val("");
    $("#route-name").val("");
    $("#route-source").val("alertmanager");
    setMatcherEditorValue("#route-matchers", {});
    $("#route-group-by").val('["alertname","instance"]');
    $("#route-enabled").prop("checked", true);
    $("#route-rotation").val("");
    $("#route-channels").val([]);
    $("#route-escalation-mode").val("rotation");
    $("#route-escalation-policy").val("");
    $("#route-service").val("");
    fillMatcherPresetSelect("#route-matcher-preset", routeMatcherPresetsCache, null);
    updateRouteMatcherPresetHint();
    $("#route-aws-sns-topic-arn").val("");
    $("#route-aws-sns-webhook-url").val("");
    $("#route-aws-sns-webhook-group").addClass("is-hidden");
    updateRouteEscalationModeUi();
    $("#route-sentry-webhook-secret").val("");
    $("#route-sentry-base-url").val("");
    $("#route-sentry-organization-slug").val("");
    $("#route-notification-channel-mode").val("route_only");
    updateRouteNotificationChannelModeUi();
    updateSentrySecretHelp(null);
    updateRouteSourceUi();
}

function getRouteIntakePath(route) {
    const source = String(route.source || "").toLowerCase();

    if (source === "sentry") {
        return "/api/integrations/sentry/" + route.id;
    }

    if (source === "aws_sns") {
        const awsSnsConfig = getRouteAwsSnsConfig(route);

        return (
            awsSnsConfig.webhook_path
            || ("/api/integrations/aws-sns/" + route.id)
        );
    }

    if (source === "alertmanager") {
        return "/api/integrations/alertmanager";
    }

    if (source === "zabbix") {
        return "/api/integrations/zabbix";
    }

    if (source === "webhook") {
        return "/api/integrations/webhook";
    }

    return "/api/integrations/" + source;
}

function getRouteIntakeUrl(route) {
    return window.location.origin + getRouteIntakePath(route);
}

function buildRouteIntakeCurl(route, token) {
    const url = getRouteIntakeUrl(route);
    const source = String(route.source || "").toLowerCase();

    if (source === "sentry") {
        return [
            "curl -X POST '" + url + "' \\",
            "  -H 'Content-Type: application/json' \\",
            "  -H 'Sentry-Hook-Resource: event_alert' \\",
            "  -H 'Sentry-Hook-Signature: <generated-by-sentry>' \\",
            "  -d '{\"action\":\"triggered\",\"data\":{}}'"
        ].join("\n");
    }

    return [
        "curl -X POST '" + url + "' \\",
        "  -H 'Content-Type: application/json' \\",
        "  -H 'Authorization: Bearer " + (token || "<route-token>") + "' \\",
        "  -d '{}'"
    ].join("\n");
}

function showRouteIntakeDetails(route) {
    const source = String(route.source || "").toLowerCase();
    const token = route.intake_token || "";
    const isSentry = source === "sentry";
    const url = getRouteIntakeUrl(route);

    $("#route-intake-title").text(
        isSentry ? "Sentry webhook URL" : "Route intake details"
    );

    $("#route-intake-subtitle").text(
        isSentry
            ? "Copy this URL to Sentry Internal Integration. Then paste Sentry Client Secret into this route settings."
            : "Copy this token now. It may not be shown again."
    );

    $("#route-intake-url").val(url);
    $("#route-intake-token").val(token);
    $("#route-intake-curl").val(buildRouteIntakeCurl(route, token));

    $("#route-intake-token-group").toggleClass("is-hidden", isSentry);
    $("#copy-route-intake-token").toggleClass("is-hidden", isSentry);

    $("#route-intake-url-help").text(
        isSentry
            ? "Use this URL as Webhook URL in Sentry Internal Integration."
            : "Send alerts to this URL and pass the token as Authorization: Bearer."
    );

    openAppModal("#route-token-box");
}

function closeRouteTokenModal() {
    closeAppModal("#route-token-box");
    $("#route-intake-url").val("");
    $("#route-intake-token").val("");
    $("#route-intake-curl").val("");
}

function regenerateRouteToken(routeId) {
    const route = routesCache.find(function (item) {
        return Number(item.id) === Number(routeId);
    });
    if (route && !canWriteObject(route)) {
        showAppError("You do not have permission to regenerate this route token.");
        return;
    }

    showAppConfirm({
        title: "Regenerate route intake token?",
        message: "Regenerate route intake token? Existing token will stop working.",
        confirmText: "Regenerate",
        confirmClass: "btn-warning",
    }).done(function () {
        apiPost("/api/routes/" + routeId + "/intake-token", {}, function (response) {
            showRouteIntakeDetails(response);
            refreshRoutes();
        });
    });
}

function openCreateRouteModal() {
    resetRouteForm();
    $("#route-form-title").text("Create route");
    loadRouteDependencies();
    openAppModal("#route-form-modal");
}
function copyTextFromField(selector) {
    const value = $(selector).val() || "";

    if (!value) {
        return;
    }

    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(value);
        return;
    }

    const field = $(selector);
    field.trigger("select");
    document.execCommand("copy");
}
function copyRouteIntakeToken() {
    copyTextFromField("#route-intake-token");
}

function copyRouteIntakeUrl() {
    copyTextFromField("#route-intake-url");
}

function copyRouteIntakeCurl() {
    copyTextFromField("#route-intake-curl");
}

function initRoutesTableSorting() {
    bindSortableTableHeaders(
        "#routes-table-view",
        routesSortState,
        routesSortColumns,
        renderRoutesTable
    );
}

function getFilteredRoutes() {
    const query = String($("#routes-search").val() || "").trim().toLowerCase();
    const source = String($("#routes-source-filter").val() || "");
    const status = String($("#routes-status-filter").val() || "");

    const filtered = routesCache.filter(function (route) {
        if (source && route.source !== source) {
            return false;
        }
        if (status === "enabled" && !route.enabled) {
            return false;
        }
        if (status === "disabled" && route.enabled) {
            return false;
        }
        if (!query) {
            return true;
        }
        return getRouteSearchText(route).indexOf(query) !== -1;
    });

    return sortTableData(filtered, routesSortState, routesSortColumns);
}

$(document).on("change", "#route-team", function () {
    loadRouteDependencies();
});
$(document).on("change", "#route-source", updateRouteSourceUi);
$(document).on("input", "#routes-search", renderRoutesTable);
$(document).on("change", "#routes-source-filter, #routes-status-filter", renderRoutesTable);
$(document).on("click", "#open-route-create-modal", openCreateRouteModal);
$(document).on("click", "#save-route", saveRoute);
$(document).on("click", "#reset-route-form", resetRouteForm);
$(document).on("click", "#reload-routes", refreshRoutes);
$(document).on("click", "#close-route-form-modal", function () {
    closeAppModal("#route-form-modal");
});
$(document).on("click", "#close-route-token-modal, #close-route-token-modal-footer", closeRouteTokenModal);
$(document).on("click", "#copy-route-intake-token", copyRouteIntakeToken);
$(document).on("click", "#route-form-modal", function (event) {
    if (event.target === this) {
        closeAppModal("#route-form-modal");
    }
});
$(document).on("click", "#route-token-box", function (event) {
    if (event.target === this) {
        closeRouteTokenModal();
    }
});
$(document).on("keydown", function (event) {
    if (event.key !== "Escape") {
        return;
    }
    if ($("#route-token-box").hasClass("is-open")) {
        closeRouteTokenModal();
        return;
    }
    if ($("#route-form-modal").hasClass("is-open")) {
        closeAppModal("#route-form-modal");
    }
});
$(document).on("change", "#route-rotation", function () {
    if ($(this).val()) {
        $("#route-escalation-mode").val("rotation");
        $("#route-escalation-policy").val("");
    }

    updateRouteEscalationModeUi();
});
$(document).on("change", "#route-escalation-policy", function () {
    if ($(this).val()) {
        $("#route-escalation-mode").val("policy");
    }

    updateRouteEscalationModeUi();
});
function updateRouteEscalationModeUi() {
    const mode = $("#route-escalation-mode").val() || "rotation";
    const usePolicy = mode === "policy";

    $("#route-rotation")
        .prop("disabled", usePolicy)
        .closest(".form-group")
        .toggleClass("is-muted", usePolicy);

    $("#route-escalation-policy")
        .prop("disabled", !usePolicy);

    $("#route-policy-group").toggleClass("is-hidden", !usePolicy);
}
$(document).on("change", "#route-escalation-mode", updateRouteEscalationModeUi);
$(document).on("click", "#save-service-rule", saveRouteServiceRule);

$(document).on("click", "#reset-service-rule-form", resetServiceRuleForm);


$(document).on("click", "#close-route-service-rules-modal", function () {
    closeAppModal("#route-service-rules-modal");
});

$(document).on("click", "#route-service-rules-modal", function (event) {
    if (event.target === this) {
        closeAppModal("#route-service-rules-modal");
    }
});
$(document).on("click", "#copy-route-intake-url", copyRouteIntakeUrl);
$(document).on("click", "#copy-route-intake-curl", copyRouteIntakeCurl);
$(document).on("change", "#route-notification-channel-mode", updateRouteNotificationChannelModeUi);
$(document).on("change", "#route-matcher-preset", updateRouteMatcherPresetHint);
$(document).on("change", "#service-rule-matcher-preset", updateServiceRuleMatcherPresetHint);
