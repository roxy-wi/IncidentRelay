/* Jira object selection and explicit mapping share the source editor lifecycle. */
let cmdbTeamEdits = {};
let cmdbAttributeCatalog = {};

function dsIsCmdb() { return $("#ds-type").val() === "jira_assets"; }

function cmdbSelectAttribute(select, attributes, value, referencesOnly = false, nameField = false) {
    select.empty().append($("<option>", {value: "", text: dsText(nameField ? "cmdb_object_label" : "cmdb_not_mapped")}));
    const available = (attributes || []).filter(item => !referencesOnly || item.type === 1);
    available.forEach(item => select.append($("<option>", {value: item.id, text: item.name + " (#" + item.id + ")"})));
    if (value && !available.some(item => String(item.id) === String(value))) {
        select.append($("<option>", {value, text: value}));
    }
    select.val(value || "");
}

function cmdbRenderAttributes(config) {
    $(".cmdb-attribute").each(function () {
        const kind = $(this).data("kind"), field = $(this).data("field");
        cmdbSelectAttribute($(this), cmdbAttributeCatalog[kind], config[kind][field],
            field === "owner_team_attribute", field === "name_attribute");
    });
    cmdbSelectAttribute($("#cmdb-relationship-attribute"), cmdbAttributeCatalog[config.relationship_side], config.relationship_attribute, true);
    cmdbSelectAttribute($("#cmdb-dependency-attribute"), cmdbAttributeCatalog.services, config.dependency_attribute, true);
}

function cmdbOpen(config, result) {
    cmdbTeamEdits = {};
    cmdbAttributeCatalog = result?.attributes || {};
    $("#cmdb-api-path").val(config.api_path);
    $("#cmdb-query-parameter").val(config.query_parameter);
    $("#cmdb-page-size").val(config.page_size);
    $("#cmdb-create-missing-teams").prop("checked", Boolean(config.create_missing_teams));
    ["services", "business_services"].forEach(kind => $("#cmdb-" + kind + "-query").val(config[kind].query));
    $("#cmdb-relationship-side").val(config.relationship_side);
    $("#cmdb-values").val(JSON.stringify({environment_values: config.environment_values,
        criticality_values: config.criticality_values, business_criticality_values: config.business_criticality_values}, null, 2));
    cmdbRenderAttributes(config);
    destroyTomSelects("#cmdb-team-matches");
    $("#cmdb-team-matches, #cmdb-issues").empty();
    $("#cmdb-issues").prop("hidden", true);
}

function dsApplyType() {
    const cmdb = dsIsCmdb();
    $(".ds-directory-only").prop("hidden", cmdb).find("input, select, textarea, button").prop("disabled", cmdb);
    $("#cmdb-settings").prop("hidden", !cmdb).find("input, select, textarea, button").prop("disabled", !cmdb);
    $("#cmdb-team-matches select").each(function () { setEnhancedSelectDisabled(this, !cmdb); });
    ["horizon", "authority", "current-enabled", "current-interval", "editable", "overwrite", "delete"].forEach(name => {
        const input = $("#ds-" + name);
        input.closest(input.is(":checkbox") ? "label" : ".form-group").prop("hidden", cmdb);
        input.prop("disabled", cmdb);
    });
    $("#ds-current-hint, #ds-current-interval-hint").prop("hidden", cmdb);
    $("#ds-behavior-hint").prop("hidden", cmdb);
    $("#ds-worker-hint").prop("hidden", cmdb);
    $("#ds-current-hint").closest(".form-group").prop("hidden", cmdb);
    $("#ds-type").prop("disabled", Boolean(directorySyncSource));
    $("#ds-url").prop("disabled", cmdb && Boolean(directorySyncSource?.last_success_at));
}

