let rotationsCache = [];
let selectedRotationForLayers = null;
let selectedRotationNameForLayers = "";
let rotationLayersCache = [];
let rotationLayerEligibleUsersCache = [];
let layerMembersCache = {};
let layerRestrictionsCache = {};
let expandedLayerId = null;
let rotationOverridesAfterChange = null;
let selectedRotationDetailsId = null;

const WEEKDAY_LABELS = [
    i18n.t("rotations.weekday.monday"),
    i18n.t("rotations.weekday.tuesday"),
    i18n.t("rotations.weekday.wednesday"),
    i18n.t("rotations.weekday.thursday"),
    i18n.t("rotations.weekday.friday"),
    i18n.t("rotations.weekday.saturday"),
    i18n.t("rotations.weekday.sunday")
];

function rotationUnitLabel(unit) {
    const labels = {
        minutes: "rotations.units.minutes_lower",
        hours: "rotations.units.hours_lower",
        days: "rotations.units.days_lower",
        weeks: "rotations.units.weeks_lower"
    };

    return labels[unit] ? i18n.t(labels[unit]) : (unit || "-");
}

function rotationActionLabel(key) {
    return i18n.t("rotations.actions." + key);
}


function getBrowserTimezones() {
    return window.AppTimezones.getBrowserTimezones();
}

function fillTimezoneSelect(selector, selectedTimezone) {
    window.AppTimezones.fillSelect(selector, selectedTimezone);
}

function initTimezoneSelect(selector, selectedTimezone, dropdownParent) {
    window.AppTimezones.initSelect(selector, selectedTimezone, dropdownParent);
}

function setTimezoneSelectValue(selector, value) {
    window.AppTimezones.setSelectValue(selector, value);
}

function getTimezoneSelectValue(selector) {
    return window.AppTimezones.getSelectValue(selector);
}

function datetimeLocalNowForTimezone(timezone) {
    return window.AppTimezones.datetimeLocalNow(timezone);
}

function findRotationInCache(rotationId) {
    return rotationsCache.find(function (item) {
        return Number(item.id) === Number(rotationId);
    }) || null;
}

function rememberRotationInCache(rotation) {
    const rotationId = Number(rotation.id);
    const index = rotationsCache.findIndex(function (item) {
        return Number(item.id) === rotationId;
    });

    if (index >= 0) {
        rotationsCache[index] = rotation;
        return;
    }

    rotationsCache.push(rotation);
}

function findSelectedLayerRotation() {
    return findRotationInCache(selectedRotationForLayers);
}

function closeRotationLayersModal() {
    closeAppModal("#rotation-layers-modal");

    selectedRotationForLayers = null;
    selectedRotationNameForLayers = "";
    rotationLayersCache = [];
    rotationLayerEligibleUsersCache = [];
    layerMembersCache = {};
    layerRestrictionsCache = {};
    expandedLayerId = null;

    $("#rotation-layer-cards")
        .empty()
        .append(
            $("<div>")
                .addClass("empty-cell")
                .text(i18n.t("rotations.empty.none_selected"))
        );
}

function selectRotationLayers(rotationId) {
    const rotation = findRotationInCache(rotationId);

    if (!rotation) {
        showAppError(i18n.t("rotations.errors.not_found"));
        return;
    }

    selectedRotationForLayers = rotation.id;
    selectedRotationNameForLayers = rotation.name || i18n.t("rotations.labels.rotation_number", {id: rotation.id});
    rotationLayersCache = [];
    rotationLayerEligibleUsersCache = [];
    layerMembersCache = {};
    layerRestrictionsCache = {};
    expandedLayerId = null;

    $("#rotation-layers-title").text(
        i18n.t("rotations.layers.title_named", {name: selectedRotationNameForLayers})
    );
    openAppModal("#rotation-layers-modal");

    loadEligibleUsersForLayerCards(rotation.id, function () {
        loadRotationLayerCards(rotation.id);
    });
}

function loadEligibleUsersForLayerCards(rotationId, callback) {
    apiGet("/api/rotations/" + rotationId + "/eligible-users", function (users) {
        rotationLayerEligibleUsersCache = asArray(users);

        if (typeof callback === "function") {
            callback(rotationLayerEligibleUsersCache);
        }
    });
}

function loadRotationLayerCards(rotationId, callback) {
    const container = $("#rotation-layer-cards");

    container
        .empty()
        .append(
            $("<div>")
                .addClass("layer-card-loading")
                .text(i18n.t("rotations.layers.loading"))
        );

    apiGet("/api/rotations/" + rotationId + "/layers", function (layers) {
        rotationLayersCache = asArray(layers).sort(function (a, b) {
            return Number(a.priority || 0) - Number(b.priority || 0);
        });

        loadAllLayerCardDetails(function () {
            renderRotationLayerCards();

            if (typeof callback === "function") {
                callback();
            }
        });
    });
}

function loadAllLayerCardDetails(callback) {
    if (!rotationLayersCache.length) {
        if (typeof callback === "function") {
            callback();
        }
        return;
    }

    let pending = rotationLayersCache.length * 2;

    function doneOne() {
        pending -= 1;

        if (pending <= 0 && typeof callback === "function") {
            callback();
        }
    }

    rotationLayersCache.forEach(function (layer) {
        apiGet("/api/rotations/layers/" + layer.id + "/members", function (members) {
            layerMembersCache[layer.id] = asArray(members);
            doneOne();
        });

        apiGet("/api/rotations/layers/" + layer.id + "/restrictions", function (restrictions) {
            layerRestrictionsCache[layer.id] = asArray(restrictions).map(function (item) {
                return {
                    weekday: item.weekday,
                    start_time: item.start_time,
                    end_time: item.end_time
                };
            });
            doneOne();
        });
    });
}

function loadOneLayerCardDetails(layerId, callback) {
    let pending = 2;

    function doneOne() {
        pending -= 1;

        if (pending <= 0 && typeof callback === "function") {
            callback();
        }
    }

    apiGet("/api/rotations/layers/" + layerId + "/members", function (members) {
        layerMembersCache[layerId] = asArray(members);
        doneOne();
    });

    apiGet("/api/rotations/layers/" + layerId + "/restrictions", function (restrictions) {
        layerRestrictionsCache[layerId] = asArray(restrictions).map(function (item) {
            return {
                weekday: item.weekday,
                start_time: item.start_time,
                end_time: item.end_time
            };
        });
        doneOne();
    });
}

function renderRotationLayerCards() {
    const container = $("#rotation-layer-cards");

    container.find("select.js-user-select").each(function () {
        destroyTomSelectIfExists(this);
    });

    container.empty();

    if (!rotationLayersCache.length) {
        container.append(
            $("<div>")
                .addClass("empty-cell")
                .text(i18n.t("rotations.layers.none"))
        );
        return;
    }

    rotationLayersCache.forEach(function (layer, index) {
        container.append(renderRotationLayerCard(layer, index + 1));
        updateLayerCadenceVisibility(layer.id);
    });

    initUserTomSelects(container);
    initLayerTimezoneSelects();
}

function renderRotationLayerCard(layer, number) {
    const card = $("<div>")
        .addClass("rotation-layer-card")
        .toggleClass("is-editing", Number(expandedLayerId) === Number(layer.id))
        .toggleClass("is-disabled", !layer.enabled)
        .attr("data-layer-id", layer.id);

    card.append(renderLayerCardHeader(layer, number));
    card.append(renderLayerSummary(layer));

    const editor = $("<div>").addClass("rotation-layer-editor");
    editor.append(renderLayerSettingsEditor(layer));
    editor.append(renderLayerMembersEditor(layer));
    editor.append(renderLayerRestrictionsEditor(layer));
    card.append(editor);

    return card;
}

