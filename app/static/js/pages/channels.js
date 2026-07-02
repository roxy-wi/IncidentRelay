let channelsCache = [];
let channelTeamsCache = [];
let selectedChannelDetailsId = null;
let emailDefaultTemplateCache = null;

function loadChannels() {
    loadDefaultEmailHtmlTemplate(function () {
        loadChannelGroups(function () {
            loadChannelTypes();
            refreshChannels();
        });
    });
}

function loadChannelGroups(callback) {
    fillGroupSelect("#channel-group", false, function (groups) {
        groups = asArray(groups);
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

function loadDefaultEmailHtmlTemplate(callback) {
    if (emailDefaultTemplateCache !== null) {
        if (typeof callback === "function") {
            callback(emailDefaultTemplateCache);
        }
        return;
    }

    apiGet("/api/channels/email-template/default", function (response) {
        response = response || {};
        emailDefaultTemplateCache = String(response.html_template || "");
        $("#cfg-email-html-template").data("defaultTemplate", emailDefaultTemplateCache);
        if (!String($("#cfg-email-html-template").val() || "").trim()) {
            $("#cfg-email-html-template").val(emailDefaultTemplateCache);
        }
        if (typeof callback === "function") {
            callback(emailDefaultTemplateCache);
        }
    });
}

function loadChannelTeams(callback) {
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
                select.append(
                    $("<option>")
                        .val(team.id)
                        .text("#" + team.id + " " + team.name + " (" + team.slug + ")")
                );
            });
        }

        if (typeof callback === "function") {
            callback();
        }
    });
}

function loadChannelTypes() {
    apiGet("/api/channels/types", function (types) {
        const select = $("#channel-type");
        select.empty();
        types = asArray(types);
        types.forEach(function (type) {
            select.append($("<option>").val(type).text(type));
        });
        fillChannelTypeFilter(types);
        showChannelFields();
    });
}

function showChannelFields() {
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
    if (type === "slack") {
        $('[data-channel-config="slack"]').show();
        showSlackModeFields();
        return;
    }

    if (["webhook", "discord", "teams"].includes(type)) {
        $('[data-channel-config="webhook"]').show();
        return;
    }
    if (type === "email") {
        $('[data-channel-config="email"]').show();
        return;
    }
}

function buildSlackConfig(config) {
    const mode = $("#cfg-slack-mode").val() || "bot_api";

    config.mode = mode;

    if (mode === "bot_api") {
        config.bot_token = String(
            $("#cfg-slack-bot-token").val() || ""
        ).trim();

        config.channel_id = String(
            $("#cfg-slack-channel-id").val() || ""
        ).trim();

        delete config.webhook_url;
        return config;
    }

    config.webhook_url = String(
        $("#cfg-slack-webhook-url").val() || ""
    ).trim();

    delete config.bot_token;
    delete config.channel_id;

    return config;
}

function updateWebhookLabel(type) {
    const labels = {
        slack: "Slack webhook URL",
        webhook: "Webhook URL",
        discord: "Discord webhook URL",
        teams: "Microsoft Teams webhook URL",
    };
    $("#cfg-webhook-label").text(labels[type] || "Webhook URL");
}

function showMattermostModeFields() {
    const mode = $("#cfg-mm-mode").val();
    if (mode === "webhook") {
        $("#cfg-mm-bot-fields").hide();
        $("#cfg-mm-webhook-fields").show();
        return;
    }
    $("#cfg-mm-bot-fields").show();
    $("#cfg-mm-webhook-fields").hide();
}

function showSlackModeFields() {
    const mode = $("#cfg-slack-mode").val() || "bot_api";

    if (mode === "webhook") {
        $("#cfg-slack-bot-fields").hide();
        $("#cfg-slack-webhook-fields").show();
        return;
    }

    $("#cfg-slack-bot-fields").show();
    $("#cfg-slack-webhook-fields").hide();
}

function getDefaultEmailHtmlTemplate() {
    if (emailDefaultTemplateCache === null) {
        const field = $("#cfg-email-html-template");
        emailDefaultTemplateCache = String(field.data("defaultTemplate") || field.val() || "");
    }
    return emailDefaultTemplateCache;
}

