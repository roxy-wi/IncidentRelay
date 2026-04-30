let teamsCache = [];
let selectedTeamForMembers = null;
let selectedTeamNameForMembers = "";
let selectedTeamDetailsId = null;


function loadTeams() {
    /*
     * Load teams page.
     */
    loadTeamGroups(function () {
        refreshTeams();
        fillUserSelect("#team-member-user", null, "/api/users?all=1");
    });
}


function loadTeamGroups(callback) {
    /*
     * Load groups into the team form.
     */
    fillGroupSelect("#team-group", false, function (groups) {
        groups = asArray(groups);

        if (!groups.length) {
            $("#team-group").append(
                $("<option>")
                    .val("")
                    .text("No groups available")
            );
        }

        if (typeof callback === "function") {
            callback(groups);
        }
    });
}


function refreshTeams() {
    /*
     * Refresh teams table and details.
     */
    apiGet("/api/teams", function (teams) {
        teamsCache = asArray(teams);

        renderTeamsSummary(teamsCache);
        fillTeamsGroupFilter(teamsCache);
        renderTeamsTable();
        restoreTeamDetails();

        if ($("#team-members-modal").hasClass("is-open") && selectedTeamForMembers) {
            loadTeamMembers(selectedTeamForMembers, selectedTeamNameForMembers);
        }
    });
}


function renderTeamsSummary(teams) {
    /*
     * Render teams summary cards.
     */
    teams = asArray(teams);

    const active = teams.filter(function (team) {
        return !!team.active;
    }).length;

    const escalation = teams.filter(function (team) {
        return !!team.escalation_enabled;
    }).length;

    const groups = {};

    teams.forEach(function (team) {
        if (team.group_slug || team.group_id) {
            groups[team.group_slug || team.group_id] = true;
        }
    });

    $("#teams-summary-total").text(teams.length);
    $("#teams-summary-active").text(active);
    $("#teams-summary-escalation").text(escalation);
    $("#teams-summary-groups").text(Object.keys(groups).length);
}


function fillTeamsGroupFilter(teams) {
    /*
     * Fill group filter from loaded teams.
     */
    const filter = $("#teams-group-filter");
    const selected = filter.val();
    const groups = {};

    asArray(teams).forEach(function (team) {
        if (team.group_slug) {
            groups[team.group_slug] = true;
        }
    });

    filter.empty();
    filter.append($("<option>").val("").text("All groups"));

    Object.keys(groups).sort().forEach(function (groupSlug) {
        filter.append($("<option>").val(groupSlug).text(groupSlug));
    });

    if (selected && groups[selected]) {
        filter.val(selected);
    }
}


function getTeamSearchText(team) {
    /*
     * Build searchable team text.
     */
    return [
        team.id,
        team.group_slug,
        team.slug,
        team.name,
        team.description,
        team.escalation_enabled ? "escalation" : "no escalation",
        team.active ? "active" : "inactive"
    ].join(" ").toLowerCase();
}


function getFilteredTeams() {
    /*
     * Apply client-side filters.
     */
    const query = String($("#teams-search").val() || "").trim().toLowerCase();
    const group = String($("#teams-group-filter").val() || "");
    const status = String($("#teams-status-filter").val() || "");

    return teamsCache.filter(function (team) {
        if (group && team.group_slug !== group) {
            return false;
        }

        if (status === "active" && !team.active) {
            return false;
        }

        if (status === "inactive" && team.active) {
            return false;
        }

        if (!query) {
            return true;
        }

        return getTeamSearchText(team).indexOf(query) !== -1;
    });
}


function renderTeamsCounter(filteredTeams, allTeams) {
    /*
     * Render "Showing X of Y teams".
     */
    filteredTeams = asArray(filteredTeams);
    allTeams = asArray(allTeams);

    $("#teams-filtered-count").text(filteredTeams.length);
    $("#teams-total-count").text(allTeams.length);
}


function renderTeamsTable() {
    /*
     * Render filtered teams table.
     */
    const tbody = $("#teams-table");
    const teams = getFilteredTeams();

    tbody.empty();
    renderTeamsCounter(teams, teamsCache);

    if (!teams.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>")
                    .attr("colspan", "6")
                    .addClass("teams-empty-cell")
                    .text("No teams")
            )
        );
        return;
    }

    teams.forEach(function (team) {
        tbody.append(renderTeamRow(team));
    });
}


