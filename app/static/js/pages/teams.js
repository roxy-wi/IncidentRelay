let teamsCache = [];
let selectedTeamForMembers = null;
let selectedTeamNameForMembers = "";

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
        if (!groups.length) {
            $("#team-group").append($("<option>").val("").text("No groups available"));
        }

        if (typeof callback === "function") {
            callback(groups);
        }
    });
}

function refreshTeams() {
    /*
     * Refresh teams table.
     */

    apiGet("/api/teams", function (teams) {
        teams = asArray(teams);
        teamsCache = teams;

        const tbody = $("#teams-table");
        tbody.empty();

        if (!teams.length) {
            tbody.append($("<tr>").append($("<td>").attr("colspan", "7").text("No teams")));
            return;
        }

        teams.forEach(function (team) {
            const row = $("<tr>");

            row.append($("<td>").text(team.id));
            row.append($("<td>").text(team.group_slug || "-"));
            row.append($("<td>").text(team.slug));
            row.append($("<td>").text(team.name));
            row.append($("<td>").text(team.escalation_enabled ? "after " + team.escalation_after_reminders : "disabled"));
            row.append($("<td>").text(team.active ? "yes" : "no"));

            const actions = $("<td>").addClass("actions");

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
                        loadTeamMembers(team.id, team.name);
                    })
            );

            actions.append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("btn btn-danger btn-small")
                    .text("Delete")
                    .on("click", function () {
                        deleteTeam(team.id);
                    })
            );

            row.append(actions);
            tbody.append(row);
        });

        if (selectedTeamForMembers) {
            loadTeamMembers(selectedTeamForMembers, selectedTeamNameForMembers);
        }
    });
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

    const tbody = $("#team-members-table");
    tbody.empty();

    apiGet("/api/teams/" + teamId + "/users", function (members) {
        if (!members.length) {
            tbody.append($("<tr>").append($("<td>").attr("colspan", "6").text("No members")));
            return;
        }

        members.forEach(function (member) {
            const row = $("<tr>");
            row.append($("<td>").text(member.user_id));
            row.append($("<td>").text(member.username));
            row.append($("<td>").text(member.display_name || "-"));
            row.append($("<td>").text(member.role));
            row.append($("<td>").text(member.active ? "yes" : "no"));

            const actions = $("<td>").addClass("actions");
            actions.append($("<button>").attr("type", "button").addClass("btn btn-small").text("Edit").on("click", function () {
                editTeamMember(member);
            }));
            actions.append($("<button>").attr("type", "button").addClass("btn btn-danger btn-small").text("Disable").on("click", function () {
                disableTeamMember(member.id);
            }));
            row.append(actions);

            tbody.append(row);
        });
    });
}

function editTeamMember(member) {
    /*
     * Load team membership data into the form.
     */

    $("#team-member-form-title").text("Edit team membership #" + member.id);
    $("#team-member-id").val(member.id);
    $("#team-member-user").val(String(member.user_id)).prop("disabled", true);
    $("#team-member-role").val(member.role);
    $("#team-member-active").prop("checked", !!member.active);
}

function resetTeamMemberForm() {
    /*
     * Reset team member form.
     */

    $("#team-member-form-title").text("Add user to selected team");
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
            loadTeamMembers(teamId, $("#team-member-team-name").val());
        });
        return;
    }

    apiPost("/api/teams/" + teamId + "/users", {
        user_id: Number($("#team-member-user").val()),
        role: $("#team-member-role").val()
    }, function () {
        resetTeamMemberForm();
        loadTeamMembers(teamId, $("#team-member-team-name").val());
    });
}

function disableTeamMember(membershipId) {
    /*
     * Disable a team membership.
     */

    if (!confirm("Disable this team membership?")) {
        return;
    }

    apiDelete("/api/teams/users/" + membershipId, function () {
        loadTeamMembers(selectedTeamForMembers, selectedTeamNameForMembers);
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
            resetTeamForm();
            refreshTeams();
        });
        return;
    }

    apiPost("/api/teams", collectTeamPayload(), function () {
        resetTeamForm();
        refreshTeams();
    });
}

function editTeam(id) {
    /*
     * Load team data into the form.
     */

    const team = teamsCache.find(function (item) {
        return item.id === id;
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

$(document).on("click", "#save-team", saveTeam);
$(document).on("click", "#reset-team-form", resetTeamForm);
$(document).on("click", "#save-team-user", saveTeamUser);
$(document).on("click", "#reset-team-member-form", resetTeamMemberForm);
$(document).on("click", "#reload-teams", function () {
    loadTeamGroups(refreshTeams);
});
