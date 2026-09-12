let orchestrationItems = [];
let orchestrationCurrent = null;
let orchestrationCatalogCache = null;
let orchestrationDefinition = {schema_version: 1, rules: []};
let orchestrationRuleBuffer = null;
let orchestrationRuleIndex = null;
let orchestrationVersions = [];
let orchestrationExecutions = [];
let orchestrationRulesView = "builder";
let orchestrationEditorId = null;
let orchestrationEditorItem = null;

const ORCHESTRATION_CONDITION_OPERATORS = [
    "equals", "not_equals", "contains", "not_contains", "starts_with",
    "ends_with", "regex", "not_regex", "in", "not_in", "exists",
    "not_exists", "greater_than", "less_than", "greater_or_equal",
    "less_or_equal", "is_true", "is_false"
];

const ORCHESTRATION_ACTION_TYPES = [
    "extract_regex", "copy_field", "copy_to_variable", "json_path", "split",
    "set_variable", "static", "lowercase", "uppercase", "trim",
    "set_title", "set_message", "set_description", "set_severity",
    "set_priority", "set_dedup_key", "set_group_key", "set_event_action",
    "set_trace_level", "set_alert_event_history",
    "set_label", "remove_label", "set_custom_field", "remove_custom_field",
    "set_team", "set_route", "set_service", "set_escalation_policy",
    "set_notification_policy", "set_priority_policy", "set_grouping",
    "add_note", "suppress", "pause", "drop", "enqueue_webhook"
];

function orchestrationGroupId() {
    const active = Number($("#active-group-select").val() || 0);
    if (active) {
        return active;
    }
    if (currentUser && currentUser.active_group_id) {
        return Number(currentUser.active_group_id);
    }
    const groups = asArray(currentUser && currentUser.groups);
    return groups.length ? Number(groups[0].id) : null;
}

function orchestrationClone(value) {
    return JSON.parse(JSON.stringify(value === undefined ? null : value));
}

function orchestrationJson(value) {
    return JSON.stringify(value, null, 2);
}

function orchestrationParseJson(value, fallback) {
    try {
        return JSON.parse(value);
    } catch (error) {
        showAppError(error.message, i18n.t("orchestrations.errors.invalid_json"));
        return fallback;
    }
}

function orchestrationIdFromLocation() {
    const params = new URLSearchParams(window.location.search || "");
    const id = Number(params.get("orchestration_id") || 0);
    return Number.isInteger(id) && id > 0 ? id : null;
}

function updateOrchestrationLocation(id, options) {
    if (!window.history || !window.history.pushState) {
        return;
    }

    const settings = $.extend({replace: false}, options || {});
    const url = new URL(window.location.href);

    if (id) {
        url.searchParams.set("orchestration_id", String(id));
    } else {
        url.searchParams.delete("orchestration_id");
    }

    const nextUrl = url.pathname + url.search + url.hash;
    const currentUrl = window.location.pathname + window.location.search + window.location.hash;

    if (nextUrl === currentUrl) {
        return;
    }

    const state = {path: nextUrl, orchestration_id: id || null};
    if (settings.replace) {
        window.history.replaceState(state, "", nextUrl);
    } else {
        window.history.pushState(state, "", nextUrl);
    }
}

function orchestrationOpenModal(id) {
    $("#" + id).css("display", "flex");
}

function orchestrationCloseModal(id) {
    $("#" + id).hide();
}

function orchestrationPermissions() {
    return (orchestrationCurrent && orchestrationCurrent.permissions) ||
        (orchestrationCatalogCache && orchestrationCatalogCache.permissions) || {};
}

function orchestrationCan(permission) {
    return !!orchestrationPermissions()[permission];
}

function orchestrationStatusBadge(mode) {
    const badge = $("<span>").addClass("status-badge").text(
        i18n.t("orchestrations.mode." + mode, {}, mode)
    );
    if (mode === "active") {
        badge.addClass("status-active");
    } else if (mode === "shadow") {
        badge.addClass("status-warning");
    } else {
        badge.addClass("status-muted");
    }
    return badge;
}

function orchestrationScopeLabel(item) {
    if (item.scope === "service") {
        const service = asArray(orchestrationCatalogCache && orchestrationCatalogCache.services)
            .find(function (candidate) { return Number(candidate.id) === Number(item.service_id); });
        return service ? service.name : i18n.t("orchestrations.scope.service");
    }
    return i18n.t("orchestrations.scope.global");
}

function orchestrationFilteredItems() {
    const query = String($("#orchestration-search").val() || "").trim().toLowerCase();
    const mode = $("#orchestration-mode-filter").val();
    const scope = $("#orchestration-scope-filter").val();
    return orchestrationItems.filter(function (item) {
        if (mode && item.mode !== mode) { return false; }
        if (scope && item.scope !== scope) { return false; }
        if (!query) { return true; }
        return [item.name, item.description, item.scope, item.mode, item.compatibility_mode]
            .some(function (value) { return String(value || "").toLowerCase().includes(query); });
    });
}

function renderOrchestrationSummary() {
    $("#orchestration-summary-total").text(orchestrationItems.length);
    $("#orchestration-summary-active").text(orchestrationItems.filter(function (item) { return item.mode === "active"; }).length);
    $("#orchestration-summary-shadow").text(orchestrationItems.filter(function (item) { return item.mode === "shadow"; }).length);
    $("#orchestration-summary-drafts").text(orchestrationItems.filter(function (item) { return !!item.draft; }).length);
}

function orchestrationItemCan(item, permission) {
    return !!(item && item.permissions && item.permissions[permission]);
}

function orchestrationLink(id) {
    const url = new URL(window.location.href);
    url.searchParams.set("orchestration_id", String(id));
    return url.pathname + url.search + url.hash;
}

function renderOrchestrationActions(item) {
    return window.makeActionMenu({
        object: item,
        items: [
            {
                label: i18n.t("orchestrations.actions.open"),
                icon: "fas fa-folder-open",
                onClick: function () { openOrchestration(item.id); }
            },
            {
                label: i18n.t("orchestrations.actions.edit"),
                icon: "fas fa-edit",
                visible: function () { return orchestrationItemCan(item, "edit"); },
                onClick: function () { openOrchestrationEditModal(item); }
            },
            {
                label: i18n.t("orchestrations.actions.delete"),
                icon: "fas fa-trash",
                danger: true,
                visible: function () { return orchestrationItemCan(item, "delete"); },
                onClick: function () { deleteOrchestrationItem(item); }
            }
        ]
    });
}

function renderOrchestrationTable() {
    const tbody = $("#orchestration-table").empty();
    const items = orchestrationFilteredItems();
    $("#orchestration-filtered-count").text(items.length);
    $("#orchestration-total-count").text(orchestrationItems.length);
    if (!items.length) {
        tbody.append($("<tr>").append($("<td>").attr("colspan", 7).addClass("empty-cell").text(i18n.t("orchestrations.empty.none"))));
        return;
    }
    items.forEach(function (item) {
        const nameLink = $("<a>")
            .addClass("link-button item-title")
            .attr("href", orchestrationLink(item.id))
            .text(item.name)
            .on("click", function (event) {
                event.preventDefault();
                openOrchestration(item.id);
            });
        const name = $("<div>").append(
            $("<strong>").append(nameLink),
            $("<div>").addClass("row-subtitle").text(item.description || "")
        );
        const row = $("<tr>").append(
            $("<td>").append(name),
            $("<td>").text(orchestrationScopeLabel(item)),
            $("<td>").append(orchestrationStatusBadge(item.mode)),
            $("<td>").text(item.compatibility_mode),
            $("<td>").text(item.active_version ? "v" + item.active_version.version_number : "—"),
            $("<td>").text(item.updated_at ? formatDateTimeMinutes(item.updated_at) : "—"),
            $("<td>").addClass("actions-td").append(renderOrchestrationActions(item))
        );
        tbody.append(row);
    });
}

function loadOrchestrationCatalog(callback, requestedGroupId) {
    const groupId = Number(requestedGroupId || orchestrationGroupId() || 0);
    if (!groupId) {
        orchestrationCatalogCache = null;
        if (callback) { callback(); }
        return;
    }
    apiGet("/api/event-orchestrations/catalog?group_id=" + groupId, function (catalog) {
        orchestrationCatalogCache = catalog;
        populateOrchestrationCreateServices();
        populateOrchestrationSimulationSources();
        if (callback) { callback(catalog); }
    });
}

function loadOrchestrations() {
    const groupId = orchestrationGroupId();
    if (!groupId) {
        orchestrationItems = [];
        renderOrchestrationSummary();
        renderOrchestrationTable();
        return;
    }
    loadOrchestrationCatalog(function () {
        apiGet("/api/event-orchestrations?group_id=" + groupId, function (response) {
            orchestrationItems = asArray(response && response.items);
            renderOrchestrationSummary();
            renderOrchestrationTable();
            $("#create-orchestration").prop("disabled", !orchestrationCan("create"));

            const linkedId = orchestrationIdFromLocation();
            if (linkedId && (!orchestrationCurrent || Number(orchestrationCurrent.id) !== linkedId)) {
                openOrchestration(linkedId, {updateUrl: false});
            }
        });
    });
}

function populateOrchestrationServiceSelect(selector, selectedId) {
    const select = $(selector).empty();
    asArray(orchestrationCatalogCache && orchestrationCatalogCache.services).forEach(function (item) {
        select.append($("<option>").val(item.id).text(item.name));
    });
    if (selectedId) {
        select.val(String(selectedId));
    }
}

function populateOrchestrationCreateServices() {
    populateOrchestrationServiceSelect("#orchestration-create-service");
    populateOrchestrationServiceSelect(
        "#orchestration-settings-service",
        orchestrationCurrent && orchestrationCurrent.service_id
    );
}

function setOrchestrationEditorScopeVisibility() {
    $("#orchestration-create-service-row").toggleClass(
        "is-hidden",
        $("#orchestration-create-scope").val() !== "service"
    );
}

function setOrchestrationSettingsScopeVisibility() {
    $("#orchestration-settings-service-row").toggleClass(
        "is-hidden",
        $("#orchestration-settings-scope").val() !== "service"
    );
}