function renderLayerCardHeader(layer, number) {
    const header = $("<div>").addClass("rotation-layer-card-header");

    header.append(
        $("<div>")
            .addClass("rotation-layer-number")
            .text(number)
    );

    header.append(
        $("<div>")
            .addClass("rotation-layer-title")
            .append($("<strong>").text(layer.name || i18n.t("rotations.layers.unnamed")))
            .append(
                $("<span>").text(
                    i18n.t("rotations.layers.priority", {value: Number(layer.priority || 0)}) +
                    " · " +
                    (layer.enabled
                        ? i18n.t("rotations.layers.enabled")
                        : i18n.t("rotations.layers.disabled")) +
                    " · " +
                    (layer.timezone || "UTC")
                )
            )
    );

    const actions = $("<div>").addClass("rotation-layer-header-actions");

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-small")
            .text(
                Number(expandedLayerId) === Number(layer.id)
                    ? i18n.t("rotations.layers.collapse")
                    : i18n.t("rotations.actions.edit")
            )
            .on("click", function () {
                toggleLayerEditor(layer.id);
            })
    );

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-danger btn-small")
            .text(i18n.t("rotations.actions.delete"))
            .on("click", function () {
                deleteRotationLayer(layer.id);
            })
    );

    header.append(actions);

    return header;
}

function renderLayerSummary(layer) {
    const summary = $("<div>").addClass("rotation-layer-summary");

    summary.append(
        $("<div>")
            .addClass("rotation-layer-summary-item")
            .append($("<span>").text(i18n.t("rotations.layers.who_rotates")))
            .append($("<strong>").html(formatLayerMembersSummary(layer.id)))
    );

    summary.append(
        $("<div>")
            .addClass("rotation-layer-summary-item")
            .append($("<span>").text(i18n.t("rotations.layers.rotation")))
            .append($("<strong>").text(formatLayerCadence(layer)))
    );

    summary.append(
        $("<div>")
            .addClass("rotation-layer-summary-item")
            .append($("<span>").text(i18n.t("rotations.layers.active")))
            .append($("<strong>").html(formatLayerRestrictionsSummary(layer.id)))
    );

    return summary;
}

function formatLayerMembersSummary(layerId) {
    const members = asArray(layerMembersCache[layerId])
        .filter(function (member) {
            return member.active !== false;
        })
        .sort(function (a, b) {
            return Number(a.position || 0) - Number(b.position || 0);
        });

    if (!members.length) {
        return i18n.t("rotations.layers.no_users");
    }

    return members.map(function (member) {
        return escapeHtml(
            member.display_name
            || member.username
            || i18n.t("rotations.layers.user_number", {id: member.user_id})
        );
    }).join(" → ");
}

function formatLayerCadence(layer) {
    const type = layer.rotation_type || "daily";
    const handoff = layer.handoff_time || "09:00";
    const timezone = layer.timezone || "UTC";

    if (type === "weekly") {
        const weekday = layer.handoff_weekday === null || layer.handoff_weekday === undefined
            ? i18n.t("rotations.weekday.monday")
            : weekdayLabel(layer.handoff_weekday);

        return i18n.t("rotations.cadence.weekly_format", {
            weekday: weekday,
            time: handoff,
            timezone: timezone
        });
    }

    if (type === "custom") {
        return i18n.t("rotations.cadence.every", {
            value: layer.interval_value || 1,
            unit: rotationUnitLabel(layer.interval_unit || "days"),
            timezone: timezone
        });
    }

    return i18n.t("rotations.cadence.daily_format", {
        time: handoff,
        timezone: timezone
    });
}

function formatLayerRestrictionsSummary(layerId) {
    const restrictions = asArray(layerRestrictionsCache[layerId]);

    if (!restrictions.length) {
        return "24/7";
    }

    const parts = restrictions.slice(0, 4).map(function (item) {
        return escapeHtml(
            weekdayLabel(item.weekday) + " " + item.start_time + "-" + item.end_time
        );
    });

    if (restrictions.length > 4) {
        parts.push(i18n.t("rotations.layers.more", {
            count: restrictions.length - 4
        }));
    }

    return parts.join("<br>");
}

function renderLayerSettingsEditor(layer) {
    const section = $("<section>").addClass("layer-editor-section");

    section.append($("<h4>").text(i18n.t("rotations.layers.when_title")));
    section.append(
        $("<div>")
            .addClass("layer-editor-section-subtitle")
            .text(i18n.t("rotations.layers.when_hint"))
    );

    const grid = $("<div>").addClass("layer-settings-grid");

    grid.append(
        layerTextField(
            layer.id,
            "name",
            i18n.t("rotations.form.name"),
            layer.name || ""
        ).addClass("layer-settings-col-4")
    );

    grid.append(
        layerNumberField(
            layer.id,
            "priority",
            i18n.t("rotations.form.priority"),
            layer.priority || 0,
            0
        ).addClass("layer-settings-col-2")
    );

    grid.append(
        $("<div>")
            .addClass("app-field layer-settings-col-6")
            .append($("<label>").text(i18n.t("rotations.layers.description")))
            .append(
                $("<textarea>")
                    .addClass("input")
                    .attr("rows", 2)
                    .attr("data-layer-field", "description")
                    .val(layer.description || "")
            )
    );

    grid.append(
        $("<div>")
            .addClass("app-field layer-settings-col-3")
            .append($("<label>").text(i18n.t("rotations.layers.starts_at")))
            .append(
                $("<input>")
                    .addClass("input")
                    .attr("type", "datetime-local")
                    .attr("data-layer-field", "start_at")
                    .val(isoToDatetimeLocal(layer.start_at))
            )
    );

    grid.append(
        $("<div>")
            .addClass("app-field layer-settings-col-3")
            .append($("<label>").text(i18n.t("rotations.layers.cadence")))
            .append(
                $("<select>")
                    .addClass("input")
                    .attr("data-layer-field", "rotation_type")
                    .append($("<option>").val("daily").text(i18n.t("rotations.cadence.daily_handoff")))
                    .append($("<option>").val("weekly").text(i18n.t("rotations.cadence.weekly_handoff")))
                    .append($("<option>").val("custom").text(i18n.t("rotations.cadence.custom_interval")))
                    .val(layer.rotation_type || "daily")
            )
    );

    grid.append(
        $("<div>")
            .addClass("app-field layer-settings-col-2")
            .append($("<label>").text(i18n.t("rotations.form.handoff_time")))
            .append(
                $("<input>")
                    .addClass("input")
                    .attr("type", "time")
                    .attr("data-layer-field", "handoff_time")
                    .val(layer.handoff_time || "09:00")
            )
    );

    grid.append(
        $("<div>")
            .addClass("app-field layer-weekly-options layer-settings-col-4")
            .append($("<label>").text(i18n.t("rotations.form.weekday")))
            .append(
                $("<select>")
                    .addClass("input")
                    .attr("data-layer-field", "handoff_weekday")
                    .append($("<option>").val("0").text(i18n.t("rotations.weekday.monday")))
                    .append($("<option>").val("1").text(i18n.t("rotations.weekday.tuesday")))
                    .append($("<option>").val("2").text(i18n.t("rotations.weekday.wednesday")))
                    .append($("<option>").val("3").text(i18n.t("rotations.weekday.thursday")))
                    .append($("<option>").val("4").text(i18n.t("rotations.weekday.friday")))
                    .append($("<option>").val("5").text(i18n.t("rotations.weekday.saturday")))
                    .append($("<option>").val("6").text(i18n.t("rotations.weekday.sunday")))
                    .val(String(
                        layer.handoff_weekday === null || layer.handoff_weekday === undefined
                            ? 0
                            : layer.handoff_weekday
                    ))
            )
    );

    grid.append(
        $("<div>")
            .addClass("app-field layer-custom-options layer-settings-col-2")
            .append($("<label>").text(i18n.t("rotations.form.every")))
            .append(
                $("<input>")
                    .addClass("input")
                    .attr("type", "number")
                    .attr("min", "1")
                    .attr("data-layer-field", "interval_value")
                    .val(layer.interval_value || 1)
            )
    );

    grid.append(
        $("<div>")
            .addClass("app-field layer-custom-options layer-settings-col-2")
            .append($("<label>").text(i18n.t("rotations.form.unit")))
            .append(
                $("<select>")
                    .addClass("input")
                    .attr("data-layer-field", "interval_unit")
                    .append($("<option>").val("minutes").text(i18n.t("rotations.units.minutes_lower")))
                    .append($("<option>").val("hours").text(i18n.t("rotations.units.hours_lower")))
                    .append($("<option>").val("days").text(i18n.t("rotations.units.days_lower")))
                    .append($("<option>").val("weeks").text(i18n.t("rotations.units.weeks_lower")))
                    .val(layer.interval_unit || "days")
            )
    );

    grid.append(
        layerTimezoneField(layer.id, layer.timezone || "UTC")
            .addClass("layer-settings-col-6")
    );

    grid.append(
        $("<div>")
            .addClass("app-field layer-settings-col-6")
            .append(
                $("<label>")
                    .addClass("layer-settings-checkbox")
                    .append(
                        $("<input>")
                            .attr("type", "checkbox")
                            .attr("data-layer-field", "enabled")
                            .prop("checked", layer.enabled !== false)
                    )
                    .append(
                        $("<span>")
                            .append($("<strong>").text(i18n.t("rotations.layers.enabled")))
                            .append($("<small>").text(i18n.t("rotations.layers.enabled_hint")))
                    )
            )
    );

    section.append(grid);

    section.append(
        $("<div>")
            .addClass("layer-editor-actions")
            .append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("btn btn-primary")
                    .text(i18n.t("rotations.layers.save"))
                    .on("click", function () {
                        saveRotationLayerFromCard(layer.id);
                    })
            )
    );

    return section;
}

