let priorityPoliciesCache = [];
let selectedPriorityPolicyDetailsId = null;
let selectedPriorityPolicyRulesId = null;
let priorityPolicyRulesCache = [];
let priorityPolicyMatcherPresetsCache = [];
let priorityPolicyPrioritiesCache = [];
let expandedPriorityPolicyRuleId = null;
let unsavedPriorityPolicyRuleCounter = 0;

function isUnsavedPriorityPolicyRule(ruleOrId) {
    const value = typeof ruleOrId === "object" ? ruleOrId.id : ruleOrId;
    return String(value || "").indexOf("new-") === 0;
}

function isSamePriorityPolicyRuleId(left, right) {
    return String(left) === String(right);
}

function loadPriorityPolicies() {
    fillTeamSelect("#priority-policy-team", false, function () { resetPriorityPolicyForm(); });
    loadPriorityPolicyPriorities(function () { refreshPriorityPolicies(); });
    updatePriorityPolicyCreateButtonState();
    updatePriorityPolicyBehaviorHints();
}

function buildPriorityPoliciesApiUrl() {
    return "/api/priority-policies" + selectedTeamQuery();
}

function updatePriorityPolicyCreateButtonState() {
    const allowed = currentUserCanCreateUiObjects();
    $("#open-priority-policy-create-modal").toggleClass("is-hidden", !allowed).prop("disabled", !allowed);
}

function refreshPriorityPolicies() {
    apiGet(buildPriorityPoliciesApiUrl(), function (policies) {
        priorityPoliciesCache = asArray(policies);
        renderPriorityPoliciesSummary();
        renderPriorityPoliciesTable();
        restorePriorityPolicyDetails();
        updatePriorityPolicyCreateButtonState();
    });
}

function loadPriorityPolicyPriorities(callback) {
    apiGet("/api/incidents/priorities", function (priorities) {
        priorityPolicyPrioritiesCache = asArray(priorities).slice().sort(function (left, right) { return Number(left.level || 0) - Number(right.level || 0); });
        renderPriorityPolicyFallbackPriorityOptions();

        if (typeof callback === "function") {
            callback();
        }
    });
}

function renderPriorityPolicyFallbackPriorityOptions(selectedPriorityId) {
    const select = $("#priority-policy-fallback-priority");
    select.empty().append($("<option>").val("").text(i18n.t("priority_policies.form.select_priority")));

    priorityPolicyPrioritiesCache.forEach(function (priority) {
        select.append($("<option>").val(String(priority.id)).text(priority.name + " (" + priority.slug + ")"));
    });

    select.val(selectedPriorityId ? String(selectedPriorityId) : "");
}

function getPriorityPolicyPriorityById(priorityId) {
    return priorityPolicyPrioritiesCache.find(function (priority) { return Number(priority.id) === Number(priorityId); }) || null;
}

function renderPriorityPoliciesSummary() {
    const enabled = priorityPoliciesCache.filter(function (policy) { return !!policy.enabled; }).length;
    const defaults = priorityPoliciesCache.filter(function (policy) { return !!policy.default_for_team; }).length;
    const services = priorityPoliciesCache.reduce(function (total, policy) { return total + Number(policy.services_count || 0); }, 0);

    $("#priority-policies-summary-total").text(priorityPoliciesCache.length);
    $("#priority-policies-summary-enabled").text(enabled);
    $("#priority-policies-summary-defaults").text(defaults);
    $("#priority-policies-summary-services").text(services);
}

function priorityPolicyUpdateModeLabel(mode) {
    return {
        raise_only: i18n.t("priority_policies.mode.raise_only"),
        recalculate: i18n.t("priority_policies.mode.recalculate_short"),
        initial_only: i18n.t("priority_policies.mode.initial_only_short"),
    }[mode] || mode || "-";
}

function priorityPolicySourceModeLabel(mode) {
    return {
        ignore: i18n.t("priority_policies.source.ignore"),
        prefer: i18n.t("priority_policies.source.prefer_short"),
    }[mode] || mode || "-";
}

function priorityPolicyFallbackLabel(policy) {
    if (policy.fallback_mode === "fixed_priority") {
        return policy.fallback_priority ? policy.fallback_priority.name + " (" + policy.fallback_priority.slug + ")" : i18n.t("priority_policies.fallback.fixed_priority_short");
    }

    return i18n.t("priority_policies.fallback.severity_mapping_short");
}

function getPriorityPolicySearchText(policy) {
    return [
        policy.id,
        policy.name,
        policy.description,
        policy.team_name,
        policy.team_slug,
        policy.update_mode,
        policy.source_priority_mode,
        policy.fallback_mode,
        policy.default_for_team ? "default" : "",
        policy.enabled ? "enabled" : "disabled",
    ].join(" ").toLowerCase();
}

function getFilteredPriorityPolicies() {
    const query = String($("#priority-policies-search").val() || "").trim().toLowerCase();
    const status = String($("#priority-policies-status-filter").val() || "");

    return priorityPoliciesCache.filter(function (policy) {
        if (status === "enabled" && !policy.enabled) {
            return false;
        }

        if (status === "disabled" && policy.enabled) {
            return false;
        }

        if (status === "default" && !policy.default_for_team) {
            return false;
        }

        if (status === "assigned" && Number(policy.services_count || 0) === 0) {
            return false;
        }

        return !query || getPriorityPolicySearchText(policy).indexOf(query) !== -1;
    });
}

