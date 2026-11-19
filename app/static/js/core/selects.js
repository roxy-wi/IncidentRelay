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

function readGlobalTeamIdFromUrl() {
    const params = new URLSearchParams(window.location.search || "");
    const routePath = typeof normalizeAppRoutePath === "function"
        ? normalizeAppRoutePath(window.location.pathname || "/")
        : (window.location.pathname || "/");

    if (routePath === "/calendar") {
        return params.get("team_id") || "";
    }

    return params.get("team") || "";
}

function restoreGlobalTeamFilterValue() {
    const select = $("#global-team-filter");
    const urlTeamId = readGlobalTeamIdFromUrl();
    const storedTeamId = readStoredGlobalTeamId();
    const preferredTeamId = urlTeamId || storedTeamId;

    if (!select.length) {
        return;
    }

    if (
        preferredTeamId &&
        select.find("option").filter(function () {
            return String($(this).val()) === String(preferredTeamId);
        }).length
    ) {
        setSelectValue(select, preferredTeamId);
        writeStoredGlobalTeamId(preferredTeamId);
        return;
    }

    setSelectValue(select, "");
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

    setSelectValue(select, value);
    writeStoredGlobalTeamId(value);

    if (triggerChange) {
        select.trigger("change");
    }
}
function fillGroupSelect(selector, includeAll, callback) {
    /* Fill a select element with groups ordered by id. */
    apiGet("/api/groups", function (groups) {
        const select = $(selector); select.empty();
        if (includeAll) { select.append($("<option>").val("").text(i18n.t("shared.select.all_groups"))); }
        groups = asArray(groups);
        groups.forEach(function (group) { select.append($("<option>").val(group.id).text("#" + group.id + " " + group.name + " (" + group.slug + ")")); });
        if (typeof callback === "function") { callback(groups); }
    });
}

function loadUiTeams(callback) {
    const user = currentUser;
    const groupId = getCurrentUserActiveGroupId();
    apiGet("/api/teams", function (teams) {
        teams = asArray(teams);
        if (setCurrentUserUiTeams(teams, user, groupId)) {
            callback(teams);
        }
    }, function (xhr) {
        if (setCurrentUserUiTeams([], user, groupId)) {
            callback([]);
            showApiError(xhr);
        }
    });
}

function selectPreferredTeam(selector) {
    // A read-only team selected in the global filter may be absent here.
    const select = $(selector);
    const preferred = String(selectedTeamId() || "");
    const available = select.find("option").filter(function () {
        return String($(this).val()) === preferred;
    });
    if (preferred && available.length) {
        select.val(preferred);
    } else if (!select.val()) {
        select.val(select.find("option").first().val() || "");
    }
}

