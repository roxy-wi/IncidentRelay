/* Group-scoped administration. Event intake and correlation are separate stages. */
let changeIntegration = null;
let changeIntegrations = [];
let changeIntegrationCursor = null;
let changeIntegrationBusy = false;
let changeEditorVersion = 0;
let changeListVersion = 0;
let changeEditorOpen = false;
let changeEditorOpener = null;
let changeSourceEditingId = null;
let changeGrantEditing = null;
let changeServiceRequest = 0;
let changeGrantServicesReady = false;
let changeCreationTeams = [];

function clearChangeSecret() {
    $("#ci-secret").val("");
    $("#ci-secret-box").prop("hidden", true);
}

function changeOption(value, label) {
    return $("<option>").val(value).text(label);
}

function changeEditorCurrent(version) {
    return changeEditorOpen && version === changeEditorVersion;
}

function closeChangeIntegrationModal() {
    const wasOpen = changeEditorOpen;
    changeEditorVersion += 1;
    changeEditorOpen = false;
    changeIntegrationBusy = false;
    changeIntegration = null;
    changeSourceEditingId = null;
    changeGrantEditing = null;
    clearChangeSecret();
    setAppModalSaving("#ci-modal", false);
    closeAppModal("#ci-modal");
    if (wasOpen) {
        if (changeEditorOpener && document.body.contains(changeEditorOpener)) changeEditorOpener.focus();
        else $("#ci-new").trigger("focus");
    }
    changeEditorOpener = null;
}

function prepareChangeEditor(title) {
    clearChangeSecret();
    changeEditorVersion += 1;
    changeEditorOpen = true;
    changeIntegrationBusy = false;
    changeIntegration = null;
    changeEditorOpener = document.activeElement;
    $("#ci-modal-title").text(title);
    $("#ci-editor-status").text(i18n.t("ci.loading"));
    $("#ci-detail, #ci-create").prop("hidden", true);
    $("#ci-modal form").each(function () { this.reset(); });
    $("#ci-modal details").prop("open", false);
    $("#ci-modal button, #ci-modal input, #ci-modal select").prop("disabled", false);
    $("#ci-owner, #ci-team, #ci-service, #ci-new-owner").empty();
    resetChangeSourceForm();
    resetChangeGrantForm();
    setAppModalSaving("#ci-modal", false);
    showChangePanel("sources");
    openAppModal("#ci-modal");
    $("#ci-close").trigger("focus");
    return changeEditorVersion;
}

function openNewChangeIntegration() {
    const version = prepareChangeEditor(i18n.t("ci.add_integration"));
    apiGet("/api/admin/change-integrations/targets", function (data) {
        if (!changeEditorCurrent(version)) return;
        const groups = $("#ci-new-group").empty();
        if (data.can_create_central) groups.append(changeOption("central", i18n.t("ci.central")));
        data.groups.forEach(group => groups.append(changeOption(group.id, group.name)));
        changeCreationTeams = data.teams;
        loadChangeCreationTeams();
        $("#ci-editor-status").text("");
        $("#ci-create").prop("hidden", false);
        $("#ci-new-name").trigger("focus");
    }, function (xhr) { changeEditorError(version, xhr); });
}

function openChangeIntegration(id) {
    const version = prepareChangeEditor(i18n.t("ci.edit"));
    apiGet("/api/admin/change-integrations/" + id, function (data) {
        if (!changeEditorCurrent(version)) return;
        renderChangeIntegration(data);
        loadChangeTargets(version);
        $("#ci-editor-status").text("");
        $("#ci-name").trigger("focus");
    }, function (xhr) { changeEditorError(version, xhr); });
}

function changeEditorError(version, xhr) {
    if (!changeEditorCurrent(version)) return;
    $("#ci-editor-status").text(i18n.t("ci.load_failed"));
    showApiError(xhr);
}

