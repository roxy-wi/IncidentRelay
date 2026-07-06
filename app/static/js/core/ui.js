function asArray(value) {
    /* Return value when it is an array, otherwise return an empty array. */
    return Array.isArray(value) ? value : [];
}

function parseJsonInput(selector, fallback) {
    /* Parse JSON from an input field. */
    const raw = $(selector).val();

    if (!raw) {
        return fallback;
    }

    try {
        return JSON.parse(raw);
    } catch (error) {
        const message = "Invalid JSON in " + selector + ": " + error;
        if (typeof showAppError === "function") {
            showAppError(message);
        } else {
            alert(message);
        }
        throw error;
    }
}

function loadVersion() {
    /* Load service version. */
    apiGet("/api/version", function (data) {
        $("#service-version").text("v" + data.service_version);
    });
}

function uiStatusBadge(label, variant) {
    return $("<span>")
        .addClass("ui-status-badge")
        .addClass("ui-status-badge-" + (variant || "muted"))
        .text(label || "-");
}


function uiStatusBadgeVariantForStatus(status) {
    const normalized = status || "unknown";

    if (normalized === "operational" || normalized === "enabled" || normalized === "active") {
        return "success";
    }

    if (normalized === "major_outage" || normalized === "critical" || normalized === "failed") {
        return "danger";
    }

    if (normalized === "partial_outage" || normalized === "degraded" || normalized === "warning") {
        return "warning";
    }

    if (normalized === "maintenance" || normalized === "info") {
        return "info";
    }

    return "muted";
}


function renderStatusBadge(isActive, activeText = "Enabled", inactiveText = "Disabled") {
    /*
     * Render a reusable enabled/disabled badge.
     */
    return uiStatusBadge(
        isActive ? activeText : inactiveText,
        isActive ? "success" : "muted"
    );
}

function upperCaseFirst(value) {
    value = String(value || "");
    return value.charAt(0).toUpperCase() + value.slice(1);
}

function findScrollableParent(element, boundary) {
    /*
     * Return the nearest vertical scroll container between element and boundary.
     * This supports both full-page scrolling and scrollable modal bodies.
     */
    const boundaryElement = boundary && boundary.length ? boundary.get(0) : null;
    let current = element && element.parentElement;

    while (current && current !== document.body && current !== document.documentElement) {
        const style = window.getComputedStyle(current);
        const canScroll = /(auto|scroll)/.test(style.overflowY + style.overflow);

        if (canScroll && current.scrollHeight > current.clientHeight + 4) {
            return current;
        }

        if (boundaryElement && current === boundaryElement) {
            break;
        }

        current = current.parentElement;
    }

    if (boundaryElement && boundaryElement.scrollHeight > boundaryElement.clientHeight + 4) {
        return boundaryElement;
    }

    return window;
}

function getHighlightTarget(target) {
    /* Highlight the meaningful container, not only a small title/input. */
    const highlight = target.closest(
        ".card, .page-details-card, .details-card, .app-modal-section, .modal-section, .form-body, .app-modal-dialog, .modal-dialog"
    );

    return highlight.length ? highlight : target;
}

