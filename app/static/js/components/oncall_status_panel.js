function oncallStatusPillClass(status) {
    return {
        primary: "status-active",
        escalation: "status-scheduled",
        idle: "status-neutral",
        unknown: "status-neutral"
    }[status || "unknown"] || "status-neutral";
}

function renderOncallStatusPill(data) {
    const status = oncallStatusKind(data || {});

    const textByStatus = {
        primary: i18n.t("profile.oncall.primary_now"),
        escalation: i18n.t("profile.oncall.backup_now"),
        idle: i18n.t("profile.oncall.not_oncall")
    };

    return $("<span>")
        .addClass("status-pill")
        .addClass(oncallStatusPillClass(status))
        .text(textByStatus[status] || i18n.t("profile.common.unknown"));
}

function renderOncallPrimarySlotCard(slot) {
    const card = $("<div>").addClass("slot-card");

    card.append(
        $("<div>")
            .addClass("slot-title")
            .text(oncallDisplayName(slot.team_name, slot.team_slug, i18n.t("profile.oncall.team")))
    );

    card.append(
        $("<div>")
            .addClass("slot-meta")
            .text([
                slot.rotation_name || i18n.t("profile.oncall.rotation", {id: slot.rotation_id}),
                slot.layer_name || (slot.type === "override" ? i18n.t("profile.oncall.override") : i18n.t("profile.oncall.layer")),
                slot.timezone || "UTC"
            ].filter(Boolean).join(" · "))
    );

    card.append(
        $("<div>")
            .addClass("slot-time")
            .text(
                oncallFormatDate(slot.start, slot.timezone)
                + " → "
                + oncallFormatDate(slot.end, slot.timezone)
            )
    );

    if (slot.type === "override" && slot.reason) {
        card.append(
            $("<div>")
                .addClass("slot-reason")
                .text(slot.reason)
        );
    }

    return card;
}

function renderOncallEscalationCard(item) {
    const card = $("<div>").addClass("slot-card escalation-card");

    card.append(
        $("<div>")
            .addClass("slot-title")
            .text(oncallDisplayName(item.team_name, item.team_slug, item.team_display || i18n.t("profile.oncall.team")))
    );

    card.append(
        $("<div>")
            .addClass("slot-meta")
            .text([
                item.policy_name || i18n.t("profile.oncall.policy", {id: item.policy_id}),
                i18n.t("profile.oncall.level", {level: item.level || "-"}),
                item.delay_seconds ? i18n.t("profile.oncall.after_minutes", {count: Math.round(Number(item.delay_seconds) / 60)}) : null
            ].filter(Boolean).join(" · "))
    );

    if (item.kind === "rotation" && item.start && item.end) {
        card.append(
            $("<div>")
                .addClass("slot-time")
                .text(
                    (item.rotation_name || i18n.t("profile.oncall.rotation", {id: item.rotation_id}))
                    + " · "
                    + oncallFormatDate(item.start, item.timezone)
                    + " → "
                    + oncallFormatDate(item.end, item.timezone)
                )
        );
    } else {
        card.append(
            $("<div>")
                .addClass("slot-time")
                .text(i18n.t("profile.oncall.direct_target"))
        );
    }

    return card;
}

function renderOncallSection(title, items, renderer, emptyText) {
    const section = $("<section>").addClass("section");

    section.append(
        $("<div>")
            .addClass("section-title")
            .text(title)
    );

    const list = $("<div>").addClass("list");

    if (!items.length) {
        list.append(
            $("<div>")
                .addClass("empty")
                .text(emptyText)
        );
    } else {
        items.forEach(function (item) {
            list.append(renderer(item));
        });
    }

    section.append(list);

    return section;
}

function renderOncallStatusPanel(target, data) {
    const root = $(target);
    const current = oncallAsArray(data && data.current);
    const next = oncallAsArray(data && data.next);
    const escalationCurrent = oncallAsArray(data && data.escalation_current);
    const escalationNext = oncallAsArray(data && data.escalation_next);

    root.empty();

    const header = $("<div>").addClass("panel-header");

    header.append(renderOncallStatusPill(data || {}));

    header.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-small")
            .text(i18n.t("profile.actions.refresh"))
            .on("click", function () {
                loadOncallStatusPanel(root);
            })
    );

    root.append(header);

    root.append(
        renderOncallSection(
            i18n.t("profile.oncall.current_primary"),
            current,
            renderOncallPrimarySlotCard,
            i18n.t("profile.oncall.no_current_primary")
        )
    );

    root.append(
        renderOncallSection(
            i18n.t("profile.oncall.current_backup"),
            escalationCurrent,
            renderOncallEscalationCard,
            i18n.t("profile.oncall.no_current_backup")
        )
    );

    root.append(
        renderOncallSection(
            i18n.t("profile.oncall.next_primary"),
            next,
            renderOncallPrimarySlotCard,
            i18n.t("profile.oncall.no_next_primary")
        )
    );

    root.append(
        renderOncallSection(
            i18n.t("profile.oncall.next_backup"),
            escalationNext,
            renderOncallEscalationCard,
            i18n.t("profile.oncall.no_next_backup")
        )
    );
}

function loadOncallStatusPanel(target, options) {
    const root = $(target);
    const opts = options || {};
    const days = opts.days || 30;
    const endpoint = opts.endpoint || "/api/profile/oncall";

    root.empty().append(
        $("<div>")
            .addClass("empty")
            .text(i18n.t("profile.oncall.loading"))
    );

    apiGet(endpoint + "?days=" + encodeURIComponent(days), function (data) {
        renderOncallStatusPanel(root, data || {});
    });
}
