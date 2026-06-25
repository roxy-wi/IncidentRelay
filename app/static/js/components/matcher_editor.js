const matcherSuggestionsCache = {};


function matcherEditorField(idOrSelector) {
    if (idOrSelector && idOrSelector.jquery) {
        return idOrSelector;
    }

    const value = String(idOrSelector || "");
    return $(value.startsWith("#") ? value : "#" + value);
}


function matcherEditorSettings(options) {
    return $.extend({
        value: {},
        label: "Matchers",
        header: null,
        helpText: "Use {} to match all alerts.",
        rows: 7,
        fieldClass: "app-field layer-settings-col-12",
        context: {},
        suggestions: true,
        preview: true,
    }, options || {});
}


function matcherEditorLabel(field) {
    return field.attr("data-matcher-editor-label") || "Matchers";
}


function parseMatcherEditorJson(field, fallback) {
    const raw = String(field.val() || "").trim();
    const value = raw ? JSON.parse(raw) : fallback;

    if (!value || Array.isArray(value) || typeof value !== "object") {
        throw new Error("Matchers must be a JSON object.");
    }

    return value;
}


function showMatcherEditorError(field, error) {
    field.addClass("field-error");
    showAppError(matcherEditorLabel(field) + " are invalid:\n\n" + error.message, "Invalid matchers");
}


function createMatcherEditorControl(settings) {
    const field = $("<textarea>")
        .attr("id", settings.id)
        .attr("rows", settings.rows)
        .attr("spellcheck", "false")
        .attr("autocomplete", "off")
        .attr("data-matcher-editor-label", settings.label)
        .addClass("input code-textarea json-editor-textarea matcher-editor-textarea")
        .val(JSON.stringify(settings.value || {}, null, 2));
    const actions = $("<div>").addClass("matcher-editor-actions");

    if (settings.preview) {
        actions.append(
            $("<button>")
                .attr("type", "button")
                .attr("data-matcher-editor-target", settings.id)
                .addClass("btn btn-small matcher-editor-run-preview")
                .text("Preview matches")
        );
    }

    if (settings.suggestions) {
        actions.append(
            $("<button>")
                .attr("type", "button")
                .attr("data-matcher-editor-target", settings.id)
                .addClass("btn btn-small matcher-editor-load-suggestions")
                .text("Suggestions")
        );
    }

    actions.append(
        $("<button>")
            .attr("type", "button")
            .attr("data-matcher-editor-target", settings.id)
            .addClass("btn btn-small matcher-editor-format")
            .text("Format")
    );

    return $("<div>")
        .addClass("json-editor matcher-editor")
        .attr("data-matcher-editor-id", settings.id)
        .data("matcher-editor-context", settings.context || {})
        .append(
            $("<div>").addClass("json-editor-header matcher-editor-header")
                .append($("<span>").text(settings.header || settings.label))
                .append(actions)
        )
        .append(field)
        .append($("<div>").addClass("matcher-editor-suggestions").attr("data-matcher-editor-suggestions", settings.id))
        .append($("<div>").addClass("matcher-editor-preview").attr("data-matcher-editor-preview", settings.id));
}


function createMatcherEditor(options) {
    const settings = matcherEditorSettings(options);

    if (!settings.id) {
        throw new Error("Matcher editor id is required.");
    }

    const wrapper = $("<div>").addClass(settings.fieldClass)
        .append($("<label>").attr("for", settings.id).text(settings.label))
        .append(createMatcherEditorControl(settings));

    if (settings.helpText) {
        wrapper.append($("<div>").addClass("help-text").text(settings.helpText));
    }

    return wrapper;
}


function enhanceMatcherEditor(idOrSelector, options) {
    const field = matcherEditorField(idOrSelector);

    if (!field.length) {
        return false;
    }

    const currentEditor = field.closest(".matcher-editor");

    if (currentEditor.length) {
        currentEditor.data("matcher-editor-context", (options && options.context) || {});
        return true;
    }

    const settings = matcherEditorSettings(options);
    settings.id = field.attr("id");
    settings.rows = Number(field.attr("rows") || settings.rows);

    try {
        settings.value = parseMatcherEditorJson(field, settings.value || {});
    } catch (error) {
        settings.value = settings.value || {};
    }

    const existingEditor = field.closest(".json-editor");
    const control = createMatcherEditorControl(settings);

    if (existingEditor.length) {
        existingEditor.replaceWith(control);
    } else {
        field.replaceWith(control);
    }

    return true;
}


