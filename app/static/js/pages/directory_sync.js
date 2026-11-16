/* Configuration, discovery and review share one editor; no duplicate resource dialogs. */
let directorySyncOptions = null;
let directorySyncSource = null;
let directorySyncVersion = 0;
let directorySyncTimer = null;
let directorySyncPreviewTimer = null;
let directorySyncDirty = false;
let directorySyncOpen = false;
let directorySyncOpener = null;
let directorySyncSaving = false;
let directorySyncAction = null;
let directorySyncListVersion = 0;
const directorySyncListWrites = new Set();
const directorySyncPath = "/api/admin/directory-sync";
const directorySyncMappingKeys = ["team_fields", "detail_fields", "team_filter", "members", "responsible", "schedules", "shift_fields", "replacements", "user_fields", "current_fields", "team_matches", "group_role", "member_role", "responsible_role", "user_fetch", "current_fetch", "timeout_seconds", "current_max_age_seconds"];

function dsText(key) { return i18n.t("ds." + key); }

function dsStatus(message, busy = false) {
    AppLoading.clear("#ds-status");
    if (busy) AppLoading.showBlock("#ds-status", message, {compact: true});
    else $("#ds-status").text(message);
}

function dsTime(value) {
    if (!value) return "—";
    return $("<time>", {datetime: value, text: formatDateTime(value),
        title: formatBrowserDate(value, "dateTime", {timeZoneName: "short"})});
}

function dsOperation(source) {
    return directorySyncAction || source?.pending_mode || (source?.running ? "run" : null);
}

function dsOperationText(source, action) {
    const queued = !directorySyncAction && source?.pending_mode && !source.running;
    return dsText(action + (queued ? "_queued" : "_loading"));
}

function dsClearButtonLoading() {
    ["sample", "preview", "apply", "run"].forEach(action => AppLoading.setButtonLoading("#ds-" + action, false));
}

function dsError(xhr) {
    dsClearButtonLoading();
    dsStatus(xhr.responseJSON?.message || dsText("failed"));
    showApiError(xhr);
}

function loadDirectorySync() {
    const version = ++directorySyncListVersion;
    apiGet(directorySyncPath + "/options", function (data) {
        if (version === directorySyncListVersion) directorySyncOptions = data;
    });
    apiGet(directorySyncPath, function (sources) {
        if (version !== directorySyncListVersion) return;
        const body = $("#ds-list").empty();
        sources.forEach(source => {
            const row = $("<tr>").attr("data-source-id", source.id);
            $("<td>").text(source.name).appendTo(row);
            $("<td>").text(source.group_name).appendTo(row);
            const statusKey = source.schedule_state === "pending_approval" ? "awaiting_apply"
                : source.schedule_state === "preview" ? "preview_ready" : source.enabled ? "enabled" : "paused";
            const status = $("<td>").text(dsText(statusKey)).appendTo(row);
            if (source.pending_mode || source.running) status.append($("<div>").text(dsText("queued")));
            if (source.last_error || source.current_error) status.append($("<div>").addClass("muted").text(source.last_error || source.current_error));
            $("<td>").append(dsTime(source.last_success_at)).appendTo(row);
            $("<td>").append(source.running ? dsText("run_loading") : dsTime(source.next_run_at)).appendTo(row);
            $("<td>").append(source.current_running ? dsText("current_loading") : dsTime(source.next_current_at)).appendTo(row);
            $("<td>").addClass("actions-cell").append(makeActionMenu({
                object: source,
                items: [{
                    label: dsText("configure"),
                    icon: "fas fa-cog",
                    onClick: () => editDirectorySync(source.id),
                }, {
                    label: dsText(source.enabled ? "disable_schedule" : "enable_schedule"),
                    icon: source.enabled ? "fas fa-pause" : "fas fa-play",
                    onClick: () => dsSetSchedule(source, !source.enabled),
                }, {
                    label: dsText("remove_source"),
                    icon: "fas fa-trash",
                    danger: true,
                    onClick: () => dsConfirmRemove(source),
                }],
            })).appendTo(row);
            body.append(row);
            if (directorySyncListWrites.has(source.id)) dsListBusy(source.id, true);
        });
        if (!sources.length) body.append($("<tr>").append($("<td>", {colspan: 7, text: dsText("empty")})));
    });
}

function dsListBusy(id, busy) {
    if (busy) directorySyncListWrites.add(id);
    else directorySyncListWrites.delete(id);
    AppLoading.setButtonLoading($("#ds-list tr[data-source-id='" + id + "'] .app-action-menu-toggle"), busy);
}

function dsCanManage(source) {
    if (directorySyncListWrites.has(source.id)) return false;
    if (source.pending_mode || source.running || source.current_running) {
        showAppError(dsText("source_busy"));
        return false;
    }
    return true;
}