function renderChangeIntegrationList() {
    const rows = $("#ci-table").empty();
    changeIntegrations.forEach(function (item) {
        const row = $("<tr>").attr("data-integration-id", item.id);
        row.append($("<td>").text(item.name));
        row.append($("<td>").text(item.owner_group_name || i18n.t("ci.central")));
        row.append($("<td>").attr("title", i18n.t("ci.count_hint")).text(item.source_count));
        row.append($("<td>").attr("title", i18n.t("ci.count_hint")).text(item.permission_count));
        row.append($("<td>").append($("<span>", {class: "status-pill " + (item.active ? "status-active" : "status-inactive")})
            .text(i18n.t(item.active ? "ci.active" : "ci.inactive"))));
        row.append($("<td>").text(item.updated_at ? new Date(item.updated_at).toLocaleString() : "\u2014"));
        row.append($("<td>", {class: "actions-cell"}).append(makeActionMenu({object: item, items: [
            {label: i18n.t("ci.edit"), icon: "fas fa-edit", onClick: () => openChangeIntegration(item.id)},
        ]})));
        rows.append(row);
    });
    $("#ci-list-status").text(changeIntegrations.length ? "" : i18n.t("ci.empty"));
}

function loadChangeIntegrationList(append) {
    const version = ++changeListVersion;
    $("#ci-more").prop("disabled", true);
    if (!append) $("#ci-list-status").text(i18n.t("ci.loading"));
    apiGet("/api/admin/change-integrations" + (append && changeIntegrationCursor ? "?after=" + changeIntegrationCursor : ""), function (data) {
        if (version !== changeListVersion) return;
        changeIntegrations = append ? changeIntegrations.concat(data.items) : data.items;
        changeIntegrationCursor = data.next_cursor;
        renderChangeIntegrationList();
        $("#ci-more").prop("hidden", !changeIntegrationCursor).prop("disabled", false);
        $("#ci-pagination").prop("hidden", !changeIntegrationCursor);
    }, function (xhr) {
        if (version !== changeListVersion) return;
        $("#ci-list-status").text(i18n.t("ci.load_failed"));
        $("#ci-more").prop("disabled", false);
        showApiError(xhr);
    });
}

function loadChangeIntegrations() {
    closeChangeIntegrationModal();
    loadChangeIntegrationList(false);
}

function loadChangeTargets(version) {
    if (!changeIntegration) return;
    apiGet("/api/admin/change-integrations/targets?integration_id=" + changeIntegration.id, function (data) {
        if (!changeEditorCurrent(version)) return;
        $("#ci-owner, #ci-team").each(function () {
            const select = $(this), value = select.val(), label = select.find("option:selected").text();
            select.empty();
            data.teams.forEach(team => select.append(changeOption(team.id, changeCatalogLabel(team.name, team.slug))));
            if (value) selectChangeValue(select, value, label);
        });
        if (!changeGrantEditing) loadChangeGrantServices();
    }, function (xhr) { changeEditorError(version, xhr); });
}

function loadChangeGrantServices(selectedService, selectedLabel) {
    if (!changeIntegration) return;
    const version = changeEditorVersion;
    const requestId = ++changeServiceRequest;
    const team = $("#ci-team").val();
    changeGrantServicesReady = false;
    $("#ci-service, #ci-add-grant button[type=submit]").prop("disabled", true);
    $("#ci-service").empty().append(changeOption("", i18n.t("ci.all_services")));
    if (!team) return;
    apiGet("/api/admin/change-integrations/targets?integration_id=" + changeIntegration.id + "&team_id=" + team, function (data) {
        if (!changeEditorCurrent(version) || requestId !== changeServiceRequest || $("#ci-team").val() !== team) return;
        data.services.forEach(service => $("#ci-service").append(changeOption(service.id, changeCatalogLabel(service.name, service.slug))));
        if (selectedService) selectChangeValue($("#ci-service"), selectedService, selectedLabel);
        changeGrantServicesReady = true;
        $("#ci-service, #ci-add-grant button[type=submit]").prop("disabled", changeIntegrationBusy);
    }, function (xhr) {
        if (requestId === changeServiceRequest) changeEditorError(version, xhr);
    });
}

