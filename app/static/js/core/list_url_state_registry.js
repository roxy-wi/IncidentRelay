(function (window) {
    "use strict";

    if (!window.PageUrlState) {
        return;
    }

    function fields() {
        return Array.prototype.slice.call(arguments);
    }

    function scalar(selector, param, defaultValue) {
        return {
            selector: selector,
            param: param,
            defaultValue: defaultValue === undefined ? "" : defaultValue,
        };
    }

    const configs = [
        {
            name: "routes",
            path: "/routes",
            fields: fields(
                scalar("#routes-search", "search"),
                scalar("#routes-source-filter", "source"),
                scalar("#routes-status-filter", "status")
            ),
            custom: [
                {
                    param: "sort",
                    defaultValue: "id",
                    get: function () { return routesSortState.column; },
                    set: function (value) {
                        routesSortState.column = routesSortColumns[value] ? value : "id";
                    },
                },
                {
                    param: "order",
                    defaultValue: "desc",
                    get: function () { return routesSortState.direction; },
                    normalize: function (value) { return value === "asc" ? "asc" : "desc"; },
                    set: function (value) { routesSortState.direction = value; },
                },
            ],
        },
        {
            name: "services",
            path: "/services",
            fields: fields(
                scalar("#services-search", "search"),
                scalar("#services-status-filter", "status"),
                scalar("#services-criticality-filter", "criticality"),
                scalar("#services-readiness-filter", "readiness")
            ),
        },
        {
            name: "business-services",
            path: "/business-services",
            fields: fields(
                scalar("#business-services-search", "search"),
                scalar("#business-services-status-filter", "status"),
                scalar("#business-services-public-filter", "public")
            ),
        },
        {
            name: "heartbeats",
            path: "/heartbeats",
            fields: fields(
                scalar("#heartbeats-search", "search"),
                scalar("#heartbeats-status-filter", "status")
            ),
        },
        {
            name: "maintenance-windows",
            path: "/maintenance-windows",
            fields: fields(
                scalar("#maintenance-window-search", "search"),
                scalar("#maintenance-window-status-filter", "status"),
                scalar("#maintenance-window-behavior-filter", "behavior")
            ),
        },
        {
            name: "orchestrations",
            path: "/event-orchestration",
            fields: fields(
                scalar("#orchestration-search", "search"),
                scalar("#orchestration-mode-filter", "mode"),
                scalar("#orchestration-scope-filter", "scope")
            ),
        },
        {
            name: "escalation-policies",
            path: "/escalation-policies",
            fields: fields(
                scalar("#escalation-policies-search", "search"),
                scalar("#escalation-policies-status-filter", "status")
            ),
        },
        {
            name: "notification-policies",
            path: "/notification-policies",
            fields: fields(
                scalar("#notification-policies-search", "search"),
                scalar("#notification-policies-status-filter", "status")
            ),
        },
        {
            name: "priority-policies",
            path: "/priority-policies",
            fields: fields(
                scalar("#priority-policies-search", "search"),
                scalar("#priority-policies-status-filter", "status")
            ),
        },
        {
            name: "matcher-presets",
            path: "/matcher-presets",
            fields: fields(
                scalar("#matcher-presets-search", "search"),
                scalar("#matcher-presets-status-filter", "status")
            ),
        },
        {
            name: "channels",
            path: "/channels",
            fields: fields(
                scalar("#channels-search", "search"),
                scalar("#channels-type-filter", "type"),
                scalar("#channels-status-filter", "status")
            ),
        },
        {
            name: "silences",
            path: "/silences",
            fields: fields(
                scalar("#silences-search", "search"),
                scalar("#silences-status-filter", "status")
            ),
        },
        {
            name: "teams",
            path: "/teams",
            fields: fields(
                scalar("#teams-search", "search"),
                scalar("#teams-group-filter", "group"),
                scalar("#teams-status-filter", "status")
            ),
        },
        {
            name: "rotations",
            path: "/rotations",
            fields: fields(
                scalar("#rotations-search", "search"),
                scalar("#rotations-status-filter", "status")
            ),
        },
        {
            name: "sso",
            path: "/admin/sso",
            fields: fields(
                scalar("#sso-search", "search"),
                scalar("#sso-protocol-filter", "protocol"),
                scalar("#sso-status-filter", "status")
            ),
        },
        {
            name: "audit-log",
            path: "/admin/audit-log",
            inputDebounceMs: 350,
            fields: fields(
                scalar("#audit-log-search", "search"),
                scalar("#audit-log-group", "group_id"),
                scalar("#audit-log-actor", "actor_id"),
                scalar("#audit-log-action", "action"),
                scalar("#audit-log-object-type", "object_type"),
                scalar("#audit-log-date-from", "date_from"),
                scalar("#audit-log-date-to", "date_to")
            ),
            custom: [
                {
                    param: "page",
                    defaultValue: "1",
                    get: function () { return auditLogCurrentPage; },
                    normalize: function (value) {
                        return String(Math.max(1, Number(value) || 1));
                    },
                    set: function (value) { auditLogCurrentPage = Number(value); },
                },
                {
                    param: "page_size",
                    defaultValue: "25",
                    get: function () { return auditLogPageSize; },
                    normalize: function (value) {
                        const size = Number(value) || 25;
                        return [10, 25, 50, 100].indexOf(size) !== -1 ? String(size) : "25";
                    },
                    set: function (value) { auditLogPageSize = Number(value); },
                },
            ],
        },
    ];

    configs.forEach(function (config) {
        window.PageUrlState.register(config);
    });
})(window);
