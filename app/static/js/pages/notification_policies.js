let notificationPoliciesCache = [];
let selectedNotificationPolicyDetailsId = null;
let selectedNotificationPolicyRulesId = null;
let notificationPolicyRulesCache = [];
let notificationPolicyChannelsCache = [];
let expandedNotificationPolicyRuleId = null;
let unsavedNotificationPolicyRuleCounter = 0;
let notificationPolicyMatcherPresetsCache = [];

function isUnsavedNotificationPolicyRule(ruleOrId) {
    const value = typeof ruleOrId === "object" ? ruleOrId.id : ruleOrId;
    return String(value || "").indexOf("new-") === 0;
}

function isSameNotificationPolicyRuleId(left, right) {
    return String(left) === String(right);
}

function loadNotificationPolicies() {
    fillTeamSelect("#notification-policy-team", false, function () {
        resetNotificationPolicyForm();
    });
    refreshNotificationPolicies();
    updateNotificationPolicyCreateButtonState();
}

function buildNotificationPoliciesApiUrl() {
    return "/api/notification-policies" + selectedTeamQuery();
}

function updateNotificationPolicyCreateButtonState() {
    const allowed = currentUserCanCreateUiObjects();

    $("#open-notification-policy-create-modal")
        .toggleClass("is-hidden", !allowed)
        .prop("disabled", !allowed);
}

function refreshNotificationPolicies() {
    apiGet(buildNotificationPoliciesApiUrl(), function (policies) {
        notificationPoliciesCache = asArray(policies);
        renderNotificationPoliciesSummary();
        renderNotificationPoliciesTable();
        restoreNotificationPolicyDetails();
        updateNotificationPolicyCreateButtonState();
    });
}

function renderNotificationPoliciesSummary() {
    const enabled = notificationPoliciesCache.filter(function (policy) {
        return !!policy.enabled;
    }).length;

    const rules = notificationPoliciesCache.reduce(function (total, policy) {
        return total + Number(policy.rules_count || 0);
    }, 0);

    const services = notificationPoliciesCache.reduce(function (total, policy) {
        return total + Number(policy.services_count || 0);
    }, 0);

    $("#notification-policies-summary-total").text(
        notificationPoliciesCache.length
    );
    $("#notification-policies-summary-enabled").text(enabled);
    $("#notification-policies-summary-rules").text(rules);
    $("#notification-policies-summary-services").text(services);
}

function getNotificationPolicySearchText(policy) {
    return [
        policy.id,
        policy.name,
        policy.description,
        policy.team_name,
        policy.team_slug,
        policy.enabled ? i18n.t("notification_policies.status.enabled") : i18n.t("notification_policies.status.disabled"),
    ].join(" ").toLowerCase();
}

function getFilteredNotificationPolicies() {
    const query = String(
        $("#notification-policies-search").val() || ""
    ).trim().toLowerCase();

    const status = String(
        $("#notification-policies-status-filter").val() || ""
    );

    return notificationPoliciesCache.filter(function (policy) {
        if (status === "enabled" && !policy.enabled) {
            return false;
        }

        if (status === "disabled" && policy.enabled) {
            return false;
        }

        return !query
            || getNotificationPolicySearchText(policy).indexOf(query) !== -1;
    });
}

function renderNotificationPoliciesTable() {
    const policies = getFilteredNotificationPolicies();
    const tbody = $("#notification-policies-table");

    tbody.empty();

    $("#notification-policies-filtered-count").text(policies.length);
    $("#notification-policies-total-count").text(
        notificationPoliciesCache.length
    );

    if (!policies.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>")
                    .attr("colspan", "6")
                    .addClass("empty-cell")
                    .text(i18n.t("notification_policies.empty.found"))
            )
        );
        return;
    }

    policies.forEach(function (policy) {
        tbody.append(renderNotificationPolicyRow(policy));
    });
}

function renderNotificationPolicyRow(policy) {
    const row = $("<tr>").toggleClass("row-disabled", !policy.enabled);

    row.append(
        $("<td>")
            .append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("name-button")
                    .text(policy.name || "-")
                    .on("click", function () {
                        renderNotificationPolicyDetails(policy, {
                            scroll: true,
                        });
                    })
            )
            .append(
                $("<div>")
                    .addClass("row-subtitle")
                    .text(policy.description || i18n.t("notification_policies.table.policy") + " #" + policy.id)
            )
    );

    row.append(
        $("<td>").append(
            $("<span>")
                .addClass("pill")
                .text(policy.team_slug || policy.team_name || "-")
        )
    );

    row.append($("<td>").text(policy.rules_count || 0));
    row.append($("<td>").text(policy.services_count || 0));
    row.append(
        $("<td>").append(
            renderStatusBadge(policy.enabled, i18n.t("notification_policies.status.enabled"), i18n.t("notification_policies.status.disabled"))
        )
    );

    row.append(
        $("<td>")
            .addClass("actions-cell")
            .append(renderNotificationPolicyActions(policy))
    );

    return row;
}

