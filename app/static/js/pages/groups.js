let selectedGroupForMembers = null;
let selectedGroupNameForMembers = "";
let groupsCache = [];
let groupMembersCache = [];


function loadGroups() {
  /*
   * Load groups and render the groups table.
   */
  RbacRoles.fillGroupSelect("#group-member-role", $("#group-member-role").val())
  ensureGroupScopedUserCreatePanel();
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
          .text(i18n.t("groups.empty.groups"))
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
                    .addClass("name-button")
                    .text(group.name || group.slug || i18n.t("groups.row.fallback", {id: group.id}))
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

    row.append($("<td>").addClass("table-cell-truncate-wide").text(group.description || "-"));

    row.append(
        $("<td>").append(
            renderGroupStatus(group.active)
        )
    );

    row.append(
        $("<td>")
            .addClass("actions-cell")
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
    .text(active ? i18n.t("groups.status.active") : i18n.t("groups.status.inactive"));
}

function renderGroupActions(group) {
    /*
     * Render group row actions as a shared three-dots menu.
     */
    return makeActionMenu({
        object: group,
        items: [
            {
                label: canEditGroup(group) ? i18n.t("groups.actions.edit") : i18n.t("groups.actions.details"),
                icon: canEditGroup(group) ? "fas fa-edit" : "fas fa-eye",
                onClick: function () {
                    openExistingGroupModal(group);
                }
            },
            {
                label: i18n.t("groups.actions.members"),
                icon: "fas fa-users",
                onClick: function () {
                    openExistingGroupModal(group);
                }
            },
            {
                label: group.active ? i18n.t("groups.actions.disable") : i18n.t("groups.actions.enable"),
                icon: group.active ? "fas fa-pause" : "fas fa-play",
                danger: group.active,
                visible: function () {
                    return canEditGroup(group);
                },
                onClick: function () {
                    setGroupActive(group, !group.active);
                }
            },
            {
                label: i18n.t("groups.actions.delete"),
                icon: "fas fa-trash",
                danger: true,
                visible: function () {
                    return isGlobalAdminUser();
                },
                onClick: function () {
                    deleteGroup(group);
                }
            }
        ]
    });
}
function getSelectedGroupForMembers() {
    /*
     * Return the currently selected group object for member permission checks.
     */
    return groupsCache.find(function (group) {
        return Number(group.id) === Number(selectedGroupForMembers);
    }) || null;
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
  resetGroupScopedUserCreateForm();
  setGroupMemberControlsEnabled(false);
  setGroupScopedUserCreateControlsEnabled(false);
  renderEmptyGroupMembers(i18n.t("groups.empty.members_save"));
  $("#group-modal-title").text(i18n.t("groups.modal.new"));
  $("#group-modal-subtitle").text(i18n.t("groups.modal.new_subtitle"));
  $("#group-members-title").text(i18n.t("groups.members.title"));
  openAppModal("#group-modal");
}

function openExistingGroupModal(group) {
  /*
   * Open modal for an existing group.
   */
  ensureGroupScopedUserCreatePanel();
  fillGroupForm(group);
  applyGroupFormPermissions(group);
  resetGroupMemberForm();
  resetGroupScopedUserCreateForm();
  setGroupMemberControlsEnabled(true);
  setGroupScopedUserCreateControlsEnabled(true);
  selectedGroupForMembers = group.id;
  selectedGroupNameForMembers = group.name || group.slug || i18n.t("groups.row.fallback", {id: group.id});
  $("#group-modal-title").text(i18n.t("groups.modal.details"));
  $("#group-modal-subtitle").text(selectedGroupNameForMembers);
  $("#group-members-title").text(i18n.t("groups.members.title_named", {name: selectedGroupNameForMembers}));
  openAppModal("#group-modal");
  loadGroupMembers(group.id, selectedGroupNameForMembers);
}
function applyGroupFormPermissions(group) {
    const canEdit = canEditGroup(group);
    const canManageUsers = canManageGroupUsers(group);

    $("#group-slug").prop("disabled", !canEdit);
    $("#group-name").prop("disabled", !canEdit);
    $("#group-description").prop("disabled", !canEdit);
    $("#group-active").prop("disabled", !canEdit);
    $("#save-group").prop("disabled", !canEdit);

    setGroupMemberControlsEnabled(canManageUsers);
    setGroupScopedUserCreateControlsEnabled(canManageUsers);
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
  const active = typeof activeOverride === "boolean" ? activeOverride : $("#group-active").is(":checked");
  return {
    slug: $("#group-slug").val().trim(),
    name: $("#group-name").val().trim(),
    description: $("#group-description").val().trim(),
    active: active,
  };
}

function saveGroup() {
    /*
     * Create or update a group.
     */
    const data = buildGroupPayload();
    const groupId = $("#group-id").val();
    if (!data.slug || !data.name) {
        showAppError(i18n.t("groups.validation.slug_name"));
        return;
    }
    if (groupId) {
        const group = groupsCache.find(function (item) {
            return Number(item.id) === Number(groupId);
        });

        if (group && !canEditGroup(group)) {
            showAppError(i18n.t("groups.permissions.edit"));
            return;
        }

        apiPut("/api/groups/" + groupId, data, function (group) {
            const updatedGroup = group || {
                id: Number(groupId),
                slug: data.slug,
                name: data.name,
                description: data.description,
                active: data.active,
            };

            selectedGroupForMembers = updatedGroup.id;
            selectedGroupNameForMembers = updatedGroup.name || updatedGroup.slug;

            $("#group-modal-subtitle").text(selectedGroupNameForMembers);
            $("#group-members-title").text(i18n.t("groups.members.title_named", {name: selectedGroupNameForMembers}));

            setGroupMemberControlsEnabled(true);
            setGroupScopedUserCreateControlsEnabled(true);

            loadGroups();
        });

        return;
    }
    apiPost("/api/groups", data, function (group) {
        $("#group-id").val(group.id);
        selectedGroupForMembers = group.id;
        selectedGroupNameForMembers = group.name || group.slug || i18n.t("groups.row.fallback", {id: group.id});
        $("#group-modal-title").text(i18n.t("groups.modal.details"));
        $("#group-modal-subtitle").text(selectedGroupNameForMembers);
        $("#group-members-title").text(i18n.t("groups.members.title_named", {name: selectedGroupNameForMembers}));
        setGroupMemberControlsEnabled(true);
        setGroupScopedUserCreateControlsEnabled(true);
        loadGroups();
        loadGroupMembers(group.id, selectedGroupNameForMembers);
    });
}

function setGroupActive(group, active) {
  /*
   * Enable or disable a group using the existing update endpoint.
   */
  const action = active ? i18n.t("groups.confirm.enable_action") : i18n.t("groups.confirm.disable_action");
  showAppConfirm({
    title: i18n.t("groups.confirm.title"),
    message: i18n.t("groups.confirm.toggle_group", {action: action}),
    confirmText: active ? i18n.t("groups.actions.enable") : i18n.t("groups.actions.disable"),
    confirmClass: active ? "btn-success" : "btn-warning",
  }).done(function () {
    apiPut(
      "/api/groups/" + group.id,
      {
        slug: group.slug,
        name: group.name,
        description: group.description || "",
        active: active,
      },
      function () {
        if (Number($("#group-id").val()) === Number(group.id)) {
          $("#group-active").prop("checked", active);
        }
        loadGroups();
      }
    );
  });
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
   setEnhancedSelectDisabled("#group-member-user", !enabled);
    $("#group-member-role").prop("disabled", !enabled);
    $("#group-member-active").prop("disabled", !enabled);
    $("#save-group-member").prop("disabled", !enabled);
    $("#reset-group-member-form").prop("disabled", !enabled);
    $("#reload-group-members").prop("disabled", !enabled);

    $("#group-member-help").text(
        enabled
            ? i18n.t("groups.members.help_saved")
            : i18n.t("groups.members.help_unsaved")
    );

    RbacRoles.fillGroupSelect("#group-member-role", $("#group-member-role").val());
}

function loadGroupMembers(groupId, groupName) {
  /*
   * Load members for one group.
   */
  selectedGroupForMembers = groupId;
  selectedGroupNameForMembers = groupName;
  $("#group-members-title").text(i18n.t("groups.members.title_named", {name: groupName}));
  const tbody = $("#group-members-table");
  tbody.empty();
  apiGet("/api/groups/" + groupId + "/users", function (members) {
    groupMembersCache = asArray(members);
    if (!groupMembersCache.length) {
      renderEmptyGroupMembers(i18n.t("groups.empty.members"));
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
                .addClass(RbacRoles.groupClass(member.role))
                .text(RbacRoles.groupLabel(member.role))
        )
    );

    row.append(
        $("<td>").append(
            $("<span>")
                .addClass("status-pill")
                .addClass(member.active ? "status-active" : "status-inactive")
                .text(member.active ? i18n.t("groups.status.active") : i18n.t("groups.status.inactive"))
        )
    );

    row.append(
        $("<td>")
            .addClass("actions-cell")
            .append(renderGroupMemberActions(member))
    );

    return row;
}

function renderGroupMemberActions(member) {
    /*
     * Render group member row actions as a shared three-dots menu.
     */
    const selectedGroup = getSelectedGroupForMembers();

    return makeActionMenu({
        object: selectedGroup,
        items: [
            {
                label: i18n.t("groups.actions.edit"),
                icon: "fas fa-edit",
                required: "manage_users",
                denyMessage: i18n.t("groups.permissions.member_edit"),
                onClick: function () {
                    editGroupMember(member);
                }
            },
            {
                label: member.active ? i18n.t("groups.actions.disable") : i18n.t("groups.actions.enable"),
                icon: member.active ? "fas fa-pause" : "fas fa-play",
                required: "manage_users",
                danger: member.active,
                denyMessage: i18n.t("groups.permissions.member_toggle"),
                onClick: function () {
                    setGroupMemberActive(member, !member.active);
                }
            },
            {
                label: i18n.t("groups.actions.delete"),
                icon: "fas fa-trash",
                required: "manage_users",
                danger: true,
                denyMessage: i18n.t("groups.permissions.member_delete"),
                onClick: function () {
                    deleteGroupMember(member);
                }
            }
        ]
    });
}

function editGroupMember(member) {
    /*
     * Load membership data into the group member form.
     */
    $("#group-member-form-title").text(i18n.t("groups.members.edit_title", {id: member.id}));
    $("#group-membership-id").val(member.id);
    setSelectValue("#group-member-user", member.user_id);
    setEnhancedSelectDisabled("#group-member-user", true);
    fillAssignableGroupRoleSelect("#group-member-role", member.role);
    $("#group-member-active").prop("checked", !!member.active);
}

function resetGroupMemberForm() {
    /*
     * Reset group member form.
     */
    $("#group-member-form-title").text(i18n.t("groups.members.add_existing_title"));
    $("#group-membership-id").val("");
    setSelectValue("#group-member-user", "");
    setEnhancedSelectDisabled("#group-member-user", !selectedGroupForMembers);
    fillAssignableGroupRoleSelect("#group-member-role", GROUP_VIEWER_ROLE);
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
    showAppError(i18n.t("groups.validation.group_first"));
    return;
  }
  if (membershipId) {
    apiPut(
        "/api/groups/users/" + membershipId,
        {
          role: $("#group-member-role").val(),
          active: $("#group-member-active").is(":checked"),
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
    showAppError(i18n.t("groups.validation.user"));
    return;
  }
  apiPost(
      "/api/groups/" + groupId + "/users",
      {
        user_id: userId,
        role: $("#group-member-role").val(),
        active: $("#group-member-active").is(":checked"),
      },
      function () {
        resetGroupMemberForm();
        loadGroupMembers(groupId, selectedGroupNameForMembers);
      }
  );
}
function deleteGroupMember(member) {
  /*
   * Remove user from group membership completely.
   * Backend also removes this user from teams and rotations inside this group.
   */
  showAppConfirm({
    title: i18n.t("groups.confirm.delete_membership_title"),
    message: i18n.t("groups.confirm.delete_membership_message", {
      user: member.username || member.display_name || ("#" + member.user_id),
    }),
    confirmText: i18n.t("groups.actions.delete"),
    confirmClass: "btn-danger",
  }).done(function () {
    apiDelete("/api/groups/users/" + member.id, function () {
      resetGroupMemberForm();
      loadGroupMembers(selectedGroupForMembers, selectedGroupNameForMembers);
      loadGroups();
    });
  });
}
function setGroupMemberActive(member, active) {
  /*
   * Enable or disable group membership using the existing update endpoint.
   */
  const action = active ? i18n.t("groups.confirm.enable_action") : i18n.t("groups.confirm.disable_action");
  showAppConfirm({
    title: i18n.t("groups.confirm.title"),
    message: i18n.t("groups.confirm.toggle_membership", {action: action}),
    confirmText: active ? i18n.t("groups.actions.enable") : i18n.t("groups.actions.disable"),
    confirmClass: active ? "btn-success" : "btn-warning",
  }).done(function () {
    apiPut(
        "/api/groups/users/" + member.id,
        {
          role: member.role || GROUP_VIEWER_ROLE,
          active: active,
        },
        function () {
          resetGroupMemberForm();
          loadGroupMembers(selectedGroupForMembers, selectedGroupNameForMembers);
        }
    );
  });
}

function ensureGroupScopedUserCreatePanel() {
  /*
   * The group-scoped user creation form is part of groups.html.
   * Keep this guard only to avoid crashes if an older template is installed.
   */
  return $("#group-user-create-panel").length > 0;
}

function resetGroupScopedUserCreateForm() {
  ensureGroupScopedUserCreatePanel();
  $("#group-create-user-username").val("");
  $("#group-create-user-display").val("");
  $("#group-create-user-email").val("");
  $("#group-create-user-phone").val("");
  $("#group-create-user-password").val("");
  fillAssignableGroupRoleSelect("#group-create-user-role", GROUP_VIEWER_ROLE);
}

function setGroupScopedUserCreateControlsEnabled(enabled) {
  ensureGroupScopedUserCreatePanel();
  $("#group-create-user-username").prop("disabled", !enabled);
  $("#group-create-user-display").prop("disabled", !enabled);
  $("#group-create-user-email").prop("disabled", !enabled);
  $("#group-create-user-phone").prop("disabled", !enabled);
  $("#group-create-user-password").prop("disabled", !enabled);
  $("#group-create-user-role").prop("disabled", !enabled);
  $("#save-group-created-user").prop("disabled", !enabled);
  $("#reset-group-created-user").prop("disabled", !enabled);
  $("#group-create-user-help").text(
    enabled
      ? i18n.t("groups.create_user.enabled_help", {
          group: selectedGroupNameForMembers || selectedGroupForMembers || i18n.t("groups.create_user.selected"),
        })
      : i18n.t("groups.create_user.disabled_help")
  );
}

function collectGroupScopedUserCreatePayload() {
  return {
    username: $("#group-create-user-username").val().trim(),
    display_name: $("#group-create-user-display").val().trim() || null,
    email: $("#group-create-user-email").val().trim() || null,
    phone: $("#group-create-user-phone").val().trim() || null,
    password: $("#group-create-user-password").val() || null,
    group_role: $("#group-create-user-role").val() || GROUP_VIEWER_ROLE,
  };
}

function saveGroupScopedUser() {
  const groupId = selectedGroupForMembers || Number($("#group-id").val());
  if (!groupId) {
    showAppError(i18n.t("groups.validation.group_first"));
    return;
  }
  const payload = collectGroupScopedUserCreatePayload();
  if (!payload.username) {
    showAppError(i18n.t("groups.validation.username"));
    return;
  }
  if (!payload.password) {
    showAppError(i18n.t("groups.validation.password"));
    return;
  }
  apiPost("/api/groups/" + groupId + "/users/create", payload, function () {
    resetGroupScopedUserCreateForm();
    fillGroupMemberUserSelect();
    loadGroupMembers(groupId, selectedGroupNameForMembers);
  });
}

$(document).on("click", "#reload-groups", loadGroups);
$(document).on("click", "#new-group", openNewGroupModal);
$(document).on("click", "#save-group", saveGroup);
$(document).on("click", "#clear-group-form", function () {
  clearGroupForm();
  resetGroupMemberForm();
  resetGroupScopedUserCreateForm();
  setGroupScopedUserCreateControlsEnabled(false);
  renderEmptyGroupMembers(i18n.t("groups.empty.members_save"));
});
$(document).on("click", "#save-group-member", saveGroupMember);
$(document).on("click", "#reset-group-member-form", resetGroupMemberForm);
$(document).on("click", "#save-group-created-user", saveGroupScopedUser);
$(document).on("click", "#reset-group-created-user", resetGroupScopedUserCreateForm);
$(document).on("click", "#reload-group-members", function () {
  if (!selectedGroupForMembers) {
    return;
  }
  loadGroupMembers(selectedGroupForMembers, selectedGroupNameForMembers);
});
$(document).on("click", "#close-group-modal, #close-group-modal-footer", closeAppModal);
$(document).on("click", "#group-modal", function (event) {
  if (event.target === this) {
    closeAppModal("#group-modal");
  }
});
$(document).on("keydown", function (event) {
  if (event.key === "Escape" && !$("#group-modal").hasClass("is-hidden")) {
    closeAppModal("#group-modal");
  }
});
function deleteGroup(group) {
  /*
   * Soft-delete a group and all resources under it.
   */
  const groupName = group.name || group.slug || i18n.t("groups.row.fallback", {id: group.id});

  showAppConfirm({
    title: i18n.t("groups.confirm.delete_group_title"),
    message: i18n.t("groups.confirm.delete_group_message", {
        group: groupName,
      }),
    confirmText: i18n.t("groups.actions.delete"),
    confirmClass: "btn-danger",
  }).done(function () {
    apiDelete("/api/groups/" + group.id, function () {
      if (Number($("#group-id").val()) === Number(group.id)) {
        closeAppModal("#group-modal");
        clearGroupForm();
        resetGroupMemberForm();
        resetGroupScopedUserCreateForm();
        selectedGroupForMembers = null;
        selectedGroupNameForMembers = "";
      }

      loadGroups();
    });
  });
}

function canEditGroup(group) {
    return isGlobalAdminUser()
        || !!(group.permissions && group.permissions.can_write);
}

function canManageGroupUsers(group) {
    return isGlobalAdminUser()
        || !!(group.permissions && group.permissions.can_manage_users);
}

function fillAssignableGroupRoleSelect(selector, selectedValue) {
    if (isGlobalAdminUser()) {
        RbacRoles.fillGroupSelect(selector, selectedValue);
        return;
    }

    RbacRoles.fillSelect(
        selector,
        GROUP_ROLES.filter(function (role) {
            return role.value !== GROUP_USER_ADMIN_ROLE;
        }),
        selectedValue || GROUP_VIEWER_ROLE,
        GROUP_VIEWER_ROLE
    );
}
