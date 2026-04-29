let channelsCache = [];
let channelTeamsCache = [];

function loadChannels() {
    /*
     * Load channel form options and the channel list.
     */

    loadChannelGroups(function () {
        loadChannelTypes();
        refreshChannels();
    });
}

function loadChannelGroups(callback) {
    /*
     * Load groups and then load teams for the selected group.
     */

    fillGroupSelect("#channel-group", false, function (groups) {
        if (!groups.length) {
            $("#channel-group").append($("<option>").val("").text("No groups available"));
            $("#channel-team").empty().append($("<option>").val("").text("No teams available"));
            if (typeof callback === "function") {
                callback();
            }
            return;
        }

        loadChannelTeams(callback);
    });
}

function loadChannelTeams(callback) {
    /*
     * Load teams and show only teams from the selected group.
     */

    const groupId = Number($("#channel-group").val());

    apiGet("/api/teams", function (teams) {
        teams = asArray(teams);
        channelTeamsCache = teams;

        const select = $("#channel-team");
        select.empty();

        const filteredTeams = teams.filter(function (team) {
            return !groupId || Number(team.group_id) === groupId;
        });

        if (!filteredTeams.length) {
            select.append($("<option>").val("").text("No teams in this group"));
        } else {
            filteredTeams.forEach(function (team) {
                select.append($("<option>").val(team.id).text("#" + team.id + " " + team.name + " (" + team.slug + ")"));
            });
        }

        if (typeof callback === "function") {
            callback();
        }
    });
}

function loadChannelTypes() {
    /*
     * Load supported channel types from the API.
     */

    apiGet("/api/channels/types", function (types) {
        const select = $("#channel-type");
        select.empty();

        types = asArray(types);
        types.forEach(function (type) {
            select.append($("<option>").val(type).text(type));
        });

        showChannelFields();
    });
}

function showChannelFields() {
    /*
     * Show only fields needed for the selected channel type.
     */

    const type = $("#channel-type").val();

    $(".channel-config").hide();

    if (type === "telegram") {
        $('[data-channel-config="telegram"]').show();
        return;
    }

    if (type === "mattermost") {
        $('[data-channel-config="mattermost"]').show();
        showMattermostModeFields();
        return;
    }

    if (["slack", "webhook", "discord", "teams"].includes(type)) {
        $('[data-channel-config="webhook"]').show();
        return;
    }

    if (type === "email") {
        $('[data-channel-config="email"]').show();
    }
}

function showMattermostModeFields() {
    /*
     * Show Bot API fields or incoming webhook fields for Mattermost.
     */

    const mode = $("#cfg-mm-mode").val();

    if (mode === "webhook") {
        $("#cfg-mm-bot-fields").hide();
        $("#cfg-mm-webhook-fields").show();
        return;
    }

    $("#cfg-mm-bot-fields").show();
    $("#cfg-mm-webhook-fields").hide();
}

function buildChannelConfig() {
    /*
     * Read the channel config from visible form fields.
     */

    const type = $("#channel-type").val();
    const config = parseJsonInput("#channel-config-json", {});

    if (type === "telegram") {
        config.bot_token = $("#cfg-telegram-bot-token").val();
        config.chat_id = $("#cfg-telegram-chat-id").val();
        return config;
    }

    if (type === "mattermost") {
        return buildMattermostConfig(config);
    }

    if (["slack", "webhook", "discord", "teams"].includes(type)) {
        config.webhook_url = $("#cfg-webhook-url").val();
        return config;
    }

    if (type === "email") {
        config.recipients = splitCsv($("#cfg-email-recipients").val());
        config.smtp_host = $("#cfg-email-smtp-host").val();
        config.smtp_port = Number($("#cfg-email-smtp-port").val() || 587);
        return config;
    }

    return config;
}

function buildMattermostConfig(config) {
    /*
     * Build Mattermost config for Bot API or webhook mode.
     */

    const mode = $("#cfg-mm-mode").val();
    config.mode = mode;

    if (mode === "bot_api") {
        config.api_url = $("#cfg-mm-api-url").val();
        config.bot_token = $("#cfg-mm-bot-token").val();
        config.channel_id = $("#cfg-mm-channel-id").val();
        config.callback_secret = $("#cfg-mm-callback-secret").val();
        delete config.webhook_url;
        return config;
    }

    config.webhook_url = $("#cfg-mm-webhook-url").val();
    delete config.api_url;
    delete config.bot_token;
    delete config.channel_id;
    delete config.callback_secret;
    return config;
}

function splitCsv(value) {
    /*
     * Split a comma-separated string into a clean array.
     */

    return (value || "")
        .split(",")
        .map(function (item) { return item.trim(); })
        .filter(Boolean);
}

function collectChannelPayload() {
    /*
     * Build the API payload for creating or updating a channel.
     */

    const teamId = Number($("#channel-team").val());

    if (!teamId) {
        alert("Select a team first.");
        throw new Error("team_id is required");
    }

    return {
        team_id: teamId,
        name: $("#channel-name").val(),
        channel_type: $("#channel-type").val(),
        config: buildChannelConfig(),
        enabled: $("#channel-enabled").is(":checked")
    };
}

function refreshChannels() {
    /*
     * Reload the channels table.
     */

    apiGet("/api/channels" + selectedTeamQuery(), function (channels) {
        channels = asArray(channels);
        channelsCache = channels;
        renderChannels(channels);
    });
}

function renderChannels(channels) {
    /*
     * Render all channels.
     */

    const tbody = $("#channels-table");
    tbody.empty();

    channels.forEach(function (channel) {
        tbody.append(renderChannelRow(channel));
    });
}