function renderNotificationPolicyActions(policy) {
    return makeActionMenu({
        object: policy,
        items: [
            {
                label: i18n.t("notification_policies.actions.edit"),
                icon: "fas fa-edit",
                required: "write",
                denyMessage: i18n.t("notification_policies.permissions.edit"),
                onClick: function () {
                    editNotificationPolicy(policy.id);
                },
            },
            {
                label: i18n.t("notification_policies.actions.rules"),
                icon: "fas fa-list",
                required: "write",
                denyMessage: i18n.t("notification_policies.permissions.rules"),
                onClick: function () {
                    openNotificationPolicyRulesModal(policy.id);
                },
            },
            {
                label: policy.enabled ? i18n.t("notification_policies.actions.disable") : i18n.t("notification_policies.actions.enable"),
                icon: policy.enabled ? "fas fa-pause" : "fas fa-play",
                required: "write",
                danger: policy.enabled,
                denyMessage: i18n.t("notification_policies.permissions.update"),
                onClick: function () {
                    setNotificationPolicyEnabled(policy, !policy.enabled);
                },
            },
            {
                label: i18n.t("notification_policies.actions.remove"),
                icon: "fas fa-trash",
                required: "delete",
                danger: true,
                denyMessage: i18n.t("notification_policies.permissions.remove"),
                onClick: function () {
                    removeNotificationPolicy(policy);
                },
            },
        ],
    });
}

function notificationPolicyDetailsItem(label, value) {
    return $("<div>")
        .addClass("details-item")
        .append($("<div>").addClass("details-label").text(label))
        .append($("<div>").addClass("details-value").text(value || "-"));
}

function renderNotificationPolicyDetails(policy, options) {
    selectedNotificationPolicyDetailsId = policy.id;

    $("#notification-policy-details-subtitle").text(
        (policy.team_slug || policy.team_name || "-")
        + " / "
        + (policy.enabled ? i18n.t("notification_policies.status.enabled") : i18n.t("notification_policies.status.disabled"))
    );

    const body = $("#notification-policy-details-body");
    body.empty();

    body.append(
        $("<div>")
            .addClass("details-list")
            .append(notificationPolicyDetailsItem(i18n.t("notification_policies.details.name"), policy.name))
            .append(
                notificationPolicyDetailsItem(
                    i18n.t("notification_policies.details.team"),
                    policy.team_slug || policy.team_name
                )
            )
            .append(
                notificationPolicyDetailsItem(
                    i18n.t("notification_policies.details.description"),
                    policy.description
                )
            )
            .append(
                notificationPolicyDetailsItem(
                    i18n.t("notification_policies.details.rules"),
                    String(policy.rules_count || 0)
                )
            )
            .append(
                notificationPolicyDetailsItem(
                    i18n.t("notification_policies.details.services"),
                    String(policy.services_count || 0)
                )
            )
            .append(
                notificationPolicyDetailsItem(
                    i18n.t("notification_policies.details.status"),
                    policy.enabled ? i18n.t("notification_policies.status.enabled") : i18n.t("notification_policies.status.disabled")
                )
            )
    );

    const actions = $("<div>").addClass("details-actions");

    appendIconActionIfAllowed(actions, policy, {
        required: "write",
        icon: "fas fa-edit",
        label: i18n.t("notification_policies.actions.edit_policy"),
        onClick: function () {
            editNotificationPolicy(policy.id);
        },
    });

    appendIconActionIfAllowed(actions, policy, {
        required: "write",
        icon: "fas fa-list",
        label: i18n.t("notification_policies.actions.manage_rules"),
        onClick: function () {
            openNotificationPolicyRulesModal(policy.id);
        },
    });

    appendIconActionIfAllowed(actions, policy, {
        required: "write",
        icon: policy.enabled ? "fas fa-pause" : "fas fa-play",
        label: policy.enabled ? i18n.t("notification_policies.actions.disable_policy") : i18n.t("notification_policies.actions.enable_policy"),
        className: policy.enabled ? "btn-warning" : "btn-success",
        onClick: function () {
            setNotificationPolicyEnabled(policy, !policy.enabled);
        },
    });

    appendIconActionIfAllowed(actions, policy, {
        required: "delete",
        icon: "fas fa-trash-alt",
        label: i18n.t("notification_policies.actions.remove_policy"),
        className: "btn-danger",
        onClick: function () {
            removeNotificationPolicy(policy);
        },
    });

    if (actions.children().length) {
        body.append(actions);
    }

    if (options && options.scroll) {
        scrollToAndHighlight("#notification-policy-details-body", {
            highlight: "#notification-policy-details-body",
            block: "nearest",
        });
    }
}

function renderNotificationPolicyDetailsEmpty() {
    selectedNotificationPolicyDetailsId = null;

    $("#notification-policy-details-subtitle").text(i18n.t("notification_policies.details.select"));
    $("#notification-policy-details-body").html(
        '<div class="details-empty">'
        + i18n.t("notification_policies.details.help")
        + "</div>"
    );
}

