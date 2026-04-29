let adminUsersCache = [];

function loadAdminUsers() {
    /* Load admin users page. */
    refreshAdminUsers();
}

function refreshAdminUsers() {
    /* Refresh admin user table. */
    apiGet("/api/admin/users", function (users) {
        users = asArray(users);
        adminUsersCache = users;
        const tbody = $("#admin-users-table");
        tbody.empty();
        users.forEach(function (user) {
            const row = $("<tr>");
            row.append($("<td>").text(user.id));
            row.append($("<td>").text(user.username));
            row.append($("<td>").text(user.email || "-"));
            row.append($("<td>").text(user.is_admin ? "yes" : "no"));
            row.append($("<td>").text(user.active ? "yes" : "no"));
            const actions = $("<td>").addClass("actions");
            actions.append($("<button>").addClass("btn btn-small").text("Edit").on("click", function () { editAdminUser(user.id); }));
            actions.append($("<button>").addClass("btn btn-danger btn-small").text("Delete").on("click", function () { deleteAdminUser(user.id); }));
            row.append(actions);
            tbody.append(row);
        });
    });
}

function collectAdminUserPayload() {
    /* Build user payload. */
    return {
        username: $("#admin-user-username").val(),
        display_name: $("#admin-user-display").val(),
        email: $("#admin-user-email").val() || null,
        phone: $("#admin-user-phone").val() || null,
        telegram_chat_id: $("#admin-user-telegram").val() || null,
        slack_user_id: $("#admin-user-slack").val() || null,
        mattermost_user_id: $("#admin-user-mattermost").val() || null,
        password: $("#admin-user-password").val() || null,
        is_admin: $("#admin-user-is-admin").is(":checked"),
        active: $("#admin-user-active").is(":checked")
    };
}

function saveAdminUser() {
    /* Create or update an admin user. */
    const id = $("#admin-user-id").val();
    if (id) { apiPut("/api/admin/users/" + id, collectAdminUserPayload(), function () { resetAdminUserForm(); refreshAdminUsers(); }); }
    else { apiPost("/api/users", collectAdminUserPayload(), function () { resetAdminUserForm(); refreshAdminUsers(); }); }
}

function editAdminUser(id) {
    /* Load user data into the form. */
    const user = adminUsersCache.find(function (item) { return item.id === id; });
    if (!user) { return; }
    $("#admin-user-form-title").text("Edit user #" + id);
    $("#admin-user-id").val(user.id);
    $("#admin-user-username").val(user.username);
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

function deleteAdminUser(id) {
    /* Disable a user. */
    if (!confirm("Disable this user?")) { return; }
    apiDelete("/api/admin/users/" + id, refreshAdminUsers);
}

function resetAdminUserForm() {
    /* Reset admin user form. */
    $("#admin-user-form-title").text("Create user");
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

$(document).on("click", "#admin-save-user", saveAdminUser);
$(document).on("click", "#admin-reset-user-form", resetAdminUserForm);
$(document).on("click", "#reload-admin-users", refreshAdminUsers);
