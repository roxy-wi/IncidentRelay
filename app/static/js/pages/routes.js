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
        return i18n.t("routes.escalation.policy", {
            name: route.escalation_policy_name,
        });
    }

    if (route.rotation_name) {
        return i18n.t("routes.escalation.rotation", {
            name: route.rotation_name,
        });
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
        return i18n.t("routes.notification.service_policy");
    }

    if (mode === "service_policy_plus_route") {
        return i18n.t("routes.notification.combined");
    }

    return i18n.t("routes.notification.route_only");
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

    let helpKey = "routes.notification.route_only_help";

    if (mode === "service_policy") {
        helpKey = "routes.notification.service_policy_help";
    } else if (mode === "service_policy_plus_route") {
        helpKey = "routes.notification.combined_help";
    }

    $("#route-notification-channel-mode-help").text(i18n.t(helpKey));
}

function getRouteTeamEscalationLabel(route) {
    if (route.escalation_policy_name) {
        return i18n.t("routes.escalation.ignored_policy");
    }

    if (route.team_escalation_enabled) {
        return i18n.t("routes.escalation.after_reminders", {
            count: route.team_escalation_after_reminders || 0,
        });
    }

    return i18n.t("routes.status.disabled");
}
function initializeRouteMatcherEditors() {
    enhanceMatcherEditor("#route-matchers", {
        label: i18n.t("routes.form.additional_matchers_json"),
        header: i18n.t("routes.form.additional_matchers"),
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
        label: i18n.t("routes.form.additional_matchers"),
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

    rotationSelect.empty().append($("<option>").val("").text(i18n.t("routes.form.no_rotation")));
    channelSelect.empty();

    if (policySelect.length) {
        policySelect.empty().append($("<option>").val("").text(i18n.t("routes.form.no_policy")));
    }

    if (serviceSelect.length) {
        serviceSelect.empty().append($("<option>").val("").text(i18n.t("routes.form.no_default_service")));
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
        rotationSelect.empty().append($("<option>").val("").text(i18n.t("routes.form.no_rotation")));

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
            policySelect.empty().append($("<option>").val("").text(i18n.t("routes.form.no_policy")));

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
            serviceSelect.empty().append($("<option>").val("").text(i18n.t("routes.form.no_default_service")));

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
        azure_monitor: true,
        datadog: true,
        new_relic: true,
        nagios: true,
        grafana: true,
        rmon: true,
        heartbeat: true,
        zabbix: true,
        webhook: true,
        sentry: true,
        librenms: true,
        uptime_kuma: true
    };

    asArray(routes).forEach(function (route) {
        if (route.source) {
            sources[route.source] = true;
        }
    });

    filter.empty();
    filter.append($("<option>").val("").text(i18n.t("routes.filters.all_sources")));
    Object.keys(sources).sort().forEach(function (source) {
        filter.append($("<option>").val(source).text(source));
    });
    if (selected && sources[selected]) {
        filter.val(selected);
    }

    if (window.PageUrlState) {
        window.PageUrlState.restoreFields("routes");
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
        route.enabled ? i18n.t("routes.status.enabled") : i18n.t("routes.status.disabled"),
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
                $("<td>")
                    .attr("colspan", "8")
                    .addClass("empty-cell")
                    .text(i18n.t("routes.table.empty"))
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
            .append(
                $("<div>")
                    .addClass("row-subtitle")
                    .text(i18n.t("routes.row.number", {id: route.id}))
            )
    );
    row.append($("<td>").append($("<span>").addClass("route-pill").text(getRouteTeamLabel(route))));
    row.append($("<td>").text(route.source || "-"));
    row.append($("<td>").text(getRouteEscalationLabel(route)));
    row.append($("<td>").append(renderRouteChannels(route)));
    row.append($("<td>").append($("<span>").addClass("token-pill").text(route.intake_token_prefix || "-")));
    row.append(
        window.AppMaintenanceBadges.statusCell(
            renderStatusBadge(
                route.enabled,
                i18n.t("routes.status.enabled"),
                i18n.t("routes.status.disabled")
            ),
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
                .text(i18n.t("routes.notification.service_policy"))
        );
    }

    if (mode === "service_policy_plus_route") {
        wrapper.append(
            $("<span>")
                .addClass("route-channel-chip")
                .text(i18n.t("routes.notification.service_policy"))
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
            label: i18n.t("routes.actions.edit"),
            icon: "fas fa-edit",
            required: "write",
            denyMessage: i18n.t("routes.permissions.edit"),
            onClick: function () {
                editRoute(route.id);
            }
        }
    ];

    if (!["sentry", "aws_sns"].includes(route.source)) {
        items.push({
            label: i18n.t("routes.actions.regenerate_token"),
            icon: "fas fa-sync-alt",
            required: "write",
            denyMessage: i18n.t("routes.permissions.regenerate"),
            onClick: function () {
                regenerateRouteToken(route.id);
            }
        });
    }

    items.push(
        {
            label: i18n.t("routes.actions.service_rules"),
            icon: "fas fa-project-diagram",
            required: "write",
            denyMessage: i18n.t("routes.permissions.rules"),
            onClick: function () {
                openRouteServiceRules(route.id);
            }
        },
        {
            label: route.enabled
                ? i18n.t("routes.actions.disable")
                : i18n.t("routes.actions.enable"),
            icon: route.enabled ? "fas fa-pause" : "fas fa-play",
            required: "write",
            danger: route.enabled,
            denyMessage: i18n.t("routes.permissions.toggle"),
            onClick: function () {
                if (route.enabled) {
                    disableRoute(route);
                } else {
                    enableRoute(route);
                }
            }
        },
        {
            label: i18n.t("routes.actions.delete"),
            icon: "fas fa-trash",
            required: "delete",
            danger: true,
            denyMessage: i18n.t("routes.permissions.delete"),
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
        showAppError(i18n.t("routes.permissions.rules_denied"));
        return;
    }

    selectedRouteForServiceRules = route.id;

    $("#route-service-rules-title").text(
        i18n.t("routes.rules.title_named", {
            name: route.name || i18n.t("routes.row.number", {id: route.id}),
        })
    );
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
    select.append($("<option>").val("").text(i18n.t("routes.rules.select_service")));

    if (!teamId) {
        if (typeof callback === "function") {
            callback();
        }
        return;
    }

    apiGet("/api/services?team_id=" + encodeURIComponent(teamId), function (services) {
        select.empty();
        select.append($("<option>").val("").text(i18n.t("routes.rules.select_service")));

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
                    .text(i18n.t("routes.rules.empty"))
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
                .text(
                    i18n.t("routes.rules.preset", {
                        name: formatMatcherPresetOption(matcherPreset),
                    })
                )
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
            renderStatusBadge(
                rule.enabled,
                i18n.t("routes.status.enabled"),
                i18n.t("routes.status.disabled")
            )
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
                            label: i18n.t("routes.actions.edit"),
                            icon: "fas fa-edit",
                            required: "write",
                            onClick: function () {
                                editRouteServiceRule(rule);
                            }
                        },
                        {
                            label: i18n.t("routes.actions.delete"),
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
    $("#service-rule-form-title").text(i18n.t("routes.rules.create"));
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
    $("#service-rule-form-title").text(i18n.t("routes.rules.edit"));
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
        showAppError(i18n.t("routes.rules.service_required"));
        return;
    }

    if (!payload.matcher_preset_id && !Object.keys(payload.matchers || {}).length) {
        showAppError(i18n.t("routes.rules.matcher_required"));
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
        title: i18n.t("routes.rules.delete_title"),
        message: i18n.t("routes.rules.delete_message", {
            name: rule.name || ("#" + rule.id),
        }),
        confirmText: i18n.t("routes.actions.delete"),
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

function renderRouteDetails(route, options) {
    options = options || {};
    selectedRouteDetailsId = route.id;

    $("#route-details-subtitle").text(
        getRouteTeamLabel(route)
        + " / "
        + (
            route.enabled
                ? i18n.t("routes.status.enabled")
                : i18n.t("routes.status.disabled")
        )
    );

    const body = $("#route-details-body");
    body.empty();

    const detailsGrid = $("<div>").addClass("details-grid");
    detailsGrid
        .append(routeDetailsItem(i18n.t("routes.details.name"), route.name))
        .append(routeDetailsItem(i18n.t("routes.details.team"), getRouteTeamLabel(route)))
        .append(routeDetailsItem(i18n.t("routes.details.source"), route.source))
        .append(
            route.source === "sentry"
                ? routeDetailsItem(
                    i18n.t("routes.details.sentry_secret"),
                    getRouteSentryConfig(route).has_webhook_secret
                        ? i18n.t("routes.details.configured")
                        : i18n.t("routes.details.not_configured")
                )
                : $()
        )
        .append(
            route.source === "sentry"
                ? routeDetailsItem(
                    i18n.t("routes.details.sentry_base_url"),
                    getRouteSentryConfig(route).base_url || "-"
                )
                : $()
        )
        .append(
            route.source === "sentry"
                ? routeDetailsItem(
                    i18n.t("routes.details.sentry_org"),
                    getRouteSentryConfig(route).organization_slug || "-"
                )
                : $()
        )
        .append(
            routeDetailsItem(
                i18n.t("routes.details.maintenance"),
                window.AppMaintenanceBadges.text(route, "-")
            )
        )
        .append(routeDetailsItem(i18n.t("routes.details.escalation"), getRouteEscalationLabel(route)))
        .append(routeDetailsItem(i18n.t("routes.details.team_escalation"), getRouteTeamEscalationLabel(route)))
        .append(routeDetailsItem(i18n.t("routes.details.notification_source"), getRouteNotificationModeLabel(route)))
        .append(routeDetailsItem(i18n.t("routes.details.channels"), asArray(route.channels).map(function (channel) {
            return channel.name;
        }).join(", ") || "-"))
        .append(
            !["sentry", "aws_sns"].includes(route.source)
                ? routeDetailsItem(
                    i18n.t("routes.details.token_prefix"),
                    route.intake_token_prefix
                )
                : $()
        )
        .append(
            routeDetailsItem(
                i18n.t("routes.details.status"),
                route.enabled
                    ? i18n.t("routes.status.enabled")
                    : i18n.t("routes.status.disabled")
            )
        )
        .append(
            routeDetailsItem(
                i18n.t("routes.details.matcher_preset"),
                route.matcher_preset
                    ? formatMatcherPresetOption(route.matcher_preset)
                    : i18n.t("routes.form.no_preset")
            )
        )
        .append(routeDetailsItem(i18n.t("routes.details.service"), route.service_name || route.service_slug || "-"));

    body.append(detailsGrid);

    // Keep long identifiers and structured values full-width so the compact
    // summary grid stays readable even for long URLs, ARNs and matcher JSON.
    const fullWidthDetails = $("<div>").addClass("details-list");

    if (route.source === "sentry") {
        fullWidthDetails.append(
            routeDetailsItem(
                i18n.t("routes.details.sentry_webhook"),
                getSentryWebhookUrl(route)
            )
        );
    }

    fullWidthDetails.append(
        routeDetailsItem(
            route.source === "aws_sns"
                ? i18n.t("routes.details.sns_webhook")
                : i18n.t("routes.details.webhook"),
            getRouteIntakeUrl(route)
        )
    );

    if (route.source === "aws_sns") {
        const awsSnsConfig = getRouteAwsSnsConfig(route);
        fullWidthDetails.append(
            routeDetailsItem(
                i18n.t("routes.details.sns_topic"),
                awsSnsConfig.topic_arn
            )
        );
    }

    fullWidthDetails
        .append(routeDetailsCode(i18n.t("routes.details.additional_matchers"), route.matchers || {}))
        .append(routeDetailsCode(i18n.t("routes.details.group_by"), asArray(route.group_by)));

    body.append(fullWidthDetails);

    const actions = $("<div>").addClass("details-actions");
    appendIconActionIfAllowed(actions, route, {
        required: "write",
        icon: "fas fa-edit",
        label: i18n.t("routes.actions.edit_route"),
        onClick: function () {
            editRoute(route.id);
        },
    });
    if (!["sentry", "aws_sns"].includes(route.source)) {
        appendIconActionIfAllowed(actions, route, {
            required: "write",
            icon: "fas fa-sync-alt",
            label: i18n.t("routes.actions.regenerate_route_token"),
            onClick: function () {
                regenerateRouteToken(route.id);
            },
        });
    }
    appendIconActionIfAllowed(actions, route, {
        required: "write",
        icon: route.enabled ? "fas fa-pause" : "fas fa-play",
        label: route.enabled
            ? i18n.t("routes.actions.disable_route")
            : i18n.t("routes.actions.enable_route"),
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
        label: i18n.t("routes.actions.delete_route"),
        className: "btn-danger",
        onClick: function () {
            deleteRoute(route);
        },
    });

    if (actions.children().length) {
        body.append(actions);
    }

    if (options.open !== false) {
        openAppModal("#route-details-modal");
    }
}

function renderRouteDetailsEmpty() {
    selectedRouteDetailsId = null;
    $("#route-details-subtitle").text("");
    $("#route-details-body").empty();
    closeAppModal("#route-details-modal");
}

function restoreRouteDetails() {
    if (!selectedRouteDetailsId) {
        return;
    }

    const selected = routesCache.find(function (route) {
        return Number(route.id) === Number(selectedRouteDetailsId);
    });

    if (!selected) {
        renderRouteDetailsEmpty();
        return;
    }

    if ($("#route-details-modal").hasClass("is-open")) {
        renderRouteDetails(selected, {open: false});
    }
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
    const isDatadog = source === "datadog";
    const isNewRelic = source === "new_relic";
    const isAzureMonitor = source === "azure_monitor";
    const isNagios = source === "nagios";
    const isUptimeKuma = source === "uptime_kuma";
    const isWebhook = source === "webhook";

    $("#route-sentry-settings").toggleClass("is-hidden", !isSentry);
    $("#route-webhook-compatibility-help").toggleClass(
        "is-hidden",
        !isWebhook
    );
    $("#route-datadog-help").toggleClass(
        "is-hidden",
        !isDatadog
    );
    $("#route-new-relic-help").toggleClass(
        "is-hidden",
        !isNewRelic
    );
    $("#route-azure-monitor-help").toggleClass(
        "is-hidden",
        !isAzureMonitor
    );
    $("#route-nagios-help").toggleClass(
        "is-hidden",
        !isNagios
    );
    $("#route-uptime-kuma-help").toggleClass(
        "is-hidden",
        !isUptimeKuma
    );

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
        } else if (source === "datadog") {
            $("#route-group-by").val(
                '["datadog_alert_id","datadog_scope"]'
            );
        } else if (source === "new_relic") {
            $("#route-group-by").val(
                '["new_relic_issue_id"]'
            );
        } else if (source === "azure_monitor") {
            $("#route-group-by").val(
                '["azure_alert_id"]'
            );
        } else if (source === "nagios") {
            $("#route-group-by").val(
                '["nagios_host","nagios_service"]'
            );
        } else if (source === "rmon") {
            $("#route-group-by").val(
                '["rmon_check_id","rmon_check_type"]'
            );
        } else if (source === "uptime_kuma") {
            $("#route-group-by").val(
                '["uptime_kuma_monitor_id"]'
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
    let key = "routes.form.sentry_secret_new_help";

    if (route && sentryConfig.has_webhook_secret) {
        key = "routes.form.sentry_secret_configured_help";
    } else if (route && route.id) {
        key = "routes.form.sentry_secret_missing_help";
    }

    $("#route-sentry-secret-help").text(i18n.t(key));
}

function getRouteGroupByValue() {
    const value = parseJsonInput(
        "#route-group-by",
        []
    );

    if (!Array.isArray(value)) {
        const message = i18n.t("routes.validation.group_by");

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
        showAppError(i18n.t("routes.permissions.edit"));
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
                i18n.t("routes.success.sns_created")
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
        showAppError(i18n.t("routes.permissions.edit_denied"));
        return;
    }

    $("#route-form-title").text(i18n.t("routes.form.edit", {id: id}));
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
        showAppError(i18n.t("routes.permissions.disable_denied"));
        return;
    }

    const routeName = route.name || i18n.t("routes.row.number", {id: route.id});
    showAppConfirm({
        title: i18n.t("routes.confirm.disable_title"),
        message: i18n.t("routes.confirm.disable_message", {
            name: routeName,
        }),
        confirmText: i18n.t("routes.actions.disable"),
        confirmClass: "btn-warning",
    }).done(function () {
        apiPost("/api/routes/" + route.id + "/disable", {}, function () {
            refreshRoutes();
        });
    });
}

function enableRoute(route) {
    if (!canWriteObject(route)) {
        showAppError(i18n.t("routes.permissions.enable_denied"));
        return;
    }

    apiPost("/api/routes/" + route.id + "/enable", {}, function () {
        refreshRoutes();
    });
}

function deleteRoute(route) {
    if (!canDeleteObject(route)) {
        showAppError(i18n.t("routes.permissions.delete_denied"));
        return;
    }

    const routeName = route.name || i18n.t("routes.row.number", {id: route.id});
    showAppConfirm({
        title: i18n.t("routes.confirm.delete_title"),
        message: i18n.t("routes.confirm.delete_message", {
            name: routeName,
        }),
        confirmText: i18n.t("routes.actions.delete"),
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
    $("#route-form-title").text(i18n.t("routes.form.create"));
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

    if (source === "heartbeat") {
        return "/api/heartbeats/ping/<heartbeat-token>";
    }

    if (source === "zabbix") {
        return "/api/integrations/zabbix";
    }

    if (source === "new_relic") {
        return "/api/integrations/new-relic";
    }

    if (source === "azure_monitor") {
        return "/api/integrations/azure-monitor";
    }

    if (source === "nagios") {
        return "/api/integrations/nagios";
    }

    if (source === "uptime_kuma") {
        return "/api/integrations/uptime-kuma";
    }

    if (source === "webhook") {
        return "/api/integrations/webhook";
    }

    return "/api/integrations/" + source;
}

function getRouteIntakeUrl(route) {
    return window.location.origin + getRouteIntakePath(route);
}

function getAzureMonitorWebhookUrl(route, token) {
    const url = new URL(getRouteIntakeUrl(route));
    url.username = "incidentrelay";
    url.password = token || "<route-token>";
    return url.toString();
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

    if (source === "heartbeat") {
        return [
            "curl -fsS -X POST '" + url + "' \\",
            "  -H 'Content-Type: application/json' \\",
            "  -d '{}'"
        ].join("\n");
    }

    if (source === "datadog") {
        return [
            "# " + i18n.t("routes.intake.datadog_example_comment"),
            `curl -X POST '${url}' \\`,
            "  -H 'Content-Type: application/json' \\",
            `  -H 'Authorization: Bearer ${token || "<route-token>"}' \\`,
            "  -d '{\"alert_title\":\"[Triggered] Example monitor\",\"text_only_msg\":\"Example Datadog alert\",\"alert_id\":\"1234\",\"alert_cycle_key\":\"cycle-example-1\",\"alert_transition\":\"Triggered\",\"alert_type\":\"error\",\"alert_priority\":\"P1\",\"alert_scope\":\"env:prod,service:api\",\"hostname\":\"api-01\",\"link\":\"https://app.datadoghq.com/monitors/1234\",\"tags\":\"env:prod,service:api\"}'"
        ].join("\n");
    }

    if (source === "new_relic") {
        return [
            "# " + i18n.t("routes.intake.new_relic_example_comment"),
            `curl -X POST '${url}' \\`,
            "  -H 'Content-Type: application/json' \\",
            `  -H 'Authorization: Bearer ${token || "<route-token>"}' \\`,
            "  -d '{\"issue_id\":\"issue-example-1\",\"title\":\"API latency is high\",\"state\":\"ACTIVATED\",\"status\":\"CREATED\",\"priority\":\"CRITICAL\",\"issue_url\":\"https://one.newrelic.com/redirects/issue/issue-example-1\",\"condition_name\":\"API latency\",\"policy_name\":\"Production API\",\"entity_name\":\"checkout-api\",\"labels\":{\"environment\":\"production\",\"team\":\"sre\"}}'"
        ].join("\n");
    }

    if (source === "azure_monitor") {
        return [
            "# " + i18n.t("routes.intake.azure_monitor_example_comment"),
            `curl -X POST '${url}' \\`,
            "  -H 'Content-Type: application/json' \\",
            `  -u 'incidentrelay:${token || "<route-token>"}' \\`,
            "  -d '{\"schemaId\":\"azureMonitorCommonAlertSchema\",\"data\":{\"essentials\":{\"alertId\":\"/subscriptions/example/providers/Microsoft.AlertsManagement/alerts/example-1\",\"alertRule\":\"Example alert\",\"severity\":\"Sev1\",\"signalType\":\"Metric\",\"monitorCondition\":\"Fired\",\"monitoringService\":\"Platform\"},\"customProperties\":{\"team\":\"sre\",\"service\":\"api\"}}}'"
        ].join("\n");
    }

    if (source === "nagios") {
        return [
            "# " + i18n.t("routes.intake.nagios_example_comment"),
            `curl -X POST '${url}' \\`,
            "  -H 'Content-Type: application/json' \\",
            `  -H 'Authorization: Bearer ${token || "<route-token>"}' \\`,
            "  -d '{\"notification_type\":\"PROBLEM\",\"host_name\":\"db01\",\"service_description\":\"Disk Usage\",\"service_state\":\"CRITICAL\",\"service_output\":\"/var is 96% full\"}'"
        ].join("\n");
    }

    if (source === "uptime_kuma") {
        return [
            "# " + i18n.t("routes.intake.uptime_kuma_example_comment"),
            `curl -X POST '${url}' \\`,
            "  -H 'Content-Type: application/json' \\",
            `  -H 'Authorization: Bearer ${token || "<route-token>"}' \\`,
            "  -d '{\"heartbeat\":{\"monitorID\":42,\"status\":0,\"msg\":\"Connection refused\",\"ping\":null},\"monitor\":{\"id\":42,\"name\":\"Production API\",\"type\":\"http\",\"url\":\"https://api.example.com\",\"tags\":[{\"name\":\"team\",\"value\":\"sre\"}]},\"msg\":\"Production API is DOWN\"}'"
        ].join("\n");
    }

    if (source === "webhook") {
        return [
            "# " + i18n.t("routes.intake.generic_example_comment"),
            "curl -X POST '" + url + "' \\",
            "  -H 'Content-Type: application/json' \\",
            "  -H 'Authorization: Bearer " + (token || "<route-token>") + "' \\",
            "  -d '{\"title\":\"Example alert\",\"severity\":\"critical\",\"fingerprint\":\"example-1\"}'",
            "",
            "# " + i18n.t("routes.intake.pagerduty_example_comment"),
            "curl -X POST '" + url + "' \\",
            "  -H 'Content-Type: application/json' \\",
            "  -d '{\"routing_key\":\"" + (token || "<route-token>") + "\",\"event_action\":\"trigger\",\"dedup_key\":\"example-1\",\"payload\":{\"summary\":\"Example alert\",\"source\":\"example-host\",\"severity\":\"critical\"}}'"
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
    const isHeartbeat = source === "heartbeat";
    const isDatadog = source === "datadog";
    const isNewRelic = source === "new_relic";
    const isAzureMonitor = source === "azure_monitor";
    const isNagios = source === "nagios";
    const isUptimeKuma = source === "uptime_kuma";
    const isWebhook = source === "webhook";
    const url = getRouteIntakeUrl(route);

    let titleKey = "routes.intake.title";
    let subtitleKey = "routes.intake.route_subtitle";
    let helpKey = "routes.intake.route_help";

    if (isSentry) {
        titleKey = "routes.intake.sentry_title";
        subtitleKey = "routes.intake.sentry_subtitle";
        helpKey = "routes.intake.sentry_help";
    } else if (isHeartbeat) {
        titleKey = "routes.intake.heartbeat_title";
        subtitleKey = "routes.intake.heartbeat_subtitle";
        helpKey = "routes.intake.heartbeat_help";
    } else if (isDatadog) {
        subtitleKey = "routes.intake.datadog_subtitle";
        helpKey = "routes.intake.datadog_help";
    } else if (isNewRelic) {
        subtitleKey = "routes.intake.new_relic_subtitle";
        helpKey = "routes.intake.new_relic_help";
    } else if (isAzureMonitor) {
        subtitleKey = "routes.intake.azure_monitor_subtitle";
        helpKey = "routes.intake.azure_monitor_help";
    } else if (isNagios) {
        subtitleKey = "routes.intake.nagios_subtitle";
        helpKey = "routes.intake.nagios_help";
    } else if (isUptimeKuma) {
        subtitleKey = "routes.intake.uptime_kuma_subtitle";
        helpKey = "routes.intake.uptime_kuma_help";
    } else if (isWebhook) {
        subtitleKey = "routes.intake.webhook_subtitle";
        helpKey = "routes.intake.webhook_help";
    }

    $("#route-intake-title").text(i18n.t(titleKey));
    $("#route-intake-subtitle").text(i18n.t(subtitleKey));

    $("#route-intake-url").val(
        isAzureMonitor
            ? getAzureMonitorWebhookUrl(route, token)
            : url
    );
    $("#route-intake-token").val(token);
    $("#route-intake-curl").val(buildRouteIntakeCurl(route, token));

    $("#route-intake-token-group").toggleClass("is-hidden", isSentry || isHeartbeat);
    $("#copy-route-intake-token").toggleClass("is-hidden", isSentry || isHeartbeat);
    $("#route-intake-url-help").text(i18n.t(helpKey));

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
        showAppError(i18n.t("routes.permissions.regenerate_denied"));
        return;
    }

    showAppConfirm({
        title: i18n.t("routes.confirm.regenerate_title"),
        message: i18n.t("routes.confirm.regenerate_message"),
        confirmText: i18n.t("routes.actions.regenerate"),
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
    $("#route-form-title").text(i18n.t("routes.form.create"));
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
        function () {
            if (window.PageUrlState) {
                window.PageUrlState.write("routes");
            }
            renderRoutesTable();
        }
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
