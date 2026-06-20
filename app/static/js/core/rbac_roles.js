var GROUP_VIEWER_ROLE = "viewer";
var GROUP_EDITOR_ROLE = "editor";
var GROUP_USER_ADMIN_ROLE = "user_admin";

var GROUP_ROLES = [
    { value: GROUP_VIEWER_ROLE, label: "Group Viewer" },
    { value: GROUP_EDITOR_ROLE, label: "Group Editor" },
    { value: GROUP_USER_ADMIN_ROLE, label: "Group Admin" },
];

var TEAM_VIEWER_ROLE = "viewer";
var TEAM_RESPONDER_ROLE = "responder";
var TEAM_MANAGER_ROLE = "manager";

var TEAM_ROLES = [
    { value: TEAM_VIEWER_ROLE, label: "Team Viewer" },
    { value: TEAM_RESPONDER_ROLE, label: "Team Responder" },
    { value: TEAM_MANAGER_ROLE, label: "Team Manager" },
];

window.RbacRoles = (function () {
    function getValue(value, fallbackValue) {
        return value || fallbackValue;
    }

    function label(roles, value, fallbackValue) {
        const safeRoles = Array.isArray(roles) ? roles : [];
        const selected = getValue(value, fallbackValue);
        const item = safeRoles.find(function (role) {
            return role.value === selected;
        });

        return item ? item.label : selected;
    }

    function fillSelect(selector, roles, selectedValue, fallbackValue) {
        const select = $(selector);
        const safeRoles = Array.isArray(roles) ? roles : [];
        const selected = selectedValue || select.val() || fallbackValue;

        select.empty();

        safeRoles.forEach(function (role) {
            select.append(
                $("<option>")
                    .val(role.value)
                    .text(role.label)
            );
        });

        if (safeRoles.some(function (role) { return role.value === selected; })) {
            select.val(selected);
            return;
        }

        if (safeRoles.length) {
            select.val(safeRoles[0].value);
        }
    }

    function groupLabel(role) {
        return label(GROUP_ROLES, role, GROUP_VIEWER_ROLE);
    }

    function teamLabel(role) {
        return label(TEAM_ROLES, role, TEAM_VIEWER_ROLE);
    }

    function groupClass(role) {
        const value = getValue(role, GROUP_VIEWER_ROLE);

        if (value === GROUP_USER_ADMIN_ROLE) {
            return "role-user-admin";
        }

        if (value === GROUP_EDITOR_ROLE) {
            return "role-editor";
        }

        return "role-viewer";
    }

    function teamClass(role) {
        const value = getValue(role, TEAM_VIEWER_ROLE);

        if (value === TEAM_MANAGER_ROLE) {
            return "role-manager";
        }

        if (value === TEAM_RESPONDER_ROLE) {
            return "role-responder";
        }

        return "role-viewer";
    }

    function fillGroupSelect(selector, selectedValue) {
        fillSelect(selector, GROUP_ROLES, selectedValue, GROUP_VIEWER_ROLE);
    }

    function fillTeamSelect(selector, selectedValue) {
        fillSelect(selector, TEAM_ROLES, selectedValue, TEAM_VIEWER_ROLE);
    }

    return {
        label: label,
        fillSelect: fillSelect,
        groupLabel: groupLabel,
        teamLabel: teamLabel,
        groupClass: groupClass,
        teamClass: teamClass,
        fillGroupSelect: fillGroupSelect,
        fillTeamSelect: fillTeamSelect,
    };
})();

function getCurrentUserGroupRole(groupId) {
    /*
     * Return current user's role in a group.
     */
    if (!currentUser || currentUser.is_admin) {
        return currentUser && currentUser.is_admin ? "global_admin" : null;
    }

    const group = asArray(currentUser.groups).find(function (item) {
        return Number(item.id) === Number(groupId)
            || Number(item.group_id) === Number(groupId);
    });

    return group ? group.role : null;
}

function canEditGroup(groupId) {
    /*
     * Return true when current user can edit operational objects in a group.
     */
    const role = getCurrentUserGroupRole(groupId);

    return !!(
        currentUser && (
            currentUser.is_admin
            || role === GROUP_EDITOR_ROLE
            || role === GROUP_USER_ADMIN_ROLE
        )
    );
}

function canManageGroupUsers(groupId) {
    /*
     * Return true when current user can manage users in a group.
     */
    const role = getCurrentUserGroupRole(groupId);

    return !!(
        currentUser && (
            currentUser.is_admin
            || role === GROUP_USER_ADMIN_ROLE
        )
    );
}

function getObjectPermissions(item) {
    /*
     * Return normalized permissions object from API payload.
     */
    return (item && item.permissions) || {};
}

function hasObjectPermissions(item) {
    const permissions = getObjectPermissions(item);
    return !!Object.keys(permissions).length;
}

function getObjectTeamRole(item) {
    return item && (item.current_user_role || item.user_role || item.role);
}

function canReadObject(item) {
    const permissions = getObjectPermissions(item);

    if (typeof permissions.can_read !== "undefined") {
        return !!permissions.can_read;
    }

    if (!currentUser) {
        return false;
    }

    if (currentUser.is_admin) {
        return true;
    }

    const teamRole = getObjectTeamRole(item);
    return teamRole === TEAM_VIEWER_ROLE
        || teamRole === TEAM_RESPONDER_ROLE
        || teamRole === TEAM_MANAGER_ROLE;
}