function renderChannelRow(channel) {
    /*
     * Render one channel row.
     */

    const row = $("<tr>");
    const config = channel.config || {};
    const mode = channel.channel_type === "mattermost" ? (config.mode || (config.api_url ? "bot_api" : "webhook")) : "-";

    row.append($("<td>").text(channel.id));
    row.append($("<td>").text(channel.group_slug || "-"));
    row.append($("<td>").text(channel.team_slug || "-"));
    row.append($("<td>").text(channel.name));
    row.append($("<td>").text(channel.channel_type));
    row.append($("<td>").text(mode));
    row.append($("<td>").text(channel.enabled ? "yes" : "no"));
    row.append(renderChannelActions(channel));

    return row;
}

function renderChannelActions(channel) {
    /*
     * Render channel action buttons.
     */

    const actions = $("<td>").addClass("actions");

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-small")
            .text("Edit")
            .on("click", function () {
                editChannel(channel.id);
            })
    );

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-small")
            .text("Test")
            .on("click", function () {
                testChannel(channel.id);
            })
    );

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-danger btn-small")
            .text("Delete")
            .on("click", function () {
                deleteChannel(channel.id);
            })
    );

    return actions;
}

function saveChannel() {
    /*
     * Create or update a channel.
     */

    const id = $("#channel-id").val();
    const payload = collectChannelPayload();

    if (id) {
        apiPut("/api/channels/" + id, payload, function () {
            resetChannelForm();
            refreshChannels();
        });
        return;
    }

    apiPost("/api/channels", payload, function () {
        resetChannelForm();
        refreshChannels();
    });
}

function editChannel(id) {
    /*
     * Load a channel into the form.
     */

    const channel = channelsCache.find(function (item) {
        return item.id === id;
    });

    if (!channel) {
        return;
    }

    $("#channel-form-title").text("Edit channel #" + id);
    $("#channel-id").val(channel.id);

    const team = channelTeamsCache.find(function (item) {
        return item.id === channel.team_id;
    });

    if (team && team.group_id) {
        $("#channel-group").val(String(team.group_id));
        loadChannelTeams(function () {
            $("#channel-team").val(String(channel.team_id || ""));
        });
    } else {
        $("#channel-team").val(String(channel.team_id || ""));
    }

    $("#channel-name").val(channel.name);
    $("#channel-type").val(channel.channel_type);
    $("#channel-enabled").prop("checked", !!channel.enabled);
    $("#channel-config-json").val(JSON.stringify(channel.config || {}, null, 2));

    fillChannelFields(channel.channel_type, channel.config || {});
    showChannelFields();
}

function fillChannelFields(type, config) {
    /*
     * Fill channel-specific fields for editing.
     */

    clearChannelFields();

    if (type === "telegram") {
        $("#cfg-telegram-bot-token").val(config.bot_token || "");
        $("#cfg-telegram-chat-id").val(config.chat_id || "");
    }

    if (type === "mattermost") {
        $("#cfg-mm-mode").val(config.mode || (config.api_url ? "bot_api" : "webhook"));
        $("#cfg-mm-api-url").val(config.api_url || "");
        $("#cfg-mm-bot-token").val(config.bot_token || "");
        $("#cfg-mm-channel-id").val(config.channel_id || "");
        $("#cfg-mm-callback-secret").val(config.callback_secret || "");
        $("#cfg-mm-webhook-url").val(config.webhook_url || "");
        showMattermostModeFields();
    }

    if (["slack", "webhook", "discord", "teams"].includes(type)) {
        $("#cfg-webhook-url").val(config.webhook_url || "");
    }

    if (type === "email") {
        $("#cfg-email-recipients").val((config.recipients || []).join(","));
        $("#cfg-email-smtp-host").val(config.smtp_host || "");
        $("#cfg-email-smtp-port").val(config.smtp_port || 587);
    }
}

function clearChannelFields() {
    /*
     * Clear all channel-specific fields.
     */

    $("#cfg-telegram-bot-token").val("");
    $("#cfg-telegram-chat-id").val("");
    $("#cfg-webhook-url").val("");
    $("#cfg-email-recipients").val("");
    $("#cfg-email-smtp-host").val("");
    $("#cfg-email-smtp-port").val("587");

    $("#cfg-mm-mode").val("bot_api");
    $("#cfg-mm-api-url").val("");
    $("#cfg-mm-bot-token").val("");
    $("#cfg-mm-channel-id").val("");
    $("#cfg-mm-callback-secret").val("");
    $("#cfg-mm-webhook-url").val("");
}

function deleteChannel(id) {
    /*
     * Disable a channel.
     */

    if (!confirm("Disable this channel?")) {
        return;
    }

    apiDelete("/api/channels/" + id, refreshChannels);
}

function testChannel(id) {
    /*
     * Send a test notification through a channel.
     */

    apiPost("/api/channels/" + id + "/test", {}, function (response) {
        alert(JSON.stringify(response, null, 2));
    });
}

function resetChannelForm() {
    /*
     * Reset the channel form.
     */

    $("#channel-form-title").text("Create channel");
    $("#channel-id").val("");
    $("#channel-name").val("");
    $("#channel-config-json").val("{}");
    $("#channel-enabled").prop("checked", true);
    clearChannelFields();
    loadChannelTeams();
    showChannelFields();
}

$(document).on("change", "#channel-group", function () {
    loadChannelTeams();
});

$(document).on("change", "#channel-type", showChannelFields);
$(document).on("change", "#cfg-mm-mode", showMattermostModeFields);
$(document).on("click", "#save-channel", saveChannel);
$(document).on("click", "#reset-channel-form", resetChannelForm);
$(document).on("click", "#reload-channels", function () {
    loadChannelGroups(refreshChannels);
});
