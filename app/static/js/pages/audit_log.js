let auditLogCurrentPage = 1;
let auditLogPageSize = 25;
let auditLogPagination = {
    page: 1,
    page_size: 25,
    total_items: 0,
    total_pages: 1,
    from: 0,
    to: 0,
    has_previous: false,
    has_next: false,
};
let auditLogItems = [];
let auditLogSearchTimer = null;


function auditLogFilterValue(selector) {
    return String($(selector).val() || "").trim();
}


function auditLogBuildUrl() {
    const params = new URLSearchParams();
    params.set("page", String(auditLogCurrentPage));
    params.set("page_size", String(auditLogPageSize));

    const filters = {
        search: auditLogFilterValue("#audit-log-search"),
        group_id: auditLogFilterValue("#audit-log-group"),
        actor_id: auditLogFilterValue("#audit-log-actor"),
        action: auditLogFilterValue("#audit-log-action"),
        object_type: auditLogFilterValue("#audit-log-object-type"),
        date_from: auditLogFilterValue("#audit-log-date-from"),
        date_to: auditLogFilterValue("#audit-log-date-to"),
    };

    Object.keys(filters).forEach(function (key) {
        if (filters[key]) {
            params.set(key, filters[key]);
        }
    });

    return "/api/admin/audit-logs?" + params.toString();
}


function loadAuditLog() {
    if (!$("#audit-log-table").length) {
        return;
    }

    apiGet(auditLogBuildUrl(), function (response) {
        auditLogItems = asArray(response && response.items);
        auditLogPagination = (response && response.pagination) || auditLogPagination;
        auditLogCurrentPage = Number(auditLogPagination.page || 1);
        auditLogPageSize = Number(auditLogPagination.page_size || auditLogPageSize);

        renderAuditLogSummary((response && response.summary) || {});
        renderAuditLogFilterOptions((response && response.filters) || {});
        renderAuditLogScope((response && response.permissions) || {});
        renderAuditLogTable(auditLogItems);
        renderAuditLogPagination(auditLogPagination);
    });
}


function renderAuditLogSummary(summary) {
    $("#audit-log-total-count").text(Number(summary.total || 0));
    $("#audit-log-actor-count").text(Number(summary.actors || 0));
    $("#audit-log-action-count").text(Number(summary.actions || 0));
    $("#audit-log-group-count").text(Number(summary.groups || 0));
}


function renderAuditLogScope(permissions) {
    const key = permissions.is_global_admin
        ? "audit.list.global_scope"
        : "audit.list.editor_scope";
    $("#audit-log-scope-hint").text(i18n.t(key));
}


function fillAuditLogSelect(selector, items, getValue, getLabel, emptyKey) {
    const select = $(selector);
    const selected = String(select.val() || "");
    select.empty().append(
        $("<option>").attr("value", "").text(i18n.t(emptyKey))
    );

    asArray(items).forEach(function (item) {
        const value = String(getValue(item));
        select.append(
            $("<option>")
                .attr("value", value)
                .text(getLabel(item))
        );
    });

    if (selected && select.find('option[value="' + selected.replace(/"/g, '\\"') + '"]').length) {
        select.val(selected);
    }
}


function renderAuditLogFilterOptions(filters) {
    fillAuditLogSelect(
        "#audit-log-group",
        filters.groups,
        function (group) { return group.id; },
        function (group) { return group.name || group.slug || ("#" + group.id); },
        "audit.filters.all_groups"
    );

    fillAuditLogSelect(
        "#audit-log-actor",
        filters.actors,
        function (actor) { return actor.id; },
        function (actor) { return actor.display_name || actor.username || ("#" + actor.id); },
        "audit.filters.all_actors"
    );

    fillAuditLogSelect(
        "#audit-log-action",
        filters.actions,
        function (action) { return action; },
        function (action) { return action; },
        "audit.filters.all_actions"
    );

    fillAuditLogSelect(
        "#audit-log-object-type",
        filters.object_types,
        function (objectType) { return objectType; },
        function (objectType) { return objectType; },
        "audit.filters.all_object_types"
    );
}


function auditLogActorLabel(item) {
    if (item.actor) {
        return item.actor.display_name || item.actor.username || ("#" + item.actor.id);
    }
    if (item.api_token) {
        return i18n.t("audit.row.api_token", {
            name: item.api_token.name || ("#" + item.api_token.id),
        });
    }
    return i18n.t("audit.row.system");
}


function auditLogObjectLabel(item) {
    if (!item.object_type) {
        return i18n.t("audit.row.not_available");
    }
    if (item.object_id === null || item.object_id === undefined) {
        return item.object_type;
    }
    return item.object_type + " #" + item.object_id;
}


function auditLogScopeCell(item) {
    const wrapper = $("<div>").addClass("audit-log-scope");
    if (item.group) {
        wrapper.append(
            $("<span>").text(item.group.name || item.group.slug || ("#" + item.group.id))
        );
    } else {
        wrapper.append($("<span>").text(i18n.t("audit.row.global_scope")));
    }

    if (item.team) {
        wrapper.append(
            $("<span>")
                .addClass("audit-log-secondary")
                .text(i18n.t("audit.row.team", {
                    name: item.team.name || item.team.slug || ("#" + item.team.id),
                }))
        );
    }
    return wrapper;
}


function renderAuditLogTable(items) {
    const tbody = $("#audit-log-table");
    tbody.empty();

    if (!items.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>")
                    .attr("colspan", 7)
                    .addClass("empty-state")
                    .text(i18n.t("audit.empty"))
            )
        );
        return;
    }

    items.forEach(function (item) {
        const actor = $("<div>").addClass("audit-log-actor");
        actor.append($("<span>").text(auditLogActorLabel(item)));
        if (item.actor && item.actor.username) {
            actor.append(
                $("<span>").addClass("audit-log-secondary").text("@" + item.actor.username)
            );
        }

        const object = $("<div>").addClass("audit-log-object");
        object.append($("<span>").text(auditLogObjectLabel(item)));

        const row = $("<tr>");
        row.append($("<td>").text(formatDateTimeMinutes(item.created_at) || "—"));
        row.append($("<td>").append(actor));
        row.append(
            $("<td>").append(
                $("<span>")
                    .addClass("badge badge-info audit-log-action")
                    .text(item.action || "—")
            )
        );
        row.append($("<td>").append(object));
        row.append($("<td>").append(auditLogScopeCell(item)));
        row.append(
            $("<td>")
                .addClass("audit-log-message")
                .text(item.message || "—")
        );
        row.append(
            $("<td>").append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("btn btn-small audit-log-view-details")
                    .attr("data-audit-id", item.id)
                    .text(i18n.t("audit.actions.view"))
            )
        );
        tbody.append(row);
    });
}