function populateOrchestrationSimulationSources() {
    const select = $("#orchestration-simulation-source");
    select.find("option:not([value=normalized])").remove();
    asArray(orchestrationCatalogCache && orchestrationCatalogCache.normalizer_sources).forEach(function (source) {
        select.append($("<option>").val(source).text(source));
    });
}

function configureOrchestrationEditor(item) {
    orchestrationEditorItem = item || null;
    orchestrationEditorId = item ? Number(item.id) : null;
    const editing = !!orchestrationEditorId;
    const canPublish = !editing || orchestrationItemCan(item, "publish");

    $("#orchestration-create-modal-title").text(
        i18n.t(editing ? "orchestrations.edit.title" : "orchestrations.create.title")
    );
    $("#orchestration-create-modal-help").text(
        i18n.t(editing ? "orchestrations.edit.help" : "orchestrations.create.help")
    );
    $("#orchestration-create-submit").text(
        i18n.t(editing ? "orchestrations.actions.save" : "orchestrations.actions.create")
    );

    $("#orchestration-create-name").val(item ? item.name : "");
    $("#orchestration-create-description").val(item ? (item.description || "") : "");
    $("#orchestration-create-scope").val(item ? item.scope : "global");
    populateOrchestrationServiceSelect(
        "#orchestration-create-service",
        item && item.service_id
    );
    $("#orchestration-create-compatibility").val(
        item ? item.compatibility_mode : "legacy"
    );
    $("#orchestration-create-mode").val(item ? item.mode : "disabled");
    $("#orchestration-create-compatibility, #orchestration-create-mode")
        .prop("disabled", editing && !canPublish);
    $("#orchestration-create-mode-row").toggleClass("is-hidden", !editing);
    setOrchestrationEditorScopeVisibility();
}

function openOrchestrationCreateModal() {
    configureOrchestrationEditor(null);
    orchestrationOpenModal("orchestration-create-modal");
}

function openOrchestrationEditModal(item) {
    if (!item) { return; }
    configureOrchestrationEditor(item);
    orchestrationOpenModal("orchestration-create-modal");
}

function finishOrchestrationEditor(item) {
    orchestrationCloseModal("orchestration-create-modal");
    orchestrationEditorId = null;
    orchestrationEditorItem = null;
    loadOrchestrations();
    if (item && orchestrationCurrent && Number(orchestrationCurrent.id) === Number(item.id)) {
        openOrchestration(item.id);
    }
}

function submitOrchestrationCreate() {
    const groupId = orchestrationGroupId();
    const scope = $("#orchestration-create-scope").val();
    const metadata = {
        name: $("#orchestration-create-name").val(),
        description: $("#orchestration-create-description").val() || null,
        scope: scope,
        service_id: scope === "service" ? Number($("#orchestration-create-service").val()) : null
    };

    if (!orchestrationEditorId) {
        apiPost("/api/event-orchestrations", $.extend({
            group_id: groupId,
            compatibility_mode: $("#orchestration-create-compatibility").val()
        }, metadata), function (item) {
            finishOrchestrationEditor(item);
            openOrchestration(item.id);
        });
        return;
    }

    const editingId = orchestrationEditorId;
    const canPublish = orchestrationItemCan(orchestrationEditorItem, "publish");
    apiRequest("PATCH", "/api/event-orchestrations/" + editingId, metadata, function (item) {
        if (!canPublish) {
            finishOrchestrationEditor(item);
            return;
        }
        apiRequest(
            "PATCH",
            "/api/event-orchestrations/" + editingId + "/runtime",
            {
                mode: $("#orchestration-create-mode").val(),
                compatibility_mode: $("#orchestration-create-compatibility").val()
            },
            function (updated) { finishOrchestrationEditor(updated || item); }
        );
    });
}

function deleteOrchestrationItem(item) {
    showAppConfirm({
        title: i18n.t("orchestrations.delete.title"),
        message: i18n.t("orchestrations.delete.message"),
        confirmText: i18n.t("orchestrations.actions.delete")
    }).done(function () {
        apiDelete("/api/event-orchestrations/" + item.id, function () {
            if (orchestrationCurrent && Number(orchestrationCurrent.id) === Number(item.id)) {
                closeOrchestrationWorkspace();
            } else {
                loadOrchestrations();
            }
        });
    });
}

function openOrchestration(id, options) {
    const settings = $.extend({updateUrl: true}, options || {});

    apiGet("/api/event-orchestrations/" + id, function (item) {
        const renderWorkspace = function () {
            orchestrationCurrent = item;
            orchestrationDefinition = orchestrationClone(
                item.draft && item.draft.definition ? item.draft.definition :
                    item.active_definition || {schema_version: 1, rules: []}
            );
            orchestrationDefinition.rules = asArray(orchestrationDefinition.rules);
            $("#orchestration-list-card").addClass("is-hidden");
            $("#orchestration-workspace").removeClass("is-hidden");
            $("#orchestration-workspace-title").text(item.name);
            $("#orchestration-workspace-subtitle").text(orchestrationScopeLabel(item) + " · " + item.compatibility_mode);
            $("#orchestration-draft-status").text(item.draft ? "Draft v" + item.draft.version_number : i18n.t("orchestrations.rules.no_draft"));
            $("#orchestration-settings-name").val(item.name);
            $("#orchestration-settings-description").val(item.description || "");
            $("#orchestration-settings-scope").val(item.scope);
            populateOrchestrationServiceSelect("#orchestration-settings-service", item.service_id);
            setOrchestrationSettingsScopeVisibility();
            $("#orchestration-runtime-mode").val(item.mode);
            $("#orchestration-runtime-compatibility").val(item.compatibility_mode);
            $("#orchestration-definition-json").val(orchestrationJson(orchestrationDefinition));
            $("#orchestration-save-draft, #orchestration-add-rule").prop("disabled", !orchestrationCan("edit"));
            $("#orchestration-publish, #orchestration-save-runtime").prop("disabled", !orchestrationCan("publish"));
            $("#orchestration-delete").prop("disabled", !orchestrationCan("delete"));
            $("#orchestration-add-webhook").prop("disabled", !orchestrationCan("manage_actions"));
            renderOrchestrationRules();
            setOrchestrationRulesView("builder");
            resetOrchestrationSimulationResult();
            switchOrchestrationTab("rules");

            if (settings.updateUrl) {
                updateOrchestrationLocation(item.id);
            }
        };

        const catalogGroupId = Number(
            orchestrationCatalogCache && orchestrationCatalogCache.group
                ? orchestrationCatalogCache.group.id
                : 0
        );

        if (catalogGroupId !== Number(item.group_id)) {
            loadOrchestrationCatalog(renderWorkspace, item.group_id);
        } else {
            renderWorkspace();
        }
    });
}

function closeOrchestrationWorkspace(options) {
    const settings = $.extend({updateUrl: true}, options || {});
    orchestrationCurrent = null;
    setOrchestrationRulesView("builder");
    $("#orchestration-workspace").addClass("is-hidden");
    $("#orchestration-list-card").removeClass("is-hidden");

    if (settings.updateUrl) {
        updateOrchestrationLocation(null, {replace: true});
    }

    loadOrchestrations();
}

function switchOrchestrationTab(tab) {
    $("[data-orchestration-tab]").removeClass("is-active");
    $("[data-orchestration-tab='" + tab + "']").addClass("is-active");
    $("[data-orchestration-panel]").addClass("is-hidden");
    $("[data-orchestration-panel='" + tab + "']").removeClass("is-hidden");
    if (tab === "versions") { loadOrchestrationVersions(); }
    if (tab === "executions") { loadOrchestrationExecutions(); }
    if (tab === "webhooks") { loadOrchestrationWebhooks(); }
}

function setOrchestrationRulesView(view) {
    const jsonView = view === "json";
    orchestrationRulesView = jsonView ? "json" : "builder";

    $("#orchestration-rule-list").toggleClass("is-hidden", jsonView);
    $("#orchestration-json-panel").toggleClass("is-hidden", !jsonView);
    $("#orchestration-add-rule").toggleClass("is-hidden", jsonView);
    $("#orchestration-toggle-json")
        .attr("aria-pressed", jsonView ? "true" : "false")
        .text(i18n.t(
            jsonView
                ? "orchestrations.actions.builder_view"
                : "orchestrations.actions.json_view"
        ));

    if (jsonView) {
        $("#orchestration-definition-json").val(orchestrationJson(orchestrationDefinition));
    }
}

function orchestrationRuleCard(rule, index) {
    const condition = orchestrationConditionSummary(rule.condition_tree || {});
    const actionSummary = asArray(rule.actions).map(function (action) { return action.type; }).join(", ") || i18n.t("orchestrations.rules.no_actions");
    const card = $("<div>").addClass("orchestration-rule-card").attr("data-rule-index", index).attr("draggable", orchestrationCan("edit") ? "true" : "false");
    const header = $("<div>").addClass("orchestration-rule-card-header").append(
        $("<div>").append(
            $("<strong>").text((index + 1) + ". " + (rule.name || "Rule")),
            $("<div>").addClass("row-subtitle").text(rule.description || "")
        ),
        $("<span>").addClass("status-badge " + (rule.enabled === false ? "status-muted" : "status-active")).text(rule.enabled === false ? i18n.t("orchestrations.rule_editor.disabled") : i18n.t("orchestrations.rule_editor.enabled"))
    );
    const body = $("<div>").addClass("orchestration-rule-card-body").append(
        $("<div>").append($("<span>").addClass("orchestration-keyword").text("WHEN"), $("<span>").text(condition)),
        $("<div>").append($("<span>").addClass("orchestration-keyword").text("THEN"), $("<span>").text(actionSummary)),
        $("<div>").append($("<span>").addClass("orchestration-keyword").text("AFTER"), $("<span>").text(rule.processing_mode || "continue"))
    );
    const controls = $("<div>").addClass("orchestration-rule-controls").append(
        $("<button>").addClass("btn btn-compact").attr("data-rule-move", "up").attr("data-rule-index", index).text("↑"),
        $("<button>").addClass("btn btn-compact").attr("data-rule-move", "down").attr("data-rule-index", index).text("↓"),
        $("<button>").addClass("btn btn-compact").attr("data-rule-edit", index).text(i18n.t("orchestrations.actions.edit")),
        $("<button>").addClass("btn btn-compact").attr("data-rule-duplicate", index).text(i18n.t("orchestrations.actions.duplicate")),
        $("<button>").addClass("btn btn-compact btn-danger").attr("data-rule-delete", index).text(i18n.t("orchestrations.actions.delete"))
    );
    if (!orchestrationCan("edit")) { controls.find("button").prop("disabled", true); }
    return card.append(header, body, controls);
}

