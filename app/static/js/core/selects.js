const GLOBAL_TEAM_FILTER_STORAGE_KEY = "incidentrelay.global_team_filter";

function readStoredGlobalTeamId() {
    try {
        return localStorage.getItem(GLOBAL_TEAM_FILTER_STORAGE_KEY) || "";
    } catch (error) {
        return "";
    }
}

function writeStoredGlobalTeamId(teamId) {
    try {
        if (teamId) {
            localStorage.setItem(GLOBAL_TEAM_FILTER_STORAGE_KEY, String(teamId));
        } else {
            localStorage.removeItem(GLOBAL_TEAM_FILTER_STORAGE_KEY);
        }
    } catch (error) {
        // Ignore storage errors, the filter still works for the current page.
    }
}

function restoreGlobalTeamFilterValue() {
    const select = $("#global-team-filter");
    const storedTeamId = readStoredGlobalTeamId();

    if (!select.length) {
        return;
    }

    if (
        storedTeamId &&
        select.find("option").filter(function () {
            return String($(this).val()) === String(storedTeamId);
        }).length
    ) {
        select.val(storedTeamId);
        return;
    }

    select.val("");
    writeStoredGlobalTeamId("");
}

function selectedTeamId() { return $("#global-team-filter").val(); }
function selectedTeamQuery() { const teamId = selectedTeamId(); return teamId ? "?team_id=" + encodeURIComponent(teamId) : ""; }
function selectedTeamNumber() {
    const teamId = selectedTeamId();
    return teamId ? Number(teamId) : null;
}

function setSelectedTeamId(teamId, triggerChange) {
    const select = $("#global-team-filter");
    const value = teamId ? String(teamId) : "";

    if (!select.length) {
        return;
    }

    select.val(value);
    writeStoredGlobalTeamId(value);

    if (triggerChange) {
        select.trigger("change");
    }
}
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
        const select = $(selector);

        select.empty();

        if (includeAll) {
            select.append($("<option>").val("").text("All teams"));
        }

        teams = asArray(teams);

        teams.forEach(function (team) {
            select.append(
                $("<option>")
                    .val(team.id)
                    .text("#" + team.id + " " + team.name + " (" + team.slug + ")")
            );
        });

        if (select.attr("id") === "global-team-filter") {
            restoreGlobalTeamFilterValue();
        }

        if (typeof callback === "function") {
            callback(teams);
        }
    });
}

function fillUserSelect(selector, callback, url, options) {
    /*
     * Fill a select element with users ordered by id.
     * If select has .js-user-select and Tom Select is loaded,
     * it becomes searchable.
     */
    apiGet(url || "/api/users", function (users) {
        const selectElement = getSelectElement(selector);

        if (!selectElement) {
            if (typeof callback === "function") {
                callback([]);
            }
            return;
        }

        const wasDisabled = $(selectElement).prop("disabled");

        destroyTomSelectIfExists(selectElement);

        const select = $(selectElement);
        const isMultiple = selectElement.hasAttribute("multiple");

        select.empty();

        users = asArray(users);

        users.forEach(function (user) {
            const userId = getUserIdValue(user);

            if (!userId) {
                return;
            }

            select.append(
                $("<option>")
                    .val(String(userId))
                    .text(getUserOptionText(user))
            );
        });

        initUserTomSelectIfNeeded(selectElement, options);
        setEnhancedSelectDisabled(selectElement, wasDisabled);

        if (typeof callback === "function") {
            callback(users);
        }
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
function getSelectElement(selector) {
    if (!selector) {
        return null;
    }

    if (selector instanceof HTMLElement) {
        return selector;
    }

    if (selector.jquery) {
        return selector.get(0) || null;
    }

    return $(selector).get(0) || null;
}

function isTomSelectLoaded() {
    return typeof window.TomSelect !== "undefined";
}

function destroyTomSelectIfExists(selectElement) {
    if (selectElement && selectElement.tomselect) {
        selectElement.tomselect.destroy();
    }
}

function shouldUseTomSelect(selectElement) {
    return (
        selectElement &&
        selectElement.classList &&
        selectElement.classList.contains("js-user-select") &&
        isTomSelectLoaded()
    );
}

function getUserIdValue(user) {
    return user.user_id || user.id;
}

function getUserOptionText(user) {
    const userId = getUserIdValue(user);

    const primary =
        user.display_name ||
        user.full_name ||
        user.name ||
        user.username ||
        user.email ||
        ("User #" + userId);

    const secondary = [];

    if (user.username && user.username !== primary) {
        secondary.push(user.username);
    }

    if (user.email && user.email !== primary) {
        secondary.push(user.email);
    }

    return "#" + userId + " " + primary + (
        secondary.length ? " (" + secondary.join(", ") + ")" : ""
    );
}

function initUserTomSelectIfNeeded(selectElement, options) {
    selectElement = getSelectElement(selectElement);

    if (!shouldUseTomSelect(selectElement)) {
        return null;
    }

    if (selectElement.tomselect) {
        return selectElement.tomselect;
    }

    const isMultiple = selectElement.hasAttribute("multiple");

    return new TomSelect(selectElement, Object.assign({
        create: false,
        persist: false,
        allowEmptyOption: true,
        maxOptions: 300,
        placeholder: selectElement.dataset.placeholder || "Select user...",
        searchField: ["text"],
        sortField: {
            field: "text",
            direction: "asc"
        },
        plugins: isMultiple ? ["remove_button"] : ["clear_button"],
        render: {
            no_results: function () {
                return '<div class="no-results">No users found</div>';
            }
        }
    }, options || {}));
}

function initUserTomSelects(root, options) {
    const container = root ? $(root) : $(document);

    container.find("select.js-user-select").each(function () {
        initUserTomSelectIfNeeded(this, options);
    });
}

function setSelectValue(selector, value) {
    const selectElement = getSelectElement(selector);

    if (!selectElement) {
        return;
    }

    const normalizedValue =
        value === undefined || value === null ? "" : String(value);

    if (selectElement.tomselect) {
        selectElement.tomselect.setValue(normalizedValue, true);
        return;
    }

    $(selectElement).val(normalizedValue);
}

function setEnhancedSelectDisabled(selector, disabled) {
    const selectElement = getSelectElement(selector);

    if (!selectElement) {
        return;
    }

    $(selectElement).prop("disabled", !!disabled);

    if (!selectElement.tomselect) {
        return;
    }

    if (disabled) {
        selectElement.tomselect.disable();
    } else {
        selectElement.tomselect.enable();
    }
}
