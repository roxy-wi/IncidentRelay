let teamsCache = [];
let selectedTeamForMembers = null;
let selectedTeamNameForMembers = "";
let selectedTeamDetailsId = null;

function loadTeams() {
    /*
     * Load teams page.
     */
    RbacRoles.fillTeamSelect(TEAM_VIEWER_ROLE);
    loadTeamGroups(refreshTeams);
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
        updateTeamCreateButtonState(groups);
        if (typeof callback === "function") {
            callback(groups);
        }
    });
}

function updateTeamCreateButtonState(groups) {
    /*
     * Hide create Team button for users who cannot write in any group.
     */
    groups = asArray(groups);
    const canCreate = groups.some(function (group) {
        return canWriteObject(group) || canEditGroup(group.id);
    });
    $("#open-team-create-modal").toggleClass("is-hidden", !canCreate);
}

function refreshTeams() {
    /*
     * Refresh teams table and details.
     */
    apiGet("/api/teams?include_inactive=1", function (teams) {
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
    const active = teams.filter(function (team) { return !!team.active; }).length;
    const escalation = teams.filter(function (team) { return !!team.escalation_enabled; }).length;
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
        team.active ? "active" : "inactive",
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
                    .attr("colspan", "7")
                    .addClass("empty-cell")
                    .text("No teams")
            )
        );
        return;
    }

    teams.forEach(function (team) {
        tbody.append(renderTeamRow(team));
    });
    if (typeof loadTeamHealthSummariesForVisibleRows === "function") {
        loadTeamHealthSummariesForVisibleRows();
    }
}

function renderTeamRow(team) {
    /*
     * Render one team row.
     */
    const row = $("<tr>").toggleClass("row-disabled", !team.active);

    row.append(
        $("<td>")
            .append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("name-button")
                    .text(team.name || "-")
                    .on("click", function () {
                        renderTeamDetails(team);
                    })
            )
            .append(
                $("<div>")
                    .addClass("row-subtitle")
                    .text("Team #" + team.id)
            )
    );
    row.append(
        $("<td>").append(
            $("<span>")
                .addClass("pill")
                .text(team.group_name || "-")
        )
    );
    row.append($("<td>").text(team.slug || "-"));
    row.append(
        $("<td>").append(
            $("<span>")
                .addClass("status-pill")
                .addClass(team.escalation_enabled ? "status-enabled" : "status-disabled")
                .text(team.escalation_enabled ? "simple after " + (team.escalation_after_reminders || 0) : "Disabled")
        )
    );
    row.append(
        $("<td>")
            .addClass("oncall-health-cell")
            .attr("data-team-health-id", team.id)
            .append(
                typeof renderTeamHealthIndicator === "function"
                    ? renderTeamHealthIndicator(null, team.id)
                    : $("<span>").text("?")
            )
    );
    row.append($("<td>").append(renderStatusBadge(team.active, "Active", "Inactive")));
    row.append($("<td>").addClass("actions-cell").append(renderTeamActions(team)));
    return row;
}

function renderTeamActions(team) {
    /*
     * Render team row actions as a shared three-dots menu.
     */
    return makeActionMenu({
        object: team,
        items: [
            {
                label: "Edit",
                icon: "fas fa-edit",
                required: "write",
                denyMessage: "Team manager role is required to edit this team.",
                onClick: function () {
                    editTeam(team.id);
                }
            },
            {
                label: "Members",
                icon: "fas fa-users",
                required: "manage_users",
                denyMessage: "Team manager role is required to manage team members.",
                onClick: function () {
                    openTeamMembers(team.id, team.name);
                }
            },
            {
                label: team.active ? "Disable" : "Enable",
                icon: team.active ? "fas fa-pause" : "fas fa-play",
                required: "write",
                danger: team.active,
                denyMessage: "Team manager role is required to enable or disable this team.",
                onClick: function () {
                    setTeamActive(team, !team.active);
                }
            },
            {
                label: "Remove",
                icon: "fas fa-trash",
                required: "delete",
                danger: true,
                denyMessage: "Delete permission is required to remove this team.",
                onClick: function () {
                    removeTeam(team);
                }
            }
        ]
    });
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

    $("#team-details-subtitle").text((team.group_slug || "-") + " / " + (team.active ? "Active" : "Inactive"));

    const body = $("#team-details-body").empty();
    body.append(
        $("<div>")
            .addClass("details-list")
            .append(teamDetailsItem("Name", team.name))
            .append(teamDetailsItem("Slug", team.slug))
            .append(teamDetailsItem("Group", team.group_slug))
            .append(teamDetailsItem("Description", team.description))
            .append(teamDetailsItem(
                "Simple rotation escalation",
                team.escalation_enabled ? "Enabled" : "Disabled"
            ))
            .append(teamDetailsItem(
                "Simple escalation after reminders",
                team.escalation_after_reminders || 0
            ))
            .append(teamDetailsItem(
                "Policy mode",
                "Routes with an escalation policy use policy rule delays instead"
            ))
            .append(teamDetailsItem("Status", team.active ? "Active" : "Inactive"))
    );

    const actions = $("<div>").addClass("details-actions");
    appendIconActionIfAllowed(actions, team, {
        required: "write",
        icon: "fas fa-edit",
        label: "Edit team",
        onClick: function () {
            editTeam(team.id);
        },
    });
    appendIconActionIfAllowed(actions, team, {
        required: "manage_users",
        icon: "fas fa-users",
        label: "Members",
        onClick: function () {
            openTeamMembers(team.id, team.name);
        },
    });
    if (actions.children().length) {
        body.append(actions);
    }
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
    $("#team-details-body").html("Click a team name to inspect group, escalation settings and quick actions.");
}

