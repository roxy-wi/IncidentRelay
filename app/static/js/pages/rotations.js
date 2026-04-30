let rotationsCache = [];
let selectedRotationForMembers = null;
let selectedRotationNameForMembers = "";

function loadRotations() {
    /* Load rotations page data. */
    fillTeamSelect("#rotation-team", false);
    fillUserSelect("#member-user");
    fillUserSelect("#override-user");
    updateRotationCadenceFields();
    refreshRotations();
}

function formatSeconds(seconds) {
    /* Format seconds as a compact duration. */
    if (!seconds) { return "-"; }
    if (seconds % 86400 === 0) { return (seconds / 86400) + "d"; }
    if (seconds % 3600 === 0) { return (seconds / 3600) + "h"; }
    if (seconds % 60 === 0) { return (seconds / 60) + "m"; }
    return seconds + "s";
}

function reminderValueToSeconds() {
    /* Convert reminder value and unit to seconds. */
    const value = Number($("#rotation-reminder-value").val() || 5);
    const unit = $("#rotation-reminder-unit").val();

    if (unit === "days") { return value * 86400; }
    if (unit === "hours") { return value * 3600; }
    return value * 60;
}

function setReminderFields(seconds) {
    /* Fill reminder fields from seconds. */
    if (!seconds) { seconds = 300; }

    if (seconds % 86400 === 0) {
        $("#rotation-reminder-value").val(seconds / 86400);
        $("#rotation-reminder-unit").val("days");
    } else if (seconds % 3600 === 0) {
        $("#rotation-reminder-value").val(seconds / 3600);
        $("#rotation-reminder-unit").val("hours");
    } else {
        $("#rotation-reminder-value").val(Math.max(1, Math.floor(seconds / 60)));
        $("#rotation-reminder-unit").val("minutes");
    }
}

function refreshRotations() {
    /* Refresh rotations table and selects. */
    apiGet("/api/rotations" + selectedTeamQuery(), function (rotations) {
        rotationsCache = rotations;

        const tbody = $("#rotations-table");
        const memberSelect = $("#member-rotation");
        const overrideSelect = $("#override-rotation");

        tbody.empty();
        memberSelect.empty();
        overrideSelect.empty();

        if (!rotations.length) {
            tbody.append($("<tr>").append($("<td>").attr("colspan", "9").text("No rotations")));
            $("#rotation-members-table").empty().append($("<tr>").append($("<td>").attr("colspan", "6").text("No rotation selected")));
            return;
        }

        rotations.forEach(function (rotation) {
            const cadence = rotation.rotation_type === "custom"
                ? "every " + rotation.interval_value + " " + rotation.interval_unit
                : rotation.rotation_type;

            const row = $("<tr>");
            row.append($("<td>").text(rotation.id));
            row.append($("<td>").text(rotation.team_slug));
            row.append($("<td>").text(rotation.name));
            row.append($("<td>").text(rotation.current_oncall || "-"));
            row.append($("<td>").text(cadence));
            row.append($("<td>").text(rotation.handoff_time || "-"));
            row.append($("<td>").text(formatSeconds(rotation.reminder_interval_seconds)));
            row.append($("<td>").text(rotation.enabled ? "yes" : "no"));

            const actions = $("<td>").addClass("actions");
            actions.append($("<button>").attr("type", "button").addClass("btn btn-small").text("Edit").on("click", function () { editRotation(rotation.id); }));
            actions.append($("<button>").attr("type", "button").addClass("btn btn-small").text("Members").on("click", function () { selectMemberRotation(rotation.id); }));
            actions.append($("<button>").attr("type", "button").addClass("btn btn-small").text("Overrides").on("click", function () { selectOverrideRotation(rotation.id); }));
            actions.append($("<button>").attr("type", "button").addClass("btn btn-danger btn-small").text("Delete").on("click", function () { deleteRotation(rotation.id); }));
            row.append(actions);

            tbody.append(row);

            if (rotation.enabled) {
                const label = rotation.team_slug + " / " + rotation.name;
                memberSelect.append($("<option>").val(rotation.id).text(label));
                overrideSelect.append($("<option>").val(rotation.id).text(label));
            }
        });

        if (selectedRotationForMembers) {
            loadRotationMembers(selectedRotationForMembers, selectedRotationNameForMembers);
        }

        if (overrideSelect.val()) {
            loadOverrides();
        }
    });
}

function updateRotationCadenceFields() {
    /* Toggle rotation cadence fields. */
    const type = $("#rotation-type").val();
    $("#weekly-options").toggle(type === "weekly");
    $("#custom-interval-options").toggle(type === "custom");
}