function renderPriorityPoliciesTable() {
    const policies = getFilteredPriorityPolicies();
    const tbody = $("#priority-policies-table");
    tbody.empty();

    $("#priority-policies-filtered-count").text(policies.length);
    $("#priority-policies-total-count").text(priorityPoliciesCache.length);

    if (!policies.length) {
        tbody.append($("<tr>").append($("<td>").attr("colspan", "7").addClass("empty-cell").text(i18n.t("priority_policies.empty.found"))));
        return;
    }

    policies.forEach(function (policy) { tbody.append(renderPriorityPolicyRow(policy)); });
}

function renderPriorityPolicyRow(policy) {
    const row = $("<tr>").toggleClass("row-disabled", !policy.enabled);

    row.append(
        $("<td>")
            .append($("<button>").attr("type", "button").addClass("name-button").text(policy.name || "-").on("click", function () { renderPriorityPolicyDetails(policy, {scroll: true}); }))
            .append($("<div>").addClass("row-subtitle").text(policy.description || i18n.t("priority_policies.row.fallback", {id: policy.id})))
    );

    row.append($("<td>").append($("<span>").addClass("pill").text(policy.team_slug || policy.team_name || "-")));
    row.append($("<td>").text(priorityPolicyUpdateModeLabel(policy.update_mode)));
    row.append($("<td>").text(policy.rules_count || 0));
    row.append($("<td>").text(policy.services_count || 0));

    const status = $("<div>");
    status.append(renderStatusBadge(policy.enabled, i18n.t("priority_policies.status.enabled"), i18n.t("priority_policies.status.disabled")));

    if (policy.default_for_team) {
        status.append($("<span>").addClass("pill").text(i18n.t("priority_policies.status.team_default")));
    }

    row.append($("<td>").append(status));
    row.append($("<td>").addClass("actions-cell").append(renderPriorityPolicyActions(policy)));

    return row;
}

function renderPriorityPolicyActions(policy) {
    return makeActionMenu({
        object: policy,
        items: [
            {
                label: i18n.t("priority_policies.actions.edit"),
                icon: "fas fa-edit",
                required: "write",
                denyMessage: i18n.t("priority_policies.permissions.manager_edit"),
                onClick: function () { editPriorityPolicy(policy.id); },
            },
            {
                label: i18n.t("priority_policies.actions.rules"),
                icon: "fas fa-list",
                required: "write",
                denyMessage: i18n.t("priority_policies.permissions.manager_rules"),
                onClick: function () { openPriorityPolicyRulesModal(policy.id); },
            },
            {
                label: policy.enabled ? i18n.t("priority_policies.actions.disable") : i18n.t("priority_policies.actions.enable"),
                icon: policy.enabled ? "fas fa-pause" : "fas fa-play",
                required: "write",
                danger: policy.enabled,
                denyMessage: i18n.t("priority_policies.permissions.manager_update"),
                onClick: function () { setPriorityPolicyEnabled(policy, !policy.enabled); },
            },
            {
                label: i18n.t("priority_policies.actions.remove"),
                icon: "fas fa-trash",
                required: "delete",
                danger: true,
                denyMessage: i18n.t("priority_policies.permissions.delete"),
                onClick: function () { removePriorityPolicy(policy); },
            },
        ],
    });
}

function priorityPolicyDetailsItem(label, value) {
    return $("<div>").addClass("details-item")
        .append($("<div>").addClass("details-label").text(label))
        .append($("<div>").addClass("details-value").text(value === null || value === undefined || value === "" ? "-" : value));
}

