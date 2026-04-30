let currentUser = null;

const routes = {
    "/": { page: "dashboard", title: "Overview", subtitle: "Real-time summary of active incidents, acknowledgements, reminders and affected teams", load: function () { loadDashboard(); } },
    "/alerts": { page: "alerts", title: "Alerts", subtitle: "Search, inspect, acknowledge and resolve routed incidents from one workspace", load: function () { loadAlerts(); } },
    "/rotations": { page: "rotations", title: "Rotations", subtitle: "Manage on-call rotations", load: function () { loadRotations(); } },
    "/calendar": { page: "calendar", title: "Calendar", subtitle: "On-call calendar by team", load: function () { loadCalendar(); } },
    "/routes": { page: "routes", title: "Routes", subtitle: "Connect alert sources, rotations and channels", load: function () { loadRoutes(); } },
    "/channels": { page: "channels", title: "Channels", subtitle: "Notification channels", load: function () { loadChannels(); } },
    "/silences": { page: "silences", title: "Silences", subtitle: "Mute alerts by matchers", load: function () { loadSilences(); } },
    "/teams": { page: "teams", title: "Teams", subtitle: "Independent duty teams", load: function () { loadTeams(); } },
    "/groups": { page: "groups", title: "Groups", subtitle: "Access boundaries and user roles", load: function () { loadGroups(); } },
    "/profile": { page: "profile", title: "Profile", subtitle: "User profile and personal API token", load: function () { loadProfile(); } },
    "/admin/users": { page: "admin-users", title: "Admin users", subtitle: "Admin-only user workspace", load: function () { loadAdminUsers(); } },
    "/login": { page: "login", title: "Login", subtitle: "JWT authentication", load: function () { loadLogin(); } }
};

function authHeaders() {
    /* Return Authorization header when a JWT is stored. */
    const token = localStorage.getItem("oncall_jwt");

    if (!token) {
        return {};
    }

    return { "Authorization": "Bearer " + token };
}

function formatApiError(xhr) {
    /* Build a readable API error message. */

    const response = xhr.responseJSON;

    if (!response) {
        return xhr.responseText || "Unknown API error";
    }

    let message = response.message || response.error || "API error";

    if (Array.isArray(response.details) && response.details.length) {
        const details = response.details.map(function (item) {
            const field = item.field || (item.loc ? item.loc.join(".") : "field");
            const text = item.message || item.msg || "Invalid value";

            if (field) {
                return field + ": " + text;
            }

            return text;
        });

        message += "\n\n" + details.join("\n");
    }

    if (response.error_id) {
        message += "\n\nError ID: " + response.error_id;
    }

    return message;
}


function apiRequest(method, url, data, callback) {
    /* Send JSON API request. */

    const token = localStorage.getItem("oncall_jwt");

    $.ajax({
        method: method,
        url: url,
        contentType: "application/json",
        data: data ? JSON.stringify(data) : null,
        headers: token ? {"Authorization": "Bearer " + token} : {},
        success: function (response) {
            if (typeof callback === "function") {
                callback(response);
            }
        },
        error: function (xhr) {
            alert(formatApiError(xhr));
        }
    });
}

function apiGet(url, callback) { apiRequest("GET", url, null, callback); }
function apiPost(url, data, callback) { apiRequest("POST", url, data, callback); }
function apiPut(url, data, callback) { apiRequest("PUT", url, data, callback); }
function apiDelete(url, callback) { apiRequest("DELETE", url, null, callback); }

function asArray(value) {
    /* Return value when it is an array, otherwise return an empty array. */
    return Array.isArray(value) ? value : [];
}

function safePageLoad(loadFunction) {
    /* Prevent one page error from hiding the whole view. */
    try {
        loadFunction();
    } catch (error) {
        console.error("Page load failed:", error);
        alert("Page load failed: " + error);
    }
}

function parseJsonInput(selector, fallback) {
    /* Parse JSON from an input field. */
    const raw = $(selector).val();
    if (!raw) { return fallback; }
    try { return JSON.parse(raw); } catch (error) { alert("Invalid JSON in " + selector + ": " + error); throw error; }
}

