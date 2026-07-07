let silencesCache = [];
let silenceMatcherPresetsCache = [];
let selectedSilenceDetailsId = null;
let selectedSilenceSummaryFilter = "";

function buildSilencesApiUrl() {
    let url = "/api/silences" + selectedTeamQuery();
    if ($("#silences-include-expired-history").is(":checked")) {
        url += url.indexOf("?") === -1 ? "?" : "&";
        url += "include_expired_history=1";
    }
    return url;
}

function initializeSilenceMatcherEditor() {
    enhanceMatcherEditor("#silence-matchers", {
        label: "Additional matchers JSON",
        header: "Additional matchers",
        context: function () {
            return {
                scope: "silence",
                teamId: Number($("#silence-team").val()) || null,
                silenceId: Number($("#silence-id").val()) || null,
                matcherPresetId: Number($("#silence-matcher-preset").val()) || null,
            };
        },
    });
}

function updateSilenceMatcherPresetHint() {
    const preset = findMatcherPresetById(
        silenceMatcherPresetsCache,
        $("#silence-matcher-preset").val()
    );

    $("#silence-matcher-preset-hint").text(
        matcherPresetAndLocalHint(preset)
    );
}


function loadSilenceMatcherPresets(teamId, selectedPresetId, callback) {
    silenceMatcherPresetsCache = [];

    fillMatcherPresetSelect(
        "#silence-matcher-preset",
        [],
        null
    );
    updateSilenceMatcherPresetHint();

    if (!teamId) {
        if (typeof callback === "function") {
            callback([]);
        }

        return;
    }

    loadMatcherPresetsForTeam(teamId, function (presets) {
        silenceMatcherPresetsCache = presets;

        fillMatcherPresetSelect(
            "#silence-matcher-preset",
            presets,
            selectedPresetId
        );
        updateSilenceMatcherPresetHint();

        if (typeof callback === "function") {
            callback(presets);
        }
    });
}

function loadSilences() {
    initializeSilenceMatcherEditor();

    fillTeamSelect("#silence-team", false, function () {
        const selectedTeam = selectedTeamNumber();

        if (
            selectedTeam &&
            $("#silence-team option[value='" + selectedTeam + "']").length
        ) {
            $("#silence-team").val(String(selectedTeam));
        }

        loadSilenceMatcherPresets(
            Number($("#silence-team").val()) || null,
            null
        );
    });

    refreshSilences();
}

function refreshSilences() {
    apiGet(buildSilencesApiUrl(), function (silences) {
        silencesCache = asArray(silences);
        renderSilencesSummary(silencesCache);
        renderSilencesTable();
        restoreSilenceDetails();
    });
}

function parseSilenceDate(value) {
    if (!value) {
        return null;
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return null;
    }
    return date;
}

function getSilenceStatus(silence) {
    if (!silence.enabled) {
        return "disabled";
    }

    const now = new Date();
    const startsAt = parseSilenceDate(silence.starts_at);
    const endsAt = parseSilenceDate(silence.ends_at);

    if (startsAt && now < startsAt) {
        return "scheduled";
    }
    if (endsAt && now > endsAt) {
        return "expired";
    }
    return "active";
}

function getSilenceStatusLabel(status) {
    if (status === "active") {
        return "Active now";
    }
    if (status === "scheduled") {
        return "Scheduled";
    }
    if (status === "expired") {
        return "Expired";
    }
    if (status === "disabled") {
        return "Disabled";
    }
    return status || "-";
}

function renderSilencesSummary(silences) {
    silences = asArray(silences);
    const counters = { active: 0, scheduled: 0, expired: 0, disabled: 0 };

    silences.forEach(function (silence) {
        const status = getSilenceStatus(silence);
        if (Object.prototype.hasOwnProperty.call(counters, status)) {
            counters[status] += 1;
        }
    });

    $("#silences-summary-total").text(silences.length);
    $("#silences-summary-active").text(counters.active);
    $("#silences-summary-scheduled").text(counters.scheduled);
    $("#silences-summary-expired").text(counters.expired);
    $("#silences-summary-disabled").text(counters.disabled);
}

