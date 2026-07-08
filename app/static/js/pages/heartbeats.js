let heartbeatsCache = [];
let heartbeatTeamsCache = [];
let heartbeatRoutesCache = [];
let heartbeatServicesCache = [];
let selectedHeartbeatId = null;


function openHeartbeatModal(selector) {
    if (typeof openAppModal === "function") {
        openAppModal(selector);
        return;
    }

    $(selector)
        .removeClass("is-hidden")
        .addClass("is-open")
        .attr("aria-hidden", "false")
        .css("display", "flex");
}

function closeHeartbeatModal(selector) {
    if (typeof closeAppModal === "function") {
        closeAppModal(selector);
        return;
    }

    $(selector)
        .removeClass("is-open")
        .addClass("is-hidden")
        .attr("aria-hidden", "true")
        .css("display", "none");
}

function heartbeatPingCurl(url) {
    return [
        "curl -fsS -X POST '" + url + "' \\",
        "  -H 'Content-Type: application/json' \\",
        "  -d '{}'"
    ].join("\n");
}


function prettyHeartbeatJson(value) {
    const source = value === undefined || value === null || value === "" ? {} : value;

    try {
        return JSON.stringify(typeof source === "string" ? JSON.parse(source) : source, null, 2);
    } catch (error) {
        return "{}";
    }
}

function formatHeartbeatLabels() {
    if (typeof formatJsonTextarea === "function") {
        return formatJsonTextarea("#heartbeat-labels", {}, "Labels JSON");
    }

    try {
        const value = String($("#heartbeat-labels").val() || "{}").trim();
        $("#heartbeat-labels").val(JSON.stringify(value ? JSON.parse(value) : {}, null, 2));
        return true;
    } catch (error) {
        heartbeatToast("Labels JSON is invalid: " + error.message, "error");
        return false;
    }
}

function setupHeartbeatSlugAutofill() {
    if (window.AppSlug && typeof window.AppSlug.bind === "function") {
        window.AppSlug.bind("#heartbeat-name", "#heartbeat-slug", {
            manualWhenHasValue: true,
        });
    }
}

function resetHeartbeatSlugAutofill(item) {
    if (window.AppSlug && typeof window.AppSlug.reset === "function") {
        window.AppSlug.reset("#heartbeat-slug", {
            manual: !!item,
        });
        if (!item && typeof window.AppSlug.update === "function") {
            window.AppSlug.update("#heartbeat-name", "#heartbeat-slug", {force: true});
        }
    }
}

function initHeartbeatTimezoneSelect(value) {
    const timezone = value || (
        window.AppTimezones && typeof window.AppTimezones.getBrowserDefaultTimezone === "function"
            ? window.AppTimezones.getBrowserDefaultTimezone()
            : "UTC"
    );

    if (window.AppTimezones && typeof window.AppTimezones.initSelect === "function") {
        window.AppTimezones.initSelect("#heartbeat-timezone", timezone, "#heartbeat-form-modal");
        window.AppTimezones.setSelectValue("#heartbeat-timezone", timezone);
        return;
    }

    $("#heartbeat-timezone").val(timezone);
}

function getHeartbeatTimezoneValue() {
    if (window.AppTimezones && typeof window.AppTimezones.getSelectValue === "function") {
        return window.AppTimezones.getSelectValue("#heartbeat-timezone");
    }
    return $("#heartbeat-timezone").val() || "UTC";
}

function showHeartbeatTokenModal(url) {
    $("#heartbeat-token-url").val(url || "");
    $("#heartbeat-token-curl").val(url ? heartbeatPingCurl(url) : "");
    openHeartbeatModal("#heartbeat-token-modal");
}

function heartbeatToast(message, type) {
    if (typeof showToast === "function") {
        showToast(message, type);
        return;
    }
    if (type === "error") {
        window.alert(message);
    }
}

function heartbeatEscape(value) {
    return String(value === undefined || value === null ? "" : value);
}

