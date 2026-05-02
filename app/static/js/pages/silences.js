let silencesCache = [];
let selectedSilenceDetailsId = null;


function loadSilences() {
    /*
     * Load silences page.
     */
    fillTeamSelect("#silence-team", false);
    refreshSilences();
}


function refreshSilences() {
    /*
     * Refresh silences table.
     */
    apiGet("/api/silences" + selectedTeamQuery(), function (silences) {
        silencesCache = asArray(silences);

        renderSilencesSummary(silencesCache);
        renderSilencesTable();
        restoreSilenceDetails();
    });
}


function parseSilenceDate(value) {
    /*
     * Parse silence datetime.
     */
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
    /*
     * Return calculated silence status.
     */
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
    /*
     * Return readable silence status.
     */
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
    /*
     * Render silences summary cards.
     */
    silences = asArray(silences);

    const counters = {
        active: 0,
        scheduled: 0,
        expired: 0,
        disabled: 0
    };

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
    /*
     * Build searchable silence text.
     */
    return [
        silence.id,
        silence.team_slug,
        silence.name,
        silence.reason,
        getSilenceStatus(silence),
        JSON.stringify(silence.matchers || {})
    ].join(" ").toLowerCase();
}


function getFilteredSilences() {
    /*
     * Apply client-side filters.
     */
    const query = String($("#silences-search").val() || "").trim().toLowerCase();
    const status = String($("#silences-status-filter").val() || "");

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


function renderSilencesCounter(filteredSilences, allSilences) {
    /*
     * Render "Showing X of Y silences".
     */
    filteredSilences = asArray(filteredSilences);
    allSilences = asArray(allSilences);

    $("#silences-filtered-count").text(filteredSilences.length);
    $("#silences-total-count").text(allSilences.length);
}


function renderSilencesTable() {
    /*
     * Render filtered silences table.
     */
    const tbody = $("#silences-table");
    const silences = getFilteredSilences();

    tbody.empty();
    renderSilencesCounter(silences, silencesCache);

    if (!silences.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>")
                    .attr("colspan", "7")
                    .addClass("silences-empty-cell")
                    .text("No silences")
            )
        );
        return;
    }

    silences.forEach(function (silence) {
        tbody.append(renderSilenceRow(silence));
    });
}


function renderSilenceRow(silence) {
    /*
     * Render one silence row.
     */
    const row = $("<tr>");
    const status = getSilenceStatus(silence);

    row.append(
        $("<td>")
            .append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("silence-name-button")
                    .text(silence.name || "-")
                    .on("click", function () {
                        renderSilenceDetails(silence);
                    })
            )
            .append(
                $("<div>")
                    .addClass("silence-row-subtitle")
                    .text("Silence #" + silence.id)
            )
    );

    row.append(
        $("<td>").append(
            $("<span>")
                .addClass("silence-team-pill")
                .text(silence.team_slug || "-")
        )
    );

    row.append($("<td>").text(silence.reason || "-"));

    row.append(
        $("<td>").append(
            $("<div>")
                .addClass("silence-window")
                .append(
                    $("<div>")
                        .addClass("silence-window-main")
                        .text(formatDateTime24(silence.starts_at))
                )
                .append(
                    $("<div>")
                        .addClass("silence-window-subtitle")
                        .text("until " + formatDateTime24(silence.ends_at))
                )
        )
    );

    row.append(
        $("<td>").append(
            $("<div>")
                .addClass("silence-matchers-preview")
                .attr("title", JSON.stringify(silence.matchers || {}))
                .text(JSON.stringify(silence.matchers || {}))
        )
    );

    row.append(
        $("<td>").append(
            $("<span>")
                .addClass("status-pill")
                .addClass("status-" + status)
                .text(getSilenceStatusLabel(status))
        )
    );

    row.append(
        $("<td>")
            .addClass("actions-cell")
            .append(renderSilenceActions(silence))
    );

    return row;
}


function renderSilenceActions(silence) {
    /*
     * Render silence row actions.
     */
    const actions = $("<div>").addClass("table-actions");

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-small")
            .text("Edit")
            .on("click", function () {
                editSilence(silence.id);
            })
    );

    if (silence.enabled) {
        actions.append(
            $("<button>")
                .attr("type", "button")
                .addClass("btn btn-danger btn-small")
                .text("Disable")
                .on("click", function () {
                    deleteSilence(silence.id);
                })
        );
    }

    return actions;
}


function silenceDetailsItem(label, value) {
    /*
     * Render one silence details item.
     */
    return $("<div>")
        .addClass("details-item")
        .append($("<div>").addClass("details-label").text(label))
        .append($("<div>").addClass("details-value").text(value || "-"));
}


function silenceDetailsCode(label, value) {
    /*
     * Render JSON details item.
     */
    return $("<div>")
        .addClass("details-item")
        .append($("<div>").addClass("details-label").text(label))
        .append(
            $("<pre>")
                .addClass("silence-details-code")
                .text(JSON.stringify(value || {}, null, 2))
        );
}


