let calendarTeamsCache = [];
let calendarEventsCache = [];
let calendarSelectedTeamId = null;
let calendarMode = "week";

const calendarUserColors = [
    "#1f77b4",
    "#6f42c1",
    "#198754",
    "#fd7e14",
    "#dc3545",
    "#0dcaf0",
    "#795548",
    "#20c997",
    "#6610f2",
    "#6c757d",
    "#b35c00",
    "#005f73"
];

function padCalendarNumber(value) {
    /*
     * Return a two-digit number.
     */

    return String(value).padStart(2, "0");
}

function dateToInputValue(date) {
    /*
     * Format Date as YYYY-MM-DD for date inputs.
     */

    return [
        date.getFullYear(),
        padCalendarNumber(date.getMonth() + 1),
        padCalendarNumber(date.getDate())
    ].join("-");
}

function formatEuropeanDate(date) {
    /*
     * Format Date as DD.MM.YYYY.
     */

    return [
        padCalendarNumber(date.getDate()),
        padCalendarNumber(date.getMonth() + 1),
        date.getFullYear()
    ].join(".");
}

function formatEuropeanShortDate(date) {
    /*
     * Format Date as DD.MM.
     */

    return [
        padCalendarNumber(date.getDate()),
        padCalendarNumber(date.getMonth() + 1)
    ].join(".");
}

function formatEuropeanDateTime(value) {
    /*
     * Format ISO datetime as DD.MM.YYYY HH:mm.
     */

    if (!value) {
        return "-";
    }

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return value;
    }

    return formatEuropeanDate(date) + " " + padCalendarNumber(date.getHours()) + ":" + padCalendarNumber(date.getMinutes());
}

function parseCalendarDate(value) {
    /*
     * Parse YYYY-MM-DD as a local date.
     */

    const parts = String(value || "").split("-");

    if (parts.length !== 3) {
        return new Date();
    }

    return new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
}

function startOfCalendarWeek(date) {
    /*
     * Return Monday of the week for the provided date.
     */

    const result = new Date(date.getFullYear(), date.getMonth(), date.getDate());
    const day = result.getDay();
    const offset = day === 0 ? -6 : 1 - day;
    result.setDate(result.getDate() + offset);
    return result;
}

function startOfCalendarMonth(date) {
    /*
     * Return the first day of a month.
     */

    return new Date(date.getFullYear(), date.getMonth(), 1);
}

function endOfCalendarMonth(date) {
    /*
     * Return the first day of the next month.
     */

    return new Date(date.getFullYear(), date.getMonth() + 1, 1);
}

function addCalendarDays(date, days) {
    /*
     * Add days to a date.
     */

    const result = new Date(date.getFullYear(), date.getMonth(), date.getDate());
    result.setDate(result.getDate() + days);
    return result;
}

function addCalendarMonths(date, months) {
    /*
     * Add months to a date.
     */

    return new Date(date.getFullYear(), date.getMonth() + months, 1);
}

function calendarDaysBetween(start, end) {
    /*
     * Return day objects from start inclusive to end exclusive.
     */

    const days = [];
    let cursor = new Date(start.getFullYear(), start.getMonth(), start.getDate());

    while (cursor < end) {
        days.push(new Date(cursor.getFullYear(), cursor.getMonth(), cursor.getDate()));
        cursor.setDate(cursor.getDate() + 1);
    }

    return days;
}

function calendarWeekdayLabel(date) {
    /*
     * Return weekday label with European date.
     */

    return date.toLocaleDateString(undefined, { weekday: "short" }) + " " + formatEuropeanShortDate(date);
}

function calendarRangeLabel(start, end) {
    /*
     * Format a European date range.
     */

    const endInclusive = addCalendarDays(end, -1);
    return formatEuropeanDate(start) + " - " + formatEuropeanDate(endInclusive);
}