function heartbeatStatusBadge(status) {
    const label = status || "unknown";
    let cls = "badge-info";
    if (label === "ok") { cls = "badge-success"; }
    if (label === "overdue") { cls = "badge-danger"; }
    if (label === "paused") { cls = "badge-muted"; }
    if (label === "new") { cls = "badge-warning"; }
    return $("<span>").addClass("badge " + cls).text(label.replace(/_/g, " "));
}

function heartbeatModeText(item) {
    if (item.mode === "scheduled") {
        let text = (item.schedule_kind || "scheduled") + " at " + (item.schedule_time || "--:--");
        if (item.schedule_kind === "weekly") {
            const names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
            text += " " + (names[item.schedule_weekday] || "");
        }
        if (item.schedule_kind === "monthly") {
            text += " day " + (item.schedule_monthday || 1);
        }
        return text + " " + (item.timezone || "UTC");
    }
    return "every " + (item.expected_interval_seconds || 0) + "s + " + (item.grace_period_seconds || 0) + "s grace";
}

function heartbeatSelectedTeamId() {
    const globalTeam = Number($("#global-team-filter").val() || 0);
    if (globalTeam) {
        return globalTeam;
    }
    return 0;
}

function heartbeatListQuery() {
    const teamId = heartbeatSelectedTeamId();
    return teamId ? "?team_id=" + encodeURIComponent(teamId) : "";
}

function loadHeartbeats() {
    apiGet("/api/teams", function (teams) {
        heartbeatTeamsCache = Array.isArray(teams) ? teams : [];
        apiGet("/api/routes", function (routes) {
            heartbeatRoutesCache = (Array.isArray(routes) ? routes : []).filter(function (route) {
                return route.source === "heartbeat";
            });
            apiGet("/api/services", function (services) {
                heartbeatServicesCache = Array.isArray(services) ? services : [];
                apiGet("/api/heartbeats" + heartbeatListQuery(), function (items) {
                    heartbeatsCache = Array.isArray(items) ? items : [];
                    renderHeartbeats();
                });
            });
        });
    });
}

function renderHeartbeatsSummary(items) {
    const total = items.length;
    const ok = items.filter(function (item) { return item.status === "ok"; }).length;
    const overdue = items.filter(function (item) { return item.status === "overdue"; }).length;
    const paused = items.filter(function (item) { return item.status === "paused"; }).length;
    $("#heartbeats-summary-total").text(total);
    $("#heartbeats-summary-ok").text(ok);
    $("#heartbeats-summary-overdue").text(overdue);
    $("#heartbeats-summary-paused").text(paused);
}

function filteredHeartbeats() {
    const query = String($("#heartbeats-search").val() || "").trim().toLowerCase();
    const status = $("#heartbeats-status-filter").val();

    return heartbeatsCache.filter(function (item) {
        if (status && item.status !== status) {
            return false;
        }
        if (!query) {
            return true;
        }
        return [
            item.name,
            item.slug,
            item.team_name,
            item.team_slug,
            item.service_name,
            item.route_name,
            item.status
        ].join(" ").toLowerCase().indexOf(query) !== -1;
    });
}

function renderHeartbeats() {
    const items = filteredHeartbeats();
    renderHeartbeatsSummary(heartbeatsCache);
    $("#heartbeats-total-count").text(heartbeatsCache.length);
    $("#heartbeats-filtered-count").text(items.length);

    const tbody = $("#heartbeats-table");
    tbody.empty();

    if (!items.length) {
        tbody.append($("<tr>").append($("<td>").attr("colspan", 9).addClass("empty-cell").text("No heartbeats found")));
        return;
    }

    items.forEach(function (item) {
        const row = $("<tr>");
        row.append($("<td>").append(
            $("<button>")
                .attr("type", "button")
                .addClass("link-button item-title")
                .text(item.name)
                .on("click", function () {
                    openHeartbeatDetails(item.id);
                }),
            $("<div>").addClass("item-subtitle").text(item.slug)
        ));
        row.append($("<td>").text(item.team_name || item.team_slug || "-"));
        row.append($("<td>").text(item.service_name || "-"));
        row.append($("<td>").append(heartbeatStatusBadge(item.status)));
        row.append($("<td>").text(heartbeatModeText(item)));
        row.append($("<td>").text(formatDateTimeMinutes(item.last_seen_at) || "-"));
        row.append($("<td>").text(formatDateTimeMinutes(item.deadline_at) || "-"));
        row.append($("<td>").text((item.priority_slug || "p2").toUpperCase()));

        const actions = $("<td>").addClass("actions-cell");
        actions.append(renderHeartbeatActions(item));
        row.append(actions);
        tbody.append(row);
    });
}


