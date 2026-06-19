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
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday"
];

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
                .text("No rotation selected")
        );
}

function selectRotationLayers(rotationId) {
    const rotation = findRotationInCache(rotationId);

    if (!rotation) {
        showAppError("Rotation was not found.");
        return;
    }

    selectedRotationForLayers = rotation.id;
    selectedRotationNameForLayers = rotation.name || ("rotation #" + rotation.id);
    rotationLayersCache = [];
    rotationLayerEligibleUsersCache = [];
    layerMembersCache = {};
    layerRestrictionsCache = {};
    expandedLayerId = null;

    $("#rotation-layers-title").text("Rotation layers: " + selectedRotationNameForLayers);
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
                .text("Loading layers...")
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
                .text("No layers. Add the first layer to define on-call coverage.")
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
            .append($("<strong>").text(layer.name || "Unnamed layer"))
            .append(
                $("<span>").text(
                    "Priority " +
                    Number(layer.priority || 0) +
                    " · " +
                    (layer.enabled ? "Enabled" : "Disabled") +
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
            .text(Number(expandedLayerId) === Number(layer.id) ? "Collapse" : "Edit")
            .on("click", function () {
                toggleLayerEditor(layer.id);
            })
    );

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-danger btn-small")
            .text("Delete")
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
            .append($("<span>").text("Who rotates"))
            .append($("<strong>").html(formatLayerMembersSummary(layer.id)))
    );

    summary.append(
        $("<div>")
            .addClass("rotation-layer-summary-item")
            .append($("<span>").text("Rotation"))
            .append($("<strong>").text(formatLayerCadence(layer)))
    );

    summary.append(
        $("<div>")
            .addClass("rotation-layer-summary-item")
            .append($("<span>").text("Active"))
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
        return "No users";
    }

    return members.map(function (member) {
        return escapeHtml(member.display_name || member.username || ("user #" + member.user_id));
    }).join(" → ");
}

function formatLayerCadence(layer) {
    const type = layer.rotation_type || "daily";
    const handoff = layer.handoff_time || "09:00";
    const timezone = layer.timezone || "UTC";

    if (type === "weekly") {
        const weekday = layer.handoff_weekday === null || layer.handoff_weekday === undefined
            ? "Monday"
            : weekdayLabel(layer.handoff_weekday);

        return "Weekly, " + weekday + " " + handoff + ", " + timezone;
    }

    if (type === "custom") {
        return "Every " + (layer.interval_value || 1) + " " + (layer.interval_unit || "days") + ", " + timezone;
    }

    return "Daily, " + handoff + ", " + timezone;
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
        parts.push("+" + (restrictions.length - 4) + " more");
    }

    return parts.join("<br>");
}

