(function () {
    function notificationCenterRoot() {
        let root = $("#notification-center-root");

        if (root.length) {
            return root;
        }

        const mount = $("#notification-center-mount");

        root = $("<div>")
            .attr("id", "notification-center-root")
            .addClass("notification-center-root");

        if (mount.length) {
            mount.empty().append(root);
        } else {
            root.appendTo("body");
        }

        return root;
    }

    function renderNotificationButton(payload) {
        const root = notificationCenterRoot();
        const count = Number(payload.unread_count || 0);

        root.empty();

        const button = $("<button>")
            .attr("type", "button")
            .attr("aria-label", i18n.t("notification_center.notifications"))
            .attr("title", i18n.t("notification_center.notifications"))
            .addClass("btn btn-icon notification-center-button")
            .append(
                $("<i>")
                    .addClass(count > 0 ? "fa-solid fa-bell" : "fa-regular fa-bell")
                    .attr("aria-hidden", "true")
            );

        if (count > 0) {
            button.append(
                $("<span>")
                    .addClass("notification-center-badge")
                    .text(count > 99 ? "99+" : String(count))
            );
        }

        const panel = $("<div>")
            .addClass("notification-center-panel")
            .hide();

        renderNotificationItems(panel, payload.items || []);

        button.on("click", function (event) {
            event.stopPropagation();
            panel.toggle();
        });

        panel.on("click", function (event) {
            event.stopPropagation();
        });

        $(document)
            .off("click.notificationCenter")
            .on("click.notificationCenter", function () {
                panel.hide();
            });

        root.append(button).append(panel);
    }

    function notificationCenterUserLabel(user) {
        if (!user) {
            return i18n.t("notification_center.unknown_user");
        }

        return (
            user.display_name ||
            user.username ||
            user.email ||
            i18n.t("notification_center.user_id", {id: user.id || "-"})
        );
    }

    function notificationCenterItemTitle(item) {
        if (item && item.type === "responder_request") {
            return i18n.t("notification_center.responder_requested");
        }

        return item && item.title
            ? item.title
            : i18n.t("notification_center.notification");
    }

    function notificationCenterItemBody(item) {
        if (!item || item.type !== "responder_request" || !item.responder) {
            return item && item.body ? item.body : "";
        }

        const responder = item.responder;
        const requester = notificationCenterUserLabel(responder.requested_by);

        if (responder.message) {
            return requester + ": " + responder.message;
        }

        return i18n.t("notification_center.help_requested", {
            requester: requester,
        });
    }

    function notificationCenterActionLabel(action) {
        if (!action) {
            return "";
        }

        if (action.id === "accept") {
            return i18n.t("notification_center.accept");
        }

        if (action.id === "decline") {
            return i18n.t("notification_center.decline");
        }

        return action.label || "";
    }

    function notificationCenterIncidentStatus(status) {
        const normalized = String(status || "").toLowerCase();

        const keys = {
            firing: "notification_center.status.firing",
            acknowledged: "notification_center.status.acknowledged",
            resolved: "notification_center.status.resolved",
            maintenance: "notification_center.status.maintenance",
            open: "notification_center.status.open",
            closed: "notification_center.status.closed",
        };

        return keys[normalized]
            ? i18n.t(keys[normalized])
            : (status || "-");
    }

    function renderNotificationItems(panel, items) {
        panel.empty();

        $("<div>")
            .addClass("notification-center-title")
            .text(i18n.t("notification_center.title"))
            .appendTo(panel);

        if (!items.length) {
            $("<div>")
                .addClass("notification-center-empty")
                .text(i18n.t("notification_center.empty"))
                .appendTo(panel);
            return;
        }

        items.forEach(function (item) {
            panel.append(renderNotificationItem(item));
        });
    }

    function renderNotificationItem(item) {
        const row = $("<div>").addClass("notification-center-item");

        $("<div>")
            .addClass("notification-center-item-title")
            .text(notificationCenterItemTitle(item))
            .appendTo(row);

        $("<div>")
            .addClass("notification-center-item-body")
            .text(notificationCenterItemBody(item))
            .appendTo(row);

        if (item.incident) {
            $("<div>")
                .addClass("notification-center-item-meta")
                .text([
                    item.incident.team_name || i18n.t("notification_center.no_team"),
                    item.incident.service_name || i18n.t("notification_center.no_service"),
                    notificationCenterIncidentStatus(item.incident.status),
                ].join(" · "))
                .appendTo(row);
        }

        const actions = $("<div>").addClass("notification-center-actions");

        (item.actions || []).forEach(function (action) {
            if (!action.url || !action.status) {
                return;
            }

            $("<button>")
                .attr("type", "button")
                .addClass(
                    action.status === "accepted"
                        ? "btn btn-sm btn-success"
                        : "btn btn-sm btn-secondary"
                )
                .text(notificationCenterActionLabel(action))
                .on("click", function () {
                    updateResponderFromNotification(action.url, action.status);
                })
                .appendTo(actions);
        });

        if (actions.children().length) {
            row.append(actions);
        }

        if (item.url) {
            $("<a>")
                .attr("href", item.url)
                .addClass("notification-center-open")
                .text(i18n.t("notification_center.open_incident"))
                .appendTo(row);
        }

        return row;
    }

    function updateResponderFromNotification(url, status) {
        apiPut(
            url,
            {
                status: status,
            },
            function () {
                loadNotificationCenter();

                if (
                    window.AlertIncidentManagement &&
                    window.AlertIncidentManagement.refreshCurrent
                ) {
                    window.AlertIncidentManagement.refreshCurrent();
                }
            }
        );
    }

    function loadNotificationCenter() {
        apiGet("/api/notification-center", function (payload) {
            renderNotificationButton(payload || {});
        });
    }

    window.NotificationCenter = {
        load: loadNotificationCenter,
    };

    $(function () {
        loadNotificationCenter();
        window.setInterval(loadNotificationCenter, 30000);
    });
})();
