(function (window) {
    "use strict";

    const commonKeys = ["involvement", "assigned_to_me", "service_id", "service_ids"];
    const inboxKeys = ["status", "statuses", "severity", "severities", "priority", "priorities",
        "search", "shelved", "page", "page_size", "sort", "order"];
    const memory = new Map();
    let storageWarningShown = false;

    function scope() {
        return currentUser ? String(currentUser.id) + ":" + (currentUser.active_group_id || "all") : "";
    }

    function storageKey(name) {
        return "incidentrelay.alert_filters." + scope() + "." + name;
    }

    function storageUnavailable() {
        if (!storageWarningShown) {
            console.warn("Filter storage is unavailable; preferences will last only for this page session.");
            storageWarningShown = true;
        }
    }

    function read(name) {
        const key = storageKey(name);
        if (storageWarningShown && memory.has(key)) {
            return new URLSearchParams(memory.get(key));
        }
        try {
            const value = localStorage.getItem(key) || "";
            memory.set(key, value);
            return new URLSearchParams(value);
        } catch (error) {
            storageUnavailable();
            return new URLSearchParams(memory.get(key) || "");
        }
    }

    function save(name, params) {
        if (!scope()) return;
        const key = storageKey(name);
        memory.set(key, params.toString());
        try {
            localStorage.setItem(key, params.toString());
        } catch (error) {
            storageUnavailable();
        }
    }

    function pick(params, keys) {
        const result = new URLSearchParams();
        keys.forEach(key => params.getAll(key).forEach(value => result.append(key, value)));
        return result;
    }

    function saved(page) {
        const params = page === "alerts" ? pick(read("alerts"), inboxKeys) : new URLSearchParams();
        pick(read("common"), commonKeys).forEach((value, key) => params.append(key, value));
        return params;
    }

    function isActive(page) {
        return page === "dashboard" ? window.location.pathname === "/"
            : /^\/alerts(?:\/\d+)?\/?$/.test(window.location.pathname);
    }

    function writeUrl(page, params) {
        if (!isActive(page)) return;
        const query = params.toString();
        const url = window.location.pathname + (query ? "?" + query : "") + window.location.hash;
        history.replaceState(Object.assign({}, history.state, {
            path: url, alert_filter_scope: scope(), alert_filter_page: page
        }), "", url);
    }

    function resolve(page) {
        const urlParams = new URLSearchParams(window.location.search);
        const keys = page === "alerts" ? commonKeys.concat(inboxKeys) : commonKeys;
        const state = history.state || {};
        // A URL containing filters, or a recorded history entry (even after
        // Reset), is an exact selection. Plain menu links restore preferences.
        if ((state.alert_filter_scope === scope() && state.alert_filter_page === page)
            || keys.some(key => urlParams.has(key))) {
            return urlParams;
        }
        const params = saved(page);
        urlParams.forEach((value, key) => params.append(key, value));
        writeUrl(page, params);
        return params;
    }

    function remember(page, params) {
        if (!isActive(page)) return;
        save("common", pick(params, commonKeys));
        if (page === "alerts") save("alerts", pick(params, inboxKeys));
        writeUrl(page, params);
    }

    window.AlertFilterState = {scope: scope, isActive: isActive, resolve: resolve,
        remember: remember, saved: saved};
})(window);