function renderTeamRow(team) {
    /*
     * Render one team row.
     */
    const row = $("<tr>");

    row.append(
        $("<td>")
            .append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("team-name-button")
                    .text(team.name || "-")
                    .on("click", function () {
                        renderTeamDetails(team);
                    })
            )
            .append(
                $("<div>")
                    .addClass("team-row-subtitle")
                    .text("Team #" + team.id)
            )
    );

    row.append(
        $("<td>").append(
            $("<span>")
                .addClass("team-pill")
                .text(team.group_slug || "-")
        )
    );

    row.append($("<td>").text(team.slug || "-"));

    row.append(
        $("<td>").append(
            $("<span>")
                .addClass("team-escalation-pill")
                .addClass(team.escalation_enabled ? "team-escalation-enabled" : "team-escalation-disabled")
                .text(team.escalation_enabled ? "after " + (team.escalation_after_reminders || 0) : "Disabled")
        )
    );

    row.append(
        $("<td>").append(
            $("<span>")
                .addClass("team-status-pill")
                .addClass(team.active ? "team-status-active" : "team-status-inactive")
                .text(team.active ? "Active" : "Inactive")
        )
    );

    row.append(
        $("<td>")
            .addClass("actions-cell")
            .append(renderTeamActions(team))
    );

    return row;
}


function renderTeamActions(team) {
    /*
     * Render team actions.
     */
    const actions = $("<div>").addClass("table-actions");

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-small")
            .text("Edit")
            .on("click", function () {
                editTeam(team.id);
            })
    );

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-small")
            .text("Members")
            .on("click", function () {
                openTeamMembers(team.id, team.name);
            })
    );

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-danger btn-small")
            .text("Disable")
            .on("click", function () {
                deleteTeam(team.id);
            })
    );

    return actions;
}


function teamDetailsItem(label, value) {
    /*
     * Render one team details item.
     */
    return $("<div>")
        .addClass("details-item")
        .append($("<div>").addClass("details-label").text(label))
        .append($("<div>").addClass("details-value").text(value || "-"));
}


function renderTeamDetails(team) {
    /*
     * Render selected team details.
     */
    selectedTeamDetailsId = team.id;

    $("#team-details-subtitle").text(
        (team.group_slug || "-") + " / " + (team.active ? "Active" : "Inactive")
    );

    $("#team-details-body")
        .empty()
        .append(
            $("<div>")
                .addClass("details-list")
                .append(teamDetailsItem("Name", team.name))
                .append(teamDetailsItem("Slug", team.slug))
                .append(teamDetailsItem("Group", team.group_slug))
                .append(teamDetailsItem("Description", team.description))
                .append(teamDetailsItem("Escalation", team.escalation_enabled ? "Enabled" : "Disabled"))
                .append(teamDetailsItem("Escalate after reminders", team.escalation_after_reminders || 0))
                .append(teamDetailsItem("Status", team.active ? "Active" : "Inactive"))
        )
        .append(
            $("<div>")
                .addClass("details-actions")
                .append(
                    $("<button>")
                        .attr("type", "button")
                        .addClass("btn btn-small")
                        .text("Edit team")
                        .on("click", function () {
                            editTeam(team.id);
                        })
                )
                .append(
                    $("<button>")
                        .attr("type", "button")
                        .addClass("btn btn-small")
                        .text("Members")
                        .on("click", function () {
                            openTeamMembers(team.id, team.name);
                        })
                )
        );
}


function restoreTeamDetails() {
    /*
     * Restore details panel after reload.
     */
    if (!teamsCache.length) {
        renderTeamDetailsEmpty();
        return;
    }

    if (selectedTeamDetailsId) {
        const selected = teamsCache.find(function (team) {
            return Number(team.id) === Number(selectedTeamDetailsId);
        });

        if (selected) {
            renderTeamDetails(selected);
            return;
        }
    }

    renderTeamDetails(teamsCache[0]);
}


function renderTeamDetailsEmpty() {
    /*
     * Render empty details state.
     */
    selectedTeamDetailsId = null;

    $("#team-details-subtitle").text("Select a team");
    $("#team-details-body").html(
        '<div class="details-empty">' +
        'Click a team name to inspect group, escalation settings and quick actions.' +
        '</div>'
    );
}


function openTeamMembers(teamId, teamName) {
    /*
     * Open team members modal and load members.
     */
    loadTeamMembers(teamId, teamName);
    openTeamMembersModal();
}