function renderHeartbeatActions(item) {
    if (typeof makeActionMenu === "function") {
        return makeActionMenu({
            object: item,
            items: [
                {
                    label: "Details",
                    icon: "fas fa-eye",
                    onClick: function () {
                        openHeartbeatDetails(item.id);
                    }
                },
                {
                    label: "Edit",
                    icon: "fas fa-edit",
                    required: "write",
                    denyMessage: "Team manager role is required to edit this heartbeat.",
                    onClick: function () {
                        openHeartbeatForm(item);
                    }
                },
                {
                    label: item.status === "paused" ? "Resume" : "Pause",
                    icon: item.status === "paused" ? "fas fa-play" : "fas fa-pause",
                    required: "write",
                    denyMessage: "Team manager role is required to pause or resume this heartbeat.",
                    onClick: function () {
                        selectedHeartbeatId = item.id;
                        if (item.status === "paused") {
                            resumeHeartbeatById(item.id, false);
                        } else {
                            pauseHeartbeatById(item.id, false);
                        }
                    }
                },
                {
                    label: "Regenerate token",
                    icon: "fas fa-key",
                    required: "write",
                    danger: true,
                    denyMessage: "Team manager role is required to regenerate heartbeat tokens.",
                    onClick: function () {
                        selectedHeartbeatId = item.id;
                        regenerateHeartbeatToken();
                    }
                }
            ]
        });
    }

    return $("<button>").addClass("btn btn-small").text("Details").on("click", function () {
        openHeartbeatDetails(item.id);
    });
}

function fillHeartbeatSelects(selected) {
    const teamSelect = $("#heartbeat-team");
    const routeSelect = $("#heartbeat-route");
    const serviceSelect = $("#heartbeat-service");
    const selectedTeamId = Number((selected && selected.team_id) || heartbeatSelectedTeamId() || 0);

    teamSelect.empty();
    heartbeatTeamsCache.forEach(function (team) {
        teamSelect.append($("<option>").val(team.id).text(team.name || team.slug || team.id));
    });
    if (selectedTeamId) {
        teamSelect.val(String(selectedTeamId));
    }

    const currentTeamId = Number(teamSelect.val() || 0);
    routeSelect.empty();
    heartbeatRoutesCache.filter(function (route) {
        return !currentTeamId || Number(route.team_id) === currentTeamId;
    }).forEach(function (route) {
        routeSelect.append($("<option>").val(route.id).text(route.name || route.id));
    });

    serviceSelect.empty();
    serviceSelect.append($("<option>").val("").text("No service"));
    heartbeatServicesCache.filter(function (service) {
        return !currentTeamId || Number(service.team_id) === currentTeamId;
    }).forEach(function (service) {
        serviceSelect.append($("<option>").val(service.id).text(service.name || service.slug || service.id));
    });

    if (selected) {
        routeSelect.val(String(selected.route_id || ""));
        serviceSelect.val(String(selected.service_id || ""));
    }
}

function updateHeartbeatScheduleFields() {
    const mode = $("#heartbeat-mode").val();
    const kind = $("#heartbeat-schedule-kind").val();
    $(".heartbeat-interval-field").toggleClass("is-hidden", mode !== "interval");
    $(".heartbeat-scheduled-field").toggleClass("is-hidden", mode !== "scheduled");
    $(".heartbeat-weekly-field").toggleClass("is-hidden", mode !== "scheduled" || kind !== "weekly");
    $(".heartbeat-monthly-field").toggleClass("is-hidden", mode !== "scheduled" || kind !== "monthly");
}

