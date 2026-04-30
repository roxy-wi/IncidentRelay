let rotationsCache = [];
let selectedRotationForMembers = null;
let selectedRotationNameForMembers = "";
let selectedRotationDetailsId = null;

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

function rotationInitials(value) {
    /*
     * Build initials for user avatar.
     */
    return String(value || "?")
        .trim()
        .split(/\s+/)
        .slice(0, 2)
        .map(function (part) {
            return part.substring(0, 1).toUpperCase();
        })
        .join("") || "?";
}


function getRotationCurrentUser(rotation) {
    /*
     * Return current on-call user label.
     */
    return rotation.current_oncall || rotation.current_user || rotation.current_username || "";
}


function getRotationSearchText(rotation) {
    /*
     * Build searchable rotation text.
     */
    return [
        rotation.id,
        rotation.team_slug,
        rotation.team_name,
        rotation.name,
        rotation.description,
        rotation.rotation_type,
        rotation.handoff_time,
        getRotationCurrentUser(rotation),
        rotation.enabled ? "active" : "inactive"
    ].join(" ").toLowerCase();
}


function getFilteredRotations() {
    /*
     * Apply client-side filters to rotationsCache.
     */
    const query = String($("#rotations-search").val() || "").trim().toLowerCase();
    const team = String($("#rotations-team-filter").val() || "");
    const status = String($("#rotations-status-filter").val() || "");

    return rotationsCache.filter(function (rotation) {
        if (team && String(rotation.team_slug || "") !== team) {
            return false;
        }

        if (status === "active" && !rotation.enabled) {
            return false;
        }

        if (status === "inactive" && rotation.enabled) {
            return false;
        }

        if (!query) {
            return true;
        }

        return getRotationSearchText(rotation).indexOf(query) !== -1;
    });
}


function fillRotationsTeamFilter(rotations) {
    /*
     * Fill table team filter from loaded rotations.
     */
    const select = $("#rotations-team-filter");
    const selected = select.val();

    const teams = {};

    rotations.forEach(function (rotation) {
        if (rotation.team_slug) {
            teams[rotation.team_slug] = rotation.team_name || rotation.team_slug;
        }
    });

    select.empty();
    select.append($("<option>").val("").text("All teams"));

    Object.keys(teams).sort().forEach(function (slug) {
        select.append($("<option>").val(slug).text(teams[slug]));
    });

    if (selected && teams[selected]) {
        select.val(selected);
    }
}


