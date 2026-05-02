let selectedGroupForMembers = null;
let selectedGroupNameForMembers = "";
let groupsCache = [];
let groupMembersCache = [];


function loadGroups() {
    /*
     * Load groups and render the groups table.
     */
    apiGet("/api/groups", function (groups) {
        groupsCache = asArray(groups);
        renderGroups(groupsCache);
        renderGroupsSummary(groupsCache);
        fillGroupMemberUserSelect();

        if (selectedGroupForMembers) {
            loadGroupMembers(selectedGroupForMembers, selectedGroupNameForMembers);
        }
    });
}


function renderGroupsSummary(groups) {
    /*
     * Render summary cards for groups.
     */
    const activeGroups = groups.filter(function (group) {
        return !!group.active;
    });

    $("#groups-total-count").text(groups.length);
    $("#groups-active-count").text(activeGroups.length);
    $("#groups-inactive-count").text(groups.length - activeGroups.length);
}


function renderGroups(groups) {
    /*
     * Render groups table.
     */
    const tbody = $("#groups-table");
    tbody.empty();

    if (!groups.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>")
                    .attr("colspan", "5")
                    .text("No groups")
            )
        );
        return;
    }

    groups.forEach(function (group) {
        tbody.append(renderGroupRow(group));
    });
}


function renderGroupRow(group) {
    /*
     * Render one group row.
     */
    const row = $("<tr>").toggleClass("row-disabled", !group.active);

    row.append($("<td>").text(group.id));

    row.append(
        $("<td>")
            .append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("team-name-button")
                    .text(group.name || group.slug || ("Group #" + group.id))
                    .on("click", function () {
                        openExistingGroupModal(group);
                    })
            )
            .append(
                $("<div>")
                    .addClass("details-meta")
                    .text(group.slug || "-")
            )
    );

    row.append($("<td>").text(group.description || "-"));

    row.append(
        $("<td>").append(
            renderGroupStatus(group.active)
        )
    );

    row.append(
        $("<td>")
            .addClass("actions")
            .append(renderGroupActions(group))
    );

    return row;
}


function renderGroupStatus(active) {
    /*
     * Render group active/inactive status.
     */
    return $("<span>")
        .addClass("status-pill")
        .addClass(active ? "status-active" : "status-inactive")
        .text(active ? "Active" : "Inactive");
}


function renderGroupActions(group) {
    /*
     * Render actions for one group row.
     */
    const actions = $("<div>").addClass("actions");

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-small")
            .text("Edit")
            .on("click", function () {
                openExistingGroupModal(group);
            })
    );

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-small")
            .text("Members")
            .on("click", function () {
                openExistingGroupModal(group);
            })
    );

    if (group.active) {
        actions.append(
            $("<button>")
                .attr("type", "button")
                .addClass("btn btn-warning btn-small")
                .text("Disable")
                .on("click", function () {
                    setGroupActive(group, false);
                })
        );
    } else {
        actions.append(
            $("<button>")
                .attr("type", "button")
                .addClass("btn btn-success btn-small")
                .text("Enable")
                .on("click", function () {
                    setGroupActive(group, true);
                })
        );
    }

    return actions;
}


function openGroupModal() {
    /*
     * Open the group modal.
     */
    $("#group-modal").removeClass("is-hidden");
}


function closeGroupModal() {
    /*
     * Close the group modal.
     */
    $("#group-modal").addClass("is-hidden");
}


function openNewGroupModal() {
    /*
     * Open modal for a new group.
     */
    selectedGroupForMembers = null;
    selectedGroupNameForMembers = "";
    groupMembersCache = [];

    clearGroupForm();
    resetGroupMemberForm();
    setGroupMemberControlsEnabled(false);
    renderEmptyGroupMembers("Save the group first, then add members");

    $("#group-modal-title").text("New group");
    $("#group-modal-subtitle").text("Create a new access group.");
    $("#group-members-title").text("Group members");

    openGroupModal();
}


function openExistingGroupModal(group) {
    /*
     * Open modal for an existing group.
     */
    fillGroupForm(group);
    resetGroupMemberForm();
    setGroupMemberControlsEnabled(true);

    selectedGroupForMembers = group.id;
    selectedGroupNameForMembers = group.name || group.slug || ("Group #" + group.id);

    $("#group-modal-title").text("Group details");
    $("#group-modal-subtitle").text(selectedGroupNameForMembers);
    $("#group-members-title").text("Group members: " + selectedGroupNameForMembers);

    openGroupModal();
    loadGroupMembers(group.id, selectedGroupNameForMembers);
}


function fillGroupForm(group) {
    /*
     * Fill group form with existing group data.
     */
    $("#group-id").val(group.id);
    $("#group-slug").val(group.slug || "");
    $("#group-name").val(group.name || "");
    $("#group-description").val(group.description || "");
    $("#group-active").prop("checked", !!group.active);
}