function getSelectedTeamForMembers() {
    return teamsCache.find(function (team) {
        return Number(team.id) === Number(selectedTeamForMembers);
    });
}

function fillTeamMemberUserSelect(team, callback) {
    /*
     * Fill team member user select with active users from this team's group.
     */
    const selectElement = getSelectElement("#team-member-user");

    if (!selectElement) {
        if (typeof callback === "function") {
            callback([]);
        }
        return;
    }

    const wasDisabled = $(selectElement).prop("disabled");

    destroyTomSelectIfExists(selectElement);

    const select = $(selectElement);
    select.empty();

    if (!team || !team.group_id) {
        initUserTomSelectIfNeeded(selectElement);
        setEnhancedSelectDisabled(selectElement, wasDisabled);

        if (typeof callback === "function") {
            callback([]);
        }
        return;
    }

    apiGet(
        "/api/groups/" + encodeURIComponent(team.group_id) + "/users",
        function (memberships) {
            memberships = asArray(memberships).filter(function (membership) {
                return !!membership.active;
            });

            memberships.forEach(function (membership) {
                const userId = getUserIdValue(membership);

                if (!userId) {
                    return;
                }

                select.append(
                    $("<option>")
                        .val(String(userId))
                        .text(getUserOptionText(membership))
                );
            });

            initUserTomSelectIfNeeded(selectElement);
            setEnhancedSelectDisabled(selectElement, wasDisabled);

            if (typeof callback === "function") {
                callback(memberships);
            }
        }
    );
}

function openTeamMembers(teamId, teamName) {
    /*
     * Open team members modal and load members.
     */
    const team = teamsCache.find(function (item) {
        return Number(item.id) === Number(teamId);
    });

    if (!team) {
        showAppError("Team was not found.");
        return;
    }

    if (!canManageUsersObject(team)) {
        showAppError("You do not have permission to manage this team's members.");
        return;
    }

    RbacRoles.fillTeamSelect(TEAM_VIEWER_ROLE);
    fillTeamMemberUserSelect(team, function () {
        resetTeamMemberForm();
    });
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
                        .addClass("empty-cell")
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
    const selectedTeam = getSelectedTeamForMembers();

    row.append($("<td>").text(member.user_id));
    row.append($("<td>").text(member.username));
    row.append($("<td>").text(member.display_name || "-"));
    row.append(
        $("<td>").append(
            $("<span>")
                .addClass("role-pill")
                .addClass(RbacRoles.teamClass(member.role))
                .text(RbacRoles.teamLabel(member.role))
        )
    );

    row.append(
        $("<td>").append(
            renderStatusBadge(member.active, "Enabled", "Disabled")
        )
    );

    row.append(
        $("<td>")
            .addClass("actions-cell")
            .append(
                makeActionMenu({
                    object: selectedTeam,
                    items: [
                        {
                            label: "Edit",
                            icon: "fas fa-edit",
                            required: "manage_users",
                            denyMessage: "Team manager role is required to edit team members.",
                            onClick: function () {
                                editTeamMember(member);
                            }
                        },
                        {
                            label: member.active ? "Disable" : "Enable",
                            icon: member.active ? "fas fa-pause" : "fas fa-play",
                            required: "manage_users",
                            danger: member.active,
                            denyMessage: "Team manager role is required to enable or disable team members.",
                            onClick: function () {
                                setTeamMemberActive(member, !member.active);
                            }
                        },
                        {
                            label: "Remove",
                            icon: "fas fa-trash",
                            required: "manage_users",
                            danger: true,
                            denyMessage: "Team manager role is required to remove team members.",
                            onClick: function () {
                                removeTeamMember(member.id);
                            }
                        }
                    ]
                })
            )
    );

    return row;
}