function restoreNotificationPolicyDetails() {
    const policies = getFilteredNotificationPolicies();

    if (!policies.length) {
        renderNotificationPolicyDetailsEmpty();
        return;
    }

    if (selectedNotificationPolicyDetailsId) {
        const selected = policies.find(function (policy) {
            return Number(policy.id)
                === Number(selectedNotificationPolicyDetailsId);
        });

        if (selected) {
            renderNotificationPolicyDetails(selected);
            return;
        }
    }

    renderNotificationPolicyDetails(policies[0]);
}

function getNotificationPolicyById(policyId) {
    return notificationPoliciesCache.find(function (policy) {
        return Number(policy.id) === Number(policyId);
    }) || null;
}

function rememberNotificationPolicyInCache(policy) {
    if (!policy || !policy.id) {
        return;
    }

    const index = notificationPoliciesCache.findIndex(function (item) {
        return Number(item.id) === Number(policy.id);
    });

    if (index >= 0) {
        notificationPoliciesCache[index] = policy;
        return;
    }

    notificationPoliciesCache.push(policy);
}

function loadNotificationPolicyRuleChannels(policy, callback) {
    notificationPolicyChannelsCache = [];

    apiGet(
        "/api/channels?team_id=" + encodeURIComponent(policy.team_id),
        function (channels) {
            notificationPolicyChannelsCache = asArray(channels).filter(
                function (channel) {
                    return channel.enabled !== false;
                }
            );

            if (typeof callback === "function") {
                callback();
            }
        }
    );
}

function loadNotificationPolicyMatcherPresets(policy, callback) {
    notificationPolicyMatcherPresetsCache = [];

    apiGet("/api/matcher-presets?team_id=" + encodeURIComponent(policy.team_id), function (presets) {
        notificationPolicyMatcherPresetsCache = asArray(presets);

        if (typeof callback === "function") {
            callback();
        }
    });
}

function getNotificationPolicyMatcherPresetById(presetId) {
    if (!presetId) {
        return null;
    }

    return notificationPolicyMatcherPresetsCache.find(function (preset) {
        return Number(preset.id) === Number(presetId);
    }) || null;
}

function getNotificationPolicyRuleMatcherPreset(rule) {
    return rule.matcher_preset || getNotificationPolicyMatcherPresetById(rule.matcher_preset_id);
}

function formatNotificationPolicyRuleMatcherPreset(rule) {
    const preset = getNotificationPolicyRuleMatcherPreset(rule);

    if (!preset) {
        return i18n.t("notification_policies.rules.no_preset");
    }

    return preset.name + " · v" + Number(preset.version || 1) + (preset.enabled ? "" : " · " + i18n.t("notification_policies.status.disabled"));
}

function notificationPolicyMatcherPresetHint(preset) {
    if (!preset) {
        return i18n.t("notification_policies.rules.no_preset_help");
    }

    if (!preset.enabled) {
        return i18n.t("notification_policies.rules.preset_disabled_help");
    }

    return i18n.t("notification_policies.rules.preset_match_help", {name: preset.name, version: Number(preset.version || 1)});
}

function loadNotificationPolicyRuleCards(policyId, callback) {
    const container = $("#notification-policy-rule-cards");

    container
        .empty()
        .append(
            $("<div>")
                .addClass("layer-card-loading")
                .text(i18n.t("notification_policies.rules.loading"))
        );

    apiGet("/api/notification-policies/" + policyId, function (policy) {
        rememberNotificationPolicyInCache(policy);

        selectedNotificationPolicyRulesId = policy.id;
        notificationPolicyRulesCache = asArray(policy.rules)
            .slice()
            .sort(function (left, right) {
                return Number(left.position || 0)
                    - Number(right.position || 0);
            });

        $("#notification-policy-rules-title").text(
            i18n.t("notification_policies.rules.title_named", {name: policy.name})
        );

        $("#notification-policy-rules-subtitle").text(
            (policy.team_slug || policy.team_name || "-")
            + " / "
            + (policy.enabled ? i18n.t("notification_policies.status.enabled") : i18n.t("notification_policies.status.disabled"))
        );

        renderNotificationPolicyRuleCards();

        if (typeof callback === "function") {
            callback(policy);
        }
    });
}

function openNotificationPolicyRulesModal(policyId, ruleIdToExpand) {
    const policy = getNotificationPolicyById(policyId);

    if (!policy) {
        showAppError(i18n.t("notification_policies.errors.not_found"));
        return;
    }

    if (!canWriteObject(policy)) {
        showAppError(
            i18n.t("notification_policies.permissions.no_manage"),
            i18n.t("notification_policies.errors.access_denied")
        );
        return;
    }

    selectedNotificationPolicyRulesId = policy.id;
    notificationPolicyRulesCache = [];
    notificationPolicyChannelsCache = [];
    notificationPolicyMatcherPresetsCache = [];
    expandedNotificationPolicyRuleId = ruleIdToExpand || null;
    unsavedNotificationPolicyRuleCounter = 0;

    $("#notification-policy-rules-title").text(
        i18n.t("notification_policies.rules.title_named", {name: policy.name})
    );

    $("#notification-policy-rules-subtitle").text(
        policy.team_slug || policy.team_name || "-"
    );

    openAppModal("#notification-policy-rules-modal");

    loadNotificationPolicyRuleChannels(policy, function () {
        loadNotificationPolicyMatcherPresets(policy, function () {
            loadNotificationPolicyRuleCards(policy.id);
        });
    });
}