function layerTimezoneField(layerId, value) {
    const select = $("<select>")
        .addClass("input timezone-select")
        .attr("data-layer-field", "timezone")
        .attr("data-layer-timezone-select", layerId);

    getBrowserTimezones().forEach(function (zone) {
        select.append(
            $("<option>")
                .val(zone)
                .text(zone)
        );
    });

    if (
        value &&
        !select.find("option").filter(function () {
            return $(this).val() === String(value);
        }).length
    ) {
        select.append(
            $("<option>")
                .val(value)
                .text(value)
        );
    }

    select.val(value || "UTC");

    return $("<div>")
        .addClass("app-field")
        .append($("<label>").text(i18n.t("rotations.form.timezone")))
        .append(select);
}

function renderLayerMembersEditor(layer) {
    const section = $("<section>").addClass("layer-editor-section");

    section.append($("<h4>").text(i18n.t("rotations.layers.who_title")));

    section.append(
        $("<div>")
            .addClass("layer-editor-section-subtitle")
            .text(i18n.t("rotations.layers.who_hint"))
    );

    const currentMembers = asArray(layerMembersCache[layer.id])
        .filter(function (member) {
            return member.active !== false && !member.ends_at;
        })
        .sort(function (a, b) {
            return Number(a.position || 0) - Number(b.position || 0);
        });

    const activeUserIds = new Set(
        currentMembers.map(function (member) {
            return Number(member.user_id);
        })
    );

    const availableUsers = asArray(rotationLayerEligibleUsersCache)
        .filter(function (user) {
            return !activeUserIds.has(Number(user.user_id));
        })
        .sort(function (a, b) {
            const left = (a.display_name || a.username || "").toLowerCase();
            const right = (b.display_name || b.username || "").toLowerCase();

            return left.localeCompare(right);
        });

    const addRow = $("<div>").addClass("layer-member-add-grid");

    const userSelect = $("<select>")
        .addClass("js-user-select")
        .attr("data-layer-member-user", layer.id)
        .attr("data-placeholder", i18n.t("rotations.layers.select_user"));

    if (!availableUsers.length) {
        userSelect.append(
            $("<option>")
                .val("")
                .text(
                    currentMembers.length
                        ? i18n.t("rotations.layers.all_users_added")
                        : i18n.t("rotations.layers.no_team_members")
                )
        );
    } else {
        userSelect.append(
            $("<option>")
                .val("")
                .text("")
        );

        availableUsers.forEach(function (user) {
            userSelect.append(
                $("<option>")
                    .val(String(user.user_id))
                    .text(getUserOptionText(user))
            );
        });
    }

    addRow.append(
        $("<div>")
            .addClass("app-field")
            .append($("<label>").text(i18n.t("rotations.layers.user")))
            .append(userSelect)
    );

    addRow.append(
        $("<div>")
            .addClass("app-field")
            .append($("<label>").text(i18n.t("rotations.layers.position")))
            .append(
                $("<input>")
                    .addClass("input")
                    .attr("type", "number")
                    .attr("min", "0")
                    .attr("data-layer-member-position", layer.id)
                    .val(nextLayerMemberPosition(layer.id))
            )
    );

    addRow.append(
        $("<div>")
            .addClass("app-field")
            .append(
                $("<label>")
                    .text(i18n.t("rotations.overrides.starts"))
                    .append(
                        $("<small>")
                            .addClass("muted")
                            .text(" · " + (layer.timezone || "UTC"))
                    )
            )
            .append(
                $("<input>")
                    .addClass("input")
                    .attr("type", "datetime-local")
                    .attr("data-layer-member-starts-at", layer.id)
                    .val(datetimeLocalNowForTimezone(layer.timezone || "UTC"))
            )
    );

    addRow.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn")
            .prop("disabled", !availableUsers.length)
            .text(i18n.t("rotations.layers.add_user"))
            .on("click", function () {
                addLayerMemberFromCard(layer.id);
            })
    );

    section.append(addRow);

    const list = $("<div>").addClass("layer-members-list");

    if (!currentMembers.length) {
        list.append(
            $("<div>")
                .addClass("layer-empty-box")
                .text(i18n.t("rotations.layers.no_active_users"))
        );
    } else {
        currentMembers.forEach(function (member) {
            list.append(renderLayerMemberRow(layer.id, member));
        });
    }

    section.append(list);

    return section;
}

function renderLayerMemberRow(layerId, member) {
    const row = $("<div>").addClass("layer-member-row");
    const starts = member.starts_at
        ? i18n.t("rotations.layers.starts_suffix", {
            value: formatDateTime(member.starts_at)
        })
        : "";

    row.append(
        $("<div>")
            .addClass("layer-member-name")
            .append(
                $("<strong>").text(
                    member.display_name
                    || member.username
                    || i18n.t("rotations.layers.user_number", {id: member.user_id})
                )
            )
            .append(
                $("<small>").text(
                    i18n.t("rotations.layers.member_meta", {
                        user_id: member.user_id,
                        member_id: member.id,
                        starts: starts
                    })
                )
            )
    );

    row.append(
        $("<input>")
            .addClass("input")
            .attr("type", "number")
            .attr("min", "0")
            .attr("data-member-position", member.id)
            .val(member.position || 0)
    );

    const actions = $("<div>").addClass("table-actions");

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-small")
            .text(i18n.t("rotations.layers.save_position"))
            .on("click", function () {
                updateLayerMemberFromCard(layerId, member.id);
            })
    );

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-danger btn-small")
            .text(i18n.t("rotations.layers.remove"))
            .on("click", function () {
                removeLayerMemberFromCard(layerId, member.id);
            })
    );

    row.append(actions);

    return row;
}

function renderLayerRestrictionsEditor(layer) {
    const section = $("<section>").addClass("layer-editor-section");

    section.append($("<h4>").text(i18n.t("rotations.layers.active_title")));
    section.append(
        $("<div>")
            .addClass("layer-editor-section-subtitle")
            .text(i18n.t("rotations.layers.active_hint"))
    );

    const toolbar = $("<div>").addClass("layer-restrictions-toolbar");

    toolbar.append(presetButton(layer.id, "24/7", "24x7"));
    toolbar.append(presetButton(layer.id, i18n.t("rotations.layers.business_hours"), "business"));
    toolbar.append(presetButton(layer.id, i18n.t("rotations.layers.nights"), "nights"));
    toolbar.append(presetButton(layer.id, i18n.t("rotations.layers.weekend"), "weekend"));
    toolbar.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-small")
            .text(i18n.t("rotations.layers.add_window"))
            .on("click", function () {
                addRestrictionRowToCard(layer.id);
            })
    );

    section.append(toolbar);

    const list = $("<div>")
        .addClass("layer-restrictions-list")
        .attr("data-layer-restrictions-list", layer.id);

    const restrictions = asArray(layerRestrictionsCache[layer.id]);

    if (!restrictions.length) {
        list.append(
            $("<div>")
                .addClass("layer-empty-box")
                .text(i18n.t("rotations.layers.active_24x7"))
        );
    } else {
        restrictions.forEach(function (restriction, index) {
            list.append(renderLayerRestrictionRow(layer.id, restriction, index));
        });
    }

    section.append(list);

    section.append(
        $("<div>")
            .addClass("layer-editor-actions")
            .append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("btn btn-primary")
                    .text(i18n.t("rotations.layers.save_restrictions"))
                    .on("click", function () {
                        saveLayerRestrictionsFromCard(layer.id);
                    })
            )
    );

    return section;
}

