(function (window, $) {
    "use strict";

    const DEFAULT_DELAY_MS = 150;

    function resolveElement(target) {
        return target && target.jquery ? target : $(target);
    }

    function spinner(options) {
        const settings = $.extend({small: false}, options || {});
        const element = $("<span>")
            .addClass("ui-loading-spinner")
            .attr("aria-hidden", "true");

        if (settings.small) {
            element.addClass("ui-loading-spinner-small");
        }

        return element;
    }

    function loadingState(message, options) {
        const settings = $.extend({compact: false}, options || {});
        const state = $("<div>")
            .addClass("ui-loading-state")
            .attr("role", "status")
            .attr("aria-live", "polite")
            .append(spinner({small: settings.compact}));

        if (settings.compact) {
            state.addClass("ui-loading-state-compact");
        }

        if (message) {
            state.append($("<span>").addClass("ui-loading-message").text(message));
        }

        return state;
    }

    function showBlock(target, message, options) {
        const element = resolveElement(target);

        if (!element.length) {
            return;
        }

        element
            .attr("aria-busy", "true")
            .empty()
            .append(loadingState(message, options));
    }

    function showInline(target, message) {
        const element = resolveElement(target);

        if (!element.length) {
            return;
        }

        element
            .attr("aria-busy", "true")
            .empty()
            .append(
                $("<span>")
                    .addClass("ui-loading-inline")
                    .attr("role", "status")
                    .attr("aria-live", "polite")
                    .append(spinner({small: true}))
                    .append($("<span>").text(message || ""))
            );
    }

    function clear(target) {
        const element = resolveElement(target);

        if (!element.length) {
            return;
        }

        element.removeAttr("aria-busy").empty();
    }

    function showTableSkeleton(target, options) {
        const settings = $.extend({columns: 4, rows: 6}, options || {});
        const tbody = resolveElement(target);

        if (!tbody.length) {
            return;
        }

        tbody.attr("aria-busy", "true").empty();

        for (let rowIndex = 0; rowIndex < settings.rows; rowIndex += 1) {
            const row = $("<tr>")
                .addClass("ui-skeleton-row")
                .attr("aria-hidden", "true");

            for (let columnIndex = 0; columnIndex < settings.columns; columnIndex += 1) {
                const widthClass = "ui-skeleton-width-" + ((rowIndex + columnIndex) % 4 + 1);
                row.append(
                    $("<td>").append(
                        $("<span>")
                            .addClass("ui-skeleton-line")
                            .addClass(widthClass)
                    )
                );
            }

            tbody.append(row);
        }
    }

    function clearTableBusy(target) {
        resolveElement(target).removeAttr("aria-busy");
    }

    function setButtonLoading(target, active) {
        const button = resolveElement(target);

        if (!button.length) {
            return;
        }

        if (active) {
            if (button.data("ui-loading-active")) {
                return;
            }

            button.data("ui-loading-active", true);
            button.data("ui-loading-original-html", button.html());
            button.data("ui-loading-original-disabled", button.prop("disabled"));
            button
                .prop("disabled", true)
                .attr("aria-busy", "true")
                .addClass("is-loading")
                .empty()
                .append(spinner({small: true}))
                .append(
                    $("<span>")
                        .addClass("ui-loading-button-label")
                        .html(button.data("ui-loading-original-html"))
                );
            return;
        }

        if (!button.data("ui-loading-active")) {
            return;
        }

        const originalHtml = button.data("ui-loading-original-html");
        const originalDisabled = Boolean(button.data("ui-loading-original-disabled"));

        button
            .html(originalHtml)
            .prop("disabled", originalDisabled)
            .removeAttr("aria-busy")
            .removeClass("is-loading")
            .removeData("ui-loading-active")
            .removeData("ui-loading-original-html")
            .removeData("ui-loading-original-disabled");
    }

    function delayed(showCallback, delayMs) {
        let finished = false;
        let visible = false;
        const timer = window.setTimeout(function () {
            if (finished) {
                return;
            }

            visible = true;
            showCallback();
        }, Number.isFinite(delayMs) ? delayMs : DEFAULT_DELAY_MS);

        return {
            finish: function (hideCallback) {
                if (finished) {
                    return;
                }

                finished = true;
                window.clearTimeout(timer);

                if (visible && typeof hideCallback === "function") {
                    hideCallback();
                }
            }
        };
    }

    window.AppLoading = {
        DEFAULT_DELAY_MS: DEFAULT_DELAY_MS,
        spinner: spinner,
        loadingState: loadingState,
        showBlock: showBlock,
        showInline: showInline,
        clear: clear,
        showTableSkeleton: showTableSkeleton,
        clearTableBusy: clearTableBusy,
        setButtonLoading: setButtonLoading,
        delayed: delayed,
    };
}(window, jQuery));