function closeNotificationPolicyRulesModal() {
    closeAppModal("#notification-policy-rules-modal");

    selectedNotificationPolicyRulesId = null;
    notificationPolicyRulesCache = [];
    notificationPolicyChannelsCache = [];
    notificationPolicyMatcherPresetsCache = [];
    expandedNotificationPolicyRuleId = null;
    unsavedNotificationPolicyRuleCounter = 0;

    $("#notification-policy-rule-cards")
        .empty()
        .append(
            $("<div>")
                .addClass("empty-cell")
                .text(i18n.t("notification_policies.rules.no_policy"))
        );
}

function getNextNotificationPolicyRulePosition() {
    return notificationPolicyRulesCache.reduce(function (position, rule) {
        return Math.max(position, Number(rule.position || 0));
    }, 0) + 1;
}

function createUnsavedNotificationPolicyRule() {
    unsavedNotificationPolicyRuleCounter += 1;

    const position = getNextNotificationPolicyRulePosition();

    return {
        id: "new-" + unsavedNotificationPolicyRuleCounter,
        name: i18n.t("notification_policies.rules.default_name", {position: position}),
        description: "",
        position: position,
        event_types: [
            "notification",
            "reminder",
            "escalation",
        ],
        matchers: {},
        matcher_preset_id: null,
        matcher_preset: null,
        channel_ids: [],
        channels: [],
        continue_matching: false,
        enabled: true,
    };
}

function addNotificationPolicyRule() {
    if (!selectedNotificationPolicyRulesId) {
        showAppError(i18n.t("notification_policies.errors.select_policy"));
        return;
    }

    const rule = createUnsavedNotificationPolicyRule();

    notificationPolicyRulesCache.push(rule);
    expandedNotificationPolicyRuleId = rule.id;

    renderNotificationPolicyRuleCards();

    scrollToAndHighlight(
        "[data-notification-policy-rule-id='" + rule.id + "']",
        {
            highlight:
                "[data-notification-policy-rule-id='" + rule.id + "']",
            block: "nearest",
            container: "#notification-policy-rules-modal",
        }
    );
}

function getNotificationPolicyChannelName(channelId) {
    const channel = notificationPolicyChannelsCache.find(function (item) {
        return Number(item.id) === Number(channelId);
    });

    return channel
        ? channel.name + " (" + channel.channel_type + ")"
        : i18n.t("notification_policies.rules.channel_number", {id: channelId});
}

function formatNotificationPolicyRuleEvents(rule) {
    const labels = {
        notification: i18n.t("notification_policies.rules.notification"),
        reminder: i18n.t("notification_policies.rules.reminder"),
        escalation: i18n.t("notification_policies.rules.escalation"),
    };

    return asArray(rule.event_types).map(function (eventType) {
        return labels[eventType] || eventType;
    }).join(", ") || i18n.t("notification_policies.rules.no_events");
}

function formatNotificationPolicyRuleChannels(rule) {
    return asArray(rule.channel_ids).map(function (channelId) {
        return getNotificationPolicyChannelName(channelId);
    }).join(", ") || i18n.t("notification_policies.rules.no_channels");
}

function formatNotificationPolicyRuleMatchers(rule) {
    const preset = getNotificationPolicyRuleMatcherPreset(rule);
    const matchers = rule.matchers || {};
    const localMatchers = Object.keys(matchers).length ? JSON.stringify(matchers) : i18n.t("notification_policies.rules.all_alerts");

    if (!preset) {
        return localMatchers;
    }

    return formatNotificationPolicyRuleMatcherPreset(rule) + " AND " + localMatchers;
}

function renderNotificationPolicyRuleCards() {
    const container = $("#notification-policy-rule-cards");
    container.empty();

    if (!notificationPolicyRulesCache.length) {
        container.append(
            $("<div>")
                .addClass("empty-cell")
                .text(
                    i18n.t("notification_policies.rules.no_rules")
                )
        );
        return;
    }

    notificationPolicyRulesCache.forEach(function (rule, index) {
        container.append(
            renderNotificationPolicyRuleCard(rule, index + 1)
        );
    });
}

function renderNotificationPolicyRuleCard(rule, number) {
    const expanded = isSameNotificationPolicyRuleId(
        expandedNotificationPolicyRuleId,
        rule.id
    );

    const card = $("<div>")
        .addClass("rotation-layer-card")
        .toggleClass("is-editing", expanded)
        .toggleClass("is-disabled", !rule.enabled)
        .toggleClass("is-unsaved", isUnsavedNotificationPolicyRule(rule))
        .attr("data-notification-policy-rule-id", rule.id);

    card.append(renderNotificationPolicyRuleHeader(rule, number));
    card.append(renderNotificationPolicyRuleSummary(rule));
    card.append(renderNotificationPolicyRuleEditor(rule));

    return card;
}

