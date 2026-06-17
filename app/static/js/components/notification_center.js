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
            .attr("aria-label", "Notifications")
            .attr("title", "Notifications")
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

    function renderNotificationItems(panel, items) {
        panel.empty();

        $("<div>")
            .addClass("notification-center-title")
            .text("Responder requests")
            .appendTo(panel);

        if (!items.length) {
            $("<div>")
                .addClass("notification-center-empty")
                .text("No pending requests")
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
            .text(item.title || "Notification")
            .appendTo(row);

        $("<div>")
            .addClass("notification-center-item-body")
            .text(item.body || "")
            .appendTo(row);

        if (item.incident) {
            $("<div>")
                .addClass("notification-center-item-meta")
                .text([
                    item.incident.team_name || "-",
                    item.incident.service_name || "-",
                    item.incident.status || "-",
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
                .text(action.label)
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
                .text("Open incident")
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
