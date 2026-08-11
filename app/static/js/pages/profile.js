let lastGeneratedProfileToken = "";
let currentProfileData = null;

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

function setProfileInlineStatus(selector, message, isError) {
    /*
     * Render inline profile status.
     */
    $(selector)
        .text(message || "")
        .toggleClass("status-firing", !!isError)
        .toggleClass("status-resolved", !!message && !isError);
}

function renderProfileHeader(profile) {
    /*
     * Render profile summary header.
     */
    const title = profile.display_name || profile.username || i18n.t("profile.title");
    const metaItems = [];

    if (profile.username) {
        metaItems.push("@" + profile.username);
    }
    if (profile.email) {
        metaItems.push(profile.email);
    }

    $("#profile-avatar").text(getProfileInitials(profile));
    $("#profile-display-title").text(title);
    $("#profile-display-meta").text(metaItems.join(" · ") || i18n.t("profile.header.no_contact"));
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
                .text(i18n.t("profile.groups.none"))
        );
        return;
    }

    groups.forEach(function (membership) {
        const groupName = membership.group_name || membership.group_slug || i18n.t("profile.groups.fallback", {id: membership.group_id});
        container.append(
            $("<span>")
                .addClass("badge")
                .addClass("badge-info")
                .text(groupName + " · " + RbacRoles.groupLabel(membership.role))
        );
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

    tokenGroupSelect.append($("<option>").val("").text(i18n.t("profile.groups.no_limit")));
    activeGroupSelect.append($("<option>").val("").text(i18n.t("profile.groups.all")));

    (profile.groups || []).forEach(function (membership) {
        const groupName = membership.group_name || membership.group_slug || i18n.t("profile.groups.fallback", {id: membership.group_id});
        const label = groupName + " (" + RbacRoles.groupLabel(membership.role) + ")";
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

function getProfileTokenScopeValues() {
    const element = document.getElementById("profile-token-scopes");

    if (!element) {
        return [];
    }

    const value = element.tomselect
        ? element.tomselect.getValue()
        : $(element).val();

    if (Array.isArray(value)) {
        return value;
    }

    return value ? [value] : [];
}

function setProfileTokenScopeValues(values) {
    const element = document.getElementById("profile-token-scopes");
    const normalized = (values || []).map(String);

    if (!element) {
        return;
    }

    if (element.tomselect) {
        element.tomselect.setValue(normalized, true);
        return;
    }

    $(element).val(normalized);
}

function renderProfileTokenScopes(profile) {
    const element = document.getElementById("profile-token-scopes");

    if (!element) {
        return;
    }

    const selected = getProfileTokenScopeValues();
    let scopes = asArray(profile.available_token_scopes);

    if (!scopes.length) {
        scopes = $(element).find("option").map(function () {
            return String($(this).val());
        }).get();

        if (!profile.is_admin) {
            scopes = scopes.filter(function (scope) { return scope !== "*"; });
        }
    }

    if (element.tomselect) {
        element.tomselect.destroy();
    }

    const select = $(element);
    select.empty();

    scopes.forEach(function (scope) {
        select.append($("<option>").val(scope).text(scope));
    });

    const allowed = new Set(scopes);
    let nextSelected = selected.filter(function (scope) {
        return allowed.has(scope);
    });

    if (!nextSelected.length && allowed.has("alerts:read")) {
        nextSelected = ["alerts:read"];
    }

    select.val(nextSelected);

    if (typeof window.TomSelect !== "undefined") {
        new TomSelect(element, {
            create: false,
            persist: false,
            closeAfterSelect: false,
            maxOptions: 200,
            plugins: ["remove_button"],
            searchField: ["text", "value"]
        });
        setProfileTokenScopeValues(nextSelected);
    }
}

function loadProfile() {
    /*
     * Load current user profile and render all profile sections.
     */
    apiGet("/api/profile", function (profile) {
        currentProfileData = profile;
        $("#profile-username").val(profile.username || "");
        $("#profile-display-name").val(profile.display_name || "");
        $("#profile-email").val(profile.email || "");
        $("#profile-phone").val(profile.phone || "");
        $("#profile-timezone").val(profile.timezone || "");
        $("#profile-language").val(profile.locale || i18n.locale || "en");
        $("#profile-theme").val(profile.theme || "system");
        $("#profile-telegram").val(profile.telegram_user_id || "");
        $("#profile-slack").val(profile.slack_user_id || "");
        $("#profile-mattermost").val(profile.mattermost_user_id || "");
        $("#profile-notify-shift-start-email").prop(
            "checked",
            profile.notify_oncall_shift_start_email !== false
        );

        $("#profile-notify-shift-end-email").prop(
            "checked",
            profile.notify_oncall_shift_end_email !== false
        );

        $("#profile-notify-shift-start-mattermost").prop(
            "checked",
            profile.notify_oncall_shift_start_mattermost !== false
        );

        if (window.AppTimezones) {
            AppTimezones.initOptionalSelect("#profile-timezone", profile.timezone);
            AppTimezones.setOptionalSelectValue("#profile-timezone", profile.timezone);
        }

        renderProfileTokenScopes(profile);
        renderProfileCaldav(profile);
        renderProfileHeader(profile);
        fillProfileGroupSelects(profile);
    });
}

function saveProfile() {
    /*
     * Save the current user profile. Interface preference changes reload the
     * shell so every page and chart is rebuilt with the selected locale/theme.
     */
    const previousLocale = i18n.locale;
    const previousTheme = window.AppTheme
        ? AppTheme.getPreference()
        : "system";

    setProfileStatus("#profile-save-status", i18n.t("profile.status.saving"), false);
    apiPut(
        "/api/profile",
        {
            display_name: $("#profile-display-name").val() || null,
            email: $("#profile-email").val() || null,
            phone: $("#profile-phone").val() || null,
            timezone: window.AppTimezones
                ? AppTimezones.getOptionalSelectValue("#profile-timezone")
                : ($("#profile-timezone").val() || null),
            locale: $("#profile-language").val() || previousLocale,
            theme: $("#profile-theme").val() || "system",
            telegram_user_id: $("#profile-telegram").val() || null,
            slack_user_id: $("#profile-slack").val() || null,
            mattermost_user_id: $("#profile-mattermost").val() || null,
            notify_oncall_shift_start_email: $("#profile-notify-shift-start-email").is(":checked"),
            notify_oncall_shift_end_email: $("#profile-notify-shift-end-email").is(":checked"),
            notify_oncall_shift_start_mattermost: $("#profile-notify-shift-start-mattermost").is(":checked")
        },
        function (profile) {
            currentProfileData = profile;
            setProfileStatus("#profile-save-status", i18n.t("profile.status.saved"), false);
            renderProfileHeader(profile);

            if (window.AppTheme) {
                AppTheme.apply(profile.theme || "system");
            }

            if (profile.locale && profile.locale !== previousLocale) {
                i18n.setLocale(profile.locale);
                return;
            }

            if ((profile.theme || "system") !== previousTheme) {
                window.location.reload();
                return;
            }

            loadProfile();
        }
    );
}

function saveProfileShiftNotificationPreferences() {
    /*
     * Save shift notification preferences immediately when a switch changes.
     */
    setProfileInlineStatus("#profile-shift-notification-status", i18n.t("profile.status.saving"), false);

    apiPut(
        "/api/profile",
        {
            notify_oncall_shift_start_email: $("#profile-notify-shift-start-email").is(":checked"),
            notify_oncall_shift_end_email: $("#profile-notify-shift-end-email").is(":checked"),
            notify_oncall_shift_start_mattermost: $("#profile-notify-shift-start-mattermost").is(":checked")
        },
        function (profile) {
            currentProfileData = profile;
            setProfileInlineStatus("#profile-shift-notification-status", i18n.t("profile.status.saved"), false);
            renderProfileHeader(profile);
        },
        function (xhr) {
            setProfileInlineStatus(
                "#profile-shift-notification-status",
                getApiErrorMessage(xhr, i18n.t("profile.status.save_notifications_failed")),
                true
            );
        }
    );
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
                    .text(i18n.t("profile.tokens.none"))
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
    row.append($("<td>").text(token.group_name || token.group_slug || i18n.t("profile.groups.no_limit")));
    row.append($("<td>").text((token.scopes || []).join(", ") || "-"));
    row.append($("<td>").text(formatDateTime24(token.created_at, { seconds: false })));
    row.append($("<td>").text(token.expires_at ? formatDateTime24(token.expires_at, { seconds: false }) : i18n.t("profile.tokens.never")));
    row.append($("<td>").text(token.last_used_at ? formatDateTime24(token.last_used_at, { seconds: false }) : i18n.t("profile.tokens.never")));
    row.append(
        $("<td>").append(
            $("<span>")
                .addClass("badge")
                .addClass(token.active && !token.expired ? "badge-success" : "badge-muted")
                .text(token.expired ? i18n.t("profile.tokens.expired") : (token.active ? i18n.t("profile.tokens.active") : i18n.t("profile.tokens.revoked")))
        )
    );

    const actions = $("<div>").addClass("table-actions");
    if (token.active && !token.expired) {
        actions.append(
            $("<button>")
                .attr("type", "button")
                .addClass("btn btn-danger btn-small")
                .text(i18n.t("profile.tokens.revoke"))
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
    showAppConfirm({
        title: i18n.t("profile.tokens.revoke_title"),
        message: i18n.t("profile.tokens.revoke_message", {name: token.name || token.id}),
        confirmText: i18n.t("profile.tokens.revoke"),
        confirmClass: "btn-danger",
    }).done(function () {
        apiDelete("/api/profile/tokens/" + token.id, function () {
            loadProfileTokens();
        });
    });
}

function resetProfileTokenModal() {
    /*
     * Reset token generation modal output.
     */
    lastGeneratedProfileToken = "";
    $("#profile-token-result").text(i18n.t("profile.tokens.none_generated"));
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
    const scopes = getProfileTokenScopeValues();

    if (days < 0) {
        setProfileInlineStatus("#profile-token-status", i18n.t("profile.tokens.days_negative"), true);
        return;
    }

    apiPost(
        "/api/profile/tokens",
        {
            name: name,
            group_id: groupId ? Number(groupId) : null,
            scopes: scopes.length ? scopes : ["alerts:read"],
            days: days,
        },
        function (data) {
            lastGeneratedProfileToken = data.token || "";
            $("#profile-token-result").text(lastGeneratedProfileToken || JSON.stringify(data, null, 2));
            $("#copy-profile-token").toggleClass("is-hidden", !lastGeneratedProfileToken);
            setProfileInlineStatus("#profile-token-status", i18n.t("profile.tokens.generated_status"), false);
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
        setProfileInlineStatus("#profile-token-status", i18n.t("profile.tokens.copied"), false);
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
            i18n.t("profile.password.required"),
            true
        );
        return;
    }

    apiPost(
        "/api/profile/change-password",
        {
            old_password: oldPassword,
            new_password: newPassword,
        },
        function () {
            $("#profile-old-password").val("");
            $("#profile-new-password").val("");
            setProfileInlineStatus("#profile-password-modal-status", i18n.t("profile.password.changed"), false);
            setProfileInlineStatus("#profile-password-status", i18n.t("profile.password.changed"), false);
            closeAppModal("#profile-password-modal");
        }
    );
}

function saveActiveGroup() {
    /*
     * Set the active group from the profile page.
     */
    const groupId = $("#profile-active-group").val();
    setProfileStatus("#profile-active-group-status", i18n.t("profile.access.updating"), false);

    apiPost(
        "/api/profile/active-group",
        {
            group_id: groupId ? Number(groupId) : null,
        },
        function (user) {
            currentUser = user;
            updateAuthUi();
            renderProfileHeader(user);
            fillTeamSelect("#global-team-filter", true, function () {
                navigate(window.location.pathname, false);
            });
            setProfileStatus("#profile-active-group-status", i18n.t("profile.access.updated"), false);
        }
    );
}

$(document).on("click", "#open-profile-token-modal", function () {
    resetProfileTokenModal();
    setProfileTokenScopeValues(["alerts:read"]);
    openAppModal("#profile-token-modal");
});
$(document).on("click", "#close-profile-token-modal, #close-profile-token-modal-footer", function () {
    closeAppModal("#profile-token-modal");
});
$(document).on("click", "#open-profile-password-modal", function () {
    setProfileInlineStatus("#profile-password-modal-status", "", false);
    $("#profile-old-password").val("");
    $("#profile-new-password").val("");
    openAppModal("#profile-password-modal");
});
$(document).on("click", "#close-profile-password-modal, #close-profile-password-modal-footer", function () {
    closeAppModal("#profile-password-modal");
});
$(document).on("click", "#profile-token-modal, #profile-password-modal", function (event) {
    if (event.target === this || $(event.target).hasClass("app-modal")) {
        closeAppModal("#" + $(this).attr("id"));
    }
});
$(document).on("keydown", function (event) {
    if (event.key !== "Escape") {
        return;
    }
    if ($("#profile-token-modal").hasClass("is-open")) {
        closeAppModal("#profile-token-modal");
    }
    if ($("#profile-password-modal").hasClass("is-open")) {
        closeAppModal("#profile-password-modal");
    }
});

$(document).on("click", "#create-profile-token", createProfileToken);
$(document).on("click", "#copy-profile-token", copyProfileToken);
$(document).on("click", "#change-profile-password", changeProfilePassword);
$(document).on("click", "#save-profile", saveProfile);
$(document).on("click", "#save-profile-top", saveProfile);
$(document).on("click", "#save-active-group", saveActiveGroup);
$(document).on(
    "change",
    "#profile-notify-shift-start-email, #profile-notify-shift-end-email, #profile-notify-shift-start-mattermost",
    saveProfileShiftNotificationPreferences
);

loadProfileTokens();
function profileOncallDisplayName(name, slug, fallback) {
    return name || slug || fallback || "-";
}


function renderProfileOncallSlot(slot) {
    const item = $("<div>").addClass("profile-oncall-slot");

    const sourceTimezone = slot.timezone || "UTC";
    const displayTimezone = window.AppTimezones
        ? AppTimezones.getDisplayTimezone(currentUser)
        : sourceTimezone;

    const title = $("<div>")
        .addClass("profile-oncall-slot-title")
        .text(profileOncallDisplayName(
            slot.team_name,
            slot.team_slug,
            i18n.t("profile.oncall.team")
        ));

    const meta = [
        slot.rotation_name || i18n.t("profile.oncall.rotation", {id: slot.rotation_id}),
        slot.layer_name || (
            slot.type === "override"
                ? i18n.t("profile.oncall.override")
                : i18n.t("profile.oncall.layer")
        ),
        i18n.t("profile.oncall.shown_in", {timezone: displayTimezone}),
        sourceTimezone !== displayTimezone
            ? i18n.t("profile.oncall.source", {timezone: sourceTimezone})
            : null,
    ].filter(Boolean).join(" · ");

    item.append(title);

    item.append(
        $("<div>")
            .addClass("profile-oncall-slot-meta")
            .text(meta)
    );

    item.append(
        $("<div>")
            .addClass("profile-oncall-slot-time")
            .text(
                formatShortDateTimeMinutesInTimezone(
                    slot.start,
                    displayTimezone
                ) +
                " → " +
                formatShortDateTimeMinutesInTimezone(
                    slot.end,
                    displayTimezone
                )
            )
    );

    if (slot.type === "override" && slot.reason) {
        item.append(
            $("<div>")
                .addClass("profile-oncall-slot-reason")
                .text(slot.reason)
        );
    }

    return item;
}

function renderProfileOncallStatus(data) {
    const current = asArray(data.current);
    const next = asArray(data.next);

    const status = $("#profile-oncall-status");
    const currentList = $("#profile-oncall-current");
    const nextList = $("#profile-oncall-next");

    currentList.empty();
    nextList.empty();

    if (data.is_oncall) {
        status
            .removeClass("profile-oncall-status-idle")
            .addClass("profile-oncall-status-active")
            .text(i18n.t("profile.oncall.now"));

        current.forEach(function (slot) {
            currentList.append(renderProfileOncallSlot(slot));
        });
    } else {
        status
            .removeClass("profile-oncall-status-active")
            .addClass("profile-oncall-status-idle")
            .text(i18n.t("profile.oncall.not_now"));
    }

    if (!next.length) {
        nextList.append(
            $("<div>")
                .addClass("profile-oncall-empty")
                .text(i18n.t("profile.oncall.no_upcoming", {days: data.lookahead_days || 30}))
        );
        return;
    }

    next.forEach(function (slot) {
        nextList.append(renderProfileOncallSlot(slot));
    });
}

function loadProfileOncallStatus() {
    $("#profile-oncall-status").text(i18n.t("profile.oncall.loading"));

    apiGet("/api/profile/oncall?days=30", function (data) {
        renderProfileOncallStatus(data || {});
    });
}
$(document).on("click", "#refresh-profile-oncall", loadProfileOncallStatus);

loadProfileOncallStatus();
function switchProfileTab(tabName) {
    const normalized = tabName || "details";

    $("[data-profile-tab]")
        .removeClass("is-active")
        .filter("[data-profile-tab='" + normalized + "']")
        .addClass("is-active");

    $(".profile-tab-panel").hide();
    $("#profile-tab-" + normalized).show();

    if (normalized === "oncall") {
        loadOncallStatusPanel("#profile-oncall-panel", {
            days: 30,
            endpoint: "/api/profile/oncall"
        });
    }
}

$(document).on("click", "[data-profile-tab]", function () {
    switchProfileTab($(this).data("profile-tab"));
});

switchProfileTab("details");
function getProfileCaldavUrl() {
    return window.location.origin + "/caldav/";
}

function renderProfileCaldav(profile) {
    const username = profile.email || profile.username || "";

    $("#profile-caldav-url").val(getProfileCaldavUrl());
    $("#profile-caldav-username").val(username);
}

function copyProfileField(selector, statusSelector, successMessage) {
    const value = $(selector).val() || "";

    if (!value) {
        setProfileInlineStatus(statusSelector, i18n.t("profile.copy.nothing"), true);
        return;
    }

    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(value).then(function () {
            setProfileInlineStatus(statusSelector, successMessage, false);
        });
        return;
    }

    const field = $(selector);
    field.trigger("select");
    document.execCommand("copy");
    setProfileInlineStatus(statusSelector, successMessage, false);
}

function openCreateCaldavTokenModal() {
    resetProfileTokenModal();

    $("#profile-token-name").val("caldav-calendar");
    $("#profile-token-days").val("");
    $("#profile-token-group").val("");

    setProfileTokenScopeValues(["calendar:read"]);

    if (getProfileTokenScopeValues().indexOf("calendar:read") === -1) {
        setProfileInlineStatus(
            "#profile-caldav-status",
            i18n.t("profile.caldav.scope_missing"),
            true
        );
        return;
    }

    setProfileInlineStatus(
        "#profile-token-status",
        i18n.t("profile.caldav.token_info"),
        false
    );

    openAppModal("#profile-token-modal");
}
$(document).on("click", "#copy-profile-caldav-url", function () {
    copyProfileField(
        "#profile-caldav-url",
        "#profile-caldav-status",
        i18n.t("profile.caldav.url_copied")
    );
});

$(document).on("click", "#copy-profile-caldav-username", function () {
    copyProfileField(
        "#profile-caldav-username",
        "#profile-caldav-status",
        i18n.t("profile.caldav.username_copied")
    );
});

$(document).on("click", "#create-profile-caldav-token", openCreateCaldavTokenModal);