function renderLayerRestrictionRow(layerId, restriction, index) {
    const row = $("<div>")
        .addClass("layer-restriction-row")
        .attr("data-restriction-row", layerId);

    const weekdaySelect = $("<select>")
        .addClass("input")
        .attr("data-restriction-weekday", index)
        .append($("<option>").val("").text(i18n.t("rotations.weekday.every_day")))
        .append($("<option>").val("0").text(i18n.t("rotations.weekday.monday")))
        .append($("<option>").val("1").text(i18n.t("rotations.weekday.tuesday")))
        .append($("<option>").val("2").text(i18n.t("rotations.weekday.wednesday")))
        .append($("<option>").val("3").text(i18n.t("rotations.weekday.thursday")))
        .append($("<option>").val("4").text(i18n.t("rotations.weekday.friday")))
        .append($("<option>").val("5").text(i18n.t("rotations.weekday.saturday")))
        .append($("<option>").val("6").text(i18n.t("rotations.weekday.sunday")));

    weekdaySelect.val(
        restriction.weekday === null || restriction.weekday === undefined
            ? ""
            : String(restriction.weekday)
    );

    row.append(weekdaySelect);

    row.append(
        $("<input>")
            .addClass("input")
            .attr("type", "time")
            .attr("data-restriction-start", index)
            .val(restriction.start_time || "09:00")
    );

    row.append(
        $("<input>")
            .addClass("input")
            .attr("type", "time")
            .attr("data-restriction-end", index)
            .val(restriction.end_time || "18:00")
    );

    row.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-danger btn-small")
            .text(i18n.t("rotations.layers.remove"))
            .on("click", function () {
                removeRestrictionRowFromCard(layerId, index);
            })
    );

    return row;
}

function layerTextField(layerId, field, label, value) {
    return $("<div>")
        .addClass("app-field")
        .append($("<label>").text(label))
        .append(
            $("<input>")
                .addClass("input")
                .attr("type", "text")
                .attr("data-layer-field", field)
                .val(value || "")
        );
}

function layerNumberField(layerId, field, label, value, minValue) {
    return $("<div>")
        .addClass("app-field")
        .append($("<label>").text(label))
        .append(
            $("<input>")
                .addClass("input")
                .attr("type", "number")
                .attr("min", String(minValue || 0))
                .attr("data-layer-field", field)
                .val(value || 0)
        );
}

function presetButton(layerId, label, preset) {
    return $("<button>")
        .attr("type", "button")
        .addClass("btn btn-small")
        .text(label)
        .on("click", function () {
            applyLayerRestrictionPreset(layerId, preset);
        });
}

function layerCard(layerId) {
    return $('.rotation-layer-card[data-layer-id="' + layerId + '"]');
}

function layerField(layerId, field) {
    return layerCard(layerId).find('[data-layer-field="' + field + '"]');
}

function collectLayerPayloadFromCard(layerId) {
    const rotation = findSelectedLayerRotation();
    const rotationType = layerField(layerId, "rotation_type").val() || "daily";

    const payload = {
        name: layerField(layerId, "name").val(),
        description: layerField(layerId, "description").val() || null,
        priority: Number(layerField(layerId, "priority").val() || 0),
        start_at: layerField(layerId, "start_at").val() || (rotation ? rotation.start_at : null),
        rotation_type: rotationType,
        interval_value: Number(layerField(layerId, "interval_value").val() || 1),
        interval_unit: layerField(layerId, "interval_unit").val() || "days",
        handoff_time: layerField(layerId, "handoff_time").val() || "09:00",
        handoff_weekday: Number(layerField(layerId, "handoff_weekday").val() || 0),
        timezone: layerField(layerId, "timezone").val() || (rotation ? rotation.timezone : "UTC"),
        enabled: layerField(layerId, "enabled").is(":checked")
    };

    if (rotationType === "daily") {
        payload.interval_value = 1;
        payload.interval_unit = "days";
    }

    if (rotationType === "weekly") {
        payload.interval_value = 1;
        payload.interval_unit = "weeks";
    }

    return payload;
}

function toggleLayerEditor(layerId) {
    if (Number(expandedLayerId) === Number(layerId)) {
        expandedLayerId = null;
        renderRotationLayerCards();
        return;
    }

    expandedLayerId = layerId;

    loadOneLayerCardDetails(layerId, function () {
        renderRotationLayerCards();
    });
}

function updateLayerCadenceVisibility(layerId) {
    const card = layerCard(layerId);
    const type = card.find('[data-layer-field="rotation_type"]').val();

    card.find(".layer-weekly-options").toggle(type === "weekly");
    card.find(".layer-custom-options").toggle(type === "custom");
}

function nextRotationLayerDefaultName() {
    const used = {};

    asArray(rotationLayersCache).forEach(function (layer) {
        const name = String((layer && layer.name) || "").trim().toLowerCase();

        if (name) {
            used[name] = true;
        }
    });

    const firstName = i18n.t("rotations.layers.new");

    if (!used[firstName.toLowerCase()]) {
        return firstName;
    }

    let index = 2;

    while (
        used[
            i18n.t("rotations.layers.new_number", {number: index}).toLowerCase()
        ]
    ) {
        index += 1;
    }

    return i18n.t("rotations.layers.new_number", {number: index});
}

function addLayerCard() {
    if (!selectedRotationForLayers) {
        showAppError(i18n.t("rotations.layers.select_first"));
        return;
    }

    const rotation = findSelectedLayerRotation();
    const nextPriority = rotationLayersCache.length
        ? Math.max.apply(null, rotationLayersCache.map(function (layer) {
            return Number(layer.priority || 0);
        })) + 10
        : 10;

    const payload = {
        name: nextRotationLayerDefaultName(rotation),
        description: null,
        priority: nextPriority,
        start_at: rotation ? rotation.start_at : null,
        rotation_type: rotation ? (rotation.rotation_type || "daily") : "daily",
        interval_value: rotation ? (rotation.interval_value || 1) : 1,
        interval_unit: rotation ? (rotation.interval_unit || "days") : "days",
        handoff_time: rotation ? (rotation.handoff_time || "09:00") : "09:00",
        handoff_weekday: rotation && rotation.handoff_weekday !== null ? rotation.handoff_weekday : 0,
        timezone: rotation ? (rotation.timezone || "UTC") : "UTC",
        enabled: true
    };

    apiPost("/api/rotations/" + selectedRotationForLayers + "/layers", payload, function (layer) {
        expandedLayerId = layer.id;
        loadRotationLayerCards(selectedRotationForLayers, function () {});
    });
}

function saveRotationLayerFromCard(layerId) {
    const payload = collectLayerPayloadFromCard(layerId);

    apiPut("/api/rotations/layers/" + layerId, payload, function () {
        expandedLayerId = layerId;
        loadRotationLayerCards(selectedRotationForLayers, function () {
            refreshRotations();
        });
    });
}

function deleteRotationLayer(layerId) {
    showAppConfirm({
        title: i18n.t("rotations.layers.delete_title"),
        message: i18n.t("rotations.layers.delete_title"),
        confirmText: i18n.t("rotations.layers.delete_confirm"),
        confirmClass: "btn-danger"
    }).done(function () {
        apiDelete("/api/rotations/layers/" + layerId, function () {
            if (Number(expandedLayerId) === Number(layerId)) {
                expandedLayerId = null;
            }

            loadRotationLayerCards(selectedRotationForLayers, function () {
                refreshRotations();
            });
        });
    });
}

function nextLayerMemberPosition(layerId) {
    const members = asArray(layerMembersCache[layerId]).filter(function (member) {
        return member.active !== false && !member.ends_at;
    });

    if (!members.length) {
        return 0;
    }

    return Math.max.apply(null, members.map(function (member) {
        return Number(member.position || 0);
    })) + 1;
}

function addLayerMemberFromCard(layerId) {
    const userId = $('[data-layer-member-user="' + layerId + '"]').val();
    const position = $('[data-layer-member-position="' + layerId + '"]').val();
    const startsAt = $('[data-layer-member-starts-at="' + layerId + '"]').val();

    if (!userId) {
        showAppError(i18n.t("rotations.layers.select_user_error"));
        return;
    }

    apiPost("/api/rotations/layers/" + layerId + "/members", {
        user_id: Number(userId),
        position: Number(position || 0),
        starts_at: startsAt || null
    }, function () {
        loadOneLayerCardDetails(layerId, function () {
            renderRotationLayerCards();
            refreshRotations();
        });
    });
}

