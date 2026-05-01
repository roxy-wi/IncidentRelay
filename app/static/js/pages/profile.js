let lastGeneratedProfileToken = "";

function getProfileInitials(profile) {
    /*
     * Build short initials for the profile avatar.
     */
    const source = profile.display_name || profile.username || "?";
    const parts = source.trim().split(/\s+/);

    if (parts.length >= 2) {
        return (parts[0][0] + parts[1][0]).toUpperCase();
    }

    return source.substring(0, 2).toUpperCase();
}


function setProfileStatus(selector, message, isError) {
    /*
     * Render a small inline status message.
     */
    const element = $(selector);

    element
        .text(message || "")
        .toggleClass("status-firing", !!isError)
        .toggleClass("status-resolved", !!message && !isError);
}


function renderProfileHeader(profile) {
    /*
     * Render profile summary header.
     */
    const title = profile.display_name || profile.username || "Profile";
    const metaItems = [];

    if (profile.username) {
        metaItems.push("@" + profile.username);
    }

    if (profile.email) {
        metaItems.push(profile.email);
    }

    $("#profile-avatar").text(getProfileInitials(profile));
    $("#profile-display-title").text(title);
    $("#profile-display-meta").text(metaItems.join(" · ") || "No contact information");

    renderProfileGroupsSummary(profile.groups || []);
}


function renderProfileGroupsSummary(groups) {
    /*
     * Render group badges in the profile hero.
     */
    const container = $("#profile-groups-summary");
    container.empty();

    if (!groups.length) {
        container.append(
            $("<span>")
                .addClass("badge")
                .addClass("badge-info")
                .text("No groups")
        );
        return;
    }

    groups.forEach(function (membership) {
        container.append(
            $("<span>")
                .addClass("badge")
                .addClass("badge-info")
                .text(membership.group_name + " · " + membership.role)
        );
    });
}


function renderProfileGroupsList(groups) {
    /*
     * Render group membership list for the Access context card.
     */
    const container = $("#profile-groups-list");
    container.empty();

    if (!groups.length) {
        container.text("No groups assigned.");
        return;
    }

    groups.forEach(function (membership) {
        const item = $("<div>").addClass("profile-group-item");

        item.append(
            $("<div>")
                .addClass("profile-group-name")
                .text(membership.group_name || membership.group_slug || ("Group #" + membership.group_id))
        );

        item.append(
            $("<div>")
                .addClass(membership.role === "rw" ? "role-rw" : "role-read-only")
                .text(membership.role === "rw" ? "Read/write" : "Read only")
        );

        container.append(item);
    });
}


function fillProfileGroupSelects(profile) {
    /*
     * Fill token group and active group selects from profile memberships.
     */
    const tokenGroupSelect = $("#profile-token-group");
    const activeGroupSelect = $("#profile-active-group");

    tokenGroupSelect.empty();
    activeGroupSelect.empty();

    tokenGroupSelect.append($("<option>").val("").text("No group limit"));
    activeGroupSelect.append($("<option>").val("").text("All my groups"));

    (profile.groups || []).forEach(function (membership) {
        const label = membership.group_name + " (" + membership.role + ")";

        tokenGroupSelect.append(
            $("<option>")
                .val(String(membership.group_id))
                .text(label)
        );

        activeGroupSelect.append(
            $("<option>")
                .val(String(membership.group_id))
                .text(label)
        );
    });

    if (profile.active_group_id) {
        activeGroupSelect.val(String(profile.active_group_id));
    }
}


function loadProfile() {
    /*
     * Load current user profile and render all profile sections.
     */
    apiGet("/api/profile", function (profile) {
        $("#profile-username").val(profile.username || "");
        $("#profile-display-name").val(profile.display_name || "");
        $("#profile-email").val(profile.email || "");
        $("#profile-phone").val(profile.phone || "");
        $("#profile-telegram").val(profile.telegram_chat_id || "");
        $("#profile-slack").val(profile.slack_user_id || "");
        $("#profile-mattermost").val(profile.mattermost_user_id || "");

        renderProfileHeader(profile);
        renderProfileGroupsList(profile.groups || []);
        fillProfileGroupSelects(profile);
    });
}


function saveProfile() {
    /*
     * Save the current user profile.
     */
    setProfileStatus("#profile-save-status", "Saving...", false);

    apiPut(
        "/api/profile",
        {
            display_name: $("#profile-display-name").val() || null,
            email: $("#profile-email").val() || null,
            phone: $("#profile-phone").val() || null,
            telegram_chat_id: $("#profile-telegram").val() || null,
            slack_user_id: $("#profile-slack").val() || null,
            mattermost_user_id: $("#profile-mattermost").val() || null
        },
        function (profile) {
            setProfileStatus("#profile-save-status", "Saved", false);
            renderProfileHeader(profile);
            loadProfile();
        }
    );
}


