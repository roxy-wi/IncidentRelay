let matcherPresetsCache = [];
let selectedMatcherPresetDetailsId = null;

function initializeMatcherPresetEditor() {
    enhanceMatcherEditor("#matcher-preset-matchers", {
        label: i18n.t("matcher_presets.form.matchers_json"),
        header: i18n.t("matcher_presets.form.matchers"),
        context: function () {
            return {scope: "matcher_preset", teamId: Number($("#matcher-preset-team").val()) || null, presetId: Number($("#matcher-preset-id").val()) || null};
        },
    });
}

function loadMatcherPresets() {
    initializeMatcherPresetEditor();
    fillTeamSelect("#matcher-preset-team", false, function () { resetMatcherPresetForm(); });
    refreshMatcherPresets();
    updateMatcherPresetCreateButtonState();
}

function buildMatcherPresetsApiUrl() {
    return "/api/matcher-presets" + selectedTeamQuery();
}

function updateMatcherPresetCreateButtonState() {
    const allowed = currentUserCanCreateUiObjects();

    $("#open-matcher-preset-create-modal")
        .toggleClass("is-hidden", !allowed)
        .prop("disabled", !allowed);
}

function refreshMatcherPresets() {
    apiGet(buildMatcherPresetsApiUrl(), function (presets) {
        matcherPresetsCache = asArray(presets);
        renderMatcherPresetsSummary();
        renderMatcherPresetsTable();
        restoreMatcherPresetDetails();
        updateMatcherPresetCreateButtonState();
    });
}

function renderMatcherPresetsSummary() {
    const enabled = matcherPresetsCache.filter(function (preset) { return !!preset.enabled; }).length;
    const used = matcherPresetsCache.filter(function (preset) { return Number(preset.usage_count || 0) > 0; }).length;
    const usages = matcherPresetsCache.reduce(function (total, preset) { return total + Number(preset.usage_count || 0); }, 0);

    $("#matcher-presets-summary-total").text(matcherPresetsCache.length);
    $("#matcher-presets-summary-enabled").text(enabled);
    $("#matcher-presets-summary-used").text(used);
    $("#matcher-presets-summary-usages").text(usages);
}

function getMatcherPresetSearchText(preset) {
    return [
        preset.id,
        preset.name,
        preset.description,
        preset.team_name,
        preset.team_slug,
        preset.version,
        JSON.stringify(preset.matchers || {}),
        preset.enabled ? "enabled" : "disabled",
    ].join(" ").toLowerCase();
}

function getFilteredMatcherPresets() {
    const query = String($("#matcher-presets-search").val() || "").trim().toLowerCase();
    const status = String($("#matcher-presets-status-filter").val() || "");

    return matcherPresetsCache.filter(function (preset) {
        const usageCount = Number(preset.usage_count || 0);

        if (status === "enabled" && !preset.enabled) {
            return false;
        }

        if (status === "disabled" && preset.enabled) {
            return false;
        }

        if (status === "used" && usageCount === 0) {
            return false;
        }

        if (status === "unused" && usageCount > 0) {
            return false;
        }

        return !query || getMatcherPresetSearchText(preset).indexOf(query) !== -1;
    });
}

function renderMatcherPresetsTable() {
    const presets = getFilteredMatcherPresets();
    const tbody = $("#matcher-presets-table");

    tbody.empty();
    $("#matcher-presets-filtered-count").text(presets.length);
    $("#matcher-presets-total-count").text(matcherPresetsCache.length);

    if (!presets.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>").attr("colspan", "6").addClass("empty-cell").text(i18n.t("matcher_presets.empty.found"))
            )
        );
        return;
    }

    presets.forEach(function (preset) { tbody.append(renderMatcherPresetRow(preset)); });
}