function renderNotificationPolicyRuleHeader(rule, number) {
    const expanded = isSameNotificationPolicyRuleId(
        expandedNotificationPolicyRuleId,
        rule.id
    );

    const unsaved = isUnsavedNotificationPolicyRule(rule);
    const header = $("<div>").addClass("rotation-layer-card-header");
    const actions = $("<div>").addClass("rotation-layer-header-actions");

    header.append(
        $("<div>")
            .addClass("rotation-layer-number")
            .text(number)
    );

    header.append(
        $("<div>")
            .addClass("rotation-layer-title")
            .append(
                $("<strong>").text(
                    rule.name
                    + (unsaved ? " · " + i18n.t("notification_policies.rules.unsaved") : "")
                )
            )
            .append(
                $("<span>").text(
                    formatNotificationPolicyRuleEvents(rule)
                    + " · "
                    + formatNotificationPolicyRuleChannels(rule)
                )
            )
    );

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-small")
            .text(expanded ? i18n.t("notification_policies.actions.collapse") : i18n.t("notification_policies.actions.edit"))
            .on("click", function () {
                toggleNotificationPolicyRuleEditor(rule.id);
            })
    );

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-danger btn-small")
            .text(unsaved ? i18n.t("notification_policies.actions.remove") : i18n.t("notification_policies.actions.delete"))
            .on("click", function () {
                deleteNotificationPolicyRule(rule.id);
            })
    );

    header.append(actions);

    return header;
}

function renderNotificationPolicyRuleSummary(rule) {
    return $("<div>")
        .addClass("rotation-layer-summary")
        .append(
            $("<div>")
                .addClass("rotation-layer-summary-item")
                .append($("<span>").text(i18n.t("notification_policies.rules.events")))
                .append(
                    $("<strong>").text(
                        formatNotificationPolicyRuleEvents(rule)
                    )
                )
        )
        .append(
            $("<div>")
                .addClass("rotation-layer-summary-item")
                .append($("<span>").text(i18n.t("notification_policies.rules.matchers")))
                .append(
                    $("<strong>").text(
                        formatNotificationPolicyRuleMatchers(rule)
                    )
                )
        )
        .append(
            $("<div>")
                .addClass("rotation-layer-summary-item")
                .append($("<span>").text(i18n.t("notification_policies.rules.status")))
                .append(
                    $("<strong>").text(
                        rule.enabled ? i18n.t("notification_policies.status.enabled") : i18n.t("notification_policies.status.disabled")
                    )
                )
        );
}

function notificationPolicyRuleFieldId(ruleId, field) {
    return "notification-policy-rule-" + ruleId + "-" + field;
}

function notificationPolicyRuleTextField(
    rule,
    field,
    label,
    value,
    columnClass
) {
    const id = notificationPolicyRuleFieldId(rule.id, field);

    return $("<div>")
        .addClass("app-field " + (columnClass || "layer-settings-col-6"))
        .append($("<label>").attr("for", id).text(label))
        .append(
            $("<input>")
                .attr("id", id)
                .attr("type", "text")
                .addClass("input")
                .val(value || "")
        );
}

function notificationPolicyRuleNumberField(
    rule,
    field,
    label,
    value,
    columnClass
) {
    const id = notificationPolicyRuleFieldId(rule.id, field);

    return $("<div>")
        .addClass("app-field " + (columnClass || "layer-settings-col-2"))
        .append($("<label>").attr("for", id).text(label))
        .append(
            $("<input>")
                .attr("id", id)
                .attr("type", "number")
                .attr("min", "1")
                .addClass("input")
                .val(value || 1)
        );
}

function notificationPolicyRuleCheckbox(
    rule,
    field,
    label,
    checked,
    columnClass
) {
    return $("<label>")
        .addClass(
            "md-checkbox app-field layer-settings-checkbox "
            + (columnClass || "layer-settings-col-6")
        )
        .append(
            $("<input>")
                .attr("id", notificationPolicyRuleFieldId(rule.id, field))
                .attr("type", "checkbox")
                .prop("checked", !!checked)
        )
        .append($("<span>").text(label));
}

function notificationPolicyRuleEventCheckbox(rule, eventType, label) {
    const id = notificationPolicyRuleFieldId(rule.id, "event-" + eventType);

    return $("<label>")
        .addClass("md-checkbox")
        .append(
            $("<input>")
                .attr("id", id)
                .attr("type", "checkbox")
                .prop("checked", asArray(rule.event_types).includes(eventType))
        )
        .append($("<span>").text(label));
}

function notificationPolicyRuleChannelsField(rule) {
    const id = notificationPolicyRuleFieldId(rule.id, "channels");

    const select = $("<select>")
        .attr("id", id)
        .attr("multiple", "multiple")
        .attr("size", "6")
        .addClass("input");

    notificationPolicyChannelsCache.forEach(function (channel) {
        select.append(
            $("<option>")
                .val(String(channel.id))
                .text(channel.name + " (" + channel.channel_type + ")")
        );
    });

    select.val(
        asArray(rule.channel_ids).map(function (channelId) {
            return String(channelId);
        })
    );

    return $("<div>")
        .addClass("app-field layer-settings-col-12")
        .append($("<label>").attr("for", id).text(i18n.t("notification_policies.rules.channels")))
        .append(select)
        .append(
            $("<div>")
                .addClass("help-text")
                .text(i18n.t("notification_policies.rules.channels_help"))
        );
}

