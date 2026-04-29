let selectedGroupForMembers = null;
let selectedGroupNameForMembers = "";

function loadGroups() {
    /* Load groups and group form data. */
    apiGet("/api/groups", function (groups) {
        groups = asArray(groups);
        renderGroups(groups);
        fillGroupSelect("#group-user-group", false);
        fillUserSelect("#group-user-user", null, "/api/users?all=1");

        if (selectedGroupForMembers) {
            loadGroupMembers(selectedGroupForMembers, selectedGroupNameForMembers);
        }
    });
}

function renderGroups(groups) {
    /* Render groups table. */
    const tbody = $("#groups-table");
    tbody.empty();

    if (!groups.length) {
        tbody.append($("<tr>").append($("<td>").attr("colspan", "6").text("No groups")));
        return;
    }

    groups.forEach(function (group) {
        const row = $("<tr>");
        row.append($("<td>").text(group.id));
        row.append($("<td>").text(group.slug));
        row.append($("<td>").text(group.name));
        row.append($("<td>").text(group.description || "-"));
        row.append($("<td>").text(group.active ? "yes" : "no"));

        const actions = $("<td>").addClass("actions");
        actions.append($("<button>").attr("type", "button").addClass("btn btn-info btn-small").text("Edit").on("click", function () {
            $("#group-id").val(group.id);
            $("#group-slug").val(group.slug);
            $("#group-name").val(group.name);
            $("#group-description").val(group.description || "");
        }));

        actions.append($("<button>").attr("type", "button").addClass("btn btn-small").text("Members").on("click", function () {
            loadGroupMembers(group.id, group.name);
        }));

        row.append(actions);
        tbody.append(row);
    });
}

function loadGroupMembers(groupId, groupName) {
    /* Load members for one group. */
    selectedGroupForMembers = groupId;
    selectedGroupNameForMembers = groupName;

    $("#group-members-title").text("Group members: " + groupName);
    $("#group-user-group").val(String(groupId));

    const tbody = $("#group-members-table");
    tbody.empty();

    apiGet("/api/groups/" + groupId + "/users", function (members) {
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
                editGroupMember(member);
            }));
            actions.append($("<button>").attr("type", "button").addClass("btn btn-danger btn-small").text("Disable").on("click", function () {
                disableGroupMember(member.id);
            }));

            row.append(actions);
            tbody.append(row);
        });
    });
}

function editGroupMember(member) {
    /* Load membership data into the group member form. */
    $("#group-member-form-title").text("Edit group membership #" + member.id);
    $("#group-membership-id").val(member.id);
    $("#group-user-user").val(String(member.user_id)).prop("disabled", true);
    $("#group-user-role").val(member.role);
    $("#group-user-active").prop("checked", !!member.active);
}

function resetGroupUserForm() {
    /* Reset group member form. */
    $("#group-member-form-title").text("Add user to group");
    $("#group-membership-id").val("");
    $("#group-user-user").prop("disabled", false);
    $("#group-user-role").val("read_only");
    $("#group-user-active").prop("checked", true);
}

function saveGroup() {
    /* Create or update a group. */
    const data = {
        slug: $("#group-slug").val(),
        name: $("#group-name").val(),
        description: $("#group-description").val(),
        active: true
    };

    const groupId = $("#group-id").val();

    if (groupId) {
        apiPut("/api/groups/" + groupId, data, loadGroups);
        return;
    }

    apiPost("/api/groups", data, loadGroups);
}

function clearGroupForm() {
    /* Clear group form. */
    $("#group-id").val("");
    $("#group-slug").val("");
    $("#group-name").val("");
    $("#group-description").val("");
}

function saveGroupUser() {
    /* Create or update a group membership. */
    const membershipId = $("#group-membership-id").val();
    const groupId = $("#group-user-group").val();

    if (membershipId) {
        apiPut("/api/groups/users/" + membershipId, {
            role: $("#group-user-role").val(),
            active: $("#group-user-active").is(":checked")
        }, function () {
            resetGroupUserForm();
            loadGroupMembers(groupId, $("#group-user-group option:selected").text());
        });
        return;
    }

    apiPost("/api/groups/" + groupId + "/users", {
        user_id: Number($("#group-user-user").val()),
        role: $("#group-user-role").val()
    }, function () {
        resetGroupUserForm();
        loadGroupMembers(groupId, $("#group-user-group option:selected").text());
    });
}

function disableGroupMember(membershipId) {
    /* Disable a group membership. */
    if (!confirm("Disable this group membership?")) {
        return;
    }

    apiDelete("/api/groups/users/" + membershipId, function () {
        loadGroupMembers(selectedGroupForMembers, selectedGroupNameForMembers);
    });
}

$(document).on("click", "#reload-groups", loadGroups);
$(document).on("click", "#save-group", saveGroup);
$(document).on("click", "#clear-group-form", clearGroupForm);
$(document).on("click", "#save-group-user", saveGroupUser);
$(document).on("click", "#reset-group-user-form", resetGroupUserForm);