function renderPriorityPolicyDetails(policy, options) {
    selectedPriorityPolicyDetailsId = policy.id;
    $("#priority-policy-details-subtitle").text((policy.team_slug || policy.team_name || "-") + " / " + (policy.enabled ? i18n.t("priority_policies.status.enabled") : i18n.t("priority_policies.status.disabled")));

    const body = $("#priority-policy-details-body");
    body.empty();

    body.append(
        $("<div>").addClass("details-list")
            .append(priorityPolicyDetailsItem(i18n.t("priority_policies.details.name"), policy.name))
            .append(priorityPolicyDetailsItem(i18n.t("priority_policies.details.team"), policy.team_slug || policy.team_name))
            .append(priorityPolicyDetailsItem(i18n.t("priority_policies.details.description"), policy.description))
            .append(priorityPolicyDetailsItem(i18n.t("priority_policies.details.team_default"), policy.default_for_team ? i18n.t("priority_policies.values.yes") : i18n.t("priority_policies.values.no")))
            .append(priorityPolicyDetailsItem(i18n.t("priority_policies.details.update_mode"), priorityPolicyUpdateModeLabel(policy.update_mode)))
            .append(priorityPolicyDetailsItem(i18n.t("priority_policies.details.source_priority"), priorityPolicySourceModeLabel(policy.source_priority_mode)))
            .append(priorityPolicyDetailsItem(i18n.t("priority_policies.details.fallback"), priorityPolicyFallbackLabel(policy)))
            .append(priorityPolicyDetailsItem(i18n.t("priority_policies.details.rules"), String(policy.rules_count || 0)))
            .append(priorityPolicyDetailsItem(i18n.t("priority_policies.details.services"), String(policy.services_count || 0)))
            .append(priorityPolicyDetailsItem(i18n.t("priority_policies.details.status"), policy.enabled ? i18n.t("priority_policies.status.enabled") : i18n.t("priority_policies.status.disabled")))
    );

    const actions = $("<div>").addClass("details-actions");

    appendIconActionIfAllowed(actions, policy, {
        required: "write",
        icon: "fas fa-edit",
        label: i18n.t("priority_policies.actions.edit_policy"),
        onClick: function () { editPriorityPolicy(policy.id); },
    });

    appendIconActionIfAllowed(actions, policy, {
        required: "write",
        icon: "fas fa-list",
        label: i18n.t("priority_policies.actions.manage_rules"),
        onClick: function () { openPriorityPolicyRulesModal(policy.id); },
    });

    appendIconActionIfAllowed(actions, policy, {
        required: "write",
        icon: policy.enabled ? "fas fa-pause" : "fas fa-play",
        label: policy.enabled ? i18n.t("priority_policies.actions.disable_policy") : i18n.t("priority_policies.actions.enable_policy"),
        className: policy.enabled ? "btn-warning" : "btn-success",
        onClick: function () { setPriorityPolicyEnabled(policy, !policy.enabled); },
    });

    appendIconActionIfAllowed(actions, policy, {
        required: "delete",
        icon: "fas fa-trash-alt",
        label: i18n.t("priority_policies.actions.remove_policy"),
        className: "btn-danger",
        onClick: function () { removePriorityPolicy(policy); },
    });

    if (actions.children().length) {
        body.append(actions);
    }

    if (options && options.scroll) {
        scrollToAndHighlight("#priority-policy-details-body", {highlight: "#priority-policy-details-body", block: "nearest"});
    }
}

function renderPriorityPolicyDetailsEmpty() {
    selectedPriorityPolicyDetailsId = null;
    $("#priority-policy-details-subtitle").text(i18n.t("priority_policies.details.select"));
    $("#priority-policy-details-body").empty().append($("<div>").addClass("details-empty").text(i18n.t("priority_policies.details.select_help")));
}

function restorePriorityPolicyDetails() {
    const policies = getFilteredPriorityPolicies();

    if (!policies.length) {
        renderPriorityPolicyDetailsEmpty();
        return;
    }

    if (selectedPriorityPolicyDetailsId) {
        const selected = policies.find(function (policy) { return Number(policy.id) === Number(selectedPriorityPolicyDetailsId); });

        if (selected) {
            renderPriorityPolicyDetails(selected);
            return;
        }
    }

    renderPriorityPolicyDetails(policies[0]);
}

function getPriorityPolicyById(policyId) {
    return priorityPoliciesCache.find(function (policy) { return Number(policy.id) === Number(policyId); }) || null;
}

function rememberPriorityPolicyInCache(policy) {
    if (!policy || !policy.id) {
        return;
    }

    const index = priorityPoliciesCache.findIndex(function (item) { return Number(item.id) === Number(policy.id); });

    if (index >= 0) {
        priorityPoliciesCache[index] = policy;
        return;
    }

    priorityPoliciesCache.push(policy);
}

function collectPriorityPolicyPayload() {
    const fallbackMode = $("#priority-policy-fallback-mode").val();

    return {
        team_id: Number($("#priority-policy-team").val()),
        name: $("#priority-policy-name").val(),
        description: $("#priority-policy-description").val(),
        enabled: $("#priority-policy-enabled").is(":checked"),
        default_for_team: $("#priority-policy-default-for-team").is(":checked"),
        update_mode: $("#priority-policy-update-mode").val(),
        source_priority_mode: $("#priority-policy-source-priority-mode").val(),
        fallback_mode: fallbackMode,
        fallback_priority_id: fallbackMode === "fixed_priority" && $("#priority-policy-fallback-priority").val() ? Number($("#priority-policy-fallback-priority").val()) : null,
    };
}

function savePriorityPolicy() {
    const policyId = $("#priority-policy-id").val();
    const payload = collectPriorityPolicyPayload();

    if (!String(payload.name || "").trim()) {
        showAppError(i18n.t("priority_policies.validation.name_required"));
        return;
    }

    if (payload.default_for_team && !payload.enabled) {
        showAppError(i18n.t("priority_policies.validation.default_enabled"));
        return;
    }

    if (payload.fallback_mode === "fixed_priority" && !payload.fallback_priority_id) {
        showAppError(i18n.t("priority_policies.validation.fallback_required"));
        return;
    }

    if (policyId) {
        delete payload.team_id;

        apiPut("/api/priority-policies/" + policyId, payload, function () {
            closeAppModal("#priority-policy-form-modal");
            resetPriorityPolicyForm();
            refreshPriorityPolicies();
        });
        return;
    }

    apiPost("/api/priority-policies", payload, function () {
        closeAppModal("#priority-policy-form-modal");
        resetPriorityPolicyForm();
        refreshPriorityPolicies();
    });
}