function openHeartbeatForm(item) {
    selectedHeartbeatId = item ? item.id : null;
    $("#heartbeat-form-title").text(item ? "Edit heartbeat" : "New heartbeat");
    $("#heartbeat-id").val(item ? item.id : "");
    fillHeartbeatSelects(item);

    $("#heartbeat-name").val(item ? item.name : "");
    $("#heartbeat-slug").val(item ? item.slug : "");
    resetHeartbeatSlugAutofill(item);
    $("#heartbeat-description").val(item ? item.description || "" : "");
    $("#heartbeat-mode").val(item ? item.mode : "interval");
    $("#heartbeat-interval").val(item ? item.expected_interval_seconds || 300 : 300);
    $("#heartbeat-grace").val(item ? item.grace_period_seconds || 300 : 300);
    $("#heartbeat-schedule-kind").val(item ? item.schedule_kind || "daily" : "daily");
    $("#heartbeat-schedule-time").val(item ? item.schedule_time || "03:00" : "03:00");
    $("#heartbeat-schedule-weekday").val(item ? String(item.schedule_weekday || 0) : "0");
    $("#heartbeat-schedule-monthday").val(item ? item.schedule_monthday || 1 : 1);
    initHeartbeatTimezoneSelect(item ? item.timezone || "UTC" : null);
    $("#heartbeat-severity").val(item ? item.severity || "critical" : "critical");
    $("#heartbeat-priority").val(item ? item.priority_slug || "p2" : "p2");
    $("#heartbeat-enabled").prop("checked", item ? !!item.enabled : true);
    $("#heartbeat-auto-resolve").prop("checked", item ? !!item.auto_resolve : true);
    $("#heartbeat-labels").val(prettyHeartbeatJson(item ? item.labels || {} : {}));
    $("#delete-heartbeat").toggleClass("is-hidden", !item);
    updateHeartbeatScheduleFields();
    openHeartbeatModal("#heartbeat-form-modal");
}

function closeHeartbeatForm() {
    closeHeartbeatModal("#heartbeat-form-modal");
}

function heartbeatPayloadFromForm() {
    let labels = {};
    const labelsText = String($("#heartbeat-labels").val() || "{}").trim();
    if (labelsText) {
        labels = JSON.parse(labelsText);
    }

    const mode = $("#heartbeat-mode").val();
    const payload = {
        team_id: Number($("#heartbeat-team").val()),
        route_id: Number($("#heartbeat-route").val()),
        service_id: $("#heartbeat-service").val() ? Number($("#heartbeat-service").val()) : null,
        name: $("#heartbeat-name").val(),
        slug: $("#heartbeat-slug").val(),
        description: $("#heartbeat-description").val() || null,
        mode: mode,
        expected_interval_seconds: mode === "interval" ? Number($("#heartbeat-interval").val()) : null,
        grace_period_seconds: Number($("#heartbeat-grace").val()),
        schedule_kind: mode === "scheduled" ? $("#heartbeat-schedule-kind").val() : null,
        schedule_time: mode === "scheduled" ? $("#heartbeat-schedule-time").val() : null,
        schedule_weekday: mode === "scheduled" && $("#heartbeat-schedule-kind").val() === "weekly" ? Number($("#heartbeat-schedule-weekday").val()) : null,
        schedule_monthday: mode === "scheduled" && $("#heartbeat-schedule-kind").val() === "monthly" ? Number($("#heartbeat-schedule-monthday").val()) : null,
        timezone: mode === "scheduled" ? getHeartbeatTimezoneValue() : "UTC",
        severity: $("#heartbeat-severity").val(),
        priority_slug: $("#heartbeat-priority").val(),
        enabled: $("#heartbeat-enabled").is(":checked"),
        auto_resolve: $("#heartbeat-auto-resolve").is(":checked"),
        labels: labels,
        metadata: {}
    };
    return payload;
}