function editTeamMember(member) {
    /*
     * Load team membership data into the form.
     */
    const selectedTeam = getSelectedTeamForMembers();
    if (selectedTeam && !canManageUsersObject(selectedTeam)) {
        showAppError("You do not have permission to manage this team's members.");
        return;
    }

    $("#team-member-id").val(member.id);
    setSelectValue("#team-member-user", member.user_id);
    setEnhancedSelectDisabled("#team-member-user", true);
    RbacRoles.fillTeamSelect(member.role);
    $("#team-member-active").prop("checked", !!member.active);
}

function resetTeamMemberForm() {
    /*
     * Reset team member form without changing selected team.
     */
    $("#team-member-id").val("");
    setEnhancedSelectDisabled("#team-member-user", false);
    setSelectValue("#team-member-user", "");
    RbacRoles.fillTeamSelect(TEAM_VIEWER_ROLE);
    $("#team-member-active").prop("checked", true);
}

function saveTeamUser() {
    /*
     * Create or update a team membership.
     */
    const teamId = $("#team-member-team-id").val();
    const teamName = $("#team-member-team-name").val();
    const membershipId = $("#team-member-id").val();
    const selectedTeam = getSelectedTeamForMembers();
    const selectedUserId = Number($("#team-member-user").val());

    if (!teamId) {
        showAppError("Select a team first.");
        return;
    }
    if (!membershipId && !selectedUserId) {
        showAppError("User is required.");
        return;
    }
    if (selectedTeam && !canManageUsersObject(selectedTeam)) {
        showAppError("You do not have permission to manage this team's members.");
        return;
    }

    if (membershipId) {
        apiPut(
            "/api/teams/users/" + membershipId,
            {
                role: $("#team-member-role").val(),
                active: $("#team-member-active").is(":checked"),
            },
            function () {
                resetTeamMemberForm();
                loadTeamMembers(teamId, teamName);
                refreshTeams();
            }
        );
        return;
    }

    apiPost(
        "/api/teams/" + teamId + "/users",
        {
            user_id: selectedUserId,
            role: $("#team-member-role").val(),
            active: $("#team-member-active").is(":checked"),
        },
        function () {
            resetTeamMemberForm();
            loadTeamMembers(teamId, teamName);
            refreshTeams();
        }
    );
}

function setTeamMemberActive(member, active) {
    /*
     * Enable or disable a team membership using the existing update endpoint.
     *
     * PUT requires role and active, so we preserve the current role.
     */
    const selectedTeam = getSelectedTeamForMembers();
    if (selectedTeam && !canManageUsersObject(selectedTeam)) {
        showAppError("You do not have permission to manage this team's members.");
        return;
    }

    const action = active ? "enable" : "disable";
    showAppConfirm({
        title: "Are you sure?",
        message: "Are you sure you want to " + action + " this team member?",
        confirmText: action.charAt(0).toUpperCase() + action.slice(1),
        confirmClass: active ? "btn-success" : "btn-warning",
    }).done(function () {
        apiPut(
            "/api/teams/users/" + member.id,
            {
                role: member.role || TEAM_VIEWER_ROLE,
                active: active,
            },
            function () {
                resetTeamMemberForm();
                if (selectedTeamForMembers) {
                    loadTeamMembers(selectedTeamForMembers, selectedTeamNameForMembers);
                }
                refreshTeams();
            }
        );
    });
}

function collectTeamPayload() {
    /*
     * Build team payload.
     */
    const groupId = Number($("#team-group").val());
    if (!groupId) {
        showAppError("Select a group first.");
        throw new Error("group_id is required");
    }

    return {
        group_id: groupId,
        slug: $("#team-slug").val(),
        name: $("#team-name").val(),
        description: $("#team-description").val(),
        escalation_enabled: $("#team-escalation-enabled").is(":checked"),
        escalation_after_reminders: Number($("#team-escalation-after").val()),
        active: $("#team-active").is(":checked"),
    };
}

