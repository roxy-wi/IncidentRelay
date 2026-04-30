let channelsCache = [];
let channelTeamsCache = [];
let selectedChannelDetailsId = null;

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

        fillChannelTypeFilter(types);
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
        return;
    }

    if (type === "voice_call") {
        $('[data-channel-config="voice_call"]').show();
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

    if (type === "voice_call") {
        config.call_on_severities = getVoiceCallSeverities();
        config.notification_rules = parseJsonInput("#cfg-voice-notification-rules", []);
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
    /*
     * Render filtered channels.
     */
    const tbody = $("#channels-table");
    const channels = getFilteredChannels();

    tbody.empty();
    renderChannelsCounter(channels, channelsCache);

    if (!channels.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>")
                    .attr("colspan", "7")
                    .addClass("channels-empty-cell")
                    .text("No channels")
            )
        );
        return;
    }

    channels.forEach(function (channel) {
        tbody.append(renderChannelRow(channel));
    });
}

function renderChannelRow(channel) {
    /*
     * Render one channel row.
     */
    const row = $("<tr>");
    const mode = getChannelModeLabel(channel);

    row.append(
        $("<td>")
            .append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("channel-name-button")
                    .text(channel.name || "-")
                    .on("click", function () {
                        renderChannelDetails(channel);
                    })
            )
            .append(
                $("<div>")
                    .addClass("channel-row-subtitle")
                    .text("Channel #" + channel.id)
            )
    );

    row.append($("<td>").text(channel.group_slug || "-"));
    row.append($("<td>").text(channel.team_slug || "-"));

    row.append(
        $("<td>").append(
            $("<span>")
                .addClass("channel-type-pill")
                .text(channel.channel_type || "-")
        )
    );

    row.append(
        $("<td>").append(
            $("<span>")
                .addClass("channel-mode-pill")
                .text(mode)
        )
    );

    row.append(
        $("<td>").append(
            $("<span>")
                .addClass("channel-status-pill")
                .addClass(channel.enabled ? "channel-status-enabled" : "channel-status-disabled")
                .text(channel.enabled ? "Enabled" : "Disabled")
        )
    );

    row.append($("<td>").addClass("actions-cell").append(renderChannelActions(channel)));

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
            closeChannelFormModal();
            resetChannelForm();
            refreshChannels();
        });
        return;
    }

    apiPost("/api/channels", payload, function () {
        closeChannelFormModal();
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
    openChannelFormModal();
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

    if (type === "voice_call") {
        const severities = config.call_on_severities || ["critical", "high"];

        $(".cfg-voice-severity").each(function () {
            $(this).prop("checked", severities.includes($(this).val()));
        });

        $("#cfg-voice-notification-rules").val(
            JSON.stringify(config.notification_rules || [], null, 2)
        );
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

    $(".cfg-voice-severity").prop("checked", false);
    $('.cfg-voice-severity[value="critical"]').prop("checked", true);
    $('.cfg-voice-severity[value="high"]').prop("checked", true);
    $("#cfg-voice-notification-rules").val("[]");
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
function getVoiceCallSeverities() {
    /*
     * Return selected severities for voice calls.
     */
    const severities = [];

    $(".cfg-voice-severity:checked").each(function () {
        severities.push($(this).val());
    });

    return severities;
}
function getChannelModeLabel(channel) {
    /*
     * Return safe display mode for channel.
     */
    const config = channel.config || {};

    if (channel.channel_type === "mattermost") {
        return config.mode || (config.api_url ? "bot_api" : "webhook");
    }

    if (channel.channel_type === "voice_call") {
        const severities = config.call_on_severities || [];
        return severities.length ? severities.join(", ") : "no severities";
    }

    if (["slack", "webhook", "discord", "teams"].includes(channel.channel_type)) {
        return "webhook";
    }

    if (channel.channel_type === "email") {
        return config.smtp_host ? "smtp" : "email";
    }

    return "-";
}


function getChannelSearchText(channel) {
    /*
     * Build searchable channel text.
     */
    return [
        channel.id,
        channel.group_slug,
        channel.team_slug,
        channel.name,
        channel.channel_type,
        getChannelModeLabel(channel),
        channel.enabled ? "enabled" : "disabled"
    ].join(" ").toLowerCase();
}


function getFilteredChannels() {
    /*
     * Apply client-side filters to channels cache.
     */
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
    /*
     * Render top summary cards.
     */
    channels = Array.isArray(channels) ? channels : [];

    const enabled = channels.filter(function (channel) {
        return !!channel.enabled;
    }).length;

    const voice = channels.filter(function (channel) {
        return channel.channel_type === "voice_call";
    }).length;

    $("#channels-summary-total").text(channels.length);
    $("#channels-summary-enabled").text(enabled);
    $("#channels-summary-disabled").text(channels.length - enabled);
    $("#channels-summary-voice").text(voice);
}


function renderChannelsCounter(filteredChannels, allChannels) {
    /*
     * Render "Showing X of Y channels" counter.
     */
    filteredChannels = Array.isArray(filteredChannels) ? filteredChannels : [];
    allChannels = Array.isArray(allChannels) ? allChannels : [];

    $("#channels-filtered-count").text(filteredChannels.length);
    $("#channels-total-count").text(allChannels.length);
}


function fillChannelTypeFilter(types) {
    /*
     * Fill channel type filter in table toolbar.
     */
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
    /*
     * Render one channel details item.
     */
    return $("<div>")
        .addClass("details-item")
        .append($("<div>").addClass("details-label").text(label))
        .append($("<div>").addClass("details-value").text(value || "-"));
}


function getSafeChannelConfigSummary(channel) {
    /*
     * Return safe config summary without secrets.
     */
    const config = channel.config || {};

    if (channel.channel_type === "mattermost") {
        return getChannelModeLabel(channel);
    }

    if (channel.channel_type === "voice_call") {
        return "Calls on: " + ((config.call_on_severities || []).join(", ") || "-");
    }

    if (channel.channel_type === "email") {
        return "Recipients: " + ((config.recipients || []).length || 0);
    }

    if (["slack", "webhook", "discord", "teams"].includes(channel.channel_type)) {
        return config.webhook_url ? "Webhook configured" : "Webhook missing";
    }

    if (channel.channel_type === "telegram") {
        return config.chat_id ? "Chat configured" : "Chat missing";
    }

    return "-";
}


function renderChannelDetails(channel) {
    /*
     * Render selected channel details.
     */
    selectedChannelDetailsId = channel.id;

    $("#channel-details-subtitle").text(
        (channel.team_slug || "-") + " / " + (channel.enabled ? "Enabled" : "Disabled")
    );

    const body = $("#channel-details-body");
    body.empty();

    body.append(
        $("<div>")
            .addClass("details-list")
            .append(channelDetailsItem("Name", channel.name))
            .append(channelDetailsItem("Group", channel.group_slug))
            .append(channelDetailsItem("Team", channel.team_slug))
            .append(channelDetailsItem("Type", channel.channel_type))
            .append(channelDetailsItem("Mode", getChannelModeLabel(channel)))
            .append(channelDetailsItem("Status", channel.enabled ? "Enabled" : "Disabled"))
            .append(channelDetailsItem("Config", getSafeChannelConfigSummary(channel)))
    );

    body.append(
        $("<div>")
            .addClass("details-actions")
            .append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("btn btn-small")
                    .text("Edit channel")
                    .on("click", function () {
                        editChannel(channel.id);
                    })
            )
            .append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("btn btn-small")
                    .text("Test")
                    .on("click", function () {
                        testChannel(channel.id);
                    })
            )
    );
}


function restoreChannelDetails() {
    /*
     * Restore selected channel details after reload.
     */
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
    /*
     * Render empty details state.
     */
    selectedChannelDetailsId = null;

    $("#channel-details-subtitle").text("Select a channel");
    $("#channel-details-body").html(
        '<div class="details-empty">' +
        'Click a channel name to inspect delivery type, team binding and safe configuration summary.' +
        '</div>'
    );
}
function openChannelFormModal() {
    /*
     * Open channel create/edit modal.
     */
    $("#channel-form-modal")
        .css("display", "flex")
        .addClass("is-open");

    $("body").addClass("modal-open");
}


function closeChannelFormModal() {
    /*
     * Close channel create/edit modal.
     */
    $("#channel-form-modal")
        .css("display", "none")
        .removeClass("is-open");

    $("body").removeClass("modal-open");
}


function openCreateChannelModal() {
    /*
     * Reset form and open create modal.
     */
    resetChannelForm();
    $("#channel-form-title").text("Create channel");
    openChannelFormModal();
}
$(document).on("input", "#channels-search", renderChannels);
$(document).on("change", "#channels-type-filter, #channels-status-filter", renderChannels);

$(document).on("click", "#open-channel-create-modal", openCreateChannelModal);
$(document).on("click", "#close-channel-form-modal", closeChannelFormModal);

$(document).on("click", "#channel-form-modal", function (event) {
    if (event.target === this) {
        closeChannelFormModal();
    }
});

$(document).on("keydown", function (event) {
    if (event.key === "Escape" && $("#channel-form-modal").hasClass("is-open")) {
        closeChannelFormModal();
    }
});