function renderMatcherPresetRow(preset) {
    const row = $("<tr>").toggleClass("row-disabled", !preset.enabled);

    row.append(
        $("<td>")
            .append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("name-button")
                    .text(preset.name || "-")
                    .on("click", function () { loadMatcherPresetDetails(preset.id, {scroll: true}); })
            )
            .append(
                $("<div>").addClass("row-subtitle").text(preset.description || i18n.t("matcher_presets.row.fallback", {id: preset.id}))
            )
    );

    row.append(
        $("<td>").append(
            $("<span>").addClass("pill").text(preset.team_slug || preset.team_name || "-")
        )
    );

    row.append($("<td>").text("v" + Number(preset.version || 1)));
    row.append($("<td>").text(Number(preset.usage_count || 0)));
    row.append($("<td>").append(renderStatusBadge(preset.enabled, i18n.t("matcher_presets.status.enabled"), i18n.t("matcher_presets.status.disabled"))));
    row.append($("<td>").addClass("actions-cell").append(renderMatcherPresetActions(preset)));

    return row;
}

function renderMatcherPresetActions(preset) {
    return makeActionMenu({
        object: preset,
        items: [
            {
                label: i18n.t("matcher_presets.actions.edit"),
                icon: "fas fa-edit",
                required: "write",
                denyMessage: i18n.t("matcher_presets.permissions.manager_edit"),
                onClick: function () { editMatcherPreset(preset.id); },
            },
            {
                label: preset.enabled ? i18n.t("matcher_presets.actions.disable") : i18n.t("matcher_presets.actions.enable"),
                icon: preset.enabled ? "fas fa-pause" : "fas fa-play",
                required: "write",
                danger: preset.enabled,
                denyMessage: i18n.t("matcher_presets.permissions.manager_update"),
                onClick: function () { setMatcherPresetEnabled(preset, !preset.enabled); },
            },
            {
                label: i18n.t("matcher_presets.actions.remove"),
                icon: "fas fa-trash",
                required: "delete",
                danger: true,
                denyMessage: i18n.t("matcher_presets.permissions.delete"),
                onClick: function () { removeMatcherPreset(preset); },
            },
        ],
    });
}

function matcherPresetDetailsItem(label, value) {
    return $("<div>")
        .addClass("details-item")
        .append($("<div>").addClass("details-label").text(label))
        .append($("<div>").addClass("details-value").text(value === null || value === undefined || value === "" ? "-" : value));
}

function matcherPresetUsageContext(usage) {
    if (usage.policy_name) {
        return usage.policy_name;
    }

    if (usage.route_name && usage.service_name) {
        return usage.route_name + " / " + usage.service_name;
    }

    if (usage.route_name) {
        return usage.route_name;
    }

    if (usage.service_name) {
        return usage.service_name;
    }

    return i18n.t("matcher_presets.details.resource", {id: usage.id});
}


function matcherPresetUsageList(title, usages) {
    const section = $("<div>").addClass("details-section");

    section.append($("<h3>").text(title));

    if (!usages.length) {
        section.append($("<div>").addClass("details-empty").text(i18n.t("matcher_presets.details.no_usages")));
        return section;
    }

    const list = $("<div>").addClass("details-list");

    usages.forEach(function (usage) {
        list.append(
            matcherPresetDetailsItem(
                matcherPresetUsageContext(usage),
                usage.name || usage.title || i18n.t("matcher_presets.details.resource", {id: usage.id})
            )
        );
    });

    section.append(list);
    return section;
}

function loadMatcherPresetDetails(presetId, options) {
    apiGet("/api/matcher-presets/" + presetId, function (preset) {
        rememberMatcherPresetInCache(preset);
        renderMatcherPresetDetails(preset, options);
    });
}