function updateLayerMemberFromCard(layerId, memberId) {
    const position = $('[data-member-position="' + memberId + '"]').val();

    apiPut("/api/rotations/layers/members/" + memberId, {
        position: Number(position || 0),
        active: true
    }, function () {
        loadOneLayerCardDetails(layerId, function () {
            renderRotationLayerCards();
            refreshRotations();
        });
    });
}

function removeLayerMemberFromCard(layerId, memberId) {
    showAppConfirm({
        title: i18n.t("rotations.layers.remove_user_title"),
        message: i18n.t("rotations.layers.remove_user_message"),
        confirmText: i18n.t("rotations.layers.remove_user_confirm"),
        confirmClass: "btn-danger"
    }).done(function () {
        apiDelete("/api/rotations/layers/members/" + memberId, function () {
            loadOneLayerCardDetails(layerId, function () {
                renderRotationLayerCards();
                refreshRotations();
            });
        });
    });
}

function weekdayLabel(value) {
    if (value === null || value === undefined || value === "") {
        return i18n.t("rotations.weekday.every_day");
    }

    return WEEKDAY_LABELS[Number(value)] || "-";
}

function collectRestrictionsFromCard(layerId) {
    const rows = layerCard(layerId).find('[data-restriction-row="' + layerId + '"]');
    const restrictions = [];

    rows.each(function () {
        const row = $(this);
        const weekdayValue = row.find("[data-restriction-weekday]").val();

        restrictions.push({
            weekday: weekdayValue === "" ? null : Number(weekdayValue),
            start_time: row.find("[data-restriction-start]").val() || "09:00",
            end_time: row.find("[data-restriction-end]").val() || "18:00"
        });
    });

    return restrictions;
}

function refreshRestrictionDraftFromCard(layerId) {
    layerRestrictionsCache[layerId] = collectRestrictionsFromCard(layerId);
}

function addRestrictionRowToCard(layerId) {
    refreshRestrictionDraftFromCard(layerId);
    layerRestrictionsCache[layerId].push({
        weekday: null,
        start_time: "09:00",
        end_time: "18:00"
    });
    renderRotationLayerCards();
}

function removeRestrictionRowFromCard(layerId, index) {
    refreshRestrictionDraftFromCard(layerId);
    layerRestrictionsCache[layerId].splice(index, 1);
    renderRotationLayerCards();
}

function applyLayerRestrictionPreset(layerId, preset) {
    if (preset === "24x7") {
        layerRestrictionsCache[layerId] = [
            {
                weekday: null,
                start_time: "00:00",
                end_time: "00:00"
            }
        ];
    } else if (preset === "business") {
        layerRestrictionsCache[layerId] = [0, 1, 2, 3, 4].map(function (weekday) {
            return {
                weekday: weekday,
                start_time: "09:00",
                end_time: "18:00"
            };
        });
    } else if (preset === "nights") {
        layerRestrictionsCache[layerId] = [0, 1, 2, 3, 4].map(function (weekday) {
            return {
                weekday: weekday,
                start_time: "18:00",
                end_time: "09:00"
            };
        });
    } else if (preset === "weekend") {
        layerRestrictionsCache[layerId] = [
            {
                weekday: 5,
                start_time: "00:00",
                end_time: "00:00"
            },
            {
                weekday: 6,
                start_time: "00:00",
                end_time: "00:00"
            }
        ];
    }

    renderRotationLayerCards();
}

function saveLayerRestrictionsFromCard(layerId) {
    const restrictions = collectRestrictionsFromCard(layerId);

    apiPut("/api/rotations/layers/" + layerId + "/restrictions", {
        restrictions: restrictions
    }, function () {
        layerRestrictionsCache[layerId] = restrictions;

        loadOneLayerCardDetails(layerId, function () {
            renderRotationLayerCards();
            refreshRotations();
        });
    });
}