function renderRotationsSummary(rotations) {
    /*
     * Render rotations summary cards.
     */
    rotations = Array.isArray(rotations) ? rotations : [];

    let active = 0;
    let oncall = 0;
    let reminders = 0;

    rotations.forEach(function (rotation) {
        if (rotation.enabled) {
            active += 1;
        }

        if (getRotationCurrentUser(rotation)) {
            oncall += 1;
        }

        if (Number(rotation.reminder_interval_seconds || 0) > 0) {
            reminders += 1;
        }
    });

    $("#rotations-summary-total").text(rotations.length);
    $("#rotations-summary-active").text(active);
    $("#rotations-summary-oncall").text(oncall);
    $("#rotations-summary-reminders").text(reminders);
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

function refreshRotations(doneCallback) {
    /*
     * Refresh rotations table and selects.
     */
    apiGet("/api/rotations" + selectedTeamQuery(), function (rotations) {
        rotations = Array.isArray(rotations) ? rotations : [];
        rotationsCache = rotations;

        renderRotationsSummary(rotationsCache);
        renderRotationsInboxCounter(rotationsCache, rotationsCache);

        const tbody = $("#rotations-table");
        const memberSelect = $("#member-rotation");
        const overrideSelect = $("#override-rotation");
        const savedMemberRotationId = selectedRotationForMembers || memberSelect.val();
        const savedOverrideRotationId = overrideSelect.val();

        tbody.empty();
        memberSelect.empty();
        overrideSelect.empty();

        if (!rotations.length) {
            tbody.append(
                $("<tr>").append(
                    $("<td>")
                        .attr("colspan", "9")
                        .addClass("rotations-empty-cell")
                        .text("No rotations")
                )
            );

            $("#rotation-members-table")
                .empty()
                .append(
                    $("<tr>").append(
                        $("<td>")
                            .attr("colspan", "6")
                            .addClass("rotations-empty-cell")
                            .text("No rotation selected")
                    )
                );

            $("#overrides-table")
                .empty()
                .append(
                    $("<tr>").append(
                        $("<td>")
                            .attr("colspan", "6")
                            .addClass("rotations-empty-cell")
                            .text("No rotation selected")
                    )
                );

            if (typeof doneCallback === "function") {
                doneCallback();
            }

            return;
        }

        rotations.forEach(function (rotation) {
            const cadence = rotation.rotation_type === "custom"
                ? "every " + rotation.interval_value + " " + rotation.interval_unit
                : rotation.rotation_type;

            const row = $("<tr>");

            // row.append($("<td>").text('#' + rotation.id));
             row.append(
                $("<td>").append(
                    $("<button>")
                        .attr("type", "button")
                        .addClass("rotation-name-button")
                        .text('#' + rotation.id)
                        .on("click", function () {
                            renderRotationDetails(rotation);
                        })
                )
            );
            row.append($("<td>").text(rotation.team_slug));
            row.append(
                $("<td>").append(
                    $("<button>")
                        .attr("type", "button")
                        .addClass("rotation-name-button")
                        .text(rotation.name || "-")
                        .on("click", function () {
                            renderRotationDetails(rotation);
                        })
                )
            );
            row.append($("<td>").text(cadence));
            row.append($("<td>").text(rotation.current_oncall || "-"));
            row.append($("<td>").text(rotation.handoff_time || "-"));
            row.append($("<td>").text(formatSeconds(rotation.reminder_interval_seconds)));
            row.append($("<td>").text(rotation.enabled ? "yes" : "no"));

            const actions = $("<td>").addClass("actions");

            actions.append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("btn btn-small")
                    .text("Edit")
                    .on("click", function () {
                        editRotation(rotation.id);
                    })
            );

            actions.append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("btn btn-small")
                    .text("Members")
                    .on("click", function () {
                        selectMemberRotation(rotation.id);
                    })
            );

            actions.append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("btn btn-small")
                    .text("Overrides")
                    .on("click", function () {
                        selectOverrideRotation(rotation.id);
                    })
            );

            actions.append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("btn btn-danger btn-small")
                    .text("Remove")
                    .on("click", function () {
                        deleteRotation(rotation.id);
                    })
            );

            row.append(actions);
            tbody.append(row);

            if (rotation.enabled) {
                const label = rotation.team_slug + " / " + rotation.name;

                memberSelect.append(
                    $("<option>")
                        .val(rotation.id)
                        .text(label)
                );

                overrideSelect.append(
                    $("<option>")
                        .val(rotation.id)
                        .text(label)
                );
            }
        });

        if (savedMemberRotationId) {
            memberSelect.val(String(savedMemberRotationId));
        }

        if (savedOverrideRotationId) {
            overrideSelect.val(String(savedOverrideRotationId));
        }

        if (typeof doneCallback === "function") {
            doneCallback();
            return;
        }

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
            closeRotationFormModal();
            resetRotationForm();
            refreshRotations();
        });
        return;
    }

    apiPost("/api/rotations", collectRotationPayload(), function () {
        closeRotationFormModal();
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
    openRotationFormModal();
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
    /*
     * Select a rotation, load eligible users, load members and open modal.
     */
    $("#member-rotation").val(String(rotationId));

    const rotation = rotationsCache.find(function (item) {
        return Number(item.id) === Number(rotationId);
    });

    if (!rotation) {
        return;
    }

    fillRotationEligibleUserSelect("#member-user", rotationId, function () {
        loadRotationMembers(rotationId, rotation.name || "rotation #" + rotationId);
        openRotationMembersModal();
    });
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
            actions.append($("<button>").attr("type", "button").addClass("btn btn-warning btn-small").text("Disable").on("click", function () {
                disableRotationMember(member.id);
            }));
            actions.append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("btn btn-danger btn-small")
                    .text("Remove")
                    .on("click", function () {
                        removeRotationMember(member.id);
                    })
            );
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
    /*
     * Create or update a rotation member.
     */
    const rotationId = $("#member-rotation").val();
    const memberId = $("#rotation-member-id").val();

    if (!rotationId) {
        alert("Select a rotation first.");
        return;
    }

    const savedRotationId = rotationId;
    const savedRotationName = selectedRotationNameForMembers || $("#member-rotation option:selected").text();

    if (memberId) {
        apiPut("/api/rotations/members/" + memberId, {
            position: Number($("#member-position").val()),
            active: $("#member-active").is(":checked")
        }, function () {
            resetRotationMemberForm();

            selectedRotationForMembers = savedRotationId;
            selectedRotationNameForMembers = savedRotationName;

            refreshRotations(function () {
                $("#member-rotation").val(String(savedRotationId));
                loadRotationMembers(savedRotationId, savedRotationName);
            });
        });

        return;
    }

    apiPost("/api/rotations/" + rotationId + "/members", {
        user_id: Number($("#member-user").val()),
        position: Number($("#member-position").val())
    }, function () {
        resetRotationMemberForm();

        selectedRotationForMembers = savedRotationId;
        selectedRotationNameForMembers = savedRotationName;

        refreshRotations(function () {
            $("#member-rotation").val(String(savedRotationId));
            loadRotationMembers(savedRotationId, savedRotationName);
        });
    });
}