function dsListWriteFinished(source, xhr) {
    dsListBusy(source.id, false);
    loadDirectorySync();
    if (xhr) showApiError(xhr);
}

function dsSetSchedule(source, enabled) {
    if (!dsCanManage(source)) return;
    dsListBusy(source.id, true);
    apiPut(directorySyncPath + "/" + source.id, {
        name: source.name, group_id: source.group_id, config: source.config,
        revision: source.revision, enabled,
    }, () => dsListWriteFinished(source), xhr => dsListWriteFinished(source, xhr));
}

function dsConfirmRemove(source) {
    if (!dsCanManage(source)) return;
    const choice = $("<select>", {id: "ds-remove-mode", class: "input"})
        .attr("aria-describedby", "ds-remove-hint")
        .append($("<option>", {value: "keep", text: dsText("keep_data")}))
        .append($("<option>", {value: "delete", text: dsText("delete_data")}));
    const hint = $("<small>", {id: "ds-remove-hint", class: "muted", "aria-live": "polite"}).text(dsText("keep_data_hint"));
    choice.on("change", () => hint.text(dsText(choice.val() === "keep" ? "keep_data_hint" : "delete_data_hint")));
    const confirmation = showAppConfirm({
        title: dsText("remove_source"),
        message: i18n.t("ds.remove_confirm", {name: source.name}),
        confirmText: dsText("remove_source"),
        confirmClass: "btn-danger",
    });
    $("#app-dialog-message").append($("<div>").addClass("form-stack").append($("<div>").addClass("form-group")
        .append($("<label>", {for: "ds-remove-mode", text: dsText("imported_data")})).append(choice).append(hint)));
    confirmation.done(() => {
        if (directorySyncListWrites.has(source.id)) return;
        dsListBusy(source.id, true);
        apiRequest("DELETE", directorySyncPath + "/" + source.id, {
            revision: source.revision, data_action: choice.val(),
        }, () => dsListWriteFinished(source), xhr => dsListWriteFinished(source, xhr));
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
    clearTimeout(directorySyncPreviewTimer);
    directorySyncSource = null;
    directorySyncOpen = false;
    directorySyncSaving = false;
    directorySyncAction = null;
    dsClearButtonLoading();
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
    clearTimeout(directorySyncPreviewTimer);
    directorySyncOpen = true;
    directorySyncSaving = false;
    directorySyncAction = null;
    dsClearButtonLoading();
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
    dsRetainedSources(config.retained_source_id);
    $("#ds-url").val(config.base_url);
    $("#ds-network").val(config.private_network_policy);
    $("#ds-skip-tls").prop("checked", config.verify_tls === false);
    $("#ds-operations").val(JSON.stringify(config.operations, null, 2));
    const mapping = {};
    directorySyncMappingKeys.forEach(key => { mapping[key] = config[key]; });
    $("#ds-mapping").val(JSON.stringify(mapping, null, 2));
    $("#ds-interval").val(config.interval_seconds);
    $("#ds-current-enabled").prop("checked", config.current_enabled !== false && Boolean(config.operations?.current));
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

function dsRetainedSources(selected = null) {
    const groupId = Number($("#ds-group").val());
    const select = $("#ds-retained-source").empty();
    select.append($("<option>", {value: "", text: dsText("retained_none")}));
    const candidates = (directorySyncOptions.retained_sources || []).filter(item => item.group_id === groupId);
    candidates.forEach(item => select.append($("<option>", {
        value: item.id, text: item.name + " (#" + item.id + ") — " + item.base_url
    })));
    // Applied sources consume their archived bindings and disappear from options.
    // Keep the immutable selection when reopening or saving operational settings.
    if (selected && !candidates.some(item => item.id === selected)) {
        select.append($("<option>", {value: selected, text: dsText("retained_selected") + " #" + selected}));
    }
    select.val(selected || "").prop("disabled", Boolean(directorySyncSource?.last_success_at));
}

function dsCurrentControls(busy = false) {
    $("#ds-current-enabled").prop("disabled", busy);
    $("#ds-current-interval").prop("disabled", busy || !$("#ds-current-enabled").prop("checked"));
}

function dsPreviewReady(source) {
    return Boolean(source?.preview_token && Date.parse(source.preview_until) > Date.now());
}

function dsRenderWorkflow(source) {
    const busy = directorySyncSaving || Boolean(source?.pending_mode || source?.running);
    $("#ds-form fieldset").prop("disabled", directorySyncSaving && directorySyncAction === "save");
    const unsaved = !source || directorySyncDirty;
    const ready = dsPreviewReady(source);
    const step = unsaved ? "save" : ready ? "apply" : !source.approved ? "preview" : "saved";
    const action = dsOperation(source);
    const expired = !ready && source?.preview_until && Date.parse(source.preview_until) <= Date.now();
    const displayStep = busy ? "busy" : expired && !unsaved ? "expired" : step;
    const icon = {save: "pen-to-square", preview: "triangle-exclamation", apply: "list-check",
        saved: "circle-check", expired: "clock", busy: "hourglass-half"}[displayStep];
    $("#ds-workflow").attr("data-step", displayStep);
    $("#ds-workflow-icon").attr("class", "fa-solid fa-" + icon);
    $("#ds-workflow-title").text(dsText("workflow_title_" + displayStep));
    $("#ds-workflow-detail").text(action ? dsOperationText(source, action)
        : dsText(expired && !unsaved ? "workflow_expired" : "workflow_" + step));
    const wait = busy ? dsText("enabled_wait") : "";
    const saveFirst = unsaved ? dsText("save_first") : "";
    const reasons = {
        save: wait || (!unsaved ? dsText("configuration_saved") : ""),
        preview: wait || saveFirst,
        apply: wait || saveFirst || (!ready ? dsText("apply_needs_preview") : ""),
        run: wait || saveFirst || (ready ? dsText("run_after_preview")
            : !source?.approved ? dsText("apply_needs_preview") : ""),
        sample: wait || saveFirst,
    };
    Object.entries(reasons).forEach(([name, reason]) => {
        $("#ds-" + name).prop("disabled", Boolean(reason)).attr("title", reason || null);
    });
    ["save", "preview", "apply"].forEach(name => {
        $("#ds-" + name).toggleClass("btn-primary", !busy && step === name);
    });
    const scheduleHint = wait || (!source?.approved ? dsText("schedule_after_apply")
        : ready && source.enabled ? dsText("schedule_preview_pause") : "");
    $("#ds-enabled").prop("disabled", busy);
    $("#ds-enabled-label").attr("title", scheduleHint || null);
    $("#ds-enabled-hint").text(scheduleHint).prop("hidden", !scheduleHint);
    dsCurrentControls(busy);
}

function dsWatchPreviewExpiry(source) {
    clearTimeout(directorySyncPreviewTimer);
    if (!dsPreviewReady(source)) return;
    const version = directorySyncVersion;
    directorySyncPreviewTimer = setTimeout(() => {
        if (version === directorySyncVersion && directorySyncOpen) dsRenderWorkflow(directorySyncSource);
    }, Date.parse(source.preview_until) - Date.now() + 50);
}

function dsRenderResult(source) {
    const busy = directorySyncSaving || Boolean(source?.pending_mode || source?.running);
    const action = dsOperation(source);
    // Restore buttons before setting their current availability; the loading helper
    // remembers the disabled state from before an operation started.
    dsClearButtonLoading();
    dsRenderWorkflow(source);
    dsWatchPreviewExpiry(source);
    if (source?.preview_result?.samples) $("#ds-sample-output").text(JSON.stringify(source.preview_result.samples, null, 2)).prop("hidden", false);
    dsStatus(action ? dsOperationText(source, action) : source?.last_error || source?.current_error || "", Boolean(action));
    $("#ds-retained-source").prop("disabled", busy || Boolean(source?.last_success_at));
    if (action && action !== "save") AppLoading.setButtonLoading("#ds-" + action, true);
    const body = $("#ds-preview-table").empty();
    (source?.preview_result?.changes || []).forEach(change => {
        const row = $("<tr>");
        [change.kind, change.label || change.external_id,
            change.action === "reconnect" ? dsText("reconnect") : change.action,
            JSON.stringify(change.fields)].forEach(value => $("<td>").text(value).appendTo(row));
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
                if (!data.last_error && !data.current_error) dsStatus(dsText("complete"));
                loadDirectorySync();
            }
        }, xhr => { if (version === directorySyncVersion) dsError(xhr); });
    }, 1500);
}

