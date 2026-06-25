let escalationPoliciesCache = [];
let selectedEscalationPolicyDetailsId = null;
let selectedEscalationPolicyRulesId = null;
let selectedEscalationPolicyRulesName = "";
let escalationPolicyRulesCache = [];
let escalationRuleTargetRotationsCache = [];
let escalationRuleTargetUsersCache = [];
let expandedEscalationRuleId = null;
let unsavedEscalationRuleCounter = 0;

function isUnsavedEscalationRule(ruleOrId) {
    const value = typeof ruleOrId === "object" ? ruleOrId.id : ruleOrId;

    return String(value || "").indexOf("new-") === 0;
}

function isSameEscalationRuleId(left, right) {
    return String(left) === String(right);
}

function getEscalationRuleTargetName(targetType, targetId) {
    if (targetType === "rotation") {
        const rotation = escalationRuleTargetRotationsCache.find(function (item) {
            return Number(item.id) === Number(targetId);
        });

        return rotation ? rotation.name : null;
    }

    if (targetType === "user") {
        const member = escalationRuleTargetUsersCache.find(function (item) {
            return Number(item.user_id) === Number(targetId);
        });

        return member
            ? (member.display_name || member.username || ("User #" + member.user_id))
            : null;
    }

    return null;
}

function createUnsavedEscalationRule() {
    const target = getDefaultEscalationRuleTarget();

    if (!target) {
        return null;
    }

    unsavedEscalationRuleCounter += 1;

    return {
        id: "new-" + unsavedEscalationRuleCounter,
        position: getNextEscalationRulePosition(),
        delay_seconds: 300,
        target_type: target.target_type,
        target_id: target.target_id,
        target_name: getEscalationRuleTargetName(target.target_type, target.target_id),
        enabled: true,
        is_new: true,
    };
}

function loadEscalationPolicies() {
    fillTeamSelect("#escalation-policy-team", false, function () {
        resetEscalationPolicyForm();
    });

    refreshEscalationPolicies();
    updateEscalationPolicyCreateButtonState();
}

function buildEscalationPoliciesApiUrl() {
    return "/api/escalation-policies" + selectedTeamQuery();
}

function updateEscalationPolicyCreateButtonState() {
    const allowed = currentUserCanCreateUiObjects();

    $("#open-escalation-policy-create-modal")
        .toggleClass("is-hidden", !allowed)
        .prop("disabled", !allowed);
}

function refreshEscalationPolicies() {
    apiGet(buildEscalationPoliciesApiUrl(), function (policies) {
        escalationPoliciesCache = asArray(policies);
        renderEscalationPoliciesSummary(escalationPoliciesCache);
        renderEscalationPoliciesTable();
        restoreEscalationPolicyDetails();
        updateEscalationPolicyCreateButtonState();
    });
}

function renderEscalationPoliciesSummary(policies) {
    policies = asArray(policies);

    const enabled = policies.filter(function (policy) {
        return !!policy.enabled;
    }).length;

    const rulesCount = policies.reduce(function (total, policy) {
        return total + asArray(policy.rules).length;
    }, 0);

    $("#escalation-policies-summary-total").text(policies.length);
    $("#escalation-policies-summary-enabled").text(enabled);
    $("#escalation-policies-summary-disabled").text(policies.length - enabled);
    $("#escalation-policies-summary-rules").text(rulesCount);
}

function getEscalationPolicySearchText(policy) {
    const rules = asArray(policy.rules).map(function (rule) {
        return [
            rule.position,
            rule.target_type,
            rule.target_name,
            rule.enabled ? "enabled" : "disabled",
        ].join(" ");
    }).join(" ");

    return [
        policy.id,
        policy.team_slug,
        policy.team_name,
        policy.name,
        policy.description,
        policy.enabled ? "enabled" : "disabled",
        rules,
    ].join(" ").toLowerCase();
}

function getFilteredEscalationPolicies() {
    const query = String($("#escalation-policies-search").val() || "").trim().toLowerCase();
    const status = String($("#escalation-policies-status-filter").val() || "");

    return escalationPoliciesCache.filter(function (policy) {
        if (status === "enabled" && !policy.enabled) {
            return false;
        }

        if (status === "disabled" && policy.enabled) {
            return false;
        }

        if (!query) {
            return true;
        }

        return getEscalationPolicySearchText(policy).indexOf(query) !== -1;
    });
}