function disableRotationMember(memberId) {
    /* Disable a rotation member. */
    if (!confirm("Disable this rotation member?")) {
        return;
    }

    apiPost("/api/rotations/members/" + memberId + "/disable", function () {
        loadRotationMembers(selectedRotationForMembers, selectedRotationNameForMembers);
        refreshRotations();
    });
}

function selectOverrideRotation(rotationId) {
    /*
     * Select a rotation, load eligible users, load overrides and open modal.
     */
    $("#override-rotation").val(String(rotationId));

    const rotation = rotationsCache.find(function (item) {
        return Number(item.id) === Number(rotationId);
    });

    if (!rotation) {
        return;
    }

    fillRotationEligibleUserSelect("#override-user", rotationId, function () {
        loadOverrides();
        openRotationOverridesModal();
    });
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
$(document).on("change", "#member-rotation", function () {
    const rotationId = $(this).val();

    const rotation = rotationsCache.find(function (item) {
        return Number(item.id) === Number(rotationId);
    });

    fillRotationEligibleUserSelect("#member-user", rotationId, function () {
        loadRotationMembers(rotationId, rotation ? rotation.name : "rotation #" + rotationId);
    });
});

$(document).on("change", "#override-rotation", function () {
    const rotationId = $(this).val();

    fillRotationEligibleUserSelect("#override-user", rotationId, loadOverrides);
});
$(document).on("click", "#save-rotation", saveRotation);
$(document).on("click", "#reset-rotation-form", resetRotationForm);
$(document).on("click", "#reload-rotations", refreshRotations);
$(document).on("click", "#reload-overrides", loadOverrides);
$(document).on("click", "#create-override", createOverride);
$(document).on("click", "#save-rotation-member", saveRotationMember);
$(document).on("click", "#reset-rotation-member-form", resetRotationMemberForm);

function renderRotationsTable() {
    /*
     * Render rotations table using current filters.
     */
    const tbody = $("#rotations-table");
    const rotations = getFilteredRotations();

    tbody.empty();

    $("#rotations-filtered-count").text(rotations.length);
    $("#rotations-total-count").text(rotationsCache.length);

    if (!rotations.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>")
                    .attr("colspan", "8")
                    .addClass("rotations-empty-cell")
                    .text("No rotations")
            )
        );
        return;
    }

    rotations.forEach(function (rotation) {
        tbody.append(renderRotationRow(rotation));
    });
}


