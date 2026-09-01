function normalizeAppRoutePath(pathname) {
    /*
     * Convert detail URLs to their SPA route.
     * Example: /alerts/123 -> /alerts
     */
    if (/^\/alerts\/\d+\/?$/.test(pathname || "")) {
        return "/alerts";
    }
    return pathname || "/";
}

function splitAppPath(path) {
    /*
     * Split an internal app URL into route path and full path.
     *
     * Example:
     * /alerts?status=firing -> routePath=/alerts, fullPath=/alerts?status=firing
     * /alerts/123 -> routePath=/alerts, fullPath=/alerts/123
     */
    const url = new URL(path || "/", window.location.origin);
    return {
        routePath: normalizeAppRoutePath(url.pathname),
        fullPath: url.pathname + url.search + url.hash,
    };
}

function navigate(path, pushState) {
    /*
     * Navigate to an application page.
     *
     * Query string is preserved for page filters, but route lookup uses only
     * pathname because routes are registered as /alerts, /routes, etc.
     */
    let appPath = splitAppPath(path);
    let routePath = appPath.routePath;

    if (routePath === "/admin/sso" && (!currentUser || !currentUser.is_admin)) {
        showAppError(i18n.t("errors.admin_role_required"));
        path = "/";
    }
    if (routePath === "/admin/audit-log" && !hasAuditLogAccess()) {
        showAppError(i18n.t("audit.errors.access_denied"));
        path = "/";
    }
    if (routePath === "/admin/users" && !hasGroupUserAdminAccess()) {
        showAppError(i18n.t("errors.group_admin_role_required"));
        path = "/";
    }
    if (routePath === "/groups" && !hasGroupUserAdminAccess()) {
        showAppError(i18n.t("errors.group_admin_role_required"));
        path = "/";
    }

    const normalizedPath = splitAppPath(path);
    const selectedRoute = routes[normalizedPath.routePath] || routes["/"];

    $(".view").removeClass("view-visible").css("display", "none");
    $("#view-" + selectedRoute.page).addClass("view-visible").css("display", "block");
    const pageTranslationKey = "pages." + selectedRoute.page;
    $("#page-title").text(
      i18n.t(pageTranslationKey + ".title", {}, selectedRoute.title)
    );
    $("#page-subtitle").text(
      i18n.t(pageTranslationKey + ".subtitle", {}, selectedRoute.subtitle)
    );

    $(".menu-link").removeClass("active");
    $(".menu-group").removeClass("is-active");

    const activeMenuLink = $(
        '.menu-link[href="' + normalizedPath.routePath + '"]'
    );

    activeMenuLink.addClass("active");

    const activeMenuGroup = activeMenuLink.closest(".menu-group");

    if (activeMenuGroup.length) {
        activeMenuGroup.addClass("is-active is-expanded");
        activeMenuGroup
            .children(".menu-group-toggle")
            .attr("aria-expanded", "true");
    }

    if (pushState) {
        history.pushState({path: normalizedPath.fullPath}, "", normalizedPath.fullPath);
    }

    if (window.PageUrlState && typeof window.PageUrlState.restorePath === "function") {
        window.PageUrlState.restorePath(normalizedPath.routePath);
    }

    safePageLoad(selectedRoute.load);
    applyRbacUiState();
}

function safePageLoad(loadFunction) {
    /*
     * Prevent one page error from hiding the whole view.
     */
    try {
        loadFunction();
    } catch (error) {
        console.error("Page load failed:", error);
        showAppError(
      i18n.t(
        "errors.page_load_failed",
        {error: error},
        "Page load failed: {error}"
      )
    );
    }
}

function updateAuthUi() {
    /*
     * Update role-dependent menu visibility.
     */
    const isGlobalAdmin = !!(currentUser && currentUser.is_admin);
    const canManageUsers = hasGroupUserAdminAccess();
    const canViewAuditLog = hasAuditLogAccess();
    const adminSection = $(".menu-section-admin, .menu-link-admin");

    adminSection.addClass("is-hidden");
    $(".menu-link-users").addClass("is-hidden");
    $(".menu-link-groups").addClass("is-hidden");
    $(".menu-link-global-admin").addClass("is-hidden");
    $(".menu-link-audit").addClass("is-hidden");

    if (canViewAuditLog) {
        adminSection.removeClass("is-hidden");
        $(".menu-link-audit").removeClass("is-hidden");
    }

    if (canManageUsers) {
        adminSection.removeClass("is-hidden");
        $(".menu-link-users").removeClass("is-hidden");
        $(".menu-link-groups").removeClass("is-hidden");
    }

    if (isGlobalAdmin) {
        adminSection.removeClass("is-hidden");
        $(".menu-link-users").removeClass("is-hidden");
        $(".menu-link-groups").removeClass("is-hidden");
        $(".menu-link-global-admin").removeClass("is-hidden");
        $(".menu-link-audit").removeClass("is-hidden");
    }

    if (currentUser) {
        $("#topbar-username").text(currentUser.display_name || currentUser.username);
        fillActiveGroupSelect();
    }

    applyRbacUiState();
}