function selectedTeamId() { return $("#global-team-filter").val(); }
function selectedTeamQuery() { const teamId = selectedTeamId(); return teamId ? "?team_id=" + encodeURIComponent(teamId) : ""; }

function fillGroupSelect(selector, includeAll, callback) {
    /* Fill a select element with groups ordered by id. */
    apiGet("/api/groups", function (groups) {
        const select = $(selector); select.empty();
        if (includeAll) { select.append($("<option>").val("").text("All groups")); }
        groups = asArray(groups);
        groups.forEach(function (group) { select.append($("<option>").val(group.id).text("#" + group.id + " " + group.name + " (" + group.slug + ")")); });
        if (typeof callback === "function") { callback(groups); }
    });
}

function fillTeamSelect(selector, includeAll, callback) {
    /* Fill a select element with teams ordered by id. */
    apiGet("/api/teams", function (teams) {
        const select = $(selector); select.empty();
        if (includeAll) { select.append($("<option>").val("").text("All teams")); }
        teams = asArray(teams);
        teams.forEach(function (team) { select.append($("<option>").val(team.id).text("#" + team.id + " " + team.name + " (" + team.slug + ")")); });
        if (typeof callback === "function") { callback(teams); }
    });
}

function fillUserSelect(selector, callback, url) {
    /* Fill a select element with users ordered by id. */
    apiGet(url || "/api/users", function (users) {
        const select = $(selector); select.empty();
        users = asArray(users);
        users.forEach(function (user) { select.append($("<option>").val(user.id).text("#" + user.id + " " + user.username)); });
        if (typeof callback === "function") { callback(users); }
    });
}

function fillActiveGroupSelect() {
    /* Fill the active group selector in the topbar. */
    const select = $("#active-group-select");
    select.empty();
    select.append($("<option>").val("").text("All my groups"));

    if (!currentUser || !currentUser.groups) {
        return;
    }

    currentUser.groups.forEach(function (membership) {
        select.append(
            $("<option>")
                .val(membership.group_id)
                .text(membership.group_name + " (" + membership.role + ")")
        );
    });

    if (currentUser.active_group_id) {
        select.val(String(currentUser.active_group_id));
    }
}

function updateAuthUi() {
    /* Update menu items that depend on authentication and role. */
    if (!currentUser || !currentUser.is_admin) {
        $(".menu-link-admin").addClass("is-hidden");
    } else {
        $(".menu-link-admin").removeClass("is-hidden");
    }

    if (currentUser) {
        $("#topbar-username").text(currentUser.display_name || currentUser.username);
        fillActiveGroupSelect();
    }
}

function navigate(path, pushState) {
    /* Navigate to an application page. */
    if ((path === "/admin/users" || path === "/groups") && (!currentUser || !currentUser.is_admin)) {
        alert("Admin permission is required.");
        path = "/";
    }

    const selectedRoute = routes[path] || routes["/"];

    $(".view").removeClass("view-visible").css("display", "none");
    $("#view-" + selectedRoute.page).addClass("view-visible").css("display", "block");

    $("#page-title").text(selectedRoute.title);
    $("#page-subtitle").text(selectedRoute.subtitle);
    $(".menu-link").removeClass("active");
    $('.menu-link[href="' + path + '"]').addClass("active");

    renderTopbarExtraActions(selectedRoute);
    if (pushState) {
        history.pushState({ path: path }, "", path);
    }

    safePageLoad(selectedRoute.load);
}

function loadVersion() {
    /* Load service version. */
    apiGet("/api/version", function (data) { $("#service-version").text("v" + data.service_version); });
}

function isoToDatetimeLocal(value) {
    /* Convert an ISO date string to datetime-local format. */
    if (!value) { return ""; }
    return value.slice(0, 16);
}

function startAuthenticatedApp() {
    /* Load user state and start the application. */
    apiGet("/api/auth/me", function (user) {
        currentUser = user;
        updateAuthUi();
        fillTeamSelect("#global-team-filter", true, function () { navigate(window.location.pathname, false); });
    });
}