function escapeHtml(value) {
    return String(value || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function loadRotations() {
    fillTeamSelect("#rotation-team", false);
    fillUserSelect("#member-user");
    fillUserSelect("#override-user");
    updateRotationCadenceFields();
    refreshRotations();
}

function formatSeconds(seconds) {
    if (!seconds) {
        return "-";
    }

    if (seconds % 86400 === 0) {
        return (seconds / 86400) + "d";
    }

    if (seconds % 3600 === 0) {
        return (seconds / 3600) + "h";
    }

    if (seconds % 60 === 0) {
        return (seconds / 60) + "m";
    }

    return seconds + "s";
}

function rotationInitials(value) {
    return String(value || "?")
        .trim()
        .split(/\s+/)
        .slice(0, 2)
        .map(function (part) {
            return part.substring(0, 1).toUpperCase();
        })
        .join("") || "?";
}

function getRotationCurrentUser(rotation) {
    return rotation.current_oncall || rotation.current_user || rotation.current_username || "";
}
function parseRotationDate(value) {
    if (!value) {
        return null;
    }

    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return null;
    }

    return date;
}

function getRotationRuntimeStatus(rotation) {
    if (!rotation.enabled) {
        return {
            key: "disabled",
            label: i18n.t("rotations.status.disabled"),
        };
    }

    const startAt = parseRotationDate(rotation.start_at);
    if (startAt && startAt.getTime() > Date.now()) {
        return {
            key: "scheduled",
            label: i18n.t("rotations.status.scheduled"),
        };
    }

    if (getRotationCurrentUser(rotation)) {
        return {
            key: "active",
            label: i18n.t("rotations.status.active_now"),
        };
    }

    return {
        key: "idle",
        label: i18n.t("rotations.status.no_active_layer"),
    };
}

function renderRotationRuntimeStatusBadge(rotation) {
    const status = getRotationRuntimeStatus(rotation);

    if (status.key === "active") {
        return renderStatusBadge(
            true,
            i18n.t("rotations.status.active_now"),
            i18n.t("rotations.status.disabled")
        );
    }

    if (status.key === "disabled") {
        return renderStatusBadge(
            false,
            i18n.t("rotations.status.active_now"),
            i18n.t("rotations.status.disabled")
        );
    }

    return $("<span>")
        .addClass("status-pill")
        .addClass(status.key === "scheduled" ? "status-scheduled" : "status-neutral")
        .text(status.label);
}
function getRotationSearchText(rotation) {
    const runtimeStatus = getRotationRuntimeStatus(rotation);

    return [
        rotation.id,
        rotation.team_slug,
        rotation.team_name,
        rotation.name,
        rotation.description,
        rotation.rotation_type,
        rotation.handoff_time,
        getRotationCurrentUser(rotation),
        rotation.enabled ? "enabled" : "disabled",
        runtimeStatus.key,
        runtimeStatus.label
    ].join(" ").toLowerCase();
}

function getFilteredRotations() {
    const query = String($("#rotations-search").val() || "").trim().toLowerCase();
    const status = String($("#rotations-status-filter").val() || "");

    return rotationsCache.filter(function (rotation) {
        const runtimeStatus = getRotationRuntimeStatus(rotation);
        if (status === "active" && runtimeStatus.key !== "active") {
            return false;
        }
        if (status === "inactive" && runtimeStatus.key !== "disabled") {
            return false;
        }
        if (status === "scheduled" && runtimeStatus.key !== "scheduled") {
            return false;
        }

        if (!query) {
            return true;
        }

        return getRotationSearchText(rotation).indexOf(query) !== -1;
    });
}

function renderRotationsSummary(rotations) {
    rotations = Array.isArray(rotations) ? rotations : [];

    let active = 0;
    let oncall = 0;
    let reminders = 0;

    rotations.forEach(function (rotation) {
        if (getRotationRuntimeStatus(rotation).key === "active") {
            active += 1;
        }

        if (getRotationCurrentUser(rotation)) {
            oncall += 1;
        }

        if (Number(rotation.reminder_interval_seconds || 0) > 0) {
            reminders += 1;
        }
    });

    $("#rotations-summary-total").text(rotations.length);
    $("#rotations-summary-active").text(active);
    $("#rotations-summary-oncall").text(oncall);
    $("#rotations-summary-reminders").text(reminders);
}
function reminderValueToSeconds() {
    const value = Number($("#rotation-reminder-value").val() || 5);
    const unit = $("#rotation-reminder-unit").val();

    if (unit === "days") {
        return value * 86400;
    }

    if (unit === "hours") {
        return value * 3600;
    }

    return value * 60;
}

function setReminderFields(seconds) {
    seconds = Number(seconds || 300);

    if (seconds % 86400 === 0) {
        $("#rotation-reminder-value").val(seconds / 86400);
        $("#rotation-reminder-unit").val("days");
    } else if (seconds % 3600 === 0) {
        $("#rotation-reminder-value").val(seconds / 3600);
        $("#rotation-reminder-unit").val("hours");
    } else {
        $("#rotation-reminder-value").val(Math.max(1, Math.floor(seconds / 60)));
        $("#rotation-reminder-unit").val("minutes");
    }
}

function refreshRotations(doneCallback) {
    apiGet("/api/rotations" + selectedTeamQuery(), function (rotations) {
        rotations = Array.isArray(rotations) ? rotations : [];
        rotationsCache = rotations;

        renderRotationsSummary(rotationsCache);

        const memberSelect = $("#member-rotation");
        const overrideSelect = $("#override-rotation");
        const savedOverrideRotationId = overrideSelect.val();

        memberSelect.empty();
        overrideSelect.empty();

        rotations.forEach(function (rotation) {
            if (!rotation.enabled) {
                return;
            }

            const label = rotation.team_slug + " / " + rotation.name;

            memberSelect.append(
                $("<option>")
                    .val(rotation.id)
                    .text(label)
            );

            overrideSelect.append(
                $("<option>")
                    .val(rotation.id)
                    .text(label)
            );
        });

        if (savedOverrideRotationId) {
            overrideSelect.val(String(savedOverrideRotationId));
        }

        renderRotationsTable();

        if (selectedRotationDetailsId) {
            const selected = findRotationInCache(selectedRotationDetailsId);

            if (selected) {
                renderRotationDetails(selected);
            }
        }

        if (overrideSelect.val()) {
            loadOverrides();
        } else {
            $("#overrides-table")
                .empty()
                .append(
                    $("<tr>").append(
                        $("<td>")
                            .attr("colspan", "6")
                            .addClass("empty-cell")
                            .text(i18n.t("rotations.empty.none_selected"))
                    )
                );
        }

        if (typeof doneCallback === "function") {
            doneCallback();
        }
    });
}

function updateRotationCadenceFields() {
    const type = $("#rotation-type").val();

    $("#weekly-options").toggle(type === "weekly");
    $("#custom-interval-options").toggle(type === "custom");
}

function collectRotationPayload() {
    return {
        team_id: Number($("#rotation-team").val()),
        name: $("#rotation-name").val(),
        description: $("#rotation-description").val(),
        start_at: $("#rotation-start").val(),
        rotation_type: $("#rotation-type").val(),
        interval_value: Number($("#rotation-interval-value").val()),
        interval_unit: $("#rotation-interval-unit").val(),
        handoff_time: $("#rotation-handoff-time").val(),
        handoff_weekday: Number($("#rotation-weekday").val()),
        reminder_interval_seconds: reminderValueToSeconds(),
        timezone: getTimezoneSelectValue("#rotation-timezone")
    };
}

function saveRotation() {
    const id = $("#rotation-id").val();

    if (id) {
        apiPut("/api/rotations/" + id, collectRotationPayload(), function () {
            closeAppModal("#rotation-form-modal");
            resetRotationForm();
            refreshRotations();
        });
        return;
    }

    apiPost("/api/rotations", collectRotationPayload(), function () {
        closeAppModal("#rotation-form-modal");
        resetRotationForm();
        refreshRotations();
    });
}

function editRotation(id) {
    const rotation = findRotationInCache(id);

    if (!rotation) {
        showAppError(i18n.t("rotations.errors.not_found"));
        return;
    }

    $("#rotation-form-title").text(
        i18n.t("rotations.form.edit_title", {id: id})
    );
    $("#rotation-id").val(rotation.id);
    $("#rotation-team").val(rotation.team_id);
    $("#rotation-name").val(rotation.name);
    $("#rotation-description").val(rotation.description || "");
    $("#rotation-start").val(isoToDatetimeLocal(rotation.start_at));
    $("#rotation-type").val(rotation.rotation_type || "daily");
    $("#rotation-interval-value").val(rotation.interval_value || 1);
    $("#rotation-interval-unit").val(rotation.interval_unit || "days");
    $("#rotation-handoff-time").val(rotation.handoff_time || "09:00");
    $("#rotation-weekday").val(
        rotation.handoff_weekday === null ? 0 : rotation.handoff_weekday
    );
    setReminderFields(rotation.reminder_interval_seconds);
    $("#rotation-timezone").val(rotation.timezone || "UTC");
    updateRotationCadenceFields();
    openRotationFormModal();
    initTimezoneSelect(
        "#rotation-timezone",
        rotation.timezone || "UTC",
        "#rotation-form-modal"
    );
    setTimezoneSelectValue("#rotation-timezone", rotation.timezone || "UTC");
}

function setRotationEnabled(id, enabled) {
    const title = enabled
        ? i18n.t("rotations.confirm.enable_title")
        : i18n.t("rotations.confirm.disable_title");
    const message = enabled
        ? i18n.t("rotations.confirm.enable_message")
        : i18n.t("rotations.confirm.disable_message");
    const confirmText = enabled
        ? i18n.t("rotations.confirm.enable")
        : i18n.t("rotations.confirm.disable");

    showAppConfirm({
        title: title,
        message: message,
        confirmText: confirmText,
        confirmClass: enabled ? "btn-primary" : "btn-danger",
    }).done(function () {
        apiPut("/api/rotations/" + id + "/enabled", { enabled: enabled }, function (rotation) {
            rememberRotationInCache(rotation);
            refreshRotations(function () {
                if (Number(selectedRotationDetailsId) === Number(id)) {
                    renderRotationDetails(rotation);
                }
            });
        });
    });
}

function deleteRotation(id) {
    showAppConfirm({
        title: i18n.t("rotations.confirm.delete_title"),
        message: i18n.t("rotations.confirm.delete_message"),
        confirmText: i18n.t("rotations.confirm.delete"),
        confirmClass: "btn-danger",
    }).done(function () {
        apiDelete("/api/rotations/" + id, function () {
            refreshRotations();
            if (Number(selectedRotationDetailsId) === Number(id)) {
                selectedRotationDetailsId = null;
                $("#rotation-details-subtitle").text(
                    i18n.t("rotations.details.select")
                );
                $("#rotation-details-body")
                    .empty()
                    .append(
                        $("<p>").text(i18n.t("rotations.details.help"))
                    );
            }
        });
    });
}

function resetRotationForm() {
    $("#rotation-form-title").text(i18n.t("rotations.form.create_title"));
    $("#rotation-id").val("");
    $("#rotation-name").val("");
    $("#rotation-description").val("");
    $("#rotation-start").val("");
    $("#rotation-type").val("daily");
    $("#rotation-interval-value").val(1);
    $("#rotation-interval-unit").val("days");
    $("#rotation-handoff-time").val("09:00");
    $("#rotation-weekday").val(0);
    setReminderFields(300);
    updateRotationCadenceFields();
    initTimezoneSelect("#rotation-timezone", "UTC", "#rotation-form-modal");
}

function ensureOverrideRotationOption(rotation) {
    const select = $("#override-rotation");
    const rotationId = String(rotation.id);

    if (!select.find('option[value="' + rotationId + '"]').length) {
        select.append(
            $("<option>")
                .val(rotationId)
                .text((rotation.team_slug || rotation.team_name || "-") + " / " + rotation.name)
        );
    }

    select.val(rotationId);
}

function loadRotationForOverride(rotationId, callback) {
    const cachedRotation = findRotationInCache(rotationId);

    if (cachedRotation) {
        callback(cachedRotation);
        return;
    }

    apiGet("/api/rotations/" + encodeURIComponent(rotationId), function (rotation) {
        if (!rotation || !rotation.id) {
            showAppError(i18n.t("rotations.errors.not_found"));
            return;
        }

        rememberRotationInCache(rotation);
        callback(rotation);
    });
}

function selectOverrideRotation(rotationId, options) {
    options = options || {};

    if (!rotationId) {
        showAppError(i18n.t("rotations.errors.not_found"));
        return;
    }

    loadRotationForOverride(rotationId, function (rotation) {
        rotationOverridesAfterChange = typeof options.afterChange === "function" ? options.afterChange : null;
        ensureOverrideRotationOption(rotation);

        fillRotationEligibleUserSelect("#override-user", rotation.id, function () {
            openAppModal("#rotation-overrides-modal");
            $("#override-rotation").val(String(rotation.id));
            applyOverridePrefill(options);
            loadOverrides();
        });
    });
}

function loadOverrides() {
    const rotationId = $("#override-rotation").val();
    const tbody = $("#overrides-table");

    tbody.empty();

    if (!rotationId) {
        tbody.append(
            $("<tr>").append(
                $("<td>")
                    .attr("colspan", "6")
                    .addClass("empty-cell")
                    .text(i18n.t("rotations.empty.none_selected"))
            )
        );
        return;
    }

    const rotation = findRotationInCache(rotationId);

    $("#overrides-title").text(
        rotation
            ? i18n.t("rotations.overrides.title_named", {name: rotation.name})
            : i18n.t("rotations.overrides.title")
    );

    apiGet("/api/rotations/" + rotationId + "/overrides", function (overrides) {
        overrides = asArray(overrides);
        if (!overrides.length) {
            tbody.append(
                $("<tr>").append(
                    $("<td>")
                        .attr("colspan", "6")
                        .addClass("empty-cell")
                        .text(i18n.t("rotations.overrides.none"))
                )
            );
            return;
        }

        overrides.forEach(function (override) {
            const row = $("<tr>");
            row.append($("<td>").text(override.id));
            row.append($("<td>").text(override.display_name || override.username));
            row.append($("<td>").text(formatDateTime24(override.starts_at)));
            row.append($("<td>").text(formatDateTime24(override.ends_at)));
            row.append($("<td>").text(override.reason || "-"));

            const actions = $("<td>").addClass("actions");

            if (rotation && canActionObject(rotation, "write")) {
                actions.append(
                    $("<button>")
                        .attr("type", "button")
                        .addClass("btn btn-danger btn-small")
                        .text(i18n.t("rotations.actions.delete"))
                        .on("click", function () {
                            deleteOverride(override.id);
                        })
                );
            }

            row.append(actions);
            tbody.append(row);
        });
    });
}

function createOverride() {
    const rotationId = $("#override-rotation").val();

    if (!rotationId) {
        showAppError(i18n.t("rotations.layers.select_first"));
        return;
    }

    apiPost("/api/rotations/" + rotationId + "/overrides", {
        user_id: Number($("#override-user").val()),
        starts_at: $("#override-starts-at").val(),
        ends_at: $("#override-ends-at").val(),
        reason: $("#override-reason").val() || null
    }, function () {
        $("#override-reason").val("");
        loadOverrides();

        if (typeof rotationOverridesAfterChange === "function") {
            rotationOverridesAfterChange();
        }
    });
}

function deleteOverride(overrideId) {
    showAppConfirm({
        title: i18n.t("rotations.overrides.delete_title"),
        message: i18n.t("rotations.overrides.delete_title"),
        confirmText: i18n.t("rotations.overrides.delete_confirm"),
        confirmClass: "btn-danger"
    }).done(function () {
        apiDelete("/api/rotations/overrides/" + overrideId, function () {
            loadOverrides();

            if (typeof rotationOverridesAfterChange === "function") {
                rotationOverridesAfterChange();
            }
        });
    });
}

function renderRotationsTable() {
    const tbody = $("#rotations-table");
    const rotations = getFilteredRotations();

    tbody.empty();

    renderRotationsInboxCounter(rotations, rotationsCache);

    if (!rotations.length) {
        tbody.append(
            $("<tr>").append(
                $("<td>")
                    .attr("colspan", "8")
                    .addClass("empty-cell")
                    .text(i18n.t("rotations.empty.none"))
            )
        );
        return;
    }

    rotations.forEach(function (rotation) {
        tbody.append(renderRotationRow(rotation));
    });

    if (typeof window.loadRotationHealthSummariesForVisibleRows === "function") {
        window.loadRotationHealthSummariesForVisibleRows();
    }
}

function renderRotationRow(rotation) {
    const row = $("<tr>");

    const rotationName = $("<button>")
        .attr("type", "button")
        .addClass("name-button")
        .text(rotation.name || "-")
        .on("click", function () {
            renderRotationDetails(rotation);
        });

    row.append(
        $("<td>")
            .append(rotationName)
            .append(
                $("<div>")
                    .addClass("row-subtitle")
                    .text(
                        rotation.description
                        || i18n.t("rotations.labels.rotation_number", {id: rotation.id})
                    )
            )
    );

    row.append(
        $("<td>").append(
            $("<span>")
                .addClass("team-pill")
                .text(rotation.team_name || rotation.team_slug || "-")
        )
    );

    row.append($("<td>").text(getRotationCadence(rotation)));

    const currentUser = getRotationCurrentUser(rotation);

    if (currentUser) {
        row.append(
            $("<td>").append(
                $("<div>")
                    .addClass("person-inline")
                    .append(
                        $("<div>")
                            .addClass("person-avatar")
                            .text(rotationInitials(currentUser))
                    )
                    .append(
                        $("<div>")
                            .append(
                                $("<div>")
                                    .addClass("person-name")
                                    .text(currentUser)
                            )
                            .append(
                                $("<div>")
                                    .addClass("person-meta")
                                    .text(i18n.t("rotations.labels.currently_oncall"))
                            )
                    )
            )
        );
    } else {
        row.append(
            $("<td>").append(
                $("<span>")
                    .addClass("rotation-empty-user")
                    .text("-")
            )
        );
    }

    row.append($("<td>").text(rotation.handoff_time || "-"));
    row.append($("<td>").text(formatSeconds(rotation.reminder_interval_seconds)));
    row.append($("<td>").append(renderRotationRuntimeStatusBadge(rotation)));

    row.append(
        $("<td>")
            .addClass("actions-cell")
            .append(
                makeActionMenu({
                    object: rotation,
                    items: [
                        {
                            label: i18n.t("rotations.actions.edit"),
                            icon: "fas fa-edit",
                            required: "write",
                            denyMessage: i18n.t("rotations.permissions.edit"),
                            onClick: function () {
                                editRotation(rotation.id);
                            }
                        },
                        {
                            label: i18n.t("rotations.actions.layers"),
                            icon: "fas fa-layer-group",
                            required: "write",
                            denyMessage: i18n.t("rotations.permissions.layers"),
                            onClick: function () {
                                selectRotationLayers(rotation.id);
                            }
                        },
                        {
                            label: i18n.t("rotations.actions.overrides"),
                            icon: "fas fa-user-clock",
                            required: "write",
                            denyMessage: i18n.t("rotations.permissions.overrides"),
                            onClick: function () {
                                selectOverrideRotation(rotation.id);
                            }
                        },
                        {
                            label: rotation.enabled
                                ? i18n.t("rotations.actions.disable")
                                : i18n.t("rotations.actions.enable"),
                            icon: rotation.enabled ? "fas fa-pause" : "fas fa-play",
                            required: "write",
                            danger: rotation.enabled,
                            denyMessage: i18n.t("rotations.permissions.toggle"),
                            onClick: function () {
                                setRotationEnabled(rotation.id, !rotation.enabled);
                            }
                        },
                        {
                            label: i18n.t("rotations.actions.delete"),
                            icon: "fas fa-trash",
                            required: "delete",
                            danger: true,
                            denyMessage: i18n.t("rotations.permissions.delete"),
                            onClick: function () {
                                deleteRotation(rotation.id);
                            }
                        }
                    ]
                })
            )
    );

    return row;
}

function openRotationFormModal() {
    initTimezoneSelect("#rotation-timezone", "UTC", "#rotation-form-modal");
    openAppModal("#rotation-form-modal");
}

function openCreateRotationModal() {
    resetRotationForm();
    $("#rotation-form-title").text(i18n.t("rotations.form.create_title"));
    openRotationFormModal();
}

function closeRotationOverridesModal() {
    closeAppModal("#rotation-overrides-modal");
    rotationOverridesAfterChange = null;
}

function getRotationCadence(rotation) {
    if (rotation.rotation_type === "custom") {
        return i18n.t("rotations.cadence.every", {
            value: rotation.custom_days || rotation.interval_value || 1,
            unit: rotationUnitLabel(rotation.interval_unit || "days"),
            timezone: rotation.timezone || "UTC"
        });
    }

    if (rotation.rotation_type === "weekly") {
        return i18n.t("rotations.cadence.weekly");
    }

    if (rotation.rotation_type === "daily") {
        return i18n.t("rotations.cadence.daily");
    }

    return rotation.rotation_type || "-";
}

function rotationDetailsItem(label, value) {
    return $("<div>")
        .addClass("details-item")
        .append($("<div>").addClass("details-label").text(label))
        .append($("<div>").addClass("details-value").text(value || "-"));
}

function renderRotationDetails(rotation) {
    selectedRotationDetailsId = rotation.id;

    $("#rotation-details-subtitle").text(
        (rotation.team_slug || rotation.team_name || "-") +
        " / " +
        (rotation.enabled
            ? i18n.t("rotations.status.active")
            : i18n.t("rotations.status.inactive"))
    );

    const body = $("#rotation-details-body");
    body.empty();

    body.append(
        $("<div>")
            .addClass("details-list")
            .append(rotationDetailsItem(i18n.t("rotations.details.name"), rotation.name))
            .append(rotationDetailsItem(i18n.t("rotations.details.team"), rotation.team_name || rotation.team_slug))
            .append(rotationDetailsItem(i18n.t("rotations.details.current_oncall"), getRotationCurrentUser(rotation) || "-"))
            .append(rotationDetailsItem(i18n.t("rotations.details.cadence"), getRotationCadence(rotation)))
            .append(rotationDetailsItem(i18n.t("rotations.details.handoff_time"), rotation.handoff_time))
            .append(rotationDetailsItem(i18n.t("rotations.details.reminder"), formatSeconds(rotation.reminder_interval_seconds)))
            .append(rotationDetailsItem(i18n.t("rotations.details.timezone"), rotation.timezone))
            .append(rotationDetailsItem(i18n.t("rotations.details.description"), rotation.description))
    );

    const actions = $("<div>").addClass("details-actions");

    appendIconActionIfAllowed(actions, rotation, {
        required: "write",
        icon: "fas fa-edit",
        label: i18n.t("rotations.actions.edit"),
        onClick: function () {
            editRotation(rotation.id);
        }
    });

    appendIconActionIfAllowed(actions, rotation, {
        required: "write",
        icon: "fas fa-layer-group",
        label: i18n.t("rotations.layers.title"),
        onClick: function () {
            selectRotationLayers(rotation.id);
        }
    });

    appendIconActionIfAllowed(actions, rotation, {
        required: "write",
        icon: "fas fa-user-clock",
        label: i18n.t("rotations.overrides.title"),
        onClick: function () {
            selectOverrideRotation(rotation.id);
        }
    });

    actions.append(
        makeIconButton({
            icon: "fas fa-calendar-alt",
            label: i18n.t("rotations.details.open_calendar"),
            onClick: function () {
                navigate("/calendar?team_id=" + encodeURIComponent(rotation.team_id), true);
            }
        })
    );

    appendIconActionIfAllowed(actions, rotation, {
        required: "disable",
        icon: rotation.enabled ? "fas fa-pause" : "fas fa-play",
        label: rotation.enabled
            ? i18n.t("rotations.confirm.disable")
            : i18n.t("rotations.confirm.enable"),
        className: rotation.enabled ? "btn-warning" : "btn-success",
        onClick: function () {
            setRotationEnabled(rotation.id, !rotation.enabled);
        }
    });

    appendIconActionIfAllowed(actions, rotation, {
        required: "delete",
        icon: "fas fa-trash",
        label: i18n.t("rotations.confirm.delete"),
        className: "btn-danger",
        onClick: function () {
            deleteRotation(rotation.id);
        }
    });

    body.append(actions);
}

function renderRotationsInboxCounter(filteredRotations, allRotations) {
    filteredRotations = Array.isArray(filteredRotations) ? filteredRotations : [];
    allRotations = Array.isArray(allRotations) ? allRotations : [];

    $("#rotations-filtered-count").text(filteredRotations.length);
    $("#rotations-total-count").text(allRotations.length);
}

function fillRotationEligibleUserSelect(selector, rotationId, callback) {
    const select = $(selector);
    select.empty();

    if (!rotationId) {
        select.append(
            $("<option>")
                .val("")
                .text(i18n.t("rotations.labels.select_rotation_first"))
        );

        if (typeof callback === "function") {
            callback([]);
        }
        return;
    }

    apiGet("/api/rotations/" + rotationId + "/eligible-users", function (users) {
        users = asArray(users);
        select.empty();

        if (!users.length) {
            select.append(
                $("<option>")
                    .val("")
                    .text(i18n.t("rotations.layers.no_team_members"))
            );
        }

        users.forEach(function (user) {
            select.append(
                $("<option>")
                    .val(user.user_id)
                    .text(
                        "#" + user.user_id + " " +
                        (user.display_name || user.username || i18n.t("rotations.labels.user"))
                    )
            );
        });

        if (typeof callback === "function") {
            callback(users);
        }
    });
}
function applyOverridePrefill(options) {
    options = options || {};

    if (options.userId) {
        $("#override-user").val(String(options.userId));
    }

    if (options.startsAt) {
        $("#override-starts-at").val(options.startsAt);
    }

    if (options.endsAt) {
        $("#override-ends-at").val(options.endsAt);
    }

    if (options.reason !== undefined) {
        $("#override-reason").val(options.reason || "");
    }
}
function initLayerTimezoneSelects() {
    $(".rotation-layer-card.is-editing select.timezone-select").each(function () {
        const select = $(this);

        if ($.fn.select2) {
            if (select.hasClass("select2-hidden-accessible")) {
                select.select2("destroy");
            }

            select.select2({
                width: "100%",
                placeholder: i18n.t("rotations.form.select_timezone"),
                dropdownParent: $("#rotation-layers-modal")
            });
        }
    });
}
$(document).on("click", "#add-layer-card", addLayerCard);
$(document).on(
    "click",
    "#close-rotation-layers-modal, #close-rotation-layers-modal-footer",
    closeRotationLayersModal
);
$(document).on("click", "#rotation-layers-modal", function (event) {
    if (event.target === this) {
        closeRotationLayersModal();
    }
});
$(document).on("change", '[data-layer-field="rotation_type"]', function () {
    const layerId = $(this).closest(".rotation-layer-card").attr("data-layer-id");
    updateLayerCadenceVisibility(layerId);
});
$(document).on("keydown", function (event) {
    if (event.key === "Escape" && $("#rotation-layers-modal").hasClass("is-open")) {
        closeRotationLayersModal();
    }
});

$(document).on("change", "#rotation-type", updateRotationCadenceFields);
$(document).on("change", "#override-rotation", function () {
    const rotationId = $(this).val();
    fillRotationEligibleUserSelect("#override-user", rotationId, loadOverrides);
});
$(document).on("click", "#save-rotation", saveRotation);
$(document).on("click", "#reset-rotation-form", resetRotationForm);
$(document).on("click", "#reload-rotations", refreshRotations);
$(document).on("click", "#reload-overrides", loadOverrides);
$(document).on("click", "#create-override", createOverride);

$(document).on("input", "#rotations-search", renderRotationsTable);
$(document).on("change", "#rotations-status-filter", renderRotationsTable);

$(document).on("click", "#open-rotation-create-modal", openCreateRotationModal);
$(document).on("click", "#close-rotation-form-modal", function () {
    closeAppModal("#rotation-form-modal");
});
$(document).on("click", "#rotation-form-modal", function (event) {
    if (event.target === this) {
        closeAppModal("#rotation-form-modal");
    }
});
$(document).on("keydown", function (event) {
    if (event.key === "Escape" && $("#rotation-form-modal").hasClass("is-open")) {
        closeAppModal("#rotation-form-modal");
    }
});

$(document).on(
    "click",
    "#close-rotation-overrides-modal, #close-rotation-overrides-modal-footer",
    closeRotationOverridesModal
);
$(document).on("click", "#rotation-overrides-modal", function (event) {
    if (event.target === this) {
        closeRotationOverridesModal();
    }
});
$(document).on("keydown", function (event) {
    if (event.key !== "Escape") {
        return;
    }

    if ($("#rotation-overrides-modal").hasClass("is-open")) {
        closeRotationOverridesModal();
    }
});