function getMatcherEditorValue(idOrSelector, fallback) {
    const field = matcherEditorField(idOrSelector);

    if (!field.length) {
        throw new Error("Matcher editor field was not found: " + idOrSelector);
    }

    try {
        const value = parseMatcherEditorJson(field, fallback || {});
        field.removeClass("field-error");
        return value;
    } catch (error) {
        showMatcherEditorError(field, error);
        throw error;
    }
}


function setMatcherEditorValue(idOrSelector, value) {
    const field = matcherEditorField(idOrSelector);

    if (!field.length) {
        return false;
    }

    field.val(JSON.stringify(value || {}, null, 2)).removeClass("field-error");
    return true;
}


function formatMatcherEditor(idOrSelector) {
    const field = matcherEditorField(idOrSelector);

    if (!field.length) {
        return false;
    }

    try {
        const value = parseMatcherEditorJson(field, {});
        field.val(JSON.stringify(value, null, 2)).removeClass("field-error");
        return true;
    } catch (error) {
        showMatcherEditorError(field, error);
        return false;
    }
}


function getMatcherEditorContext(idOrSelector) {
    const field = matcherEditorField(idOrSelector);
    const context = field.closest(".matcher-editor").data("matcher-editor-context") || {};
    return typeof context === "function" ? context() : context;
}

function findMatcherPresetById(presets, presetId) {
    if (!presetId) {
        return null;
    }

    return asArray(presets).find(function (preset) {
        return Number(preset.id) === Number(presetId);
    }) || null;
}


function formatMatcherPresetOption(preset) {
    return preset.name + " · v" + Number(preset.version || 1) + (preset.enabled ? "" : " · Disabled");
}


function fillMatcherPresetSelect(selector, presets, selectedPresetId) {
    const select = $(selector);

    select.empty().append($("<option>").val("").text("No preset"));

    asArray(presets).forEach(function (preset) {
        const selected = Number(preset.id) === Number(selectedPresetId);
        const option = $("<option>").val(String(preset.id)).text(formatMatcherPresetOption(preset));

        if (!preset.enabled && !selected) {
            option.prop("disabled", true);
        }

        select.append(option);
    });

    select.val(selectedPresetId ? String(selectedPresetId) : "");
}


function matcherPresetAndLocalHint(preset) {
    if (!preset) {
        return "No preset selected. Only the additional matchers below will be evaluated.";
    }

    if (!preset.enabled) {
        return "This preset is disabled. Matching will not succeed until the preset is enabled.";
    }

    return "Preset \"" + preset.name + "\" v" + Number(preset.version || 1) + " and the additional matchers must both match.";
}


function loadMatcherPresetsForTeam(teamId, callback) {
    if (!teamId) {
        callback([]);
        return;
    }

    apiGet("/api/matcher-presets?team_id=" + encodeURIComponent(teamId), function (presets) {
        callback(asArray(presets));
    });
}

function matcherSuggestionsUrl(context) {
    const teamId = Number(context.teamId || context.team_id || 0);

    if (!teamId) {
        return null;
    }

    const params = ["team_id=" + encodeURIComponent(teamId)];
    const routeId = Number(context.routeId || context.route_id || 0);
    const serviceId = Number(context.serviceId || context.service_id || 0);

    if (routeId) {
        params.push("route_id=" + encodeURIComponent(routeId));
    }

    if (serviceId) {
        params.push("service_id=" + encodeURIComponent(serviceId));
    }

    return "/api/matchers/suggestions?" + params.join("&");
}


function matcherSuggestionsContainer(idOrSelector) {
    const field = matcherEditorField(idOrSelector);
    return field.closest(".matcher-editor").find(".matcher-editor-suggestions").first();
}


function insertMatcherSuggestion(idOrSelector, name, value, kind) {
    const matchers = getMatcherEditorValue(idOrSelector, {});

    if (kind === "field" && !["source", "title", "title_regex"].includes(name)) {
        matchers.fields = matchers.fields || {};
        matchers.fields[name] = value;
    } else {
        matchers[name] = value;
    }

    setMatcherEditorValue(idOrSelector, matchers);
}


function createMatcherSuggestionValue(target, name, value, kind) {
    return $("<button>")
        .attr("type", "button")
        .attr("data-matcher-editor-target", target)
        .attr("data-matcher-suggestion-name", name)
        .attr("data-matcher-suggestion-value", value)
        .attr("data-matcher-suggestion-kind", kind)
        .addClass("matcher-editor-suggestion-value")
        .text(value);
}