function cmdbConfigFromForm() {
    const original = directorySyncSource?.config || directorySyncOptions.cmdb_preset;
    const matches = {...original.team_matches};
    for (const [externalId, localId] of Object.entries(cmdbTeamEdits)) {
        if (localId) matches[externalId] = localId;
        else delete matches[externalId];
    }
    const config = {...original, ...JSON.parse($("#cmdb-values").val()), source_type: "jira_assets",
        base_url: $("#ds-url").val(), private_network_policy: $("#ds-network").val(),
        verify_tls: !$("#ds-skip-tls").prop("checked"), interval_seconds: Number($("#ds-interval").val()),
        api_path: $("#cmdb-api-path").val(), query_parameter: $("#cmdb-query-parameter").val(),
        page_size: Number($("#cmdb-page-size").val()), team_matches: matches,
        create_missing_teams: $("#cmdb-create-missing-teams").prop("checked"),
        relationship_side: $("#cmdb-relationship-side").val(),
        dependency_attribute: $("#cmdb-dependency-attribute").val() || null,
        relationship_attribute: $("#cmdb-relationship-attribute").val() || null};
    ["services", "business_services"].forEach(kind => {
        config[kind] = {...original[kind], query: $("#cmdb-" + kind + "-query").val()};
    });
    $(".cmdb-attribute").each(function () {
        config[$(this).data("kind")][$(this).data("field")] = $(this).val() || null;
    });
    return config;
}

function cmdbRenderResult(source) {
    if (!dsIsCmdb() || !source || directorySyncDirty) return;
    const result = source.preview_result;
    cmdbAttributeCatalog = result?.attributes || cmdbAttributeCatalog;
    cmdbRenderAttributes(source.config);
    cmdbTeamEdits = {};
    destroyTomSelects("#cmdb-team-matches");
    const container = $("#cmdb-team-matches").empty();
    (result?.team_catalog || []).forEach(team => {
        const select = $("<select>", {id: "cmdb-team-" + team.id, class: "input", "data-cmdb-team": team.id})
            .append($("<option>", {value: "", text: dsText(source.config.create_missing_teams ? "automatic_match" : "cmdb_select_team")}));
        directorySyncOptions.teams.filter(local => local.group_id === source.group_id && local.active !== false)
            .forEach(local => select.append($("<option>", {value: local.id, text: local.name})));
        select.val(source.config.team_matches?.[team.id] || "");
        select.on("change", () => {
            cmdbTeamEdits[team.id] = Number(select.val()) || null;
            directorySyncDirty = true;
            dsRenderWorkflow(directorySyncSource);
        });
        container.append($("<div>", {class: "form-group"}).append($("<label>", {for: "cmdb-team-" + team.id}).text(team.name + " (#" + team.id + ")")).append(select));
        initSearchableSelect(select);
    });
    const messages = [...(result?.issues || []), ...(result?.warnings || [])];
    const issues = $("#cmdb-issues").empty().prop("hidden", !messages.length);
    if (messages.length) {
        issues.append($("<strong>").text(dsText(result?.issues?.length ? "cmdb_resolve_issues" : "cmdb_warnings")));
        const list = $("<ul>").appendTo(issues);
        messages.forEach(message => list.append($("<li>").text(message)));
    }
}

$(document).on("change", "#ds-type", () => {
    if (directorySyncSource) return;
    const config = dsIsCmdb() ? directorySyncOptions.cmdb_preset : directorySyncOptions.preset;
    $("#ds-url").val(config.base_url);
    if (dsIsCmdb()) cmdbOpen(config, null);
    dsApplyType();
    dsRenderWorkflow(null);
});
$(document).on("change", "#cmdb-relationship-side", () => {
    cmdbSelectAttribute($("#cmdb-relationship-attribute"), cmdbAttributeCatalog[$("#cmdb-relationship-side").val()], null, true);
});
$(document).on("change", "#ds-group", () => {
    if (dsIsCmdb() && !directorySyncSource) {
        cmdbTeamEdits = {};
        destroyTomSelects("#cmdb-team-matches");
        $("#cmdb-team-matches").empty();
    }
});
$(document).on("click", "#ds-inspect", () => dsQueue("inspect"));
$(document).on("click", "#cmdb-format-values", () => formatJsonTextarea("#cmdb-values", {}, dsText("cmdb_value_mappings")));