function saveHeartbeat() {
    let payload;
    try {
        payload = heartbeatPayloadFromForm();
    } catch (error) {
        heartbeatToast("Labels JSON is invalid: " + error.message, "error");
        return;
    }

    const id = $("#heartbeat-id").val();
    if (id) {
        apiPut("/api/heartbeats/" + id, payload, function () {
            closeHeartbeatForm();
            loadHeartbeats();
        });
        return;
    }

    apiPost("/api/heartbeats", payload, function (item) {
        closeHeartbeatForm();
        loadHeartbeats();
        if (item.ping_url) {
            showHeartbeatTokenModal(item.ping_url);
        }
    });
}

function deleteHeartbeat() {
    const id = $("#heartbeat-id").val();
    if (!id) { return; }
    if (!window.confirm("Delete this heartbeat?")) { return; }
    apiDelete("/api/heartbeats/" + id, function () {
        closeHeartbeatForm();
        loadHeartbeats();
    });
}

function renderHeartbeatDetails(item) {
    const body = $("#heartbeat-details-body");
    body.empty();
    const curl = item.ping_url_hint ? "curl -fsS \"" + item.ping_url_hint + "\"" : "Ping URL token is hidden. Regenerate token to view a new URL.";
    const fields = [
        ["Status", item.status],
        ["Team", item.team_name || item.team_slug || "-"],
        ["Service", item.service_name || "-"],
        ["Route", item.route_name || item.route_id || "-"],
        ["Mode", heartbeatModeText(item)],
        ["Last ping", formatDateTimeMinutes(item.last_seen_at)],
        ["Next expected", formatDateTimeMinutes(item.next_expected_at)],
        ["Deadline", formatDateTimeMinutes(item.deadline_at)],
        ["Current alert group", item.current_alert_group_id || "-"],
        ["Curl", curl]
    ];

    fields.forEach(function (field) {
        body.append(
            $("<div>").addClass("detail-item").append(
                $("<div>").addClass("detail-label").text(field[0]),
                $("<div>").addClass("detail-value").text(field[1] || "-")
            )
        );
    });

    const tbody = $("#heartbeat-pings-table");
    tbody.empty();
    const pings = Array.isArray(item.pings) ? item.pings : [];
    if (!pings.length) {
        tbody.append($("<tr>").append($("<td>").attr("colspan", 4).addClass("empty-cell").text("No events")));
    } else {
        pings.forEach(function (ping) {
            tbody.append(
                $("<tr>")
                    .append($("<td>").text(formatDateTimeMinutes(ping.received_at)))
                    .append($("<td>").text(ping.event_type || "ping"))
                    .append($("<td>").text((ping.status_before || "-") + " → " + (ping.status_after || "-")))
                    .append($("<td>").text(ping.message || "-"))
            );
        });
    }
}

function openHeartbeatDetails(id, afterOpen) {
    selectedHeartbeatId = id;
    apiGet("/api/heartbeats/" + id, function (item) {
        $("#heartbeat-details-title").text(item.name);
        $("#heartbeat-details-subtitle").text(item.slug + " · " + heartbeatModeText(item));
        renderHeartbeatDetails(item);
        $("#heartbeat-details-pause").toggleClass("is-hidden", item.status === "paused");
        $("#heartbeat-details-resume").toggleClass("is-hidden", item.status !== "paused");
        openHeartbeatModal("#heartbeat-details-modal");
        if (typeof afterOpen === "function") {
            afterOpen(item);
        }
    });
}

function closeHeartbeatDetails() {
    closeHeartbeatModal("#heartbeat-details-modal");
}

function selectedHeartbeatFromCache() {
    const id = Number(selectedHeartbeatId || 0);
    return heartbeatsCache.find(function (item) { return Number(item.id) === id; });
}