function calendarMonthLabel(start) {
    /*
     * Format month title.
     */

    return start.toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

function getCalendarUserLabel(event) {
    /*
     * Return display name for event user.
     */

    return event.display_name || event.username || ("user-" + event.user_id);
}
function getCalendarTeamId(team) {
    /*
     * Return team id from different possible API field names.
     */
    if (!team) {
        return null;
    }

    return Number(team.id || team.team_id || team.teamId || 0);
}


function getCalendarEventTeamId(event) {
    /*
     * Return event team id from different possible API field names.
     */
    if (!event) {
        return null;
    }

    return Number(event.team_id || event.teamId || 0);
}


function parseCalendarDateTime(value) {
    /*
     * Parse calendar event datetime safely.
     */
    if (!value) {
        return null;
    }

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return null;
    }

    return date;
}
function getCalendarUserColor(userId) {
    /*
     * Return a stable color for user id.
     */

    const id = Number(userId || 0);
    return calendarUserColors[Math.abs(id) % calendarUserColors.length];
}

function getCalendarQueryTeamId() {
    /*
     * Return team_id from current URL query string.
     */

    const params = new URLSearchParams(window.location.search);
    const value = params.get("team_id");

    return value ? Number(value) : null;
}

function setCalendarQueryTeamId(teamId) {
    /*
     * Update browser URL for team calendar without leaving the SPA.
     */

    const path = teamId ? "/calendar?team_id=" + encodeURIComponent(teamId) : "/calendar";
    history.pushState({ path: path }, "", path);
}

function setWeekCalendarRange(baseDate) {
    /*
     * Set range to the week of baseDate.
     */

    const monday = startOfCalendarWeek(baseDate || new Date());
    const nextMonday = addCalendarDays(monday, 7);

    $("#calendar-start").val(dateToInputValue(monday));
    $("#calendar-end").val(dateToInputValue(nextMonday));
}

function setMonthCalendarRange(baseDate) {
    /*
     * Set range to the month of baseDate.
     */

    const monthStart = startOfCalendarMonth(baseDate || new Date());
    const nextMonth = endOfCalendarMonth(monthStart);

    $("#calendar-start").val(dateToInputValue(monthStart));
    $("#calendar-end").val(dateToInputValue(nextMonth));
}

function setDefaultCalendarRange() {
    /*
     * Set default range based on the current calendar mode.
     */

    if (calendarMode === "month") {
        setMonthCalendarRange(new Date());
        return;
    }

    setWeekCalendarRange(new Date());
}

function loadCalendar() {
    /*
     * Load calendar page data.
     */

    calendarSelectedTeamId = getCalendarQueryTeamId();
    calendarMode = calendarSelectedTeamId ? "month" : "week";

    if (calendarMode === "month") {
        setMonthCalendarRange(new Date());
    } else {
        setWeekCalendarRange(new Date());
    }

    loadCalendarTeams(function () {
        refreshCalendar();
    });
}

function loadCalendarTeams(callback) {
    /*
     * Load available teams and fill calendar team filter.
     */

    apiGet("/api/teams", function (teams) {
        calendarTeamsCache = Array.isArray(teams) ? teams : [];

        const select = $("#calendar-team-filter");
        select.empty();
        select.append($("<option>").val("").text("All teams"));

        calendarTeamsCache.forEach(function (team) {
            select.append(
                $("<option>")
                    .val(team.id)
                    .text(team.name + " (" + team.slug + ")")
            );
        });

        if (calendarSelectedTeamId) {
            select.val(String(calendarSelectedTeamId));
        } else {
            select.val("");
        }

        if (typeof callback === "function") {
            callback();
        }
    });
}

