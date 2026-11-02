/* Each load invalidates previous responses, including after SPA navigation. */
let changesRequest = 0;
let changesListPath = "/changes";
let changesUid = null;
let changesServicePage = 1;
let changesEventPage = 1;

function changesText(key, values) {
    return i18n.t("changes." + key, values || {}, key);
}
function changesCell(value) {
    return $("<td>").text(value === null || value === undefined || value === "" ? "—" : value);
}
function changesEmpty(target, columns) {
    $(target)
        .empty()
        .append(
            $("<tr>").append(
                $("<td>")
                    .attr("colspan", columns)
                    .addClass("empty-table-cell")
                    .text(changesText("empty")),
            ),
        );
}
function changesActive(requestId) {
    return requestId === changesRequest && normalizeAppRoutePath(location.pathname) === "/changes";
}
function leaveChanges() {
    changesRequest += 1;
    changesUid = null;
    $(
        "#changes-rows, #changes-services, #changes-references, #changes-events, #changes-metadata",
    ).empty();
    $("#changes-detail-title, #changes-description, #changes-processing, #changes-message").text(
        "",
    );
    $("#changes-external").removeAttr("href").prop("hidden", true);
}
function changesFailure(xhr, requestId) {
    if (!changesActive(requestId)) return;
    changesRequest += 1;
    $("#changes-message").text(changesText(xhr.status === 404 ? "unavailable" : "load_error"));
    // Clear previously authorized content on every failed refresh.
    $(
        "#changes-rows, #changes-services, #changes-references, #changes-events, #changes-metadata",
    ).empty();
    $("#changes-detail").prop("hidden", true);
    $("#changes-detail-title, #changes-description, #changes-processing").text("");
    $("#changes-error-actions").prop("hidden", false);
    $("#changes-external").removeAttr("href").prop("hidden", true);
}
function changesPagination(prefix, pagination) {
    $(prefix + "-pagination").text(
        changesText("pagination", {
            page: pagination.page,
            pages: pagination.pages,
            count: pagination.total,
        }),
    );
    $(prefix + "-prev").prop("disabled", pagination.page <= 1);
    $(prefix + "-next").prop("disabled", pagination.page >= pagination.pages);
}
function loadChanges() {
    const requestId = ++changesRequest;
    const match = location.pathname.match(/^\/changes\/([0-9a-f-]{36})\/?$/i);
    changesUid = match ? match[1] : null;
    $("#changes-message").text(changesText("loading"));
    $("#changes-list").prop("hidden", !!changesUid);
    $("#changes-detail").prop("hidden", true);
    $("#changes-error-actions").prop("hidden", true);
    $(
        "#changes-rows, #changes-services, #changes-references, #changes-events, #changes-metadata",
    ).empty();
    $("#changes-external").removeAttr("href").prop("hidden", true);
    if (changesUid) {
        changesServicePage = changesEventPage = 1;
        apiGet(
            "/api/changes/" + changesUid,
            function (change) {
                if (!changesActive(requestId)) return;
                $("#changes-message").text("");
                renderChangeDetail(change);
                loadChangeServices(requestId);
                if (change.projection === "full") loadChangeEvents(requestId);
            },
            function (xhr) {
                changesFailure(xhr, requestId);
            },
        );
        return;
    }
    changesListPath = location.pathname + location.search;
    const params = new URLSearchParams(location.search);
    ["search", "status", "kind", "source", "environment"].forEach((key) =>
        $("#changes-" + key).val(params.get(key) || ""),
    );
    $("#changes-page-size").val(params.get("page_size") || "25");
    ["from", "to"].forEach((key) => {
        const raw = params.get("occurred_" + key);
        const date = raw ? new Date(raw) : null;
        const local =
            date && Number.isFinite(date.getTime())
                ? new Date(date.getTime() - date.getTimezoneOffset() * 60000)
                      .toISOString()
                      .slice(0, 16)
                : "";
        $("#changes-" + key).val(local);
    });
    loadChangeFilters(params, requestId);
    const apiParams = new URLSearchParams(params);
    const team = apiParams.get("team");
    apiParams.delete("team");
    if (team) apiParams.set("scope_team_id", team);
    apiGet(
        "/api/changes?" + apiParams.toString(),
        function (response) {
            if (!changesActive(requestId)) return;
            $("#changes-message").text("");
            const rows = $("#changes-rows").empty();
            response.items.forEach((change) => {
                const full = change.projection === "full";
                const title = full ? change.title : changesText("related");
                const link = $("<a>")
                    .addClass("changes-title-link")
                    .attr("href", "/changes/" + change.uid)
                    .text(title);
                const context = full
                    ? [changesText(change.kind), change.environment].filter(Boolean).join(" · ")
                    : change.services.map((item) => item.service.name).join(", ");
                const cell = $("<td>").append(
                    link,
                    $("<small>").addClass("muted changes-row-context").text(context),
                );
                const status = full
                    ? changesText(change.lifecycle_conflict ? "conflict_short" : change.status)
                    : changesText("limited_short");
                const mapping = full
                    ? changesText(
                          change.processing.state === "dead"
                              ? "dead"
                              : !change.processing.current
                                ? "processing"
                                : change.mapping_status,
                      )
                    : "—";
                rows.append(
                    $("<tr>").append(
                        cell,
                        changesCell(status),
                        changesCell(full ? change.owner_team.name : null),
                        changesCell(full ? change.source : null),
                        changesCell(mapping),
                        changesCell(formatDateTimeMinutes(change.occurred_at)),
                    ),
                );
            });
            if (!response.items.length) changesEmpty("#changes-rows", 6);
            changesPagination("#changes", response.pagination);
        },
        function (xhr) {
            changesFailure(xhr, requestId);
        },
    );
}
function loadChangeFilters(params, requestId) {
    [
        ["team", "/api/teams", "owner_team_id", "all_teams"],
        ["service", "/api/services", "service_id", "all_services"],
    ].forEach(([field, endpoint, key, empty]) => {
        const select = $("#changes-" + field)
            .empty()
            .append($("<option>").val("").text(changesText(empty)))
            .prop("disabled", true);
        apiGet(
            endpoint,
            function (response) {
                if (!changesActive(requestId)) return;
                const items = Array.isArray(response) ? response : response.items || [];
                const readable = items.filter(
                    (item) => field !== "team" || item.permissions?.can_read,
                );
                readable.forEach((item) =>
                    select.append(
                        $("<option>")
                            .val(item.id)
                            .text(item.name + (item.slug ? " (" + item.slug + ")" : "")),
                    ),
                );
                select.val(params.get(key) || "").prop("disabled", false);
            },
            function () {
                if (changesActive(requestId))
                    $("#changes-message").text(changesText("filter_error"));
            },
        );
    });
}
function changesApply(page) {
    if ($("#changes-team, #changes-service").is(":disabled")) {
        $("#changes-message").text(changesText("filter_error"));
        return;
    }
    const params = new URLSearchParams();
    const team = new URLSearchParams(location.search).get("team");
    if (team) params.set("team", team);
    ["search", "status", "kind", "source", "environment"].forEach((key) => {
        const value = String($("#changes-" + key).val() || "").trim();
        if (value) params.set(key, value);
    });
    [
        ["team", "owner_team_id"],
        ["service", "service_id"],
    ].forEach(([field, key]) => {
        const value = $("#changes-" + field).val();
        if (value) params.set(key, value);
    });
    ["from", "to"].forEach((key) => {
        const value = $("#changes-" + key).val();
        if (value) params.set("occurred_" + key, new Date(value).toISOString());
    });
    params.set("page_size", $("#changes-page-size").val() || "25");
    params.set("page", String(page || 1));
    navigate("/changes?" + params.toString(), true);
}
function changeMetadata(label, value) {
    if (value === null || value === undefined || value === "") return;
    $("#changes-metadata").append(
        $("<div>")
            .addClass("form-group")
            .append($("<label>").text(changesText(label)), $("<div>").text(value)),
    );
}
function renderChangeDetail(change) {
    const full = change.projection === "full";
    $("#changes-detail").prop("hidden", false);
    $("#changes-detail-title").text(full ? change.title : changesText("related"));
    $("#changes-limited").prop("hidden", full);
    $("#changes-conflict").prop("hidden", !change.lifecycle_conflict);
    $("#changes-events-panel, #changes-references-panel").prop("hidden", !full);
    $("#changes-description").text(full ? change.description || "" : "");
    $("#changes-processing").text(
        full
            ? changesText(
                  change.processing.state === "dead"
                      ? "dead"
                      : change.processing.current
                        ? "mapping_current"
                        : "processing",
              )
            : "",
    );
    changeMetadata("kind", changesText(change.kind));
    changeMetadata("occurred", formatDateTimeMinutes(change.occurred_at));
    if (!full) return;
    changeMetadata("status", changesText(change.status));
    changeMetadata("owner", change.owner_team.name);
    changeMetadata("source", change.source);
    changeMetadata("environment", change.environment);
    changeMetadata("change_id", change.change_id);
    changeMetadata("mapping", changesText(change.mapping_status));
    changeMetadata("pending", change.reference_counts.pending_resolution || 0);
    if (change.external_url) {
        try {
            const url = new URL(change.external_url);
            if (["https:", "http:"].includes(url.protocol) && !url.username && !url.password)
                $("#changes-external").attr("href", url.href).prop("hidden", false);
        } catch (error) {
            /* Invalid external URLs are displayed only in event text. */
        }
    }
}
function loadChangeServices(requestId) {
    const page = changesServicePage;
    $("#changes-services, #changes-references").empty();
    apiGet(
        "/api/changes/" + changesUid + "/services?page=" + page,
        function (response) {
            if (!changesActive(requestId) || page !== changesServicePage) return;
            response.items.forEach((item) =>
                $("#changes-services").append(
                    $("<tr>").append(
                        changesCell(item.service.name + " (" + item.service.slug + ")"),
                        changesCell(changesText(item.relation_type)),
                        changesCell(
                            item.verification_state ? changesText(item.verification_state) : null,
                        ),
                    ),
                ),
            );
            if (!response.items.length) changesEmpty("#changes-services", 3);
            if (response.references) {
                response.references.items.forEach((ref) =>
                    $("#changes-references").append(
                        $("<tr>").append(
                            changesCell(ref.requested_service_slug || ref.requested_service_id),
                            changesCell(changesText(ref.relation_type)),
                            changesCell(changesText(ref.resolution_status)),
                        ),
                    ),
                );
                if (!response.references.items.length) changesEmpty("#changes-references", 3);
            }
            const pagination = { ...response.pagination };
            if (response.references) {
                pagination.pages = Math.max(pagination.pages, response.references.pagination.pages);
                pagination.total += response.references.pagination.total;
            }
            changesPagination("#changes-services", pagination);
        },
        function (xhr) {
            if (page === changesServicePage) changesFailure(xhr, requestId);
        },
    );
}
function loadChangeEvents(requestId) {
    const page = changesEventPage;
    $("#changes-events").empty();
    apiGet(
        "/api/changes/" + changesUid + "/events?page=" + page,
        function (response) {
            if (!changesActive(requestId) || page !== changesEventPage) return;
            response.items.forEach((event) => {
                const details = $("<details>").append(
                    $("<summary>").text(changesText("details")),
                    $("<pre>").text(
                        JSON.stringify(
                            {
                                event_id: event.event_id,
                                received_at: event.received_at,
                                sequence: event.source_sequence,
                                fields: event.fields,
                                details: event.details,
                            },
                            null,
                            2,
                        ),
                    ),
                );
                $("#changes-events").append(
                    $("<tr>").append(
                        changesCell(changesText(event.event_type.replace("change.", ""))),
                        changesCell(formatDateTimeMinutes(event.occurred_at)),
                        changesCell(event.actor.name),
                        $("<td>").append(details),
                    ),
                );
            });
            if (!response.items.length) changesEmpty("#changes-events", 4);
            changesPagination("#changes-events", response.pagination);
        },
        function (xhr) {
            if (page === changesEventPage) changesFailure(xhr, requestId);
        },
    );
}
$(document).on("submit", "#changes-filters", function (event) {
    event.preventDefault();
    changesApply(1);
});
$(document).on("click", ".changes-reload", loadChanges);
$(document).on("click", "#changes-reset", function () {
    navigate(appUrlWithGlobalTeamScope("/changes"), true);
});
$(document).on("click", "#changes-back, #changes-error-back", function () {
    navigate(changesListPath, true);
});
$(document).on("click", ".changes-title-link", function (event) {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    navigate($(this).attr("href"), true);
});
$(document).on("change", "#changes-page-size", function () {
    const params = new URLSearchParams(location.search);
    params.set("page_size", $(this).val());
    params.set("page", "1");
    navigate("/changes?" + params.toString(), true);
});
$(document).on("click", "#changes-prev, #changes-next", function () {
    const params = new URLSearchParams(location.search);
    const page = Number(params.get("page") || 1);
    params.set("page", String(page + (this.id === "changes-next" ? 1 : -1)));
    navigate("/changes?" + params.toString(), true);
});
$(document).on("click", "#changes-services-prev, #changes-services-next", function () {
    changesServicePage += this.id.endsWith("next") ? 1 : -1;
    loadChangeServices(changesRequest);
});
$(document).on("click", "#changes-events-prev, #changes-events-next", function () {
    changesEventPage += this.id.endsWith("next") ? 1 : -1;
    loadChangeEvents(changesRequest);
});