function resetEmailHtmlTemplate() {
    loadDefaultEmailHtmlTemplate(function (template) {
        $("#cfg-email-html-template").val(template || "");
    });
}

function getEmailHtmlTemplateConfigValue() {
    const value = String($("#cfg-email-html-template").val() || "").trim();
    const defaultValue = String(getDefaultEmailHtmlTemplate() || "").trim();
    if (!value || value === defaultValue) {
        return null;
    }
    return value;
}

function buildChannelConfig() {
    const type = $("#channel-type").val();
    const config = parseJsonInput("#channel-config-json", {});
    const notifyOnSeverities = getChannelNotifySeverities();

    if (notifyOnSeverities.length) {
        config.notify_on_severities = notifyOnSeverities;
    } else {
        delete config.notify_on_severities;
    }

    if (type === "telegram") {
        config.bot_token = $("#cfg-telegram-bot-token").val();
        config.chat_id = $("#cfg-telegram-chat-id").val();
        return config;
    }
    if (type === "mattermost") {
        return buildMattermostConfig(config);
    }
    if (type === "slack") {
        return buildSlackConfig(config);
    }

    if (["webhook", "discord", "teams"].includes(type)) {
        config.webhook_url = String(
            $("#cfg-webhook-url").val() || ""
        ).trim();

        return config;
    }
    if (type === "email") {
        const htmlTemplate = getEmailHtmlTemplateConfigValue();
        if (htmlTemplate) {
            config.html_template = htmlTemplate;
        } else {
            delete config.html_template;
        }
        return config;
    }
    return config;
}

function buildMattermostConfig(config) {
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

function getSelectedChannelTeam() {
    const teamId = Number($("#channel-team").val());
    return channelTeamsCache.find(function (team) {
        return Number(team.id) === teamId;
    });
}

function canWriteChannelResourceForTeam(team) {
    const permissions = (team && team.permissions) || {};
    return Boolean(
        permissions.can_write_resources ||
        permissions.can_write
    );
}

function collectChannelPayload() {
    const teamId = Number($("#channel-team").val());
    if (!teamId) {
        showAppError("Select a team first.");
        throw new Error("team_id is required");
    }

    return {
        team_id: teamId,
        name: $("#channel-name").val(),
        channel_type: $("#channel-type").val(),
        config: buildChannelConfig(),
        enabled: $("#channel-enabled").is(":checked"),
    };
}

function refreshChannels() {
    apiGet("/api/channels" + selectedTeamQuery(), function (channels) {
        channelsCache = asArray(channels);
        renderChannelsSummary(channelsCache);
        renderChannels();
        if (selectedChannelDetailsId) {
            restoreChannelDetails();
        } else if (channelsCache.length) {
            renderChannelDetails(channelsCache[0]);
        } else {
            renderChannelDetailsEmpty();
        }
    });
}

function renderChannels() {
    const tbody = $("#channels-table");
    const channels = getFilteredChannels();
    tbody.empty();
    renderChannelsCounter(channels, channelsCache);

    if (!channels.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>").attr("colspan", "7").addClass("empty-cell").text("No channels")
            )
        );
        return;
    }

    channels.forEach(function (channel) {
        tbody.append(renderChannelRow(channel));
    });
}

function renderChannelRow(channel) {
    const row = $("<tr>");
    const mode = getChannelModeLabel(channel);

    row.append(
        $("<td>")
            .append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("name-button")
                    .text(channel.name || "-")
                    .on("click", function () {
                        renderChannelDetails(channel);
                    })
            )
            .append($("<div>").addClass("row-subtitle").text("Channel #" + channel.id))
    );
    row.append($("<td>").text(channel.group_name || channel.group_slug || "-"));
    row.append($("<td>").text(channel.team_name|| channel.team_slug || "-"));
    row.append($("<td>").append($("<span>").addClass("channel-type-pill").text(channel.channel_type || "-")));
    row.append($("<td>").append($("<span>").addClass("channel-mode-pill").text(mode)));
    row.append($("<td>").append(renderStatusBadge(channel.enabled, "Enabled", "Disabled")));
    row.append($("<td>").addClass("actions-cell").append(renderChannelActions(channel)));
    return row;
}