function canWriteObject(item) {
    const permissions = getObjectPermissions(item);

    if (typeof permissions.can_write !== "undefined") {
        return !!permissions.can_write;
    }

    if (!currentUser) {
        return false;
    }

    if (currentUser.is_admin) {
        return true;
    }

    const teamRole = getObjectTeamRole(item);
    return teamRole === TEAM_MANAGER_ROLE;
}

function canDeleteObject(item) {
    const permissions = getObjectPermissions(item);

    if (typeof permissions.can_delete !== "undefined") {
        return !!permissions.can_delete;
    }

    return canWriteObject(item);
}

function canRespondObject(item) {
    const permissions = getObjectPermissions(item);

    if (typeof permissions.can_respond !== "undefined") {
        return !!permissions.can_respond;
    }

    if (!currentUser) {
        return false;
    }

    if (currentUser.is_admin) {
        return true;
    }

    const teamRole = getObjectTeamRole(item);
    return teamRole === TEAM_RESPONDER_ROLE || teamRole === TEAM_MANAGER_ROLE;
}

function canManageUsersObject(item) {
    const permissions = getObjectPermissions(item);

    if (typeof permissions.can_manage_users !== "undefined") {
        return !!permissions.can_manage_users;
    }

    if (!currentUser) {
        return false;
    }

    if (currentUser.is_admin) {
        return true;
    }

    if (item && item.group_id && canManageGroupUsers(item.group_id)) {
        return true;
    }

    const teamRole = getObjectTeamRole(item);
    return teamRole === TEAM_MANAGER_ROLE;
}

function canActionObject(item, required) {
    const action = required || "write";

    if (action === "read") {
        return canReadObject(item);
    }

    if (action === "respond") {
        return canRespondObject(item);
    }

    if (action === "manage_users") {
        return canManageUsersObject(item);
    }

    if (action === "delete") {
        return canDeleteObject(item);
    }

    return canWriteObject(item);
}

function getCurrentUserActiveGroupId() {
    /*
     * Return the selected active group id from the current user or UI selector.
     */
    if (currentUser && currentUser.active_group_id) {
        return Number(currentUser.active_group_id);
    }

    const selectedGroup = Number($("#active-group-select").val());
    return selectedGroup || null;
}

function getCurrentUserGroups() {
    return asArray(currentUser && currentUser.groups).filter(function (group) {
        return group.active !== false;
    });
}

function getCurrentUserActiveGroupRole() {
    const activeGroupId = getCurrentUserActiveGroupId();
    const groups = getCurrentUserGroups();

    if (!activeGroupId) {
        return groups.length === 1 ? groups[0].role : null;
    }

    const group = groups.find(function (item) {
        return Number(item.group_id || item.id) === Number(activeGroupId);
    });

    return group ? group.role : null;
}

function hasCurrentUserGroupWriteAccess() {
    /*
     * Return true when the user is allowed to create operational objects.
     */
    if (!currentUser) {
        return false;
    }

    if (currentUser.is_admin) {
        return true;
    }

    return getCurrentUserGroups().some(function (group) {
        return group.role === GROUP_EDITOR_ROLE || group.role === GROUP_USER_ADMIN_ROLE;
    });
}

function isCurrentUserViewerOnly() {
    /*
     * Return true when every known group role is viewer/read-only.
     */
    if (!currentUser) {
        return true;
    }

    if (currentUser.is_admin) {
        return false;
    }

    const groups = getCurrentUserGroups();
    if (!groups.length) {
        return true;
    }

    return groups.every(function (group) {
        return !group.role || group.role === GROUP_VIEWER_ROLE || group.role === "viewer";
    });
}

function currentUserCanCreateUiObjects() {
    /*
     * UI-only helper for top-level New/Create buttons.
     * Backend permissions remain authoritative.
     */
    if (!currentUser) {
        return false;
    }

    if (currentUser.is_admin) {
        return true;
    }

    if (isCurrentUserViewerOnly()) {
        return false;
    }

    const activeRole = getCurrentUserActiveGroupRole();
    if (activeRole) {
        return activeRole !== GROUP_VIEWER_ROLE && activeRole !== "viewer";
    }

    return hasCurrentUserGroupWriteAccess();
}

function setElementAllowed(selector, allowed) {
    const element = $(selector);

    if (!element.length) {
        return;
    }

    element.toggleClass("is-hidden", !allowed);
    element.prop("disabled", !allowed);
}

function applyCreateButtonsVisibility() {
    /*
     * Hide top-level New/Create buttons according to current user role.
     */
    const canCreateOperationalObjects = currentUserCanCreateUiObjects();
    const isGlobalAdmin = !!(currentUser && currentUser.is_admin);
    const canManageUsers = typeof hasGroupUserAdminAccess === "function"
        ? hasGroupUserAdminAccess()
        : isGlobalAdmin;

    [
        "#open-team-create-modal",
        "#open-rotation-create-modal",
        "#open-route-create-modal",
        "#open-channel-create-modal",
        "#open-silence-create-modal",
    ].forEach(function (selector) {
        setElementAllowed(selector, canCreateOperationalObjects);
    });

    setElementAllowed("#new-admin-user", canManageUsers);
    setElementAllowed("#new-group", isGlobalAdmin);
    setElementAllowed("#open-sso-provider-create-modal", isGlobalAdmin);
    setElementAllowed("#add-sso-mapping", isGlobalAdmin);
}

function applyRbacUiState() {
    /*
     * Re-apply role-aware visibility after navigation and page refreshes.
     */
    applyCreateButtonsVisibility();
}

function isGlobalAdminUser() {
    return !!(currentUser && currentUser.is_admin);
}