function scrollToAndHighlight(selector, options) {
    /*
     * Scroll to a rendered UI block and briefly highlight it.
     *
     * options.container: optional scroll boundary such as "#group-modal".
     * options.focus: optional field to focus after scrolling.
     * options.highlight: optional element to highlight instead of target parent.
     */
    options = options || {};

    const target = $(selector).first();
    if (!target.length) {
        return;
    }

    const boundary = options.container ? $(options.container).first() : $();
    const element = target.get(0);
    const scrollContainer = findScrollableParent(element, boundary);
    const offset = Number(options.offset || 72);

    if (scrollContainer === window) {
        element.scrollIntoView({
            behavior: "smooth",
            block: options.block || "center",
            inline: "nearest"
        });
    } else {
        const containerRect = scrollContainer.getBoundingClientRect();
        const elementRect = element.getBoundingClientRect();
        const nextTop = scrollContainer.scrollTop + elementRect.top - containerRect.top - offset;

        if (typeof scrollContainer.scrollTo === "function") {
            scrollContainer.scrollTo({ top: Math.max(0, nextTop), behavior: "smooth" });
        } else {
            scrollContainer.scrollTop = Math.max(0, nextTop);
        }
    }

    const highlight = options.highlight ? $(options.highlight).first() : getHighlightTarget(target);
    if (highlight.length) {
        highlight.removeClass("app-scroll-highlight");
        // Force animation restart.
        void highlight.get(0).offsetWidth;
        highlight.addClass("app-scroll-highlight");
        setTimeout(function () {
            highlight.removeClass("app-scroll-highlight");
        }, 1600);
    }

    if (options.focus) {
        setTimeout(function () {
            const focusTarget = $(options.focus).first();
            if (focusTarget.length && !focusTarget.prop("disabled")) {
                focusTarget.trigger("focus");
            }
        }, 280);
    }
}

const appDetailsHighlightState = {
    enabledUntil: 0,
    timers: new WeakMap()
};

function markDetailsInteraction() {
    /*
     * Allow details highlight shortly after a user action.
     * This prevents random highlighting during background refresh.
     */
    appDetailsHighlightState.enabledUntil = Date.now() + 1800;
}

function shouldHighlightDetailsNow() {
    return Date.now() <= appDetailsHighlightState.enabledUntil;
}

function getDetailsHighlightContainer(element) {
    /*
     * Find the visible details block that should be highlighted.
     */
    const target = $(element).closest([
        "[id$='-details-body']",
        "#alert-details-summary",
        "#alert-details-labels",
        "#alert-details-payload",
        "#alert-details-events",
        "#alert-details-notifications",
        ".details-list"
    ].join(", "));

    if (!target.length) {
        return $();
    }

    const container = target.closest([
        ".card",
        ".content-card",
        ".details-card",
        ".page-details-card",
        ".app-modal-dialog",
        ".modal-dialog",
        ".app-modal-content",
        ".modal-content"
    ].join(", "));

    return container.length ? container : target;
}

function highlightDetailsElement(element) {
    const target = getDetailsHighlightContainer(element);

    if (!target.length || !target.is(":visible")) {
        return;
    }

    const domNode = target.get(0);

    if (appDetailsHighlightState.timers.has(domNode)) {
        clearTimeout(appDetailsHighlightState.timers.get(domNode));
    }

    const timer = setTimeout(function () {
        target.removeClass("app-scroll-highlight");
        void domNode.offsetWidth;
        target.addClass("app-scroll-highlight");

        setTimeout(function () {
            target.removeClass("app-scroll-highlight");
        }, 1600);

        appDetailsHighlightState.timers.delete(domNode);
    }, 40);

    appDetailsHighlightState.timers.set(domNode, timer);
}

function initDetailsAutoHighlight() {
    /*
     * Highlight details panels after user-triggered changes.
     *
     * Covers:
     * - team details
     * - route details
     * - channel details
     * - rotation details
     * - alert details modal sections
     */
    $(document).on("click.appDetailsHighlight", [
        ".name-button",
        ".details-button",
        "[data-details-target]",
        "[data-open-details]",
        "[onclick*='Details']",
        "[onclick*='details']"
    ].join(", "), markDetailsInteraction);

    const observer = new MutationObserver(function (mutations) {
        if (!shouldHighlightDetailsNow()) {
            return;
        }

        mutations.forEach(function (mutation) {
            const node = mutation.target;

            if (!node || node.nodeType !== 1) {
                return;
            }

            const detailsTarget = $(node).closest([
                "[id$='-details-body']",
                "#alert-details-summary",
                "#alert-details-labels",
                "#alert-details-payload",
                "#alert-details-events",
                "#alert-details-notifications",
                ".details-list"
            ].join(", "));

            if (!detailsTarget.length) {
                return;
            }

            highlightDetailsElement(detailsTarget.get(0));
        });
    });

    observer.observe(document.body, {
        childList: true,
        subtree: true,
        characterData: true
    });
}