function applyEscalationPolicyFilters() {
    renderEscalationPoliciesTable();
    restoreEscalationPolicyDetails();
}

function renderEscalationPoliciesCounter(filteredPolicies, allPolicies) {
    filteredPolicies = asArray(filteredPolicies);
    allPolicies = asArray(allPolicies);

    $("#escalation-policies-filtered-count").text(filteredPolicies.length);
    $("#escalation-policies-total-count").text(allPolicies.length);
}

function renderEscalationPoliciesTable() {
    const tbody = $("#escalation-policies-table");
    const policies = getFilteredEscalationPolicies();

    tbody.empty();
    renderEscalationPoliciesCounter(policies, escalationPoliciesCache);

    if (!policies.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>")
                    .attr("colspan", "6")
                    .addClass("empty-cell")
                    .text("No escalation policies")
            )
        );
        return;
    }

    policies.forEach(function (policy) {
        tbody.append(renderEscalationPolicyRow(policy));
    });
}

function renderEscalationPolicyRow(policy) {
    const row = $("<tr>").toggleClass("row-disabled", !policy.enabled);
    const rules = asArray(policy.rules);

    row.append(
        $("<td>")
            .append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("name-button")
                    .text(policy.name || "-")
                    .on("click", function () {
                        renderEscalationPolicyDetails(policy, { scroll: true });
                    })
            )
            .append(
                $("<div>")
                    .addClass("row-subtitle")
                    .text(policy.description || "Policy #" + policy.id)
            )
    );

    row.append(
        $("<td>").append(
            $("<span>")
                .addClass("pill")
                .text(policy.team_slug || policy.team_name || "-")
        )
    );
    row.append($("<td>").text(rules.length));
    row.append($("<td>").text(policy.repeat_count || 0));
    row.append($("<td>").append(renderStatusBadge(policy.enabled, "Enabled", "Disabled")));
    row.append($("<td>").addClass("actions-cell").append(renderEscalationPolicyActions(policy)));

    return row;
}

function renderEscalationPolicyActions(policy) {
    return makeActionMenu({
        object: policy,
        items: [
            {
                label: "Edit",
                icon: "fas fa-edit",
                required: "write",
                denyMessage: "Team manager role is required to edit this policy.",
                onClick: function () {
                    editEscalationPolicy(policy.id);
                }
            },
            {
                label: "Rules",
                icon: "fas fa-list-ol",
                required: "write",
                denyMessage: "Team manager role is required to manage policy rules.",
                onClick: function () {
                    openEscalationRulesModal(policy.id);
                }
            },
            {
                label: policy.enabled ? "Disable" : "Enable",
                icon: policy.enabled ? "fas fa-pause" : "fas fa-play",
                required: "write",
                danger: policy.enabled,
                denyMessage: "Team manager role is required to enable or disable this policy.",
                onClick: function () {
                    setEscalationPolicyEnabled(policy, !policy.enabled);
                }
            },
            {
                label: "Remove",
                icon: "fas fa-trash",
                required: "delete",
                danger: true,
                denyMessage: "Delete permission is required to remove this policy.",
                onClick: function () {
                    removeEscalationPolicy(policy);
                }
            }
        ]
    });
}

function escalationPolicyDetailsItem(label, value) {
    return $("<div>")
        .addClass("details-item")
        .append($("<div>").addClass("details-label").text(label))
        .append($("<div>").addClass("details-value").text(value || "-"));
}

function formatEscalationPolicyRule(rule) {
    const target = upperCaseFirst(rule.target_type || "-") + ": " + (rule.target_name || rule.target_id || "-");
    const delay = formatSeconds(rule.delay_seconds || 0);
    const status = rule.enabled ? "enabled" : "disabled";

    return "#" + rule.position + " — " + target + " — after " + delay + " — " + status;
}

