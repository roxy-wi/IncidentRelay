/*
 * Shared table pagination controls.
 *
 * Pages should not keep page-specific pagination markup in templates.
 * Keep only the table/card markup; this helper creates one shared footer and
 * mounts it next to the table wrapper or into an explicit mount slot.
 */

function tablePaginationIdSelector(id) {
    if (typeof $.escapeSelector === "function") {
        return "#" + $.escapeSelector(id);
    }

    return "#" + String(id).replace(
        /([\\!"#$%&'()*+,./:;<=>?@\[\]^`{|}~])/g,
        "\\$1"
    );
}


function tablePaginationPageExists(options) {
    const tableSelector = options && options.tableSelector;

    if (!tableSelector) {
        return true;
    }

    return $(tableSelector).length > 0;
}


function buildTablePaginationControls(options) {
    options = options || {};

    const id = options.id;

    if (!id) {
        throw new Error("table pagination id is required");
    }

    const prefix = options.prefix || id;
    const pageSizeOptions = options.pageSizeOptions || [10, 25, 50, 100];
    const rowsLabel = options.rowsLabel || "Rows per page";
    const previousLabel = options.previousLabel || "Previous";
    const nextLabel = options.nextLabel || "Next";

    const controls = $("<div>")
        .attr("id", id)
        .attr("data-table-pagination", "true")
        .addClass("table-pagination")
        .append(
            $("<div>")
                .addClass("table-pagination-left")
                .append(
                    $("<label>")
                        .addClass("details-meta table-pagination-size-label")
                        .text(rowsLabel + " ")
                        .append(
                            $("<select>")
                                .attr("id", prefix + "-page-size")
                                .addClass("input input-sm table-page-size")
                        )
                )
                .append(
                    $("<span>")
                        .addClass("details-meta table-pagination-range")
                        .append(" Showing ")
                        .append($("<span>").attr("id", prefix + "-page-from").text("0"))
                        .append("-")
                        .append($("<span>").attr("id", prefix + "-page-to").text("0"))
                        .append(" of ")
                        .append($("<span>").attr("id", prefix + "-filtered-count").text("0"))
                )
        )
        .append(
            $("<div>")
                .addClass("table-pagination-center")
                .append(" Page ")
                .append($("<span>").attr("id", prefix + "-current-page").text("1"))
                .append(" of ")
                .append($("<span>").attr("id", prefix + "-total-pages").text("1"))
        )
        .append(
            $("<div>")
                .addClass("table-pagination-actions")
                .append(
                    $("<button>")
                        .attr("type", "button")
                        .attr("id", prefix + "-prev-page")
                        .addClass("btn btn-secondary btn-small")
                        .text(previousLabel)
                )
                .append(
                    $("<button>")
                        .attr("type", "button")
                        .attr("id", prefix + "-next-page")
                        .addClass("btn btn-secondary btn-small")
                        .text(nextLabel)
                )
        );

    const select = controls.find(tablePaginationIdSelector(prefix + "-page-size"));

    pageSizeOptions.forEach(function (value) {
        select.append($("<option>").val(String(value)).text(String(value)));
    });

    return controls;
}


function resolveTablePaginationMount(options) {
    options = options || {};

    const mount = $(options.mountSelector || "").first();

    if (mount.length) {
        return {
            mode: "append",
            target: mount,
        };
    }

    const after = $(options.afterSelector || "").first();

    if (after.length) {
        return {
            mode: "after",
            target: after,
        };
    }

    const tableTarget = $(options.tableSelector || "").first();
    const wrapper = tableTarget.is("table")
        ? tableTarget.closest(".table-wrapper, .table-responsive, .table-container")
        : tableTarget.find(".table-wrapper, .table-responsive, .table-container").first();

    if (wrapper.length) {
        return {
            mode: "after",
            target: wrapper,
        };
    }

    const tableElement = tableTarget.is("table") ? tableTarget : tableTarget.find("table").first();

    if (tableElement.length) {
        return {
            mode: "after",
            target: tableElement,
        };
    }

    const card = tableTarget.closest(".card, .content-card, .page-card, .table-card, .dashboard-card");

    if (card.length) {
        return {
            mode: "append",
            target: card,
        };
    }

    return {
        mode: "append",
        target: $(options.containerSelector || "body"),
    };
}


function mountTablePaginationControls(controls, options) {
    const mount = resolveTablePaginationMount(options);

    controls
        .detach()
        .addClass("table-pagination table-pagination-attached");

    if (mount.mode === "after") {
        mount.target.addClass("has-table-pagination");
        mount.target.after(controls);
        return controls;
    }

    mount.target.addClass("has-table-pagination");
    mount.target.append(controls);
    return controls;
}


function ensureTablePaginationControls(options) {
    options = options || {};

    const id = options.id;

    if (!id) {
        throw new Error("table pagination id is required");
    }

    if (!tablePaginationPageExists(options)) {
        $(tablePaginationIdSelector(id)).remove();
        return $();
    }

    let controls = $(tablePaginationIdSelector(id)).first();

    if (controls.length && controls.attr("data-table-pagination") !== "true") {
        const replacement = buildTablePaginationControls(options);
        controls.replaceWith(replacement);
        controls = replacement;
    }

    if (!controls.length) {
        controls = buildTablePaginationControls(options);
    }

    mountTablePaginationControls(controls, options);

    return controls;
}


function renderTablePaginationControls(options) {
    options = options || {};

    const prefix = options.prefix || options.id;
    const pagination = options.pagination || {};
    const currentPage = pagination.page || 1;
    const totalPages = pagination.total_pages || 1;
    const pageSize = pagination.page_size || options.pageSize || 25;
    const totalItems = pagination.total_items || 0;
    const controls = ensureTablePaginationControls(options);

    if (!controls.length) {
        return;
    }

    $(tablePaginationIdSelector(prefix + "-current-page")).text(currentPage);
    $(tablePaginationIdSelector(prefix + "-total-pages")).text(totalPages);
    $(tablePaginationIdSelector(prefix + "-page-from")).text(pagination.from || 0);
    $(tablePaginationIdSelector(prefix + "-page-to")).text(pagination.to || 0);
    $(tablePaginationIdSelector(prefix + "-filtered-count")).text(totalItems);
    $(tablePaginationIdSelector(prefix + "-page-size")).val(String(pageSize));
    $(tablePaginationIdSelector(prefix + "-prev-page")).prop("disabled", !pagination.has_prev);
    $(tablePaginationIdSelector(prefix + "-next-page")).prop("disabled", !pagination.has_next);

    controls.toggle(options.alwaysVisible === true || totalItems > 0);
}


function createTableFilterChip(text) {
    return $("<span>")
        .addClass("table-filter-chip")
        .text(text || "-");
}


function makeUiPill(text, cssClass) {
    return $("<span>")
        .addClass("ui-pill")
        .addClass(cssClass || "ui-pill-muted")
        .text(text || "-");
}


function makeStatusDot(status) {
    return $("<span>")
        .addClass("status-dot")
        .addClass("status-dot-" + String(status || "muted").toLowerCase());
}
