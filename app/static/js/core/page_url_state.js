(function (window, $) {
    "use strict";

    const registry = {};
    const inputTimers = {};

    function currentRoutePath() {
        if (typeof normalizeAppRoutePath === "function") {
            return normalizeAppRoutePath(window.location.pathname || "/");
        }

        return window.location.pathname || "/";
    }

    function isActive(config) {
        return currentRoutePath() === config.path;
    }

    function defaultFieldValue(field) {
        if (field.defaultValue !== undefined) {
            return field.defaultValue;
        }
        if (field.type === "checkbox") {
            return false;
        }
        if (field.type === "multi") {
            return [];
        }
        return "";
    }

    function normalizeScalar(value) {
        if (value === undefined || value === null) {
            return "";
        }
        return String(value);
    }

    function queryBool(params, name) {
        return ["1", "true", "yes", "on"].indexOf(
            String(params.get(name) || "").toLowerCase()
        ) !== -1;
    }

    function fieldParamNames(field) {
        return [field.param].concat(field.aliases || []);
    }

    function setSelectValue(element, value) {
        const scalar = normalizeScalar(value);

        if (
            scalar &&
            !element.find("option").filter(function () {
                return String($(this).val()) === scalar;
            }).length
        ) {
            element.data("page-url-state-pending", scalar);
            return false;
        }

        element.removeData("page-url-state-pending");
        element.val(scalar);
        return true;
    }

    function restoreField(field, params) {
        const element = $(field.selector);

        if (!element.length) {
            return;
        }

        const hasValue = fieldParamNames(field).some(function (name) {
            return params.has(name);
        });
        const fallback = defaultFieldValue(field);

        if (field.type === "checkbox") {
            element.prop(
                "checked",
                hasValue ? queryBool(params, field.param) : !!fallback
            );
            return;
        }

        if (field.type === "multi") {
            let values = [];
            fieldParamNames(field).forEach(function (name) {
                values = values.concat(params.getAll(name));
            });
            if (!hasValue) {
                values = Array.isArray(fallback) ? fallback : [];
            }

            if (typeof setTableFilterValues === "function") {
                setTableFilterValues(element, values);
            } else {
                element.val(values);
            }
            return;
        }

        let value = fallback;
        if (params.has(field.param)) {
            value = params.get(field.param);
        } else if (field.aliases) {
            field.aliases.some(function (name) {
                if (!params.has(name)) {
                    return false;
                }
                value = params.get(name);
                return true;
            });
        }

        if (element.is("select")) {
            setSelectValue(element, value);
            return;
        }

        element.val(normalizeScalar(value));
    }

    function restoreCustom(custom, params) {
        let value = params.has(custom.param)
            ? params.get(custom.param)
            : custom.defaultValue;

        if (typeof custom.normalize === "function") {
            value = custom.normalize(value);
        }

        if (typeof custom.set === "function") {
            custom.set(value);
        }
    }

    function restoreFields(name) {
        const config = registry[name];

        if (!config || !isActive(config)) {
            return false;
        }

        const params = new URLSearchParams(window.location.search || "");
        (config.fields || []).forEach(function (field) {
            restoreField(field, params);
        });
        return true;
    }

    function restore(name) {
        const config = registry[name];

        if (!config || !restoreFields(name)) {
            return false;
        }

        const params = new URLSearchParams(window.location.search || "");
        (config.custom || []).forEach(function (custom) {
            restoreCustom(custom, params);
        });

        if (typeof config.afterRestore === "function") {
            config.afterRestore(params);
        }

        return true;
    }

    function reapply(name) {
        return restore(name);
    }

    function restorePath(path) {
        Object.keys(registry).forEach(function (name) {
            const config = registry[name];
            if (config.path === path) {
                restore(name);
            }
        });
    }

    function deleteFieldParams(params, field) {
        fieldParamNames(field).forEach(function (name) {
            params.delete(name);
        });
    }

    function appendField(params, field) {
        const element = $(field.selector);

        deleteFieldParams(params, field);

        if (!element.length) {
            return;
        }

        if (field.type === "checkbox") {
            if (element.is(":checked") !== !!defaultFieldValue(field)) {
                params.set(field.param, element.is(":checked") ? "1" : "0");
            }
            return;
        }

        if (field.type === "multi") {
            let values;
            if (typeof getTableFilterValues === "function") {
                values = getTableFilterValues(element);
            } else {
                values = element.val() || [];
            }

            (values || []).forEach(function (value) {
                if (normalizeScalar(value)) {
                    params.append(field.param, normalizeScalar(value));
                }
            });
            return;
        }

        let value = normalizeScalar(element.val());
        if (field.trim !== false) {
            value = value.trim();
        }

        const fallback = normalizeScalar(defaultFieldValue(field));
        if (value && value !== fallback) {
            params.set(field.param, value);
        }
    }

    function appendCustom(params, custom) {
        params.delete(custom.param);

        if (typeof custom.get !== "function") {
            return;
        }

        let value = custom.get();
        if (typeof custom.normalize === "function") {
            value = custom.normalize(value);
        }

        const scalar = normalizeScalar(value);
        const fallback = normalizeScalar(custom.defaultValue);

        if (scalar && scalar !== fallback) {
            params.set(custom.param, scalar);
        }
    }

    function write(name, options) {
        const config = registry[name];

        if (!config || !isActive(config) || !window.history || !window.history.replaceState) {
            return false;
        }

        const settings = $.extend({replace: true}, options || {});
        const url = new URL(window.location.href);

        (config.fields || []).forEach(function (field) {
            appendField(url.searchParams, field);
        });
        (config.custom || []).forEach(function (custom) {
            appendCustom(url.searchParams, custom);
        });

        const nextUrl = url.pathname + url.search + url.hash;
        const currentUrl = window.location.pathname + window.location.search + window.location.hash;

        if (nextUrl === currentUrl) {
            return false;
        }

        const state = Object.assign({}, window.history.state || {}, {path: nextUrl});
        if (settings.replace === false && window.history.pushState) {
            window.history.pushState(state, "", nextUrl);
        } else {
            window.history.replaceState(state, "", nextUrl);
        }

        return true;
    }

    function bind(name) {
        const config = registry[name];
        const selectors = (config.fields || [])
            .map(function (field) { return field.selector; })
            .filter(Boolean)
            .join(", ");

        if (!selectors) {
            return;
        }

        const namespace = ".pageUrlState-" + name.replace(/[^a-z0-9_-]/gi, "-");

        $(document)
            .off("input" + namespace + " change" + namespace, selectors)
            .on("input" + namespace + " change" + namespace, selectors, function (event) {
                if (!isActive(config)) {
                    return;
                }

                const delay = event.type === "input" ? Number(config.inputDebounceMs || 120) : 0;
                window.clearTimeout(inputTimers[name]);
                inputTimers[name] = window.setTimeout(function () {
                    write(name);
                }, delay);
            });
    }

    function register(config) {
        if (!config || !config.name || !config.path) {
            throw new Error("page URL state requires name and path");
        }

        registry[config.name] = config;
        bind(config.name);
        return config;
    }

    function getParam(name, fallback) {
        const value = new URLSearchParams(window.location.search || "").get(name);
        return value === null ? fallback : value;
    }

    window.PageUrlState = {
        register: register,
        restore: restore,
        restoreFields: restoreFields,
        restorePath: restorePath,
        reapply: reapply,
        write: write,
        getParam: getParam,
    };
})(window, jQuery);