function saveTeam() {
    /*
     * Create or update a team.
     */
    const id = $("#team-id").val();
    const existingTeam = id ? teamsCache.find(function (item) { return Number(item.id) === Number(id); }) : null;

    if (existingTeam && !canWriteObject(existingTeam)) {
        showAppError("You do not have permission to edit this team.");
        return;
    }

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
    if (!canWriteObject(team)) {
        showAppError("You do not have permission to edit this team.");
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
    openAppModal("#team-form-modal");
}

function closeTeamFormModal() {
    closeAppModal("#team-form-modal");
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
    openAppModal("#team-members-modal");
}

function closeTeamMembersModal() {
    closeAppModal("#team-members-modal");
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
    const selectedTeam = getSelectedTeamForMembers();
    if (selectedTeam && !canManageUsersObject(selectedTeam)) {
        showAppError("You do not have permission to manage this team's members.");
        return;
    }

    showAppConfirm({
        title: "Removing team member",
        message: "Remove this user from the team and from all team rotations?",
        confirmText: "Remove",
        confirmClass: "btn-danger",
    }).done(function () {
        apiDelete("/api/teams/users/" + membershipId, function () {
            resetTeamMemberForm();
            loadTeamMembers(selectedTeamForMembers, selectedTeamNameForMembers);
            refreshTeams();
            if (typeof refreshRotations === "function") {
                refreshRotations();
            }
        });
    });
}

function buildTeamUpdatePayload(team, active) {
    /*
     * Build a full team update payload.
     *
     * Backend TeamUpdateSchema expects the full team object, so we preserve all
     * current values and only change active.
     */
    return {
        group_id: Number(team.group_id),
        slug: team.slug,
        name: team.name,
        description: team.description || "",
        escalation_enabled: !!team.escalation_enabled,
        escalation_after_reminders: Number(team.escalation_after_reminders || 0),
        active: active,
    };
}

function setTeamActive(team, active) {
    /*
     * Enable or disable a team without deleting rotations, routes, channels or silences.
     */
    if (!canWriteObject(team)) {
        showAppError("You do not have permission to update this team.");
        return;
    }

    const action = active ? "enable" : "disable";
    const btnClass = active ? "btn-success" : "btn-warning";

    showAppConfirm({
        title: "Are you sure?",
        message: "Are you sure you want to " + action + " this team?",
        confirmText: upperCaseFirst(action),
        confirmClass: btnClass,
    }).done(function () {
        apiPut(
            "/api/teams/" + team.id,
            buildTeamUpdatePayload(team, active),
            function () {
                refreshTeams();
                if (typeof refreshRotations === "function") {
                    refreshRotations();
                }
                if (typeof refreshRoutes === "function") {
                    refreshRoutes();
                }
                if (typeof refreshChannels === "function") {
                    refreshChannels();
                }
                if (typeof refreshSilences === "function") {
                    refreshSilences();
                }
            }
        );
    });
}

function removeTeam(team) {
    /*
     * Remove a team and all non-historical resources under it.
     */
    if (!canDeleteObject(team)) {
        showAppError("You do not have permission to remove this team.");
        return;
    }

    const message = [
        "Remove team \"" + (team.name || team.slug || team.id) + "\"?",
        "",
        "This will remove rotations, routes, notification channels, silences,",
        "team memberships and route-channel links for this team.",
        "",
        "Historical alerts will be preserved.",
        "",
        "Continue?",
    ].join("\n");

    showAppConfirm({
        title: "Remove team",
        message: message,
        confirmText: "Remove",
        confirmClass: "btn-danger",
    }).done(function () {
        apiDelete("/api/teams/" + team.id, function () {
            if (Number(selectedTeamDetailsId) === Number(team.id)) {
                selectedTeamDetailsId = null;
            }
            refreshTeams();
            if (typeof refreshRotations === "function") {
                refreshRotations();
            }
            if (typeof refreshRoutes === "function") {
                refreshRoutes();
            }
            if (typeof refreshChannels === "function") {
                refreshChannels();
            }
            if (typeof refreshSilences === "function") {
                refreshSilences();
            }
        });
    });
}
