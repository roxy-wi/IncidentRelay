/* Configuration, discovery and review share one editor; no duplicate resource dialogs. */
let directorySyncOptions = null;
let directorySyncSource = null;
let directorySyncVersion = 0;
let directorySyncTimer = null;
let directorySyncDirty = false;
let directorySyncOpen = false;
let directorySyncOpener = null;
let directorySyncSaving = false;
const directorySyncPath = "/api/admin/directory-sync";
const directorySyncMappingKeys = ["team_fields", "detail_fields", "team_filter", "members", "responsible", "schedules", "shift_fields", "replacements", "user_fields", "current_fields", "team_matches", "group_role", "member_role", "responsible_role", "user_fetch", "current_fetch", "timeout_seconds", "current_max_age_seconds"];

function dsText(key) { return i18n.t("ds." + key); }

function dsError(xhr) {
    $("#ds-status").text(xhr.responseJSON?.message || dsText("failed"));
    showApiError(xhr);
}

function loadDirectorySync() {
    apiGet(directorySyncPath + "/options", function (data) { directorySyncOptions = data; });
    apiGet(directorySyncPath, function (sources) {
        const body = $("#ds-list").empty();
        sources.forEach(source => {
            const row = $("<tr>");
            $("<td>").text(source.name).appendTo(row);
            $("<td>").text(source.group_name).appendTo(row);
            $("<td>").text(source.last_error || source.current_error || (source.pending_mode || source.running ? dsText("queued") : dsText(source.enabled ? "enabled" : "paused"))).appendTo(row);
            $("<td>").text(source.last_success_at || "—").appendTo(row);
            $("<td>").append($("<button>", {type: "button", class: "btn", text: dsText("configure")}).on("click", () => editDirectorySync(source.id))).appendTo(row);
            body.append(row);
        });
        if (!sources.length) body.append($("<tr>").append($("<td>", {colspan: 5, text: dsText("empty")})));
    });
}

function editDirectorySync(id) {
    const version = ++directorySyncVersion;
    apiGet(directorySyncPath + "/" + id, source => {
        if (version === directorySyncVersion) openDirectorySync(source);
    }, xhr => { if (version === directorySyncVersion) dsError(xhr); });
}

function closeDirectorySync() {
    const wasOpen = directorySyncOpen;
    directorySyncVersion += 1;
    clearTimeout(directorySyncTimer);
    directorySyncSource = null;
    directorySyncOpen = false;
    directorySyncSaving = false;
    $("#ds-headers").val("");
    setAppModalSaving("#ds-editor", false);
    closeAppModal("#ds-editor");
    if (wasOpen) {
        if (directorySyncOpener && document.body.contains(directorySyncOpener)) directorySyncOpener.focus();
        else $("#ds-new").trigger("focus");
    }
    directorySyncOpener = null;
}

function openDirectorySync(source) {
    if (!directorySyncOptions) return;
    if (!directorySyncOpen) directorySyncOpener = document.activeElement;
    directorySyncVersion += 1;
    clearTimeout(directorySyncTimer);
    directorySyncOpen = true;
    directorySyncSaving = false;
    setAppModalSaving("#ds-editor", false);
    directorySyncSource = source;
    directorySyncDirty = false;
    const config = source ? source.config : directorySyncOptions.preset;
    $("#ds-headers").val("");
    $("#ds-editor-title").text(source ? source.name : dsText("new"));
    $("#ds-name").val(source?.name || "");
    const groups = $("#ds-group").empty().prop("disabled", Boolean(source));
    directorySyncOptions.groups.forEach(group => groups.append($("<option>", {value: group.id, text: group.name})));
    if (source) groups.val(source.group_id);
    $("#ds-url").val(config.base_url);
    $("#ds-network").val(config.private_network_policy);
    $("#ds-operations").val(JSON.stringify(config.operations, null, 2));
    const mapping = {};
    directorySyncMappingKeys.forEach(key => { mapping[key] = config[key]; });
    $("#ds-mapping").val(JSON.stringify(mapping, null, 2));
    $("#ds-interval").val(config.interval_seconds);
    $("#ds-current-interval").val(config.current_interval_seconds);
    $("#ds-horizon").val(config.horizon_months);
    $("#ds-authority").val(config.membership_authority);
    $("#ds-editable").prop("checked", config.editable);
    $("#ds-overwrite").prop("checked", config.overwrite_existing);
    $("#ds-delete").prop("checked", config.delete_missing);
    $("#ds-enabled").prop("checked", Boolean(source?.enabled));
    $("#ds-sample-output").empty().prop("hidden", true);
    $("#ds-team-matches").empty();
    dsRenderResult(source);
    openAppModal("#ds-editor");
    $("#ds-editor .app-modal-body").scrollTop(0);
    $("#ds-name").trigger("focus");
    if (source?.pending_mode || source?.running) dsPoll(directorySyncVersion, source.id);
}