function renderOrchestrationRules() {
    const target = $("#orchestration-rule-list").empty();
    const rules = asArray(orchestrationDefinition.rules);
    if (!rules.length) {
        target.append($("<div>").addClass("details-empty").text(i18n.t("orchestrations.rules.empty")));
    } else {
        rules.forEach(function (rule, index) { target.append(orchestrationRuleCard(rule, index)); });
    }
    $("#orchestration-definition-json").val(orchestrationJson(orchestrationDefinition));
}

function orchestrationConditionSummary(node) {
    if (!node || !Object.keys(node).length) { return i18n.t("orchestrations.rules.catch_all"); }
    const logical = ["all", "any", "none"].find(function (key) { return Object.prototype.hasOwnProperty.call(node, key); });
    if (logical) {
        return logical.toUpperCase() + " (" + asArray(node[logical]).length + ")";
    }
    return String(node.field || "?") + " " + String(node.operator || "?") + (Object.prototype.hasOwnProperty.call(node, "value") ? " " + JSON.stringify(node.value) : "");
}

function openOrchestrationRuleEditor(index) {
    orchestrationRuleIndex = index === null || index === undefined ? null : Number(index);
    const source = orchestrationRuleIndex === null ? {
        name: "New rule",
        description: "",
        enabled: true,
        condition_tree: {all: []},
        actions: [],
        processing_mode: "continue",
        children: []
    } : orchestrationDefinition.rules[orchestrationRuleIndex];
    orchestrationRuleBuffer = orchestrationClone(source);
    $("#orchestration-rule-index").val(orchestrationRuleIndex === null ? "" : orchestrationRuleIndex);
    $("#orchestration-rule-name").val(orchestrationRuleBuffer.name || "");
    $("#orchestration-rule-description").val(orchestrationRuleBuffer.description || "");
    $("#orchestration-rule-processing-mode").val(orchestrationRuleBuffer.processing_mode || "continue");
    $("#orchestration-rule-enabled").prop("checked", orchestrationRuleBuffer.enabled !== false);
    renderOrchestrationConditionEditor();
    renderOrchestrationActionEditor();
    orchestrationOpenModal("orchestration-rule-modal");
}

function orchestrationNodeAt(path) {
    let node = orchestrationRuleBuffer.condition_tree;
    asArray(path).forEach(function (step) {
        node = node[step.key][step.index];
    });
    return node;
}

function orchestrationPathEncode(path) {
    return btoa(unescape(encodeURIComponent(JSON.stringify(path))));
}

function orchestrationPathDecode(value) {
    return JSON.parse(decodeURIComponent(escape(atob(value))));
}

function orchestrationConditionOperatorLabel(operator) {
    return i18n.t(
        "orchestrations.rule_editor.operator_" + operator,
        {},
        String(operator || "").replace(/_/g, " ")
    );
}

function orchestrationConditionEditorHeader() {
    return $("<div>")
        .addClass("orchestration-condition-editor-header")
        .append(
            orchestrationEditorColumnHeader(
                "orchestrations.rule_editor.condition_field",
                "orchestrations.rule_editor.condition_field_help"
            ),
            orchestrationEditorColumnHeader(
                "orchestrations.rule_editor.condition_operator",
                "orchestrations.rule_editor.condition_operator_help"
            ),
            orchestrationEditorColumnHeader(
                "orchestrations.rule_editor.condition_value",
                "orchestrations.rule_editor.condition_value_help"
            ),
            $("<span>").attr("aria-hidden", "true")
        );
}

function orchestrationConditionLeaf(node, path) {
    const encoded = orchestrationPathEncode(path);
    const fieldHelp = i18n.t("orchestrations.rule_editor.condition_field_help");
    const operatorHelp = i18n.t("orchestrations.rule_editor.condition_operator_help");
    const valueHelp = i18n.t("orchestrations.rule_editor.condition_value_help");
    const removeLabel = i18n.t("orchestrations.rule_editor.remove_condition");
    const row = $("<div>").addClass("orchestration-condition-leaf").attr("data-condition-path", encoded);
    const field = $("<input>")
        .addClass("input orchestration-condition-field")
        .val(node.field || "labels.")
        .attr({
            placeholder: "labels.environment",
            list: "orchestration-field-options",
            title: fieldHelp,
            "aria-label": i18n.t("orchestrations.rule_editor.condition_field")
        });
    const operator = $("<select>")
        .addClass("input orchestration-condition-operator")
        .attr({
            title: operatorHelp,
            "aria-label": i18n.t("orchestrations.rule_editor.condition_operator")
        });
    ORCHESTRATION_CONDITION_OPERATORS.forEach(function (item) {
        operator.append($("<option>").val(item).text(orchestrationConditionOperatorLabel(item)));
    });
    operator.val(node.operator || "equals");
    const value = $("<input>")
        .addClass("input orchestration-condition-value")
        .val(Object.prototype.hasOwnProperty.call(node, "value") ? (typeof node.value === "string" ? node.value : JSON.stringify(node.value)) : "")
        .attr({
            title: valueHelp,
            "aria-label": i18n.t("orchestrations.rule_editor.condition_value")
        });
    const remove = $("<button>")
        .addClass("btn btn-compact btn-danger")
        .attr({
            "data-condition-remove": encoded,
            title: removeLabel,
            "aria-label": removeLabel
        })
        .text("×");
    row.append(field, operator, value, remove);
    return row;
}

function orchestrationConditionGroup(node, path) {
    const logical = ["all", "any", "none"].find(function (key) { return Object.prototype.hasOwnProperty.call(node, key); }) || "all";
    if (!Object.prototype.hasOwnProperty.call(node, logical)) { node[logical] = []; }
    const encoded = orchestrationPathEncode(path);
    const group = $("<div>").addClass("orchestration-condition-group").attr("data-condition-path", encoded);
    const header = $("<div>").addClass("orchestration-condition-group-header");
    const groupModeHelp = i18n.t("orchestrations.rule_editor.condition_group_mode_help");
    const select = $("<select>")
        .addClass("input orchestration-condition-logical")
        .attr({
            title: groupModeHelp,
            "aria-label": i18n.t("orchestrations.rule_editor.condition_group_mode")
        });
    ["all", "any", "none"].forEach(function (item) {
        select.append(
            $("<option>")
                .val(item)
                .text(i18n.t("orchestrations.rule_editor.condition_" + item))
        );
    });
    select.val(logical);
    header.append(select,
        $("<button>").addClass("btn btn-compact").attr("data-condition-add-leaf", encoded).text("+ " + i18n.t("orchestrations.rule_editor.condition")),
        $("<button>").addClass("btn btn-compact").attr("data-condition-add-group", encoded).text("+ " + i18n.t("orchestrations.rule_editor.group"))
    );
    if (path.length) {
        const removeGroupLabel = i18n.t("orchestrations.rule_editor.remove_condition_group");
        header.append(
            $("<button>")
                .addClass("btn btn-compact btn-danger")
                .attr({
                    "data-condition-remove": encoded,
                    title: removeGroupLabel,
                    "aria-label": removeGroupLabel
                })
                .text("×")
        );
    }
    const children = $("<div>").addClass("orchestration-condition-children");
    if (!path.length) {
        children.append(orchestrationConditionEditorHeader());
    }
    asArray(node[logical]).forEach(function (child, index) {
        const childPath = path.concat([{key: logical, index: index}]);
        const childLogical = child && ["all", "any", "none"].some(function (key) { return Object.prototype.hasOwnProperty.call(child, key); });
        children.append(childLogical ? orchestrationConditionGroup(child, childPath) : orchestrationConditionLeaf(child || {}, childPath));
    });
    return group.append(header, children);
}

function renderOrchestrationConditionEditor() {
    const target = $("#orchestration-condition-editor").empty();
    let root = orchestrationRuleBuffer.condition_tree;
    const rootIsGroup = root && ["all", "any", "none"].some(function (key) { return Object.prototype.hasOwnProperty.call(root, key); });
    if (!rootIsGroup) {
        root = {all: root && Object.keys(root).length ? [root] : []};
        orchestrationRuleBuffer.condition_tree = root;
    }
    target.append(orchestrationConditionGroup(root, []));
}

function syncOrchestrationConditionEditor() {
    $("[data-condition-path].orchestration-condition-leaf").each(function () {
        const row = $(this);
        const path = orchestrationPathDecode(row.attr("data-condition-path"));
        const node = orchestrationNodeAt(path);
        if (node) {
            node.field = row.find(".orchestration-condition-field").val();
            node.operator = row.find(".orchestration-condition-operator").val();
            const noValue = ["exists", "not_exists", "is_true", "is_false"].includes(node.operator);
            if (noValue) {
                delete node.value;
            } else {
                const raw = row.find(".orchestration-condition-value").val();
                if (["in", "not_in"].includes(node.operator)) {
                    node.value = orchestrationParseJson(raw, raw.split(",").map(function (item) { return item.trim(); }));
                } else if (["greater_than", "less_than", "greater_or_equal", "less_or_equal"].includes(node.operator) && raw !== "") {
                    node.value = Number(raw);
                } else {
                    node.value = raw;
                }
            }
        }
    });
}

function orchestrationParentForPath(path) {
    if (!path.length) { return null; }
    const parentPath = path.slice(0, -1);
    const step = path[path.length - 1];
    return {node: orchestrationNodeAt(parentPath), step: step};
}

function addOrchestrationCondition(path, group) {
    syncOrchestrationConditionEditor();
    const node = orchestrationNodeAt(path);
    const logical = ["all", "any", "none"].find(function (key) { return Object.prototype.hasOwnProperty.call(node, key); }) || "all";
    node[logical].push(group ? {all: []} : {field: "labels.", operator: "equals", value: ""});
    renderOrchestrationConditionEditor();
}

