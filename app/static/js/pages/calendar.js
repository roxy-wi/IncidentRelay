let calendarTeamsCache = [];
let calendarEventsCache = [];
let calendarSelectedRotationId = null;
let calendarMode = "week";
let selectedCalendarEvent = null;
let selectedCalendarClippedStart = null;
let selectedCalendarClippedEnd = null;
let calendarExportFeed = null;

const calendarWeekdaysShort = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

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

function getCalendarDisplayTimezone() {
    if (window.AppTimezones) {
        return AppTimezones.getDisplayTimezone(currentUser);
    }

    return "UTC";
}

function getCalendarEventTimezone(event) {
    return getCalendarDisplayTimezone();
}

function getCalendarSourceTimezone(event) {
    return event && event.timezone ? event.timezone : "UTC";
}

function dateToInputValue(date) {
    /*
     * Format Date as YYYY-MM-DD for date inputs.
     */

    return [
        date.getFullYear(),
        padDateTimePart(date.getMonth() + 1),
        padDateTimePart(date.getDate())
    ].join("-");
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

function getTimezoneOffsetMs(date, timezone) {
    const parts = new Intl.DateTimeFormat("en-US", {
        timeZone: timezone || "UTC",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
        hourCycle: "h23",
    }).formatToParts(date);

    const values = {};

    parts.forEach(function (part) {
        if (part.type !== "literal") {
            values[part.type] = part.value;
        }
    });

    const localAsUtc = Date.UTC(
        Number(values.year),
        Number(values.month) - 1,
        Number(values.day),
        Number(values.hour),
        Number(values.minute),
        Number(values.second)
    );

    return localAsUtc - date.getTime();
}

function calendarZonedDateTimeToDate(
    year,
    month,
    day,
    hour,
    minute,
    second,
    timezone
) {
    const utcGuess = Date.UTC(
        year,
        month - 1,
        day,
        hour || 0,
        minute || 0,
        second || 0
    );

    const firstOffset = getTimezoneOffsetMs(
        new Date(utcGuess),
        timezone
    );
    const adjusted = utcGuess - firstOffset;
    const secondOffset = getTimezoneOffsetMs(
        new Date(adjusted),
        timezone
    );

    return new Date(utcGuess - secondOffset);
}

function calendarDisplayDayStart(day) {
    const timezone = getCalendarDisplayTimezone();

    return calendarZonedDateTimeToDate(
        day.getFullYear(),
        day.getMonth() + 1,
        day.getDate(),
        0,
        0,
        0,
        timezone
    );
}

function calendarDisplayNextDayStart(day) {
    return calendarDisplayDayStart(addCalendarDays(day, 1));
}

function parseCalendarDateTime(value) {
    /*
     * Parse calendar event datetime safely.
     *
     * Backend stores and returns UTC-naive datetimes like:
     * 2026-05-30T08:11:00
     *
     * Browser treats such strings as local time, so we explicitly
     * interpret timezone-less ISO datetime values as UTC.
     */
    if (!value) {
        return null;
    }

    if (value instanceof Date) {
        return Number.isNaN(value.getTime()) ? null : value;
    }

    let text = String(value).trim();

    if (!text) {
        return null;
    }

    const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(text);

    if (!hasTimezone) {
        text += "Z";
    }

    const date = new Date(text);

    if (Number.isNaN(date.getTime())) {
        return null;
    }

    return date;
}


function formatDateTimeMinutes(value) {
    /*
     * Format ISO datetime as DD.MM.YYYY HH:mm.
     */

    if (!value) {
        return "-";
    }

    const date = value instanceof Date ? value : new Date(value);

    if (Number.isNaN(date.getTime())) {
        return String(value);
    }

    return formatShortDate(date) + " " + padDateTimePart(date.getHours()) + ":" + padDateTimePart(date.getMinutes());
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
     * Return weekday label with European short date.
     */

    return calendarWeekdaysShort[date.getDay()] + " " + formatShortDate(date);
}


function calendarRangeLabel(start, end) {
    /*
     * Format a European date range.
     */

    const endInclusive = addCalendarDays(end, -1);

    return formatDate(start) + " - " + formatDate(endInclusive);
}


function calendarMonthLabel(start) {
    /*
     * Format month title using numeric European style.
     */

    return padDateTimePart(start.getMonth() + 1) + "." + start.getFullYear();
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

function getCalendarTeamById(teamId) {
    teamId = Number(teamId || 0);

    if (!teamId) {
        return null;
    }

    return calendarTeamsCache.find(function (team) {
        return Number(team.id) === teamId;
    }) || null;
}

function canManageCalendarTeam(teamId) {
    const team = getCalendarTeamById(teamId);

    if (!team || !team.permissions) {
        return false;
    }

    return !!team.permissions.can_write;
}


function getCalendarEventRotationId(event) {
    /*
     * Return event rotation id from different possible API field names.
     */

    if (!event) {
        return null;
    }

    return Number(event.rotation_id || event.rotationId || 0);
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

function getCalendarQueryRotationId() {
    /*
     * Return rotation_id from current URL query string.
     */

    const params = new URLSearchParams(window.location.search);
    const value = params.get("rotation_id");

    return value ? Number(value) : null;
}


function setCalendarQueryTeamId(teamId, rotationId, replace) {
    /*
     * Update browser URL for team/rotation calendar without leaving the SPA.
     */
    const params = new URLSearchParams();

    if (teamId) {
        params.set("team_id", String(teamId));
    }

    if (rotationId) {
        params.set("rotation_id", String(rotationId));
    }

    const query = params.toString();
    const path = query ? "/calendar?" + query : "/calendar";
    const state = { path: path };
    if (replace) {
        history.replaceState(state, "", path);
        return;
    }

    history.pushState(state, "", path);
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


function getCalendarInitialTeamId() {
    /*
     * Direct links may still contain team_id.
     * If team_id exists in URL, sync it into the global selector.
     * Otherwise use the global selector.
     */
    const queryTeamId = getCalendarQueryTeamId();

    if (queryTeamId) {
        setSelectedTeamId(queryTeamId, false);
        return queryTeamId;
    }

    return selectedTeamNumber();
}

function loadCalendar() {
    /*
     * Load calendar page data.
     */
    calendarSelectedTeamId = getCalendarInitialTeamId();
    calendarSelectedRotationId = getCalendarQueryRotationId();

    calendarMode = (calendarSelectedTeamId || calendarSelectedRotationId) ? "month" : "week";

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
     * Load available teams.
     */
    apiGet("/api/teams", function (teams) {
        calendarTeamsCache = Array.isArray(teams) ? teams : [];

        if (typeof callback === "function") {
            callback();
        }
    });
}

function getCalendarVisibleTeams() {
    /*
     * Return teams visible in the current calendar view.
     */
    const selected = getCalendarSelectedTeamId();

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


function ensureCalendarRotationFilter() {
    /*
     * Rotation selector is rendered in calendar.html.
     * JS only fills and shows/hides it.
     */
    const select = $("#calendar-rotation-filter");

    if (select.length) {
        return select;
    }

    return $("<select>")
        .attr("id", "calendar-rotation-filter")
        .addClass("input filter-select")
        .hide();
}
function getCalendarSelectedTeamId() {
    /*
     * Global team selector is the only team scope source.
     * Do not prefer cached calendarSelectedTeamId because it becomes stale
     * after changing #global-team-filter.
     */
    if (typeof selectedTeamNumber === "function") {
        return selectedTeamNumber();
    }

    if (typeof selectedTeamId === "function") {
        const value = selectedTeamId();
        return value ? Number(value) : null;
    }

    const value = $("#global-team-filter").val();
    return value ? Number(value) : null;
}
function syncCalendarTeamScopeFromGlobal() {
    /*
     * Sync calendar state from global team selector.
     * If team changed, selected rotation must be reset.
     */
    const globalTeamId = getCalendarSelectedTeamId();
    const currentTeamId = calendarSelectedTeamId ? Number(calendarSelectedTeamId) : null;

    if (Number(currentTeamId || 0) !== Number(globalTeamId || 0)) {
        calendarSelectedRotationId = null;
    }

    calendarSelectedTeamId = globalTeamId;
    calendarMode = calendarSelectedTeamId ? "month" : "week";

    return calendarSelectedTeamId;
}

function getSelectedCalendarRotation() {
    /*
     * Return selected rotation calendar descriptor.
     */

    const rotationId = Number(calendarSelectedRotationId || 0);

    if (!rotationId) {
        return null;
    }

    return getRotationCalendarsFromEvents().find(function (calendar) {
        return Number(calendar.rotation_id) === rotationId;
    }) || null;
}


function syncSelectedRotationCalendar(calendars) {
    /*
     * Keep selected rotation valid for current team.
     * When team has 0 or 1 rotations, do not keep a local rotation selection.
     */
    calendars = Array.isArray(calendars) ? calendars : [];

    if (calendarMode !== "month") {
        calendarSelectedRotationId = null;
        return;
    }

    if (calendars.length <= 1) {
        calendarSelectedRotationId = null;
        return;
    }

    const selectedExists = calendars.some(function (calendar) {
        return Number(calendar.rotation_id) === Number(calendarSelectedRotationId);
    });

    if (!calendarSelectedRotationId || !selectedExists) {
        calendarSelectedRotationId = calendars[0].rotation_id;
    }
}


function updateCalendarRotationFilter(calendars) {
    /*
     * Fill rotation selector for selected team calendar.
     * Hide and clear selector when team has 0 or 1 rotations.
     */
    const select = ensureCalendarRotationFilter();
    const selectedTeamId = getCalendarSelectedTeamId();

    calendars = Array.isArray(calendars) ? calendars : [];

    select.empty();

    if (calendarMode !== "month" || !selectedTeamId || calendars.length <= 1) {
        calendarSelectedRotationId = null;
        select.val("");
        select.hide();
        return;
    }

    calendars.forEach(function (calendar) {
        select.append(
            $("<option>")
                .val(calendar.rotation_id)
                .text(calendar.rotation_name || ("rotation #" + calendar.rotation_id))
        );
    });

    if (calendarSelectedRotationId) {
        select.val(String(calendarSelectedRotationId));
    }

    select.show();
}


function getRotationCalendarsForCurrentView() {
    /*
     * Return rotation calendars that should be rendered now.
     */
    let calendars = getRotationCalendarsFromEvents();
    const selectedTeamId = getCalendarSelectedTeamId();

    if (selectedTeamId) {
        calendars = calendars.filter(function (calendar) {
            return Number(calendar.team_id) === Number(selectedTeamId);
        });
    }

    if (calendarMode === "month") {
        syncSelectedRotationCalendar(calendars);

        if (calendarSelectedRotationId) {
            calendars = calendars.filter(function (calendar) {
                return Number(calendar.rotation_id) === Number(calendarSelectedRotationId);
            });
        }

        return calendars.slice(0, 1);
    }

    return calendars;
}

function refreshCalendar() {
    /*
     * Refresh calendar events for all visible teams.
     * Team scope always comes from the global team selector.
     */
    syncCalendarTeamScopeFromGlobal();

    if (calendarMode === "month") {
        setMonthCalendarRange(new Date($("#calendar-start").val() || new Date()));
    } else {
        setWeekCalendarRange(new Date($("#calendar-start").val() || new Date()));
    }

    const teams = getCalendarVisibleTeams();
    const grid = $("#calendar-grid");

    calendarEventsCache = [];
    grid.empty();
    updateCalendarTitle();

    if (!teams.length) {
        $("#calendar-rotation-filter").hide().empty();
        grid.append(
            $("<div>")
                .addClass("calendar-empty")
                .text("No teams available.")
        );
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
                    const visibleCalendars = getRotationCalendarsFromEvents().filter(function (calendar) {
                        const selectedTeamId = getCalendarSelectedTeamId();

                        return !selectedTeamId
                            || Number(calendar.team_id) === Number(selectedTeamId);
                    });

                    syncSelectedRotationCalendar(visibleCalendars);
                    updateCalendarRotationFilter(visibleCalendars);
                    setCalendarQueryTeamId(calendarSelectedTeamId, calendarSelectedRotationId, true);

                    updateCalendarTitle();

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
    const selectedTeam = getSelectedCalendarTeam();

    if (calendarMode === "month" && selectedTeam) {
        const selectedRotation = getSelectedCalendarRotation();
        const rotationName = selectedRotation ? selectedRotation.rotation_name : null;

        $("#calendar-range-title").text(
            selectedTeam.name +
                (rotationName ? " / " + rotationName : "") +
                " / " +
                calendarMonthLabel(start)
        );
        return;
    }

    $("#calendar-range-title").text(calendarRangeLabel(start, end));
}


function renderCalendarWeek() {
    /*
     * Render all visible rotations as separate weekly calendars.
     */

    renderRotationCalendars(false);
}


function renderCalendarMonth() {
    /*
     * Render selected team rotations as separate monthly calendars.
     */

    renderRotationCalendars(true);
}


function getRotationCalendarsFromEvents() {
    /*
     * Build separate calendar descriptors from final schedule events.
     * Rotation is the visible calendar entity. Team is only the owner/filter.
     */

    const visibleTeams = getCalendarVisibleTeams();
    const visibleTeamIds = {};
    const calendarsByKey = {};

    visibleTeams.forEach(function (team) {
        visibleTeamIds[Number(team.id)] = team;
    });

    calendarEventsCache.forEach(function (event) {
        const teamId = getCalendarEventTeamId(event);
        const rotationId = getCalendarEventRotationId(event);

        if (!teamId || !rotationId || !visibleTeamIds[teamId]) {
            return;
        }

        const key = teamId + ":" + rotationId;

        if (!calendarsByKey[key]) {
            calendarsByKey[key] = {
                team_id: teamId,
                team_name: event.team_name || visibleTeamIds[teamId].name,
                team_slug: event.team_slug || visibleTeamIds[teamId].slug,
                rotation_id: rotationId,
                rotation_name: event.rotation_name || ("rotation #" + rotationId)
            };
        }
    });

    return Object.keys(calendarsByKey)
        .map(function (key) {
            return calendarsByKey[key];
        })
        .sort(function (left, right) {
            const teamCompare = String(left.team_name || "").localeCompare(String(right.team_name || ""));

            if (teamCompare !== 0) {
                return teamCompare;
            }

            return String(left.rotation_name || "").localeCompare(String(right.rotation_name || ""));
        });
}


function renderRotationCalendars(monthMode) {
    /*
     * Render one complete calendar block per rotation.
     */

    const grid = $("#calendar-grid");
    const start = parseCalendarDate($("#calendar-start").val());
    const end = parseCalendarDate($("#calendar-end").val());
    const calendars = getRotationCalendarsForCurrentView();

    let days;

    if (monthMode) {
        const monthStart = startOfCalendarMonth(start);
        const monthEnd = endOfCalendarMonth(monthStart);

        const firstVisibleDay = startOfCalendarWeek(monthStart);
        const lastVisibleDay = endOfCalendarWeek(addCalendarDays(monthEnd, -1));

        days = calendarDaysBetween(firstVisibleDay, lastVisibleDay);
    } else {
        days = calendarDaysBetween(start, end);
    }

    grid.empty();
    grid.attr("class", "rotation-calendars-container");

    if (!calendars.length) {
        grid.append(
            $("<div>")
                .addClass("calendar-empty")
                .text("No calendars found.")
        );
        $("#calendar-legend").empty();
        return;
    }

    calendars.forEach(function (calendar) {
        if (monthMode) {
            const monthStart = startOfCalendarMonth(start);
            const monthEnd = endOfCalendarMonth(monthStart);

            grid.append(
                renderRotationCalendarBlock(
                    calendar,
                    days,
                    monthMode,
                    monthStart,
                    monthEnd
                )
            );
            return;
        }

        grid.append(renderRotationCalendarBlock(calendar, days, monthMode, start, end));
    });
}


function renderRotationCalendarBlock(calendar, days, monthMode, rangeStart, rangeEnd) {
    /*
     * Render one separate calendar block for one rotation.
     */

    const block = $("<section>").addClass("rotation-calendar-block");

    block.append(
        $("<div>")
            .addClass("rotation-calendar-header")
            .append(
                $("<div>")
                    .append($("<h3>").text(calendar.rotation_name || ("rotation #" + calendar.rotation_id)))
            )
    );

    if (monthMode) {
        block.append(renderRotationMonthGrid(calendar, days, rangeStart, rangeEnd));
    } else {
        block.append(renderRotationWeekGrid(calendar, days));
    }

    return block;
}


function renderRotationWeekGrid(calendar, days) {
    /*
     * Render a weekly grid for one rotation.
     */

    const grid = $("<div>").addClass("calendar-week-grid rotation-calendar-week-grid");
    const header = $("<div>").addClass("calendar-week-header calendar-row");

    header.append(
        $("<div>")
            .addClass("calendar-team-header")
            .text("Calendar")
    );

    days.forEach(function (day) {
        header.append(
            $("<div>")
                .addClass("calendar-day-header")
                .text(calendarWeekdayLabel(day))
        );
    });

    grid.append(header);
    const row = $("<div>").addClass("calendar-row calendar-team-row");

    row.append(
        $("<div>")
            .addClass("calendar-team-cell")
            .append(
                $("<a>")
                    .attr(
                        "href",
                        "/calendar?team_id=" + calendar.team_id + "&rotation_id=" + calendar.rotation_id
                    )
                    .addClass("calendar-team-link")
                    .text(calendar.team_name || calendar.team_slug || ("team #" + calendar.team_id))
                    .on("click", function (event) {
                        event.preventDefault();
                        openCalendarTeam(calendar.team_id, calendar.rotation_id);
                    })
            )
            .append(
                $("<div>")
                    .addClass("calendar-team-subtitle")
                    .text(calendar.rotation_name || ("rotation #" + calendar.rotation_id))
            )
    );

    days.forEach(function (day) {
        const cell = $("<div>").addClass("calendar-day-cell");

        renderRotationCalendarDayTimeline(calendar, day, cell, false);

        row.append(cell);
    });

    grid.append(row);

    return grid;
}


function renderRotationMonthGrid(calendar, days, rangeStart, rangeEnd) {
    /*
     * Render a monthly grid for one rotation.
     */

    const grid = $("<div>").addClass("calendar-month-grid rotation-calendar-month-grid");
    const header = $("<div>").addClass("calendar-month-header");
    const body = $("<div>").addClass("calendar-month-body");

    ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].forEach(function (weekday) {
        header.append(
            $("<div>")
                .addClass("calendar-month-weekday")
                .text(weekday)
        );
    });

    grid.append(header);

    days.forEach(function (day) {
        const inMonth = day >= rangeStart && day < rangeEnd;
        const cell = $("<div>").addClass("calendar-month-day-cell");

        if (!inMonth) {
            cell.addClass("calendar-day-outside-month");
        }

        cell.append(
            $("<div>")
                .addClass("calendar-month-day-number")
                .text(formatShortDate(day))
        );

        renderRotationCalendarDayTimeline(calendar, day, cell, true);

        body.append(cell);
    });

    grid.append(body);

    return grid;
}


function renderRotationCalendarDayTimeline(calendar, day, cell, monthMode) {
    /*
     * Render final schedule timeline for one rotation/day in the current
     * display timezone.
     */
    const dayStart = calendarDisplayDayStart(day);
    const dayEnd = calendarDisplayNextDayStart(day);
    const events = getCalendarEventsForRotation(calendar, dayStart, dayEnd);

    cell.append(renderCalendarDayTimeline(
        events,
        dayStart,
        dayEnd,
        monthMode
    ));
}


function getCalendarEventsForRotation(calendar, dayStart, dayEnd) {
    /*
     * Return visible events for one rotation and one day.
     */

    let events = calendarEventsCache.filter(function (event) {
        const eventTeamId = getCalendarEventTeamId(event);
        const eventRotationId = getCalendarEventRotationId(event);
        const eventStart = parseCalendarDateTime(event.start);
        const eventEnd = parseCalendarDateTime(event.end);

        if (!eventTeamId || !eventRotationId || !eventStart || !eventEnd) {
            return false;
        }

        return (
            eventTeamId === Number(calendar.team_id)
            && eventRotationId === Number(calendar.rotation_id)
            && eventStart < dayEnd
            && eventEnd > dayStart
        );
    });

    events = filterCalendarEventsForSearch(events);

    return events.sort(function (left, right) {
        return new Date(left.start).getTime() - new Date(right.start).getTime();
    });
}


function renderCalendarDayTimeline(events, dayStart, dayEnd, monthMode) {
    /*
     * Render one horizontal timeline for a day.
     */

    const timeline = $("<div>")
        .addClass("calendar-day-timeline")
        .toggleClass("calendar-day-timeline-month", !!monthMode);

    timeline.append(renderCalendarTimelineTicks());

    if (!events.length) {
        timeline.append(
            $("<div>")
                .addClass("calendar-no-duty calendar-no-duty-timeline")
                .text("-")
        );

        return timeline;
    }

    events.forEach(function (event) {
        timeline.append(renderCalendarTimelineAssignment(event, dayStart, dayEnd, monthMode));
    });

    return timeline;
}


function renderCalendarTimelineTicks() {
    /*
     * Render subtle time marks inside a day: 00, 06, 12, 18.
     */

    const ticks = $("<div>").addClass("calendar-timeline-ticks");

    [
        { label: "00", left: 0 },
        { label: "06", left: 25 },
        { label: "12", left: 50 },
        { label: "18", left: 75 }
    ].forEach(function (tick) {
        ticks.append(
            $("<span>")
                .addClass("calendar-timeline-tick")
                .css("left", tick.left + "%")
                .text(tick.label)
        );
    });

    return ticks;
}


function renderCalendarTimelineAssignment(event, dayStart, dayEnd, monthMode) {
    /*
     * Render one assignment positioned by duration inside the day.
     * The visible label intentionally contains only the on-call user.
     * Time is available in title/details.
     */

    const eventStart = parseCalendarDateTime(event.start);
    const eventEnd = parseCalendarDateTime(event.end);
    const displayTimezone = getCalendarEventTimezone(event);

    if (!eventStart || !eventEnd) {
        return $("<span>");
    }

    const clippedStart = eventStart > dayStart ? eventStart : dayStart;
    const clippedEnd = eventEnd < dayEnd ? eventEnd : dayEnd;

    const position = getCalendarTimelinePosition(clippedStart, clippedEnd, dayStart, dayEnd);
    const label = getCalendarUserLabel(event);
    const color = getCalendarUserColor(event.user_id);
    const layerLabel = event.type === "override"
        ? "override"
        : (event.layer_name || "final");

    const item = $("<button>")
        .attr("type", "button")
        .addClass("calendar-assignment calendar-assignment-timeline")
        .toggleClass("calendar-assignment-timeline-month", !!monthMode)
        .toggleClass("calendar-assignment-override", event.type === "override")
        .attr(
            "style",
            "--calendar-user-color: " + color + "; " +
            "--calendar-user-bg: " + hexToCalendarSoftColor(color, 0.14) + "; " +
            "left: " + position.left + "%; " +
            "width: " + position.width + "%;"
        )
        .attr(
            "title",
            label +
            " / " +
            (event.rotation_name || "-") +
            " / " +
            layerLabel +
            " / " +
            formatTimeMinutesInTimezone(clippedStart, displayTimezone) +
            " - " +
            formatTimeMinutesInTimezone(clippedEnd, displayTimezone)
        )
        .on("click", function () {
            renderCalendarDetails(event, clippedStart, clippedEnd);
        });

    item.append(
        $("<span>")
            .addClass("calendar-assignment-user")
            .text(label)
    );

    if (event.type === "override" && !monthMode) {
        item.append(
            $("<span>")
                .addClass("calendar-assignment-badge")
                .text("override")
        );
    }

    return item;
}


function getCalendarTimelinePosition(clippedStart, clippedEnd, dayStart, dayEnd) {
    /*
     * Calculate left/width percentage for one day.
     */

    const totalMs = dayEnd.getTime() - dayStart.getTime();
    const startMs = clippedStart.getTime() - dayStart.getTime();
    const endMs = clippedEnd.getTime() - dayStart.getTime();

    let left = totalMs > 0 ? (startMs / totalMs) * 100 : 0;
    let width = totalMs > 0 ? ((endMs - startMs) / totalMs) * 100 : 100;

    left = Math.max(0, Math.min(100, left));
    width = Math.max(0.8, Math.min(100 - left, width));

    return {
        left: left,
        width: width
    };
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


function openCalendarTeam(teamId, rotationId) {
    /*
     * Open one team calendar in month mode.
     */
    calendarSelectedTeamId = teamId ? Number(teamId) : null;
    calendarSelectedRotationId = rotationId || null;
    calendarMode = "month";

    setSelectedTeamId(calendarSelectedTeamId, false);
    setCalendarQueryTeamId(calendarSelectedTeamId, calendarSelectedRotationId, false);

    setMonthCalendarRange(new Date());
    refreshCalendar();
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
        event.layer_name,
        event.layer_priority,
        event.timezone,
        event.team_name,
        event.team_slug,
        event.type,
        event.reason
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
    const typeLabel = event.type === "override" ? "override" : "scheduled layer";
    const displayTimezone = getCalendarEventTimezone(event);
    const sourceTimezone = getCalendarSourceTimezone(event);

    selectedCalendarEvent = event;
    selectedCalendarClippedStart = clippedStart;
    selectedCalendarClippedEnd = clippedEnd;

    $("#calendar-details-subtitle").text(event.team_name || event.team_slug || "Selected shift");

    body.empty();

    body.append(
        $("<div>")
            .addClass("details-user")
            .append(
                $("<div>")
                    .addClass("details-avatar")
                    .text(calendarInitials(userLabel))
            )
            .append(
                $("<div>")
                    .append(
                        $("<div>")
                            .addClass("details-name")
                            .text(userLabel)
                    )
                    .append(
                        $("<div>")
                            .addClass("details-meta")
                            .text(event.username || "On-call user")
                    )
            )
    );

    const details = $("<div>")
        .addClass("details-list")
        .append(calendarDetailsItem("Team", event.team_name || event.team_slug))
        .append(calendarDetailsItem("Rotation", event.rotation_name))
        .append(calendarDetailsItem("Layer", event.layer_name || (event.type === "override" ? "Override" : "Final schedule")))
        .append(calendarDetailsItem("Layer priority", event.layer_priority === null || event.layer_priority === undefined ? "-" : String(event.layer_priority)))
        .append(calendarDetailsItem("Timezone", displayTimezone))
        .append(
            sourceTimezone !== displayTimezone
                ? calendarDetailsItem("Source timezone", sourceTimezone)
                : $("")
        )
        .append(calendarDetailsItem("Type", typeLabel))
        .append(calendarDetailsItem(
            "Start",
            formatDateTimeMinutesInTimezone(
                clippedStart || event.start,
                displayTimezone
            )
        ))
        .append(calendarDetailsItem(
            "End",
            formatDateTimeMinutesInTimezone(
                clippedEnd || event.end,
                displayTimezone
            )
        ))

    if (event.reason) {
        details.append(calendarDetailsItem("Reason", event.reason));
    }

    body.append(details);

    const actions = $("<div>").addClass("details-actions");

    if (canManageCalendarTeam(event.team_id)) {
        actions.append(
            makeIconButton({
                icon: "fas fa-user-clock",
                label: "Create override",
                onClick: function () {
                    openCalendarOverrideModal(event, clippedStart, clippedEnd);
                }
            })
        );
    }

    if (actions.children().length) {
        body.append(actions);
    }
}


function renderCalendarDetailsEmpty() {
    /*
     * Reset details panel.
     */

    selectedCalendarEvent = null;
    selectedCalendarClippedStart = null;
    selectedCalendarClippedEnd = null;

    $("#calendar-details-subtitle").text("Select an assignment");
    $("#calendar-details-body").html(
        '<div class="empty-state">Click any shift in the calendar to see user, team, rotation and time range.</div>'
    );
}


function calendarDateTimeLocalValue(value) {
    /*
     * Format a calendar datetime for datetime-local inputs.
     */

    const date = value instanceof Date ? value : new Date(value);

    if (Number.isNaN(date.getTime())) {
        return "";
    }

    return [
        date.getFullYear(),
        padDateTimePart(date.getMonth() + 1),
        padDateTimePart(date.getDate())
    ].join("-") + "T" + [
        padDateTimePart(date.getHours()),
        padDateTimePart(date.getMinutes())
    ].join(":");
}


function openCalendarOverrideModal(event, clippedStart, clippedEnd) {
    /*
     * Open the existing rotation overrides modal from calendar details.
     */

    if (!event || !event.rotation_id) {
        showAppError("This calendar item is not linked to a rotation.");
        return;
    }

    selectOverrideRotation(event.rotation_id, {
        startsAt: calendarDateTimeLocalValue(clippedStart || event.start),
        endsAt: calendarDateTimeLocalValue(clippedEnd || event.end),
        reason: event.type === "override" ? (event.reason || "") : "",
        afterChange: function () {
            refreshCalendar();
        }
    });
}


$(document).on("click", "#reload-calendar", refreshCalendar);

$(document).on("click", "#calendar-today", function () {
    setDefaultCalendarRange();
    refreshCalendar();
});

$(document).on("click", "#calendar-prev", function () {
    shiftCalendarRange(-1);
});

$(document).on("click", "#calendar-next", function () {
    shiftCalendarRange(1);
});


$(document).on("change", "#calendar-rotation-filter", function () {
    const value = $(this).val();

    calendarSelectedTeamId = getCalendarSelectedTeamId();
    calendarSelectedRotationId = value ? Number(value) : null;

    setCalendarQueryTeamId(calendarSelectedTeamId, calendarSelectedRotationId, true);
    updateCalendarTitle();
    renderCalendarMonth();
    renderCalendarDetailsEmpty();
});


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
function endOfCalendarWeek(date) {
    /*
     * Return Monday after the week containing the provided date.
     */
    return addCalendarDays(startOfCalendarWeek(date), 7);
}
function getCalendarExportTeamId() {
    return Number($("#global-team-filter").val() || 0) || null;
}

function setCalendarExportStatus(message, isError) {
    const box = $("#calendar-export-status");

    box
        .text(message || "")
        .toggleClass("error", !!isError)
        .toggleClass("success", !!message && !isError);
}

function openCalendarExportModal() {
    const teamId = getCalendarExportTeamId();

    if (!teamId) {
        setCalendarExportStatus("Select a team before exporting calendar.", true);
        return;
    }

    calendarExportFeed = null;
    $("#calendar-export-url").val("");
    setCalendarExportStatus("", false);

    openAppModal("#calendar-export-modal");

    apiGet(
        "/api/calendar/feeds?team_id=" + encodeURIComponent(teamId),
        function (feeds) {
            feeds = Array.isArray(feeds) ? feeds : [];

            if (!feeds.length) {
                setCalendarExportStatus(
                    "No subscription URL exists yet. Click Create URL.",
                    false
                );
                return;
            }

            calendarExportFeed = feeds[0];

            if (calendarExportFeed.feed_url) {
                $("#calendar-export-url").val(calendarExportFeed.feed_url);
            } else {
                setCalendarExportStatus(
                    "This URL was created earlier and cannot be shown again. Click Regenerate to create a new URL.",
                    true
                );
            }
        }
    );
}

function createCalendarExportFeed() {
    const teamId = getCalendarExportTeamId();
    if (!teamId) {
        setCalendarExportStatus("Select a team before exporting calendar.", true);
        return;
    }

    apiPost(
        "/api/calendar/feeds",
        {
            team_id: teamId,
            name: "On-call calendar",
            past_days: 7,
            future_days: 90
        },
        function (feed) {
            calendarExportFeed = feed;
            $("#calendar-export-url").val(feed.feed_url || "");
            setCalendarExportStatus("Subscription URL created. Copy it now.", false);
        }
    );
}

function regenerateCalendarExportFeed() {
    if (!calendarExportFeed || !calendarExportFeed.id) {
        createCalendarExportFeed();
        return;
    }

    apiPost(
        "/api/calendar/feeds/" + calendarExportFeed.id + "/token",
        {},
        function (feed) {
            calendarExportFeed = feed;
            $("#calendar-export-url").val(feed.feed_url || "");
            setCalendarExportStatus(
                "Subscription URL regenerated. The old URL no longer works.",
                false
            );
        }
    );
}

function copyCalendarExportUrl() {
    const value = $("#calendar-export-url").val() || "";

    if (!value) {
        setCalendarExportStatus("There is no URL to copy.", true);
        return;
    }

    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(value).then(function () {
            setCalendarExportStatus("Subscription URL copied.", false);
        });
        return;
    }

    $("#calendar-export-url").trigger("select");
    document.execCommand("copy");
    setCalendarExportStatus("Subscription URL copied.", false);
}

function closeCalendarExportModal() {
    closeAppModal("#calendar-export-modal");
    calendarExportFeed = null;
    $("#calendar-export-url").val("");
    setCalendarExportStatus("", false);
}
$(document).on("click", "#calendar-export", openCalendarExportModal);
$(document).on("click", "#create-calendar-export-feed", createCalendarExportFeed);
$(document).on("click", "#copy-calendar-export-url", copyCalendarExportUrl);
$(document).on("click", "#regenerate-calendar-export-url", regenerateCalendarExportFeed);
$(document).on("click", "#close-calendar-export-modal", closeCalendarExportModal);
$(document).on("click", "#close-calendar-export-modal-footer", closeCalendarExportModal);
function updateCalendarExportButtonVisibility() {
    const teamId = getCalendarExportTeamId();

    $("#calendar-export").toggleClass("is-hidden", !teamId);
}
$("#global-team-filter").on("change", function () {
    updateCalendarExportButtonVisibility();
});