function collectRotationPayload() {
    /* Build rotation payload from form fields. */
    return {
        team_id: Number($("#rotation-team").val()),
        name: $("#rotation-name").val(),
        description: $("#rotation-description").val(),
        start_at: $("#rotation-start").val(),
        rotation_type: $("#rotation-type").val(),
        interval_value: Number($("#rotation-interval-value").val()),
        interval_unit: $("#rotation-interval-unit").val(),
        handoff_time: $("#rotation-handoff-time").val(),
        handoff_weekday: Number($("#rotation-weekday").val()),
        reminder_interval_seconds: reminderValueToSeconds(),
        timezone: $("#rotation-timezone").val()
    };
}

function saveRotation() {
    /* Create or update a rotation. */
    const id = $("#rotation-id").val();

    if (id) {
        apiPut("/api/rotations/" + id, collectRotationPayload(), function () {
            resetRotationForm();
            refreshRotations();
        });
        return;
    }

    apiPost("/api/rotations", collectRotationPayload(), function () {
        resetRotationForm();
        refreshRotations();
    });
}

function editRotation(id) {
    /* Load rotation data into the form. */
    const rotation = rotationsCache.find(function (item) { return item.id === id; });

    if (!rotation) {
        return;
    }

    $("#rotation-form-title").text("Edit rotation #" + id);
    $("#rotation-id").val(rotation.id);
    $("#rotation-team").val(rotation.team_id);
    $("#rotation-name").val(rotation.name);
    $("#rotation-description").val(rotation.description || "");
    $("#rotation-start").val(isoToDatetimeLocal(rotation.start_at));
    $("#rotation-type").val(rotation.rotation_type || "daily");
    $("#rotation-interval-value").val(rotation.interval_value || 1);
    $("#rotation-interval-unit").val(rotation.interval_unit || "days");
    $("#rotation-handoff-time").val(rotation.handoff_time || "09:00");
    $("#rotation-weekday").val(rotation.handoff_weekday === null ? 0 : rotation.handoff_weekday);
    setReminderFields(rotation.reminder_interval_seconds);
    $("#rotation-timezone").val(rotation.timezone || "UTC");
    updateRotationCadenceFields();
}

function deleteRotation(id) {
    /* Disable a rotation. */
    if (!confirm("Disable this rotation?")) {
        return;
    }

    apiDelete("/api/rotations/" + id, refreshRotations);
}

function resetRotationForm() {
    /* Reset rotation form. */
    $("#rotation-form-title").text("Create rotation");
    $("#rotation-id").val("");
    $("#rotation-name").val("");
    $("#rotation-description").val("");
    $("#rotation-start").val("");
    $("#rotation-type").val("daily");
    $("#rotation-interval-value").val(1);
    $("#rotation-interval-unit").val("days");
    $("#rotation-handoff-time").val("09:00");
    $("#rotation-weekday").val(0);
    setReminderFields(300);
    $("#rotation-timezone").val("UTC");
    updateRotationCadenceFields();
}

function selectMemberRotation(rotationId) {
    /* Select a rotation in the member block and load members. */
    $("#member-rotation").val(String(rotationId));
    const rotation = rotationsCache.find(function (item) { return item.id === Number(rotationId); });
    loadRotationMembers(rotationId, rotation ? rotation.name : "rotation #" + rotationId);
}

function loadRotationMembers(rotationId, rotationName) {
    /* Load members for one rotation. */
    selectedRotationForMembers = rotationId;
    selectedRotationNameForMembers = rotationName;

    $("#rotation-members-title").text("Rotation members: " + rotationName);
    $("#member-rotation").val(String(rotationId));

    const tbody = $("#rotation-members-table");
    tbody.empty();

    apiGet("/api/rotations/" + rotationId + "/members", function (members) {
        if (!members.length) {
            tbody.append($("<tr>").append($("<td>").attr("colspan", "6").text("No members")));
            return;
        }

        members.forEach(function (member) {
            const row = $("<tr>");
            row.append($("<td>").text(member.user_id));
            row.append($("<td>").text(member.username));
            row.append($("<td>").text(member.display_name || "-"));
            row.append($("<td>").text(member.position));
            row.append($("<td>").text(member.active ? "yes" : "no"));

            const actions = $("<td>").addClass("actions");
            actions.append($("<button>").attr("type", "button").addClass("btn btn-small").text("Edit").on("click", function () {
                editRotationMember(member);
            }));
            actions.append($("<button>").attr("type", "button").addClass("btn btn-danger btn-small").text("Disable").on("click", function () {
                disableRotationMember(member.id);
            }));
            row.append(actions);
            tbody.append(row);
        });
    });
}

function editRotationMember(member) {
    /* Load rotation member data into the form. */
    $("#rotation-member-form-title").text("Edit rotation member #" + member.id);
    $("#rotation-member-id").val(member.id);
    $("#member-user").val(String(member.user_id)).prop("disabled", true);
    $("#member-position").val(member.position);
    $("#member-active").prop("checked", !!member.active);
}