function removeOrchestrationCondition(path) {
    if (!path.length) { return; }
    syncOrchestrationConditionEditor();
    const parent = orchestrationParentForPath(path);
    parent.node[parent.step.key].splice(parent.step.index, 1);
    renderOrchestrationConditionEditor();
}

function orchestrationActionOptions(select, selected) {
    ORCHESTRATION_ACTION_TYPES
        .filter(function (item) {
            return item !== "set_trace_level" || !orchestrationCurrent || orchestrationCurrent.scope !== "service";
        })
        .forEach(function (item) { select.append($("<option>").val(item).text(item)); });
    select.val(selected || "set_title");
}

function orchestrationCatalogOptions(type) {
    const map = {
        set_team: "teams", set_route: "routes", set_service: "services",
        set_escalation_policy: "escalation_policies",
        set_notification_policy: "notification_policies",
        set_priority_policy: "priority_policies", enqueue_webhook: "webhook_actions"
    };
    return asArray(orchestrationCatalogCache && orchestrationCatalogCache[map[type]]);
}

function orchestrationEditorColumnHeader(labelKey, helpKey) {
    const helpText = i18n.t(helpKey);

    return $("<div>")
        .addClass("orchestration-editor-column-header")
        .append(
            $("<span>").text(i18n.t(labelKey)),
            $("<span>")
                .addClass("orchestration-editor-column-help")
                .attr({
                    title: helpText,
                    "aria-label": helpText,
                    tabindex: 0
                })
                .text("?")
        );
}

function orchestrationActionEditorHeader() {
    return $("<div>")
        .addClass("orchestration-action-editor-header")
        .append(
            orchestrationEditorColumnHeader(
                "orchestrations.rule_editor.action_type",
                "orchestrations.rule_editor.action_type_help"
            ),
            orchestrationEditorColumnHeader(
                "orchestrations.rule_editor.parameters",
                "orchestrations.rule_editor.parameters_help"
            ),
            orchestrationEditorColumnHeader(
                "orchestrations.rule_editor.on_failure",
                "orchestrations.rule_editor.on_failure_help"
            ),
            $("<span>").attr("aria-hidden", "true")
        );
}

function orchestrationActionFailureEditor(action) {
    const helpText = i18n.t("orchestrations.rule_editor.on_failure_help");

    return $("<select>")
        .addClass("input orchestration-action-failure")
        .attr({
            title: helpText,
            "aria-label": i18n.t("orchestrations.rule_editor.on_failure")
        })
        .append(
            $("<option>")
                .val("continue")
                .text(i18n.t("orchestrations.rule_editor.failure_continue")),
            $("<option>")
                .val("stop_rule")
                .text(i18n.t("orchestrations.rule_editor.failure_stop_rule")),
            $("<option>")
                .val("stop_orchestration")
                .text(i18n.t("orchestrations.rule_editor.failure_stop_orchestration"))
        )
        .val(action.on_failure || "continue");
}

function orchestrationActionParamEditor(action, index) {
    const type = action.type || "set_title";
    const container = $("<div>")
        .addClass("orchestration-action-params")
        .attr("aria-label", i18n.t("orchestrations.rule_editor.parameters"));
    const textActions = ["set_title", "set_message", "set_description", "set_severity", "set_priority", "set_dedup_key", "set_group_key", "add_note"];
    const referenceActions = ["set_team", "set_route", "set_service", "set_escalation_policy", "set_notification_policy", "set_priority_policy", "enqueue_webhook"];
    if (type === "extract_regex") {
        container.append(
            $("<input>").addClass("input orchestration-action-source")
                .attr({placeholder: "event.title", list: "orchestration-field-options"})
                .val(action.source || ""),
            $("<input>").addClass("input orchestration-action-pattern")
                .attr("placeholder", "regex pattern")
                .val(action.pattern || ""),
            $("<input>").addClass("input orchestration-action-variable")
                .attr("placeholder", "variable name (optional)")
                .val(action.name || action.target || ""),
            $("<input>").addClass("input orchestration-action-regex-group")
                .attr("placeholder", "group (optional)")
                .val(action.group === undefined || action.group === null ? "" : action.group)
        );
    } else if (["copy_field", "copy_to_variable", "lowercase", "uppercase", "trim"].includes(type)) {
        container.append(
            $("<input>").addClass("input orchestration-action-source")
                .attr({placeholder: "labels.service", list: "orchestration-field-options"})
                .val(action.source || ""),
            $("<input>").addClass("input orchestration-action-variable")
                .attr("placeholder", "variable name")
                .val(action.name || action.target || "")
        );
    } else if (type === "json_path") {
        container.append(
            $("<input>").addClass("input orchestration-action-source")
                .attr({placeholder: "raw", list: "orchestration-field-options"})
                .val(action.source || "raw"),
            $("<input>").addClass("input orchestration-action-json-path")
                .attr("placeholder", "$.payload.service")
                .val(action.path || ""),
            $("<input>").addClass("input orchestration-action-variable")
                .attr("placeholder", "variable name")
                .val(action.name || action.target || "")
        );
    } else if (type === "split") {
        container.append(
            $("<input>").addClass("input orchestration-action-source")
                .attr({placeholder: "labels.instance", list: "orchestration-field-options"})
                .val(action.source || ""),
            $("<input>").addClass("input orchestration-action-delimiter")
                .attr("placeholder", "delimiter")
                .val(action.delimiter || ""),
            $("<input>").addClass("input orchestration-action-split-targets")
                .attr("placeholder", "targets: host,port OR variable name")
                .val(
                    Array.isArray(action.targets)
                        ? action.targets.join(",")
                        : (action.name || action.target || "")
                ),
            $("<input>").addClass("input orchestration-action-split-index")
                .attr({type: "number", min: 0, placeholder: "index (single target)"})
                .val(action.index === undefined || action.index === null ? "" : action.index)
        );
    } else if (["set_variable", "static"].includes(type)) {
        container.append(
            $("<input>").addClass("input orchestration-action-variable")
                .attr("placeholder", "variable name")
                .val(action.name || action.target || ""),
            $("<input>").addClass("input orchestration-action-value")
                .attr("placeholder", "value or {{ template }}")
                .val(
                    action.value === undefined
                        ? ""
                        : (typeof action.value === "string" ? action.value : JSON.stringify(action.value))
                )
        );
    } else if (textActions.includes(type)) {
        container.append($("<input>").addClass("input orchestration-action-value").attr("placeholder", "value or {{ template }}").val(action.template !== undefined ? action.template : (action.value !== undefined ? action.value : "")));
    } else if (type === "set_event_action") {
        container.append($("<select>").addClass("input orchestration-action-value").append($("<option>").val("trigger").text("trigger"), $("<option>").val("resolve").text("resolve")).val(action.value || "trigger"));
    } else if (type === "set_trace_level") {
        container.append(
            $("<select>")
                .addClass("input orchestration-action-trace-level")
                .append(
                    $("<option>").val("full").text("full"),
                    $("<option>").val("compact").text("compact"),
                    $("<option>").val("disabled").text("disabled")
                )
                .val(action.level || "full")
        );
    } else if (type === "set_alert_event_history") {
        container.append(
            $("<select>")
                .addClass("input orchestration-action-event-history")
                .append(
                    $("<option>").val("full").text("full"),
                    $("<option>").val("initial").text("initial"),
                    $("<option>").val("disabled").text("disabled")
                )
                .val(action.level || "full")
        );
    } else if (["set_label", "set_custom_field"].includes(type)) {
        container.append($("<input>").addClass("input orchestration-action-name").attr("placeholder", type === "set_label" ? "label name" : "field name").val(action.name || ""), $("<input>").addClass("input orchestration-action-value").attr("placeholder", "value or {{ template }}").val(action.template !== undefined ? action.template : (action.value !== undefined ? (typeof action.value === "string" ? action.value : JSON.stringify(action.value)) : "")));
    } else if (["remove_label", "remove_custom_field"].includes(type)) {
        container.append($("<input>").addClass("input orchestration-action-name").attr("placeholder", "name").val(action.name || ""));
    } else if (referenceActions.includes(type)) {
        const select = $("<select>").addClass("input orchestration-action-reference");
        orchestrationCatalogOptions(type).forEach(function (item) { select.append($("<option>").val(item.id).text(item.name)); });
        const value = action.action_id || action.team_id || action.route_id || action.service_id || action.escalation_policy_id || action.notification_policy_id || action.priority_policy_id || action.value;
        select.val(value || "");
        container.append(select);
    } else if (type === "set_grouping") {
        container.append(
            $("<input>").addClass("input orchestration-action-group-key").attr("placeholder", "group_key").val(action.group_key || ""),
            $("<input>").addClass("input orchestration-action-dedup-key").attr("placeholder", "dedup_key").val(action.dedup_key || ""),
            $("<input>").addClass("input orchestration-action-window").attr({type: "number", min: 0, max: 86400, placeholder: "window seconds"}).val(action.window_seconds === undefined ? "" : action.window_seconds)
        );
    } else if (["suppress", "drop"].includes(type)) {
        container.append($("<input>").addClass("input orchestration-action-reason").attr("placeholder", "reason").val(action.reason || ""));
    } else if (type === "pause") {
        container.append(
            $("<input>").addClass("input orchestration-action-seconds").attr({type: "number", min: 1, max: 604800, placeholder: "seconds"}).val(action.seconds || 300),
            $("<select>").addClass("input orchestration-action-retrigger").append($("<option>").val("preserve").text("preserve"), $("<option>").val("reset").text("reset")).val(action.retrigger || "preserve"),
            $("<input>").addClass("input orchestration-action-reason").attr("placeholder", "reason").val(action.reason || "")
        );
    }
    return container;
}

function renderOrchestrationActionEditor() {
    const target = $("#orchestration-action-editor").empty();
    const actions = asArray(orchestrationRuleBuffer.actions);
    if (!actions.length) { target.append($("<div>").addClass("details-empty").text(i18n.t("orchestrations.rules.no_actions"))); return; }

    target.append(orchestrationActionEditorHeader());

    actions.forEach(function (action, index) {
        const row = $("<div>").addClass("orchestration-action-row").attr("data-action-index", index);
        const actionTypeHelp = i18n.t("orchestrations.rule_editor.action_type_help");
        const select = $("<select>")
            .addClass("input orchestration-action-type")
            .attr({
                title: actionTypeHelp,
                "aria-label": i18n.t("orchestrations.rule_editor.action_type")
            });
        const removeLabel = i18n.t("orchestrations.rule_editor.remove_action");
        const remove = $("<button>")
            .addClass("btn btn-compact btn-danger")
            .attr({
                "data-action-remove": index,
                title: removeLabel,
                "aria-label": removeLabel
            })
            .text("×");

        orchestrationActionOptions(select, action.type);
        row.append(
            select,
            orchestrationActionParamEditor(action, index),
            orchestrationActionFailureEditor(action),
            remove
        );
        target.append(row);
    });
}