function notificationPolicyRuleMatcherPresetField(rule) {
    const id = notificationPolicyRuleFieldId(rule.id, "matcher-preset");
    const hintId = notificationPolicyRuleFieldId(rule.id, "matcher-preset-hint");
    const selectedPresetId = rule.matcher_preset_id || (rule.matcher_preset ? rule.matcher_preset.id : null);
    const select = $("<select>").attr("id", id).attr("data-rule-id", rule.id).addClass("input notification-policy-rule-matcher-preset");

    select.append($("<option>").val("").text(i18n.t("notification_policies.rules.no_preset")));

    notificationPolicyMatcherPresetsCache.forEach(function (preset) {
        const selected = Number(preset.id) === Number(selectedPresetId);
        const label = preset.name + " · v" + Number(preset.version || 1) + (preset.enabled ? "" : " · " + i18n.t("notification_policies.status.disabled"));
        const option = $("<option>").val(String(preset.id)).text(label);

        if (!preset.enabled && !selected) {
            option.prop("disabled", true);
        }

        select.append(option);
    });

    select.val(selectedPresetId ? String(selectedPresetId) : "");

    const preset = getNotificationPolicyMatcherPresetById(selectedPresetId) || rule.matcher_preset || null;

    return $("<div>").addClass("app-field layer-settings-col-12")
        .append($("<label>").attr("for", id).text(i18n.t("notification_policies.rules.matcher_preset")))
        .append(select)
        .append($("<div>").attr("id", hintId).addClass("help-text").text(notificationPolicyMatcherPresetHint(preset)));
}

function renderNotificationPolicyRuleEditor(rule) {
    const editor = $("<div>").addClass("rotation-layer-editor");
    const section = $("<section>").addClass("layer-editor-section");
    const grid = $("<div>").addClass("layer-settings-grid");

    section.append($("<h4>").text(i18n.t("notification_policies.rules.settings")));

    section.append(
        $("<div>")
            .addClass("layer-editor-section-subtitle")
            .text(
                i18n.t("notification_policies.rules.settings_help")
            )
    );

    grid.append(
        notificationPolicyRuleTextField(
            rule,
            "name",
            i18n.t("notification_policies.rules.name"),
            rule.name,
            "layer-settings-col-6"
        )
    );

    grid.append(
        notificationPolicyRuleNumberField(
            rule,
            "position",
            i18n.t("notification_policies.rules.position"),
            rule.position,
            "layer-settings-col-2"
        )
    );

    grid.append(
        notificationPolicyRuleCheckbox(
            rule,
            "enabled",
            i18n.t("notification_policies.rules.enabled"),
            rule.enabled !== false,
            "layer-settings-col-4"
        )
    );

    grid.append(notificationPolicyRuleChannelsField(rule));
    grid.append(notificationPolicyRuleMatcherPresetField(rule));

    grid.append(
        $("<div>")
            .addClass("app-field layer-settings-col-12")
            .append($("<label>").text(i18n.t("notification_policies.rules.event_types")))
            .append(
                $("<div>")
                    .addClass("checkbox-grid")
                    .append(
                        notificationPolicyRuleEventCheckbox(
                            rule,
                            "notification",
                            i18n.t("notification_policies.rules.notification")
                        )
                    )
                    .append(
                        notificationPolicyRuleEventCheckbox(
                            rule,
                            "reminder",
                            i18n.t("notification_policies.rules.reminder")
                        )
                    )
                    .append(
                        notificationPolicyRuleEventCheckbox(
                            rule,
                            "escalation",
                            i18n.t("notification_policies.rules.escalation")
                        )
                    )
            )
    );

    grid.append(
        notificationPolicyRuleCheckbox(
            rule,
            "continue-matching",
            i18n.t("notification_policies.rules.continue_matching"),
            rule.continue_matching,
            "layer-settings-col-12"
        )
    );

    const descriptionId = notificationPolicyRuleFieldId(
        rule.id,
        "description"
    );

    grid.append(
        $("<div>")
            .addClass("app-field layer-settings-col-12")
            .append(
                $("<label>").attr("for", descriptionId).text(i18n.t("notification_policies.rules.description"))
            )
            .append(
                $("<textarea>")
                    .attr("id", descriptionId)
                    .attr("rows", "3")
                    .addClass("input")
                    .val(rule.description || "")
            )
    );

    grid.append(
        createMatcherEditor({
            id: notificationPolicyRuleFieldId(rule.id, "matchers"),
            value: rule.matchers || {},
            label: i18n.t("notification_policies.rules.additional_matchers"),
            helpText: i18n.t("notification_policies.rules.additional_matchers_help"),
            context: function () {
                const policy = getNotificationPolicyById(selectedNotificationPolicyRulesId);
                const matcherPresetId = Number($("#" + notificationPolicyRuleFieldId(rule.id, "matcher-preset")).val()) || null;

                return {
                    scope: "notification_policy",
                    teamId: policy ? policy.team_id : null,
                    policyId: selectedNotificationPolicyRulesId,
                    ruleId: rule.id,
                    matcherPresetId: matcherPresetId,
                };
            },
        })
    );

    section.append(grid);

    section.append(
        $("<div>")
            .addClass("layer-editor-actions")
            .append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("btn btn-primary btn-small")
                    .text(i18n.t("notification_policies.actions.save_rule"))
                    .on("click", function () {
                        saveNotificationPolicyRule(rule.id);
                    })
            )
            .append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("btn btn-danger btn-small")
                    .text(i18n.t("notification_policies.actions.delete_rule"))
                    .on("click", function () {
                        deleteNotificationPolicyRule(rule.id);
                    })
            )
    );

    editor.append(section);

    return editor;
}