function getSilenceSearchText(silence) {
    return [
        silence.id,
        silence.team_name,
        silence.team_slug,
        silence.name,
        silence.reason,
        silence.matcher_preset
            ? silence.matcher_preset.name
            : "",
        getSilenceStatus(silence),
        JSON.stringify(silence.matchers || {}),
    ].join(" ").toLowerCase();
}

function getFilteredSilences() {
    const query = String($("#silences-search").val() || "").trim().toLowerCase();
    const status = String($("#silences-status-filter").val() || selectedSilenceSummaryFilter || "");

    return silencesCache.filter(function (silence) {
        if (status && getSilenceStatus(silence) !== status) {
            return false;
        }
        if (!query) {
            return true;
        }
        return getSilenceSearchText(silence).indexOf(query) !== -1;
    });
}

function applySilenceFilters() {
    renderSilencesTable();
    restoreSilenceDetails();
}

function renderSilencesCounter(filteredSilences, allSilences) {
    filteredSilences = asArray(filteredSilences);
    allSilences = asArray(allSilences);
    $("#silences-filtered-count").text(filteredSilences.length);
    $("#silences-total-count").text(allSilences.length);
}

function renderSilencesTable() {
    const tbody = $("#silences-table");
    const silences = getFilteredSilences();
    tbody.empty();
    renderSilencesCounter(silences, silencesCache);

    if (!silences.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>").attr("colspan", "7").addClass("empty-cell").text("No silences")
            )
        );
        return;
    }

    silences.forEach(function (silence) {
        tbody.append(renderSilenceRow(silence));
    });
}

function renderSilenceRow(silence) {
    const row = $("<tr>");
    const status = getSilenceStatus(silence);

    row.append(
        $("<td>")
            .append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("name-button")
                    .text(silence.name || "-")
                    .on("click", function () {
                        renderSilenceDetails(silence);
                    })
            )
            .append($("<div>").addClass("row-subtitle").text("Silence #" + silence.id))
    );
    row.append($("<td>").append($("<span>").addClass("pill").text(silence.team_name || silence.team_slug || "-")));
    row.append($("<td>").text(silence.reason || "-"));
    row.append(
        $("<td>").append(
            $("<div>")
                .addClass("details-compact-list")
                .append($("<div>").addClass("item-title").text(formatDateTime24(silence.starts_at)))
                .append($("<div>").addClass("item-subtitle").text("until " + formatDateTime24(silence.ends_at)))
        )
    );
    const matchingCell = $("<td>");

    if (silence.matcher_preset) {
        matchingCell.append(
            $("<div>")
                .addClass("row-subtitle")
                .text(
                    "Preset: " +
                    formatMatcherPresetOption(silence.matcher_preset)
                )
        );
    }

    matchingCell.append(
        $("<code>")
            .addClass("details-code")
            .attr(
                "title",
                JSON.stringify(silence.matchers || {})
            )
            .text(JSON.stringify(silence.matchers || {}))
    );

    row.append(matchingCell);
    row.append(
        $("<td>").append(
            $("<span>")
                .addClass("status-pill")
                .addClass("status-" + status)
                .text(getSilenceStatusLabel(status))
        )
    );
    row.append($("<td>").addClass("actions-cell").append(renderSilenceActions(silence)));
    return row;
}

function renderSilenceActions(silence) {
    /*
     * Render silence row actions as a shared three-dots menu.
     */
    return makeActionMenu({
        object: silence,
        items: [
            {
                label: "Edit",
                icon: "fas fa-edit",
                required: "write",
                denyMessage: "Team manager role is required to edit this silence.",
                onClick: function () {
                    editSilence(silence.id);
                }
            },
            {
                label: silence.enabled ? "Disable" : "Enable",
                icon: silence.enabled ? "fas fa-pause" : "fas fa-play",
                required: "write",
                danger: silence.enabled,
                hidden: !silence.enabled && typeof enableSilence !== "function",
                denyMessage: "Team manager role is required to enable or disable this silence.",
                onClick: function () {
                    if (silence.enabled) {
                        disableSilence(silence.id);
                    } else if (typeof enableSilence === "function") {
                        enableSilence(silence.id);
                    }
                }
            }
        ]
    });
}

function silenceDetailsItem(label, value) {
    return $("<div>")
        .addClass("details-item")
        .append($("<div>").addClass("details-label").text(label))
        .append($("<div>").addClass("details-value").text(value || "-"));
}

