function oncallAsArray(value) {
    return Array.isArray(value) ? value : [];
}

function oncallDisplayName(name, slug, fallback) {
    return name || slug || fallback || "-";
}

function oncallStatusKind(data) {
    if (data && data.status) {
        return data.status;
    }

    if (data && data.is_oncall) {
        return "primary";
    }

    if (data && data.is_escalation_backup) {
        return "escalation";
    }

    return "idle";
}

function oncallFormatDate(value, timezone) {
    if (typeof formatShortDateTimeMinutesInTimezone === "function") {
        return formatShortDateTimeMinutesInTimezone(value, timezone || "UTC");
    }

    if (typeof formatDateTime24 === "function") {
        return formatDateTime24(value, {seconds: false});
    }

    return value || "-";
}

function oncallFormatPrimarySlot(slot) {
    const team = oncallDisplayName(slot.team_name, slot.team_slug, i18n.t("shared.oncall.team"));
    const rotation = slot.rotation_name || i18n.t("shared.oncall.rotation", {id: slot.rotation_id});
    const layer = slot.layer_name || (slot.type === "override" ? i18n.t("shared.oncall.override") : i18n.t("shared.oncall.layer"));
    const timezone = slot.timezone || "UTC";

    return [
        team + " / " + rotation + " / " + layer,
        oncallFormatDate(slot.start, timezone)
            + " → "
            + oncallFormatDate(slot.end, timezone)
    ].join(" — ");
}

function oncallFormatEscalationItem(item) {
    const team = oncallDisplayName(item.team_name, item.team_slug, item.team_display || i18n.t("shared.oncall.team"));
    const policy = item.policy_name || i18n.t("shared.oncall.policy", {id: item.policy_id});
    const level = i18n.t("shared.oncall.level", {level: item.level || "-"});
    const delay = Number(item.delay_seconds || 0);

    const parts = [
        team,
        policy,
        level
    ];

    if (delay > 0) {
        parts.push(i18n.t("shared.oncall.after_minutes", {count: Math.round(delay / 60)}));
    }

    if (item.kind === "rotation" && item.start && item.end) {
        const rotation = item.rotation_name || i18n.t("shared.oncall.rotation", {id: item.rotation_id});
        const timezone = item.timezone || "UTC";

        return parts.join(" / ")
            + " — "
            + rotation
            + " — "
            + oncallFormatDate(item.start, timezone)
            + " → "
            + oncallFormatDate(item.end, timezone);
    }

    return parts.join(" / ");
}

function oncallBuildTooltip(data) {
    const current = oncallAsArray(data && data.current);
    const next = oncallAsArray(data && data.next);
    const escalationCurrent = oncallAsArray(data && data.escalation_current);
    const escalationNext = oncallAsArray(data && data.escalation_next);

    const lines = [];

    if (current.length) {
        lines.push(i18n.t("shared.oncall.primary_now"));
        current.slice(0, 3).forEach(function (slot) {
            lines.push("• " + oncallFormatPrimarySlot(slot));
        });
    } else if (escalationCurrent.length) {
        lines.push(i18n.t("shared.oncall.backup_now"));
    } else {
        lines.push(i18n.t("shared.oncall.not_now"));
    }

    if (escalationCurrent.length) {
        lines.push("");
        lines.push(i18n.t("shared.oncall.backup"));
        escalationCurrent.slice(0, 5).forEach(function (item) {
            lines.push("• " + oncallFormatEscalationItem(item));
        });
    }

    lines.push("");
    lines.push(i18n.t("shared.oncall.next_primary"));

    if (next.length) {
        next.slice(0, 5).forEach(function (slot) {
            lines.push("• " + oncallFormatPrimarySlot(slot));
        });
    } else {
        lines.push(i18n.t("shared.oncall.no_primary", {days: ((data && data.lookahead_days) || 30)}));
    }

    if (escalationNext.length) {
        lines.push("");
        lines.push(i18n.t("shared.oncall.next_backup"));
        escalationNext.slice(0, 5).forEach(function (item) {
            lines.push("• " + oncallFormatEscalationItem(item));
        });
    }

    return lines.join("\n");
}