function fillTeamSelect(selector, includeAll, callback, permission) {
    /* Fill a select element with teams ordered by id. */
    loadUiTeams(function (teams) {
        const select = $(selector);

        destroyTomSelectIfExists(select[0]);
        select.empty();

        if (includeAll) {
            select.append($("<option>").val("").text(i18n.t("shared.select.all_teams")));
        }

        if (permission) {
            teams = teams.filter(function (team) {
                return canCreateTeamObject(team, permission);
            });
        }

        teams.forEach(function (team) {
            select.append(
                $("<option>")
                    .val(team.id)
                    .text("#" + team.id + " " + team.name + " (" + team.slug + ")")
            );
        });

        if (select.attr("id") === "global-team-filter") {
            restoreGlobalTeamFilterValue();
            initSearchableSelect(select, {wrapperClass: "ts-wrapper searchable-select global-team-select"});
        } else if (permission) {
            selectPreferredTeam(selector);
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
                    .attr("data-color", UserAppearance.color(user))
                    .attr("data-display_name", UserAppearance.name(user))
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
    select.append($("<option>").val("").text(i18n.t("shared.select.all_my_groups")));

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
        // Tom Select rewrites labels but does not restore them on destroy.
        const controlId = selectElement.tomselect.control_input.id;
        document.querySelectorAll("label").forEach(function (label) {
            if (label.htmlFor === controlId) label.htmlFor = selectElement.id;
        });
        selectElement.tomselect.destroy();
    }
}

function destroyTomSelects(root) {
    $(root).find("select").each(function () { destroyTomSelectIfExists(this); });
}

function initSearchableSelect(selector, options) {
    const element = getSelectElement(selector);
    if (!element || !isTomSelectLoaded()) return null;
    if (element.tomselect) return element.tomselect;

    const modal = element.closest(".app-modal, .modal");
    const picker = new TomSelect(element, Object.assign({
        wrapperClass: "ts-wrapper searchable-select",
        dropdownClass: "ts-dropdown searchable-select-dropdown",
        dropdownParent: modal,
        copyClassesToDropdown: false,
        create: false,
        allowEmptyOption: true,
        maxOptions: 300,
        searchField: ["text"],
        placeholder: i18n.t("shared.select.search_placeholder"),
        render: {
            no_results: function (data, escape) {
                return '<div class="no-results">' + escape(i18n.t("shared.select.no_results")) + '</div>';
            }
        }
    }, options || {}));
    // Keep form-field classes on the select: delegated change handlers and
    // value readers must never match the generated wrapper or dropdown.
    picker.wrapper.classList.remove(...element.classList);
    if (modal && picker.dropdown.parentElement === modal) {
        positionSearchableSelectInModal(picker, modal);
    }
    return picker;
}

function positionSearchableSelectInModal(picker, modal) {
    // Keep the menu in the modal's stacking context, outside clipped cards and
    // the scrolling dialog body. Its options scroll within the available space.
    picker.dropdown.classList.add("searchable-select-modal-dropdown");
    picker.positionDropdown = function () {
        const control = picker.control.getBoundingClientRect();
        const parent = modal.getBoundingClientRect();
        const gap = 6;
        const edge = 8;
        const above = Math.max(0, control.top - Math.max(parent.top, 0) - edge - gap);
        const below = Math.max(0, Math.min(parent.bottom, window.innerHeight) - control.bottom - edge - gap);
        const desired = Math.min(200, picker.dropdown_content.scrollHeight);
        const openAbove = below < desired + 2 && above > below;
        picker.dropdown_content.style.maxHeight = Math.max(0, Math.min(200, (openAbove ? above : below) - 2)) + "px";
        const width = Math.min(control.width, parent.width - edge * 2);
        const left = Math.max(parent.left + edge, Math.min(control.left, parent.right - edge - width));
        picker.dropdown.style.width = width + "px";
        picker.dropdown.style.left = (left - parent.left) + "px";
        picker.dropdown.style.top = (openAbove
            ? control.top - parent.top - gap - picker.dropdown.offsetHeight
            : control.bottom - parent.top + gap) + "px";
    };
    function onScroll(event) {
        // Scrolling the option list must not dismiss it. Scrolling the form
        // closes the menu so it cannot float over an unrelated field.
        if (!picker.dropdown.contains(event.target)) picker.close();
    }
    function stopTracking() {
        modal.removeEventListener("scroll", onScroll, true);
    }
    picker.on("dropdown_open", function () { modal.addEventListener("scroll", onScroll, true); });
    picker.on("dropdown_close", stopTracking);
    picker.on("destroy", stopTracking);
    picker.on("type", function () { if (picker.isOpen) picker.positionDropdown(); });
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
        i18n.t("shared.select.user", {id: userId});

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
        placeholder: selectElement.dataset.placeholder || i18n.t("shared.select.user_placeholder"),
        searchField: ["text"],
        sortField: {
            field: "text",
            direction: "asc"
        },
        plugins: isMultiple ? ["remove_button"] : ["clear_button"],
        render: {
            option: function (data) {
                return UserAppearance.option(data);
            },
            item: function (data) {
                return UserAppearance.option(data);
            },
            no_results: function () {
                return '<div class="no-results">' + i18n.t("shared.select.no_users") + '</div>';
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