function renderEscalationPolicyRules(policy) {
    const wrapper = $("<div>").addClass("details-list");
    const rules = asArray(policy.rules).slice().sort(function (left, right) {
        return Number(left.position || 0) - Number(right.position || 0);
    });

    const header = $("<div>").addClass("details-item");
    const actions = $("<div>").addClass("table-actions");

    header.append($("<div>").addClass("details-label").text("Rules"));
    header.append(
        $("<div>")
            .addClass("details-value")
            .text(rules.length ? rules.length + " configured" : "No rules")
    );

    appendActionIfAllowed(actions, policy, {
        required: "write",
        text: "Manage rules",
        className: "btn btn-small",
        onClick: function () {
            openEscalationRulesModal(policy.id);
        },
    });

    if (actions.children().length) {
        header.append(actions);
    }

    wrapper.append(header);

    if (!rules.length) {
        wrapper.append(
            $("<div>")
                .addClass("details-item")
                .append($("<div>").addClass("details-label").text("First rule"))
                .append(
                    $("<div>")
                        .addClass("details-value")
                        .text("Open rules and add the first escalation rule.")
                )
        );
        return wrapper;
    }

    rules.forEach(function (rule) {
        wrapper.append(
            $("<div>")
                .addClass("details-item")
                .append($("<div>").addClass("details-label").text("Rule " + rule.position))
                .append($("<div>").addClass("details-value").text(formatEscalationPolicyRule(rule)))
        );
    });

    return wrapper;
}

function renderEscalationPolicyDetails(policy, options) {
    selectedEscalationPolicyDetailsId = policy.id;

    $("#escalation-policy-details-subtitle").text(
        (policy.team_slug || policy.team_name || "-") + " / " + (policy.enabled ? "Enabled" : "Disabled")
    );

    const body = $("#escalation-policy-details-body");
    body.empty();

    body.append(
        $("<div>")
            .addClass("details-list")
            .append(escalationPolicyDetailsItem("Name", policy.name))
            .append(escalationPolicyDetailsItem("Team", policy.team_slug || policy.team_name))
            .append(escalationPolicyDetailsItem("Description", policy.description))
            .append(escalationPolicyDetailsItem("Repeat count", policy.repeat_count || 0))
            .append(escalationPolicyDetailsItem("Status", policy.enabled ? "Enabled" : "Disabled"))
    );

    body.append(renderEscalationPolicyRules(policy));

    const actions = $("<div>").addClass("details-actions");

    appendIconActionIfAllowed(actions, policy, {
        required: "write",
        icon: "fas fa-edit",
        label: "Edit policy",
        onClick: function () {
            editEscalationPolicy(policy.id);
        },
    });

    appendIconActionIfAllowed(actions, policy, {
        required: "write",
        icon: "fas fa-layer-group",
        label: "Manage rules",
        onClick: function () {
            openEscalationRulesModal(policy.id);
        },
    });

    appendIconActionIfAllowed(actions, policy, {
        required: "write",
        icon: policy.enabled ? "fas fa-pause" : "fas fa-play",
        label: policy.enabled ? "Disable policy" : "Enable policy",
        className: policy.enabled ? "btn-warning" : "btn-success",
        onClick: function () {
            setEscalationPolicyEnabled(policy, !policy.enabled);
        },
    });

    appendIconActionIfAllowed(actions, policy, {
        required: "delete",
        icon: "fas fa-trash-alt",
        label: "Remove policy",
        className: "btn-danger",
        onClick: function () {
            removeEscalationPolicy(policy);
        },
    });

    if (actions.children().length) {
        body.append(actions);
    }

    if (options && options.scroll && typeof scrollToAndHighlight === "function") {
        scrollToAndHighlight("#escalation-policy-details-body", {
            highlight: "#escalation-policy-details-body",
            block: "nearest",
        });
    }
}

function renderEscalationPolicyDetailsEmpty() {
    selectedEscalationPolicyDetailsId = null;
    $("#escalation-policy-details-subtitle").text("Select a policy");
    $("#escalation-policy-details-body").html("Click a policy name to inspect rules and quick actions.");
}

function restoreEscalationPolicyDetails() {
    const policies = getFilteredEscalationPolicies();

    if (!policies.length) {
        renderEscalationPolicyDetailsEmpty();
        return;
    }

    if (selectedEscalationPolicyDetailsId) {
        const selected = policies.find(function (policy) {
            return Number(policy.id) === Number(selectedEscalationPolicyDetailsId);
        });

        if (selected) {
            renderEscalationPolicyDetails(selected);
            return;
        }
    }

    renderEscalationPolicyDetails(policies[0]);
}

function getEscalationPolicyById(id) {
    return escalationPoliciesCache.find(function (policy) {
        return Number(policy.id) === Number(id);
    }) || null;
}

function rememberEscalationPolicyInCache(policy) {
    /*
     * Update cached policy after loading it from the rule modal.
     */
    if (!policy || !policy.id) {
        return;
    }

    const index = escalationPoliciesCache.findIndex(function (item) {
        return Number(item.id) === Number(policy.id);
    });

    if (index >= 0) {
        escalationPoliciesCache[index] = policy;
        return;
    }

    escalationPoliciesCache.push(policy);
}