function syncOrchestrationActionEditor() {
    const actions = [];
    $(".orchestration-action-row").each(function () {
        const row = $(this);
        const type = row.find(".orchestration-action-type").val();
        const action = {type: type};
        const value = row.find(".orchestration-action-value").val();
        if (value !== undefined) {
            if (["set_variable", "static"].includes(type)) {
                action.value = value;
            } else if (String(value).includes("{{")) {
                action.template = value;
            } else {
                action.value = value;
            }
        }
        const name = row.find(".orchestration-action-name").val();
        if (name !== undefined) { action.name = name; }
        const variable = row.find(".orchestration-action-variable").val();
        if (variable) { action.name = variable; }
        const source = row.find(".orchestration-action-source").val();
        if (source !== undefined && source !== "") { action.source = source; }
        if (type === "extract_regex") {
            action.pattern = row.find(".orchestration-action-pattern").val() || "";
            const regexGroup = row.find(".orchestration-action-regex-group").val();
            if (regexGroup !== undefined && regexGroup !== "") {
                action.group = /^\d+$/.test(String(regexGroup))
                    ? Number(regexGroup)
                    : regexGroup;
            }
        }
        if (type === "json_path") {
            action.path = row.find(".orchestration-action-json-path").val() || "";
        }
        if (type === "split") {
            action.delimiter = row.find(".orchestration-action-delimiter").val() || "";
            const rawTargets = String(row.find(".orchestration-action-split-targets").val() || "").trim();
            const rawIndex = row.find(".orchestration-action-split-index").val();
            if (rawTargets.includes(",")) {
                action.targets = rawTargets.split(",")
                    .map(function (item) { return item.trim(); })
                    .filter(Boolean);
                delete action.name;
            } else if (rawTargets) {
                action.name = rawTargets;
                action.index = Number(rawIndex || 0);
            }
        }
        const ref = Number(row.find(".orchestration-action-reference").val() || 0);
        const refKeys = {set_team: "team_id", set_route: "route_id", set_service: "service_id", set_escalation_policy: "escalation_policy_id", set_notification_policy: "notification_policy_id", set_priority_policy: "priority_policy_id", enqueue_webhook: "action_id"};
        if (refKeys[type] && ref) { action[refKeys[type]] = ref; }
        if (type === "set_grouping") {
            const groupKey = row.find(".orchestration-action-group-key").val();
            const dedupKey = row.find(".orchestration-action-dedup-key").val();
            const windowValue = row.find(".orchestration-action-window").val();
            if (groupKey) { action.group_key = groupKey; }
            if (dedupKey) { action.dedup_key = dedupKey; }
            if (windowValue !== "") { action.window_seconds = Number(windowValue); }
        }
        const traceLevel = row.find(".orchestration-action-trace-level").val();
        if (type === "set_trace_level" && traceLevel) { action.level = traceLevel; }
        const eventHistory = row.find(".orchestration-action-event-history").val();
        if (type === "set_alert_event_history" && eventHistory) { action.level = eventHistory; }
        const reason = row.find(".orchestration-action-reason").val();
        if (reason) { action.reason = reason; }
        if (type === "pause") {
            action.seconds = Number(row.find(".orchestration-action-seconds").val() || 300);
            action.retrigger = row.find(".orchestration-action-retrigger").val() || "preserve";
        }
        const failure = row.find(".orchestration-action-failure").val();
        if (failure && failure !== "continue") { action.on_failure = failure; }
        actions.push(action);
    });
    orchestrationRuleBuffer.actions = actions;
}

function saveOrchestrationRule() {
    syncOrchestrationConditionEditor();
    syncOrchestrationActionEditor();
    orchestrationRuleBuffer.name = $("#orchestration-rule-name").val() || "Rule";
    orchestrationRuleBuffer.description = $("#orchestration-rule-description").val() || null;
    orchestrationRuleBuffer.processing_mode = $("#orchestration-rule-processing-mode").val();
    orchestrationRuleBuffer.enabled = $("#orchestration-rule-enabled").is(":checked");
    orchestrationRuleBuffer.children = asArray(orchestrationRuleBuffer.children);
    if (orchestrationRuleIndex === null) {
        orchestrationDefinition.rules.push(orchestrationRuleBuffer);
    } else {
        orchestrationDefinition.rules[orchestrationRuleIndex] = orchestrationRuleBuffer;
    }
    orchestrationCloseModal("orchestration-rule-modal");
    renderOrchestrationRules();
}

function saveOrchestrationDraft(callback) {
    if (!orchestrationCurrent) { return; }
    apiRequest("PUT", "/api/event-orchestrations/" + orchestrationCurrent.id + "/draft", {rules: orchestrationDefinition.rules}, function (version) {
        orchestrationCurrent.draft = version;
        orchestrationDefinition = orchestrationClone(version.definition || orchestrationDefinition);
        $("#orchestration-draft-status").text("Draft v" + version.version_number);
        renderOrchestrationRules();
        if (callback) { callback(version); }
    });
}

function validateOrchestrationDraft() {
    saveOrchestrationDraft(function () {
        apiPost("/api/event-orchestrations/" + orchestrationCurrent.id + "/validate", {}, function (result) {
            const box = $("#orchestration-validation-result").removeClass("is-hidden validation-success validation-error");
            box.addClass(result.valid ? "validation-success" : "validation-error");
            const parts = [];
            if (result.valid) { parts.push(i18n.t("orchestrations.validation.valid")); }
            asArray(result.errors).forEach(function (item) { parts.push("ERROR: " + item); });
            asArray(result.warnings).forEach(function (item) { parts.push("WARNING: " + item); });
            box.text(parts.join("\n"));
        });
    });
}

function publishOrchestrationDraft() {
    saveOrchestrationDraft(function () {
        showAppConfirm({title: i18n.t("orchestrations.publish.title"), message: i18n.t("orchestrations.publish.message"), confirmText: i18n.t("orchestrations.actions.publish")}).done(function () {
            apiPost("/api/event-orchestrations/" + orchestrationCurrent.id + "/publish", {confirm_catch_all_drop: true}, function () {
                openOrchestration(orchestrationCurrent.id);
            });
        });
    });
}

function loadOrchestrationVersions() {
    if (!orchestrationCurrent) { return; }
    apiGet("/api/event-orchestrations/" + orchestrationCurrent.id + "/versions", function (response) {
        orchestrationVersions = asArray(response && response.items);
        const tbody = $("#orchestration-version-table").empty();
        orchestrationVersions.forEach(function (version) {
            const actions = $("<div>").addClass("table-actions").append($("<button>").addClass("btn btn-compact").attr("data-version-view", version.id).text(i18n.t("orchestrations.actions.view")));
            if (["published", "archived"].includes(version.status) && orchestrationCan("publish")) { actions.append($("<button>").addClass("btn btn-compact").attr("data-version-rollback", version.id).text(i18n.t("orchestrations.actions.rollback"))); }
            tbody.append($("<tr>").append($("<td>").text("v" + version.version_number), $("<td>").text(version.status), $("<td>").text(version.comment || ""), $("<td>").text((version.definition_hash || "").slice(0, 12)), $("<td>").text(version.published_at ? formatDateTimeMinutes(version.published_at) : "—"), $("<td>").append(actions)));
        });
    });
}

function viewOrchestrationVersion(versionId) {
    apiGet("/api/event-orchestrations/" + orchestrationCurrent.id + "/versions/" + versionId, function (version) {
        $("#orchestration-version-definition").text(orchestrationJson(version.definition));
        const active = orchestrationCurrent.active_definition || {};
        $("#orchestration-version-diff").text(orchestrationSimpleDiff(active, version.definition));
    });
}

function orchestrationSimpleDiff(left, right) {
    const leftLines = orchestrationJson(left).split("\n");
    const rightLines = orchestrationJson(right).split("\n");
    const max = Math.max(leftLines.length, rightLines.length);
    const output = [];
    for (let index = 0; index < max; index += 1) {
        if (leftLines[index] === rightLines[index]) { continue; }
        if (leftLines[index] !== undefined) { output.push("- " + leftLines[index]); }
        if (rightLines[index] !== undefined) { output.push("+ " + rightLines[index]); }
    }
    return output.join("\n") || i18n.t("orchestrations.versions.no_diff");
}

function rollbackOrchestrationVersion(versionId) {
    showAppConfirm({title: i18n.t("orchestrations.rollback.title"), message: i18n.t("orchestrations.rollback.message"), confirmText: i18n.t("orchestrations.actions.rollback")}).done(function () {
        apiPost("/api/event-orchestrations/" + orchestrationCurrent.id + "/rollback", {version_id: Number(versionId), confirm_catch_all_drop: true}, function () { openOrchestration(orchestrationCurrent.id); });
    });
}

function orchestrationSimulationValue(value) {
    if (value === undefined || value === null || value === "") { return "—"; }
    if (typeof value === "string") { return value; }
    if (typeof value === "number" || typeof value === "boolean") { return String(value); }
    return orchestrationJson(value);
}

function orchestrationSimulationCompactValue(value) {
    const text = orchestrationSimulationValue(value).replace(/\s+/g, " ").trim();
    return text.length > 180 ? text.slice(0, 177) + "…" : text;
}

function orchestrationSimulationEntity(value) {
    if (!value) { return "—"; }
    return value.name || value.slug || (value.id ? "#" + value.id : "—");
}

function orchestrationSimulationStatusBadge(text, kind) {
    return $("<span>")
        .addClass("status-badge " + (kind || "status-muted"))
        .text(text || "—");
}