function resetPriorityPolicyForm() {
    $("#priority-policy-form-title").text(i18n.t("priority_policies.form.create"));
    $("#priority-policy-id").val("");
    $("#priority-policy-name").val("");
    $("#priority-policy-description").val("");
    $("#priority-policy-enabled").prop("checked", true);
    $("#priority-policy-default-for-team").prop("checked", false);
    $("#priority-policy-update-mode").val("raise_only");
    $("#priority-policy-source-priority-mode").val("ignore");
    $("#priority-policy-fallback-mode").val("severity_mapping");
    $("#priority-policy-team").prop("disabled", false);
    renderPriorityPolicyFallbackPriorityOptions();

    const selectedTeam = $("#global-team-filter").val();

    if (selectedTeam) {
        $("#priority-policy-team").val(selectedTeam);
    }

    updatePriorityPolicyBehaviorHints();
}

function openCreatePriorityPolicyModal() {
    if (!currentUserCanCreateUiObjects()) {
        showAppError(i18n.t("priority_policies.permissions.create"), i18n.t("priority_policies.errors.access_denied"));
        return;
    }

    resetPriorityPolicyForm();
    openAppModal("#priority-policy-form-modal");
}

function editPriorityPolicy(policyId) {
    const policy = getPriorityPolicyById(policyId);

    if (!policy) {
        showAppError(i18n.t("priority_policies.errors.not_found"));
        return;
    }

    if (!canWriteObject(policy)) {
        showAppError(i18n.t("priority_policies.permissions.edit"), i18n.t("priority_policies.errors.access_denied"));
        return;
    }

    $("#priority-policy-form-title").text(i18n.t("priority_policies.form.edit", {id: policy.id}));
    $("#priority-policy-id").val(policy.id);
    $("#priority-policy-team").val(policy.team_id).prop("disabled", true);
    $("#priority-policy-name").val(policy.name || "");
    $("#priority-policy-description").val(policy.description || "");
    $("#priority-policy-enabled").prop("checked", !!policy.enabled);
    $("#priority-policy-default-for-team").prop("checked", !!policy.default_for_team);
    $("#priority-policy-update-mode").val(policy.update_mode || "raise_only");
    $("#priority-policy-source-priority-mode").val(policy.source_priority_mode || "ignore");
    $("#priority-policy-fallback-mode").val(policy.fallback_mode || "severity_mapping");
    renderPriorityPolicyFallbackPriorityOptions(policy.fallback_priority_id);
    updatePriorityPolicyBehaviorHints();
    openAppModal("#priority-policy-form-modal");
}

function setPriorityPolicyEnabled(policy, enabled) {
    if (!canWriteObject(policy)) {
        showAppError(i18n.t("priority_policies.permissions.update"), i18n.t("priority_policies.errors.access_denied"));
        return;
    }

    apiPut("/api/priority-policies/" + policy.id, {enabled: !!enabled}, refreshPriorityPolicies);
}

function removePriorityPolicy(policy) {
    if (!canDeleteObject(policy)) {
        showAppError(i18n.t("priority_policies.permissions.remove"), i18n.t("priority_policies.errors.access_denied"));
        return;
    }

    showAppConfirm({
        title: i18n.t("priority_policies.confirm.remove_title"),
        message: i18n.t("priority_policies.confirm.remove_message", {name: policy.name}),
        confirmText: i18n.t("priority_policies.confirm.remove"),
        confirmClass: "btn-danger",
    }).done(function () { apiDelete("/api/priority-policies/" + policy.id, refreshPriorityPolicies); });
}

function updatePriorityPolicyBehaviorHints() {
    const updateMode = $("#priority-policy-update-mode").val();
    const sourceMode = $("#priority-policy-source-priority-mode").val();
    const fallbackMode = $("#priority-policy-fallback-mode").val();

    const updateHints = {
        raise_only: i18n.t("priority_policies.hints.raise_only"),
        recalculate: i18n.t("priority_policies.hints.recalculate"),
        initial_only: i18n.t("priority_policies.hints.initial_only"),
    };

    const sourceHints = {
        ignore: i18n.t("priority_policies.hints.source_ignore"),
        prefer: i18n.t("priority_policies.hints.source_prefer"),
    };

    const fallbackHints = {
        severity_mapping: i18n.t("priority_policies.hints.fallback_severity"),
        fixed_priority: i18n.t("priority_policies.hints.fallback_fixed"),
    };

    $("#priority-policy-update-mode-hint").text(updateHints[updateMode] || "");
    $("#priority-policy-source-priority-mode-hint").text(sourceHints[sourceMode] || "");
    $("#priority-policy-fallback-mode-hint").text(fallbackHints[fallbackMode] || "");
    $("#priority-policy-fallback-priority-field").toggleClass("is-hidden", fallbackMode !== "fixed_priority");
}

