/* Each load invalidates previous responses, including after SPA navigation. */
let changesRequest = 0;
let changesUid = null;
let changesServicePage = 1;
let changesReferencePage = 1;
let changesEventPage = 1;
const changesServiceRequests = {services: 0, references: 0};

function changesText(key, values) {
    return i18n.t("changes." + key, values || {}, key);
}
function changesKindIcon(kind) {
    const icons = {
        deployment: "fa-rocket",
        configuration: "fa-sliders-h",
        infrastructure: "fa-server",
        database: "fa-database",
        feature_flag: "fa-flag",
        other: "fa-exchange-alt",
    };
    const knownKind = Object.prototype.hasOwnProperty.call(icons, kind) ? kind : "other";
    const label = changesText(knownKind);
    return $("<span>")
        .addClass("changes-kind-icon")
        .attr({
            "data-kind": knownKind,
            role: "img",
            "aria-label": label,
            title: label,
        })
        .append($("<i>").addClass("fas " + icons[knownKind]).attr("aria-hidden", "true"));
}
function changesCell(value) {
    return $("<td>").text(value === null || value === undefined || value === "" ? "—" : value);
}
function changesBadge(value) {
    if (!value) return $("<span>").text("—");
    const tones = {
        succeeded: "success", resolved: "success", trusted: "success", confirmed: "success", active_link: "success",
        failed: "danger", rejected: "danger", denied: "danger", invalid: "danger", dead: "danger", conflict_short: "danger",
        running: "info", changed: "info", context: "info", confirmed_cause: "danger",
        suggested: "warning", potential_cause: "warning", pending_resolution: "warning", unverified: "warning",
        reported_affected: "accent", inferred_impact: "accent", mitigation: "success", rolled_back: "accent", stale_suggestion: "warning",
    };
    return uiStatusBadge(changesText(value), tones[value] || "muted");
}
function changesBadgeCell(value) {
    return $("<td>").append(changesBadge(value));
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
    clearChangeReviews();
    changesRequest += 1;
    changesUid = null;
    $(
        "#changes-rows, #changes-services, #changes-references, #changes-events, #changes-metadata",
    ).empty();
    $(
        "#changes-detail-title, #changes-description, #changes-processing, #changes-message, #changes-filter-message",
    ).text("");
    $("#changes-external").removeAttr("href").prop("hidden", true);
}
function changesFailure(xhr, requestId) {
    if (!changesActive(requestId)) return;
    clearChangeReviews();
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
function changesPagination(prefix, pagination, section) {
    const pages = Math.max(1, pagination.pages);
    $(prefix + "-pagination").text(
        changesText(section ? (pages > 1 ? "section_pagination" : "section_count") : "pagination", {
            section: section ? changesText(section) : "",
            page: pagination.page,
            pages,
            count: pagination.total,
        }),
    );
    $(prefix + "-prev").prop("disabled", pagination.page <= 1);
    $(prefix + "-next").prop("disabled", pagination.page >= pagination.pages);
    if (section) $(prefix + "-next").parent().prop("hidden", pages <= 1);
}
function loadChanges() {
    clearChangeReviews();
    const requestId = ++changesRequest;
    const match = location.pathname.match(/^\/changes\/([0-9a-f-]{36})\/?$/i);
    changesUid = match ? match[1] : null;
    $("#changes-message").text(changesText("loading"));
    $("#changes-filter-message").text("");
    $("#changes-list").prop("hidden", !!changesUid);
    $("#changes-detail").prop("hidden", true);
    $("#changes-error-actions").prop("hidden", true);
    $(
        "#changes-rows, #changes-services, #changes-references, #changes-events, #changes-metadata",
    ).empty();
    $("#changes-external").removeAttr("href").prop("hidden", true);
    if (changesUid) {
        changesServicePage = changesReferencePage = changesEventPage = 1;
        apiGet(
            "/api/changes/" + changesUid,
            function (change) {
                if (!changesActive(requestId)) return;
                $("#changes-message").text("");
                renderChangeDetail(change);
                loadChangeReviews(requestId);
                loadChangeServices(requestId);
                if (change.projection === "full") loadChangeEvents(requestId);
            },
            function (xhr) {
                changesFailure(xhr, requestId);
            },
        );
        return;
    }
    const params = new URLSearchParams(location.search);
    // Old Inbox links used a separate owner selector. Use the global Team filter.
    if (params.has("owner_team_id")) {
        if (!params.has("team")) params.set("team", params.get("owner_team_id"));
        params.delete("owner_team_id");
        navigate("/changes?" + params.toString(), true);
        return;
    }
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
                    $("<div>").addClass("changes-row-heading").append(
                        changesKindIcon(change.kind),
                        $("<div>").addClass("changes-row-text").append(
                            link,
                            $("<small>").addClass("muted changes-row-context").text(context),
                        ),
                    ),
                );
                const status = full
                    ? (change.lifecycle_conflict ? "conflict_short" : change.status)
                    : "limited_short";
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
                        changesBadgeCell(status),
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
        ["source", "/api/changes/sources", "source", "all_sources"],
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
                items.forEach((item) =>
                    select.append(
                        $("<option>")
                            .val(field === "source" ? item : item.id)
                            .text(
                                field === "source"
                                    ? item
                                    : item.name + (item.slug ? " (" + item.slug + ")" : ""),
                            ),
                    ),
                );
                const selected = params.get(key) || "";
                // Keep a bookmarked source filter even after its catalog entry disappears.
                if (field === "source" && selected && !items.includes(selected))
                    select.append($("<option>").val(selected).text(selected));
                select.val(selected).prop("disabled", false);
            },
            function () {
                if (changesActive(requestId))
                    $("#changes-filter-message").text(changesText("filter_error"));
            },
        );
    });
}
function changesApply(page) {
    if ($("#changes-source, #changes-service").is(":disabled")) {
        $("#changes-filter-message").text(changesText("filter_error"));
        return;
    }
    const params = new URLSearchParams();
    const team = new URLSearchParams(location.search).get("team");
    if (team) params.set("team", team);
    ["search", "status", "kind", "source", "environment"].forEach((key) => {
        const value = String($("#changes-" + key).val() || "").trim();
        if (value) params.set(key, value);
    });
    const service = $("#changes-service").val();
    if (service) params.set("service_id", service);
    ["from", "to"].forEach((key) => {
        const value = $("#changes-" + key).val();
        if (value) params.set("occurred_" + key, new Date(value).toISOString());
    });
    params.set("page_size", $("#changes-page-size").val() || "25");
    params.set("page", String(page || 1));
    navigate("/changes?" + params.toString(), true);
}
function changeMetadata(label, value, badge) {
    if (value === null || value === undefined || value === "") return;
    $("#changes-metadata").append(
        $("<div>")
            .addClass("form-group")
            .append($("<label>").text(changesText(label)), $("<div>").append(badge ? changesBadge(value) : document.createTextNode(value))),
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
    changeMetadata("status", change.lifecycle_conflict ? "conflict_short" : change.status, true);
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
function loadChangeServices(requestId, collection) {
    // The API returns two independently counted collections. Initial loading
    // shares one request; navigating either table leaves the other one intact.
    const collections = collection ? [collection] : ["services", "references"];
    const page = collection === "references" ? changesReferencePage : changesServicePage;
    const generations = {};
    collections.forEach(function (kind) {
        generations[kind] = ++changesServiceRequests[kind];
        $("#changes-" + kind).empty();
    });
    apiGet(
        "/api/changes/" + changesUid + "/services?page=" + page,
        function (response) {
            if (!changesActive(requestId)) return;
            collections.forEach(function (kind) {
                if (generations[kind] !== changesServiceRequests[kind]) return;
                const result = kind === "services" ? response : response.references;
                if (!result) return;
                const target = "#changes-" + kind;
                result.items.forEach(function (item) {
                    const service = item.service;
                    const label = service ? service.name + " (" + service.slug + ")"
                        : item.requested_service_slug || changesText("service_id", {id: item.requested_service_id});
                    $(target).append(
                        $("<tr>").append(
                            changesCell(label),
                            changesBadgeCell(item.relation_type),
                            changesBadgeCell(kind === "services" ? item.verification_state : item.resolution_status),
                        ),
                    );
                });
                if (!result.items.length) changesEmpty(target, 3);
                changesPagination(target, result.pagination, kind);
            });
        },
        function (xhr) {
            if (collections.some((kind) => generations[kind] === changesServiceRequests[kind])) changesFailure(xhr, requestId);
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
                        changesBadgeCell(event.event_type.replace("change.", "")),
                        changesCell(formatDateTimeMinutes(event.occurred_at)),
                        changesCell(event.actor.name),
                        $("<td>").append(details),
                    ),
                );
            });
            if (!response.items.length) changesEmpty("#changes-events", 4);
            changesPagination("#changes-events", response.pagination, "events");
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
    loadChangeServices(changesRequest, "services");
});
$(document).on("click", "#changes-references-prev, #changes-references-next", function () {
    changesReferencePage += this.id.endsWith("next") ? 1 : -1;
    loadChangeServices(changesRequest, "references");
});
$(document).on("click", "#changes-events-prev, #changes-events-next", function () {
    changesEventPage += this.id.endsWith("next") ? 1 : -1;
    loadChangeEvents(changesRequest);
});