function loadTeamMembers(teamId, teamName) {
    /*
     * Load members for one team.
     */
    selectedTeamForMembers = teamId;
    selectedTeamNameForMembers = teamName;

    $("#team-members-title").text("Team members: " + teamName);
    $("#team-member-team-id").val(teamId);
    $("#team-member-team-name").val(teamName);
    $("#team-member-team-label").val(teamName);

    const tbody = $("#team-members-table");
    tbody.empty();

    apiGet("/api/teams/" + teamId + "/users", function (members) {
        members = asArray(members);

        if (!members.length) {
            tbody.append(
                $("<tr>").append(
                    $("<td>")
                        .attr("colspan", "6")
                        .addClass("teams-empty-cell")
                        .text("No members")
                )
            );
            return;
        }

        members.forEach(function (member) {
            tbody.append(renderTeamMemberRow(member));
        });
    });
}


function renderTeamMemberRow(member) {
    /*
     * Render one team member row.
     */
    const row = $("<tr>");
    console.log(member);
    row.append($("<td>").text(member.user_id));
    row.append($("<td>").text(member.username));
    row.append($("<td>").text(member.display_name || "-"));

    row.append(
        $("<td>").append(
            $("<span>")
                .addClass("team-role-pill")
                .addClass(member.role === "rw" ? "team-role-rw" : "team-role-read-only")
                .text(member.role === "rw" ? "Read/write" : "Read only")
        )
    );

    row.append(
        $("<td>").append(
            $("<span>")
                .addClass("team-status-pill")
                .addClass(member.active ? "team-status-active" : "team-status-inactive")
                .text(member.active ? "Active" : "Inactive")
        )
    );

    const actions = $("<div>").addClass("table-actions");

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-small")
            .text("Edit")
            .on("click", function () {
                editTeamMember(member);
            })
    );

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-warning btn-small")
            .text("Disable")
            .on("click", function () {
                disableTeamMember(member.id);
            })
    );

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-danger btn-small")
            .text("Remove")
            .on("click", function () {
                removeTeamMember(member.id);
            })
    );

    row.append($("<td>").addClass("actions-cell").append(actions));

    return row;
}


function editTeamMember(member) {
    /*
     * Load team membership data into the form.
     */
    $("#team-member-id").val(member.id);
    $("#team-member-user").val(String(member.user_id)).prop("disabled", true);
    $("#team-member-role").val(member.role);
    $("#team-member-active").prop("checked", !!member.active);
}


function resetTeamMemberForm() {
    /*
     * Reset team member form without changing selected team.
     */
    $("#team-member-id").val("");
    $("#team-member-user").prop("disabled", false);
    $("#team-member-role").val("read_only");
    $("#team-member-active").prop("checked", true);
}


function saveTeamUser() {
    /*
     * Create or update a team membership.
     */
    const teamId = $("#team-member-team-id").val();
    const teamName = $("#team-member-team-name").val();
    const membershipId = $("#team-member-id").val();

    if (!teamId) {
        alert("Select a team first.");
        return;
    }

    if (membershipId) {
        apiPut("/api/teams/users/" + membershipId, {
            role: $("#team-member-role").val(),
            active: $("#team-member-active").is(":checked")
        }, function () {
            resetTeamMemberForm();
            loadTeamMembers(teamId, teamName);
            refreshTeams();
        });

        return;
    }

    apiPost("/api/teams/" + teamId + "/users", {
        user_id: Number($("#team-member-user").val()),
        role: $("#team-member-role").val()
    }, function () {
        resetTeamMemberForm();
        loadTeamMembers(teamId, teamName);
        refreshTeams();
    });
}


function disableTeamMember(membershipId) {
    /*
     * Disable team membership without deleting it.
     */
    if (!confirm("Disable this team membership?")) {
        return;
    }

    apiPost("/api/teams/users/" + membershipId + "/disable", {}, function () {
        resetTeamMemberForm();
        loadTeamMembers(selectedTeamForMembers, selectedTeamNameForMembers);
        refreshTeams();
    });
}


function collectTeamPayload() {
    /*
     * Build team payload.
     */
    const groupId = Number($("#team-group").val());

    if (!groupId) {
        alert("Select a group first.");
        throw new Error("group_id is required");
    }

    return {
        group_id: groupId,
        slug: $("#team-slug").val(),
        name: $("#team-name").val(),
        description: $("#team-description").val(),
        escalation_enabled: $("#team-escalation-enabled").is(":checked"),
        escalation_after_reminders: Number($("#team-escalation-after").val()),
        active: $("#team-active").is(":checked")
    };
}


function saveTeam() {
    /*
     * Create or update a team.
     */
    const id = $("#team-id").val();

    if (id) {
        apiPut("/api/teams/" + id, collectTeamPayload(), function () {
            closeTeamFormModal();
            resetTeamForm();
            refreshTeams();
        });

        return;
    }

    apiPost("/api/teams", collectTeamPayload(), function () {
        closeTeamFormModal();
        resetTeamForm();
        refreshTeams();
    });
}