function getCalendarVisibleTeams() {
    /*
     * Return teams visible in the current calendar view.
     */

    const selected = $("#calendar-team-filter").val();

    if (selected) {
        return calendarTeamsCache.filter(function (team) {
            return Number(team.id) === Number(selected);
        });
    }

    return calendarTeamsCache;
}
function getSelectedCalendarTeam() {
    /*
     * Return the selected team for monthly calendar view.
     */

    const teams = getCalendarVisibleTeams();

    if (!teams.length) {
        return null;
    }

    return teams[0];
}
function refreshCalendar() {
    /*
     * Refresh calendar events for all visible teams.
     */

    const teams = getCalendarVisibleTeams();
    const grid = $("#calendar-grid");

    calendarMode = $("#calendar-team-filter").val() ? "month" : "week";
    calendarEventsCache = [];
    grid.empty();

    updateCalendarTitle();

    if (!teams.length) {
        grid.append($("<div>").addClass("calendar-empty").text("No teams available."));
        $("#calendar-legend").empty();
        renderCalendarSummaryCards();
        renderCalendarDetailsEmpty();
        return;
    }

    let pending = teams.length;

    teams.forEach(function (team) {
        apiGet(
            "/api/calendar?team_id=" + team.id
                + "&start=" + encodeURIComponent($("#calendar-start").val())
                + "&end=" + encodeURIComponent($("#calendar-end").val()),
            function (events) {
                events = Array.isArray(events) ? events : [];

                events.forEach(function (event) {
                    const teamId = getCalendarTeamId(team);

                    event.team_id = getCalendarEventTeamId(event) || teamId;
                    event.team_slug = event.team_slug || team.slug;
                    event.team_name = event.team_name || team.name;

                    event.display_name = event.display_name || event.username || ("user-" + event.user_id);
                });

                calendarEventsCache = calendarEventsCache.concat(events);
                pending -= 1;

                if (pending === 0) {
                    if (calendarMode === "month") {
                        renderCalendarMonth();
                    } else {
                        renderCalendarWeek();
                    }

                    renderCalendarSummaryCards();
                    renderCalendarDetailsEmpty();
                }
            }
        );
    });
}

function updateCalendarTitle() {
    /*
     * Update calendar range title.
     */

    const start = parseCalendarDate($("#calendar-start").val());
    const end = parseCalendarDate($("#calendar-end").val());
    const selectedTeam = getCalendarVisibleTeams()[0];

    if (calendarMode === "month" && selectedTeam) {
        $("#calendar-range-title").text(selectedTeam.name + " / " + calendarMonthLabel(start));
        return;
    }

    $("#calendar-range-title").text(calendarRangeLabel(start, end));
}

function renderCalendarWeek() {
    /*
     * Render one-row-per-team weekly calendar.
     */

    const start = parseCalendarDate($("#calendar-start").val());
    const end = parseCalendarDate($("#calendar-end").val());
    const days = calendarDaysBetween(start, end);
    const teams = getCalendarVisibleTeams();
    const grid = $("#calendar-grid");
    const selectedTeam = getCalendarVisibleTeams()[0];
    const monthBody = $("<div>").addClass("calendar-month-body");

    grid.empty();
    grid.attr("class", "calendar-week-grid");

    const header = $("<div>").addClass("calendar-week-header calendar-row");
    header.append($("<div>").addClass("calendar-team-header").text("Team"));

    days.forEach(function (day) {
        header.append(
            $("<div>")
                .addClass("calendar-day-header")
                .text(calendarWeekdayLabel(day))
        );
    });

    grid.append(header);

    teams.forEach(function (team) {
        grid.append(renderCalendarTeamRow(team, days));
    });

    renderCalendarLegend();
}

function renderCalendarTeamRow(team, days) {
    /*
     * Render one team row.
     */

    const row = $("<div>").addClass("calendar-row calendar-team-row");

    const teamCell = $("<div>").addClass("calendar-team-cell");
    const link = $("<a>")
        .attr("href", "/calendar?team_id=" + team.id)
        .addClass("calendar-team-link")
        .text(team.name || team.slug)
        .on("click", function (event) {
            event.preventDefault();
            openCalendarTeam(team.id);
        });

    teamCell.append(link);
    teamCell.append($("<div>").addClass("calendar-team-subtitle").text(team.slug || ""));
    row.append(teamCell);

    days.forEach(function (day) {
        row.append(renderCalendarDayCell(team, day, false));
    });

    return row;
}