function renderRotationRow(rotation) {
    /*
     * Render one rotation row.
     */
    const row = $("<tr>");

    const rotationName = $("<button>")
        .attr("type", "button")
        .addClass("rotation-name-button")
        .text(rotation.name || "-")
        .on("click", function () {
            renderRotationDetails(rotation);
        });

    row.append(
        $("<td>")
            .append(rotationName)
            .append(
                $("<div>")
                    .addClass("rotation-row-subtitle")
                    .text(rotation.description || "Rotation #" + rotation.id)
            )
    );

    row.append(
        $("<td>").append(
            $("<span>")
                .addClass("rotation-team-pill")
                .text(rotation.team_slug || rotation.team_name || "-")
        )
    );

    row.append($("<td>").text(getRotationCadence(rotation)));

    const currentUser = getRotationCurrentUser(rotation);

    if (currentUser) {
        row.append(
            $("<td>").append(
                $("<div>")
                    .addClass("rotation-current-user")
                    .append($("<div>").addClass("rotation-user-avatar").text(rotationInitials(currentUser)))
                    .append(
                        $("<div>")
                            .append($("<div>").addClass("rotation-user-name").text(currentUser))
                            .append($("<div>").addClass("rotation-user-meta").text("Currently on call"))
                    )
            )
        );
    } else {
        row.append($("<td>").append($("<span>").addClass("rotation-empty-user").text("-")));
    }

    row.append($("<td>").text(rotation.handoff_time || "-"));
    row.append($("<td>").text(formatSeconds(rotation.reminder_interval_seconds)));

    row.append(
        $("<td>").append(
            $("<span>")
                .addClass("rotation-status-pill")
                .addClass(rotation.enabled ? "rotation-status-active" : "rotation-status-inactive")
                .text(rotation.enabled ? "Active" : "Inactive")
        )
    );

    const actions = $("<div>").addClass("table-actions");

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-small")
            .text("Edit")
            .on("click", function () {
                editRotation(rotation.id);
            })
    );

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-small")
            .text("Members")
            .on("click", function () {
                selectMemberRotation(rotation.id);
            })
    );

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-small")
            .text("Overrides")
            .on("click", function () {
                selectOverrideRotation(rotation.id);
            })
    );

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-danger btn-small")
            .text("Disable")
            .on("click", function () {
                deleteRotation(rotation.id);
            })
    );

    row.append($("<td>").addClass("actions-cell").append(actions));

    return row;
}

$(document).on("input", "#rotations-search", renderRotationsTable);
$(document).on("change", "#rotations-team-filter, #rotations-status-filter", renderRotationsTable);
function openRotationFormModal() {
    /*
     * Open rotation create/edit modal.
     */
    $("#rotation-form-modal")
        .css("display", "flex")
        .addClass("is-open");

    $("body").addClass("modal-open");
}


function closeRotationFormModal() {
    /*
     * Close rotation create/edit modal.
     */
    $("#rotation-form-modal")
        .css("display", "none")
        .removeClass("is-open");

    $("body").removeClass("modal-open");
}


function openCreateRotationModal() {
    /*
     * Reset form and open modal in create mode.
     */
    resetRotationForm();
    $("#rotation-form-title").text("Create rotation");
    openRotationFormModal();
}
$(document).on("click", "#open-rotation-create-modal", openCreateRotationModal);

$(document).on("click", "#close-rotation-form-modal", closeRotationFormModal);

$(document).on("click", "#rotation-form-modal", function (event) {
    if (event.target === this) {
        closeRotationFormModal();
    }
});

$(document).on("keydown", function (event) {
    if (event.key === "Escape" && $("#rotation-form-modal").hasClass("is-open")) {
        closeRotationFormModal();
    }
});
function openRotationMembersModal() {
    /*
     * Open rotation members modal.
     */
    $("#rotation-members-modal")
        .css("display", "flex")
        .addClass("is-open");

    $("body").addClass("modal-open");
}


function closeRotationMembersModal() {
    /*
     * Close rotation members modal.
     */
    $("#rotation-members-modal")
        .css("display", "none")
        .removeClass("is-open");

    $("body").removeClass("modal-open");
}


function openRotationOverridesModal() {
    /*
     * Open rotation overrides modal.
     */
    $("#rotation-overrides-modal")
        .css("display", "flex")
        .addClass("is-open");

    $("body").addClass("modal-open");
}


function closeRotationOverridesModal() {
    /*
     * Close rotation overrides modal.
     */
    $("#rotation-overrides-modal")
        .css("display", "none")
        .removeClass("is-open");

    $("body").removeClass("modal-open");
}
$(document).on("click", "#close-rotation-members-modal, #close-rotation-members-modal-footer", closeRotationMembersModal);

$(document).on("click", "#close-rotation-overrides-modal, #close-rotation-overrides-modal-footer", closeRotationOverridesModal);

$(document).on("click", "#rotation-members-modal", function (event) {
    if (event.target === this) {
        closeRotationMembersModal();
    }
});

$(document).on("click", "#rotation-overrides-modal", function (event) {
    if (event.target === this) {
        closeRotationOverridesModal();
    }
});