function editTeam(id) {
    /*
     * Load team data into the form.
     */
    const team = teamsCache.find(function (item) {
        return Number(item.id) === Number(id);
    });

    if (!team) {
        return;
    }

    $("#team-form-title").text("Edit team #" + id);
    $("#team-id").val(team.id);
    $("#team-group").val(String(team.group_id || ""));
    $("#team-slug").val(team.slug);
    $("#team-name").val(team.name);
    $("#team-description").val(team.description || "");
    $("#team-escalation-enabled").prop("checked", !!team.escalation_enabled);
    $("#team-escalation-after").val(team.escalation_after_reminders || 0);
    $("#team-active").prop("checked", !!team.active);

    openTeamFormModal();
}


function deleteTeam(id) {
    /*
     * Disable a team.
     */
    if (!confirm("Disable this team?")) {
        return;
    }

    apiDelete("/api/teams/" + id, refreshTeams);
}


function resetTeamForm() {
    /*
     * Reset team form.
     */
    $("#team-form-title").text("Create team");
    $("#team-id").val("");

    const firstGroup = $("#team-group option:first").val();

    if (firstGroup) {
        $("#team-group").val(firstGroup);
    }

    $("#team-slug").val("");
    $("#team-name").val("");
    $("#team-description").val("");
    $("#team-escalation-enabled").prop("checked", true);
    $("#team-escalation-after").val(2);
    $("#team-active").prop("checked", true);
}


function openTeamFormModal() {
    /*
     * Open team create/edit modal.
     */
    $("#team-form-modal")
        .css("display", "flex")
        .addClass("is-open");

    $("body").addClass("modal-open");
}


function closeTeamFormModal() {
    /*
     * Close team create/edit modal.
     */
    $("#team-form-modal")
        .css("display", "none")
        .removeClass("is-open");

    $("body").removeClass("modal-open");
}


function openCreateTeamModal() {
    /*
     * Reset and open create team modal.
     */
    resetTeamForm();
    $("#team-form-title").text("Create team");
    openTeamFormModal();
}


function openTeamMembersModal() {
    /*
     * Open team members modal.
     */
    $("#team-members-modal")
        .css("display", "flex")
        .addClass("is-open");

    $("body").addClass("modal-open");
}


function closeTeamMembersModal() {
    /*
     * Close team members modal.
     */
    $("#team-members-modal")
        .css("display", "none")
        .removeClass("is-open");

    $("body").removeClass("modal-open");
}


$(document).on("input", "#teams-search", renderTeamsTable);
$(document).on("change", "#teams-group-filter, #teams-status-filter", renderTeamsTable);

$(document).on("click", "#open-team-create-modal", openCreateTeamModal);
$(document).on("click", "#save-team", saveTeam);
$(document).on("click", "#reset-team-form", resetTeamForm);
$(document).on("click", "#reload-teams", function () {
    loadTeamGroups(refreshTeams);
});

$(document).on("click", "#save-team-user", saveTeamUser);
$(document).on("click", "#reset-team-member-form", resetTeamMemberForm);

$(document).on("click", "#close-team-form-modal", closeTeamFormModal);
$(document).on("click", "#close-team-members-modal, #close-team-members-modal-footer", closeTeamMembersModal);

$(document).on("click", "#team-form-modal", function (event) {
    if (event.target === this) {
        closeTeamFormModal();
    }
});

$(document).on("click", "#team-members-modal", function (event) {
    if (event.target === this) {
        closeTeamMembersModal();
    }
});

$(document).on("keydown", function (event) {
    if (event.key !== "Escape") {
        return;
    }

    if ($("#team-members-modal").hasClass("is-open")) {
        closeTeamMembersModal();
        return;
    }

    if ($("#team-form-modal").hasClass("is-open")) {
        closeTeamFormModal();
    }
});
function removeTeamMember(membershipId) {
    /*
     * Permanently remove a user from the selected team.
     * Backend also removes user from this team's rotations.
     */
    if (!confirm("Remove this user from the team and from all team rotations?")) {
        return;
    }

    apiDelete("/api/teams/users/" + membershipId, function () {
        resetTeamMemberForm();
        loadTeamMembers(selectedTeamForMembers, selectedTeamNameForMembers);
        refreshTeams();

        if (typeof refreshRotations === "function") {
            refreshRotations();
        }
    });
}