function renderCalendarMonth() {
    /*
     * Render monthly calendar for one selected team.
     */

    const start = parseCalendarDate($("#calendar-start").val());
    const end = parseCalendarDate($("#calendar-end").val());
    const selectedTeam = getSelectedCalendarTeam();
    const grid = $("#calendar-grid");

    grid.empty();
    grid.attr("class", "calendar-month-grid");

    if (!selectedTeam) {
        grid.append($("<div>").addClass("calendar-empty").text("Select a team."));
        $("#calendar-legend").empty();
        return;
    }

    const header = $("<div>").addClass("calendar-month-header");

    ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].forEach(function (weekday) {
        header.append(
            $("<div>")
                .addClass("calendar-month-weekday")
                .text(weekday)
        );
    });

    grid.append(header);

    const firstVisibleDay = startOfCalendarWeek(start);
    const lastVisibleDay = startOfCalendarWeek(addCalendarDays(end, 6));
    const days = calendarDaysBetween(firstVisibleDay, lastVisibleDay);
    const monthBody = $("<div>").addClass("calendar-month-body");

    days.forEach(function (day) {
        const inMonth = day >= start && day < end;
        const cell = $("<div>").addClass("calendar-month-day-cell");

        if (!inMonth) {
            cell.addClass("calendar-day-outside-month");
        }

        cell.append(
            $("<div>")
                .addClass("calendar-month-day-number")
                .text(formatEuropeanDate(day))
        );

        renderCalendarDayEvents(selectedTeam, day, cell, true);

        monthBody.append(cell);
    });

    grid.append(monthBody);
    renderCalendarLegend();
}

function renderCalendarDayCell(team, day, monthMode) {
    /*
     * Render one day cell for a team.
     */

    const cell = $("<div>").addClass(monthMode ? "calendar-month-day-cell" : "calendar-day-cell");

    renderCalendarDayEvents(team, day, cell, monthMode);

    return cell;
}

function renderCalendarAssignment(event, dayStart, dayEnd, monthMode) {
    /*
     * Render one assignment in a calendar day cell.
     */
    const eventStart = new Date(event.start);
    const eventEnd = new Date(event.end);

    const clippedStart = eventStart > dayStart ? eventStart : dayStart;
    const clippedEnd = eventEnd < dayEnd ? eventEnd : dayEnd;

    const label = getCalendarUserLabel(event);
    const color = getCalendarUserColor(event.user_id);

    const item = $("<button>")
        .attr("type", "button")
        .addClass(monthMode ? "calendar-assignment calendar-assignment-month" : "calendar-assignment")
        .attr(
            "style",
            "--calendar-user-color: " + color + "; " +
            "--calendar-user-bg: " + hexToCalendarSoftColor(color, 0.14) + ";"
        )
        .attr(
            "title",
            label + " / " +
            (event.rotation_name || "-") + " / " +
            formatEuropeanDateTime(clippedStart) + " - " +
            formatEuropeanDateTime(clippedEnd)
        )
        .on("click", function () {
            renderCalendarDetails(event, clippedStart, clippedEnd);
        });

    if (event.type === "override") {
        item.addClass("calendar-assignment-override");
    }

    item.append($("<span>").addClass("calendar-assignment-user").text(label));

    if (event.type === "override") {
        item.append($("<span>").addClass("calendar-assignment-badge").text("override"));
    }

    return item;
}