function getEscalationPolicyRuleById(policy, ruleId) {
    return asArray(policy && policy.rules).find(function (rule) {
        return Number(rule.id) === Number(ruleId);
    }) || null;
}

function collectEscalationPolicyPayload() {
    return {
        team_id: Number($("#escalation-policy-team").val()),
        name: $("#escalation-policy-name").val(),
        description: $("#escalation-policy-description").val(),
        repeat_count: Number($("#escalation-policy-repeat-count").val() || 0),
        enabled: $("#escalation-policy-enabled").is(":checked"),
    };
}

function saveEscalationPolicy() {
    const id = $("#escalation-policy-id").val();
    const payload = collectEscalationPolicyPayload();

    if (id) {
        delete payload.team_id;

        apiPut("/api/escalation-policies/" + id, payload, function () {
            closeAppModal("#escalation-policy-form-modal");
            resetEscalationPolicyForm();
            refreshEscalationPolicies();
        });
        return;
    }

    apiPost("/api/escalation-policies", payload, function () {
        closeAppModal("#escalation-policy-form-modal");
        resetEscalationPolicyForm();
        refreshEscalationPolicies();
    });
}

function resetEscalationPolicyForm() {
    $("#escalation-policy-form-title").text("Create policy");
    $("#escalation-policy-id").val("");
    $("#escalation-policy-name").val("");
    $("#escalation-policy-description").val("");
    $("#escalation-policy-repeat-count").val("0");
    $("#escalation-policy-enabled").prop("checked", true);
    $("#escalation-policy-team").prop("disabled", false);

    const selectedTeam = $("#global-team-filter").val();
    if (selectedTeam) {
        $("#escalation-policy-team").val(selectedTeam);
    }
}

function openCreateEscalationPolicyModal() {
    if (!currentUserCanCreateUiObjects()) {
        showAppError("Write role is required to create policies.", "Access denied");
        return;
    }

    resetEscalationPolicyForm();
    openAppModal("#escalation-policy-form-modal");
}

function editEscalationPolicy(id) {
    const policy = getEscalationPolicyById(id);

    if (!policy) {
        showAppError("Policy was not found.");
        return;
    }

    if (!canWriteObject(policy)) {
        showAppError("You do not have permission to edit this policy.", "Access denied");
        return;
    }

    $("#escalation-policy-form-title").text("Edit policy #" + id);
    $("#escalation-policy-id").val(policy.id);
    $("#escalation-policy-team").val(policy.team_id).prop("disabled", true);
    $("#escalation-policy-name").val(policy.name || "");
    $("#escalation-policy-description").val(policy.description || "");
    $("#escalation-policy-repeat-count").val(policy.repeat_count || 0);
    $("#escalation-policy-enabled").prop("checked", !!policy.enabled);

    openAppModal("#escalation-policy-form-modal");
}

function setEscalationPolicyEnabled(policy, enabled) {
    if (!canWriteObject(policy)) {
        showAppError("You do not have permission to update this policy.", "Access denied");
        return;
    }

    apiPut("/api/escalation-policies/" + policy.id, { enabled: !!enabled }, refreshEscalationPolicies);
}

function removeEscalationPolicy(policy) {
    if (!canDeleteObject(policy)) {
        showAppError("You do not have permission to remove this policy.", "Access denied");
        return;
    }

    showAppConfirm({
        title: "Remove this policy?",
        message: "Remove policy '" + policy.name + "'? Existing alerts keep their current state, but new routes will not be able to use this policy.",
        confirmText: "Remove policy",
        confirmClass: "btn-danger",
    }).done(function () {
        apiDelete("/api/escalation-policies/" + policy.id, refreshEscalationPolicies);
    });
}

function closeEscalationRulesModal() {
    closeAppModal("#escalation-rules-modal");

    selectedEscalationPolicyRulesId = null;
    selectedEscalationPolicyRulesName = "";
    escalationPolicyRulesCache = [];
    escalationRuleTargetRotationsCache = [];
    escalationRuleTargetUsersCache = [];
    expandedEscalationRuleId = null;
    unsavedEscalationRuleCounter = 0;

    $("#escalation-rule-cards")
        .empty()
        .append(
            $("<div>")
                .addClass("empty-cell")
                .text("No policy selected")
        );
}