function dsRenderResult(source) {
    const busy = directorySyncSaving || Boolean(source?.pending_mode || source?.running);
    let enabledBlocker = "";
    if (busy) enabledBlocker = dsText("enabled_wait");
    else if (!source) enabledBlocker = dsText("enabled_save_first");
    else if (!source.approved) enabledBlocker = dsText("enabled_apply_first");
    $("#ds-enabled").prop("disabled", Boolean(enabledBlocker));
    $("#ds-enabled-label").attr("title", enabledBlocker || null);
    $("#ds-enabled-hint").text(enabledBlocker).prop("hidden", !enabledBlocker);
    if (source?.preview_result?.samples) $("#ds-sample-output").text(JSON.stringify(source.preview_result.samples, null, 2)).prop("hidden", false);
    $("#ds-status").text(source?.last_error || source?.current_error || (source?.pending_mode || source?.running ? dsText("queued") : ""));
    $("#ds-save").prop("disabled", busy);
    $("#ds-apply").prop("disabled", !source?.preview_token || directorySyncDirty || busy);
    $("#ds-sample, #ds-preview").prop("disabled", !source || busy);
    $("#ds-run").prop("disabled", !source?.approved || busy);
    const body = $("#ds-preview-table").empty();
    (source?.preview_result?.changes || []).forEach(change => {
        const row = $("<tr>");
        [change.kind, change.label || change.external_id, change.action, JSON.stringify(change.fields)].forEach(value => $("<td>").text(value).appendTo(row));
        body.append(row);
    });
    if (source?.preview_result?.team_catalog && !directorySyncDirty) {
        const matches = $("#ds-team-matches").empty();
        source.preview_result.team_catalog.forEach(team => {
            const select = $("<select>").addClass("input").append($("<option>", {value: "", text: dsText("automatic_match")}));
            directorySyncOptions.teams.filter(local => local.group_id === source.group_id).forEach(local =>
                select.append($("<option>", {value: local.id, text: local.name})));
            select.val(source.config.team_matches[team.id] || "");
            select.on("change", () => {
                try {
                    const mapping = JSON.parse($("#ds-mapping").val());
                    mapping.team_matches = mapping.team_matches || {};
                    if (select.val()) mapping.team_matches[team.id] = Number(select.val());
                    else delete mapping.team_matches[team.id];
                    $("#ds-mapping").val(JSON.stringify(mapping, null, 2)).trigger("input");
                } catch (_error) { $("#ds-status").text(dsText("invalid_json")); }
            });
            matches.append($("<div>").addClass("form-group").append($("<label>").text(team.name + " (" + team.id + ")")).append(select));
        });
    }
}

function dsPoll(version, id) {
    clearTimeout(directorySyncTimer);
    directorySyncTimer = setTimeout(() => {
        if (version !== directorySyncVersion || location.pathname !== "/admin/directory-sync") return;
        apiGet(directorySyncPath + "/" + id, data => {
            if (version !== directorySyncVersion) return;
            directorySyncSource = data;
            dsRenderResult(data);
            if (data.pending_mode || data.running) dsPoll(version, id);
            else {
                if (!data.last_error) $("#ds-status").text(dsText("complete"));
                loadDirectorySync();
            }
        }, xhr => { if (version === directorySyncVersion) dsError(xhr); });
    }, 1500);
}