function buildGroupPayload(activeOverride) {
    /*
     * Build group create/update payload.
     */
    const active = typeof activeOverride === "boolean"
        ? activeOverride
        : $("#group-active").is(":checked");

    return {
        slug: $("#group-slug").val().trim(),
        name: $("#group-name").val().trim(),
        description: $("#group-description").val().trim(),
        active: active
    };
}


function saveGroup() {
    /*
     * Create or update a group.
     */
    const data = buildGroupPayload();
    const groupId = $("#group-id").val();

    if (!data.slug || !data.name) {
        showAppError("Slug and name are required");
        return;
    }

    if (groupId) {
        apiPut("/api/groups/" + groupId, data, function (group) {
            const updatedGroup = group || {
                id: Number(groupId),
                slug: data.slug,
                name: data.name,
                description: data.description,
                active: data.active
            };

            selectedGroupForMembers = updatedGroup.id;
            selectedGroupNameForMembers = updatedGroup.name || updatedGroup.slug;

            $("#group-modal-subtitle").text(selectedGroupNameForMembers);
            $("#group-members-title").text("Group members: " + selectedGroupNameForMembers);

            setGroupMemberControlsEnabled(true);
            loadGroups();
        });
        return;
    }

    apiPost("/api/groups", data, function (group) {
        $("#group-id").val(group.id);

        selectedGroupForMembers = group.id;
        selectedGroupNameForMembers = group.name || group.slug || ("Group #" + group.id);

        $("#group-modal-title").text("Group details");
        $("#group-modal-subtitle").text(selectedGroupNameForMembers);
        $("#group-members-title").text("Group members: " + selectedGroupNameForMembers);

        setGroupMemberControlsEnabled(true);
        loadGroups();
        loadGroupMembers(group.id, selectedGroupNameForMembers);
    });
}


function setGroupActive(group, active) {
    /*
     * Enable or disable a group using the existing update endpoint.
     */
    const action = active ? "enable" : "disable";

    if (!confirm("Are you sure you want to " + action + " this group?")) {
        return;
    }

    apiPut(
        "/api/groups/" + group.id,
        {
            slug: group.slug,
            name: group.name,
            description: group.description || "",
            active: active
        },
        function () {
            if (Number($("#group-id").val()) === Number(group.id)) {
                $("#group-active").prop("checked", active);
            }

            loadGroups();
        }
    );
}


function clearGroupForm() {
    /*
     * Clear group form.
     */
    $("#group-id").val("");
    $("#group-slug").val("");
    $("#group-name").val("");
    $("#group-description").val("");
    $("#group-active").prop("checked", true);
}


function fillGroupMemberUserSelect() {
    /*
     * Fill users select for group membership.
     */
    fillUserSelect("#group-member-user", null, "/api/users?all=1");
}


function setGroupMemberControlsEnabled(enabled) {
    /*
     * Enable or disable member management controls.
     */
    $("#group-member-user").prop("disabled", !enabled);
    $("#group-member-role").prop("disabled", !enabled);
    $("#group-member-active").prop("disabled", !enabled);
    $("#save-group-member").prop("disabled", !enabled);
    $("#reset-group-member-form").prop("disabled", !enabled);
    $("#reload-group-members").prop("disabled", !enabled);

    $("#group-member-help").text(
        enabled
            ? "Select a user and role, then save membership."
            : "Save the group first, then add members."
    );
}


function loadGroupMembers(groupId, groupName) {
    /*
     * Load members for one group.
     */
    selectedGroupForMembers = groupId;
    selectedGroupNameForMembers = groupName;

    $("#group-members-title").text("Group members: " + groupName);

    const tbody = $("#group-members-table");
    tbody.empty();

    apiGet("/api/groups/" + groupId + "/users", function (members) {
        groupMembersCache = asArray(members);

        if (!groupMembersCache.length) {
            renderEmptyGroupMembers("No members");
            return;
        }

        groupMembersCache.forEach(function (member) {
            tbody.append(renderGroupMemberRow(member));
        });
    });
}


function renderEmptyGroupMembers(message) {
    /*
     * Render an empty members table state.
     */
    $("#group-members-table")
        .empty()
        .append(
            $("<tr>").append(
                $("<td>")
                    .attr("colspan", "6")
                    .text(message)
            )
        );
}