function dsQueue(action) {
    if (!directorySyncSource || directorySyncSaving || directorySyncSource.pending_mode || directorySyncSource.running) return;
    if (directorySyncDirty) { $("#ds-status").text(dsText("save_first")); return; }
    const version = directorySyncVersion;
    directorySyncSaving = true;
    directorySyncAction = action;
    setAppModalSaving("#ds-editor", true);
    dsRenderResult(directorySyncSource);
    apiPost(directorySyncPath + "/" + directorySyncSource.id + "/" + action,
        {revision: directorySyncSource.revision, preview_token: directorySyncSource.preview_token}, data => {
            if (version !== directorySyncVersion) return;
            directorySyncSaving = false;
            directorySyncAction = null;
            setAppModalSaving("#ds-editor", false);
            directorySyncSource = data;
            dsRenderResult(data);
            dsPoll(version, data.id);
        }, xhr => dsWriteError(version, xhr));
}

function dsWriteError(version, xhr) {
    if (version !== directorySyncVersion) return;
    directorySyncSaving = false;
    directorySyncAction = null;
    setAppModalSaving("#ds-editor", false);
    dsRenderResult(directorySyncSource);
    dsError(xhr);
}

$(document).on("click", "#ds-new", () => openDirectorySync(null));
$(document).on("click", "#ds-reload", loadDirectorySync);
$(document).on("change", "#ds-group", () => dsRetainedSources());
$(document).on("change", "#ds-current-enabled", () => dsCurrentControls());
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
    dsRenderWorkflow(directorySyncSource);
});
$(document).on("click", "#ds-preview", () => dsQueue("preview"));
$(document).on("click", "#ds-apply", () => dsQueue("apply"));
$(document).on("click", "#ds-run", () => dsQueue("run"));
$(document).on("click", "#ds-sample", () => {
    if (directorySyncSaving || directorySyncSource?.pending_mode || directorySyncSource?.running) return;
    if (!directorySyncSource || directorySyncDirty) { $("#ds-status").text(dsText("save_first")); return; }
    const version = directorySyncVersion;
    directorySyncSaving = true;
    directorySyncAction = "sample";
    setAppModalSaving("#ds-editor", true);
    dsRenderResult(directorySyncSource);
    apiPost(directorySyncPath + "/" + directorySyncSource.id + "/sample", {}, data => {
        if (version !== directorySyncVersion) return;
        directorySyncSaving = false;
        directorySyncAction = null;
        setAppModalSaving("#ds-editor", false);
        dsRenderResult(directorySyncSource);
        dsStatus(directorySyncSource.current_error || directorySyncSource.last_error || dsText("complete"));
        $("#ds-sample-output").text(JSON.stringify(data.samples, null, 2)).prop("hidden", false);
    }, xhr => dsWriteError(version, xhr));
});
$(document).on("submit", "#ds-form", function (event) {
    event.preventDefault();
    if (directorySyncSaving || directorySyncSource?.pending_mode || directorySyncSource?.running) return;
    let payload;
    try {
        const config = {...(directorySyncSource?.config || directorySyncOptions.preset), ...JSON.parse($("#ds-mapping").val()),
            retained_source_id: Number($("#ds-retained-source").val()) || null,
            operations: JSON.parse($("#ds-operations").val()), base_url: $("#ds-url").val(),
            private_network_policy: $("#ds-network").val(), interval_seconds: Number($("#ds-interval").val()),
            verify_tls: !$("#ds-skip-tls").prop("checked"),
            current_enabled: $("#ds-current-enabled").prop("checked"),
            current_interval_seconds: Number($("#ds-current-interval").val()), horizon_months: Number($("#ds-horizon").val()),
            membership_authority: $("#ds-authority").val(), editable: $("#ds-editable").prop("checked"),
            overwrite_existing: $("#ds-overwrite").prop("checked"), delete_missing: $("#ds-delete").prop("checked")};
        if (config.current_enabled && !config.operations.current) {
            dsStatus(dsText("current_missing"));
            return;
        }
        payload = {name: $("#ds-name").val(), group_id: Number($("#ds-group").val()), config,
            enabled: $("#ds-enabled").prop("checked"), revision: directorySyncSource?.revision};
        if ($("#ds-headers").val().trim()) payload.headers = JSON.parse($("#ds-headers").val());
    } catch (_error) { $("#ds-status").text(dsText("invalid_json")); return; }
    const scrollTop = $("#ds-editor .app-modal-body").scrollTop();
    const version = directorySyncVersion;
    directorySyncSaving = true;
    directorySyncAction = "save";
    setAppModalSaving("#ds-editor", true);
    dsRenderResult(directorySyncSource);
    apiRequest(directorySyncSource ? "PUT" : "POST", directorySyncPath + (directorySyncSource ? "/" + directorySyncSource.id : ""), payload, data => {
        if (version !== directorySyncVersion) return;
        if (data.approved) {
            closeDirectorySync();
        } else {
            // Updating in place preserves the user's position in the form.
            const body = $("#ds-editor .app-modal-body");
            directorySyncSaving = false;
            directorySyncAction = null;
            directorySyncSource = data;
            directorySyncDirty = false;
            setAppModalSaving("#ds-editor", false);
            $("#ds-headers").val("");
            $("#ds-group").prop("disabled", true);
            $("#ds-name").val(data.name);
            $("#ds-editor-title").text(data.name);
            if (!data.preview_result?.team_catalog) $("#ds-team-matches").empty();
            dsRenderResult(data);
            body.scrollTop(scrollTop);
            const nextAction = dsPreviewReady(data) ? "ds-apply" : "ds-preview";
            document.getElementById(nextAction)?.focus({preventScroll: true});
        }
        loadDirectorySync();
    }, xhr => dsWriteError(version, xhr));
});