function renderChannelActions(channel) {
    /*
     * Render channel row actions as a shared three-dots menu.
     */
    return makeActionMenu({
        object: channel,
        items: [
            {
                label: "Edit",
                icon: "fas fa-edit",
                required: "write",
                denyMessage: "Team manager role is required to edit this channel.",
                onClick: function () {
                    editChannel(channel.id);
                }
            },
            {
                label: "Test",
                icon: "fas fa-vial",
                required: "write",
                denyMessage: "Team manager role is required to test this channel.",
                onClick: function () {
                    testChannel(channel.id);
                }
            },
            {
                label: channel.enabled ? "Disable" : "Enable",
                icon: channel.enabled ? "fas fa-pause" : "fas fa-play",
                required: "write",
                danger: channel.enabled,
                denyMessage: "Team manager role is required to enable or disable this channel.",
                onClick: function () {
                    if (channel.enabled) {
                        disableChannel(channel);
                    } else {
                        enableChannel(channel);
                    }
                }
            },
            {
                label: "Delete",
                icon: "fas fa-trash",
                required: "delete",
                danger: true,
                denyMessage: "Delete permission is required to delete this channel.",
                onClick: function () {
                    deleteChannel(channel);
                }
            }
        ]
    });
}

function saveChannel() {
    const id = $("#channel-id").val();
    const existing = id ? channelsCache.find(function (item) { return Number(item.id) === Number(id); }) : null;
    const selectedTeam = getSelectedChannelTeam();

    if (existing && !canWriteObject(existing)) {
        showAppError("You do not have permission to edit this channel.");
        return;
    }
    if (!existing && selectedTeam && !canWriteChannelResourceForTeam(selectedTeam)) {
        showAppError("Team manager or group editor role is required to create channels in this team.");
        return;
    }

    const payload = collectChannelPayload();
    if (id) {
        apiPut("/api/channels/" + id, payload, function () {
            closeAppModal("#channel-form-modal");
            resetChannelForm();
            refreshChannels();
        });
        return;
    }

    apiPost("/api/channels", payload, function () {
        closeAppModal("#channel-form-modal");
        resetChannelForm();
        refreshChannels();
    });
}