function loadPriorityPolicyMatcherPresets(policy, callback) {
    priorityPolicyMatcherPresetsCache = [];

    apiGet("/api/matcher-presets?team_id=" + encodeURIComponent(policy.team_id), function (presets) {
        priorityPolicyMatcherPresetsCache = asArray(presets);

        if (typeof callback === "function") {
            callback();
        }
    });
}

function getPriorityPolicyMatcherPresetById(presetId) {
    return priorityPolicyMatcherPresetsCache.find(function (preset) { return Number(preset.id) === Number(presetId); }) || null;
}

function getPriorityPolicyRuleMatcherPreset(rule) {
    return rule.matcher_preset || getPriorityPolicyMatcherPresetById(rule.matcher_preset_id);
}

function priorityPolicyMatcherPresetHint(preset) {
    if (!preset) {
        return i18n.t("priority_policies.preset.none_hint");
    }

    if (!preset.enabled) {
        return i18n.t("priority_policies.preset.disabled_hint");
    }

    return i18n.t("priority_policies.preset.active_hint", {name: preset.name, version: Number(preset.version || 1)});
}

function loadPriorityPolicyRuleCards(policyId, callback) {
    const container = $("#priority-policy-rule-cards");
    container.empty().append($("<div>").addClass("layer-card-loading").text(i18n.t("priority_policies.rules.loading")));

    apiGet("/api/priority-policies/" + policyId, function (policy) {
        rememberPriorityPolicyInCache(policy);
        selectedPriorityPolicyRulesId = policy.id;
        priorityPolicyRulesCache = asArray(policy.rules).slice().sort(function (left, right) { return Number(left.position || 0) - Number(right.position || 0); });

        $("#priority-policy-rules-title").text(i18n.t("priority_policies.rules.title_named", {name: policy.name}));
        $("#priority-policy-rules-subtitle").text((policy.team_slug || policy.team_name || "-") + " / " + (policy.enabled ? i18n.t("priority_policies.status.enabled") : i18n.t("priority_policies.status.disabled")));
        renderPriorityPolicyRuleCards();

        if (typeof callback === "function") {
            callback(policy);
        }
    });
}

function openPriorityPolicyRulesModal(policyId, ruleIdToExpand) {
    const policy = getPriorityPolicyById(policyId);

    if (!policy) {
        showAppError(i18n.t("priority_policies.errors.not_found"));
        return;
    }

    if (!canWriteObject(policy)) {
        showAppError(i18n.t("priority_policies.permissions.manage_rules"), i18n.t("priority_policies.errors.access_denied"));
        return;
    }

    selectedPriorityPolicyRulesId = policy.id;
    priorityPolicyRulesCache = [];
    priorityPolicyMatcherPresetsCache = [];
    expandedPriorityPolicyRuleId = ruleIdToExpand || null;
    unsavedPriorityPolicyRuleCounter = 0;

    $("#priority-policy-rules-title").text(i18n.t("priority_policies.rules.title_named", {name: policy.name}));
    $("#priority-policy-rules-subtitle").text(policy.team_slug || policy.team_name || "-");
    openAppModal("#priority-policy-rules-modal");

    loadPriorityPolicyMatcherPresets(policy, function () { loadPriorityPolicyRuleCards(policy.id); });
}

function closePriorityPolicyRulesModal() {
    closeAppModal("#priority-policy-rules-modal");
    selectedPriorityPolicyRulesId = null;
    priorityPolicyRulesCache = [];
    priorityPolicyMatcherPresetsCache = [];
    expandedPriorityPolicyRuleId = null;
    unsavedPriorityPolicyRuleCounter = 0;
    $("#priority-policy-rule-cards").empty().append($("<div>").addClass("empty-cell").text(i18n.t("priority_policies.rules.none_selected")));
}

function getNextPriorityPolicyRulePosition() {
    return priorityPolicyRulesCache.reduce(function (position, rule) { return Math.max(position, Number(rule.position || 0)); }, 0) + 1;
}

function createUnsavedPriorityPolicyRule() {
    unsavedPriorityPolicyRuleCounter += 1;
    const position = getNextPriorityPolicyRulePosition();
    const defaultPriority = priorityPolicyPrioritiesCache[0] || null;

    return {
        id: "new-" + unsavedPriorityPolicyRuleCounter,
        name: i18n.t("priority_policies.rules.default_name", {position: position}),
        description: "",
        position: position,
        matchers: {},
        matcher_preset_id: null,
        matcher_preset: null,
        priority_id: defaultPriority ? defaultPriority.id : null,
        priority: defaultPriority,
        enabled: true,
    };
}

function addPriorityPolicyRule() {
    if (!selectedPriorityPolicyRulesId) {
        showAppError(i18n.t("priority_policies.validation.policy_first"));
        return;
    }

    const rule = createUnsavedPriorityPolicyRule();
    priorityPolicyRulesCache.push(rule);
    expandedPriorityPolicyRuleId = rule.id;
    renderPriorityPolicyRuleCards();

    scrollToAndHighlight("[data-priority-policy-rule-id='" + rule.id + "']", {
        highlight: "[data-priority-policy-rule-id='" + rule.id + "']",
        block: "nearest",
        container: "#priority-policy-rules-modal",
    });
}

