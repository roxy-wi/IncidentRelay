function alertClassificationBadge(classification, label) {
    const variants = {
        incident: "danger",
        false_positive: "orange",
        duplicate: "primary",
        known_issue: "warning",
        no_action_required: "success",
        planned_activity: "accent",
        test_alert: "info",
        other: "muted",
    };
    return uiStatusBadge(label, variants[classification] || "muted");
}

function renderAlertReview(alert, modal) {
    const section = modal.find("#alert-review");
    const form = section.find("[data-review-form]");
    const field = name => form.find('[name="' + name + '"]');
    const outcome = field("classification");
    const mode = field("mode");
    const target = field("target");
    const edit = section.find("[data-review-edit]");
    const t = key => i18n.t("alert_details.review." + key);
    function destroyPicker() {
        destroyTomSelectIfExists(target[0]);
        target.empty();
    }
    destroyPicker();
    destroyTomSelectIfExists(outcome[0]);
    section.addClass("is-hidden");
    form.addClass("is-hidden");
    if (!alert?.review) return;

    const review = alert.review;
    const url = "/api/alert-groups/" + alert.id + "/classification";
    const result = section.removeClass("is-hidden").find("[data-review-summary]").empty()
        .append(alertClassificationBadge(review.classification, t(review.classification || "none")));
    if (review.classified_by) {
        result.append(UserAppearance.label({
            id: review.classified_by_id, username: review.classified_by, color: review.classified_by_color,
        }));
    }
    if (review.classified_at) {
        result.append($("<time>").attr("datetime", review.classified_at).text(formatDateTimeMinutes(review.classified_at)));
    }
    const reference = review.incident_id || review.canonical_group_id;
    if (reference) {
        result.append($("<a>")
            .attr("href", (review.incident_id ? "/incidents/" : "/alerts/") + reference)
            .text(t(review.incident_id ? "incident_target" : "group_target") + " #" + reference));
    } else if (["duplicate", "incident"].includes(review.classification)) {
        result.append($("<span>").text(t("unavailable")));
    }
    const error = form.find("[data-review-error]").empty().addClass("is-hidden");
    const showError = message => error.text(message).removeClass("is-hidden");
    section.find("[data-review-note]").text(review.note || "").toggle(!!review.note);
    edit.toggle(review.can_classify).attr("aria-expanded", "false").text(t("edit")).off("click");
    if (!review.can_classify) return;

    function fillPicker(selectedId) {
        destroyPicker();
        const kind = mode.val();
        const needsId = kind === "incident_target" || kind === "group_target";
        form.find("[data-review-picker]").toggle(needsId);
        if (!needsId) return;
        const base = kind === "group_target" ? "/api/alert-groups" : "/api/incidents";
        initSearchableSelect(target, {
            allowEmptyOption: false,
            valueField: "id", labelField: "label", searchField: ["label"], maxItems: 1,
            options: selectedId ? [{id: selectedId, label: "#" + selectedId}] : [],
            items: selectedId ? [selectedId] : [], loadThrottle: 250,
            placeholder: t("choose"),
            shouldLoad: query => query.trim().length >= 2 || /^#?\d+$/.test(query.trim()),
            load: function (query, callback) {
                const term = query.trim();
                const id = /^#?(\d+)$/.exec(term);
                const params = new URLSearchParams({search: term, page_size: "40"});
                if (outcome.val() === "incident") {
                    params.set("team_id", alert.team_id);
                    ["declared", "investigating", "identified", "monitoring", "resolved"].forEach(
                        status => params.append("status", status)
                    );
                }
                apiGet(id ? base + "/" + id[1] : base + "?" + params, data => {
                    if (target[0].tomselect !== this) return;
                    const rows = id ? [data] : data.items;
                    const options = rows.filter(row => kind === "group_target" ? row.id !== alert.id :
                        outcome.val() !== "incident" || (row.team_id === alert.team_id &&
                            !["closed", "cancelled"].includes(row.workflow_status)));
                    callback(options.map(row => ({id: row.id, label: "#" + row.id + " " + row.title})));
                }, xhr => { callback(); if (xhr.status !== 404 && xhr.status !== 403) showApiError(xhr); });
            },
        });
    }

    function fillModes(initial) {
        const value = outcome.val();
        const modes = value === "duplicate" ? ["group_target", "incident_target"]
            : value === "incident" && canRespondObject(alert) ? ["incident_target", "create_incident"] : [];
        mode.empty();
        modes.forEach(key => mode.append($("<option>").val(key).text(t(key))));
        if (initial && review.incident_id) mode.val("incident_target");
        form.find("[data-review-mode]").toggle(modes.length > 0);
        fillPicker(initial ? review.incident_id || review.canonical_group_id : null);
    }
    outcome.find("option[value=incident]").prop("disabled", !canRespondObject(alert) && review.classification !== "incident");
    mode.off("change").on("change", () => fillPicker(null));
    edit.on("click", () => {
        const opening = form.hasClass("is-hidden");
        form.toggleClass("is-hidden", !opening);
        edit.attr("aria-expanded", String(opening)).text(opening ? i18n.t("common.cancel") : t("edit"));
        if (!opening) {
            destroyTomSelectIfExists(outcome[0]);
            destroyPicker();
            return;
        }
        error.empty().addClass("is-hidden");
        outcome.val(review.classification || "");
        field("note").val(review.note || "");
        const badgeOption = data => $("<div>").append(alertClassificationBadge(data.value, data.text))[0];
        initSearchableSelect(outcome, {
            allowEmptyOption: false, placeholder: t("none"),
            render: {option: badgeOption, item: badgeOption},
            onChange: () => fillModes(false),
        });
        fillModes(true);
    });

    function submit(clear) {
        const data = {version: review.version, classification: outcome.val(), note: field("note").val()};
        if (["group_target", "incident_target"].includes(mode.val())) {
            const id = Number(target.val());
            if (!clear && !id) { showError(t("choose")); return; }
            data[mode.val() === "group_target" ? "canonical_group_id" : "incident_id"] = id;
        } else if (mode.val() === "create_incident") {
            data.create_incident = true;
        } else if (!mode.val() && data.classification === "incident" && review.classification === "incident") {
            data.incident_id = review.incident_id;
        }
        form.find("button").add(edit).prop("disabled", true);
        const reload = () => {
            if (currentDetailsAlertId === alert.id && modal.hasClass("is-open")) showAlertDetails(alert.id);
        };
        const failed = xhr => {
            if (currentDetailsAlertId !== alert.id || !modal.hasClass("is-open")) return;
            form.find("button").add(edit).prop("disabled", false);
            showError(xhr.status === 403 || xhr.status === 404 ? t("unavailable") : getApiErrorMessage(xhr));
            if (xhr.status === 409) {
                error.append(" ", $("<button>").attr("type", "button").addClass("btn btn-secondary btn-sm")
                    .text(t("reload")).on("click", reload));
            }
        };
        if (clear) apiDelete(url + "?version=" + review.version, reload, failed);
        else apiPut(url, data, reload, failed);
    }
    form.find("button").add(edit).prop("disabled", false);
    form.off("submit").on("submit", event => { event.preventDefault(); submit(false); });
    form.find("[data-review-clear]").toggle(!!review.classification).off("click").on("click", () => submit(true));
}
