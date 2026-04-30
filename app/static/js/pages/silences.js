let silencesCache = [];

function loadSilences() {
    /* Load silences page. */
    fillTeamSelect("#silence-team", false);
    refreshSilences();
}

function refreshSilences() {
    /* Refresh silences table. */
    apiGet("/api/silences" + selectedTeamQuery(), function (silences) {
        silences = asArray(silences);
        silencesCache = silences;
        const tbody = $("#silences-table");
        tbody.empty();
        silences.forEach(function (s) {
            const row = $("<tr>");
            row.append($("<td>").text(s.id));
            row.append($("<td>").text(s.team_slug));
            row.append($("<td>").text(s.name));
            row.append($("<td>").text(s.reason || "-"));
            row.append($("<td>").text(formatDateTime24(s.starts_at)));
            row.append($("<td>").text(formatDateTime24(s.ends_at)));
            row.append($("<td>").text(s.enabled ? "yes" : "no"));
            const actions = $("<td>").addClass("actions");
            actions.append($("<button>").addClass("btn btn-small").text("Edit").on("click", function () { editSilence(s.id); }));
            actions.append($("<button>").addClass("btn btn-danger btn-small").text("Delete").on("click", function () { deleteSilence(s.id); }));
            row.append(actions);
            tbody.append(row);
        });
    });
}

function collectSilencePayload() {
    /* Build silence payload. */
    return { team_id: Number($("#silence-team").val()), name: $("#silence-name").val(), reason: $("#silence-reason").val(), starts_at: $("#silence-starts-at").val(), ends_at: $("#silence-ends-at").val(), matchers: parseJsonInput("#silence-matchers", {}) };
}

function saveSilence() {
    /* Create or update silence. */
    const id = $("#silence-id").val();
    if (id) { apiPut("/api/silences/" + id, collectSilencePayload(), function () { resetSilenceForm(); refreshSilences(); }); }
    else { apiPost("/api/silences", collectSilencePayload(), function () { resetSilenceForm(); refreshSilences(); }); }
}

function editSilence(id) {
    /* Load silence data into the form. */
    const s = silencesCache.find(function (item) { return item.id === id; });
    if (!s) { return; }
    $("#silence-form-title").text("Edit silence #" + id);
    $("#silence-id").val(s.id);
    $("#silence-team").val(s.team_id);
    $("#silence-name").val(s.name);
    $("#silence-reason").val(s.reason || "");
    $("#silence-starts-at").val(isoToDatetimeLocal(s.starts_at));
    $("#silence-ends-at").val(isoToDatetimeLocal(s.ends_at));
    $("#silence-matchers").val(JSON.stringify(s.matchers || {}, null, 2));
}

function deleteSilence(id) {
    /* Disable silence. */
    if (!confirm("Disable this silence?")) { return; }
    apiDelete("/api/silences/" + id, refreshSilences);
}

function resetSilenceForm() {
    /* Reset silence form. */
    $("#silence-form-title").text("Create silence");
    $("#silence-id").val("");
    $("#silence-name").val("");
    $("#silence-reason").val("");
    $("#silence-starts-at").val("");
    $("#silence-ends-at").val("");
    $("#silence-matchers").val('{"labels":{"host":"host1"}}');
}

$(document).on("click", "#save-silence", saveSilence);
$(document).on("click", "#reset-silence-form", resetSilenceForm);
$(document).on("click", "#reload-silences", refreshSilences);