const stickyTableScrollState = {
    bar: null,
    inner: null,
    wrapper: null,
    isSyncing: false,
    scheduled: false,
    wrapperScrollHandler: null
};

function ensureStickyTableScrollbar() {
    if (stickyTableScrollState.bar) {
        return;
    }

    const bar = document.createElement("div");
    const inner = document.createElement("div");

    bar.className = "app-sticky-x-scroll is-hidden";
    inner.className = "app-sticky-x-scroll-inner";

    bar.appendChild(inner);
    document.body.appendChild(bar);

    bar.addEventListener("scroll", function () {
        if (!stickyTableScrollState.wrapper || stickyTableScrollState.isSyncing) {
            return;
        }

        stickyTableScrollState.isSyncing = true;
        stickyTableScrollState.wrapper.scrollLeft = bar.scrollLeft;
        stickyTableScrollState.isSyncing = false;
    });

    stickyTableScrollState.bar = bar;
    stickyTableScrollState.inner = inner;
}

function isElementVisible(element) {
    if (!element) {
        return false;
    }

    const rect = element.getBoundingClientRect();
    const style = window.getComputedStyle(element);

    return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
}

function getScrollableTableWrappers() {
    const selectors = [
        ".view-visible .table-wrapper",
        ".view-visible .table-responsive",
        ".view-visible .table-container",
        ".app-modal:not(.is-hidden) .table-wrapper",
        ".app-modal.is-open .table-wrapper",
        ".modal:not(.is-hidden) .table-wrapper",
        ".table-wrapper"
    ].join(", ");

    const seen = [];
    const wrappers = [];

    $(selectors).each(function () {
        if (seen.indexOf(this) !== -1) {
            return;
        }
        seen.push(this);

        if (!isElementVisible(this)) {
            return;
        }

        if (this.scrollWidth <= this.clientWidth + 2) {
            return;
        }

        wrappers.push(this);
    });

    return wrappers;
}

function scoreTableWrapperForStickyScrollbar(wrapper) {
    const rect = wrapper.getBoundingClientRect();
    const viewportHeight = window.innerHeight || document.documentElement.clientHeight;
    const visibleTop = Math.max(rect.top, 0);
    const visibleBottom = Math.min(rect.bottom, viewportHeight - 20);
    const visibleHeight = Math.max(0, visibleBottom - visibleTop);

    if (visibleHeight <= 0) {
        return 0;
    }

    // Prefer wrappers that occupy the visible area, and slightly prefer
    // wrappers whose top is already above the viewport while scrolling a list.
    return visibleHeight + (rect.top < 0 ? 60 : 0);
}

function getActiveTableWrapperForStickyScrollbar() {
    const wrappers = getScrollableTableWrappers();
    let active = null;
    let activeScore = 0;

    wrappers.forEach(function (wrapper) {
        const score = scoreTableWrapperForStickyScrollbar(wrapper);
        if (score > activeScore) {
            active = wrapper;
            activeScore = score;
        }
    });

    return active;
}

function detachStickyTableWrapper() {
    if (stickyTableScrollState.wrapper && stickyTableScrollState.wrapperScrollHandler) {
        stickyTableScrollState.wrapper.removeEventListener("scroll", stickyTableScrollState.wrapperScrollHandler);
    }

    stickyTableScrollState.wrapper = null;
    stickyTableScrollState.wrapperScrollHandler = null;
}

