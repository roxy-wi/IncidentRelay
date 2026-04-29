function loadProfile() {
    /* Load current user profile. */
    apiGet("/api/profile", function (profile) {
        $("#profile-username").val(profile.username || "");
        $("#profile-display-name").val(profile.display_name || "");
        $("#profile-email").val(profile.email || "");
        $("#profile-phone").val(profile.phone || "");
        $("#profile-telegram").val(profile.telegram_chat_id || "");
        $("#profile-slack").val(profile.slack_user_id || "");
        $("#profile-mattermost").val(profile.mattermost_user_id || "");

        const tokenGroupSelect = $("#profile-token-group");
        const activeGroupSelect = $("#profile-active-group");

        tokenGroupSelect.empty();
        activeGroupSelect.empty();

        tokenGroupSelect.append($("<option>").val("").text("No group limit"));
        activeGroupSelect.append($("<option>").val("").text("All my groups"));

        (profile.groups || []).forEach(function (membership) {
            const label = membership.group_name + " (" + membership.role + ")";
            tokenGroupSelect.append($("<option>").val(membership.group_id).text(label));
            activeGroupSelect.append($("<option>").val(membership.group_id).text(label));
        });

        if (profile.active_group_id) {
            activeGroupSelect.val(String(profile.active_group_id));
        }
    });
}

function saveProfile() {
    /* Save the current user profile. */
    apiPut("/api/profile", {
        display_name: $("#profile-display-name").val() || null,
        email: $("#profile-email").val() || null,
        phone: $("#profile-phone").val() || null,
        telegram_chat_id: $("#profile-telegram").val() || null,
        slack_user_id: $("#profile-slack").val() || null,
        mattermost_user_id: $("#profile-mattermost").val() || null
    }, function () {
        alert("Profile saved");
        loadProfile();
    });
}

function changeProfilePassword() {
    /* Change current user password. */
    apiPost("/api/profile/change-password", {
        old_password: $("#profile-old-password").val(),
        new_password: $("#profile-new-password").val()
    }, function () {
        alert("Password changed");
        $("#profile-old-password").val("");
        $("#profile-new-password").val("");
    });
}

function createProfileToken() {
    /* Generate a personal API token. */
    const groupId = $("#profile-token-group").val();

    apiPost("/api/profile/tokens", {
        name: $("#profile-token-name").val() || "personal-api-token",
        group_id: groupId ? Number(groupId) : null,
        scopes: $("#profile-token-scopes").val() || ["alerts:read"],
        days: Number($("#profile-token-days").val() || 0)
    }, function (data) {
        $("#profile-token-result").text(JSON.stringify(data, null, 2));
    });
}

$(document).on("click", "#save-profile", saveProfile);
$(document).on("click", "#change-profile-password", changeProfilePassword);
$(document).on("click", "#create-profile-token", createProfileToken);


function saveActiveGroup() {
    /* Set the active group from the profile page. */
    const groupId = $("#profile-active-group").val();

    apiPost("/api/profile/active-group", { group_id: groupId ? Number(groupId) : null }, function (user) {
        currentUser = user;
        updateAuthUi();
        fillTeamSelect("#global-team-filter", true, function () { navigate(window.location.pathname, false); });
        alert("Active group updated");
    });
}

$(document).on("click", "#save-active-group", saveActiveGroup);