function openEscalationRulesModal(policyId, ruleIdToExpand) {
    const policy = getEscalationPolicyById(policyId);

    if (!policy) {
        showAppError("Policy was not found.");
        return;
    }

    if (!canWriteObject(policy)) {
        showAppError("You do not have permission to manage policy rules.", "Access denied");
        return;
    }

    selectedEscalationPolicyRulesId = policy.id;
    selectedEscalationPolicyRulesName = policy.name || ("policy #" + policy.id);
    expandedEscalationRuleId = ruleIdToExpand || null;
    escalationPolicyRulesCache = [];
    escalationRuleTargetRotationsCache = [];
    escalationRuleTargetUsersCache = [];

    $("#escalation-rules-title").text("Policy rules: " + selectedEscalationPolicyRulesName);
    $("#escalation-rules-subtitle").text(
        (policy.team_slug || policy.team_name || "-") + " / " + (policy.enabled ? "Enabled" : "Disabled")
    );

    openAppModal("#escalation-rules-modal");

    loadEscalationRuleTargetsForPolicy(policy, function () {
        loadEscalationRuleCards(policy.id);
    });
}

function loadEscalationRuleTargetsForPolicy(policy, callback) {
    if (!policy) {
        escalationRuleTargetRotationsCache = [];
        escalationRuleTargetUsersCache = [];

        if (typeof callback === "function") {
            callback();
        }
        return;
    }

    let rotationsLoaded = false;
    let usersLoaded = false;

    function finishWhenReady() {
        if (!rotationsLoaded || !usersLoaded) {
            return;
        }

        if (typeof callback === "function") {
            callback();
        }
    }

    apiGet("/api/rotations?team_id=" + encodeURIComponent(policy.team_id), function (rotations) {
        escalationRuleTargetRotationsCache = asArray(rotations).filter(function (rotation) {
            return rotation.enabled !== false;
        });

        rotationsLoaded = true;
        finishWhenReady();
    });

    apiGet("/api/teams/" + policy.team_id + "/users", function (members) {
        escalationRuleTargetUsersCache = asArray(members).filter(function (member) {
            return member.active !== false;
        });

        usersLoaded = true;
        finishWhenReady();
    });
}

function loadEscalationRuleCards(policyId, callback) {
    const container = $("#escalation-rule-cards");

    container
        .empty()
        .append(
            $("<div>")
                .addClass("layer-card-loading")
                .text("Loading rules...")
        );

    apiGet("/api/escalation-policies/" + policyId, function (policy) {
        rememberEscalationPolicyInCache(policy);
        selectedEscalationPolicyRulesId = policy.id;
        selectedEscalationPolicyRulesName = policy.name || ("policy #" + policy.id);
        escalationPolicyRulesCache = asArray(policy.rules).slice().sort(function (left, right) {
            return Number(left.position || 0) - Number(right.position || 0);
        });

        $("#escalation-rules-title").text("Policy rules: " + selectedEscalationPolicyRulesName);
        $("#escalation-rules-subtitle").text(
            (policy.team_slug || policy.team_name || "-") + " / " + (policy.enabled ? "Enabled" : "Disabled")
        );

        renderEscalationRuleCards();
        renderEscalationPoliciesSummary(escalationPoliciesCache);
        renderEscalationPoliciesTable();
        restoreEscalationPolicyDetails();

        if (typeof callback === "function") {
            callback(policy);
        }
    });
}

function renderEscalationRuleCards() {
    const container = $("#escalation-rule-cards");

    container.find("select.js-user-select").each(function () {
        destroyTomSelectIfExists(this);
    });

    container.empty();

    if (!escalationPolicyRulesCache.length) {
        container.append(
            $("<div>")
                .addClass("empty-cell")
                .text("No rules. Add the first rule to define the escalation chain.")
        );
        return;
    }

    escalationPolicyRulesCache.forEach(function (rule, index) {
        container.append(renderEscalationRuleCard(rule, index + 1));
    });

    initUserTomSelects(container);

    escalationPolicyRulesCache.forEach(function (rule) {
        updateEscalationRuleTargetTypeUi(rule.id);
    });
}