function changeIntegrationWrite(method, suffix, payload, onSuccess) {
    if (changeIntegrationBusy || !changeEditorOpen) return;
    const version = changeEditorVersion;
    changeIntegrationBusy = true;
    const controls = $("#ci-modal").find("button, input, select");
    setAppModalSaving("#ci-modal", true);
    controls.prop("disabled", true);
    const finish = function () {
        if (!changeEditorCurrent(version)) return false;
        changeIntegrationBusy = false;
        controls.prop("disabled", false);
        setAppModalSaving("#ci-modal", false);
        applyChangeSourceIdentityLock();
        $("#ci-service, #ci-add-grant button[type=submit]").prop("disabled", !changeGrantServicesReady);
        return true;
    };
    apiRequest(method, "/api/admin/change-integrations" + suffix, payload, function (data) {
        if (finish()) onSuccess(data);
    }, function (xhr) {
        if (finish()) showApiError(xhr);
    });
}

function changeIntegrationEdit(method, suffix, payload, onSuccess) {
    if (!changeIntegration) return;
    changeIntegrationWrite(method, "/" + changeIntegration.id + suffix,
        {...payload, expected_revision: changeIntegration.auth_revision}, function (data) {
            renderChangeIntegration(data);
            if (onSuccess) onSuccess(data);
        });
}

function showChangePanel(panel) {
    $("#ci-modal .ci-panel").prop("hidden", true);
    $("#ci-panel-" + panel).prop("hidden", false);
    $("#ci-modal [data-ci-panel]").each(function () {
        const selected = this.dataset.ciPanel === panel;
        $(this).attr("aria-pressed", String(selected)).toggleClass("is-active", selected);
    });
    if (panel !== "tokens") clearChangeSecret();
}