function renderAuditLogPagination(pagination) {
    const page = Number(pagination.page || 1);
    const totalPages = Number(pagination.total_pages || 1);
    const from = Number(pagination.from || 0);
    const to = Number(pagination.to || 0);
    const total = Number(pagination.total_items || 0);

    $("#audit-log-range").text(
        i18n.t("audit.pagination.range", {from: from, to: to, total: total})
    );
    $("#audit-log-page-label").text(
        i18n.t("audit.pagination.page_value", {page: page, total: totalPages})
    );
    $("#audit-log-page-size").val(String(auditLogPageSize));
    $("#audit-log-prev-page").prop("disabled", !pagination.has_previous);
    $("#audit-log-next-page").prop("disabled", !pagination.has_next);
}


function auditLogDetailsItem(label, value) {
    return $("<div>")
        .addClass("details-item")
        .append($("<div>").addClass("details-label").text(label))
        .append($("<div>").addClass("details-value").text(value || "—"));
}


function openAuditLogDetails(auditId) {
    const item = auditLogItems.find(function (entry) {
        return Number(entry.id) === Number(auditId);
    });
    if (!item) {
        return;
    }

    $("#audit-log-details-title").text(
        i18n.t("audit.details.entry", {id: item.id})
    );
    $("#audit-log-details-subtitle").text(item.action || "");

    const summary = $("#audit-log-details-summary");
    summary.empty()
        .append(auditLogDetailsItem(i18n.t("audit.details.time"), formatDateTimeMinutes(item.created_at)))
        .append(auditLogDetailsItem(i18n.t("audit.details.actor"), auditLogActorLabel(item)))
        .append(auditLogDetailsItem(i18n.t("audit.details.action"), item.action))
        .append(auditLogDetailsItem(i18n.t("audit.details.object"), auditLogObjectLabel(item)))
        .append(auditLogDetailsItem(
            i18n.t("audit.details.group"),
            item.group ? (item.group.name || item.group.slug || ("#" + item.group.id)) : i18n.t("audit.row.global_scope")
        ))
        .append(auditLogDetailsItem(
            i18n.t("audit.details.team"),
            item.team ? (item.team.name || item.team.slug || ("#" + item.team.id)) : "—"
        ))
        .append(auditLogDetailsItem(i18n.t("audit.details.message"), item.message || "—"));

    $("#audit-log-details-json").text(JSON.stringify(item.data || {}, null, 2));
    openAppModal("#audit-log-details-modal");
}


function clearAuditLogFilters() {
    $("#audit-log-search").val("");
    $("#audit-log-group").val("");
    $("#audit-log-actor").val("");
    $("#audit-log-action").val("");
    $("#audit-log-object-type").val("");
    $("#audit-log-date-from").val("");
    $("#audit-log-date-to").val("");
    auditLogCurrentPage = 1;
    loadAuditLog();
}


$(document).on("click", "#reload-audit-log", loadAuditLog);
$(document).on("click", "#clear-audit-log-filters", clearAuditLogFilters);
$(document).on("change", "#audit-log-group, #audit-log-actor, #audit-log-action, #audit-log-object-type, #audit-log-date-from, #audit-log-date-to", function () {
    auditLogCurrentPage = 1;
    loadAuditLog();
});
$(document).on("input", "#audit-log-search", function () {
    clearTimeout(auditLogSearchTimer);
    auditLogSearchTimer = setTimeout(function () {
        auditLogCurrentPage = 1;
        loadAuditLog();
    }, 300);
});
$(document).on("change", "#audit-log-page-size", function () {
    auditLogPageSize = Number($(this).val() || 25);
    auditLogCurrentPage = 1;
    loadAuditLog();
});
$(document).on("click", "#audit-log-prev-page", function () {
    if (auditLogPagination.has_previous) {
        auditLogCurrentPage -= 1;
        loadAuditLog();
    }
});
$(document).on("click", "#audit-log-next-page", function () {
    if (auditLogPagination.has_next) {
        auditLogCurrentPage += 1;
        loadAuditLog();
    }
});
$(document).on("click", ".audit-log-view-details", function () {
    openAuditLogDetails($(this).data("audit-id"));
});
$(document).on("click", "#close-audit-log-details, #close-audit-log-details-footer", function () {
    closeAppModal("#audit-log-details-modal");
});