function orchestrationSimulationMetric(label, value, options) {
    const settings = $.extend({badge: false, badgeKind: "status-muted"}, options || {});
    const target = $("<div>").addClass("orchestration-simulation-metric");
    target.append($("<span>").addClass("orchestration-simulation-metric-label").text(label));
    if (settings.badge) {
        target.append(orchestrationSimulationStatusBadge(value, settings.badgeKind));
    } else {
        target.append($("<strong>").text(orchestrationSimulationValue(value)));
    }
    return target;
}

function orchestrationSimulationDispositionKind(disposition) {
    if (disposition === "process") { return "status-active"; }
    if (disposition === "drop") { return "status-danger"; }
    if (disposition === "suppress" || disposition === "pause") { return "status-warning"; }
    return "status-muted";
}

function orchestrationSimulationFlattenRules(rules, depth, output) {
    const target = output || [];
    asArray(rules).forEach(function (rule) {
        target.push({rule: rule, depth: depth || 0});
        orchestrationSimulationFlattenRules(rule.children, (depth || 0) + 1, target);
    });
    return target;
}

function orchestrationSimulationConditionRows(condition, depth, output) {
    const target = output || [];
    if (!condition) { return target; }
    const currentDepth = depth || 0;
    if (condition.field) {
        target.push({condition: condition, depth: currentDepth});
        return target;
    }
    asArray(condition.children).forEach(function (child) {
        orchestrationSimulationConditionRows(child, currentDepth + 1, target);
    });
    return target;
}

function orchestrationSimulationConditionText(condition) {
    const operator = orchestrationConditionOperatorLabel(condition.operator || "");
    const field = condition.field || condition.path || "condition";
    let text = field + " " + operator;
    if (!["exists", "not_exists", "is_true", "is_false"].includes(condition.operator)) {
        text += " " + orchestrationSimulationCompactValue(condition.expected);
    }
    if (condition.found === true) {
        text += " · " + i18n.t("orchestrations.simulator.actual") + ": " + orchestrationSimulationCompactValue(condition.actual);
    } else if (condition.found === false) {
        text += " · " + i18n.t("orchestrations.simulator.field_missing");
    }
    return text;
}

function orchestrationSimulationActionText(action) {
    const type = action.type || "action";
    const before = orchestrationSimulationCompactValue(action.before);
    const after = orchestrationSimulationCompactValue(action.after);
    if (before === after) { return type + " · " + after; }
    return type + ": " + before + " → " + after;
}

function switchOrchestrationSimulationResultTab(tab) {
    const selected = tab || "summary";
    $("[data-simulation-result-tab]")
        .removeClass("is-active")
        .attr("aria-selected", "false");
    $("[data-simulation-result-tab='" + selected + "']")
        .addClass("is-active")
        .attr("aria-selected", "true");
    $("[data-simulation-result-panel]").addClass("is-hidden");
    $("[data-simulation-result-panel='" + selected + "']").removeClass("is-hidden");
}

function resetOrchestrationSimulationResult() {
    $("#orchestration-simulation-empty").removeClass("is-hidden");
    $("#orchestration-simulation-view").addClass("is-hidden");
    $("#orchestration-simulation-overview, #orchestration-simulation-summary, #orchestration-simulation-rules, #orchestration-simulation-changes").empty();
    $("#orchestration-simulation-result").empty();
    switchOrchestrationSimulationResultTab("summary");
}

function renderOrchestrationSimulationOverview(result) {
    const target = $("#orchestration-simulation-overview").empty();
    const execution = result.execution || {};
    const flattened = orchestrationSimulationFlattenRules(execution.rules || [], 0, []);
    const disposition = (result.disposition || {}).type || "process";
    target.append(
        orchestrationSimulationMetric(
            i18n.t("orchestrations.simulator.disposition"),
            disposition,
            {badge: true, badgeKind: orchestrationSimulationDispositionKind(disposition)}
        ),
        orchestrationSimulationMetric(
            i18n.t("orchestrations.simulator.outcome"),
            execution.outcome || (result.executed ? "continue" : i18n.t("orchestrations.simulator.not_executed"))
        ),
        orchestrationSimulationMetric(
            i18n.t("orchestrations.simulator.matched_rules"),
            String(execution.matched_rule_count || 0) + " / " + String(flattened.length)
        ),
        orchestrationSimulationMetric(
            i18n.t("orchestrations.simulator.duration"),
            result.duration_ms === undefined ? "—" : result.duration_ms + " ms"
        )
    );
}

function orchestrationSimulationKeyValue(label, value, options) {
    const settings = $.extend({code: false}, options || {});
    const item = $("<div>").addClass("orchestration-simulation-kv");
    item.append($("<span>").text(label));
    const rendered = $(settings.code ? "<code>" : "<strong>").text(orchestrationSimulationValue(value));
    item.append(rendered);
    return item;
}

function renderOrchestrationSimulationSummary(result) {
    const target = $("#orchestration-simulation-summary").empty();
    if (!result.executed) {
        const errors = asArray(result.errors);
        target.append(
            $("<div>")
                .addClass("orchestration-message validation-error")
                .text(errors.length ? errors.join("\n") : i18n.t("orchestrations.simulator.not_executed"))
        );
        return;
    }

    const context = result.final_context || {};
    const event = context.event || {};
    const runtimeResult = context.result || {};
    const selected = result.selected || {};
    const disposition = result.disposition || {};

    const eventSection = $("<section>").addClass("orchestration-simulation-section").append(
        $("<h3>").text(i18n.t("orchestrations.simulator.effective_event")),
        $("<div>").addClass("orchestration-simulation-kv-grid").append(
            orchestrationSimulationKeyValue(i18n.t("orchestrations.simulator.title"), event.title),
            orchestrationSimulationKeyValue(i18n.t("orchestrations.simulator.severity"), event.severity),
            orchestrationSimulationKeyValue(i18n.t("orchestrations.simulator.priority"), event.priority),
            orchestrationSimulationKeyValue(i18n.t("orchestrations.simulator.dedup_key"), event.dedup_key, {code: true}),
            orchestrationSimulationKeyValue(i18n.t("orchestrations.simulator.group_key"), event.group_key, {code: true}),
            orchestrationSimulationKeyValue(i18n.t("orchestrations.simulator.trace_level"), runtimeResult.trace_level),
            orchestrationSimulationKeyValue(i18n.t("orchestrations.simulator.alert_event_history"), runtimeResult.alert_event_history)
        )
    );

    const selectionSection = $("<section>").addClass("orchestration-simulation-section").append(
        $("<h3>").text(i18n.t("orchestrations.simulator.selected_targets")),
        $("<div>").addClass("orchestration-simulation-kv-grid").append(
            orchestrationSimulationKeyValue(i18n.t("orchestrations.simulator.route"), orchestrationSimulationEntity(selected.route)),
            orchestrationSimulationKeyValue(i18n.t("orchestrations.simulator.team"), orchestrationSimulationEntity(selected.team)),
            orchestrationSimulationKeyValue(i18n.t("orchestrations.simulator.service"), orchestrationSimulationEntity(selected.service)),
            orchestrationSimulationKeyValue(i18n.t("orchestrations.simulator.escalation_policy"), orchestrationSimulationEntity(selected.escalation_policy)),
            orchestrationSimulationKeyValue(i18n.t("orchestrations.simulator.notification_policy"), orchestrationSimulationEntity(selected.notification_policy)),
            orchestrationSimulationKeyValue(i18n.t("orchestrations.simulator.priority_policy"), orchestrationSimulationEntity(selected.priority_policy))
        )
    );

    const executionSection = $("<section>").addClass("orchestration-simulation-section").append(
        $("<h3>").text(i18n.t("orchestrations.simulator.execution_details")),
        $("<div>").addClass("orchestration-simulation-kv-grid").append(
            orchestrationSimulationKeyValue(i18n.t("orchestrations.simulator.version"), "v" + (result.version_number || result.version_id || "—")),
            orchestrationSimulationKeyValue(i18n.t("orchestrations.simulator.normalizer"), result.selected_normalizer),
            orchestrationSimulationKeyValue(i18n.t("orchestrations.simulator.normalized_events"), result.normalized_event_count),
            orchestrationSimulationKeyValue(i18n.t("orchestrations.simulator.reason"), disposition.reason),
            orchestrationSimulationKeyValue(i18n.t("orchestrations.simulator.pause_seconds"), disposition.pause_seconds),
            orchestrationSimulationKeyValue(i18n.t("orchestrations.simulator.grouping"), selected.grouping, {code: true})
        )
    );

    target.append(eventSection, selectionSection, executionSection);

    const errors = asArray(result.errors);
    if (errors.length) {
        target.append(
            $("<section>").addClass("orchestration-simulation-section").append(
                $("<h3>").text(i18n.t("orchestrations.simulator.errors")),
                $("<div>").addClass("orchestration-message validation-error").text(errors.join("\n"))
            )
        );
    }
}