function renderMatcherPresetDetails(preset, options) {
    selectedMatcherPresetDetailsId = preset.id;

    $("#matcher-preset-details-subtitle").text(
        (preset.team_slug || preset.team_name || "-") + " / v" + Number(preset.version || 1)
    );

    const body = $("#matcher-preset-details-body");
    body.empty();

    body.append(
        $("<div>")
            .addClass("details-list")
            .append(matcherPresetDetailsItem(i18n.t("matcher_presets.details.name"), preset.name))
            .append(matcherPresetDetailsItem(i18n.t("matcher_presets.details.team"), preset.team_slug || preset.team_name))
            .append(matcherPresetDetailsItem(i18n.t("matcher_presets.details.description"), preset.description))
            .append(matcherPresetDetailsItem(i18n.t("matcher_presets.details.version"), "v" + Number(preset.version || 1)))
            .append(matcherPresetDetailsItem(i18n.t("matcher_presets.details.status"), preset.enabled ? i18n.t("matcher_presets.status.enabled") : i18n.t("matcher_presets.status.disabled")))
            .append(matcherPresetDetailsItem(i18n.t("matcher_presets.details.total_usages"), String(preset.usage_count || 0)))
            .append(matcherPresetDetailsItem(i18n.t("matcher_presets.details.matchers"), JSON.stringify(preset.matchers || {}, null, 2)))
    );

    const usages = preset.usages || {};
    body.append(matcherPresetUsageList(i18n.t("matcher_presets.usages.notification"), asArray(usages.notification_policy_rules)));
    body.append(matcherPresetUsageList(i18n.t("matcher_presets.usages.priority"), asArray(usages.priority_policy_rules)));
    body.append(matcherPresetUsageList(i18n.t("matcher_presets.usages.routes"), asArray(usages.routes)));
    body.append(matcherPresetUsageList(i18n.t("matcher_presets.usages.service_match"), asArray(usages.service_match_rules)));
    body.append(matcherPresetUsageList(i18n.t("matcher_presets.usages.runbooks"), asArray(usages.service_runbooks)));
    body.append(matcherPresetUsageList(i18n.t("matcher_presets.usages.silences"), asArray(usages.silences)));

    const actions = $("<div>").addClass("details-actions");

    appendIconActionIfAllowed(actions, preset, {
        required: "write",
        icon: "fas fa-edit",
        label: i18n.t("matcher_presets.actions.edit_preset"),
        onClick: function () { editMatcherPreset(preset.id); },
    });

    appendIconActionIfAllowed(actions, preset, {
        required: "write",
        icon: preset.enabled ? "fas fa-pause" : "fas fa-play",
        label: preset.enabled ? i18n.t("matcher_presets.actions.disable_preset") : i18n.t("matcher_presets.actions.enable_preset"),
        className: preset.enabled ? "btn-warning" : "btn-success",
        onClick: function () { setMatcherPresetEnabled(preset, !preset.enabled); },
    });

    appendIconActionIfAllowed(actions, preset, {
        required: "delete",
        icon: "fas fa-trash-alt",
        label: i18n.t("matcher_presets.actions.remove_preset"),
        className: "btn-danger",
        onClick: function () { removeMatcherPreset(preset); },
    });

    if (actions.children().length) {
        body.append(actions);
    }

    if (options && options.scroll) {
        scrollToAndHighlight("#matcher-preset-details-body", {
            highlight: "#matcher-preset-details-body",
            block: "nearest",
        });
    }
}

function renderMatcherPresetDetailsEmpty() {
    selectedMatcherPresetDetailsId = null;
    $("#matcher-preset-details-subtitle").text(i18n.t("matcher_presets.details.select"));
    $("#matcher-preset-details-body")
        .empty()
        .append(
            $("<div>")
                .addClass("details-empty")
                .text(i18n.t("matcher_presets.details.select_help"))
        );
}

function restoreMatcherPresetDetails() {
    const presets = getFilteredMatcherPresets();

    if (!presets.length) {
        renderMatcherPresetDetailsEmpty();
        return;
    }

    if (selectedMatcherPresetDetailsId) {
        const selected = presets.find(function (preset) { return Number(preset.id) === Number(selectedMatcherPresetDetailsId); });

        if (selected) {
            loadMatcherPresetDetails(selected.id);
            return;
        }
    }

    loadMatcherPresetDetails(presets[0].id);
}

function rememberMatcherPresetInCache(preset) {
    const index = matcherPresetsCache.findIndex(function (item) { return Number(item.id) === Number(preset.id); });

    if (index >= 0) {
        matcherPresetsCache[index] = preset;
    } else {
        matcherPresetsCache.push(preset);
    }
}

function getMatcherPresetById(presetId) {
    return matcherPresetsCache.find(function (preset) { return Number(preset.id) === Number(presetId); }) || null;
}

function collectMatcherPresetPayload() {
    return {
        team_id: Number($("#matcher-preset-team").val()),
        name: $("#matcher-preset-name").val(),
        description: $("#matcher-preset-description").val(),
        matchers: getMatcherEditorValue("#matcher-preset-matchers", {}),
        enabled: $("#matcher-preset-enabled").is(":checked"),
    };
}