function renderSilenceDetails(silence) {
    /*
     * Render selected silence details.
     */
    const status = getSilenceStatus(silence);

    selectedSilenceDetailsId = silence.id;

    $("#silence-details-subtitle").text(
        (silence.team_slug || "-") + " / " + getSilenceStatusLabel(status)
    );

    $("#silence-details-body")
        .empty()
        .append(
            $("<div>")
                .addClass("details-list")
                .append(silenceDetailsItem("Name", silence.name))
                .append(silenceDetailsItem("Team", silence.team_slug))
                .append(silenceDetailsItem("Reason", silence.reason))
                .append(silenceDetailsItem("Starts at", formatDateTime24(silence.starts_at)))
                .append(silenceDetailsItem("Ends at", formatDateTime24(silence.ends_at)))
                .append(silenceDetailsItem("Status", getSilenceStatusLabel(status)))
                .append(silenceDetailsCode("Matchers", silence.matchers || {}))
        )
        .append(
            $("<div>")
                .addClass("details-actions")
                .append(
                    $("<button>")
                        .attr("type", "button")
                        .addClass("btn btn-small")
                        .text("Edit silence")
                        .on("click", function () {
                            editSilence(silence.id);
                        })
                )
        );
}


function restoreSilenceDetails() {
    /*
     * Restore details panel after reload.
     */
    if (!silencesCache.length) {
        renderSilenceDetailsEmpty();
        return;
    }

    if (selectedSilenceDetailsId) {
        const selected = silencesCache.find(function (silence) {
            return Number(silence.id) === Number(selectedSilenceDetailsId);
        });

        if (selected) {
            renderSilenceDetails(selected);
            return;
        }
    }

    renderSilenceDetails(silencesCache[0]);
}


function renderSilenceDetailsEmpty() {
    /*
     * Render empty details state.
     */
    selectedSilenceDetailsId = null;

    $("#silence-details-subtitle").text("Select a silence");
    $("#silence-details-body").html(
        '<div class="details-empty">' +
        'Click a silence name to inspect time window, reason and matchers.' +
        '</div>'
    );
}


function collectSilencePayload() {
    /*
     * Build silence payload.
     */
    return {
        team_id: Number($("#silence-team").val()),
        name: $("#silence-name").val(),
        reason: $("#silence-reason").val(),
        starts_at: $("#silence-starts-at").val(),
        ends_at: $("#silence-ends-at").val(),
        matchers: parseJsonInput("#silence-matchers", {})
    };
}


function saveSilence() {
    /*
     * Create or update silence.
     */
    const id = $("#silence-id").val();

    if (id) {
        apiPut("/api/silences/" + id, collectSilencePayload(), function () {
            closeSilenceFormModal();
            resetSilenceForm();
            refreshSilences();
        });

        return;
    }

    apiPost("/api/silences", collectSilencePayload(), function () {
        closeSilenceFormModal();
        resetSilenceForm();
        refreshSilences();
    });
}


function editSilence(id) {
    /*
     * Load silence data into the form.
     */
    const silence = silencesCache.find(function (item) {
        return Number(item.id) === Number(id);
    });

    if (!silence) {
        return;
    }

    $("#silence-form-title").text("Edit silence #" + id);
    $("#silence-id").val(silence.id);
    $("#silence-team").val(silence.team_id);
    $("#silence-name").val(silence.name);
    $("#silence-reason").val(silence.reason || "");
    $("#silence-starts-at").val(isoToDatetimeLocal(silence.starts_at));
    $("#silence-ends-at").val(isoToDatetimeLocal(silence.ends_at));
    $("#silence-matchers").val(JSON.stringify(silence.matchers || {}, null, 2));

    openSilenceFormModal();
}


function deleteSilence(id) {
    /*
     * Disable silence.
     */

    showAppConfirm({
        title: "Disable this silence?",
        message: "Disable this silence?",
        confirmText: "Disable",
        confirmClass: "btn-warning",
    }).done(function () {
        apiDelete("/api/silences/" + id, refreshSilences)
    });
}


function resetSilenceForm() {
    /*
     * Reset silence form.
     */
    $("#silence-form-title").text("Create silence");
    $("#silence-id").val("");
    $("#silence-name").val("");
    $("#silence-reason").val("");
    $("#silence-starts-at").val("");
    $("#silence-ends-at").val("");
    $("#silence-matchers").val('{"labels":{"host":"host1"}}');
}


function openSilenceFormModal() {
    /*
     * Open silence create/edit modal.
     */
    $("#silence-form-modal")
        .css("display", "flex")
        .addClass("is-open");

    $("body").addClass("modal-open");
}


function closeSilenceFormModal() {
    /*
     * Close silence create/edit modal.
     */
    $("#silence-form-modal")
        .css("display", "none")
        .removeClass("is-open");

    $("body").removeClass("modal-open");
}


function openCreateSilenceModal() {
    /*
     * Reset form and open create modal.
     */
    resetSilenceForm();
    $("#silence-form-title").text("Create silence");
    openSilenceFormModal();
}


$(document).on("input", "#silences-search", renderSilencesTable);
$(document).on("change", "#silences-status-filter", renderSilencesTable);

$(document).on("click", "#open-silence-create-modal", openCreateSilenceModal);
$(document).on("click", "#save-silence", saveSilence);
$(document).on("click", "#reset-silence-form", resetSilenceForm);
$(document).on("click", "#reload-silences", refreshSilences);

$(document).on("click", "#close-silence-form-modal", closeSilenceFormModal);

$(document).on("click", "#silence-form-modal", function (event) {
    if (event.target === this) {
        closeSilenceFormModal();
    }
});

$(document).on("keydown", function (event) {
    if (event.key === "Escape" && $("#silence-form-modal").hasClass("is-open")) {
        closeSilenceFormModal();
    }
});