function renderChangeIntegration(data) {
    changeIntegration = data;
    $("#ci-detail").prop("hidden", false);
    $("#ci-name").val(data.name);
    $("#ci-active").prop("checked", data.active);
    $("#ci-identity").text(data.uid);
    $("#ci-modal-title").text(i18n.t("ci.edit") + " \u00b7 " + data.name);
    $("#ci-group-label").text(data.owner_group_name || i18n.t("ci.central"));
    $("#ci-central-hint").prop("hidden", data.owner_group_id !== null);
    const index = changeIntegrations.findIndex(item => item.id === data.id);
    if (index >= 0) changeIntegrations[index] = data;
    else changeIntegrations.unshift(data);
    renderChangeIntegrationList();
    $("#ci-sources, #ci-grants, #ci-tokens, #ci-grant-source, #ci-rotate").empty();
    $("#ci-rotate").append(changeOption("", i18n.t("ci.new_token")));
    data.sources.forEach(function (source) {
        const owner = changeCatalogLabel(source.owner_team_name, source.owner_team_slug, "team", source.owner_team_id);
        $("#ci-grant-source").append(changeOption(source.id, source.source + " \u2014 " + owner));
        const row = $("<tr>").attr("data-source-id", source.id)
            .append($("<td>").text(source.source), $("<td>").text(owner));
        row.append($("<td>").text(i18n.t(source.ordering_mode === "sequence" ? "ci.order_sequence" : "ci.order_timestamp")));
        row.append($("<td>").append(changeStatus(source.active ? "ci.active" : "ci.inactive", source.active)));
        row.append($("<td>", {class: "actions-cell"}).append(makeActionMenu({object: source, items: [
            {label: i18n.t("ci.edit_source"), icon: "fas fa-edit", onClick: () => editChangeSource(source)},
            {label: i18n.t(source.active ? "ci.disable" : "ci.enable"), icon: source.active ? "fas fa-ban" : "fas fa-check",
                onClick: () => changeIntegrationEdit("PATCH", "/sources/" + source.id, {active: !source.active})},
        ]})));
        $("#ci-sources").append(row);
        source.grants.forEach(function (grant) {
            const team = changeCatalogLabel(grant.target_team_name, grant.target_team_slug, "team", grant.target_team_id);
            const service = grant.target_service_id
                ? changeCatalogLabel(grant.target_service_name, grant.target_service_slug, "service", grant.target_service_id)
                : i18n.t("ci.all_services");
            const capability = {reference: "ci.reference", changed: "ci.changed", reported_affected: "ci.reported"}[grant.capability];
            $("#ci-grants").append($("<tr>").attr("data-grant-id", grant.id)
                .append($("<td>").append($("<span>").text(source.source), $("<small>", {class: "muted ci-source-owner"}).text(i18n.t("ci.owner") + ": " + owner)))
                .append($("<td>").text(i18n.t(capability)), $("<td>").text(team), $("<td>").text(service))
                .append($("<td>").append(changeStatus(grant.active ? "ci.active" : "ci.inactive", grant.active)))
                .append($("<td>", {class: "actions-cell"}).append(makeActionMenu({object: grant, items: [
                    {label: i18n.t("ci.edit_permission"), icon: "fas fa-edit", onClick: () => editChangeGrant(source, grant)},
                    {label: i18n.t(grant.active ? "ci.disable" : "ci.enable"), icon: grant.active ? "fas fa-ban" : "fas fa-check",
                        onClick: () => changeIntegrationEdit("PATCH", "/sources/" + source.id + "/grants/" + grant.id, {active: !grant.active})},
                ]}))));
        });
    });
    data.tokens.forEach(function (token) {
        const prefix = token.token_prefix + "\u2026";
        const status = !token.active ? "ci.revoked" : token.expired ? "ci.expired" : "ci.active";
        const row = $("<tr>").attr("data-token-id", token.id)
            .append($("<td>").text(token.name), $("<td>").append($("<span>", {class: "ci-token-prefix"}).text(prefix)))
            .append($("<td>").append(changeStatus(status, token.active && !token.expired)))
            .append($("<td>").text(token.expires_at ? new Date(token.expires_at).toLocaleString() : i18n.t("ci.no_expiry")))
            .append($("<td>").text(token.last_used_at ? new Date(token.last_used_at).toLocaleString() : i18n.t("ci.never_used")));
        const actions = $("<td>", {class: "actions-cell"});
        if (token.active) {
            $("#ci-rotate").append(changeOption(token.id, token.name + " \u2014 " + prefix));
            actions.append(makeActionMenu({object: token, items: [
                {label: i18n.t("ci.rotate"), icon: "fas fa-sync-alt", onClick: () => {
                    $("#ci-issue").closest("details").prop("open", true);
                    $("#ci-token-name").val(token.name);
                    $("#ci-rotate").val(String(token.id));
                    document.querySelector("#ci-issue").scrollIntoView({block: "nearest"});
                    $("#ci-token-name").trigger("focus");
                }},
                {label: i18n.t("ci.revoke"), icon: "fas fa-ban", danger: true,
                    onClick: () => changeIntegrationEdit("POST", "/tokens/" + token.id + "/revoke", {})},
            ]}));
        } else {
            actions.text("\u2014");
        }
        $("#ci-tokens").append(row.append(actions));
    });
    changeEmptyRow("#ci-sources", 5, "ci.no_sources");
    changeEmptyRow("#ci-grants", 6, "ci.no_grants");
    changeEmptyRow("#ci-tokens", 6, "ci.no_credentials");
}

function changeCatalogLabel(name, slug, kind, id) {
    if (!name) return i18n.t("ci.unavailable_" + kind) + " (#" + id + ")";
    return name + (slug ? " (" + slug + ")" : "");
}

function changeStatus(key, active) {
    return $("<span>", {class: "status-pill " + (active ? "status-active" : "status-inactive")}).text(i18n.t(key));
}

function changeEmptyRow(selector, columns, key) {
    if (!$(selector).children().length) {
        $(selector).append($("<tr>").append($("<td>", {colspan: columns, class: "empty-cell"}).text(i18n.t(key))));
    }
}

function selectChangeValue(select, value, label) {
    if (!select.find("option").filter(function () { return this.value === String(value); }).length) {
        select.append(changeOption(value, label));
    }
    select.val(String(value));
}

function loadChangeCreationTeams() {
    const group = $("#ci-new-group").val(), teams = $("#ci-new-owner").empty();
    changeCreationTeams.filter(team => group === "central" || String(team.group_id) === group)
        .forEach(team => teams.append(changeOption(team.id, changeCatalogLabel(team.name, team.slug))));
    $("#ci-create button[type=submit]").prop("disabled", !teams.children().length);
    $("#ci-new-owner-hint").text(i18n.t(teams.children().length ? "ci.auto_source_hint" : "ci.no_owner_teams"));
}