function createMatcherSuggestionRow(target, name, values, kind) {
    const row = $("<div>").addClass("matcher-editor-suggestion-row");
    const nameButton = $("<button>")
        .attr("type", "button")
        .attr("data-matcher-editor-target", target)
        .attr("data-matcher-suggestion-name", name)
        .attr("data-matcher-suggestion-value", "")
        .attr("data-matcher-suggestion-kind", kind)
        .addClass("matcher-editor-suggestion-name")
        .text(name);
    const valuesContainer = $("<div>").addClass("matcher-editor-suggestion-values");

    (values || []).forEach(function (value) {
        valuesContainer.append(createMatcherSuggestionValue(target, name, value, kind));
    });

    row.append(nameButton).append(valuesContainer);
    return row;
}


function createMatcherSuggestionSection(target, title, suggestions, kind) {
    const names = Object.keys(suggestions || {});

    if (!names.length) {
        return null;
    }

    const section = $(document.createElement("div")).addClass("matcher-editor-suggestion-section");
    const sectionTitle = $(document.createElement("div")).addClass("matcher-editor-suggestion-title").text(title);

    section.append(sectionTitle);

    names.forEach(function (name) {
        section.append(createMatcherSuggestionRow(target, name, suggestions[name], kind));
    });

    return section;
}


function renderMatcherSuggestions(idOrSelector, payload) {
    const field = matcherEditorField(idOrSelector);
    const target = field.attr("id");
    const container = matcherSuggestionsContainer(field);
    const header = $("<div>").addClass("matcher-editor-suggestions-header");
    const summary = "Known matcher values from " + Number(payload.sample_size || 0) + " recent alerts";

    header.append($("<span>").text(summary));
    header.append(
        $("<button>")
            .attr("type", "button")
            .attr("data-matcher-editor-target", target)
            .addClass("btn btn-small matcher-editor-close-suggestions")
            .text("Close")
    );

    const labelsSection = createMatcherSuggestionSection(target, "Labels", payload.labels, "label");
    const fieldsSection = createMatcherSuggestionSection(target, "Fields", payload.fields, "field");

    container.empty().append(header);

    if (labelsSection) {
        container.append(labelsSection);
    }

    if (fieldsSection) {
        container.append(fieldsSection);
    }

    if (!labelsSection && !fieldsSection) {
        const emptyMessage = $(document.createElement("div")).addClass("help-text").text("No matcher suggestions found for this context.");
        container.append(emptyMessage);
    }
}


function loadMatcherSuggestions(idOrSelector, button) {
    const field = matcherEditorField(idOrSelector);
    const context = getMatcherEditorContext(field);
    const url = matcherSuggestionsUrl(context);

    if (!url) {
        showAppError("Select a team before loading matcher suggestions.", "Suggestions unavailable");
        return;
    }

    const cached = matcherSuggestionsCache[url];

    if (cached) {
        renderMatcherSuggestions(field, cached);
        return;
    }

    const originalText = button.text();
    button.prop("disabled", true).text("Loading...");

    apiGet(url, function (payload) {
        matcherSuggestionsCache[url] = payload;
        renderMatcherSuggestions(field, payload);
        button.prop("disabled", false).text(originalText);
    }, function (xhr) {
        button.prop("disabled", false).text(originalText);
        showApiError(xhr);
    });
}

function matcherPreviewContainer(idOrSelector) {
    const field = matcherEditorField(idOrSelector);
    return field.closest(".matcher-editor").find(".matcher-editor-preview").first();
}


function matcherPreviewPayload(idOrSelector) {
    const context = getMatcherEditorContext(idOrSelector);
    const teamId = Number(context.teamId || context.team_id || 0);

    if (!teamId) {
        throw new Error("Select a team before previewing matchers.");
    }

    return {
        team_id: teamId,
        route_id: Number(context.routeId || context.route_id || 0) || null,
        service_id: Number(context.serviceId || context.service_id || 0) || null,
        matcher_preset_id: Number(context.matcherPresetId || context.matcher_preset_id || 0) || null,
        matchers: getMatcherEditorValue(idOrSelector, {}),
        scan_limit: 200,
        result_limit: 20,
    };
}