function renderCalendarLegend() {
    /*
     * Render user color legend for visible events.
     */

    const legend = $("#calendar-legend");
    const users = {};

    legend.empty();

    calendarEventsCache.forEach(function (event) {
        if (!event.user_id) {
            return;
        }

        users[event.user_id] = {
            id: event.user_id,
            label: getCalendarUserLabel(event),
            color: getCalendarUserColor(event.user_id)
        };
    });

    Object.keys(users).sort(function (a, b) { return Number(a) - Number(b); }).forEach(function (userId) {
        const user = users[userId];
        legend.append(
            $("<div>").addClass("calendar-legend-item")
                .append($("<span>").addClass("calendar-legend-color").attr("style", "background-color: " + user.color))
                .append($("<span>").addClass("calendar-legend-name").text(user.label))
        );
    });
}

function shiftCalendarRange(direction) {
    /*
     * Move calendar range.
     */

    const start = parseCalendarDate($("#calendar-start").val());

    if (calendarMode === "month") {
        const nextMonth = addCalendarMonths(start, direction);
        setMonthCalendarRange(nextMonth);
        refreshCalendar();
        return;
    }

    const end = parseCalendarDate($("#calendar-end").val());
    $("#calendar-start").val(dateToInputValue(addCalendarDays(start, direction * 7)));
    $("#calendar-end").val(dateToInputValue(addCalendarDays(end, direction * 7)));
    refreshCalendar();
}

function openCalendarTeam(teamId) {
    /*
     * Open team calendar in month mode.
     */

    calendarSelectedTeamId = teamId;
    calendarMode = "month";
    $("#calendar-team-filter").val(String(teamId));
    setCalendarQueryTeamId(teamId);
    setMonthCalendarRange(new Date());
    refreshCalendar();
}

function resetCalendarToAllTeams() {
    /*
     * Show all teams in week mode.
     */

    calendarSelectedTeamId = null;
    calendarMode = "week";
    $("#calendar-team-filter").val("");
    setCalendarQueryTeamId(null);
    setWeekCalendarRange(new Date());
    refreshCalendar();
}

$(document).on("click", "#reload-calendar", refreshCalendar);
$(document).on("click", "#calendar-today", function () {
    setDefaultCalendarRange();
    refreshCalendar();
});
$(document).on("click", "#calendar-prev", function () { shiftCalendarRange(-1); });
$(document).on("click", "#calendar-next", function () { shiftCalendarRange(1); });
$(document).on("change", "#calendar-team-filter", function () {
    const value = $(this).val();

    if (value) {
        openCalendarTeam(Number(value));
        return;
    }

    resetCalendarToAllTeams();
});
function renderCalendarDayEvents(team, day, cell, monthMode) {
    /*
     * Render events into an existing calendar day cell.
     */
    const teamId = getCalendarTeamId(team);

    const dayStart = new Date(
        day.getFullYear(),
        day.getMonth(),
        day.getDate(),
        0,
        0,
        0,
        0
    );

    const dayEnd = addCalendarDays(dayStart, 1);

    let events = calendarEventsCache.filter(function (event) {
        const eventTeamId = getCalendarEventTeamId(event);
        const eventStart = parseCalendarDateTime(event.start);
        const eventEnd = parseCalendarDateTime(event.end);

        if (!eventTeamId || !teamId || !eventStart || !eventEnd) {
            return false;
        }

        return eventTeamId === teamId &&
            eventStart < dayEnd &&
            eventEnd > dayStart;
    });

    events = filterCalendarEventsForSearch(events);
    events.sort(function (left, right) {
        return new Date(left.start).getTime() - new Date(right.start).getTime();
    });

    if (!events.length) {
        if (!monthMode) {
            cell.append(
                $("<div>")
                    .addClass("calendar-no-duty")
                    .text("-")
            );
        }

        return;
    }

    events.forEach(function (event) {
        cell.append(renderCalendarAssignment(event, dayStart, dayEnd, monthMode));
    });
}
function hexToCalendarSoftColor(hex, alpha) {
    /*
     * Convert hex color to rgba background for soft calendar cards.
     */
    const value = String(hex || "").replace("#", "");

    if (value.length !== 6) {
        return "rgba(11, 108, 255, " + alpha + ")";
    }

    const r = parseInt(value.substring(0, 2), 16);
    const g = parseInt(value.substring(2, 4), 16);
    const b = parseInt(value.substring(4, 6), 16);

    return "rgba(" + r + ", " + g + ", " + b + ", " + alpha + ")";
}

