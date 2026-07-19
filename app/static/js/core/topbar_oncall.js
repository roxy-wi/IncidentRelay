let topbarOncallRefreshTimer = null;

function topbarDisplayName(name, slug, fallback) {
    return name || slug || fallback || "-";
}

function topbarFormatOncallDate(value, timezone) {
    if (typeof formatShortDateTimeMinutesInTimezone === "function") {
        return formatShortDateTimeMinutesInTimezone(value, timezone || "UTC");
    }

    if (typeof formatDateTime24 === "function") {
        return formatDateTime24(value, {seconds: false});
    }

    return value || "-";
}

function topbarFormatOncallSlot(slot) {
    const team = topbarDisplayName(slot.team_name, slot.team_slug, i18n.t("shared.oncall.team"));
    const rotation = slot.rotation_name || i18n.t("shared.oncall.rotation", {id: slot.rotation_id});
    const layer = slot.layer_name || (slot.type === "override" ? i18n.t("shared.oncall.override") : i18n.t("shared.oncall.layer"));
    const timezone = slot.timezone || "UTC";

    return [
        team + " / " + rotation + " / " + layer,
        topbarFormatOncallDate(slot.start, timezone)
            + " → "
            + topbarFormatOncallDate(slot.end, timezone)
    ].join(" — ");
}

function buildTopbarOncallTooltip(data) {
    const current = asArray(data && data.current);
    const next = asArray(data && data.next);
    const lines = [];

    if (data && data.is_oncall) {
        lines.push(i18n.t("shared.oncall.oncall_now"));

        current.slice(0, 3).forEach(function (slot) {
            lines.push("• " + topbarFormatOncallSlot(slot));
        });
    } else {
        lines.push(i18n.t("shared.oncall.not_now"));
    }

    lines.push("");

    if (next.length) {
        lines.push(i18n.t("shared.oncall.next_shifts"));

        next.slice(0, 5).forEach(function (slot) {
            lines.push("• " + topbarFormatOncallSlot(slot));
        });
    } else {
        lines.push(i18n.t("shared.oncall.no_upcoming", {days: ((data && data.lookahead_days) || 30)}));
    }

    return lines.join("\n");
}

function renderTopbarOncallStatus(data) {
    const indicator = $("#topbar-oncall-indicator");

    if (!indicator.length) {
        return;
    }

    const status = oncallStatusKind(data || {});
    const tooltip = oncallBuildTooltip(data || {});

    indicator
        .removeClass(
            "topbar-oncall-unknown "
            + "topbar-oncall-active "
            + "topbar-oncall-escalation "
            + "topbar-oncall-idle"
        )
        .addClass(
            status === "primary"
                ? "topbar-oncall-active"
                : status === "escalation"
                    ? "topbar-oncall-escalation"
                    : "topbar-oncall-idle"
        )
        .attr("title", tooltip)
        .attr(
            "aria-label",
            status === "primary"
                ? i18n.t("shared.oncall.primary_now")
                : status === "escalation"
                    ? i18n.t("shared.oncall.backup_now")
                    : i18n.t("shared.oncall.not_now")
        );

    $("#topbar-profile").attr("title", tooltip);
}

function renderTopbarOncallUnknown(message) {
    const tooltip = message || i18n.t("shared.oncall.unavailable");

    $("#topbar-oncall-indicator")
        .removeClass("topbar-oncall-active topbar-oncall-idle")
        .addClass("topbar-oncall-unknown")
        .attr("title", tooltip)
        .attr("aria-label", tooltip);

    $("#topbar-profile").attr("title", tooltip);
}

function loadTopbarOncallStatus() {
    if (!currentUser) {
        renderTopbarOncallUnknown(i18n.t("shared.oncall.not_authenticated"));
        return;
    }

    apiGet(
        "/api/profile/oncall?days=30",
        function (data) {
            renderTopbarOncallStatus(data || {});
        },
        function () {
            renderTopbarOncallUnknown(i18n.t("shared.oncall.unavailable"));
        }
    );
}

function startTopbarOncallStatusRefresh() {
    if (topbarOncallRefreshTimer) {
        clearInterval(topbarOncallRefreshTimer);
        topbarOncallRefreshTimer = null;
    }

    loadTopbarOncallStatus();

    topbarOncallRefreshTimer = setInterval(function () {
        loadTopbarOncallStatus();
    }, 60000);
}
