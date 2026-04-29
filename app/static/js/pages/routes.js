let routesCache = [];

function loadRoutes() {
    /* Load routes page. */
    fillTeamSelect("#route-team", false, loadRouteDependencies);
    refreshRoutes();
}

function loadRouteDependencies(callback) {
    /* Load rotations and channels for selected route team. */
    const teamId = $("#route-team").val();
    if (!teamId) { return; }
    apiGet("/api/rotations?team_id=" + teamId, function (rotations) {
        const select = $("#route-rotation");
        select.empty();
        select.append($("<option>").val("").text("No rotation"));
        rotations = asArray(rotations);
        rotations.forEach(function (r) { if (r.enabled) { select.append($("<option>").val(r.id).text(r.name)); } });
        if (typeof callback === "function") { callback(); }
    });
    apiGet("/api/channels?team_id=" + teamId, function (channels) {
        const select = $("#route-channels");
        select.empty();
        channels = asArray(channels);
        channels.forEach(function (c) { if (c.enabled) { select.append($("<option>").val(c.id).text(c.name + " (" + c.channel_type + ")")); } });
    });
}

function refreshRoutes() {
    /* Refresh routes table. */
    apiGet("/api/routes" + selectedTeamQuery(), function (routes) {
        routes = asArray(routes);
        routesCache = routes;
        const tbody = $("#routes-table");
        tbody.empty();
        routes.forEach(function (r) {
            const channels = asArray(r.channels).map(function (c) { return c.name; }).join(", ");
            const row = $("<tr>");
            row.append($("<td>").text(r.id));
            row.append($("<td>").text(r.team_slug));
            row.append($("<td>").text(r.name));
            row.append($("<td>").text(r.source));
            row.append($("<td>").text(r.rotation_name || "-"));
            row.append($("<td>").text(channels || "-"));
            row.append($("<td>").text(r.intake_token_prefix || "-"));
            row.append($("<td>").text(r.enabled ? "yes" : "no"));
            const actions = $("<td>").addClass("actions");
            actions.append($("<button>").addClass("btn btn-small").text("Edit").on("click", function () { editRoute(r.id); }));
            actions.append($("<button>").addClass("btn btn-small").text("Regenerate token").on("click", function () { regenerateRouteToken(r.id); }));
            actions.append($("<button>").addClass("btn btn-danger btn-small").text("Delete").on("click", function () { deleteRoute(r.id); }));
            row.append(actions);
            tbody.append(row);
        });
    });
}

function collectRoutePayload() {
    /* Build route payload. */
    return {
        team_id: Number($("#route-team").val()),
        name: $("#route-name").val(),
        source: $("#route-source").val(),
        rotation_id: $("#route-rotation").val() ? Number($("#route-rotation").val()) : null,
        channel_ids: ($("#route-channels").val() || []).map(Number),
        matchers: parseJsonInput("#route-matchers", {}),
        group_by: parseJsonInput("#route-group-by", []),
        enabled: $("#route-enabled").is(":checked")
    };
}

function saveRoute() {
    /* Create or update route. */
    const id = $("#route-id").val();

    if (id) {
        apiPut("/api/routes/" + id, collectRoutePayload(), function () {
            resetRouteForm();
            refreshRoutes();
        });
        return;
    }

    apiPost("/api/routes", collectRoutePayload(), function (response) {
        resetRouteForm();
        refreshRoutes();
        showRouteToken(response.intake_token);
    });
}

function editRoute(id) {
    /* Load route data into the form. */
    const r = routesCache.find(function (item) { return item.id === id; });
    if (!r) { return; }
    $("#route-form-title").text("Edit route #" + id);
    $("#route-id").val(r.id);
    $("#route-team").val(r.team_id);
    $("#route-name").val(r.name);
    $("#route-source").val(r.source);
    $("#route-matchers").val(JSON.stringify(r.matchers || {}, null, 2));
    $("#route-group-by").val(JSON.stringify(r.group_by || []));
    $("#route-enabled").prop("checked", !!r.enabled);
    loadRouteDependencies(function () {
        $("#route-rotation").val(r.rotation_id || "");
        $("#route-channels").val(asArray(r.channels).map(function (channel) { return String(channel.id); }));
    });
}

function deleteRoute(id) {
    /* Disable a route. */
    if (!confirm("Disable this route?")) { return; }
    apiDelete("/api/routes/" + id, refreshRoutes);
}

function resetRouteForm() {
    /* Reset route form. */
    $("#route-form-title").text("Create route");
    $("#route-id").val("");
    $("#route-name").val("");
    $("#route-source").val("alertmanager");
    $("#route-matchers").val('{"labels":{"team":"infra"}}');
    $("#route-group-by").val('["alertname","instance"]');
    $("#route-enabled").prop("checked", true);
    $("#route-rotation").val("");
    $("#route-channels").val([]);
    $("#route-token-box").hide();
    $("#route-intake-token").val("");
}

function showRouteToken(token) {
    /* Show route token once. */
    $("#route-token-box").show();
    $("#route-intake-token").val(token || "");
}

function regenerateRouteToken(routeId) {
    /* Regenerate route intake token. */
    if (!confirm("Regenerate route intake token? Existing token will stop working.")) {
        return;
    }

    apiPost("/api/routes/" + routeId + "/intake-token", {}, function (response) {
        showRouteToken(response.intake_token);
        refreshRoutes();
    });
}

$(document).on("change", "#route-team", function () { loadRouteDependencies(); });
$(document).on("click", "#save-route", saveRoute);
$(document).on("click", "#reset-route-form", resetRouteForm);
$(document).on("click", "#reload-routes", refreshRoutes);