function renderEscalationRuleCard(rule, number) {
    const isExpanded = isSameEscalationRuleId(expandedEscalationRuleId, rule.id);

    const card = $("<div>")
        .addClass("rotation-layer-card escalation-rule-card")
        .toggleClass("is-editing", isExpanded)
        .toggleClass("is-disabled", !rule.enabled)
        .toggleClass("is-unsaved", isUnsavedEscalationRule(rule))
        .attr("data-rule-id", rule.id);

    card.append(renderEscalationRuleCardHeader(rule, number));
    card.append(renderEscalationRuleSummary(rule));
    card.append(renderEscalationRuleEditor(rule));

    return card;
}

function renderEscalationRuleCardHeader(rule, number) {
    const header = $("<div>").addClass("rotation-layer-card-header");
    const actions = $("<div>").addClass("rotation-layer-header-actions");
    const isExpanded = isSameEscalationRuleId(expandedEscalationRuleId, rule.id);
    const isUnsaved = isUnsavedEscalationRule(rule);

    header.append(
        $("<div>")
            .addClass("rotation-layer-number")
            .text(number)
    );

    const title = $("<div>")
        .addClass("rotation-layer-title")
        .append(
            $("<strong>").text(
                "Rule " + (rule.position || number) + (isUnsaved ? " · unsaved" : "")
            )
        )
        .append(
            $("<span>").text(
                formatRuleTargetSummary(rule) +
                " · after " + formatSeconds(rule.delay_seconds || 0) +
                " · " + (rule.enabled ? "Enabled" : "Disabled")
            )
        );

    header.append(title);

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-small")
            .text(isExpanded ? "Collapse" : "Edit")
            .on("click", function () {
                toggleEscalationRuleEditor(rule.id);
            })
    );

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-danger btn-small")
            .text(isUnsaved ? "Remove" : "Delete")
            .on("click", function () {
                deleteEscalationRule(rule.id);
            })
    );

    header.append(actions);

    return header;
}

function renderEscalationRuleSummary(rule) {
    const summary = $("<div>").addClass("rotation-layer-summary");

    summary.append(
        $("<div>")
            .addClass("rotation-layer-summary-item")
            .append($("<span>").text("Target"))
            .append($("<strong>").text(formatRuleTargetSummary(rule)))
    );

    summary.append(
        $("<div>")
            .addClass("rotation-layer-summary-item")
            .append($("<span>").text("Escalate after"))
            .append($("<strong>").text(formatSeconds(rule.delay_seconds || 0)))
    );

    summary.append(
        $("<div>")
            .addClass("rotation-layer-summary-item")
            .append($("<span>").text("Status"))
            .append($("<strong>").text(rule.enabled ? "Enabled" : "Disabled"))
    );

    return summary;
}

function renderEscalationRuleEditor(rule) {
    const editor = $("<div>").addClass("rotation-layer-editor escalation-rule-editor");
    const section = $("<section>").addClass("layer-editor-section");
    const grid = $("<div>").addClass("app-form-grid");

    section.append($("<h4>").text("Rule settings"));
    section.append(
        $("<div>")
            .addClass("layer-editor-section-subtitle")
            .text("Configure position, delay and the target for this escalation rule.")
    );

    grid.append(ruleNumberField(rule.id, "position", "Position", rule.position || 1, 1));
    grid.append(ruleNumberField(rule.id, "delay-seconds", "Escalate after seconds", rule.delay_seconds || 0, 0));
    grid.append(ruleTargetTypeField(rule));
    grid.append(ruleRotationTargetField(rule));
    grid.append(ruleUserTargetField(rule));
    grid.append(ruleCheckboxField(rule.id, "enabled", "Enabled", rule.enabled !== false));

    section.append(grid);
    section.append(
        $("<div>")
            .addClass("layer-editor-actions")
            .append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("btn btn-primary btn-small")
                    .text("Save rule")
                    .on("click", function () {
                        saveEscalationRuleFromCard(rule.id);
                    })
            )
            .append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("btn btn-danger btn-small")
                    .text("Delete rule")
                    .on("click", function () {
                        deleteEscalationRule(rule.id);
                    })
            )
    );

    editor.append(section);

    return editor;
}

function ruleFieldId(ruleId, field) {
    return "escalation-rule-" + ruleId + "-" + field;
}

function ruleNumberField(ruleId, field, label, value, min) {
    return $("<div>")
        .addClass("app-field")
        .append($("<label>").attr("for", ruleFieldId(ruleId, field)).text(label))
        .append(
            $("<input>")
                .attr("id", ruleFieldId(ruleId, field))
                .attr("type", "number")
                .attr("min", min)
                .addClass("input")
                .val(value)
        );
}