function changeProfilePassword() {
    /*
     * Change current user password.
     */
    const oldPassword = $("#profile-old-password").val();
    const newPassword = $("#profile-new-password").val();

    if (!oldPassword || !newPassword) {
        setProfileStatus("#profile-password-status", "Old and new password are required.", true);
        return;
    }

    apiPost(
        "/api/profile/change-password",
        {
            old_password: oldPassword,
            new_password: newPassword
        },
        function () {
            $("#profile-old-password").val("");
            $("#profile-new-password").val("");
            setProfileStatus("#profile-password-status", "Password changed", false);
        }
    );
}


function createProfileToken() {
    /*
     * Generate a personal API token.
     */
    const groupId = $("#profile-token-group").val();
    const scopes = $("#profile-token-scopes").val() || ["alerts:read"];
    const days = Number($("#profile-token-days").val() || 0);
    const name = $("#profile-token-name").val().trim() || "personal-api-token";

    if (days < 0) {
        setProfileStatus("#profile-token-status", "Expiration days cannot be negative.", true);
        return;
    }

    setProfileStatus("#profile-token-status", "Generating...", false);

    apiPost(
        "/api/profile/tokens",
        {
            name: name,
            group_id: groupId ? Number(groupId) : null,
            scopes: scopes,
            days: days
        },
        function (data) {
            lastGeneratedProfileToken = data.token || "";

            $("#profile-token-result").text(JSON.stringify(data, null, 2));
            $("#copy-profile-token").toggleClass("is-hidden", !lastGeneratedProfileToken);

            setProfileStatus("#profile-token-status", "Token generated", false);
        }
    );
}


function copyProfileToken() {
    /*
     * Copy the last generated profile token to the clipboard.
     */
    if (!lastGeneratedProfileToken) {
        return;
    }

    navigator.clipboard.writeText(lastGeneratedProfileToken).then(function () {
        setProfileStatus("#profile-token-status", "Token copied", false);
    });
}


function saveActiveGroup() {
    /*
     * Set the active group from the profile page.
     */
    const groupId = $("#profile-active-group").val();

    setProfileStatus("#profile-active-group-status", "Updating...", false);

    apiPost(
        "/api/profile/active-group",
        {
            group_id: groupId ? Number(groupId) : null
        },
        function (user) {
            currentUser = user;

            updateAuthUi();
            renderProfileHeader(user);
            renderProfileGroupsList(user.groups || []);

            fillTeamSelect("#global-team-filter", true, function () {
                navigate(window.location.pathname, false);
            });

            setProfileStatus("#profile-active-group-status", "Active group updated", false);
        }
    );
}

function profileModal(selector) {
    /*
     * Return profile modal element by selector.
     */
    return $(selector);
}


function openProfileModal(selector) {
    /*
     * Open a profile modal.
     */
    profileModal(selector).css("display", "flex").addClass("is-open");
    $("body").addClass("modal-open");
}


function closeProfileModal(selector) {
    /*
     * Close a profile modal.
     */
    profileModal(selector).css("display", "none").removeClass("is-open");
    $("body").removeClass("modal-open");
}


function setProfileInlineStatus(selector, message, isError) {
    /*
     * Render inline profile status.
     */
    $(selector)
        .text(message || "")
        .toggleClass("status-firing", !!isError)
        .toggleClass("status-resolved", !!message && !isError);
}


function loadProfileTokens() {
    /*
     * Load current user's personal API tokens.
     */
    apiGet("/api/profile/tokens", function (tokens) {
        renderProfileTokens(asArray(tokens));
    });
}


function renderProfileTokens(tokens) {
    /*
     * Render token metadata table.
     */
    const tbody = $("#profile-tokens-table");
    tbody.empty();

    if (!tokens.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>")
                    .attr("colspan", "9")
                    .addClass("empty-table-cell")
                    .text("No personal API tokens")
            )
        );
        return;
    }

    tokens.forEach(function (token) {
        tbody.append(renderProfileTokenRow(token));
    });
}


function renderProfileTokenRow(token) {
    /*
     * Render one token metadata row.
     */
    const row = $("<tr>").toggleClass("row-disabled", !token.active || token.expired);

    row.append($("<td>").text(token.name || "-"));
    row.append($("<td>").text(token.token_prefix || "-"));
    row.append($("<td>").text(token.group_name || token.group_slug || "No group limit"));
    row.append($("<td>").text((token.scopes || []).join(", ") || "-"));
    row.append($("<td>").text(formatDateTime24(token.created_at, {seconds: false})));
    row.append($("<td>").text(token.expires_at ? formatDateTime24(token.expires_at, {seconds: false}) : "Never"));
    row.append($("<td>").text(token.last_used_at ? formatDateTime24(token.last_used_at, {seconds: false}) : "Never"));

    row.append(
        $("<td>").append(
            $("<span>")
                .addClass("badge")
                .addClass(token.active && !token.expired ? "badge-success" : "badge-muted")
                .text(token.expired ? "Expired" : (token.active ? "Active" : "Revoked"))
        )
    );

    const actions = $("<div>").addClass("table-actions");

    if (token.active && !token.expired) {
        actions.append(
            $("<button>")
                .attr("type", "button")
                .addClass("btn btn-danger btn-small")
                .text("Revoke")
                .on("click", function () {
                    revokeProfileToken(token);
                })
        );
    }

    row.append($("<td>").addClass("actions-cell").append(actions));

    return row;
}