function renderLayerSettingsEditor(layer) {
    const section = $("<section>").addClass("layer-editor-section");

    section.append($("<h4>").text("1. When do they rotate?"));
    section.append(
        $("<div>")
            .addClass("layer-editor-section-subtitle")
            .text("Configure handoff time, timezone and priority for this layer.")
    );

    const grid = $("<div>").addClass("layer-settings-grid");

    grid.append(
        layerTextField(layer.id, "name", "Name", layer.name || "")
            .addClass("layer-settings-col-4")
    );

    grid.append(
        layerNumberField(layer.id, "priority", "Priority", layer.priority || 0, 0)
            .addClass("layer-settings-col-2")
    );

    grid.append(
        $("<div>")
            .addClass("app-field layer-settings-col-6")
            .append($("<label>").text("Description"))
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
            .append($("<label>").text("Schedule starts at"))
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
            .append($("<label>").text("Cadence"))
            .append(
                $("<select>")
                    .addClass("input")
                    .attr("data-layer-field", "rotation_type")
                    .append($("<option>").val("daily").text("Daily handoff"))
                    .append($("<option>").val("weekly").text("Weekly handoff"))
                    .append($("<option>").val("custom").text("Custom interval"))
                    .val(layer.rotation_type || "daily")
            )
    );

    grid.append(
        $("<div>")
            .addClass("app-field layer-settings-col-2")
            .append($("<label>").text("Handoff time"))
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
            .append($("<label>").text("Weekly handoff day"))
            .append(
                $("<select>")
                    .addClass("input")
                    .attr("data-layer-field", "handoff_weekday")
                    .append($("<option>").val("0").text("Monday"))
                    .append($("<option>").val("1").text("Tuesday"))
                    .append($("<option>").val("2").text("Wednesday"))
                    .append($("<option>").val("3").text("Thursday"))
                    .append($("<option>").val("4").text("Friday"))
                    .append($("<option>").val("5").text("Saturday"))
                    .append($("<option>").val("6").text("Sunday"))
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
            .append($("<label>").text("Every"))
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
            .append($("<label>").text("Unit"))
            .append(
                $("<select>")
                    .addClass("input")
                    .attr("data-layer-field", "interval_unit")
                    .append($("<option>").val("minutes").text("minutes"))
                    .append($("<option>").val("hours").text("hours"))
                    .append($("<option>").val("days").text("days"))
                    .append($("<option>").val("weeks").text("weeks"))
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
                            .append($("<strong>").text("Enabled"))
                            .append($("<small>").text("Layer participates in final schedule"))
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
                    .text("Save layer")
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
        .append($("<label>").text("Timezone"))
        .append(select);
}

function renderLayerMembersEditor(layer) {
    const section = $("<section>").addClass("layer-editor-section");

    section.append($("<h4>").text("2. Who rotates?"));

    section.append(
        $("<div>")
            .addClass("layer-editor-section-subtitle")
            .text("Users rotate in position order. Removing a user only affects future shifts; past shifts stay visible.")
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
        .addClass("input js-user-select")
        .attr("data-layer-member-user", layer.id)
        .attr("data-placeholder", "Select user...");

    if (!availableUsers.length) {
        userSelect.append(
            $("<option>")
                .val("")
                .text(currentMembers.length ? "All active users are already in this layer" : "No active team members")
        );
    }else {
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
            .append($("<label>").text("User"))
            .append(userSelect)
    );

    addRow.append(
        $("<div>")
            .addClass("app-field")
            .append($("<label>").text("Position"))
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
                    .text("Starts at")
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
            .text("Add user")
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
                .text("No active users in this layer yet.")
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

    row.append(
        $("<div>")
            .addClass("layer-member-name")
            .append($("<strong>").text(member.display_name || member.username || ("user #" + member.user_id)))
            .append(
                $("<small>").text(
                    "User ID " + member.user_id +
                    " · member #" + member.id +
                    (member.starts_at ? " · starts at " + formatDateTime(member.starts_at) : "")
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
            .text("Save position")
            .on("click", function () {
                updateLayerMemberFromCard(layerId, member.id);
            })
    );

    actions.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-danger btn-small")
            .text("Remove")
            .on("click", function () {
                removeLayerMemberFromCard(layerId, member.id);
            })
    );

    row.append(actions);

    return row;
}

function renderLayerRestrictionsEditor(layer) {
    const section = $("<section>").addClass("layer-editor-section");

    section.append($("<h4>").text("3. When is this layer active?"));
    section.append(
        $("<div>")
            .addClass("layer-editor-section-subtitle")
            .text("No restrictions means this layer is active 24/7.")
    );

    const toolbar = $("<div>").addClass("layer-restrictions-toolbar");

    toolbar.append(presetButton(layer.id, "24/7", "24x7"));
    toolbar.append(presetButton(layer.id, "Business hours", "business"));
    toolbar.append(presetButton(layer.id, "Nights", "nights"));
    toolbar.append(presetButton(layer.id, "Weekend", "weekend"));
    toolbar.append(
        $("<button>")
            .attr("type", "button")
            .addClass("btn btn-small")
            .text("+ Add window")
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
                .text("Active 24/7. Add windows if this layer should only work during specific days or hours.")
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
                    .text("Save restrictions")
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
        .append($("<option>").val("").text("Every day"))
        .append($("<option>").val("0").text("Monday"))
        .append($("<option>").val("1").text("Tuesday"))
        .append($("<option>").val("2").text("Wednesday"))
        .append($("<option>").val("3").text("Thursday"))
        .append($("<option>").val("4").text("Friday"))
        .append($("<option>").val("5").text("Saturday"))
        .append($("<option>").val("6").text("Sunday"));

    weekdaySelect.val(restriction.weekday === null || restriction.weekday === undefined ? "" : String(restriction.weekday));

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
            .text("Remove")
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

function addLayerCard() {
    if (!selectedRotationForLayers) {
        showAppError("Select a rotation first.");
        return;
    }

    const rotation = findSelectedLayerRotation();
    const nextPriority = rotationLayersCache.length
        ? Math.max.apply(null, rotationLayersCache.map(function (layer) {
            return Number(layer.priority || 0);
        })) + 10
        : 10;

    const payload = {
        name: "New layer",
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
        title: "Delete this layer?",
        message: "Delete this layer?",
        confirmText: "Delete layer",
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
        showAppError("Select a user to add.");
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
        title: "Remove this user from future shifts?",
        message: "Past on-call shifts will stay visible. This user will no longer be assigned to future shifts in this layer.",
        confirmText: "Remove from future shifts",
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
        return "Every day";
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
            label: "Disabled",
        };
    }

    const startAt = parseRotationDate(rotation.start_at);
    if (startAt && startAt.getTime() > Date.now()) {
        return {
            key: "scheduled",
            label: "Scheduled",
        };
    }

    if (getRotationCurrentUser(rotation)) {
        return {
            key: "active",
            label: "Active now",
        };
    }

    return {
        key: "idle",
        label: "No active layer",
    };
}

function renderRotationRuntimeStatusBadge(rotation) {
    const status = getRotationRuntimeStatus(rotation);

    if (status.key === "active") {
        return renderStatusBadge(true, "Active now", "Disabled");
    }

    if (status.key === "disabled") {
        return renderStatusBadge(false, "Active now", "Disabled");
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
                            .text("No rotation selected")
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
        showAppError("Rotation was not found.");
        return;
    }

    $("#rotation-form-title").text("Edit rotation #" + id);
    $("#rotation-id").val(rotation.id);
    $("#rotation-team").val(rotation.team_id);
    $("#rotation-name").val(rotation.name);
    $("#rotation-description").val(rotation.description || "");
    $("#rotation-start").val(isoToDatetimeLocal(rotation.start_at));
    $("#rotation-type").val(rotation.rotation_type || "daily");
    $("#rotation-interval-value").val(rotation.interval_value || 1);
    $("#rotation-interval-unit").val(rotation.interval_unit || "days");
    $("#rotation-handoff-time").val(rotation.handoff_time || "09:00");
    $("#rotation-weekday").val(rotation.handoff_weekday === null ? 0 : rotation.handoff_weekday);
    setReminderFields(rotation.reminder_interval_seconds);
    $("#rotation-timezone").val(rotation.timezone || "UTC");
    updateRotationCadenceFields();
    openRotationFormModal();
    initTimezoneSelect("#rotation-timezone", rotation.timezone || "UTC", "#rotation-form-modal");
    setTimezoneSelectValue("#rotation-timezone", rotation.timezone || "UTC");
}

function setRotationEnabled(id, enabled) {
    const title = enabled ? "Enable this rotation?" : "Disable this rotation?";
    const message = enabled
        ? "Enable this rotation and allow it to participate in on-call scheduling?"
        : "Disable this rotation without deleting layers, members, overrides or route links?";
    const confirmText = enabled ? "Enable rotation" : "Disable rotation";

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

function enableRotation(id) {
    setRotationEnabled(id, true);
}

function disableRotation(id) {
    setRotationEnabled(id, false);
}

function deleteRotation(id) {
    showAppConfirm({
        title: "Delete this rotation?",
        message: "This will remove the rotation, delete its layers, members and overrides, and detach it from alert routes.",
        confirmText: "Delete rotation",
        confirmClass: "btn-danger",
    }).done(function () {
        apiDelete("/api/rotations/" + id, function () {
            refreshRotations();
            if (Number(selectedRotationDetailsId) === Number(id)) {
                selectedRotationDetailsId = null;
                $("#rotation-details-subtitle").text("Select a rotation");
                $("#rotation-details-body").html(
                    "<p>Click a rotation name to inspect current on-call user, cadence, reminders and quick actions.</p>"
                );
            }
        });
    });
}

function resetRotationForm() {
    $("#rotation-form-title").text("Create rotation");
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
            showAppError("Rotation was not found.");
            return;
        }

        rememberRotationInCache(rotation);
        callback(rotation);
    });
}

function selectOverrideRotation(rotationId, options) {
    options = options || {};

    if (!rotationId) {
        showAppError("Rotation was not found.");
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
                    .text("No rotation selected")
            )
        );
        return;
    }

    const rotation = findRotationInCache(rotationId);

    $("#overrides-title").text("Overrides" + (rotation ? ": " + rotation.name : ""));

    apiGet("/api/rotations/" + rotationId + "/overrides", function (overrides) {
        overrides = asArray(overrides);
        if (!overrides.length) {
            tbody.append(
                $("<tr>").append(
                    $("<td>")
                        .attr("colspan", "6")
                        .addClass("empty-cell")
                        .text("No overrides")
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
                        .text("Delete")
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
        showAppError("Select a rotation first.");
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
        title: "Delete this override?",
        message: "Delete this override?",
        confirmText: "Delete override",
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
                    .text("No rotations")
            )
        );
        return;
    }

    rotations.forEach(function (rotation) {
        tbody.append(renderRotationRow(rotation));
    });
}

function renderRotationRow(rotation) {
    /*
     * Render one rotation row.
     */
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
                    .text(rotation.description || "Rotation #" + rotation.id)
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
                                    .text("Currently on call")
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

    row.append(
        $("<td>").text(formatSeconds(rotation.reminder_interval_seconds))
    );

    row.append(
        $("<td>").append(
            renderRotationRuntimeStatusBadge(rotation)
        )
    );

    row.append(
        $("<td>")
            .addClass("actions-cell")
            .append(
                makeActionMenu({
                    object: rotation,
                    items: [
                        {
                            label: "Edit",
                            icon: "fas fa-edit",
                            required: "write",
                            denyMessage: "Team manager role is required to edit this rotation.",
                            onClick: function () {
                                editRotation(rotation.id);
                            }
                        },
                        {
                            label: "Layers",
                            icon: "fas fa-layer-group",
                            required: "write",
                            denyMessage: "Team manager role is required to manage rotation layers.",
                            onClick: function () {
                                selectRotationLayers(rotation.id);
                            }
                        },
                        {
                            label: "Overrides",
                            icon: "fas fa-user-clock",
                            required: "write",
                            denyMessage: "Team manager role is required to manage rotation overrides.",
                            onClick: function () {
                                selectOverrideRotation(rotation.id);
                            }
                        },
                        {
                            label: rotation.enabled ? "Disable" : "Enable",
                            icon: rotation.enabled ? "fas fa-pause" : "fas fa-play",
                            required: "write",
                            danger: rotation.enabled,
                            denyMessage: "Team manager role is required to enable or disable this rotation.",
                            onClick: function () {
                                setRotationEnabled(rotation.id, !rotation.enabled);
                            }
                        },
                        {
                            label: "Delete",
                            icon: "fas fa-trash",
                            required: "delete",
                            danger: true,
                            denyMessage: "Delete permission is required to remove this rotation.",
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
    $("#rotation-form-title").text("Create rotation");
    openRotationFormModal();
}

function closeRotationOverridesModal() {
    closeAppModal("#rotation-overrides-modal");
    rotationOverridesAfterChange = null;
}

function getRotationCadence(rotation) {
    if (rotation.rotation_type === "custom") {
        return (rotation.custom_days || rotation.interval_value || 1) + "d";
    }

    if (rotation.rotation_type === "weekly") {
        return "weekly";
    }

    if (rotation.rotation_type === "daily") {
        return "daily";
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
        (rotation.enabled ? "Active" : "Inactive")
    );

    const body = $("#rotation-details-body");
    body.empty();

    body.append(
        $("<div>")
            .addClass("details-list")
            .append(rotationDetailsItem("Name", rotation.name))
            .append(rotationDetailsItem("Team", rotation.team_name || rotation.team_slug))
            .append(rotationDetailsItem("Current on call", getRotationCurrentUser(rotation) || "-"))
            .append(rotationDetailsItem("Cadence", getRotationCadence(rotation)))
            .append(rotationDetailsItem("Handoff time", rotation.handoff_time))
            .append(rotationDetailsItem("Reminder", formatSeconds(rotation.reminder_interval_seconds)))
            .append(rotationDetailsItem("Timezone", rotation.timezone))
            .append(rotationDetailsItem("Description", rotation.description))
    );

    const actions = $("<div>").addClass("details-actions");

    appendIconActionIfAllowed(actions, rotation, {
        required: "write",
        icon: "fas fa-edit",
        label: "Edit rotation",
        onClick: function () {
            editRotation(rotation.id);
        }
    });

    appendIconActionIfAllowed(actions, rotation, {
        required: "write",
        icon: "fas fa-layer-group",
        label: "Rotation layers",
        onClick: function () {
            selectRotationLayers(rotation.id);
        }
    });

    appendIconActionIfAllowed(actions, rotation, {
        required: "write",
        icon: "fas fa-user-clock",
        label: "Rotation overrides",
        onClick: function () {
            selectOverrideRotation(rotation.id);
        }
    });

    actions.append(
        makeIconButton({
            icon: "fas fa-calendar-alt",
            label: "Open calendar",
            onClick: function () {
                navigate("/calendar?team_id=" + encodeURIComponent(rotation.team_id), true);
            }
        })
    );

    appendIconActionIfAllowed(actions, rotation, {
        required: "disable",
        icon: rotation.enabled ? "fas fa-pause" : "fas fa-play",
        label: rotation.enabled ? "Disable rotation" : "Enable rotation",
        className: rotation.enabled ? "btn-warning" : "btn-success",
        onClick: function () {
            setRotationEnabled(rotation.id, !rotation.enabled);
        }
    });
    appendIconActionIfAllowed(actions, rotation, {
        required: "delete",
        icon: "fas fa-trash",
        label: "Delete rotation",
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
                .text("Select rotation first")
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
                    .text("No active team members")
            );
        }

        users.forEach(function (user) {
            select.append(
                $("<option>")
                    .val(user.user_id)
                    .text("#" + user.user_id + " " + (user.display_name || user.username || "user"))
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
                placeholder: "Select timezone",
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