function saveMatcherPreset() {
    const presetId = $("#matcher-preset-id").val();
    const payload = collectMatcherPresetPayload();

    if (!String(payload.name || "").trim()) {
        showAppError(i18n.t("matcher_presets.validation.name_required"));
        return;
    }

    if (presetId) {
        delete payload.team_id;

        apiPut("/api/matcher-presets/" + presetId, payload, function () {
            closeAppModal("#matcher-preset-form-modal");
            resetMatcherPresetForm();
            refreshMatcherPresets();
        });
        return;
    }

    apiPost("/api/matcher-presets", payload, function () {
        closeAppModal("#matcher-preset-form-modal");
        resetMatcherPresetForm();
        refreshMatcherPresets();
    });
}

function resetMatcherPresetForm() {
    $("#matcher-preset-form-title").text(i18n.t("matcher_presets.form.create"));
    $("#matcher-preset-id").val("");
    $("#matcher-preset-name").val("");
    $("#matcher-preset-description").val("");
    setMatcherEditorValue("#matcher-preset-matchers", {});
    $("#matcher-preset-enabled").prop("checked", true);
    $("#matcher-preset-team").prop("disabled", false);

    const selectedTeam = $("#global-team-filter").val();

    if (selectedTeam) {
        $("#matcher-preset-team").val(selectedTeam);
    }
}

function openCreateMatcherPresetModal() {
    if (!currentUserCanCreateUiObjects()) {
        showAppError(i18n.t("matcher_presets.permissions.create"), i18n.t("matcher_presets.errors.access_denied"));
        return;
    }

    resetMatcherPresetForm();
    openAppModal("#matcher-preset-form-modal");
}

function editMatcherPreset(presetId) {
    const preset = getMatcherPresetById(presetId);

    if (!preset) {
        showAppError(i18n.t("matcher_presets.errors.not_found"));
        return;
    }

    if (!canWriteObject(preset)) {
        showAppError(i18n.t("matcher_presets.permissions.edit"), i18n.t("matcher_presets.errors.access_denied"));
        return;
    }

    $("#matcher-preset-form-title").text(i18n.t("matcher_presets.form.edit", {id: preset.id}));
    $("#matcher-preset-id").val(preset.id);
    $("#matcher-preset-team").val(preset.team_id).prop("disabled", true);
    $("#matcher-preset-name").val(preset.name || "");
    $("#matcher-preset-description").val(preset.description || "");
    setMatcherEditorValue("#matcher-preset-matchers", preset.matchers || {});
    $("#matcher-preset-enabled").prop("checked", !!preset.enabled);

    openAppModal("#matcher-preset-form-modal");
}

function setMatcherPresetEnabled(preset, enabled) {
    if (!canWriteObject(preset)) {
        showAppError(i18n.t("matcher_presets.permissions.update"), i18n.t("matcher_presets.errors.access_denied"));
        return;
    }

    apiPut("/api/matcher-presets/" + preset.id, {enabled: !!enabled}, refreshMatcherPresets);
}

function removeMatcherPreset(preset) {
    if (!canDeleteObject(preset)) {
        showAppError(i18n.t("matcher_presets.permissions.remove"), i18n.t("matcher_presets.errors.access_denied"));
        return;
    }

    showAppConfirm({
        title: i18n.t("matcher_presets.confirm.title"),
        message: i18n.t("matcher_presets.confirm.message", {name: preset.name}),
        confirmText: i18n.t("matcher_presets.confirm.remove"),
        confirmClass: "btn-danger",
    }).done(function () {
        apiDelete("/api/matcher-presets/" + preset.id, refreshMatcherPresets);
    });
}

$(document).on("click", "#open-matcher-preset-create-modal", openCreateMatcherPresetModal);
$(document).on("click", "#close-matcher-preset-form-modal", function () { closeAppModal("#matcher-preset-form-modal"); });
$(document).on("click", "#reset-matcher-preset-form", resetMatcherPresetForm);
$(document).on("click", "#save-matcher-preset", saveMatcherPreset);
$(document).on("click", "#reload-matcher-presets", refreshMatcherPresets);

$(document).on("input", "#matcher-presets-search", function () {
    renderMatcherPresetsTable();
    restoreMatcherPresetDetails();
});

$(document).on("change", "#matcher-presets-status-filter", function () {
    renderMatcherPresetsTable();
    restoreMatcherPresetDetails();
});