function matcherPreviewItemMeta(item) {
    return [
        item.source,
        item.severity,
        item.status,
        item.priority ? String(item.priority).toUpperCase() : null,
        item.service_name || item.route_name,
    ].filter(Boolean).join(" · ");
}


function renderMatcherPreview(idOrSelector, payload) {
    const field = matcherEditorField(idOrSelector);
    const target = field.attr("id");
    const container = matcherPreviewContainer(field);
    const matchedCount = Number(payload.matched_count || 0);
    const sampleSize = Number(payload.sample_size || 0);
    const items = Array.isArray(payload.items) ? payload.items : [];
    const header = $("<div>").addClass("matcher-editor-preview-header");

    header.append(
        $("<div>")
            .append($("<strong>").text(matchedCount + " matched"))
            .append($("<span>").text(" from " + sampleSize + " recent alerts"))
    );

    header.append(
        $("<button>")
            .attr("type", "button")
            .attr("data-matcher-editor-target", target)
            .addClass("btn btn-small matcher-editor-close-preview")
            .text("Close")
    );

    container.empty().append(header);

    if (!items.length) {
        container.append($("<div>").addClass("help-text").text("No recent alerts matched these conditions."));
        return;
    }

    const list = $("<div>").addClass("matcher-editor-preview-list");

    items.forEach(function (item) {
        const labels = Object.entries(item.labels || {}).slice(0, 6);
        const card = $("<button>")
            .attr("type", "button")
            .attr("data-group-id", item.group_id || "")
            .addClass("matcher-editor-preview-item")
            .prop("disabled", !item.group_id);

        card.append(
            $("<div>").addClass("matcher-editor-preview-item-header")
                .append($("<strong>").text(item.title || "Alert #" + item.id))
                .append($("<span>").text(matcherPreviewItemMeta(item)))
        );

        if (labels.length) {
            const labelsContainer = $("<div>").addClass("matcher-editor-preview-labels");

            labels.forEach(function (entry) {
                labelsContainer.append(
                    $("<span>").text(entry[0] + "=" + entry[1])
                );
            });

            card.append(labelsContainer);
        }

        list.append(card);
    });

    container.append(list);

    if (payload.truncated) {
        container.append($("<div>").addClass("help-text").text("Only the first " + items.length + " matching alerts are shown."));
    }
}


function loadMatcherPreview(idOrSelector, button) {
    const field = matcherEditorField(idOrSelector);
    let payload;

    try {
        payload = matcherPreviewPayload(field);
    } catch (error) {
        if (!field.hasClass("field-error")) {
            showAppError(error.message, "Preview unavailable");
        }

        return;
    }

    const originalText = button.text();
    button.prop("disabled", true).text("Checking...");

    apiPost("/api/matchers/preview", payload, function (response) {
        renderMatcherPreview(field, response);
        button.prop("disabled", false).text(originalText);
    }, function (xhr) {
        button.prop("disabled", false).text(originalText);
        showApiError(xhr);
    });
}

$(document).on("click", ".matcher-editor-run-preview", function () {
    loadMatcherPreview($(this).attr("data-matcher-editor-target"), $(this));
});


$(document).on("click", ".matcher-editor-close-preview", function () {
    matcherPreviewContainer($(this).attr("data-matcher-editor-target")).empty();
});


$(document).on("click", ".matcher-editor-preview-item", function () {
    const groupId = Number($(this).attr("data-group-id") || 0);

    if (groupId) {
        navigate("/alerts/" + encodeURIComponent(groupId), true);
    }
});

$(document).on("click", ".matcher-editor-format", function () {
    formatMatcherEditor($(this).attr("data-matcher-editor-target"));
});


$(document).on("click", ".matcher-editor-load-suggestions", function () {
    loadMatcherSuggestions($(this).attr("data-matcher-editor-target"), $(this));
});


$(document).on("click", ".matcher-editor-close-suggestions", function () {
    matcherSuggestionsContainer($(this).attr("data-matcher-editor-target")).empty();
});


$(document).on("click", ".matcher-editor-suggestion-name, .matcher-editor-suggestion-value", function () {
    insertMatcherSuggestion(
        $(this).attr("data-matcher-editor-target"),
        $(this).attr("data-matcher-suggestion-name"),
        $(this).attr("data-matcher-suggestion-value"),
        $(this).attr("data-matcher-suggestion-kind")
    );
});


$(document).on("input", ".matcher-editor-textarea", function () {
    $(this).removeClass("field-error");
});