function ruleCheckboxField(ruleId, field, label, checked) {
    return $("<label>")
        .addClass("md-checkbox app-field")
        .append(
            $("<input>")
                .attr("id", ruleFieldId(ruleId, field))
                .attr("type", "checkbox")
                .prop("checked", !!checked)
        )
        .append($("<span>").text(label));
}

function ruleTargetTypeField(rule) {
    return $("<div>")
        .addClass("app-field")
        .append($("<label>").attr("for", ruleFieldId(rule.id, "target-type")).text("Target type"))
        .append(
            $("<select>")
                .attr("id", ruleFieldId(rule.id, "target-type"))
                .addClass("input")
                .append($("<option>").val("rotation").text("Rotation"))
                .append($("<option>").val("user").text("User"))
                .val(rule.target_type || "rotation")
                .on("change", function () {
                    updateEscalationRuleTargetTypeUi(rule.id);
                })
        );
}

function ruleRotationTargetField(rule) {
    const field = $("<div>")
        .addClass("app-field")
        .attr("id", ruleFieldId(rule.id, "rotation-target-group"));
    const select = $("<select>")
        .attr("id", ruleFieldId(rule.id, "target-rotation"))
        .addClass("input");

    escalationRuleTargetRotationsCache.forEach(function (rotation) {
        select.append(
            $("<option>")
                .val(String(rotation.id))
                .text(rotation.name)
        );
    });

    if (!select.children().length) {
        select.append($("<option>").val("").text("No active rotations"));
    }

    if (rule.target_type === "rotation") {
        select.val(String(rule.target_id || ""));
    }

    field.append($("<label>").attr("for", ruleFieldId(rule.id, "target-rotation")).text("Rotation"));
    field.append(select);

    return field;
}

function ruleUserTargetField(rule) {
    const field = $("<div>")
        .addClass("app-field")
        .attr("id", ruleFieldId(rule.id, "user-target-group"));
    const select = $("<select>")
        .attr("id", ruleFieldId(rule.id, "target-user"))
        .addClass("js-user-select")
        .attr("data-placeholder", "Select user...");

    if (!escalationRuleTargetUsersCache.length) {
        select.append(
            $("<option>")
                .val("")
                .text("No active users")
        );
    } else {
        select.append(
            $("<option>")
                .val("")
                .text("")
        );

        escalationRuleTargetUsersCache.forEach(function (member) {
            select.append(
                $("<option>")
                    .val(String(member.user_id))
                    .text(getUserOptionText(member))
            );
        });
    }

    if (rule.target_type === "user") {
        select.val(String(rule.target_id || ""));
    }

    field.append($("<label>").attr("for", ruleFieldId(rule.id, "target-user")).text("User"));
    field.append(select);

    return field;
}

function updateEscalationRuleTargetTypeUi(ruleId) {
    const targetType = $("#" + ruleFieldId(ruleId, "target-type")).val() || "rotation";
    const useUser = targetType === "user";

    $("#" + ruleFieldId(ruleId, "rotation-target-group")).toggleClass("is-hidden", useUser);
    $("#" + ruleFieldId(ruleId, "user-target-group")).toggleClass("is-hidden", !useUser);
    $("#" + ruleFieldId(ruleId, "target-rotation")).prop("disabled", useUser);
    setEnhancedSelectDisabled("#" + ruleFieldId(ruleId, "target-user"), !useUser);
}

function formatRuleTargetSummary(rule) {
    return upperCaseFirst(rule.target_type || "-") + ": " + (
        rule.target_name ||
        getEscalationRuleTargetName(rule.target_type, rule.target_id) ||
        rule.target_id ||
        "-"
    );
}

function getNextEscalationRulePosition() {
    return escalationPolicyRulesCache.reduce(function (maxPosition, rule) {
        return Math.max(maxPosition, Number(rule.position || 0));
    }, 0) + 1;
}

function getDefaultEscalationRuleTarget() {
    if (escalationRuleTargetRotationsCache.length) {
        return {
            target_type: "rotation",
            target_id: Number(escalationRuleTargetRotationsCache[0].id),
        };
    }

    if (escalationRuleTargetUsersCache.length) {
        return {
            target_type: "user",
            target_id: Number(escalationRuleTargetUsersCache[0].user_id),
        };
    }

    return null;
}