function collectNotificationPolicyRulePayload(ruleId) {
    const prefix = "#notification-policy-rule-" + ruleId + "-";

    const eventTypes = [];

    $(prefix + "event-notification").is(":checked")
        && eventTypes.push("notification");

    $(prefix + "event-reminder").is(":checked")
        && eventTypes.push("reminder");

    $(prefix + "event-escalation").is(":checked")
        && eventTypes.push("escalation");

    return {
        name: $(prefix + "name").val(),
        description: $(prefix + "description").val(),
        position: Number($(prefix + "position").val() || 1),
        event_types: eventTypes,
        matchers: getMatcherEditorValue(prefix + "matchers", {}),
        matcher_preset_id: $(prefix + "matcher-preset").val() ? Number($(prefix + "matcher-preset").val()) : null,
        channel_ids: ($(prefix + "channels").val() || []).map(Number),
        continue_matching: $(prefix + "continue-matching").is(":checked"),
        enabled: $(prefix + "enabled").is(":checked"),
    };
}

function saveNotificationPolicyRule(ruleId) {
    const payload = collectNotificationPolicyRulePayload(ruleId);

    if (!String(payload.name || "").trim()) {
        showAppError(i18n.t("notification_policies.errors.rule_name_required"));
        return;
    }

    if (!payload.event_types.length) {
        showAppError(i18n.t("notification_policies.errors.event_required"));
        return;
    }

    if (payload.enabled && !payload.channel_ids.length) {
        showAppError(i18n.t("notification_policies.errors.channel_required"));
        return;
    }

    if (isUnsavedNotificationPolicyRule(ruleId)) {
        apiPost(
            "/api/notification-policies/"
                + selectedNotificationPolicyRulesId
                + "/rules",
            payload,
            function (rule) {
                expandedNotificationPolicyRuleId = rule.id;
                reloadNotificationPolicyRules();
            }
        );
        return;
    }

    apiPut(
        "/api/notification-policies/"
            + selectedNotificationPolicyRulesId
            + "/rules/"
            + ruleId,
        payload,
        function () {
            expandedNotificationPolicyRuleId = ruleId;
            reloadNotificationPolicyRules();
        }
    );
}

function reloadNotificationPolicyRules() {
    if (!selectedNotificationPolicyRulesId) {
        return;
    }

    loadNotificationPolicyRuleCards(
        selectedNotificationPolicyRulesId,
        function () {
            refreshNotificationPolicies();
        }
    );
}

function deleteNotificationPolicyRule(ruleId) {
    if (isUnsavedNotificationPolicyRule(ruleId)) {
        notificationPolicyRulesCache = notificationPolicyRulesCache.filter(
            function (rule) {
                return !isSameNotificationPolicyRuleId(rule.id, ruleId);
            }
        );

        if (
            isSameNotificationPolicyRuleId(
                expandedNotificationPolicyRuleId,
                ruleId
            )
        ) {
            expandedNotificationPolicyRuleId = null;
        }

        renderNotificationPolicyRuleCards();
        return;
    }

    showAppConfirm({
        title: i18n.t("notification_policies.confirm.delete_rule_title"),
        message: i18n.t("notification_policies.confirm.delete_rule_message", {id: ruleId}),
        confirmText: i18n.t("notification_policies.actions.delete_rule"),
        confirmClass: "btn-danger",
    }).done(function () {
        apiDelete(
            "/api/notification-policies/"
                + selectedNotificationPolicyRulesId
                + "/rules/"
                + ruleId,
            function () {
                expandedNotificationPolicyRuleId = null;
                reloadNotificationPolicyRules();
            }
        );
    });
}

function toggleNotificationPolicyRuleEditor(ruleId) {
    if (
        isSameNotificationPolicyRuleId(
            expandedNotificationPolicyRuleId,
            ruleId
        )
    ) {
        expandedNotificationPolicyRuleId = null;
    } else {
        expandedNotificationPolicyRuleId = ruleId;
    }

    renderNotificationPolicyRuleCards();
}

function collectNotificationPolicyPayload() {
    return {
        team_id: Number($("#notification-policy-team").val()),
        name: $("#notification-policy-name").val(),
        description: $("#notification-policy-description").val(),
        enabled: $("#notification-policy-enabled").is(":checked"),
    };
}

