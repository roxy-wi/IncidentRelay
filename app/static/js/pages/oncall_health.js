(function () {
    "use strict";

    const MODAL_ID = "#rotation-health-modal";
    const HEALTH_CSS_ID = "oncall-health-css";
    const SUMMARY_DEBOUNCE_MS = 120;
    const SUMMARY_ENDPOINT = "/api/oncall-health/rotations/summaries";
    const DETAIL_ENDPOINT_PREFIX = "/api/oncall-health/rotations/";
    const TEAM_SUMMARY_ENDPOINT = "/api/oncall-health/teams/summaries";
    const TEAM_DETAIL_ENDPOINT_PREFIX = "/api/oncall-health/teams/";

    let pendingSummaryIds = new Set();
    let loadingSummaryIds = new Set();
    let rotationHealthSummaryCache = new Map();
    let summaryTimer = null;
    let syncScheduled = false;
    let syncingRows = false;
    let tableObserver = null;

    function asArray(value) {
        return Array.isArray(value) ? value : [];
    }

    function healthT(key, params, fallback) {
        if (window.i18n && typeof window.i18n.t === "function") {
            return window.i18n.t(key, params || {}, fallback || key);
        }
        return fallback || key;
    }

    function localizedHealthStatus(status) {
        const value = status || "unknown";
        return healthT(
            `oncall_health.status.${value}`,
            {},
            value
        );
    }

    function localizedIssueText(issue, field, fallback) {
        const code = issue && issue.code ? issue.code : "";
        if (!code) {
            return fallback || "";
        }
        return healthT(
            `oncall_health.issues.${code}.${field}`,
            {
                username: issue.username || "",
                rotation: issue.rotation_name || "",
                layer: issue.layer_name || "",
            },
            fallback || ""
        );
    }

    function loadOncallHealthCss() {
        if (document.getElementById(HEALTH_CSS_ID)) {
            return;
        }

        const link = document.createElement("link");
        link.id = HEALTH_CSS_ID;
        link.rel = "stylesheet";
        link.href = "/static/css/oncall_health.css";
        document.head.appendChild(link);
    }

    function getHealthStatus(health) {
        return health && health.status ? health.status : "unknown";
    }

    function healthIcon(status) {
        if (status === "critical") {
            return "×";
        }
        if (status === "warning") {
            return "!";
        }
        if (status === "ok") {
            return "✓";
        }
        return "?";
    }

    function healthLabel(health) {
        if (!health) {
            return healthT("oncall_health.indicator.loading", {}, "Health status is loading. Click to open diagnostics.");
        }

        if (health.status === "unknown") {
            return healthT("oncall_health.indicator.unknown", {}, "Health status is unknown. Click to open diagnostics.");
        }

        if (health.status === "ok") {
            return healthT("oncall_health.indicator.ok", {}, "OK · click to open diagnostics");
        }

        return healthT("oncall_health.indicator.counts", {
            critical: health.critical || 0,
            warning: health.warning || 0,
            info: health.info || 0,
        }, `Critical: ${health.critical || 0} · Warnings: ${health.warning || 0} · Info: ${health.info || 0}`);
    }

    function ensureRotationHealthModal() {
        if ($(MODAL_ID).length) {
            return;
        }

        const modal = $(
            `<div class="app-modal oncall-health-modal" id="rotation-health-modal" style="display: none;">
                <div class="app-modal-card app-modal-wide">
                    <div class="app-modal-header">
                        <div>
                            <h2 id="rotation-health-title">${healthT("oncall_health.title.rotation", {}, "On-call health")}</h2>
                            <p id="rotation-health-subtitle" class="muted"></p>
                        </div>
                        <button type="button" class="modal-close" data-oncall-health-close="1" aria-label="${healthT("oncall_health.close", {}, "Close")}">×</button>
                    </div>
                    <div class="app-modal-body">
                        <div id="rotation-health-window" class="oncall-health-window muted"></div>
                        <div id="rotation-health-summary" class="oncall-health-summary-grid"></div>
                        <div id="rotation-health-issues" class="oncall-health-issues-list"></div>
                    </div>
                    <div class="app-modal-footer">
                        <button type="button" class="btn" data-oncall-health-close="1">${healthT("oncall_health.close", {}, "Close")}</button>
                    </div>
                </div>
            </div>`
        );

        modal.on("click", "[data-oncall-health-close]", function () {
            closeRotationHealthModal();
        });
        modal.on("click", function (event) {
            if (event.target === modal[0]) {
                closeRotationHealthModal();
            }
        });

        $(document.body).append(modal);
    }

    function openRotationHealthModalElement() {
        ensureRotationHealthModal();
        if (typeof window.openAppModal === "function") {
            window.openAppModal(MODAL_ID);
        } else {
            $(MODAL_ID).show().addClass("is-open");
        }
    }

    function closeRotationHealthModal() {
        if (typeof window.closeAppModal === "function") {
            window.closeAppModal(MODAL_ID);
        } else {
            $(MODAL_ID).hide().removeClass("is-open");
        }
    }

    function renderOncallHealthIndicator(health, rotationId) {
        const status = getHealthStatus(health);
        const label = healthLabel(health);

        return $("<button>")
            .attr("type", "button")
            .attr("title", label)
            .attr("aria-label", healthT("oncall_health.indicator.open_rotation", {label: label}, `Open on-call health details. ${label}`))
            .attr("data-rotation-health-open", rotationId || "")
            .addClass("oncall-health-indicator")
            .addClass(`oncall-health-${status}`)
            .text(healthIcon(status));
    }

    function getRotationsTable() {
        return $("#rotations-table").closest("table");
    }

    function getRotationsTbody() {
        return $("#rotations-table");
    }

    function ensureRotationHealthColumn() {
        const table = getRotationsTable();
        if (!table.length) {
            return;
        }

        const headerRow = table.find("thead tr").first();
        if (!headerRow.length) {
            return;
        }

        const existing = headerRow.find("th.oncall-health-th");
        if (!existing.length) {
            const statusText = healthT("rotations.table.status", {}, "Status").trim().toLowerCase();
            const statusHeader = headerRow.find("th").filter(function () {
                return $(this).text().trim().toLowerCase() === statusText;
            }).first();

            const healthHeader = $("<th>")
                .addClass("oncall-health-th")
                .text(healthT("oncall_health.table.health", {}, "Health"));

            if (statusHeader.length) {
                statusHeader.before(healthHeader);
            } else {
                const actionsHeader = headerRow.find("th").filter(function () {
                    const actionsText = healthT("rotations.table.actions", {}, "Actions").trim().toLowerCase();
                    return $(this).text().trim().toLowerCase() === actionsText || $(this).hasClass("actions-th");
                }).first();
                if (actionsHeader.length) {
                    actionsHeader.before(healthHeader);
                } else {
                    headerRow.append(healthHeader);
                }
            }
        }

        getRotationsTbody().find("td[colspan='8']").attr("colspan", "9");
    }

    function getVisibleRotations() {
        if (typeof window.getFilteredRotations === "function") {
            return asArray(window.getFilteredRotations());
        }
        if (Array.isArray(window.rotationsCache)) {
            return window.rotationsCache;
        }
        return [];
    }

    function findHealthInsertIndex(row) {
        const cells = row.children("td");
        // Current table order before Health is:
        // Name, Team, Cadence, Current on call, Handoff, Reminder, Status, Actions.
        // Insert before Status, so index 6. If another column was already added,
        // this still keeps the health cell before the runtime status/action area.
        if (cells.length >= 7) {
            return 6;
        }
        return cells.length;
    }

    function updateHealthCell(cell, rotation) {
        const rotationId = rotation && rotation.id
            ? String(rotation.id)
            : "";

        const currentId = String(
            cell.attr("data-rotation-health-id") || ""
        );

        cell
            .addClass("oncall-health-cell")
            .attr("data-rotation-health-id", rotationId);

        if (!rotationId) {
            cell.empty().append(
                renderOncallHealthIndicator(null, "")
            );
            return;
        }

        let summary = rotationHealthSummaryCache.get(rotationId) || null;

        if (!summary && rotation && rotation.health) {
            summary = rotation.health;
            rotationHealthSummaryCache.set(rotationId, summary);
        }

        if (
            currentId !== rotationId
            || !cell.find(".oncall-health-indicator").length
            || summary
        ) {
            cell
                .empty()
                .append(
                    renderOncallHealthIndicator(summary, rotationId)
                );
        }

        if (
            !summary
            && !loadingSummaryIds.has(rotationId)
        ) {
            queueRotationHealthSummary(rotationId);
        }
    }

    function syncRotationHealthRows() {
        const tbody = getRotationsTbody();
        if (!tbody.length || syncingRows) {
            return;
        }

        syncingRows = true;
        try {
            ensureRotationHealthColumn();

            const rotations = getVisibleRotations();
            const rows = tbody.children("tr").filter(function () {
                return !$(this).find("td.empty-cell").length;
            });

            rows.each(function (index) {
                const rotation = rotations[index];
                if (!rotation || !rotation.id) {
                    return;
                }

                const row = $(this);
                let healthCell = row.children("td.oncall-health-cell").first();
                if (!healthCell.length) {
                    healthCell = $("<td>").addClass("oncall-health-cell");
                    const insertIndex = findHealthInsertIndex(row);
                    const cells = row.children("td");
                    if (insertIndex >= cells.length) {
                        row.append(healthCell);
                    } else {
                        cells.eq(insertIndex).before(healthCell);
                    }
                }

                updateHealthCell(healthCell, rotation);
            });
        } finally {
            syncingRows = false;
        }
    }

    function scheduleSyncRotationHealthRows() {
        if (syncScheduled) {
            return;
        }
        syncScheduled = true;
        window.setTimeout(function () {
            syncScheduled = false;
            syncRotationHealthRows();
        }, 0);
    }

    function updateRotationHealthSummary(rotationId, summary) {
        const id = String(rotationId || "");

        if (!id) {
            return;
        }

        rotationHealthSummaryCache.set(id, summary);

        const selector =
            `td.oncall-health-cell[data-rotation-health-id="${id}"]`;

        $(selector).each(function () {
            $(this)
                .empty()
                .append(
                    renderOncallHealthIndicator(summary, id)
                );
        });
    }

    function markRotationHealthFailed(rotationId, message) {
        updateRotationHealthSummary(rotationId, {
            status: "unknown",
            critical: 0,
            warning: 0,
            info: 0,
            total: 0,
            tooltip: message || healthT("oncall_health.errors.summary_failed", {}, "Health summary failed to load."),
        });
    }

    function flushRotationHealthSummaryQueue() {
        summaryTimer = null;

        const ids = Array.from(pendingSummaryIds)
            .filter(function (id) {
                return id
                    && !loadingSummaryIds.has(id)
                    && !rotationHealthSummaryCache.has(id);
            });

        pendingSummaryIds = new Set();
        if (!ids.length) {
            return;
        }

        ids.forEach(function (id) {
            loadingSummaryIds.add(id);
        });

        const params = new URLSearchParams();
        ids.forEach(function (id) {
            params.append("rotation_id", id);
        });

        $.ajax({
            url: `${SUMMARY_ENDPOINT}?${params.toString()}`,
            method: "GET",
            dataType: "json",
        }).done(function (payload) {
            const byId = payload && payload.by_id ? payload.by_id : {};
            ids.forEach(function (id) {
                loadingSummaryIds.delete(id);
                const summary = byId[String(id)];
                if (summary) {
                    updateRotationHealthSummary(id, summary);
                } else {
                    markRotationHealthFailed(id, healthT("oncall_health.errors.summary_missing_rotation", {}, "Health summary was not returned for this rotation."));
                }
            });
        }).fail(function (xhr) {
            const message = xhr.responseJSON && (xhr.responseJSON.message || xhr.responseJSON.error)
                ? (xhr.responseJSON.message || xhr.responseJSON.error)
                : healthT("oncall_health.errors.summary_failed", {}, "Health summary failed to load.");
            ids.forEach(function (id) {
                loadingSummaryIds.delete(id);
                markRotationHealthFailed(id, message);
            });
        });
    }

    function queueRotationHealthSummary(rotationId) {
        const id = String(rotationId || "");

        if (!id) {
            return;
        }

        if (
            loadingSummaryIds.has(id)
            || rotationHealthSummaryCache.has(id)
        ) {
            return;
        }

        pendingSummaryIds.add(id);
    }

    function renderSummaryCard(label, value, className) {
        const card = $("<div>")
            .addClass("oncall-health-summary-card")
            .addClass(className || "");

        $("<div>")
            .addClass("oncall-health-summary-label")
            .text(label)
            .appendTo(card);

        $("<div>")
            .addClass("oncall-health-summary-value")
            .text(value === undefined || value === null ? 0 : value)
            .appendTo(card);

        return card;
    }

    function formatDateTime(value) {
        if (!value) {
            return "";
        }
        try {
            return new Date(value).toLocaleString();
        } catch (error) {
            return value;
        }
    }

    function issueTimeRange(issue) {
        if (!issue.starts_at && !issue.ends_at) {
            return "";
        }
        if (issue.starts_at && issue.ends_at) {
            return `${formatDateTime(issue.starts_at)} — ${formatDateTime(issue.ends_at)}`;
        }
        return formatDateTime(issue.starts_at || issue.ends_at);
    }

    function renderIssue(issue) {
        const severity = issue.severity || "info";
        const title = localizedIssueText(issue, "title", issue.title || issue.code || healthT("oncall_health.issue.default", {}, "Health issue"));

        const card = $("<div>")
            .addClass("oncall-health-issue")
            .addClass(`oncall-health-issue-${severity}`);

        const header = $("<div>")
            .addClass("oncall-health-issue-header")
            .appendTo(card);

        $("<span>")
            .addClass("oncall-health-issue-badge")
            .text(localizedHealthStatus(severity))
            .appendTo(header);

        $("<span>")
            .addClass("oncall-health-issue-title")
            .text(title)
            .appendTo(header);

        if (issue.message) {
            $("<p>")
                .addClass("oncall-health-issue-message")
                .text(localizedIssueText(issue, "message", issue.message))
                .appendTo(card);
        }

        const metaItems = [];

        if (issue.rotation_name) {
            metaItems.push(healthT("oncall_health.issue.rotation", {name: issue.rotation_name}, `Rotation: ${issue.rotation_name}`));
        }
        if (issue.layer_name) {
            metaItems.push(healthT("oncall_health.issue.layer", {name: issue.layer_name}, `Layer: ${issue.layer_name}`));
        }
        if (issue.username) {
            metaItems.push(healthT("oncall_health.issue.user", {name: issue.username}, `User: ${issue.username}`));
        }

        const range = issueTimeRange(issue);
        if (range) {
            metaItems.push(range);
        }

        if (metaItems.length) {
            $("<div>")
                .addClass("oncall-health-issue-meta")
                .text(metaItems.join(" · "))
                .appendTo(card);
        }

        if (issue.hint) {
            $("<div>")
                .addClass("oncall-health-issue-recommendation")
                .text(localizedIssueText(issue, "hint", issue.hint))
                .appendTo(card);
        }

        return card;
    }

    function renderIssueGroup(container, title, issues) {
        if (!issues.length) {
            return;
        }

        const section = $("<section>")
            .addClass("oncall-health-section")
            .appendTo(container);

        $("<h3>")
            .addClass("oncall-health-section-title")
            .text(title)
            .appendTo(section);

        const list = $("<div>")
            .addClass("oncall-health-issues-list")
            .appendTo(section);

        issues.forEach(function (issue) {
            list.append(renderIssue(issue));
        });
    }

    function renderRotationHealthModal(payload) {
        ensureRotationHealthModal();

        const summary = payload.summary || {};
        const issues = payload.issues || [];
        const title = payload.rotation_name
            ? healthT("oncall_health.title.rotation_named", {name: payload.rotation_name}, `On-call health: ${payload.rotation_name}`)
            : healthT("oncall_health.title.rotation", {}, "On-call health");
        const subtitle = payload.team_name || payload.team_slug
            ? healthT("oncall_health.team_label", {name: payload.team_name || payload.team_slug}, `Team: ${payload.team_name || payload.team_slug}`)
            : "";

        if (payload.rotation_id) {
            updateRotationHealthSummary(payload.rotation_id, summary);
        }

        $("#rotation-health-title").text(title);
        $("#rotation-health-subtitle").text(subtitle);

        const startsAt = payload.window && payload.window.starts_at;
        const endsAt = payload.window && payload.window.ends_at;
        $("#rotation-health-window").text(
            startsAt && endsAt
                ? healthT("oncall_health.window", {
                    start: formatDateTime(startsAt),
                    end: formatDateTime(endsAt),
                }, `Checked window: ${formatDateTime(startsAt)} — ${formatDateTime(endsAt)}`)
                : ""
        );

        const summaryEl = $("#rotation-health-summary").empty();
        summaryEl.append(renderSummaryCard(healthT("oncall_health.summary.status", {}, "Status"), localizedHealthStatus(summary.status || "unknown"), `oncall-health-summary-card-${summary.status || "unknown"}`));
        summaryEl.append(renderSummaryCard(healthT("oncall_health.summary.critical", {}, "Critical"), summary.critical, "oncall-health-summary-card-critical"));
        summaryEl.append(renderSummaryCard(healthT("oncall_health.summary.warning", {}, "Warnings"), summary.warning, "oncall-health-summary-card-warning"));
        summaryEl.append(renderSummaryCard(healthT("oncall_health.summary.info", {}, "Info"), summary.info, "oncall-health-summary-card-info"));

        const issuesEl = $("#rotation-health-issues").empty();
        if (!issues.length) {
            issuesEl.append(
                $("<div>")
                    .addClass("oncall-health-empty")
                    .text(healthT("oncall_health.empty.rotation", {}, "No on-call health issues were found for this rotation."))
            );
            return;
        }

        renderIssueGroup(issuesEl, healthT("oncall_health.summary.critical", {}, "Critical"), issues.filter((item) => item.severity === "critical"));
        renderIssueGroup(issuesEl, healthT("oncall_health.summary.warning", {}, "Warnings"), issues.filter((item) => item.severity === "warning"));
        renderIssueGroup(issuesEl, healthT("oncall_health.summary.info", {}, "Info"), issues.filter((item) => item.severity === "info"));
    }

    function openRotationHealthModal(rotationId) {
        if (!rotationId) {
            if (typeof window.showAppError === "function") {
                window.showAppError(healthT("oncall_health.errors.rotation_id_missing", {}, "Rotation id was not found for this health indicator."));
            }
            return;
        }

        ensureRotationHealthModal();
        openRotationHealthModalElement();
        $("#rotation-health-title").text(healthT("oncall_health.title.rotation", {}, "On-call health"));
        $("#rotation-health-subtitle").text(healthT("oncall_health.loading", {}, "Loading..."));
        $("#rotation-health-window").text("");
        $("#rotation-health-summary").empty();
        $("#rotation-health-issues").empty().append(
            $("<div>").addClass("oncall-health-loading muted").text(healthT("oncall_health.loading.rotation", {}, "Loading health details..."))
        );

        $.ajax({
            url: DETAIL_ENDPOINT_PREFIX + encodeURIComponent(rotationId),
            method: "GET",
            dataType: "json",
        }).done(function (payload) {
            renderRotationHealthModal(payload || {});
        }).fail(function (xhr) {
            const message = xhr.responseJSON && (xhr.responseJSON.message || xhr.responseJSON.error)
                ? (xhr.responseJSON.message || xhr.responseJSON.error)
                : healthT("oncall_health.errors.rotation_details_failed", {}, "Failed to load health details.");
            $("#rotation-health-subtitle").text("");
            $("#rotation-health-summary").empty();
            $("#rotation-health-issues").empty().append(
                $("<div>").addClass("oncall-health-empty oncall-health-error").text(message)
            );
        });
    }

    function loadRotationHealthSummariesForVisibleRows() {
        ensureRotationHealthColumn();
        syncRotationHealthRows();
        flushRotationHealthSummaryQueue();
    }

    function installTableObserver() {
        const tbody = getRotationsTbody();
        if (!tbody.length || tableObserver) {
            return;
        }

        tableObserver = new MutationObserver(function () {
            if (!syncingRows) {
                scheduleSyncRotationHealthRows();
            }
        });
        tableObserver.observe(tbody[0], {
            childList: true,
            subtree: false,
        });
    }

    function installRotationHealthIntegration(attempt) {
        loadOncallHealthCss();
        ensureRotationHealthModal();
        ensureRotationHealthColumn();
        installTableObserver();
        scheduleSyncRotationHealthRows();

        if (!getRotationsTbody().length && (attempt || 0) < 40) {
            window.setTimeout(function () {
                installRotationHealthIntegration((attempt || 0) + 1);
            }, 100);
        }
    }

    $(document).on("click", "[data-rotation-health-open]", function (event) {
        event.preventDefault();
        event.stopPropagation();
        const rotationId = $(this).attr("data-rotation-health-open")
            || $(this).closest("td.oncall-health-cell").attr("data-rotation-health-id");
        openRotationHealthModal(rotationId);
    });

    function renderTeamHealthIndicator(health, teamId) {
        const status = getHealthStatus(health);
        const label = healthLabel(health);

        return $("<button>")
            .attr("type", "button")
            .attr("title", label)
            .attr("aria-label", healthT("oncall_health.indicator.open_team", {label: label}, `Open team on-call health details. ${label}`))
            .attr("data-team-health-open", teamId || "")
            .addClass("oncall-health-indicator")
            .addClass(`oncall-health-${status}`)
            .text(healthIcon(status));
    }

    function updateTeamHealthSummary(teamId, summary) {
        const id = String(teamId || "");
        if (!id) {
            return;
        }

        $(`td.oncall-health-cell[data-team-health-id="${id}"]`).each(function () {
            $(this)
                .empty()
                .append(renderTeamHealthIndicator(summary, id));
        });
    }

    function loadTeamHealthSummariesForVisibleRows() {
        const ids = [];

        $("td.oncall-health-cell[data-team-health-id]").each(function () {
            const id = String($(this).attr("data-team-health-id") || "");

            if (id && ids.indexOf(id) === -1) {
                ids.push(id);
            }
        });

        if (!ids.length) {
            return;
        }

        const params = new URLSearchParams();
        ids.forEach(function (id) {
            params.append("team_id", id);
        });

        $.ajax({
            url: `${TEAM_SUMMARY_ENDPOINT}?${params.toString()}`,
            method: "GET",
            dataType: "json",
        }).done(function (payload) {
            const byId = payload && payload.by_id ? payload.by_id : {};

            ids.forEach(function (id) {
                if (byId[String(id)]) {
                    updateTeamHealthSummary(id, byId[String(id)]);
                } else {
                    updateTeamHealthSummary(id, {
                        status: "unknown",
                        critical: 0,
                        warning: 0,
                        info: 0,
                        total: 0,
                        tooltip: healthT("oncall_health.errors.summary_missing_team", {}, "Team health summary was not returned."),
                    });
                }
            });
        }).fail(function (xhr) {
            const message = xhr.responseJSON && (xhr.responseJSON.message || xhr.responseJSON.error)
                ? (xhr.responseJSON.message || xhr.responseJSON.error)
                : healthT("oncall_health.errors.team_summary_failed", {}, "Team health summary failed to load.");

            ids.forEach(function (id) {
                updateTeamHealthSummary(id, {
                    status: "unknown",
                    critical: 0,
                    warning: 0,
                    info: 0,
                    total: 0,
                    tooltip: message,
                });
            });
        });
    }

    function renderTeamHealthModal(payload) {
        ensureRotationHealthModal();

        const summary = payload.summary || {};
        const issues = payload.issues || [];
        const title = payload.team_name || payload.team_slug
            ? healthT("oncall_health.title.team_named", {name: payload.team_name || payload.team_slug}, `Team on-call health: ${payload.team_name || payload.team_slug}`)
            : healthT("oncall_health.title.team", {}, "Team on-call health");

        $("#rotation-health-title").text(title);
        $("#rotation-health-subtitle").text(payload.team_slug ? healthT("oncall_health.team_label", {name: payload.team_slug}, `Team: ${payload.team_slug}`) : "");

        const startsAt = payload.window && payload.window.starts_at;
        const endsAt = payload.window && payload.window.ends_at;
        $("#rotation-health-window").text(
            startsAt && endsAt
                ? healthT("oncall_health.window", {
                    start: formatDateTime(startsAt),
                    end: formatDateTime(endsAt),
                }, `Checked window: ${formatDateTime(startsAt)} — ${formatDateTime(endsAt)}`)
                : ""
        );

        const summaryEl = $("#rotation-health-summary").empty();
        summaryEl.append(renderSummaryCard(
            "Status",
            summary.status || "unknown",
            `oncall-health-summary-card-status oncall-health-summary-card-${summary.status || "unknown"}`
        ));
        summaryEl.append(renderSummaryCard(healthT("oncall_health.summary.critical", {}, "Critical"), summary.critical, "oncall-health-summary-card-critical"));
        summaryEl.append(renderSummaryCard(healthT("oncall_health.summary.warning", {}, "Warnings"), summary.warning, "oncall-health-summary-card-warning"));
        summaryEl.append(renderSummaryCard(healthT("oncall_health.summary.info", {}, "Info"), summary.info, "oncall-health-summary-card-info"));

        const issuesEl = $("#rotation-health-issues").empty();

        if (!issues.length) {
            issuesEl.append(
                $("<div>")
                    .addClass("oncall-health-empty")
                    .text(healthT("oncall_health.empty.team", {}, "No team health issues were found."))
            );
            return;
        }

        renderIssueGroup(issuesEl, healthT("oncall_health.summary.critical", {}, "Critical"), issues.filter((item) => item.severity === "critical"));
        renderIssueGroup(issuesEl, healthT("oncall_health.summary.warning", {}, "Warnings"), issues.filter((item) => item.severity === "warning"));
        renderIssueGroup(issuesEl, healthT("oncall_health.summary.info", {}, "Info"), issues.filter((item) => item.severity === "info"));
    }

    function openTeamHealthModal(teamId) {
        if (!teamId) {
            if (typeof window.showAppError === "function") {
                window.showAppError(healthT("oncall_health.errors.team_id_missing", {}, "Team id was not found for this health indicator."));
            }
            return;
        }

        ensureRotationHealthModal();
        openRotationHealthModalElement();

        $("#rotation-health-title").text(healthT("oncall_health.title.team", {}, "Team on-call health"));
        $("#rotation-health-subtitle").text(healthT("oncall_health.loading", {}, "Loading..."));
        $("#rotation-health-window").text("");
        $("#rotation-health-summary").empty();
        $("#rotation-health-issues").empty().append(
            $("<div>").addClass("oncall-health-loading muted").text(healthT("oncall_health.loading.team", {}, "Loading team health details..."))
        );

        $.ajax({
            url: TEAM_DETAIL_ENDPOINT_PREFIX + encodeURIComponent(teamId),
            method: "GET",
            dataType: "json",
        }).done(function (payload) {
            renderTeamHealthModal(payload || {});
        }).fail(function (xhr) {
            const message = xhr.responseJSON && (xhr.responseJSON.message || xhr.responseJSON.error)
                ? (xhr.responseJSON.message || xhr.responseJSON.error)
                : healthT("oncall_health.errors.team_details_failed", {}, "Failed to load team health details.");

            $("#rotation-health-subtitle").text("");
            $("#rotation-health-summary").empty();
            $("#rotation-health-issues").empty().append(
                $("<div>").addClass("oncall-health-empty oncall-health-error").text(message)
            );
        });
    }

    $(document).on("click", "[data-team-health-open]", function (event) {
        event.preventDefault();
        event.stopPropagation();

        const teamId = $(this).attr("data-team-health-open")
            || $(this).closest("td.oncall-health-cell").attr("data-team-health-id");

        openTeamHealthModal(teamId);
    });

    window.renderOncallHealthIndicator = renderOncallHealthIndicator;
    window.openRotationHealthModal = openRotationHealthModal;
    window.renderRotationHealthModal = renderRotationHealthModal;
    window.loadRotationHealthSummariesForVisibleRows = loadRotationHealthSummariesForVisibleRows;
    window.syncRotationHealthRows = syncRotationHealthRows;
    window.renderTeamHealthIndicator = renderTeamHealthIndicator;
    window.openTeamHealthModal = openTeamHealthModal;
    window.renderTeamHealthModal = renderTeamHealthModal;
    window.loadTeamHealthSummariesForVisibleRows = loadTeamHealthSummariesForVisibleRows;

    $(function () {
        installRotationHealthIntegration(0);
    });
}());