function attachStickyTableWrapper(wrapper) {
    if (stickyTableScrollState.wrapper === wrapper) {
        return;
    }

    detachStickyTableWrapper();

    stickyTableScrollState.wrapper = wrapper;
    stickyTableScrollState.wrapperScrollHandler = function () {
        if (!stickyTableScrollState.bar || stickyTableScrollState.isSyncing) {
            return;
        }

        stickyTableScrollState.isSyncing = true;
        stickyTableScrollState.bar.scrollLeft = wrapper.scrollLeft;
        stickyTableScrollState.isSyncing = false;
    };

    wrapper.addEventListener("scroll", stickyTableScrollState.wrapperScrollHandler, { passive: true });
}

function hideStickyTableScrollbar() {
    ensureStickyTableScrollbar();
    detachStickyTableWrapper();
    stickyTableScrollState.bar.classList.add("is-hidden");
    document.body.classList.remove("has-app-sticky-x-scroll");
}

function refreshStickyTableScrollbars() {
    /*
     * Show a fixed horizontal scrollbar for the currently visible wide table.
     * The real table scroll and the fixed scrollbar are synchronized.
     */
    ensureStickyTableScrollbar();

    const wrapper = getActiveTableWrapperForStickyScrollbar();
    if (!wrapper) {
        hideStickyTableScrollbar();
        return;
    }

    attachStickyTableWrapper(wrapper);

    const rect = wrapper.getBoundingClientRect();
    stickyTableScrollState.inner.style.width = wrapper.scrollWidth + "px";
    stickyTableScrollState.bar.style.left = Math.max(0, rect.left) + "px";
    stickyTableScrollState.bar.style.width = Math.max(0, Math.min(rect.width, window.innerWidth - Math.max(0, rect.left))) + "px";
    stickyTableScrollState.bar.scrollLeft = wrapper.scrollLeft;
    stickyTableScrollState.bar.classList.remove("is-hidden");
    document.body.classList.add("has-app-sticky-x-scroll");
}

function scheduleStickyTableScrollbars() {
    if (stickyTableScrollState.scheduled) {
        return;
    }

    stickyTableScrollState.scheduled = true;
    window.requestAnimationFrame(function () {
        stickyTableScrollState.scheduled = false;
        refreshStickyTableScrollbars();
    });
}

function initStickyTableScrollbars() {
    ensureStickyTableScrollbar();

    $(window).on("resize.appStickyXScroll scroll.appStickyXScroll", scheduleStickyTableScrollbars);
    $(document).on("shown.app-modal hidden.app-modal app:page-loaded", scheduleStickyTableScrollbars);

    const observer = new MutationObserver(function () {
        scheduleStickyTableScrollbars();
    });

    observer.observe(document.body, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ["class", "style"]
    });

    setTimeout(scheduleStickyTableScrollbars, 0);
    setTimeout(scheduleStickyTableScrollbars, 250);
}

function initAppUxNavigationHelpers() {
    /*
     * Make indirect UI changes visible to users:
     * - group/team member Edit fills a form above the table;
     * - team name opens details below the table.
     */
    $(document).on("click.appUxNavigation", "#group-members-table .btn", function () {
        if ($.trim($(this).text()) !== "Edit") {
            return;
        }

        setTimeout(function () {
            scrollToAndHighlight("#group-member-form-title, #group-member-user", {
                container: "#group-modal",
                focus: "#group-member-role"
            });
        }, 0);
    });

    $(document).on("click.appUxNavigation", "#team-members-table .btn", function () {
        if ($.trim($(this).text()) !== "Edit") {
            return;
        }

        setTimeout(function () {
            scrollToAndHighlight("#team-member-user", {
                container: "#team-members-modal",
                focus: "#team-member-role"
            });
        }, 0);
    });

    $(document).on("click.appUxNavigation", "#teams-table .name-button", function () {
        setTimeout(function () {
            scrollToAndHighlight("#team-details-body", {
                highlight: "#team-details-body",
                block: "nearest"
            });
        }, 0);
    });
}

$(document).ready(function () {
    initAppUxNavigationHelpers();
    initStickyTableScrollbars();
    initDetailsAutoHighlight();
});
