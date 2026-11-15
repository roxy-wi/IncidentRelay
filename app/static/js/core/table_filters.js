(function () {
    "use strict";

    function normalizeTableFilterValues(values) {
        if (values === undefined || values === null) {
            return [];
        }

        if (!Array.isArray(values)) {
            values = [values];
        }

        const result = [];
        const seen = {};

        values.forEach(function (value) {
            if (value === undefined || value === null) {
                return;
            }

            String(value).split(",").forEach(function (item) {
                item = String(item || "").trim();

                if (!item || seen[item]) {
                    return;
                }

                seen[item] = true;
                result.push(item);
            });
        });

        return result;
    }

    function getTableFilterValues(selector) {
        const select = $(selector);

        if (!select.length) {
            return [];
        }

        if (select[0].tomselect) {
            return normalizeTableFilterValues(select[0].tomselect.getValue());
        }

        return normalizeTableFilterValues(select.val());
    }

    function setTableFilterSilent(selector, value) {
        $(selector).data("table-filter-silent", value === true);
    }


    function isTableFilterSilent(selector) {
        return $(selector).data("table-filter-silent") === true;
    }


    function withTableFilterSilentChange(selector, callback) {
        const select = $(selector);

        setTableFilterSilent(select, true);

        try {
            return callback(select);
        } finally {
            window.setTimeout(function () {
                setTableFilterSilent(select, false);
            }, 0);
        }
    }


    function setTableFilterValues(selector, values, options) {
        options = options || {};
        values = normalizeTableFilterValues(values);

        const select = $(selector);

        if (!select.length) {
            return;
        }

        withTableFilterSilentChange(select, function () {
            if (select[0].tomselect) {
                select[0].tomselect.setValue(values, true);
                return;
            }

            select.val(values);
        });

        if (options.triggerChange) {
            select.trigger("change");
        }
    }


    function refreshTableMultiSelect(selector) {
        const select = $(selector);

        if (!select.length) {
            return;
        }

        if (!select.data("table-multi-select-ready")) {
            ensureTableMultiSelect(select);
            return;
        }

        if (!select[0].tomselect) {
            return;
        }

        withTableFilterSilentChange(select, function () {
            select[0].tomselect.sync();
            select[0].tomselect.refreshOptions(false);
        });
    }

    function appendTableFilterParams(params, name, values) {
        normalizeTableFilterValues(values).forEach(function (value) {
            if (params instanceof URLSearchParams) {
                params.append(name, value);
                return;
            }

            if (Array.isArray(params)) {
                params.push(
                    encodeURIComponent(name) + "=" + encodeURIComponent(value)
                );
                return;
            }

            if (params && typeof params.append === "function") {
                params.append(name, value);
                return;
            }

            throw new TypeError("appendTableFilterParams expects URLSearchParams or array");
        });
    }

    function getTableFilterParamValues(params, name, aliases) {
        aliases = aliases || [];

        let values = [];

        [name].concat(aliases).forEach(function (key) {
            values = values.concat(params.getAll(key));
        });

        return normalizeTableFilterValues(values);
    }

    function tableSelectOptionLabel(selector, value) {
        const select = $(selector);
        const option = select.find("option").filter(function () {
            return String($(this).val()) === String(value);
        }).first();

        return option.length ? option.text() : value;
    }

    function renderTableFilterChips(targetSelector, chips) {
        const target = $(targetSelector);

        target.empty();
        target.addClass("table-filter-chips");

        (chips || []).forEach(function (chip) {
            let text = chip.label || "";

            if (chip.value !== undefined && chip.value !== null && chip.value !== "") {
                text += ": " + chip.value;
            }

            if (!text) {
                return;
            }

            target.append(
                $("<span>")
                    .addClass("table-filter-chip")
                    .text(text)
            );
        });
    }

    function ensureTableMultiSelect(select) {
        select = $(select);

        if (!select.length || select.data("table-multi-select-ready")) {
            return;
        }

        select.data("table-multi-select-ready", true);

        if (typeof TomSelect === "undefined") {
            console.error("TomSelect is not loaded");
            return;
        }

        const isSingle = select.is("[data-table-single-select]");
        new TomSelect(select[0], {
            wrapperClass: "ts-wrapper table-filter-control",
            plugins: isSingle ? [] : ["remove_button"],
            create: false,
            persist: false,
            maxItems: isSingle ? 1 : null,
            closeAfterSelect: isSingle,
            hideSelected: true,
            allowEmptyOption: isSingle,
            placeholder: select.data("placeholder") || "All",
            hidePlaceholder: true,
            render: {
                item: function (data, escape) {
                    const label = escape(data.text);
                    return '<div><span class="table-filter-value" title="' + label + '">' + label + '</span></div>';
                },
                no_results: function () {
                    return '<div class="no-results">No results found</div>';
                }
            }
        });
    }

    function initTableMultiSelects(root) {
        root = root || document;

        $(root)
            .find("select[data-table-multi-select], select[data-table-single-select]")
            .each(function () {
                ensureTableMultiSelect(this);
            });
    }


    function clearTableMultiSelect(selector) {
        const select = $(selector);

        if (!select.length) {
            return;
        }

        if (select[0].tomselect) {
            select[0].tomselect.clear(true);
            select.trigger("change");
            return;
        }

        select.val([]);
        select.trigger("change");
    }

    function normalizeTableSelectOptions(options) {
        return (options || [])
            .map(function (option) {
                if (option === undefined || option === null) {
                    return null;
                }

                if (typeof option === "object") {
                    return {
                        value: String(option.value),
                        text: String(option.text || option.label || option.value)
                    };
                }

                return {
                    value: String(option),
                    text: String(option)
                };
            })
            .filter(Boolean);
    }


    function replaceTableSelectOptions(selector, options, selectedValues) {
        const select = $(selector);
        const normalizedOptions = normalizeTableSelectOptions(options);
        const allowedValues = normalizedOptions.map(function (option) {
            return String(option.value);
        });

        selectedValues = normalizeTableFilterValues(selectedValues).filter(function (value) {
            return allowedValues.indexOf(String(value)) !== -1;
        });

        if (!select.length) {
            return;
        }

        withTableFilterSilentChange(select, function () {
            select.empty();

            normalizedOptions.forEach(function (option) {
                select.append(
                    $("<option>")
                        .val(option.value)
                        .text(option.text)
                );
            });

            if (select[0].tomselect) {
                const ts = select[0].tomselect;

                ts.clear(true);
                ts.clearOptions();

                normalizedOptions.forEach(function (option) {
                    ts.addOption({
                        value: option.value,
                        text: option.text
                    });
                });

                ts.refreshOptions(false);
                ts.setValue(selectedValues, true);
                return;
            }

            select.val(selectedValues);
        });
    }

    function tableServiceFilterScope() {
        return [
            currentUser && currentUser.id,
            currentUser && currentUser.active_group_id,
            selectedTeamId() || "all"
        ].join(":");
    }

    function loadTableServiceFilter(selector, selectedValues, callback) {
        // Cache per control and authorization/team scope. A late response must
        // not restore options or selections from a previously selected team.
        const select = $(selector);
        if (!select.length) {
            callback();
            return;
        }
        const scope = tableServiceFilterScope();
        const state = select.data("service-filter-state") || {generation: 0};
        select.data("service-filter-state", state);
        const generation = ++state.generation;
        const control = select[0].tomselect;
        function enable() {
            if (control) control.enable();
            else select.prop("disabled", false);
        }
        function applyOptions(options) {
            replaceTableSelectOptions(select, options, selectedValues);
            refreshTableMultiSelect(select);
        }
        if (state.scope === scope) {
            enable();
            applyOptions(state.options);
            callback();
            return;
        }
        if (control) control.disable();
        else select.prop("disabled", true);
        function finish() {
            if (generation !== state.generation || scope !== tableServiceFilterScope()) return false;
            enable();
            return true;
        }
        apiGet("/api/services" + selectedTeamQuery(), function (response) {
            if (!finish()) return;
            const services = Array.isArray(response) ? response : (response.items || []);
            state.options = services.filter(service => service.enabled !== false).map(service => ({
                value: String(service.id),
                text: [service.team_name || service.team_slug, service.name || service.slug || service.id]
                    .filter(Boolean).join(" / ")
            }));
            state.scope = scope;
            applyOptions(state.options);
            callback();
        }, function (xhr) {
            if (!finish()) return;
            callback(xhr);
        });
    }

    window.loadTableServiceFilter = loadTableServiceFilter;
    window.normalizeTableFilterValues = normalizeTableFilterValues;
    window.getTableFilterValues = getTableFilterValues;
    window.setTableFilterValues = setTableFilterValues;
    window.appendTableFilterParams = appendTableFilterParams;
    window.getTableFilterParamValues = getTableFilterParamValues;
    window.renderTableFilterChips = renderTableFilterChips;
    window.tableSelectOptionLabel = tableSelectOptionLabel;
    window.initTableMultiSelects = initTableMultiSelects;
    window.refreshTableMultiSelect = refreshTableMultiSelect;
    window.clearTableMultiSelect = clearTableMultiSelect;
    window.isTableFilterSilent = isTableFilterSilent;
    window.replaceTableSelectOptions = replaceTableSelectOptions;
})();