function renderGroupMemberRow(member) {
    /*
     * Render one group member row.
     */
    const row = $("<tr>").toggleClass("row-disabled", !member.active);

    row.append($("<td>").text(member.user_id));
    row.append($("<td>").text(member.username || "-"));
    row.append($("<td>").text(member.display_name || "-"));

    row.append(
        $("<td>").append(
            $("<span>")
                .addClass(member.role === "rw" ? "role-rw" : "role-read-only")
                .text(member.role === "rw" ? "Read/write" : "Read only")
        )
    );

    row.append(
        $("<td>").append(
            $("<span>")
                .addClass("status-pill")
                .addClass(member.active ? "status-active" : "status-inactive")
                .text(member.active ? "Active" : "Inactive")
        )
    );

    row.append(
        $("<td>")
            .addClass("actions")
            .append(renderGroupMemberActions(member))
    );

    return row;
}


function renderGroupMemberActions(member) {
    /*
     * Render group member row actions.
     */
    const actions = $("<div>").addClass("actions");

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-small")
            .text("Edit")
            .on("click", function () {
                editGroupMember(member);
            })
    );

    if (member.active) {
        actions.append(
            $("<button>")
                .attr("type", "button")
                .addClass("btn btn-warning btn-small")
                .text("Disable")
                .on("click", function () {
                    setGroupMemberActive(member, false);
                })
        );
    } else {
        actions.append(
            $("<button>")
                .attr("type", "button")
                .addClass("btn btn-success btn-small")
                .text("Enable")
                .on("click", function () {
                    setGroupMemberActive(member, true);
                })
        );
    }

    return actions;
}


function editGroupMember(member) {
    /*
     * Load membership data into the group member form.
     */
    $("#group-member-form-title").text("Edit group membership #" + member.id);
    $("#group-membership-id").val(member.id);
    $("#group-member-user").val(String(member.user_id)).prop("disabled", true);
    $("#group-member-role").val(member.role);
    $("#group-member-active").prop("checked", !!member.active);
}


function resetGroupMemberForm() {
    /*
     * Reset group member form.
     */
    $("#group-member-form-title").text("Add user to group");
    $("#group-membership-id").val("");
    $("#group-member-user").prop("disabled", !selectedGroupForMembers);
    $("#group-member-role").val("read_only");
    $("#group-member-active").prop("checked", true);

    setGroupMemberControlsEnabled(!!selectedGroupForMembers);
}


function saveGroupMember() {
    /*
     * Create or update group membership.
     */
    const membershipId = $("#group-membership-id").val();
    const groupId = selectedGroupForMembers || Number($("#group-id").val());

    if (!groupId) {
        showAppError("Save or select a group first");
        return;
    }

    if (membershipId) {
        apiPut(
            "/api/groups/users/" + membershipId,
            {
                role: $("#group-member-role").val(),
                active: $("#group-member-active").is(":checked")
            },
            function () {
                resetGroupMemberForm();
                loadGroupMembers(groupId, selectedGroupNameForMembers);
            }
        );
        return;
    }

    const userId = Number($("#group-member-user").val());

    if (!userId) {
        showAppError("User is required");
        return;
    }

    apiPost(
        "/api/groups/" + groupId + "/users",
        {
            user_id: userId,
            role: $("#group-member-role").val()
        },
        function () {
            resetGroupMemberForm();
            loadGroupMembers(groupId, selectedGroupNameForMembers);
        }
    );
}


function setGroupMemberActive(member, active) {
    /*
     * Enable or disable group membership using the existing update endpoint.
     */
    const action = active ? "enable" : "disable";

    if (!confirm("Are you sure you want to " + action + " this group membership?")) {
        return;
    }

    apiPut(
        "/api/groups/users/" + member.id,
        {
            role: member.role || "read_only",
            active: active
        },
        function () {
            resetGroupMemberForm();
            loadGroupMembers(selectedGroupForMembers, selectedGroupNameForMembers);
        }
    );
}


$(document).on("click", "#reload-groups", loadGroups);
$(document).on("click", "#new-group", openNewGroupModal);
$(document).on("click", "#save-group", saveGroup);
$(document).on("click", "#clear-group-form", function () {
    clearGroupForm();
    resetGroupMemberForm();
    renderEmptyGroupMembers("Save the group first, then add members");
});
$(document).on("click", "#save-group-member", saveGroupMember);
$(document).on("click", "#reset-group-member-form", resetGroupMemberForm);
$(document).on("click", "#reload-group-members", function () {
    if (!selectedGroupForMembers) {
        return;
    }

    loadGroupMembers(selectedGroupForMembers, selectedGroupNameForMembers);
});
$(document).on("click", "#close-group-modal, #close-group-modal-footer", closeGroupModal);
$(document).on("click", "#group-modal", function (event) {
    if (event.target === this) {
        closeGroupModal();
    }
});
$(document).on("keydown", function (event) {
    if (event.key === "Escape" && !$("#group-modal").hasClass("is-hidden")) {
        closeGroupModal();
    }
});
