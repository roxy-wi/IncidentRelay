window.AppMaintenanceBadges = (function () {
    const behaviorLabels = {
        suppress_notifications: i18n.t("maintenance.behavior.suppress_notifications"),
        suppress_incident: i18n.t("maintenance.behavior.suppress_incident"),
        create_maintenance_incident: i18n.t("maintenance.behavior.maintenance_incident"),
        pause_escalation_only: i18n.t("maintenance.behavior.pause_escalation"),
    };

    function has(item) {
        return Boolean(item && item.active_maintenance);
    }

    function label(item) {
        if (!has(item)) {
            return "";
        }

        const maintenance = item.active_maintenance;

        return (
            behaviorLabels[maintenance.behavior] ||
            maintenance.behavior ||
            i18n.t("maintenance.badge.default")
        );
    }

    function formatDateWithoutTimezone(value) {
        const formatted = window.AppTimezones
            ? window.AppTimezones.formatPlainDatetime(value)
            : String(value || "");

        return formatted || "";
    }

    function maintenanceTimeText(maintenance) {
        if (!maintenance) {
            return "";
        }

        const occurrence = maintenance.occurrence || {};
        const startsAt = occurrence.starts_at || maintenance.starts_at;
        const endsAt = occurrence.ends_at || maintenance.ends_at;
        const timezone = occurrence.timezone || maintenance.timezone;

        if (!startsAt) {
            return timezone || "";
        }

        const startText = formatDateWithoutTimezone(startsAt);
        const endText = endsAt ? formatDateWithoutTimezone(endsAt) : "";

        if (!startText || startText === "-") {
            return timezone || "";
        }

        const rangeText = endText && endText !== "-"
            ? startText + " — " + endText
            : startText;

        return timezone ? rangeText + " " + timezone : rangeText;
    }

    function text(item, fallback) {
        if (!has(item)) {
            return fallback === undefined ? "" : fallback;
        }

        const maintenance = item.active_maintenance;
        const parts = [
            maintenance.name || i18n.t("maintenance.badge.default"),
            label(item),
            maintenanceTimeText(maintenance),
        ];

        return parts.filter(Boolean).join(" · ");
    }

    function badge(item) {
        if (!has(item)) {
            return $();
        }

        return $("<span>")
            .addClass("status-pill status-scheduled")
            .attr("title", text(item))
            .text(label(item));
    }

    function appendTo(container, item) {
        if (!has(item)) {
            return container;
        }

        container.append(badge(item));

        return container;
    }

    function appendBaseContent(container, content) {
        if (Array.isArray(content)) {
            content.forEach(function (item) {
                container.append(item);
            });

            return;
        }

        container.append(content);
    }

    function statusCell(baseContent, item) {
        const wrapper = $("<div>").addClass("status-cell");

        appendBaseContent(wrapper, baseContent);
        appendTo(wrapper, item);

        return $("<td>").append(wrapper);
    }

    return {
        has: has,
        label: label,
        text: text,
        badge: badge,
        appendTo: appendTo,
        statusCell: statusCell,
    };
})();