function renderOrchestrationSimulationRules(result) {
    const target = $("#orchestration-simulation-rules").empty();
    const execution = result.execution || {};
    const flattened = orchestrationSimulationFlattenRules(execution.rules || [], 0, []);
    if (!flattened.length) {
        target.append($("<div>").addClass("empty-cell").text(i18n.t("orchestrations.simulator.no_rules")));
        return;
    }

    flattened.forEach(function (entry) {
        const rule = entry.rule || {};
        let stateText = i18n.t("orchestrations.simulator.skipped");
        let stateKind = "status-muted";
        if (rule.enabled === false) {
            stateText = i18n.t("orchestrations.simulator.disabled_rule");
        } else if (rule.matched) {
            stateText = i18n.t("orchestrations.simulator.matched");
            stateKind = "status-active";
        } else {
            stateText = i18n.t("orchestrations.simulator.not_matched");
            stateKind = "status-warning";
        }

        const card = $("<article>")
            .addClass("orchestration-simulation-rule")
            .css("--orchestration-rule-depth", Math.min(Number(entry.depth || 0), 8));
        const header = $("<div>").addClass("orchestration-simulation-rule-header").append(
            $("<div>").append(
                $("<strong>").text(rule.name || rule.path || i18n.t("orchestrations.simulator.rule")),
                $("<div>").addClass("row-subtitle").text((rule.path || "") + (rule.reason ? " · " + rule.reason : ""))
            ),
            orchestrationSimulationStatusBadge(stateText, stateKind)
        );
        card.append(header);

        const conditionRows = orchestrationSimulationConditionRows(rule.condition, 0, []);
        if (conditionRows.length) {
            const conditions = $("<div>").addClass("orchestration-simulation-rule-details").append(
                $("<div>").addClass("orchestration-simulation-detail-label").text(i18n.t("orchestrations.simulator.conditions"))
            );
            conditionRows.forEach(function (conditionEntry) {
                const condition = conditionEntry.condition || {};
                conditions.append(
                    $("<div>")
                        .addClass("orchestration-simulation-step " + (condition.matched ? "is-success" : "is-failed"))
                        .css("--orchestration-condition-depth", Math.min(Number(conditionEntry.depth || 0), 8))
                        .append(
                            $("<span>").addClass("orchestration-simulation-step-icon").attr("aria-hidden", "true").text(condition.matched ? "✓" : "×"),
                            $("<span>").text(orchestrationSimulationConditionText(condition))
                        )
                );
            });
            card.append(conditions);
        }

        const actions = asArray(rule.actions);
        if (actions.length) {
            const actionList = $("<div>").addClass("orchestration-simulation-rule-details").append(
                $("<div>").addClass("orchestration-simulation-detail-label").text(i18n.t("orchestrations.simulator.actions"))
            );
            actions.forEach(function (action) {
                actionList.append(
                    $("<div>")
                        .addClass("orchestration-simulation-step " + (action.success ? "is-success" : "is-failed"))
                        .append(
                            $("<span>").addClass("orchestration-simulation-step-icon").attr("aria-hidden", "true").text(action.success ? "✓" : "×"),
                            $("<span>").text(orchestrationSimulationActionText(action))
                        )
                );
            });
            card.append(actionList);
        }
        target.append(card);
    });
}

function orchestrationSimulationDiffTable(diff) {
    const changes = asArray(diff && diff.changes);
    if (!changes.length) {
        return $("<div>").addClass("orchestration-simulation-no-changes").text(i18n.t("orchestrations.simulator.no_changes"));
    }
    const table = $("<table>").addClass("data-table orchestration-simulation-diff-table");
    table.append(
        $("<thead>").append(
            $("<tr>").append(
                $("<th>").text(i18n.t("orchestrations.simulator.path")),
                $("<th>").text(i18n.t("orchestrations.simulator.before")),
                $("<th>").text(i18n.t("orchestrations.simulator.after"))
            )
        )
    );
    const body = $("<tbody>");
    changes.forEach(function (change) {
        body.append(
            $("<tr>").append(
                $("<td>").append($("<code>").text(change.path || "$")),
                $("<td>").append($("<code>").text(orchestrationSimulationCompactValue(change.before))),
                $("<td>").append($("<code>").text(orchestrationSimulationCompactValue(change.after)))
            )
        );
    });
    table.append(body);
    const wrapper = $("<div>").addClass("table-wrapper").append(table);
    if (diff && diff.truncated) {
        wrapper.append(
            $("<div>").addClass("card-subtitle orchestration-simulation-truncated").text(
                i18n.t("orchestrations.simulator.diff_truncated", {count: diff.total_changes})
            )
        );
    }
    return wrapper;
}

function renderOrchestrationSimulationChanges(result) {
    const target = $("#orchestration-simulation-changes").empty();
    target.append(
        $("<section>").addClass("orchestration-simulation-section").append(
            $("<h3>").text(i18n.t("orchestrations.simulator.input_output_changes")),
            orchestrationSimulationDiffTable(result.input_output_diff || {})
        )
    );

    if (result.active_draft_diff) {
        target.append(
            $("<section>").addClass("orchestration-simulation-section").append(
                $("<h3>").text(i18n.t("orchestrations.simulator.active_draft_changes")),
                orchestrationSimulationDiffTable(result.active_draft_diff)
            )
        );
    }
}

function renderOrchestrationSimulationResult(result) {
    $("#orchestration-simulation-empty").addClass("is-hidden");
    $("#orchestration-simulation-view").removeClass("is-hidden");
    renderOrchestrationSimulationOverview(result || {});
    renderOrchestrationSimulationSummary(result || {});
    renderOrchestrationSimulationRules(result || {});
    renderOrchestrationSimulationChanges(result || {});
    $("#orchestration-simulation-result").text(orchestrationJson(result || {}));
    switchOrchestrationSimulationResultTab("summary");
}

function runOrchestrationSimulation() {
    const source = $("#orchestration-simulation-source").val();
    const parsed = orchestrationParseJson($("#orchestration-simulation-payload").val(), null);
    if (parsed === null) { return; }
    const payload = {compare_with_active: $("#orchestration-compare-active").is(":checked")};
    if (source === "normalized") { payload.normalized_event = parsed; } else { payload.source = source; payload.payload = parsed; }
    apiPost("/api/event-orchestrations/" + orchestrationCurrent.id + "/simulate", payload, function (result) {
        renderOrchestrationSimulationResult(result);
    });
}

function loadOrchestrationExecutions() {
    if (!orchestrationCurrent || !orchestrationCan("view_executions")) { return; }
    apiGet("/api/event-orchestrations/" + orchestrationCurrent.id + "/executions?limit=100&include_trace=1", function (response) {
        orchestrationExecutions = asArray(response && response.items ? response.items : response);
        const tbody = $("#orchestration-execution-table").empty();
        orchestrationExecutions.forEach(function (row) {
            tbody.append($("<tr>").append($("<td>").text(row.id), $("<td>").text(row.source || "—"), $("<td>").text(row.disposition || "process"), $("<td>").text(row.matched_rule_count || 0), $("<td>").text(row.duration_ms === null ? "—" : row.duration_ms + " ms"), $("<td>").text(formatDateTimeMinutes(row.created_at)), $("<td>").append($("<button>").addClass("btn btn-compact").attr("data-execution-view", row.id).text(i18n.t("orchestrations.actions.trace")))));
        });
    });
    apiGet("/api/event-orchestrations/" + orchestrationCurrent.id + "/shadow-metrics", function (metrics) {
        const target = $("#orchestration-shadow-metrics").empty();
        const values = (metrics && metrics.metrics) || {};
        Object.keys(values).forEach(function (key) {
            if (typeof values[key] === "number") {
                target.append($("<div>").addClass("orchestration-metric").append($("<span>").text(key), $("<strong>").text(values[key])));
            }
        });
    });
}

function viewOrchestrationExecution(id) {
    const row = orchestrationExecutions.find(function (item) { return Number(item.id) === Number(id); });
    $("#orchestration-execution-trace").text(orchestrationJson(row && (row.trace || row.trace_json || row)));
}

function loadOrchestrationWebhooks() {
    const groupId = orchestrationGroupId();
    apiGet("/api/orchestration-webhook-actions?group_id=" + groupId, function (response) {
        if (orchestrationCatalogCache) { orchestrationCatalogCache.webhook_actions = asArray(response.items); }
        const tbody = $("#orchestration-webhook-table").empty();
        asArray(response.items).forEach(function (action) {
            const actions = $("<div>").addClass("table-actions");
            if (orchestrationCan("manage_actions")) {
                actions.append(
                    $("<button>").addClass("btn btn-compact").attr("data-webhook-edit", action.id).text(i18n.t("orchestrations.actions.edit")),
                    $("<button>").addClass("btn btn-compact btn-danger").attr("data-webhook-delete", action.id).text(i18n.t("orchestrations.actions.delete"))
                );
            }
            tbody.append($("<tr>").append($("<td>").text(action.name), $("<td>").text(action.url), $("<td>").text(action.method), $("<td>").text(action.retry_count), $("<td>").text(action.enabled ? i18n.t("orchestrations.rule_editor.enabled") : i18n.t("orchestrations.rule_editor.disabled")), $("<td>").append(actions)));
        });
    });
}

function openOrchestrationWebhookEditor(id) {
    const action = asArray(orchestrationCatalogCache && orchestrationCatalogCache.webhook_actions).find(function (item) { return Number(item.id) === Number(id); }) || {};
    $("#orchestration-webhook-id").val(action.id || "");
    $("#orchestration-webhook-name").val(action.name || "");
    $("#orchestration-webhook-description").val(action.description || "");
    $("#orchestration-webhook-url").val(action.url || "");
    $("#orchestration-webhook-method").val(action.method || "POST");
    $("#orchestration-webhook-headers").val("{}");
    $("#orchestration-webhook-body").val(action.body_template || "");
    $("#orchestration-webhook-timeout").val(action.timeout_seconds || 10);
    $("#orchestration-webhook-retries").val(action.retry_count === undefined ? 2 : action.retry_count);
    $("#orchestration-webhook-private-policy").val(action.private_network_policy || "deny");
    $("#orchestration-webhook-enabled").prop("checked", action.enabled !== false);
    orchestrationOpenModal("orchestration-webhook-modal");
}

function saveOrchestrationWebhook() {
    const id = Number($("#orchestration-webhook-id").val() || 0);
    const headers = orchestrationParseJson($("#orchestration-webhook-headers").val() || "{}", null);
    if (headers === null) { return; }
    const payload = {
        name: $("#orchestration-webhook-name").val(), description: $("#orchestration-webhook-description").val() || null,
        url: $("#orchestration-webhook-url").val(), method: $("#orchestration-webhook-method").val(),
        body_template: $("#orchestration-webhook-body").val() || null,
        timeout_seconds: Number($("#orchestration-webhook-timeout").val()), retry_count: Number($("#orchestration-webhook-retries").val()),
        private_network_policy: $("#orchestration-webhook-private-policy").val(),
        enabled: $("#orchestration-webhook-enabled").is(":checked")
    };
    if (!id || Object.keys(headers).length) { payload.headers = headers; }
    const method = id ? "PATCH" : "POST";
    if (!id) { payload.group_id = orchestrationGroupId(); }
    apiRequest(method, "/api/orchestration-webhook-actions" + (id ? "/" + id : ""), payload, function () {
        orchestrationCloseModal("orchestration-webhook-modal");
        loadOrchestrationCatalog(function () { loadOrchestrationWebhooks(); renderOrchestrationActionEditor(); });
    });
}

