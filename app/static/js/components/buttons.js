(function (window, $) {
    "use strict";

    function callMaybe(value, object) {
        if (typeof value === "function") {
            return value(object);
        }
        return value;
    }

    function actionAllowed(object, required) {
        if (!required) {
            return true;
        }
        if (typeof window.canActionObject !== "function") {
            return false;
        }
        return window.canActionObject(object, required);
    }

    function makeButton(options) {
        /*
         * Build a text button.
         *
         * Required:
         * - label: visible button text
         *
         * Optional:
         * - className: extra button classes
         * - icon: Font Awesome class, for example "fas fa-edit"
         * - srOnlyLabel: screen reader label override
         * - disabled: boolean or function(object)
         * - object: object passed to disabled/onClick handlers
         * - onClick: click handler
         */
        options = options || {};

        const object = options.object || null;
        const label = options.label || options.text || i18n.t("shared.action");
        const button = $("<button>")
            .attr("type", "button")
            .addClass(options.className || "btn btn-small btn-secondary")
            .prop("disabled", !!callMaybe(options.disabled, object));

        if (options.title) {
            button.attr("title", options.title);
        }

        if (options.ariaLabel || options.srOnlyLabel) {
            button.attr("aria-label", options.ariaLabel || options.srOnlyLabel);
        }

        if (options.icon) {
            button.append(
                $("<i>")
                    .addClass(options.icon)
                    .attr("aria-hidden", "true")
            );
            button.append(" ");
        }

        button.append($("<span>").text(label));

        if (typeof options.onClick === "function") {
            button.on("click", function (event) {
                options.onClick(object, event);
            });
        }

        return button;
    }

    function makeIconButton(options) {
        /*
         * Build an accessible icon-only button.
         *
         * Required:
         * - icon: Font Awesome class, for example "fas fa-edit"
         * - label: human-readable action label
         *
         * Optional:
         * - className: extra button classes
         * - object: object passed to disabled/onClick handlers
         * - disabled: boolean or function(object)
         * - onClick: click handler
         */
        options = options || {};

        const object = options.object || null;
        const label = options.label || i18n.t("shared.action");
        const button = $("<button>")
            .attr("type", "button")
            .addClass("btn btn-icon btn-small")
            .attr("title", label)
            .attr("aria-label", label)
            .prop("disabled", !!callMaybe(options.disabled, object));

        if (options.className) {
            button.addClass(options.className);
        }

        button.append(
            $("<i>")
                .addClass(options.icon || "fas fa-circle")
                .attr("aria-hidden", "true")
        );
        button.append(
            $("<span>")
                .addClass("sr-only")
                .text(label)
        );

        if (typeof options.onClick === "function") {
            button.on("click", function (event) {
                options.onClick(object, event);
            });
        }

        return button;
    }

    function makeActionButton(object, options) {
        /*
         * Build a text action button with the same required permission model
         * as makeActionMenu(). Use this for standalone page buttons only.
         */
        options = options || {};

        if (!actionAllowed(object, options.required || "write")) {
            return $();
        }

        return makeButton(Object.assign({}, options, { object: object }));
    }

    function makeIconActionButton(object, options) {
        /*
         * Build an icon-only action button with the same required permission model
         * as makeActionMenu(). Use this only when a row does not use a three-dot menu.
         */
        options = options || {};

        if (!actionAllowed(object, options.required || "write")) {
            return $();
        }

        return makeIconButton(Object.assign({}, options, { object: object }));
    }

    function appendActionIfAllowed(container, object, options) {
        const button = makeActionButton(object, options || {});
        if (button.length) {
            container.append(button);
        }
        return container;
    }

    function appendIconActionIfAllowed(container, object, options) {
        const button = makeIconActionButton(object, options || {});
        if (button.length) {
            container.append(button);
        }
        return container;
    }

    window.makeButton = makeButton;
    window.makeIconButton = makeIconButton;
    window.makeActionButton = makeActionButton;
    window.makeIconActionButton = makeIconActionButton;

    /* Backward-compatible legacy names. Keep these outside rbac_roles.js. */
    window.appendActionIfAllowed = appendActionIfAllowed;
    window.appendIconActionIfAllowed = appendIconActionIfAllowed;
})(window, jQuery);