function formatPriorityPolicyRulePriority(rule) {
    const priority = rule.priority || getPriorityPolicyPriorityById(rule.priority_id);
    return priority ? priority.name + " (" + priority.slug + ")" : i18n.t("priority_policies.rules.no_priority");
}

function formatPriorityPolicyRuleMatchers(rule) {
    const preset = getPriorityPolicyRuleMatcherPreset(rule);
    const matchers = rule.matchers || {};
    const localMatchers = Object.keys(matchers).length ? JSON.stringify(matchers) : i18n.t("priority_policies.rules.all_alerts");

    if (!preset) {
        return localMatchers;
    }

    return preset.name + " · v" + Number(preset.version || 1) + (preset.enabled ? "" : " · " + i18n.t("priority_policies.rules.disabled_suffix")) + " AND " + localMatchers;
}

function renderPriorityPolicyRuleCards() {
    const container = $("#priority-policy-rule-cards");
    container.empty();

    if (!priorityPolicyRulesCache.length) {
        container.append($("<div>").addClass("empty-cell").text(i18n.t("priority_policies.rules.none")));
        return;
    }

    priorityPolicyRulesCache.forEach(function (rule, index) { container.append(renderPriorityPolicyRuleCard(rule, index + 1)); });
}

function renderPriorityPolicyRuleCard(rule, number) {
    const expanded = isSamePriorityPolicyRuleId(expandedPriorityPolicyRuleId, rule.id);
    const card = $("<div>").addClass("rotation-layer-card")
        .toggleClass("is-editing", expanded)
        .toggleClass("is-disabled", !rule.enabled)
        .toggleClass("is-unsaved", isUnsavedPriorityPolicyRule(rule))
        .attr("data-priority-policy-rule-id", rule.id);

    card.append(renderPriorityPolicyRuleHeader(rule, number));
    card.append(renderPriorityPolicyRuleSummary(rule));
    card.append(renderPriorityPolicyRuleEditor(rule));
    return card;
}

function renderPriorityPolicyRuleHeader(rule, number) {
    const expanded = isSamePriorityPolicyRuleId(expandedPriorityPolicyRuleId, rule.id);
    const unsaved = isUnsavedPriorityPolicyRule(rule);
    const header = $("<div>").addClass("rotation-layer-card-header");
    const actions = $("<div>").addClass("rotation-layer-header-actions");

    header.append($("<div>").addClass("rotation-layer-number").text(number));
    header.append(
        $("<div>").addClass("rotation-layer-title")
            .append($("<strong>").text(rule.name + (unsaved ? " · " + i18n.t("priority_policies.rules.unsaved") : "")))
            .append($("<span>").text(formatPriorityPolicyRulePriority(rule)))
    );

    actions.append($("<button>").attr("type", "button").addClass("btn btn-small").text(expanded ? i18n.t("priority_policies.actions.collapse") : i18n.t("priority_policies.actions.edit")).on("click", function () { togglePriorityPolicyRuleEditor(rule.id); }));
    actions.append($("<button>").attr("type", "button").addClass("btn btn-danger btn-small").text(unsaved ? i18n.t("priority_policies.actions.remove") : i18n.t("priority_policies.actions.delete")).on("click", function () { deletePriorityPolicyRule(rule.id); }));
    header.append(actions);
    return header;
}

function renderPriorityPolicyRuleSummary(rule) {
    return $("<div>").addClass("rotation-layer-summary")
        .append($("<div>").addClass("rotation-layer-summary-item").append($("<span>").text(i18n.t("priority_policies.rules.priority"))).append($("<strong>").text(formatPriorityPolicyRulePriority(rule))))
        .append($("<div>").addClass("rotation-layer-summary-item").append($("<span>").text(i18n.t("priority_policies.rules.matchers"))).append($("<strong>").text(formatPriorityPolicyRuleMatchers(rule))))
        .append($("<div>").addClass("rotation-layer-summary-item").append($("<span>").text(i18n.t("priority_policies.rules.status"))).append($("<strong>").text(rule.enabled ? i18n.t("priority_policies.status.enabled") : i18n.t("priority_policies.status.disabled"))));
}

function priorityPolicyRuleFieldId(ruleId, field) {
    return "priority-policy-rule-" + ruleId + "-" + field;
}

function priorityPolicyRuleTextField(rule, field, label, value, columnClass) {
    const id = priorityPolicyRuleFieldId(rule.id, field);

    return $("<div>").addClass("app-field " + (columnClass || "layer-settings-col-6"))
        .append($("<label>").attr("for", id).text(label))
        .append($("<input>").attr("id", id).attr("type", "text").addClass("input").val(value || ""));
}

function priorityPolicyRuleNumberField(rule, field, label, value, columnClass) {
    const id = priorityPolicyRuleFieldId(rule.id, field);

    return $("<div>").addClass("app-field " + (columnClass || "layer-settings-col-2"))
        .append($("<label>").attr("for", id).text(label))
        .append($("<input>").attr("id", id).attr("type", "number").attr("min", "1").addClass("input").val(value || 1));
}

