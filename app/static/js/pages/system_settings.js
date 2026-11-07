let systemSettingsVersion = 0;
let systemSettingsSaving = false;

function advancedSettingsChanges() {
    const changes = {};
    $("#system-settings-advanced input").each(function () {
        if (this.value !== this.defaultValue) changes[this.name] = this.valueAsNumber;
    });
    return changes;
}

function updateAdvancedSaveButton() {
    const dirty = Object.keys(advancedSettingsChanges()).length > 0;
    $("#system-settings-advanced button").prop("disabled", systemSettingsSaving || !dirty);
}

function loadSystemSettings(changes) {
    if (!isGlobalAdminUser() || systemSettingsSaving) return;
    const version = ++systemSettingsVersion;
    const saving = Boolean(changes);
    const controls = $("#system-settings-controls");
    const switches = controls.find("input[type=checkbox]");
    const numbers = controls.find("input[type=number]");
    const status = $("#system-settings-status");
    systemSettingsSaving = saving;
    controls.find("input, button").prop("disabled", true);
    $("#system-settings-reload").prop("disabled", saving);
    status.addClass("is-hidden");

    function finish() {
        systemSettingsSaving = false;
        controls.find("input").prop("disabled", false);
        $("#system-settings-reload").prop("disabled", false);
        updateAdvancedSaveButton();
    }
    apiRequest(saving ? "PATCH" : "GET", "/api/admin/system-settings", changes, function (values) {
        if (version !== systemSettingsVersion) return;
        switches.each(function () { this.defaultChecked = this.checked = values[this.name]; });
        numbers.each(function () {
            this.setCustomValidity("");
            const keepDraft = saving && !(this.name in changes) && this.value !== this.defaultValue;
            this.defaultValue = String(values[this.name]);
            if (!keepDraft) this.value = this.defaultValue;
        });
        controls.removeClass("is-hidden");
        if (saving) status.text(i18n.t("system_settings.saved")).removeClass("is-hidden");
        finish();
    }, function (xhr) {
        if (version !== systemSettingsVersion) return;
        switches.each(function () { this.checked = this.defaultChecked; });
        if (!saving) controls.addClass("is-hidden");
        status.text(i18n.t(saving ? "system_settings.save_failed" : "system_settings.load_failed"))
            .removeClass("is-hidden");
        finish();
        showApiError(xhr);
    });
}

$(document).on("click", "#system-settings-reload", function () { loadSystemSettings(); });
$(document).on("change", "#system-settings-controls input[type=checkbox]", function () {
    loadSystemSettings({[this.name]: this.checked});
});
$(document).on("input", "#system-settings-advanced", function () {
    this.elements.change_worker_retry_base_seconds.setCustomValidity("");
    updateAdvancedSaveButton();
});
$(document).on("submit", "#system-settings-advanced", function (event) {
    event.preventDefault();
    const base = this.elements.change_worker_retry_base_seconds;
    const max = this.elements.change_worker_retry_max_seconds;
    if (base.valueAsNumber > max.valueAsNumber) {
        base.setCustomValidity(i18n.t("system_settings.invalid_retry_window"));
        base.reportValidity();
        return;
    }
    const changes = advancedSettingsChanges();
    if (Object.keys(changes).length) loadSystemSettings(changes);
});