function saveNotificationPolicy() {
    const policyId = $("#notification-policy-id").val();
    const payload = collectNotificationPolicyPayload();

    if (policyId) {
        delete payload.team_id;

        apiPut(
            "/api/notification-policies/" + policyId,
            payload,
            function () {
                closeAppModal("#notification-policy-form-modal");
                resetNotificationPolicyForm();
                refreshNotificationPolicies();
            }
        );
        return;
    }

    apiPost("/api/notification-policies", payload, function () {
        closeAppModal("#notification-policy-form-modal");
        resetNotificationPolicyForm();
        refreshNotificationPolicies();
    });
}

function resetNotificationPolicyForm() {
    $("#notification-policy-form-title").text(
        i18n.t("notification_policies.form.create_title")
    );
    $("#notification-policy-id").val("");
    $("#notification-policy-name").val("");
    $("#notification-policy-description").val("");
    $("#notification-policy-enabled").prop("checked", true);
    $("#notification-policy-team").prop("disabled", false);

    const selectedTeam = $("#global-team-filter").val();

    if (selectedTeam) {
        $("#notification-policy-team").val(selectedTeam);
    }
}

function openCreateNotificationPolicyModal() {
    if (!currentUserCanCreateUiObjects()) {
        showAppError(
            i18n.t("notification_policies.permissions.create"),
            i18n.t("notification_policies.errors.access_denied")
        );
        return;
    }

    resetNotificationPolicyForm();
    openAppModal("#notification-policy-form-modal");
}

function editNotificationPolicy(policyId) {
    const policy = getNotificationPolicyById(policyId);

    if (!policy) {
        showAppError(i18n.t("notification_policies.errors.not_found"));
        return;
    }

    if (!canWriteObject(policy)) {
        showAppError(
            i18n.t("notification_policies.permissions.no_edit"),
            i18n.t("notification_policies.errors.access_denied")
        );
        return;
    }

    $("#notification-policy-form-title").text(
        i18n.t("notification_policies.form.edit_title", {id: policy.id})
    );
    $("#notification-policy-id").val(policy.id);
    $("#notification-policy-team")
        .val(policy.team_id)
        .prop("disabled", true);
    $("#notification-policy-name").val(policy.name || "");
    $("#notification-policy-description").val(
        policy.description || ""
    );
    $("#notification-policy-enabled").prop(
        "checked",
        !!policy.enabled
    );

    openAppModal("#notification-policy-form-modal");
}

function setNotificationPolicyEnabled(policy, enabled) {
    if (!canWriteObject(policy)) {
        showAppError(
            i18n.t("notification_policies.permissions.no_update"),
            i18n.t("notification_policies.errors.access_denied")
        );
        return;
    }

    apiPut(
        "/api/notification-policies/" + policy.id,
        {enabled: !!enabled},
        refreshNotificationPolicies
    );
}

function removeNotificationPolicy(policy) {
    if (!canDeleteObject(policy)) {
        showAppError(
            i18n.t("notification_policies.permissions.no_remove"),
            i18n.t("notification_policies.errors.access_denied")
        );
        return;
    }

    showAppConfirm({
        title: i18n.t("notification_policies.confirm.remove_title"),
        message: i18n.t("notification_policies.confirm.remove_message", {name: policy.name}),
        confirmText: i18n.t("notification_policies.actions.remove_policy"),
        confirmClass: "btn-danger",
    }).done(function () {
        apiDelete(
            "/api/notification-policies/" + policy.id,
            refreshNotificationPolicies
        );
    });
}

$(document).on(
    "click",
    "#open-notification-policy-create-modal",
    openCreateNotificationPolicyModal
);

$(document).on(
    "click",
    "#close-notification-policy-form-modal",
    function () {
        closeAppModal("#notification-policy-form-modal");
    }
);

$(document).on(
    "click",
    "#reset-notification-policy-form",
    resetNotificationPolicyForm
);

$(document).on(
    "click",
    "#save-notification-policy",
    saveNotificationPolicy
);

$(document).on(
    "click",
    "#reload-notification-policies",
    refreshNotificationPolicies
);

$(document).on(
    "input",
    "#notification-policies-search",
    function () {
        renderNotificationPoliciesTable();
        restoreNotificationPolicyDetails();
    }
);

$(document).on(
    "change",
    "#notification-policies-status-filter",
    function () {
        renderNotificationPoliciesTable();
        restoreNotificationPolicyDetails();
    }
);
$(document).on(
    "click",
    "#add-notification-policy-rule",
    addNotificationPolicyRule
);

$(document).on(
    "click",
    "#reload-notification-policy-rules",
    reloadNotificationPolicyRules
);

$(document).on(
    "click",
    [
        "#close-notification-policy-rules-modal",
        "#close-notification-policy-rules-modal-footer",
    ].join(", "),
    closeNotificationPolicyRulesModal
);

$(document).on("change", ".notification-policy-rule-matcher-preset", function () {
    const ruleId = $(this).attr("data-rule-id");
    const preset = getNotificationPolicyMatcherPresetById($(this).val());
    $("#" + notificationPolicyRuleFieldId(ruleId, "matcher-preset-hint")).text(notificationPolicyMatcherPresetHint(preset));
});