function editChannel(id) {
    const channel = channelsCache.find(function (item) {
        return Number(item.id) === Number(id);
    });
    if (!channel) {
        return;
    }
    if (!canWriteObject(channel)) {
        showAppError("You do not have permission to edit this channel.");
        return;
    }

    $("#channel-form-title").text("Edit channel #" + id);
    $("#channel-id").val(channel.id);

    const team = channelTeamsCache.find(function (item) {
        return Number(item.id) === Number(channel.team_id);
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
    $("#channel-config-json").val(JSON.stringify(stripVisibleChannelConfig(channel.channel_type, channel.config || {}), null, 2));
    fillChannelFields(channel.channel_type, channel.config || {});
    showChannelFields();
    openAppModal("#channel-form-modal");
}

function stripVisibleChannelConfig(type, config) {
    config = Object.assign({}, config || {});
    if (type === "telegram") {
        delete config.bot_token;
        delete config.chat_id;
    }
    if (type === "mattermost") {
        delete config.mode;
        delete config.api_url;
        delete config.bot_token;
        delete config.channel_id;
        delete config.callback_secret;
        delete config.webhook_url;
    }
    if (type === "slack") {
        delete config.mode;
        delete config.bot_token;
        delete config.channel_id;
        delete config.webhook_url;
    }
    if (["webhook", "discord", "teams"].includes(type)) {
        delete config.webhook_url;
    }
    return config;
}

function fillChannelFields(type, config) {
    clearChannelFields();
    setChannelNotifySeverities(config.notify_on_severities || []);

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
    if (type === "slack") {
        const inferredMode = (
            config.bot_token && config.channel_id
                ? "bot_api"
                : "webhook"
        );

        $("#cfg-slack-mode").val(
            config.mode || inferredMode
        );

        $("#cfg-slack-bot-token").val(
            config.bot_token || ""
        );

        $("#cfg-slack-channel-id").val(
            config.channel_id || ""
        );

        $("#cfg-slack-webhook-url").val(
            config.webhook_url || ""
        );

        showSlackModeFields();
    }
    if (["webhook", "discord", "teams"].includes(type)) {
        $("#cfg-webhook-url").val(config.webhook_url || "");
        updateWebhookLabel(type);
    }
    if (type === "email") {
        $("#cfg-email-html-template").val(config.html_template || getDefaultEmailHtmlTemplate());
    }
}

function clearChannelFields() {
    $("#cfg-telegram-bot-token").val("");
    $("#cfg-telegram-chat-id").val("");
    $("#cfg-webhook-url").val("");
    $("#cfg-mm-mode").val("bot_api");
    $("#cfg-mm-api-url").val("");
    $("#cfg-mm-bot-token").val("");
    $("#cfg-mm-channel-id").val("");
    $("#cfg-mm-callback-secret").val("");
    $("#cfg-mm-webhook-url").val("");
    $(".cfg-channel-severity").prop("checked", false);
    $("#cfg-slack-mode").val("bot_api");
    $("#cfg-slack-bot-token").val("");
    $("#cfg-slack-channel-id").val("");
    $("#cfg-slack-webhook-url").val("");

    showSlackModeFields();
    resetEmailHtmlTemplate();
}

function confirmChannelAction(options, onConfirm) {
    showAppConfirm(options).done(onConfirm);
}

function disableChannel(channel) {
    if (!canWriteObject(channel)) {
        showAppError("You do not have permission to disable this channel.");
        return;
    }

    const channelName = channel.name || ("Channel #" + channel.id);
    confirmChannelAction({
        title: "Disable this channel?",
        message: "Disable channel \"" + channelName + "\"?\n\nThe channel will stop receiving notifications, but it will stay visible and can be enabled again.",
        confirmText: "Disable",
        confirmClass: "btn-warning",
    }, function () {
        apiPost("/api/channels/" + channel.id + "/disable", {}, function () {
            refreshChannels();
        });
    });
}

function enableChannel(channel) {
    if (!canWriteObject(channel)) {
        showAppError("You do not have permission to enable this channel.");
        return;
    }

    apiPost("/api/channels/" + channel.id + "/enable", {}, function () {
        refreshChannels();
    });
}

function deleteChannel(channel) {
    if (!canDeleteObject(channel)) {
        showAppError("You do not have permission to delete this channel.");
        return;
    }

    const channelName = channel.name || ("Channel #" + channel.id);
    confirmChannelAction({
        title: "Delete this channel?",
        message: "Delete channel \"" + channelName + "\"?\n\nThis will remove the channel from active channel lists and detach it from routes.\nHistorical alerts will be preserved.",
        confirmText: "Delete",
        confirmClass: "btn-danger",
    }, function () {
        apiDelete("/api/channels/" + channel.id, function () {
            if (Number(selectedChannelDetailsId) === Number(channel.id)) {
                selectedChannelDetailsId = null;
                renderChannelDetailsEmpty();
            }
            refreshChannels();
        });
    });
}

function testChannel(id) {
    const channel = channelsCache.find(function (item) {
        return Number(item.id) === Number(id);
    });
    if (channel && !canWriteObject(channel)) {
        showAppError("You do not have permission to test this channel.");
        return;
    }

    apiPost("/api/channels/" + id + "/test", {}, function (response) {
        showAppSuccess(JSON.stringify(response, null, 2));
    });
}

function resetChannelForm() {
    $("#channel-form-title").text("Create channel");
    $("#channel-id").val("");
    $("#channel-name").val("");
    $("#channel-config-json").val("{}");
    $("#channel-enabled").prop("checked", true);
    clearChannelFields();
    loadChannelTeams();
    showChannelFields();
}

function getChannelModeLabel(channel) {
    const config = channel.config || {};
    if (channel.channel_type === "mattermost") {
        return config.mode || (config.api_url ? "bot_api" : "webhook");
    }
    if (channel.channel_type === "slack") {
        if (config.mode) {
            return config.mode;
        }

        return (
            config.bot_token && config.channel_id
                ? "bot_api"
                : "webhook"
        );
    }

    if (
        ["webhook", "discord", "teams"].includes(
            channel.channel_type
        )
    ) {
        return "webhook";
    }
    if (channel.channel_type === "email") {
        return "email";
    }
    return "-";
}

function getChannelSearchText(channel) {
    return [
        channel.id,
        channel.group_slug,
        channel.team_name,
        channel.team_slug,
        channel.name,
        channel.channel_type,
        getChannelModeLabel(channel),
        getChannelSeverityLabel(channel),
        channel.enabled ? "enabled" : "disabled",
    ].join(" ").toLowerCase();
}

function getFilteredChannels() {
    const query = String($("#channels-search").val() || "").trim().toLowerCase();
    const type = String($("#channels-type-filter").val() || "");
    const status = String($("#channels-status-filter").val() || "");

    return channelsCache.filter(function (channel) {
        if (type && channel.channel_type !== type) {
            return false;
        }
        if (status === "enabled" && !channel.enabled) {
            return false;
        }
        if (status === "disabled" && channel.enabled) {
            return false;
        }
        if (!query) {
            return true;
        }
        return getChannelSearchText(channel).indexOf(query) !== -1;
    });
}

function renderChannelsSummary(channels) {
    channels = Array.isArray(channels) ? channels : [];
    const enabled = channels.filter(function (channel) {
        return !!channel.enabled;
    }).length;
    const webhooks = channels.filter(function (channel) {
        return ["slack", "webhook", "discord", "teams"].includes(channel.channel_type);
    }).length;

    $("#channels-summary-webhooks").text(webhooks);
    $("#channels-summary-total").text(channels.length);
    $("#channels-summary-enabled").text(enabled);
    $("#channels-summary-disabled").text(channels.length - enabled);
}

function renderChannelsCounter(filteredChannels, allChannels) {
    filteredChannels = Array.isArray(filteredChannels) ? filteredChannels : [];
    allChannels = Array.isArray(allChannels) ? allChannels : [];
    $("#channels-filtered-count").text(filteredChannels.length);
    $("#channels-total-count").text(allChannels.length);
}

function fillChannelTypeFilter(types) {
    const filter = $("#channels-type-filter");
    const selected = filter.val();
    filter.empty();
    filter.append($("<option>").val("").text("All types"));
    types.forEach(function (type) {
        filter.append($("<option>").val(type).text(type));
    });
    if (selected && types.includes(selected)) {
        filter.val(selected);
    }
}

function channelDetailsItem(label, value) {
    return $("<div>")
        .addClass("details-item")
        .append($("<div>").addClass("details-label").text(label))
        .append($("<div>").addClass("details-value").text(value || "-"));
}

function getSafeChannelConfigSummary(channel) {
    const config = channel.config || {};
    if (channel.channel_type === "mattermost") {
        return getChannelModeLabel(channel);
    }
    if (channel.channel_type === "email") {
        return "Assigned user profile email; " + (config.html_template ? "custom HTML template" : "default HTML template");
    }
    if (channel.channel_type === "slack") {
        const mode = getChannelModeLabel(channel);

        if (mode === "bot_api") {
            return (
                config.bot_token && config.channel_id
                    ? "Bot API configured"
                    : "Bot API incomplete"
            );
        }

        return (
            config.webhook_url
                ? "Webhook configured"
                : "Webhook missing"
        );
    }
    if (["webhook", "discord", "teams"].includes(channel.channel_type)) {
        return config.webhook_url ? "Webhook configured" : "Webhook missing";
    }
    if (channel.channel_type === "telegram") {
        return config.chat_id ? "Chat configured" : "Chat missing";
    }
    return "-";
}

function renderChannelDetails(channel) {
    selectedChannelDetailsId = channel.id;
    $("#channel-details-subtitle").text((channel.team_name || channel.team_slug || "-") + " / " + (channel.enabled ? "Enabled" : "Disabled"));

    const body = $("#channel-details-body");
    body.empty();
    body.append(
        $("<div>")
            .addClass("details-list")
            .append(channelDetailsItem("Name", channel.name))
            .append(channelDetailsItem("Group", channel.group_slug))
            .append(channelDetailsItem("Team", channel.team_name || channel.team_slug || "-"))
            .append(channelDetailsItem("Type", channel.channel_type))
            .append(channelDetailsItem("Mode", getChannelModeLabel(channel)))
            .append(channelDetailsItem("Severity filter", getChannelSeverityLabel(channel)))
            .append(channelDetailsItem("Status", channel.enabled ? "Enabled" : "Disabled"))
            .append(channelDetailsItem("Config", getSafeChannelConfigSummary(channel)))
    );

    const actions = $("<div>").addClass("details-actions");
    appendIconActionIfAllowed(actions, channel, {
        required: "write",
        icon: "fas fa-edit",
        label: "Edit channel",
        onClick: function () {
            editChannel(channel.id);
        },
    });
    appendIconActionIfAllowed(actions, channel, {
        required: "write",
        icon: "fas fa-paper-plane",
        label: "Test channel",
        onClick: function () {
            testChannel(channel.id);
        },
    });
    appendIconActionIfAllowed(actions, channel, {
        required: "write",
        icon: channel.enabled ? "fas fa-pause" : "fas fa-play",
        label: channel.enabled ? "Disable channel" : "Enable channel",
        className: channel.enabled ? "btn-warning" : "btn-success",
        onClick: function () {
            if (channel.enabled) {
                disableChannel(channel);
            } else {
                enableChannel(channel);
            }
        },
    });
    appendIconActionIfAllowed(actions, channel, {
        required: "delete",
        icon: "fas fa-trash-alt",
        label: "Delete channel",
        className: "btn-danger",
        onClick: function () {
            deleteChannel(channel);
        },
    });

    if (actions.children().length) {
        body.append(actions);
    }
}

function restoreChannelDetails() {
    const selected = channelsCache.find(function (channel) {
        return Number(channel.id) === Number(selectedChannelDetailsId);
    });
    if (selected) {
        renderChannelDetails(selected);
        return;
    }
    renderChannelDetailsEmpty();
}

function renderChannelDetailsEmpty() {
    selectedChannelDetailsId = null;
    $("#channel-details-subtitle").text("Select a channel");
    $("#channel-details-body").html("<p class=\"muted\">Click a channel name to inspect delivery type, team binding and safe configuration summary.</p>");
}

function openCreateChannelModal() {
    resetChannelForm();
    $("#channel-form-title").text("Create channel");
    const team = getSelectedChannelTeam();
    if (team && !canWriteChannelResourceForTeam(team)) {
        showAppError("Team manager or group editor role is required to create channels in this team.");
        return;
    }
    openAppModal("#channel-form-modal");
}

function getChannelNotifySeverities() {
    return $('input[name="notify_on_severities"]:checked').map(function () {
        return this.value;
    }).get();
}

function getChannelSeverityLabel(channel) {
    const config = channel.config || {};
    const severities = config.notify_on_severities || [];
    if (!severities.length) {
        return "All severities";
    }
    return severities.join(", ");
}

function setChannelNotifySeverities(severities) {
    const selected = new Set(severities || []);
    $('input[name="notify_on_severities"]').each(function () {
        $(this).prop("checked", selected.has(this.value));
    });
}

$(document).on("change", "#channel-group", function () {
    loadChannelTeams();
});
$(document).on("change", "#channel-type", showChannelFields);
$(document).on("change", "#cfg-mm-mode", showMattermostModeFields);
$(document).on("change", "#cfg-slack-mode", showSlackModeFields);
$(document).on("click", "#save-channel", saveChannel);
$(document).on("click", "#reset-channel-form", resetChannelForm);
$(document).on("click", "#reload-channels", function () {
    loadChannelGroups(refreshChannels);
});
$(document).on("click", "#reset-email-template", resetEmailHtmlTemplate);
$(document).on("input", "#channels-search", renderChannels);
$(document).on("change", "#channels-type-filter, #channels-status-filter", renderChannels);
$(document).on("click", "#open-channel-create-modal", openCreateChannelModal);
$(document).on("click", "#close-channel-form-modal", function () {
    closeAppModal("#channel-form-modal");
});
$(document).on("click", "#channel-form-modal", function (event) {
    if (event.target === this) {
        closeAppModal("#channel-form-modal");
    }
});
$(document).on("keydown", function (event) {
    if (event.key === "Escape" && $("#channel-form-modal").hasClass("is-open")) {
        closeAppModal("#channel-form-modal");
    }
});
$(document).on("click", "#format-channel-config-json", function () {
    formatJsonTextarea("#channel-config-json", {}, "Advanced JSON config");
});
