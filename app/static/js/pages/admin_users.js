let adminUsersCache = [];


function loadAdminUsers() {
    /*
     * Load admin users page.
     */
    refreshAdminUsers();
}


function refreshAdminUsers() {
    /*
     * Refresh admin user table.
     */
    apiGet("/api/admin/users", function (users) {
        adminUsersCache = asArray(users);

        renderAdminUsersSummary(adminUsersCache);
        renderAdminUsersTable(getFilteredAdminUsers());
    });
}


function renderAdminUsersSummary(users) {
    /*
     * Render summary cards for the admin users page.
     */
    const activeUsers = users.filter(function (user) {
        return !!user.active;
    });

    const adminUsers = users.filter(function (user) {
        return !!user.is_admin;
    });

    $("#admin-users-total-count").text(users.length);
    $("#admin-users-active-count").text(activeUsers.length);
    $("#admin-users-inactive-count").text(users.length - activeUsers.length);
    $("#admin-users-admin-count").text(adminUsers.length);
}


function getFilteredAdminUsers() {
    /*
     * Return users filtered by search input.
     */
    const query = ($("#admin-users-search").val() || "").trim().toLowerCase();

    if (!query) {
        return adminUsersCache;
    }

    return adminUsersCache.filter(function (user) {
        return [
            user.id,
            user.username,
            user.display_name,
            user.email,
            user.phone,
            user.telegram_chat_id,
            user.slack_user_id,
            user.mattermost_user_id
        ].join(" ").toLowerCase().indexOf(query) !== -1;
    });
}


function renderAdminUsersTable(users) {
    /*
     * Render users table.
     */
    const tbody = $("#admin-users-table");
    tbody.empty();

    if (!users.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>")
                    .attr("colspan", "7")
                    .text("No users")
            )
        );
        return;
    }

    users.forEach(function (user) {
        tbody.append(renderAdminUserRow(user));
    });
}


function renderAdminUserRow(user) {
    /*
     * Render one admin user row.
     */
    const row = $("<tr>").toggleClass("row-disabled", !user.active);

    row.append($("<td>").text(user.id));

    row.append(
        $("<td>")
            .append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("team-name-button")
                    .text(user.display_name || user.username || ("User #" + user.id))
                    .on("click", function () {
                        openExistingAdminUserModal(user);
                    })
            )
            .append(
                $("<div>")
                    .addClass("details-meta")
                    .text("@" + (user.username || "-"))
            )
    );

    row.append($("<td>").append(renderAdminUserContacts(user)));
    row.append($("<td>").append(renderAdminUserMessengers(user)));

    row.append(
        $("<td>").append(
            $("<span>")
                .addClass(user.is_admin ? "role-rw" : "role-read-only")
                .text(user.is_admin ? "Admin" : "User")
        )
    );

    row.append(
        $("<td>").append(
            $("<span>")
                .addClass("status-pill")
                .addClass(user.active ? "status-active" : "status-inactive")
                .text(user.active ? "Active" : "Inactive")
        )
    );

    row.append(
        $("<td>")
            .addClass("actions")
            .append(renderAdminUserActions(user))
    );

    return row;
}


function renderAdminUserContacts(user) {
    /*
     * Render user contact information.
     */
    const box = $("<div>").addClass("details-compact-list");

    box.append(
        $("<div>").text(user.email || "No email")
    );

    box.append(
        $("<div>")
            .addClass("details-meta")
            .text(user.phone || "No phone")
    );

    return box;
}


function renderAdminUserMessengers(user) {
    /*
     * Render messenger identifiers.
     */
    const box = $("<div>").addClass("details-compact-list");

    box.append(
        $("<div>").text("Telegram: " + (user.telegram_chat_id || "-"))
    );

    box.append(
        $("<div>")
            .addClass("details-meta")
            .text("Slack: " + (user.slack_user_id || "-"))
    );

    box.append(
        $("<div>")
            .addClass("details-meta")
            .text("Mattermost: " + (user.mattermost_user_id || "-"))
    );

    return box;
}


function renderAdminUserActions(user) {
    /*
     * Render user row actions.
     */
    const actions = $("<div>").addClass("actions");

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-small")
            .text("Edit")
            .on("click", function () {
                openExistingAdminUserModal(user);
            })
    );

    if (user.active) {
        actions.append(
            $("<button>")
                .attr("type", "button")
                .addClass("btn btn-warning btn-small")
                .text("Disable")
                .on("click", function () {
                    setAdminUserActive(user, false);
                })
        );
    } else {
        actions.append(
            $("<button>")
                .attr("type", "button")
                .addClass("btn btn-success btn-small")
                .text("Enable")
                .on("click", function () {
                    setAdminUserActive(user, true);
                })
        );
    }

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-danger btn-small")
            .text("Remove")
            .on("click", function () {
                removeAdminUser(user);
            })
    );

    return actions;
}


function openAdminUserModal() {
    /*
     * Open admin user modal.
     */
    $("#admin-user-modal").removeClass("is-hidden");
}


function closeAdminUserModal() {
    /*
     * Close admin user modal.
     */
    $("#admin-user-modal").addClass("is-hidden");
}


function openNewAdminUserModal() {
    /*
     * Open modal for a new user.
     */
    resetAdminUserForm();

    $("#admin-user-modal-title").text("New user");
    $("#admin-user-modal-subtitle").text("Create local user account.");

    $("#admin-user-password").attr("placeholder", "Password");
    openAdminUserModal();
}