function resetChangeSourceForm() {
    changeSourceEditingId = null;
    const form = $("#ci-add-source");
    form[0]?.reset();
    form.closest("details").prop("open", false);
    $("#ci-source-form-toggle, #ci-add-source button[type=submit]").text(i18n.t("ci.add_source"));
    $("#ci-source-cancel, #ci-source-edit-status, #ci-source-lock-hint").prop("hidden", true);
    $("#ci-source-name, #ci-owner").prop("disabled", false);
}

function applyChangeSourceIdentityLock() {
    const source = changeIntegration?.sources.find(item => item.id === changeSourceEditingId);
    const locked = Boolean(source && !source.identity_editable);
    $("#ci-source-name, #ci-owner").prop("disabled", changeIntegrationBusy || locked);
    $("#ci-source-lock-hint").prop("hidden", !locked);
}

function editChangeSource(source) {
    resetChangeSourceForm();
    changeSourceEditingId = source.id;
    $("#ci-source-name").val(source.source);
    selectChangeValue($("#ci-owner"), source.owner_team_id,
        changeCatalogLabel(source.owner_team_name, source.owner_team_slug, "team", source.owner_team_id));
    $("#ci-ordering").val(source.ordering_mode);
    $("#ci-source-active").prop("checked", source.active);
    $("#ci-source-form-toggle").text(i18n.t("ci.edit_source"));
    $("#ci-add-source button[type=submit]").text(i18n.t("ci.save"));
    $("#ci-source-cancel, #ci-source-edit-status").prop("hidden", false);
    applyChangeSourceIdentityLock();
    $("#ci-add-source").closest("details").prop("open", true);
    document.querySelector("#ci-add-source").scrollIntoView({block: "nearest"});
    $(source.identity_editable ? "#ci-source-name" : "#ci-ordering").trigger("focus");
}

function resetChangeGrantForm() {
    changeGrantEditing = null;
    $("#ci-add-grant")[0]?.reset();
    $("#ci-add-grant").closest("details").prop("open", false);
    $("#ci-grant-form-toggle, #ci-add-grant button[type=submit]").text(i18n.t("ci.add_grant"));
    $("#ci-grant-cancel, #ci-grant-edit-status").prop("hidden", true);
    changeServiceRequest += 1;
    changeGrantServicesReady = false;
    $("#ci-service, #ci-add-grant button[type=submit]").prop("disabled", true);
}

function editChangeGrant(source, grant) {
    resetChangeGrantForm();
    changeGrantEditing = {sourceId: source.id, id: grant.id};
    $("#ci-grant-source").val(String(source.id));
    $("#ci-capability").val(grant.capability);
    selectChangeValue($("#ci-team"), grant.target_team_id,
        changeCatalogLabel(grant.target_team_name, grant.target_team_slug, "team", grant.target_team_id));
    loadChangeGrantServices(grant.target_service_id,
        changeCatalogLabel(grant.target_service_name, grant.target_service_slug, "service", grant.target_service_id));
    $("#ci-grant-active").prop("checked", grant.active);
    $("#ci-grant-form-toggle").text(i18n.t("ci.edit_permission"));
    $("#ci-add-grant button[type=submit]").text(i18n.t("ci.save"));
    $("#ci-grant-cancel, #ci-grant-edit-status").prop("hidden", false);
    $("#ci-add-grant").closest("details").prop("open", true);
    document.querySelector("#ci-add-grant").scrollIntoView({block: "nearest"});
    $("#ci-capability").trigger("focus");
}