function priorityPolicyRuleCheckbox(rule, field, label, checked, columnClass) {
    return $("<label>").addClass("md-checkbox app-field layer-settings-checkbox " + (columnClass || "layer-settings-col-6"))
        .append($("<input>").attr("id", priorityPolicyRuleFieldId(rule.id, field)).attr("type", "checkbox").prop("checked", !!checked))
        .append($("<span>").text(label));
}

function priorityPolicyRulePriorityField(rule) {
    const id = priorityPolicyRuleFieldId(rule.id, "priority");
    const select = $("<select>").attr("id", id).addClass("input");

    priorityPolicyPrioritiesCache.forEach(function (priority) {
        select.append($("<option>").val(String(priority.id)).text(priority.name + " (" + priority.slug + ")"));
    });

    select.val(rule.priority_id ? String(rule.priority_id) : "");

    return $("<div>").addClass("app-field layer-settings-col-4")
        .append($("<label>").attr("for", id).text(i18n.t("priority_policies.rules.incident_priority")))
        .append(select);
}

function priorityPolicyRuleMatcherPresetField(rule) {
    const id = priorityPolicyRuleFieldId(rule.id, "matcher-preset");
    const hintId = priorityPolicyRuleFieldId(rule.id, "matcher-preset-hint");
    const selectedPresetId = rule.matcher_preset_id || (rule.matcher_preset ? rule.matcher_preset.id : null);
    const select = $("<select>").attr("id", id).attr("data-rule-id", rule.id).addClass("input priority-policy-rule-matcher-preset");

    select.append($("<option>").val("").text(i18n.t("priority_policies.rules.no_preset")));

    priorityPolicyMatcherPresetsCache.forEach(function (preset) {
        const selected = Number(preset.id) === Number(selectedPresetId);
        const label = preset.name + " · v" + Number(preset.version || 1) + (preset.enabled ? "" : " · " + i18n.t("priority_policies.rules.disabled_suffix"));
        const option = $("<option>").val(String(preset.id)).text(label);

        if (!preset.enabled && !selected) {
            option.prop("disabled", true);
        }

        select.append(option);
    });

    select.val(selectedPresetId ? String(selectedPresetId) : "");
    const preset = getPriorityPolicyMatcherPresetById(selectedPresetId) || rule.matcher_preset || null;

    return $("<div>").addClass("app-field layer-settings-col-4")
        .append($("<label>").attr("for", id).text(i18n.t("priority_policies.rules.matcher_preset")))
        .append(select)
        .append($("<div>").attr("id", hintId).addClass("help-text").text(priorityPolicyMatcherPresetHint(preset)));
}

function priorityPolicyRuleMatchersField(rule) {
    return createMatcherEditor({
        id: priorityPolicyRuleFieldId(rule.id, "matchers"),
        value: rule.matchers || {},
        label: i18n.t("priority_policies.rules.additional_matchers"),
        helpText: i18n.t("priority_policies.rules.additional_help"),
        context: function () {
            const policy = getPriorityPolicyById(selectedPriorityPolicyRulesId);
            const matcherPresetId = Number($("#" + priorityPolicyRuleFieldId(rule.id, "matcher-preset")).val()) || null;

            return {
                scope: "priority_policy",
                teamId: policy ? policy.team_id : null,
                policyId: selectedPriorityPolicyRulesId,
                ruleId: rule.id,
                matcherPresetId: matcherPresetId,
            };
        },
    });
}

function renderPriorityPolicyRuleEditor(rule) {
    const editor = $("<div>").addClass("rotation-layer-editor");
    const section = $("<section>").addClass("layer-editor-section");
    const grid = $("<div>").addClass("layer-settings-grid");

    section.append($("<h4>").text(i18n.t("priority_policies.rules.settings")));
    section.append($("<div>").addClass("layer-editor-section-subtitle").text(i18n.t("priority_policies.rules.settings_help")));

    grid.append(priorityPolicyRuleTextField(rule, "name", i18n.t("priority_policies.rules.name"), rule.name, "layer-settings-col-6"));
    grid.append(priorityPolicyRuleNumberField(rule, "position", i18n.t("priority_policies.rules.position"), rule.position, "layer-settings-col-2"));
    grid.append(priorityPolicyRuleCheckbox(rule, "enabled", i18n.t("priority_policies.rules.enabled"), rule.enabled !== false, "layer-settings-col-4"));
    grid.append(priorityPolicyRulePriorityField(rule));
    grid.append(priorityPolicyRuleMatcherPresetField(rule));

    const descriptionId = priorityPolicyRuleFieldId(rule.id, "description");

    grid.append(
        $("<div>").addClass("app-field layer-settings-col-12")
            .append($("<label>").attr("for", descriptionId).text(i18n.t("priority_policies.rules.description")))
            .append($("<textarea>").attr("id", descriptionId).attr("rows", "3").addClass("input").val(rule.description || ""))
    );

    grid.append(priorityPolicyRuleMatchersField(rule));
    section.append(grid);

    section.append(
        $("<div>").addClass("layer-editor-actions")
            .append($("<button>").attr("type", "button").addClass("btn btn-primary btn-small").text(i18n.t("priority_policies.actions.save_rule")).on("click", function () { savePriorityPolicyRule(rule.id); }))
            .append($("<button>").attr("type", "button").addClass("btn btn-danger btn-small").text(i18n.t("priority_policies.actions.delete_rule")).on("click", function () { deletePriorityPolicyRule(rule.id); }))
    );

    editor.append(section);
    return editor;
}