function resetRotationMemberForm() {
    /* Reset rotation member form. */
    $("#rotation-member-form-title").text("Add member");
    $("#rotation-member-id").val("");
    $("#member-user").prop("disabled", false);
    $("#member-position").val(0);
    $("#member-active").prop("checked", true);
}

function saveRotationMember() {
    /* Create or update a rotation member. */
    const rotationId = $("#member-rotation").val();
    const memberId = $("#rotation-member-id").val();

    if (!rotationId) {
        alert("Select a rotation first.");
        return;
    }

    if (memberId) {
        apiPut("/api/rotations/members/" + memberId, {
            position: Number($("#member-position").val()),
            active: $("#member-active").is(":checked")
        }, function () {
            resetRotationMemberForm();
            loadRotationMembers(rotationId, selectedRotationNameForMembers || $("#member-rotation option:selected").text());
            refreshRotations();
        });
        return;
    }

    apiPost("/api/rotations/" + rotationId + "/members", {
        user_id: Number($("#member-user").val()),
        position: Number($("#member-position").val())
    }, function () {
        resetRotationMemberForm();
        loadRotationMembers(rotationId, $("#member-rotation option:selected").text());
        refreshRotations();
    });
}

function disableRotationMember(memberId) {
    /* Disable a rotation member. */
    if (!confirm("Disable this rotation member?")) {
        return;
    }

    apiDelete("/api/rotations/members/" + memberId, function () {
        loadRotationMembers(selectedRotationForMembers, selectedRotationNameForMembers);
        refreshRotations();
    });
}

function selectOverrideRotation(rotationId) {
    /* Select a rotation in the override block and load its overrides. */
    $("#override-rotation").val(String(rotationId));
    loadOverrides();
}

function loadOverrides() {
    /* Load overrides for the selected rotation. */
    const rotationId = $("#override-rotation").val();
    const tbody = $("#overrides-table");

    tbody.empty();

    if (!rotationId) {
        tbody.append($("<tr>").append($("<td>").attr("colspan", "6").text("No rotation selected")));
        return;
    }

    const rotation = rotationsCache.find(function (item) { return item.id === Number(rotationId); });
    $("#overrides-title").text("Overrides" + (rotation ? ": " + rotation.name : ""));

    apiGet("/api/rotations/" + rotationId + "/overrides", function (overrides) {
        if (!overrides.length) {
            tbody.append($("<tr>").append($("<td>").attr("colspan", "6").text("No overrides")));
            return;
        }

        overrides.forEach(function (override) {
            const row = $("<tr>");
            row.append($("<td>").text(override.id));
            row.append($("<td>").text(override.display_name || override.username));
            row.append($("<td>").text(formatDateTime24(override.starts_at)));
            row.append($("<td>").text(formatDateTime24(override.ends_at)));
            row.append($("<td>").text(override.reason || "-"));

            const actions = $("<td>").addClass("actions");
            actions.append($("<button>").attr("type", "button").addClass("btn btn-danger btn-small").text("Delete").on("click", function () {
                deleteOverride(override.id);
            }));
            row.append(actions);

            tbody.append(row);
        });
    });
}

function createOverride() {
    /* Create a temporary rotation override. */
    const rotationId = $("#override-rotation").val();

    if (!rotationId) {
        alert("Select a rotation first.");
        return;
    }

    apiPost("/api/rotations/" + rotationId + "/overrides", {
        user_id: Number($("#override-user").val()),
        starts_at: $("#override-starts-at").val(),
        ends_at: $("#override-ends-at").val(),
        reason: $("#override-reason").val() || null
    }, function () {
        $("#override-reason").val("");
        loadOverrides();
    });
}

function deleteOverride(overrideId) {
    /* Delete a rotation override. */
    if (!confirm("Delete this override?")) {
        return;
    }

    apiDelete("/api/rotations/overrides/" + overrideId, loadOverrides);
}

$(document).on("change", "#rotation-type", updateRotationCadenceFields);
$(document).on("change", "#override-rotation", loadOverrides);
$(document).on("change", "#member-rotation", function () {
    const rotationId = $("#member-rotation").val();
    const rotation = rotationsCache.find(function (item) { return item.id === Number(rotationId); });
    if (rotationId) {
        loadRotationMembers(rotationId, rotation ? rotation.name : "rotation #" + rotationId);
    }
});
$(document).on("click", "#save-rotation", saveRotation);
$(document).on("click", "#reset-rotation-form", resetRotationForm);
$(document).on("click", "#reload-rotations", refreshRotations);
$(document).on("click", "#reload-overrides", loadOverrides);
$(document).on("click", "#create-override", createOverride);
$(document).on("click", "#save-rotation-member", saveRotationMember);
$(document).on("click", "#reset-rotation-member-form", resetRotationMemberForm);