function revokeProfileToken(token) {
    /*
     * Revoke a personal API token.
     */
    if (!confirm("Revoke token \"" + (token.name || token.id) + "\"?")) {
        return;
    }

    apiDelete("/api/profile/tokens/" + token.id, function () {
        loadProfileTokens();
    });
}


function resetProfileTokenModal() {
    /*
     * Reset token generation modal output.
     */
    lastGeneratedProfileToken = "";
    $("#profile-token-result").text("No token generated yet.");
    $("#copy-profile-token").addClass("is-hidden");
    setProfileInlineStatus("#profile-token-status", "", false);
}


function createProfileToken() {
    /*
     * Generate a personal API token.
     */
    const groupId = $("#profile-token-group").val();
    const days = Number($("#profile-token-days").val() || 0);
    const name = $("#profile-token-name").val().trim() || "personal-api-token";

    if (days < 0) {
        setProfileInlineStatus("#profile-token-status", "Expiration days cannot be negative.", true);
        return;
    }

    apiPost(
        "/api/profile/tokens",
        {
            name: name,
            group_id: groupId ? Number(groupId) : null,
            scopes: $("#profile-token-scopes").val() || ["alerts:read"],
            days: days
        },
        function (data) {
            lastGeneratedProfileToken = data.token || "";

            $("#profile-token-result").text(lastGeneratedProfileToken || JSON.stringify(data, null, 2));
            $("#copy-profile-token").toggleClass("is-hidden", !lastGeneratedProfileToken);

            setProfileInlineStatus("#profile-token-status", "Token generated", false);
            loadProfileTokens();
        }
    );
}


function copyProfileToken() {
    /*
     * Copy the last generated token to clipboard.
     */
    if (!lastGeneratedProfileToken) {
        return;
    }

    navigator.clipboard.writeText(lastGeneratedProfileToken).then(function () {
        setProfileInlineStatus("#profile-token-status", "Token copied", false);
    });
}


function changeProfilePassword() {
    /*
     * Change current user password from modal.
     */
    const oldPassword = $("#profile-old-password").val();
    const newPassword = $("#profile-new-password").val();

    if (!oldPassword || !newPassword) {
        setProfileInlineStatus(
            "#profile-password-modal-status",
            "Old and new password are required.",
            true
        );
        return;
    }

    apiPost(
        "/api/profile/change-password",
        {
            old_password: oldPassword,
            new_password: newPassword
        },
        function () {
            $("#profile-old-password").val("");
            $("#profile-new-password").val("");

            setProfileInlineStatus("#profile-password-modal-status", "Password changed", false);
            setProfileInlineStatus("#profile-password-status", "Password changed", false);

            closeProfileModal("#profile-password-modal");
        }
    );
}

$(document).on("click", "#open-profile-token-modal", function () {
    resetProfileTokenModal();
    openProfileModal("#profile-token-modal");
});

$(document).on("click", "#close-profile-token-modal", function () {
    closeProfileModal("#profile-token-modal");
});

$(document).on("click", "#open-profile-password-modal", function () {
    setProfileInlineStatus("#profile-password-modal-status", "", false);
    $("#profile-old-password").val("");
    $("#profile-new-password").val("");
    openProfileModal("#profile-password-modal");
});

$(document).on("click", "#close-profile-password-modal", function () {
    closeProfileModal("#profile-password-modal");
});

$(document).on("click", "#profile-token-modal, #profile-password-modal", function (event) {
    if (event.target === this || $(event.target).hasClass("app-modal-backdrop")) {
        closeProfileModal("#" + $(this).attr("id"));
    }
});

$(document).on("keydown", function (event) {
    if (event.key !== "Escape") {
        return;
    }

    if ($("#profile-token-modal").hasClass("is-open")) {
        closeProfileModal("#profile-token-modal");
    }

    if ($("#profile-password-modal").hasClass("is-open")) {
        closeProfileModal("#profile-password-modal");
    }
});

$(document).on("click", "#create-profile-token", createProfileToken);
$(document).on("click", "#copy-profile-token", copyProfileToken);
$(document).on("click", "#change-profile-password", changeProfilePassword);
$(document).on("click", "#save-profile", saveProfile);
$(document).on("click", "#save-profile-top", saveProfile);
$(document).on("click", "#save-active-group", saveActiveGroup);
loadProfileTokens();