function collectPriorityPolicyRulePayload(ruleId) {
    const prefix = "#priority-policy-rule-" + ruleId + "-";

    return {
        name: $(prefix + "name").val(),
        description: $(prefix + "description").val(),
        position: Number($(prefix + "position").val() || 1),
        matcher_preset_id: $(prefix + "matcher-preset").val() ? Number($(prefix + "matcher-preset").val()) : null,
        matchers: getMatcherEditorValue(prefix + "matchers", {}),
        priority_id: Number($(prefix + "priority").val()),
        enabled: $(prefix + "enabled").is(":checked"),
    };
}

function savePriorityPolicyRule(ruleId) {
    const payload = collectPriorityPolicyRulePayload(ruleId);

    if (!String(payload.name || "").trim()) {
        showAppError(i18n.t("priority_policies.validation.rule_name_required"));
        return;
    }

    if (!payload.priority_id) {
        showAppError(i18n.t("priority_policies.validation.priority_required"));
        return;
    }

    if (isUnsavedPriorityPolicyRule(ruleId)) {
        apiPost("/api/priority-policies/" + selectedPriorityPolicyRulesId + "/rules", payload, function (rule) {
            expandedPriorityPolicyRuleId = rule.id;
            reloadPriorityPolicyRules();
        });
        return;
    }

    apiPut("/api/priority-policies/" + selectedPriorityPolicyRulesId + "/rules/" + ruleId, payload, function () {
        expandedPriorityPolicyRuleId = ruleId;
        reloadPriorityPolicyRules();
    });
}

function reloadPriorityPolicyRules() {
    if (!selectedPriorityPolicyRulesId) {
        return;
    }

    loadPriorityPolicyRuleCards(selectedPriorityPolicyRulesId, function () { refreshPriorityPolicies(); });
}

function deletePriorityPolicyRule(ruleId) {
    if (isUnsavedPriorityPolicyRule(ruleId)) {
        priorityPolicyRulesCache = priorityPolicyRulesCache.filter(function (rule) { return !isSamePriorityPolicyRuleId(rule.id, ruleId); });

        if (isSamePriorityPolicyRuleId(expandedPriorityPolicyRuleId, ruleId)) {
            expandedPriorityPolicyRuleId = null;
        }

        renderPriorityPolicyRuleCards();
        return;
    }

    showAppConfirm({
        title: i18n.t("priority_policies.confirm.delete_rule_title"),
        message: i18n.t("priority_policies.confirm.delete_rule_message", {id: ruleId}),
        confirmText: i18n.t("priority_policies.confirm.delete_rule"),
        confirmClass: "btn-danger",
    }).done(function () {
        apiDelete("/api/priority-policies/" + selectedPriorityPolicyRulesId + "/rules/" + ruleId, function () {
            expandedPriorityPolicyRuleId = null;
            reloadPriorityPolicyRules();
        });
    });
}

function togglePriorityPolicyRuleEditor(ruleId) {
    expandedPriorityPolicyRuleId = isSamePriorityPolicyRuleId(expandedPriorityPolicyRuleId, ruleId) ? null : ruleId;
    renderPriorityPolicyRuleCards();
}

$(document).on("click", "#open-priority-policy-create-modal", openCreatePriorityPolicyModal);
$(document).on("click", "#close-priority-policy-form-modal", function () { closeAppModal("#priority-policy-form-modal"); });
$(document).on("click", "#reset-priority-policy-form", resetPriorityPolicyForm);
$(document).on("click", "#save-priority-policy", savePriorityPolicy);
$(document).on("click", "#reload-priority-policies", refreshPriorityPolicies);
$(document).on("input", "#priority-policies-search", function () { renderPriorityPoliciesTable(); restorePriorityPolicyDetails(); });
$(document).on("change", "#priority-policies-status-filter", function () { renderPriorityPoliciesTable(); restorePriorityPolicyDetails(); });
$(document).on("change", "#priority-policy-update-mode, #priority-policy-source-priority-mode, #priority-policy-fallback-mode", updatePriorityPolicyBehaviorHints);
$(document).on("click", "#add-priority-policy-rule", addPriorityPolicyRule);
$(document).on("click", "#reload-priority-policy-rules", reloadPriorityPolicyRules);
$(document).on("click", "#close-priority-policy-rules-modal, #close-priority-policy-rules-modal-footer", closePriorityPolicyRulesModal);

$(document).on("change", ".priority-policy-rule-matcher-preset", function () {
    const ruleId = $(this).attr("data-rule-id");
    const preset = getPriorityPolicyMatcherPresetById($(this).val());
    $("#" + priorityPolicyRuleFieldId(ruleId, "matcher-preset-hint")).text(priorityPolicyMatcherPresetHint(preset));
});