$(document).on("keydown", function (event) {
    if (event.key !== "Escape") {
        return;
    }

    if ($("#rotation-members-modal").hasClass("is-open")) {
        closeRotationMembersModal();
        return;
    }

    if ($("#rotation-overrides-modal").hasClass("is-open")) {
        closeRotationOverridesModal();
    }
});
function getRotationCadence(rotation) {
    /*
     * Return human-readable rotation cadence.
     */
    if (rotation.rotation_type === "custom") {
        return "every " + rotation.interval_value + " " + rotation.interval_unit;
    }

    return rotation.rotation_type || "-";
}

function rotationDetailsItem(label, value) {
    /*
     * Render one details item.
     */
    return $("<div>")
        .addClass("details-item")
        .append($("<div>").addClass("details-label").text(label))
        .append($("<div>").addClass("details-value").text(value || "-"));
}


function renderRotationDetails(rotation) {
    /*
     * Render selected rotation in right-side details panel.
     */
    selectedRotationDetailsId = rotation.id;

    $("#rotation-details-subtitle").text(
        (rotation.team_slug || rotation.team_name || "-") +
        " / " +
        (rotation.enabled ? "Active" : "Inactive")
    );

    const body = $("#rotation-details-body");
    body.empty();

    body.append(
        $("<div>")
            .addClass("details-list")
            .append(rotationDetailsItem("Name", rotation.name))
            .append(rotationDetailsItem("Team", rotation.team_name || rotation.team_slug))
            .append(rotationDetailsItem("Current on call", getRotationCurrentUser(rotation) || "-"))
            .append(rotationDetailsItem("Cadence", getRotationCadence(rotation)))
            .append(rotationDetailsItem("Handoff time", rotation.handoff_time))
            .append(rotationDetailsItem("Reminder", formatSeconds(rotation.reminder_interval_seconds)))
            .append(rotationDetailsItem("Timezone", rotation.timezone))
            .append(rotationDetailsItem("Description", rotation.description))
    );

    body.append(
        $("<div>")
            .addClass("details-actions")
            .append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("btn btn-small")
                    .text("Edit rotation")
                    .on("click", function () {
                        editRotation(rotation.id);
                    })
            )
            .append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("btn btn-small")
                    .text("Members")
                    .on("click", function () {
                        selectMemberRotation(rotation.id);
                    })
            )
            .append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("btn btn-small")
                    .text("Overrides")
                    .on("click", function () {
                        selectOverrideRotation(rotation.id);
                    })
            )
    );
}


function renderRotationDetailsEmpty() {
    /*
     * Render empty details state.
     */
    selectedRotationDetailsId = null;

    $("#rotation-details-subtitle").text("Select a rotation");

    $("#rotation-details-body").html(
        '<div class="details-empty">' +
        'Click a rotation name to see current on-call user, cadence, reminder and quick actions.' +
        '</div>'
    );
}
function renderRotationsInboxCounter(filteredRotations, allRotations) {
    /*
     * Render "Showing X of Y rotations" counter.
     */
    filteredRotations = Array.isArray(filteredRotations) ? filteredRotations : [];
    allRotations = Array.isArray(allRotations) ? allRotations : [];

    $("#rotations-filtered-count").text(filteredRotations.length);
    $("#rotations-total-count").text(allRotations.length);
}
function removeRotationMember(memberId) {
    /*
     * Permanently remove a user from rotation.
     */
    if (!confirm("Remove this user from the rotation?")) {
        return;
    }

    apiDelete("/api/rotations/members/" + memberId, function () {
        resetRotationMemberForm();
        loadRotationMembers(selectedRotationForMembers, selectedRotationNameForMembers);
        refreshRotations();
    });
}
function fillRotationEligibleUserSelect(selector, rotationId, callback) {
    /*
     * Fill user select with users eligible for this rotation.
     */
    const select = $(selector);
    select.empty();

    if (!rotationId) {
        select.append(
            $("<option>")
                .val("")
                .text("Select rotation first")
        );

        if (typeof callback === "function") {
            callback([]);
        }

        return;
    }

    apiGet("/api/rotations/" + rotationId + "/eligible-users", function (users) {
        users = asArray(users);

        select.empty();

        if (!users.length) {
            select.append(
                $("<option>")
                    .val("")
                    .text("No active team members")
            );
        }

        users.forEach(function (user) {
            select.append(
                $("<option>")
                    .val(user.user_id)
                    .text("#" + user.user_id + " " + (user.display_name || user.username || "user"))
            );
        });

        if (typeof callback === "function") {
            callback(users);
        }
    });
}