function silenceDetailsCode(label, value) {
    return $("<div>")
        .addClass("details-item")
        .append($("<div>").addClass("details-label").text(label))
        .append($("<pre>").addClass("details-code").text(JSON.stringify(value || {}, null, 2)));
}

function renderSilenceDetails(silence) {
    const status = getSilenceStatus(silence);
    selectedSilenceDetailsId = silence.id;

    $("#silence-details-subtitle").text((silence.team_slug || "-") + " / " + getSilenceStatusLabel(status));

    const body = $("#silence-details-body");
    body.empty().append(
        $("<div>")
            .addClass("details-list")
            .append(silenceDetailsItem("Name", silence.name))
            .append(silenceDetailsItem("Team", silence.team_slug))
            .append(silenceDetailsItem("Reason", silence.reason))
            .append(silenceDetailsItem("Starts at", formatDateTime24(silence.starts_at)))
            .append(silenceDetailsItem("Ends at", formatDateTime24(silence.ends_at)))
            .append(silenceDetailsItem("Status", getSilenceStatusLabel(status)))
            .append(
                silenceDetailsItem(
                    "Matcher preset",
                    silence.matcher_preset
                        ? formatMatcherPresetOption(silence.matcher_preset)
                        : "No preset"
                )
            )
            .append(
                silenceDetailsCode(
                    "Additional matchers",
                    silence.matchers || {}
                )
            )
    );

    const actions = $("<div>").addClass("details-actions");
    appendIconActionIfAllowed(actions, silence, {
        required: "write",
        icon: "fas fa-edit",
        label: "Edit silence",
        onClick: function () {
            editSilence(silence.id);
        },
    });
    if (silence.enabled) {
        appendIconActionIfAllowed(actions, silence, {
            required: "write",
            icon: "fas fa-pause",
            label: "Disable silence",
            className: "btn-warning",
            onClick: function () {
                disableSilence(silence.id);
            },
        });
    } else if (typeof enableSilence === "function") {
        appendIconActionIfAllowed(actions, silence, {
            required: "write",
            icon: "fas fa-play",
            label: "Enable silence",
            className: "btn-success",
            onClick: function () {
                enableSilence(silence.id);
            },
        });
    }

    if (actions.children().length) {
        body.append(actions);
    }
}

function restoreSilenceDetails() {
    const silences = getFilteredSilences();
    if (!silences.length) {
        renderSilenceDetailsEmpty();
        return;
    }

    if (selectedSilenceDetailsId) {
        const selected = silences.find(function (silence) {
            return Number(silence.id) === Number(selectedSilenceDetailsId);
        });
        if (selected) {
            renderSilenceDetails(selected);
            return;
        }
    }

    renderSilenceDetails(silences[0]);
}

function applySilenceSummaryFilter(status) {
    selectedSilenceSummaryFilter = status || "";
    $("#silences-status-filter").val(selectedSilenceSummaryFilter);
    applySilenceFilters();
}

function renderSilenceDetailsEmpty() {
    selectedSilenceDetailsId = null;
    $("#silence-details-subtitle").text("Select a silence");
    $("#silence-details-body").html("<p class=\"muted\">Click a silence name to inspect time window, reason and matchers.</p>");
}

function collectSilencePayload() {
    return {
        team_id: Number($("#silence-team").val()),
        name: $("#silence-name").val(),
        reason: $("#silence-reason").val(),
        starts_at: $("#silence-starts-at").val(),
        ends_at: $("#silence-ends-at").val(),
        matcher_preset_id: $("#silence-matcher-preset").val()
            ? Number($("#silence-matcher-preset").val())
            : null,
        matchers: getMatcherEditorValue("#silence-matchers", {}),
    };
}

function saveSilence() {
    const id = $("#silence-id").val();
    const existing = id ? silencesCache.find(function (item) { return Number(item.id) === Number(id); }) : null;

    if (existing && !canWriteObject(existing)) {
        showAppError("You do not have permission to edit this silence.");
        return;
    }

    if (id) {
        apiPut("/api/silences/" + id, collectSilencePayload(), function () {
            closeAppModal("#silence-form-modal");
            resetSilenceForm();
            refreshSilences();
        });
        return;
    }

    apiPost("/api/silences", collectSilencePayload(), function () {
        closeAppModal("#silence-form-modal");
        resetSilenceForm();
        refreshSilences();
    });
}

