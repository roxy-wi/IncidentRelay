function loadCalendar() {
    /* Load calendar page data. */
    const today = new Date();
    const end = new Date();
    end.setDate(today.getDate() + 30);
    if (!$("#calendar-start").val()) { $("#calendar-start").val(today.toISOString().slice(0, 10)); }
    if (!$("#calendar-end").val()) { $("#calendar-end").val(end.toISOString().slice(0, 10)); }
    refreshCalendar();
}

function refreshCalendar() {
    /* Refresh calendar events. */
    const teamId = selectedTeamId();
    if (!teamId) { $("#calendar-grid").html("<p>Select a team.</p>"); return; }
    apiGet("/api/calendar?team_id=" + teamId + "&start=" + $("#calendar-start").val() + "&end=" + $("#calendar-end").val(), renderCalendar);
}

function renderCalendar(events) {
    /* Render calendar events grouped by day. */
    const byDay = {};
    events.forEach(function (event) {
        const day = event.start.slice(0, 10);
        if (!byDay[day]) { byDay[day] = []; }
        byDay[day].push(event);
    });
    const grid = $("#calendar-grid");
    grid.empty();
    Object.keys(byDay).sort().forEach(function (day) {
        const cell = $("<div>").addClass("calendar-day");
        cell.append($("<div>").addClass("calendar-date").text(day));
        byDay[day].forEach(function (event) {
            cell.append($("<div>").addClass("calendar-event " + event.type).text(event.rotation_name + ": " + event.username + " (" + event.type + ")"));
        });
        grid.append(cell);
    });
}

$(document).on("click", "#reload-calendar", refreshCalendar);