function openExistingAdminUserModal(user) {
    /*
     * Open modal for an existing user.
     */
    fillAdminUserForm(user);

    $("#admin-user-modal-title").text("User details");
    $("#admin-user-modal-subtitle").text(user.display_name || user.username || ("User #" + user.id));

    $("#admin-user-password").attr("placeholder", "Leave empty to keep current password");
    openAdminUserModal();
}


function collectAdminUserPayload() {
    /*
     * Build user payload.
     */
    return {
        username: $("#admin-user-username").val().trim(),
        display_name: $("#admin-user-display").val().trim() || null,
        email: $("#admin-user-email").val().trim() || null,
        phone: $("#admin-user-phone").val().trim() || null,
        telegram_chat_id: $("#admin-user-telegram").val().trim() || null,
        slack_user_id: $("#admin-user-slack").val().trim() || null,
        mattermost_user_id: $("#admin-user-mattermost").val().trim() || null,
        password: $("#admin-user-password").val() || null,
        is_admin: $("#admin-user-is-admin").is(":checked"),
        active: $("#admin-user-active").is(":checked")
    };
}


function validateAdminUserPayload(data, isCreate) {
    /*
     * Validate user form before sending it to the API.
     */
    if (!data.username) {
        showAppError("Username is required");
        return false;
    }

    if (isCreate && !data.password) {
        showAppError("Password is required for a new user");
        return false;
    }

    return true;
}


function saveAdminUser() {
    /*
     * Create or update an admin user.
     */
    const id = $("#admin-user-id").val();
    const data = collectAdminUserPayload();
    const isCreate = !id;

    if (!validateAdminUserPayload(data, isCreate)) {
        return;
    }

    if (id) {
        apiPut("/api/admin/users/" + id, data, function () {
            resetAdminUserForm();
            closeAdminUserModal();
            refreshAdminUsers();
        });
        return;
    }

    apiPost("/api/admin/users", data, function () {
        resetAdminUserForm();
        closeAdminUserModal();
        refreshAdminUsers();
    });
}


function fillAdminUserForm(user) {
    /*
     * Load user data into the form.
     */
    $("#admin-user-id").val(user.id);
    $("#admin-user-username").val(user.username || "");
    $("#admin-user-display").val(user.display_name || "");
    $("#admin-user-email").val(user.email || "");
    $("#admin-user-phone").val(user.phone || "");
    $("#admin-user-telegram").val(user.telegram_chat_id || "");
    $("#admin-user-slack").val(user.slack_user_id || "");
    $("#admin-user-mattermost").val(user.mattermost_user_id || "");
    $("#admin-user-password").val("");
    $("#admin-user-is-admin").prop("checked", !!user.is_admin);
    $("#admin-user-active").prop("checked", !!user.active);
}


function setAdminUserActive(user, active) {
    /*
     * Enable or disable user through the update endpoint.
     */
    const action = active ? "enable" : "disable";

    if (!confirm("Are you sure you want to " + action + " this user?")) {
        return;
    }

    apiPut(
        "/api/admin/users/" + user.id,
        {
            username: user.username,
            display_name: user.display_name || null,
            email: user.email || null,
            phone: user.phone || null,
            telegram_chat_id: user.telegram_chat_id || null,
            slack_user_id: user.slack_user_id || null,
            mattermost_user_id: user.mattermost_user_id || null,
            password: null,
            is_admin: !!user.is_admin,
            active: active
        },
        function () {
            refreshAdminUsers();
        }
    );
}


function resetAdminUserForm() {
    /*
     * Reset admin user form.
     */
    $("#admin-user-id").val("");
    $("#admin-user-username").val("");
    $("#admin-user-display").val("");
    $("#admin-user-email").val("");
    $("#admin-user-phone").val("");
    $("#admin-user-telegram").val("");
    $("#admin-user-slack").val("");
    $("#admin-user-mattermost").val("");
    $("#admin-user-password").val("");
    $("#admin-user-is-admin").prop("checked", false);
    $("#admin-user-active").prop("checked", true);
}


$(document).on("click", "#reload-admin-users", refreshAdminUsers);
$(document).on("input", "#admin-users-search", function () {
    renderAdminUsersTable(getFilteredAdminUsers());
});
$(document).on("click", "#new-admin-user", openNewAdminUserModal);
$(document).on("click", "#admin-save-user", saveAdminUser);
$(document).on("click", "#admin-reset-user-form", resetAdminUserForm);
$(document).on("click", "#close-admin-user-modal, #close-admin-user-modal-footer", closeAdminUserModal);
$(document).on("click", "#admin-user-modal", function (event) {
    if (event.target === this) {
        closeAdminUserModal();
    }
});
$(document).on("keydown", function (event) {
    if (event.key === "Escape" && !$("#admin-user-modal").hasClass("is-hidden")) {
        closeAdminUserModal();
    }
});

function removeAdminUser(user) {
    /*
     * Soft-delete a user from the admin workspace.
     */
    const message = [
        "Remove user \"" + (user.username || user.id) + "\"?",
        "",
        "This will revoke personal API tokens and remove the user from groups,",
        "teams, rotations and overrides.",
        "",
        "Historical alerts will be preserved.",
        "",
        "Continue?"
    ].join("\n");

    if (!confirm(message)) {
        return;
    }

    apiDelete("/api/admin/users/" + user.id, function () {
        resetAdminUserForm();
        closeAdminUserModal();
        refreshAdminUsers();
    });
}