const TEAM_SCOPED_ROUTE_PATHS = {
    "/": true,
    "/alerts": true,
    "/rotations": true,
    "/calendar": true,
    "/routes": true,
    "/services": true,
    "/business-services": true,
    "/heartbeats": true,
    "/escalation-policies": true,
    "/notification-policies": true,
    "/matcher-presets": true,
    "/priority-policies": true,
    "/channels": true,
    "/silences": true,
    "/teams": true,
};

function appUrlWithGlobalTeamScope(path, options) {
    const settings = $.extend({teamChanged: false}, options || {});
    const url = new URL(path || currentAppUrl(), window.location.origin);
    const routePath = normalizeAppRoutePath(url.pathname);
    const teamId = typeof selectedTeamId === "function" ? selectedTeamId() : "";

    url.searchParams.delete("team");

    if (routePath === "/calendar") {
        url.searchParams.delete("team_id");
        if (teamId) {
            url.searchParams.set("team_id", String(teamId));
        }
        if (settings.teamChanged) {
            url.searchParams.delete("rotation_id");
        }
    } else if (TEAM_SCOPED_ROUTE_PATHS[routePath] && teamId) {
        url.searchParams.set("team", String(teamId));
    }

    return url.pathname + url.search + url.hash;
}

function startAuthenticatedApp() {
    apiGet("/api/auth/me", function (user) {
        currentUser = user;
        updateAuthUi();

        if (typeof startTopbarOncallStatusRefresh === "function") {
            startTopbarOncallStatusRefresh();
        }

        fillTeamSelect("#global-team-filter", true, function () {
            const scopedUrl = appUrlWithGlobalTeamScope(currentAppUrl());
            const currentUrl = currentAppUrl();

            if (scopedUrl !== currentUrl && window.history && window.history.replaceState) {
                window.history.replaceState({path: scopedUrl}, "", scopedUrl);
            }

            navigate(scopedUrl, false);
        });
    });
}

$(document).ready(function () {
    /*
     * Initialize frontend routing and global selectors.
     */
    if (typeof installRbacUiPatches === "function") {
        installRbacUiPatches();
    }

    loadVersion();

    if (window.location.pathname === "/login") {
        navigate("/login", false);
    } else {
        startAuthenticatedApp();
    }

    $(".menu-link[data-page]").on("click", function (event) {
        event.preventDefault();
        navigate(appUrlWithGlobalTeamScope($(this).attr("href")), true);
    });

    $("#global-team-filter").on("change", function () {
        writeStoredGlobalTeamId($(this).val());
        navigate(appUrlWithGlobalTeamScope(currentAppUrl(), {teamChanged: true}), true);
        applyRbacUiState();
    });

    $("#active-group-select").on("change", function () {
        const groupId = $(this).val();

        apiPost(
            "/api/profile/active-group",
            {group_id: groupId ? Number(groupId) : null},
            function (user) {
                currentUser = user;
                updateAuthUi();

                if (typeof loadTopbarOncallStatus === "function") {
                    loadTopbarOncallStatus();
                }

                fillTeamSelect("#global-team-filter", true, function () {
                    const scopedUrl = appUrlWithGlobalTeamScope(currentAppUrl());
                    if (scopedUrl !== currentAppUrl() && window.history && window.history.replaceState) {
                        window.history.replaceState({path: scopedUrl}, "", scopedUrl);
                    }
                    navigate(scopedUrl, false);
                });
            }
        );
    });

    $("#topbar-profile").on("click", function () {
        navigate("/profile", true);
    });

    $("#topbar-logout").on("click", function () {
        logout();
    });

    window.onpopstate = function () {
        navigate(currentAppUrl(), false);
    };
});

function currentAppUrl() {
    /*
     * Return current SPA URL with query string and hash.
     */
    return window.location.pathname + window.location.search + window.location.hash;
}

function hasAuditLogAccess() {
    /*
     * Audit logs are visible to global admins and group editors only.
     */
    if (!currentUser) {
        return false;
    }
    if (currentUser.is_admin) {
        return true;
    }
    return asArray(currentUser.groups).some(function (group) {
        return group.role === GROUP_EDITOR_ROLE || group.role === "editor";
    });
}


function hasGroupUserAdminAccess() {
    /*
     * Return true when the current user can manage users in at least one group.
     */
    if (!currentUser) {
        return false;
    }
    if (currentUser.is_admin) {
        return true;
    }
    return asArray(currentUser.groups).some(function (group) {
        return group.role === GROUP_USER_ADMIN_ROLE || group.role === "user_admin";
    });
}