function regenerateHeartbeatToken() {
    if (!selectedHeartbeatId) { return; }

    const run = function () {
        apiPost("/api/heartbeats/" + selectedHeartbeatId + "/regenerate-token", {}, function (item) {
            loadHeartbeats();
            if (item.ping_url) {
                showHeartbeatTokenModal(item.ping_url);
            }
        });
    };

    if (typeof showAppConfirm === "function") {
        showAppConfirm({
            type: "warning",
            title: "Regenerate heartbeat token?",
            subtitle: "Existing ping URLs will stop working immediately.",
            message: "All producers using the current URL must be updated with the new token. Continue only if you are ready to replace the old ping URL.",
            confirmText: "Regenerate token",
            confirmClass: "btn-danger",
            cancelText: "Cancel"
        }).done(run);
        return;
    }

    if (window.confirm("Regenerate heartbeat token? Existing ping URLs will stop working immediately.")) {
        run();
    }
}

function pauseHeartbeatById(id, showDetails) {
    if (!id) { return; }
    apiPost("/api/heartbeats/" + id + "/pause", {}, function () {
        if (showDetails) {
            openHeartbeatDetails(id);
        }
        loadHeartbeats();
    });
}

function resumeHeartbeatById(id, showDetails) {
    if (!id) { return; }
    apiPost("/api/heartbeats/" + id + "/resume", {}, function () {
        if (showDetails) {
            openHeartbeatDetails(id);
        }
        loadHeartbeats();
    });
}

function pauseSelectedHeartbeat() {
    pauseHeartbeatById(selectedHeartbeatId, true);
}

function resumeSelectedHeartbeat() {
    resumeHeartbeatById(selectedHeartbeatId, true);
}

function copyHeartbeatText(selector, message) {
    const el = document.querySelector(selector);
    if (!el) { return; }
    el.select();
    document.execCommand("copy");
    heartbeatToast(message, "success");
}

function copyHeartbeatTokenUrl() {
    copyHeartbeatText("#heartbeat-token-url", "Ping URL copied");
}

function copyHeartbeatTokenCurl() {
    copyHeartbeatText("#heartbeat-token-curl", "Curl command copied");
}

$(document).on("click", "#reload-heartbeats", loadHeartbeats);
$(document).on("input", "#heartbeats-search", renderHeartbeats);
$(document).on("change", "#heartbeats-status-filter", renderHeartbeats);
$(document).on("click", "#open-heartbeat-create-modal", function () { openHeartbeatForm(null); });
$(document).on("click", "#close-heartbeat-form-modal, #cancel-heartbeat-form", closeHeartbeatForm);
$(document).on("click", "#save-heartbeat", saveHeartbeat);
$(document).on("click", "#delete-heartbeat", deleteHeartbeat);
$(document).on("change", "#heartbeat-team", function () { fillHeartbeatSelects(null); });
$(document).on("change", "#heartbeat-mode, #heartbeat-schedule-kind", updateHeartbeatScheduleFields);
$(document).on("click", "#close-heartbeat-details-modal", closeHeartbeatDetails);
$(document).on("click", "#heartbeat-details-edit", function () {
    const item = selectedHeartbeatFromCache();
    closeHeartbeatDetails();
    openHeartbeatForm(item);
});
$(document).on("click", "#heartbeat-details-regenerate-token", regenerateHeartbeatToken);
$(document).on("click", "#heartbeat-details-pause", pauseSelectedHeartbeat);
$(document).on("click", "#heartbeat-details-resume", resumeSelectedHeartbeat);
$(document).on("click", "#run-heartbeat-overdue-check", function () {
    apiPost("/api/heartbeats/check-overdue", {}, function () {
        loadHeartbeats();
    });
});
$(document).on("click", "#close-heartbeat-token-modal", function () { closeHeartbeatModal("#heartbeat-token-modal"); });
$(document).on("click", "#copy-heartbeat-token-url", copyHeartbeatTokenUrl);
$(document).on("click", "#copy-heartbeat-token-curl", copyHeartbeatTokenCurl);

$(function () {
    setupHeartbeatSlugAutofill();
});
$(document).on("click", "#format-heartbeat-labels", formatHeartbeatLabels);