function dsQueue(action) {
    if (!directorySyncSource || directorySyncSaving) return;
    if (directorySyncDirty) { $("#ds-status").text(dsText("save_first")); return; }
    const version = directorySyncVersion;
    directorySyncSaving = true;
    setAppModalSaving("#ds-editor", true);
    dsRenderResult(directorySyncSource);
    apiPost(directorySyncPath + "/" + directorySyncSource.id + "/" + action,
        {revision: directorySyncSource.revision, preview_token: directorySyncSource.preview_token}, data => {
            if (version !== directorySyncVersion) return;
            directorySyncSaving = false;
            setAppModalSaving("#ds-editor", false);
            directorySyncSource = data;
            dsRenderResult(data);
            dsPoll(version, data.id);
        }, xhr => dsWriteError(version, xhr));
}

function dsWriteError(version, xhr) {
    if (version !== directorySyncVersion) return;
    directorySyncSaving = false;
    setAppModalSaving("#ds-editor", false);
    dsRenderResult(directorySyncSource);
    dsError(xhr);
}

$(document).on("click", "#ds-new", () => openDirectorySync(null));
$(document).on("click", "#ds-reload", loadDirectorySync);
$(document).on("click", "#ds-close, #ds-close-footer, #ds-editor", function (event) {
    if (this.id === "ds-editor" && event.target !== this) return;
    if (!directorySyncSaving) closeDirectorySync();
});
$(document).on("keydown", function (event) {
    if (!directorySyncOpen) return;
    // Shared modal handling closes the topmost dialog before this handler runs.
    if (event.key === "Escape" && !$("#ds-editor").hasClass("is-open")) closeDirectorySync();
    if (event.key === "Tab" && $("#ds-editor").hasClass("is-open") && !$("#app-dialog-modal").hasClass("is-open")) {
        const controls = $("#ds-editor").find("button, input, select, textarea").filter(":visible:not(:disabled)");
        const first = controls[0], last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
});
$(window).on("pagehide", closeDirectorySync);
$(document).on("input change", "#ds-form input, #ds-form select, #ds-form textarea", () => {
    directorySyncDirty = true;
    $("#ds-apply").prop("disabled", true);
});
$(document).on("click", "#ds-preview", () => dsQueue("preview"));
$(document).on("click", "#ds-apply", () => dsQueue("apply"));
$(document).on("click", "#ds-run", () => dsQueue("run"));
$(document).on("click", "#ds-sample", () => {
    if (!directorySyncSource || directorySyncDirty) { $("#ds-status").text(dsText("save_first")); return; }
    const version = directorySyncVersion;
    apiPost(directorySyncPath + "/" + directorySyncSource.id + "/sample", {}, data => {
        if (version !== directorySyncVersion) return;
        $("#ds-sample-output").text(JSON.stringify(data.samples, null, 2)).prop("hidden", false);
    }, xhr => { if (version === directorySyncVersion) dsError(xhr); });
});
$(document).on("submit", "#ds-form", function (event) {
    event.preventDefault();
    if (directorySyncSaving) return;
    let payload;
    try {
        const config = {...(directorySyncSource?.config || directorySyncOptions.preset), ...JSON.parse($("#ds-mapping").val()),
            operations: JSON.parse($("#ds-operations").val()), base_url: $("#ds-url").val(),
            private_network_policy: $("#ds-network").val(), interval_seconds: Number($("#ds-interval").val()),
            current_interval_seconds: Number($("#ds-current-interval").val()), horizon_months: Number($("#ds-horizon").val()),
            membership_authority: $("#ds-authority").val(), editable: $("#ds-editable").prop("checked"),
            overwrite_existing: $("#ds-overwrite").prop("checked"), delete_missing: $("#ds-delete").prop("checked")};
        payload = {name: $("#ds-name").val(), group_id: Number($("#ds-group").val()), config,
            enabled: $("#ds-enabled").prop("checked"), revision: directorySyncSource?.revision};
        if ($("#ds-headers").val().trim()) payload.headers = JSON.parse($("#ds-headers").val());
    } catch (_error) { $("#ds-status").text(dsText("invalid_json")); return; }
    const version = directorySyncVersion;
    directorySyncSaving = true;
    setAppModalSaving("#ds-editor", true);
    dsRenderResult(directorySyncSource);
    apiRequest(directorySyncSource ? "PUT" : "POST", directorySyncPath + (directorySyncSource ? "/" + directorySyncSource.id : ""), payload, data => {
        if (version !== directorySyncVersion) return;
        openDirectorySync(data);
        $("#ds-status").text(dsText("saved"));
        loadDirectorySync();
    }, xhr => dsWriteError(version, xhr));
});