function editSilence(id) {
    const silence = silencesCache.find(function (item) {
        return Number(item.id) === Number(id);
    });

    if (!silence) {
        return;
    }

    if (!canWriteObject(silence)) {
        showAppError("You do not have permission to edit this silence.");
        return;
    }

    const matcherPresetId = silence.matcher_preset_id ||
        (silence.matcher_preset ? silence.matcher_preset.id : null);

    $("#silence-form-title").text("Edit silence #" + id);
    $("#silence-id").val(silence.id);
    $("#silence-team").val(String(silence.team_id));
    $("#silence-name").val(silence.name);
    $("#silence-reason").val(silence.reason || "");
    $("#silence-starts-at").val(isoToDatetimeLocal(silence.starts_at));
    $("#silence-ends-at").val(isoToDatetimeLocal(silence.ends_at));
    setMatcherEditorValue("#silence-matchers", silence.matchers || {});

    loadSilenceMatcherPresets(
        silence.team_id,
        matcherPresetId,
        function () {
            openAppModal("#silence-form-modal");
        }
    );
}

function disableSilence(id) {
    const silence = silencesCache.find(function (item) {
        return Number(item.id) === Number(id);
    });
    if (silence && !canWriteObject(silence)) {
        showAppError("You do not have permission to disable this silence.");
        return;
    }

    showAppConfirm({
        title: "Disable this silence?",
        message: "Disable this silence?",
        confirmText: "Disable",
        confirmClass: "btn-warning",
    }).done(function () {
        apiDelete("/api/silences/" + id, refreshSilences);
    });
}

function resetSilenceForm() {
    $("#silence-form-title").text("Create silence");
    $("#silence-id").val("");
    $("#silence-name").val("");
    $("#silence-reason").val("");
    $("#silence-starts-at").val("");
    $("#silence-ends-at").val("");

    fillMatcherPresetSelect(
        "#silence-matcher-preset",
        silenceMatcherPresetsCache,
        null
    );
    updateSilenceMatcherPresetHint();

    setMatcherEditorValue("#silence-matchers", {});
}

function openCreateSilenceModal() {
    resetSilenceForm();

    const selectedTeam = selectedTeamNumber();

    if (
        selectedTeam &&
        $("#silence-team option[value='" + selectedTeam + "']").length
    ) {
        $("#silence-team").val(String(selectedTeam));
    }

    const teamId = Number($("#silence-team").val()) || null;

    loadSilenceMatcherPresets(teamId, null, function () {
        $("#silence-form-title").text("Create silence");
        openAppModal("#silence-form-modal");
    });
}

$(document).on("input", "#silences-search", applySilenceFilters);
$(document).on("change", "#silences-status-filter", function () {
    selectedSilenceSummaryFilter = String($(this).val() || "");
    applySilenceFilters();
});
$(document).on("change", "#silences-include-expired-history", refreshSilences);
$(document).on("click", "[data-silences-summary-filter]", function () {
    applySilenceSummaryFilter($(this).data("silences-summary-filter"));
});
$(document).on("keydown", "[data-silences-summary-filter]", function (event) {
    if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        applySilenceSummaryFilter($(this).data("silences-summary-filter"));
    }
});
$(document).on("click", "#open-silence-create-modal", openCreateSilenceModal);
$(document).on("click", "#save-silence", saveSilence);
$(document).on("click", "#reset-silence-form", resetSilenceForm);
$(document).on("click", "#reload-silences", refreshSilences);
$(document).on("click", "#close-silence-form-modal", function () {
    closeAppModal("#silence-form-modal");
});
$(document).on("click", "#silence-form-modal", function (event) {
    if (event.target === this) {
        closeAppModal("#silence-form-modal");
    }
});
$(document).on("keydown", function (event) {
    if (event.key === "Escape" && $("#silence-form-modal").hasClass("is-open")) {
        closeAppModal("#silence-form-modal");
    }
});
$(document).on(
    "change",
    "#silence-matcher-preset",
    updateSilenceMatcherPresetHint
);