$(document).ready(function () {
    /* Initialize frontend routing and global selectors. */
    loadVersion();

    if (window.location.pathname === "/login") {
        navigate("/login", false);
    } else {
        startAuthenticatedApp();
    }

    $(".menu-link[data-page]").on("click", function (event) { event.preventDefault(); navigate($(this).attr("href"), true); });

    $("#global-team-filter").on("change", function () { navigate(window.location.pathname, false); });

    $("#active-group-select").on("change", function () {
        const groupId = $(this).val();

        apiPost("/api/profile/active-group", { group_id: groupId ? Number(groupId) : null }, function (user) {
            currentUser = user;
            updateAuthUi();
            fillTeamSelect("#global-team-filter", true, function () { navigate(window.location.pathname, false); });
        });
    });

    $("#topbar-profile").on("click", function () { navigate("/profile", true); });

    $("#topbar-logout").on("click", function () {
        apiPost("/api/auth/logout", {}, function () {
            localStorage.removeItem("oncall_jwt");
            window.location.href = "/login";
        });
    });

    window.onpopstate = function () { navigate(window.location.pathname, false); };
});
function padDateTimePart(value) {
    /*
     * Return a date/time part as a two-digit string.
     *
     * Example:
     *   4  -> "04"
     *   12 -> "12"
     */
    return String(value).padStart(2, "0");
}

function formatDateTime24(value, options) {
    /*
     * Format an ISO datetime or Date object as European 24-hour datetime.
     *
     * Output:
     *   29.04.2026, 17:46:55
     *
     * By default seconds are included.
     * Pass { seconds: false } to hide seconds:
     *   29.04.2026, 17:46
     */
    if (!value) {
        return "-";
    }

    const date = value instanceof Date ? value : new Date(value);

    if (Number.isNaN(date.getTime())) {
        return value;
    }

    const datePart = [
        padDateTimePart(date.getDate()),
        padDateTimePart(date.getMonth() + 1),
        date.getFullYear()
    ].join(".");

    const timeParts = [
        padDateTimePart(date.getHours()),
        padDateTimePart(date.getMinutes())
    ];

    if (!options || options.seconds !== false) {
        timeParts.push(padDateTimePart(date.getSeconds()));
    }

    return datePart + ", " + timeParts.join(":");
}
function clearTopbarExtraActions() {
    /*
     * Clear page-specific controls from topbar.
     */
    $("#topbar-extra-actions").empty();
    $(".topbar").removeClass("topbar-alerts");

    if (typeof setAlertsAutoRefresh === "function") {
        setAlertsAutoRefresh(false);
    }
}


function renderAlertsTopbarActions() {
    /*
     * Render Alerts page controls in the shared topbar.
     * These controls are recreated on every navigation to /alerts.
     */
    $(".topbar").addClass("topbar-alerts");

    $("#topbar-extra-actions").html(`
        <div class="alerts-topbar-controls">
            <div class="alerts-topbar-search">
                <span class="alerts-search-icon">⌕</span>
                <input
                    id="alerts-search"
                    class="input"
                    type="search"
                    placeholder="Search alerts..."
                    autocomplete="off"
                >
            </div>

            <select id="status-filter" class="input alerts-topbar-select">
                <option value="">All statuses</option>
                <option value="firing">Firing</option>
                <option value="acknowledged">Acknowledged</option>
                <option value="resolved">Resolved</option>
                <option value="silenced">Silenced</option>
            </select>

            <select id="severity-filter" class="input alerts-topbar-select">
                <option value="">All severities</option>
                <option value="critical">Critical</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
            </select>

            <select id="alerts-sort" class="input alerts-topbar-select">
                <option value="activity_desc">Newest activity</option>
                <option value="created_desc">Newest created</option>
                <option value="created_asc">Oldest created</option>
                <option value="severity_desc">Severity first</option>
                <option value="status_asc">Status</option>
            </select>

            <label class="alerts-topbar-switch">
                <input id="alerts-auto-refresh" type="checkbox">
                <span>Auto</span>
            </label>

            <button id="reload-alerts" type="button" class="btn btn-primary btn-small">
                Reload
            </button>
        </div>
    `);
}


function renderTopbarExtraActions(route) {
    /*
     * Render page-specific actions in topbar.
     */
    clearTopbarExtraActions();

    if (route && route.page === "alerts") {
        renderAlertsTopbarActions();
    }
}