function deleteOrchestrationWebhook(id) {
    showAppConfirm({title: i18n.t("orchestrations.webhooks.delete_title"), message: i18n.t("orchestrations.webhooks.delete_message"), confirmText: i18n.t("orchestrations.actions.delete")}).done(function () {
        apiDelete("/api/orchestration-webhook-actions/" + id, function () { loadOrchestrationCatalog(loadOrchestrationWebhooks); });
    });
}

function saveOrchestrationSettings() {
    const scope = $("#orchestration-settings-scope").val();
    apiRequest(
        "PATCH",
        "/api/event-orchestrations/" + orchestrationCurrent.id,
        {
            name: $("#orchestration-settings-name").val(),
            description: $("#orchestration-settings-description").val() || null,
            scope: scope,
            service_id: scope === "service"
                ? Number($("#orchestration-settings-service").val())
                : null
        },
        function () { openOrchestration(orchestrationCurrent.id); }
    );
}

function saveOrchestrationRuntime() {
    apiRequest("PATCH", "/api/event-orchestrations/" + orchestrationCurrent.id + "/runtime", {mode: $("#orchestration-runtime-mode").val(), compatibility_mode: $("#orchestration-runtime-compatibility").val()}, function () { openOrchestration(orchestrationCurrent.id); });
}

function deleteCurrentOrchestration() {
    showAppConfirm({title: i18n.t("orchestrations.delete.title"), message: i18n.t("orchestrations.delete.message"), confirmText: i18n.t("orchestrations.actions.delete")}).done(function () {
        apiDelete("/api/event-orchestrations/" + orchestrationCurrent.id, closeOrchestrationWorkspace);
    });
}

$(document).on("click", "#reload-orchestrations", loadOrchestrations);
$(document).on("input change", "#orchestration-search, #orchestration-mode-filter, #orchestration-scope-filter", renderOrchestrationTable);
$(document).on("click", "#create-orchestration", openOrchestrationCreateModal);
$(document).on("change", "#orchestration-create-scope", setOrchestrationEditorScopeVisibility);
$(document).on("change", "#orchestration-settings-scope", setOrchestrationSettingsScopeVisibility);
$(document).on("click", "#orchestration-create-submit", submitOrchestrationCreate);
$(document).on("click", "[data-close-modal]", function () { orchestrationCloseModal($(this).attr("data-close-modal")); });
$(document).on("click", "[data-open-orchestration]", function () { openOrchestration($(this).attr("data-open-orchestration")); });
$(document).on("click", "#orchestration-back", closeOrchestrationWorkspace);
$(document).on("click", "[data-orchestration-tab]", function () { switchOrchestrationTab($(this).attr("data-orchestration-tab")); });
$(document).on("click", "[data-simulation-result-tab]", function () { switchOrchestrationSimulationResultTab($(this).attr("data-simulation-result-tab")); });
$(document).on("click", "#orchestration-add-rule", function () { openOrchestrationRuleEditor(null); });
$(document).on("click", "[data-rule-edit]", function () { openOrchestrationRuleEditor($(this).attr("data-rule-edit")); });
$(document).on("click", "[data-rule-delete]", function () { orchestrationDefinition.rules.splice(Number($(this).attr("data-rule-delete")), 1); renderOrchestrationRules(); });
$(document).on("click", "[data-rule-duplicate]", function () { const index = Number($(this).attr("data-rule-duplicate")); const copy = orchestrationClone(orchestrationDefinition.rules[index]); copy.name = (copy.name || "Rule") + " copy"; orchestrationDefinition.rules.splice(index + 1, 0, copy); renderOrchestrationRules(); });
$(document).on("click", "[data-rule-move]", function () { const index = Number($(this).attr("data-rule-index")); const target = $(this).attr("data-rule-move") === "up" ? index - 1 : index + 1; if (target < 0 || target >= orchestrationDefinition.rules.length) { return; } const item = orchestrationDefinition.rules.splice(index, 1)[0]; orchestrationDefinition.rules.splice(target, 0, item); renderOrchestrationRules(); });
$(document).on("click", "#orchestration-rule-save", saveOrchestrationRule);
$(document).on("click", "#orchestration-condition-add", function () { addOrchestrationCondition([], false); });
$(document).on("click", "#orchestration-condition-group-add", function () { addOrchestrationCondition([], true); });
$(document).on("click", "[data-condition-add-leaf]", function () { addOrchestrationCondition(orchestrationPathDecode($(this).attr("data-condition-add-leaf")), false); });
$(document).on("click", "[data-condition-add-group]", function () { addOrchestrationCondition(orchestrationPathDecode($(this).attr("data-condition-add-group")), true); });
$(document).on("click", "[data-condition-remove]", function () { removeOrchestrationCondition(orchestrationPathDecode($(this).attr("data-condition-remove"))); });
$(document).on("change", ".orchestration-condition-logical", function () {
    syncOrchestrationConditionEditor();
    const row = $(this).closest("[data-condition-path]");
    const node = orchestrationNodeAt(orchestrationPathDecode(row.attr("data-condition-path")));
    const oldKey = ["all", "any", "none"].find(function (key) {
        return node && Object.prototype.hasOwnProperty.call(node, key);
    }) || "all";
    const newKey = $(this).val();
    if (node && oldKey !== newKey) {
        const children = node[oldKey] || [];
        Object.keys(node).forEach(function (key) { delete node[key]; });
        node[newKey] = children;
    }
    renderOrchestrationConditionEditor();
});
$(document).on("dragstart", ".orchestration-rule-card", function (event) {
    if (!orchestrationCan("edit")) { event.preventDefault(); return; }
    event.originalEvent.dataTransfer.effectAllowed = "move";
    event.originalEvent.dataTransfer.setData("text/plain", String($(this).attr("data-rule-index")));
});
$(document).on("dragover", ".orchestration-rule-card", function (event) {
    if (!orchestrationCan("edit")) { return; }
    event.preventDefault();
    event.originalEvent.dataTransfer.dropEffect = "move";
    $(this).addClass("is-drag-over");
});
$(document).on("dragleave dragend", ".orchestration-rule-card", function () { $(this).removeClass("is-drag-over"); });
$(document).on("drop", ".orchestration-rule-card", function (event) {
    if (!orchestrationCan("edit")) { return; }
    event.preventDefault();
    $(".orchestration-rule-card").removeClass("is-drag-over");
    const source = Number(event.originalEvent.dataTransfer.getData("text/plain"));
    const target = Number($(this).attr("data-rule-index"));
    if (!Number.isInteger(source) || source === target || source < 0 || target < 0) { return; }
    const item = orchestrationDefinition.rules.splice(source, 1)[0];
    orchestrationDefinition.rules.splice(target, 0, item);
    renderOrchestrationRules();
});
$(document).on("click", "#orchestration-action-add", function () { orchestrationRuleBuffer.actions.push({type: "set_title", value: ""}); renderOrchestrationActionEditor(); });
$(document).on("change", ".orchestration-action-type", function () { syncOrchestrationActionEditor(); renderOrchestrationActionEditor(); });
$(document).on("click", "[data-action-remove]", function () { syncOrchestrationActionEditor(); orchestrationRuleBuffer.actions.splice(Number($(this).attr("data-action-remove")), 1); renderOrchestrationActionEditor(); });
$(document).on("click", "#orchestration-save-draft", function () { saveOrchestrationDraft(); });
$(document).on("click", "#orchestration-validate", validateOrchestrationDraft);
$(document).on("click", "#orchestration-publish", publishOrchestrationDraft);
$(document).on("click", "#orchestration-toggle-json", function () {
    setOrchestrationRulesView(orchestrationRulesView === "json" ? "builder" : "json");
});
$(document).on("click", "#orchestration-back-to-builder", function () {
    setOrchestrationRulesView("builder");
});
$(document).on("click", "#orchestration-format-json", function () {
    formatJsonTextarea(
        "#orchestration-definition-json",
        {schema_version: 1, rules: []},
        i18n.t("orchestrations.rules.definition_json")
    );
});
$(document).on("click", "#orchestration-apply-json", function () {
    const parsed = orchestrationParseJson($("#orchestration-definition-json").val(), null);
    if (parsed && Array.isArray(parsed.rules)) {
        orchestrationDefinition = parsed;
        renderOrchestrationRules();
        setOrchestrationRulesView("builder");
    } else if (parsed) {
        showAppError(i18n.t("orchestrations.errors.rules_required"));
    }
});
$(document).on("click", "#orchestration-run-simulation", runOrchestrationSimulation);
$(document).on("click", "#reload-orchestration-versions", loadOrchestrationVersions);
$(document).on("click", "[data-version-view]", function () { viewOrchestrationVersion($(this).attr("data-version-view")); });
$(document).on("click", "[data-version-rollback]", function () { rollbackOrchestrationVersion($(this).attr("data-version-rollback")); });
$(document).on("click", "#reload-orchestration-executions", loadOrchestrationExecutions);
$(document).on("click", "[data-execution-view]", function () { viewOrchestrationExecution($(this).attr("data-execution-view")); });
$(document).on("click", "#orchestration-add-webhook", function () { openOrchestrationWebhookEditor(null); });
$(document).on("click", "[data-webhook-edit]", function () { openOrchestrationWebhookEditor($(this).attr("data-webhook-edit")); });
$(document).on("click", "[data-webhook-delete]", function () { deleteOrchestrationWebhook($(this).attr("data-webhook-delete")); });
$(document).on("click", "#orchestration-webhook-format-headers", function () {
    formatJsonTextarea(
        "#orchestration-webhook-headers",
        {},
        i18n.t("orchestrations.webhooks.headers")
    );
});
$(document).on("click", "#orchestration-webhook-save", saveOrchestrationWebhook);
$(document).on("click", "#orchestration-save-settings", saveOrchestrationSettings);
$(document).on("click", "#orchestration-save-runtime", saveOrchestrationRuntime);
$(document).on("click", "#orchestration-delete", deleteCurrentOrchestration);

$(window).on("popstate", function () {
    const linkedId = orchestrationIdFromLocation();

    if (linkedId) {
        if (!orchestrationCurrent || Number(orchestrationCurrent.id) !== linkedId) {
            openOrchestration(linkedId, {updateUrl: false});
        }
        return;
    }

    if (orchestrationCurrent) {
        closeOrchestrationWorkspace({updateUrl: false});
    }
});