function getCalendarEventSearchText(event) {
    /*
     * Build searchable event text.
     */
    return [
        event.display_name,
        event.username,
        event.rotation_name,
        event.team_name,
        event.team_slug,
        event.type
    ].join(" ").toLowerCase();
}

function getCalendarSearchQuery() {
    /*
     * Return current calendar search query.
     */
    return String($("#calendar-search").val() || "").trim().toLowerCase();
}

function filterCalendarEventsForSearch(events) {
    /*
     * Filter events by search input.
     */
    const query = getCalendarSearchQuery();

    if (!query) {
        return events;
    }

    return events.filter(function (event) {
        return getCalendarEventSearchText(event).indexOf(query) !== -1;
    });
}
function renderCalendarSummaryCards() {
    /*
     * Render calendar summary cards.
     */
    const visibleTeams = getCalendarVisibleTeams();
    const users = {};
    let overrides = 0;

    calendarEventsCache.forEach(function (event) {
        if (event.user_id) {
            users[event.user_id] = true;
        }

        if (event.type === "override") {
            overrides += 1;
        }
    });

    $("#calendar-summary-teams").text(visibleTeams.length);
    $("#calendar-summary-users").text(Object.keys(users).length);
    $("#calendar-summary-assignments").text(calendarEventsCache.length);
    $("#calendar-summary-overrides").text(overrides);
}


function calendarInitials(name) {
    /*
     * Return initials for details avatar.
     */
    return String(name || "?")
        .trim()
        .split(/\s+/)
        .slice(0, 2)
        .map(function (part) {
            return part.substring(0, 1).toUpperCase();
        })
        .join("") || "?";
}


function calendarDetailsItem(label, value) {
    /*
     * Render one details item.
     */
    return $("<div>")
        .addClass("details-item")
        .append($("<div>").addClass("details-label").text(label))
        .append($("<div>").addClass("details-value").text(value || "-"));
}


function renderCalendarDetails(event, clippedStart, clippedEnd) {
    /*
     * Render selected assignment details.
     */
    const userLabel = getCalendarUserLabel(event);
    const body = $("#calendar-details-body");

    $("#calendar-details-subtitle").text(event.team_name || event.team_slug || "Selected shift");

    body.empty();

    body.append(
        $("<div>")
            .addClass("details-user")
            .append($("<div>").addClass("details-avatar").text(calendarInitials(userLabel)))
            .append(
                $("<div>")
                    .append($("<div>").addClass("details-name").text(userLabel))
                    .append($("<div>").addClass("details-meta").text(event.username || "On-call user"))
            )
    );

    body.append(
        $("<div>")
            .addClass("details-list")
            .append(calendarDetailsItem("Team", event.team_name || event.team_slug))
            .append(calendarDetailsItem("Rotation", event.rotation_name))
            .append(calendarDetailsItem("Type", event.type || "regular"))
            .append(calendarDetailsItem("Start", formatEuropeanDateTime(clippedStart || event.start)))
            .append(calendarDetailsItem("End", formatEuropeanDateTime(clippedEnd || event.end)))
    );
}


function renderCalendarDetailsEmpty() {
    /*
     * Reset details panel.
     */
    $("#calendar-details-subtitle").text("Select an assignment");

    $("#calendar-details-body").html(
        '<div class="details-empty">' +
        'Click any shift in the calendar to see user, team, rotation and time range.' +
        '</div>'
    );
}
$(document).on("input", "#calendar-search", function () {
    if (calendarMode === "month") {
        renderCalendarMonth();
    } else {
        renderCalendarWeek();
    }

    renderCalendarDetailsEmpty();
});

$(document).on("change", "#calendar-start, #calendar-end", function () {
    refreshCalendar();
});