$(document).on("click", "#ci-new", openNewChangeIntegration);
$(document).on("click", "#ci-reload", () => loadChangeIntegrationList(false));
$(document).on("click", "#ci-more", () => loadChangeIntegrationList(true));
$(document).on("click", "#ci-close, #ci-close-footer, #ci-modal", function (event) {
    if (this.id === "ci-modal" && event.target !== this) return;
    if (!changeIntegrationBusy) closeChangeIntegrationModal();
});
$(document).on("keydown", function (event) {
    if (!changeEditorOpen) return;
    // The shared modal handler closes the topmost dialog first.
    if (event.key === "Escape" && !$("#ci-modal").hasClass("is-open")) closeChangeIntegrationModal();
    if (event.key === "Tab" && $("#ci-modal").hasClass("is-open") && !$("#app-dialog-modal").hasClass("is-open")) {
        const controls = $("#ci-modal").find("button, input, select, textarea, summary").filter(":visible:not(:disabled)");
        const first = controls[0], last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
});
$(document).on("click", "#ci-modal [data-ci-panel]", function () { showChangePanel(this.dataset.ciPanel); });
$(document).on("change", "#ci-team", () => loadChangeGrantServices());
$(document).on("change", "#ci-new-group", loadChangeCreationTeams);
$(document).on("click", "#ci-source-cancel", resetChangeSourceForm);
$(document).on("click", "#ci-grant-cancel", function () { resetChangeGrantForm(); loadChangeGrantServices(); });
$(document).on("click", "#ci-clear-secret", clearChangeSecret);
$(window).on("pagehide", closeChangeIntegrationModal);
$(document).on("submit", "#ci-create", function (event) {
    event.preventDefault();
    const group = $("#ci-new-group").val();
    changeIntegrationWrite("POST", "", {name: $("#ci-new-name").val(), owner_group_id: group === "central" ? null : Number(group), owner_team_id: Number($("#ci-new-owner").val())}, function (data) {
        $("#ci-create").prop("hidden", true);
        renderChangeIntegration(data);
        loadChangeTargets(changeEditorVersion);
    });
});
$(document).on("submit", "#ci-edit", function (event) {
    event.preventDefault();
    changeIntegrationEdit("PATCH", "", {name: $("#ci-name").val(), active: $("#ci-active").is(":checked")});
});
$(document).on("submit", "#ci-add-source", function (event) {
    event.preventDefault();
    const payload = {ordering_mode: $("#ci-ordering").val()};
    const source = changeIntegration.sources.find(item => item.id === changeSourceEditingId);
    if (!source || source.identity_editable) {
        payload.owner_team_id = Number($("#ci-owner").val());
        payload.source = $("#ci-source-name").val();
    }
    if (source) payload.active = $("#ci-source-active").is(":checked");
    changeIntegrationEdit(source ? "PATCH" : "POST", "/sources" + (source ? "/" + source.id : ""), payload, resetChangeSourceForm);
});
$(document).on("submit", "#ci-add-grant", function (event) {
    event.preventDefault();
    if (!changeGrantServicesReady) return;
    const payload = {
        target_team_id: Number($("#ci-team").val()), target_service_id: $("#ci-service").val() ? Number($("#ci-service").val()) : null,
        capability: $("#ci-capability").val(),
    };
    if (changeGrantEditing) {
        payload.source_id = Number($("#ci-grant-source").val());
        payload.active = $("#ci-grant-active").is(":checked");
    }
    const suffix = changeGrantEditing
        ? "/sources/" + changeGrantEditing.sourceId + "/grants/" + changeGrantEditing.id
        : "/sources/" + $("#ci-grant-source").val() + "/grants";
    changeIntegrationEdit(changeGrantEditing ? "PATCH" : "POST", suffix, payload, function () {
        resetChangeGrantForm(); loadChangeGrantServices();
    });
});
$(document).on("submit", "#ci-issue", function (event) {
    event.preventDefault();
    if (!changeIntegration) return;
    clearChangeSecret();
    const id = changeIntegration.id;
    const version = changeEditorVersion;
    const old = $("#ci-rotate").val();
    changeIntegrationWrite("POST", "/" + id + "/tokens" + (old ? "/" + old + "/rotate" : ""), {
        expected_revision: changeIntegration.auth_revision, name: $("#ci-token-name").val(), days: Number($("#ci-days").val()),
    }, function (data) {
        $("#ci-secret").val(data.token);
        $("#ci-secret-box").prop("hidden", false);
        apiGet("/api/admin/change-integrations/" + id, function (detail) {
            if (changeEditorCurrent(version)) renderChangeIntegration(detail);
        }, function (xhr) { changeEditorError(version, xhr); });
    });
});
