(function (window, $) {
    "use strict";

    let openedActionMenu = null;

    function actionItems(items) {
        return Array.isArray(items) ? items : [];
    }

    function callMaybe(value, object) {
        if (typeof value === "function") {
            return value(object);
        }
        return value;
    }

    function canUseActionItem(object, item) {
        if (callMaybe(item.disabled, object)) {
            return false;
        }

        if (typeof item.allowed === "function") {
            return !!item.allowed(object);
        }

        if (item.required && typeof window.canActionObject === "function") {
            return window.canActionObject(object, item.required);
        }

        return true;
    }

    function shouldShowActionItem(object, item) {
        if (callMaybe(item.hidden, object)) {
            return false;
        }

        if (typeof item.visible === "function" && !item.visible(object)) {
            return false;
        }

        if (!canUseActionItem(object, item)) {
            return false;
        }

        return true;
    }

    function getActionItemLabel(item, object) {
        const label = callMaybe(item.label, object);
        return label || i18n.t("shared.action");
    }

    function getActionItemIcon(item, object) {
        return callMaybe(item.icon, object) || "";
    }

    function setMenuExpanded(menu, expanded) {
        const toggle = menu && menu.data("action-menu-toggle");
        if (toggle && toggle.length) {
            toggle.attr("aria-expanded", expanded ? "true" : "false");
        }
    }

    function placeActionMenu(menu) {
        const toggle = menu.data("action-menu-toggle");
        const list = menu.data("action-menu-list");

        if (!toggle || !toggle.length || !list || !list.length) {
            return;
        }

        if (!document.body.contains(toggle[0])) {
            closeActionMenu(menu);
            return;
        }

        const rect = toggle[0].getBoundingClientRect();
        const gap = 6;
        const edgeGap = 8;

        list.css({
            position: "fixed",
            display: "block",
            visibility: "hidden",
            left: "0px",
            top: "0px",
            zIndex: 3000,
        });

        const listWidth = list.outerWidth();
        const listHeight = list.outerHeight();

        let left = rect.right - listWidth;
        let top = rect.bottom + gap;

        if (left < edgeGap) {
            left = edgeGap;
        }

        if (left + listWidth > window.innerWidth - edgeGap) {
            left = Math.max(edgeGap, window.innerWidth - listWidth - edgeGap);
        }

        if (
            top + listHeight > window.innerHeight - edgeGap
            && rect.top - gap - listHeight >= edgeGap
        ) {
            top = rect.top - gap - listHeight;
        }

        if (top + listHeight > window.innerHeight - edgeGap) {
            top = Math.max(edgeGap, window.innerHeight - listHeight - edgeGap);
        }

        list.css({
            left: Math.round(left) + "px",
            top: Math.round(top) + "px",
            visibility: "visible",
        });
    }

    function openActionMenu(menu) {
        if (openedActionMenu && openedActionMenu[0] === menu[0]) {
            closeActionMenu(menu);
            return;
        }

        closeOpenedActionMenu();

        const list = menu.data("action-menu-list");
        if (!list || !list.length) {
            return;
        }

        openedActionMenu = menu;
        menu.addClass("is-open");
        setMenuExpanded(menu, true);

        list
            .appendTo(document.body)
            .addClass("is-open app-action-menu-portal")
            .show();

        window.requestAnimationFrame(function () {
            placeActionMenu(menu);
        });
    }

    function closeActionMenu(menu) {
        if (!menu || !menu.length) {
            return;
        }

        const list = menu.data("action-menu-list");

        menu.removeClass("is-open");
        setMenuExpanded(menu, false);

        if (list && list.length) {
            list
                .removeClass("is-open app-action-menu-portal")
                .hide()
                .css({
                    position: "",
                    display: "",
                    visibility: "",
                    left: "",
                    top: "",
                    zIndex: "",
                })
                .appendTo(menu);
        }

        if (openedActionMenu && openedActionMenu[0] === menu[0]) {
            openedActionMenu = null;
        }
    }

    function closeOpenedActionMenu() {
        if (openedActionMenu) {
            closeActionMenu(openedActionMenu);
        }
    }

    function focusNextMenuItem(list, direction) {
        const items = list.find(".app-action-menu-item:enabled");
        if (!items.length) {
            return;
        }

        const activeElement = document.activeElement;
        let currentIndex = items.index(activeElement);

        if (currentIndex < 0) {
            currentIndex = direction > 0 ? -1 : 0;
        }

        let nextIndex = currentIndex + direction;
        if (nextIndex >= items.length) {
            nextIndex = 0;
        }
        if (nextIndex < 0) {
            nextIndex = items.length - 1;
        }

        items.eq(nextIndex).trigger("focus");
    }

    function bindActionMenuGlobalHandlers() {
        if (window.__appActionMenuGlobalHandlersBound) {
            return;
        }

        window.__appActionMenuGlobalHandlersBound = true;

        $(document).on("click.appActionMenu", function (event) {
            if (!openedActionMenu) {
                return;
            }

            const list = openedActionMenu.data("action-menu-list");
            const clickedInsideMenu = openedActionMenu[0].contains(event.target);
            const clickedInsideList = list && list[0] && list[0].contains(event.target);

            if (clickedInsideMenu || clickedInsideList) {
                return;
            }

            closeOpenedActionMenu();
        });

        $(document).on("keydown.appActionMenu", function (event) {
            if (!openedActionMenu) {
                return;
            }

            const list = openedActionMenu.data("action-menu-list");

            if (event.key === "Escape") {
                event.preventDefault();
                closeOpenedActionMenu();
                const toggle = openedActionMenu && openedActionMenu.data("action-menu-toggle");
                if (toggle && toggle.length) {
                    toggle.trigger("focus");
                }
                return;
            }

            if (event.key === "ArrowDown") {
                event.preventDefault();
                focusNextMenuItem(list, 1);
                return;
            }

            if (event.key === "ArrowUp") {
                event.preventDefault();
                focusNextMenuItem(list, -1);
            }
        });

        window.addEventListener(
            "scroll",
            function () {
                if (openedActionMenu) {
                    placeActionMenu(openedActionMenu);
                }
            },
            true
        );

        window.addEventListener("resize", function () {
            if (openedActionMenu) {
                placeActionMenu(openedActionMenu);
            }
        });
    }

    function makeActionMenuItem(item, object, menu) {
        const label = getActionItemLabel(item, object);
        const icon = getActionItemIcon(item, object);
        const button = $("<button>")
            .attr("type", "button")
            .attr("role", "menuitem")
            .addClass("app-action-menu-item")
            .toggleClass("is-danger", !!callMaybe(item.danger, object));

        if (icon) {
            if (/^(fa|fas|far|fab|fal|fad)\s/.test(icon)) {
                button.append(
                    $("<i>")
                        .addClass("app-action-menu-icon " + icon)
                        .attr("aria-hidden", "true")
                );
            } else {
                button.append(
                    $("<span>")
                        .addClass("app-action-menu-icon")
                        .text(icon)
                );
            }
        }

        button.append(
            $("<span>")
                .addClass("app-action-menu-label")
                .text(label)
        );

        button.on("click", function (event) {
            event.preventDefault();
            event.stopPropagation();

            if (!canUseActionItem(object, item)) {
                closeActionMenu(menu);
                if (item.denyMessage && typeof window.showAppError === "function") {
                    window.showAppError(callMaybe(item.denyMessage, object));
                }
                return;
            }

            closeActionMenu(menu);

            if (typeof item.onClick === "function") {
                item.onClick(object, event);
            }
        });

        return button;
    }

    function makeActionMenu(options) {
        options = options || {};

        const object = options.object || {};
        const items = actionItems(options.items);
        const menu = $("<div>").addClass("app-action-menu");
        const toggle = $("<button>")
            .attr("type", "button")
            .attr("aria-label", options.label || i18n.t("shared.actions"))
            .attr("aria-haspopup", "menu")
            .attr("aria-expanded", "false")
            .addClass("app-action-menu-toggle")
            .append(
                $("<i>")
                    .addClass(options.icon || "fas fa-ellipsis-v")
                    .attr("aria-hidden", "true")
            );

        if (options.className) {
            menu.addClass(options.className);
        }

        const list = $("<div>")
            .addClass("app-action-menu-list")
            .attr("role", "menu")
            .hide();

        items.forEach(function (item) {
            if (!item || !shouldShowActionItem(object, item)) {
                return;
            }

            list.append(makeActionMenuItem(item, object, menu));
        });

        if (!list.children().length) {
            return $();
        }

        toggle.on("click", function (event) {
            event.preventDefault();
            event.stopPropagation();

            if (toggle.prop("disabled")) {
                return;
            }

            openActionMenu(menu);
        });

        menu
            .data("action-menu-toggle", toggle)
            .data("action-menu-list", list)
            .append(toggle)
            .append(list);

        bindActionMenuGlobalHandlers();

        return menu;
    }

    window.makeActionMenu = makeActionMenu;
    window.closeOpenedActionMenu = closeOpenedActionMenu;
})(window, jQuery);