function addEscalationRuleCard() {
    if (!selectedEscalationPolicyRulesId) {
        showAppError("Select a policy first.");
        return;
    }

    const rule = createUnsavedEscalationRule();

    if (!rule) {
        showAppError("Add an active rotation or team user before creating rules.");
        return;
    }

    escalationPolicyRulesCache.push(rule);
    expandedEscalationRuleId = rule.id;

    renderEscalationRuleCards();

    scrollToAndHighlight("[data-rule-id='" + rule.id + "']", {
        highlight: "[data-rule-id='" + rule.id + "']",
        block: "nearest",
        container: "#escalation-rules-modal"
    });
}

function collectEscalationRulePayloadFromCard(ruleId) {
    const targetType = $("#" + ruleFieldId(ruleId, "target-type")).val() || "rotation";
    const targetId = targetType === "user"
        ? $("#" + ruleFieldId(ruleId, "target-user")).val()
        : $("#" + ruleFieldId(ruleId, "target-rotation")).val();

    return {
        position: Number($("#" + ruleFieldId(ruleId, "position")).val() || 1),
        delay_seconds: Number($("#" + ruleFieldId(ruleId, "delay-seconds")).val() || 0),
        target_type: targetType,
        target_id: Number(targetId),
        enabled: $("#" + ruleFieldId(ruleId, "enabled")).is(":checked"),
    };
}

function saveEscalationRuleFromCard(ruleId) {
    const payload = collectEscalationRulePayloadFromCard(ruleId);

    if (!payload.target_id) {
        showAppError("Select rule target.");
        return;
    }

    if (isUnsavedEscalationRule(ruleId)) {
        apiPost(
            "/api/escalation-policies/" + selectedEscalationPolicyRulesId + "/rules",
            payload,
            function (rule) {
                expandedEscalationRuleId = rule.id;

                loadEscalationRuleCards(selectedEscalationPolicyRulesId, function () {});
            }
        );

        return;
    }

    apiPut("/api/escalation-policies/rules/" + ruleId, payload, function () {
        expandedEscalationRuleId = ruleId;

        loadEscalationRuleCards(selectedEscalationPolicyRulesId, function () {});
    });
}

function deleteEscalationRule(ruleId) {
    if (isUnsavedEscalationRule(ruleId)) {
        escalationPolicyRulesCache = escalationPolicyRulesCache.filter(function (rule) {
            return !isSameEscalationRuleId(rule.id, ruleId);
        });

        if (isSameEscalationRuleId(expandedEscalationRuleId, ruleId)) {
            expandedEscalationRuleId = null;
        }

        renderEscalationRuleCards();
        return;
    }

    showAppConfirm({
        title: "Delete this rule?",
        message: "Delete escalation rule #" + ruleId + "?",
        confirmText: "Delete rule",
        confirmClass: "btn-danger",
    }).done(function () {
        apiDelete("/api/escalation-policies/rules/" + ruleId, function () {
            if (isSameEscalationRuleId(expandedEscalationRuleId, ruleId)) {
                expandedEscalationRuleId = null;
            }

            loadEscalationRuleCards(selectedEscalationPolicyRulesId);
        });
    });
}

function toggleEscalationRuleEditor(ruleId) {
    expandedEscalationRuleId = isSameEscalationRuleId(expandedEscalationRuleId, ruleId)
        ? null
        : ruleId;

    renderEscalationRuleCards();
}

$(document).on("input", "#escalation-policies-search", applyEscalationPolicyFilters);
$(document).on("change", "#escalation-policies-status-filter", applyEscalationPolicyFilters);
$(document).on("click", "#reload-escalation-policies", refreshEscalationPolicies);
$(document).on("click", "#open-escalation-policy-create-modal", openCreateEscalationPolicyModal);
$(document).on("click", "#save-escalation-policy", saveEscalationPolicy);
$(document).on("click", "#reset-escalation-policy-form", resetEscalationPolicyForm);
$(document).on("click", "#close-escalation-policy-form-modal", function () {
    closeAppModal("#escalation-policy-form-modal");
});

$(document).on("click", "#add-escalation-rule-card", addEscalationRuleCard);
$(document).on("click", "#reload-escalation-rules", function () {
    if (selectedEscalationPolicyRulesId) {
        loadEscalationRuleCards(selectedEscalationPolicyRulesId);
    }
});
$(document).on("click", "#close-escalation-rules-modal, #close-escalation-rules-modal-footer", closeEscalationRulesModal);
