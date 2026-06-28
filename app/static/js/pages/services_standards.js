(function () {
    let standardsState = {
        standards: [],
        selectedStandardId: null,
        checks: [],
    };
    let serviceStandardTomSelects = [];

    const CHECK_TYPES = [
        ["field_present", "Field present"],
        ["field_equals", "Field equals"],
        ["owner_exists", "Owner exists"],
        ["active_rotation_exists", "Active rotation exists"],
        ["escalation_policy_exists", "Escalation policy exists"],
        ["notification_policy_exists", "Notification policy exists"],
        ["service_channel_exists", "Service channel exists"],
        ["route_exists", "Route exists"],
        ["match_rule_exists", "Match rule exists"],
        ["runbook_exists", "Runbook exists"],
        ["link_type_exists", "Link type exists"],
        ["dependency_exists", "Dependency exists"],
        ["dependency_cycle_absent", "Dependency cycle absent"],
        ["metadata_value", "Metadata value"],
    ];

    const SEVERITIES = [
        ["info", "Info"],
        ["warning", "Warning"],
        ["critical", "Critical"],
    ];

    const SERVICE_OPTIONS = window.ServiceCatalogOptions || {};

    const KIND_OPTIONS = SERVICE_OPTIONS.kinds || [
        ["technical", "Technical"],
        ["business", "Business"],
    ];

    const LIFECYCLE_OPTIONS = SERVICE_OPTIONS.lifecycles || [
        ["experimental", "Experimental"],
        ["development", "Development"],
        ["production", "Production"],
        ["deprecated", "Deprecated"],
        ["retired", "Retired"],
    ];

    const TIER_OPTIONS = SERVICE_OPTIONS.tiers || [
        ["tier_1", "Tier 1"],
        ["tier_2", "Tier 2"],
        ["tier_3", "Tier 3"],
        ["tier_4", "Tier 4"],
    ];

    const CRITICALITY_OPTIONS = SERVICE_OPTIONS.criticalities || [
        ["critical", "Critical"],
        ["high", "High"],
        ["medium", "Medium"],
        ["low", "Low"],
    ];

    const ENVIRONMENT_OPTIONS = SERVICE_OPTIONS.environments || [
        ["production", "Production"],
        ["staging", "Staging"],
        ["development", "Development"],
        ["testing", "Testing"],
        ["shared", "Shared"],
    ];

    const SERVICE_TYPE_OPTIONS = SERVICE_OPTIONS.serviceTypes || SERVICE_OPTIONS.service_types || [
        ["api", "API"],
        ["web", "Web"],
        ["database", "Database"],
        ["queue", "Queue"],
        ["cache", "Cache"],
        ["worker", "Worker"],
        ["cron", "Cron"],
        ["network", "Network"],
        ["storage", "Storage"],
        ["infrastructure", "Infrastructure"],
        ["external", "External"],
        ["other", "Other"],
    ];

    function standardsApi(method, url, data) {
        return new Promise(function (resolve, reject) {
            const success = function (payload) {
                resolve(payload || {});
            };
            const error = function (xhr) {
                reject(xhr);
            };

            if (method === "GET" && typeof window.apiGet === "function") {
                window.apiGet(url, success, error);
                return;
            }

            if (method === "POST" && typeof window.apiPost === "function") {
                window.apiPost(url, data || {}, success, error);
                return;
            }

            if (method === "PUT" && typeof window.apiPut === "function") {
                window.apiPut(url, data || {}, success, error);
                return;
            }

            if (method === "DELETE" && typeof window.apiDelete === "function") {
                window.apiDelete(url, success, error);
                return;
            }

            $.ajax({
                url: url,
                method: method,
                data: data ? JSON.stringify(data) : undefined,
                contentType: "application/json",
                success: success,
                error: error,
            });
        });
    }

    function notifyError(message) {
        if (typeof window.showAppError === "function") {
            window.showAppError(message);
            return;
        }

        alert(message);
    }

    function getTomSelectClass() {
        if (window.TomSelect) {
            return window.TomSelect;
        }

        if (typeof TomSelect !== "undefined") {
            return TomSelect;
        }

        return null;
    }

    function destroyServiceStandardTomSelects() {
        serviceStandardTomSelects.forEach(function (instance) {
            if (instance && typeof instance.destroy === "function") {
                instance.destroy();
            }
        });

        serviceStandardTomSelects = [];
    }

    function initializeServiceStandardTomSelects() {
        const TomSelectClass = getTomSelectClass();

        if (!TomSelectClass) {
            return;
        }

        $("#service-standard-modal select[data-standard-tomselect='1']").each(function () {
            if (this.tomselect) {
                this.tomselect.destroy();
            }

            const options = {
                create: false,
                persist: false,
                maxItems: null,
                closeAfterSelect: false,
                hideSelected: true,
                placeholder: $(this).data("placeholder") || "Select values",
            };

            if (TomSelectClass.plugins && TomSelectClass.plugins.remove_button) {
                options.plugins = ["remove_button"];
            }

            serviceStandardTomSelects.push(new TomSelectClass(this, options));
        });
    }

    function closeServiceStandardModal(selector) {
        destroyServiceStandardTomSelects();
        closeAppModal(selector);
    }

    function getErrorMessage(xhr, fallback) {
        const payload = xhr && xhr.responseJSON ? xhr.responseJSON : null;

        if (payload && payload.error) {
            return payload.error;
        }

        if (payload && payload.message) {
            return payload.message;
        }

        return fallback;
    }

    function confirmAction(options, callback) {
        if (typeof window.showAppConfirm === "function") {
            window.showAppConfirm(options).done(callback);
            return;
        }

        if (confirm(options.message || options.title || "Are you sure?")) {
            callback();
        }
    }

    function normalizeListResponse(payload) {
        if (Array.isArray(payload)) {
            return payload;
        }

        if (payload && Array.isArray(payload.items)) {
            return payload.items;
        }

        if (payload && Array.isArray(payload.standards)) {
            return payload.standards;
        }

        if (payload && Array.isArray(payload.data)) {
            return payload.data;
        }

        return [];
    }

    function getSelectedService() {
        if (!window.selectedServiceId || !Array.isArray(window.servicesCache)) {
            return null;
        }

        return window.servicesCache.find(function (service) {
            return Number(service.id) === Number(window.selectedServiceId);
        }) || null;
    }

    function getSelectedGroupId() {
        const selectors = [
            "#global-group-filter",
            "#services-group-filter",
            "#service-group-filter",
            "#group-filter",
            "select[name='group_id']",
        ];

        for (let i = 0; i < selectors.length; i += 1) {
            const value = $(selectors[i]).val();

            if (value && value !== "all") {
                return Number(value);
            }
        }

        const selectedService = getSelectedService();

        if (selectedService && selectedService.group_id) {
            return Number(selectedService.group_id);
        }

        if (Array.isArray(window.servicesCache) && window.servicesCache.length) {
            const service = window.servicesCache.find(function (item) {
                return !!item.group_id;
            });

            if (service) {
                return Number(service.group_id);
            }
        }

        if (window.currentGroupId) {
            return Number(window.currentGroupId);
        }

        if (window.activeGroupId) {
            return Number(window.activeGroupId);
        }

        return null;
    }

    function buildStandardsUrl() {
        const groupId = getSelectedGroupId();
        let url = "/api/services/standards?include_disabled=1";

        if (groupId) {
            url += "&group_id=" + encodeURIComponent(groupId);
        }

        return url;
    }

    function loadServiceStandards() {
        const tbody = $("#service-standards-list");

        if (!tbody.length) {
            return;
        }

        renderStandardsLoading("Loading service standards...");
        renderChecksEmpty("Select a standard to manage checks.");

        standardsApi("GET", buildStandardsUrl())
            .then(function (payload) {
                standardsState.standards = normalizeListResponse(payload);
                $("#services-standards-count").text(standardsState.standards.length);

                if (
                    standardsState.selectedStandardId &&
                    !getStandardById(standardsState.selectedStandardId)
                ) {
                    standardsState.selectedStandardId = null;
                    standardsState.checks = [];
                }

                if (!standardsState.selectedStandardId && standardsState.standards.length) {
                    standardsState.selectedStandardId = standardsState.standards[0].id;
                }

                renderStandardsTable();

                if (standardsState.selectedStandardId) {
                    loadStandardChecks(standardsState.selectedStandardId);
                } else {
                    renderChecksEmpty("Select a standard to manage checks.");
                }
            })
            .catch(function (xhr) {
                renderStandardsEmpty(getErrorMessage(xhr, "Failed to load service standards."));
            });
    }

    function loadStandardChecks(standardId) {
        renderChecksLoading("Loading checks...");
        $("#new-service-standard-check-btn").prop("disabled", true);

        standardsApi("GET", "/api/services/standards/" + encodeURIComponent(standardId) + "/checks?include_disabled=1")
            .then(function (payload) {
                standardsState.checks = normalizeListResponse(payload);
                renderChecksTable();
            })
            .catch(function (xhr) {
                renderChecksEmpty(getErrorMessage(xhr, "Failed to load service standard checks."));
            });
    }

    function renderStandardsLoading(message) {
        $("#service-standards-list").html(
            $("<tr>").append($("<td>").attr("colspan", 5).addClass("empty-cell").text(message))
        );
    }

    function renderStandardsEmpty(message) {
        $("#services-standards-count").text("0");

        $("#service-standards-list").html(
            $("<tr>").append($("<td>").attr("colspan", 5).addClass("empty-cell").text(message))
        );
    }

    function renderChecksLoading(message) {
        $("#service-standard-checks-list").html(
            $("<tr>").append($("<td>").attr("colspan", 6).addClass("empty-cell").text(message))
        );
    }

    function renderChecksEmpty(message) {
        $("#new-service-standard-check-btn").prop("disabled", !getSelectedStandard());
        $("#service-standard-checks-list").html(
            $("<tr>").append($("<td>").attr("colspan", 6).addClass("empty-cell").text(message))
        );
    }

    function renderStandardsTable() {
        const tbody = $("#service-standards-list");
        tbody.empty();

        if (!standardsState.standards.length) {
            renderStandardsEmpty("No service standards configured for this group.");
            return;
        }

        standardsState.standards.forEach(function (standard) {
            tbody.append(renderStandardRow(standard));
        });
    }

    function renderStandardRow(standard) {
        const selected = Number(standard.id) === Number(standardsState.selectedStandardId);
        const row = $("<tr>").toggleClass("is-selected", selected).toggleClass("row-disabled", !standard.enabled);

        row.append(
            $("<td>")
                .addClass("table-cell-truncate")
                .append(
                    $("<button>")
                        .attr("type", "button")
                        .addClass("name-button")
                        .text(standard.name || standard.slug || ("Standard #" + standard.id))
                        .on("click", function () {
                            selectStandard(standard.id);
                        })
                )
                .append($("<div>").addClass("row-subtitle").text(standard.slug || "-"))
        );
        row.append($("<td>").addClass("table-cell-truncate-wide").text(formatAppliesTo(standard.applies_to)));
        row.append($("<td>").text(Number(standard.checks_count || 0)));
        row.append($("<td>").append(renderStatusBadge(!!standard.enabled, "Enabled", "Disabled")));
        row.append($("<td>").addClass("actions-cell").append(renderStandardActions(standard)));

        return row;
    }

    function renderChecksTable() {
        const tbody = $("#service-standard-checks-list");
        const standard = getSelectedStandard();

        tbody.empty();
        $("#new-service-standard-check-btn").prop("disabled", !standard);
        $("#service-standard-checks-subtitle").text(
            standard ? (standard.name || standard.slug || "Selected standard") : "Select a standard to manage checks."
        );

        if (!standard) {
            renderChecksEmpty("Select a standard to manage checks.");
            return;
        }

        if (!standardsState.checks.length) {
            renderChecksEmpty("This standard has no checks.");
            return;
        }

        standardsState.checks.forEach(function (check) {
            tbody.append(renderCheckRow(check));
        });
    }

    function renderCheckRow(check) {
        const row = $("<tr>").toggleClass("row-disabled", !check.enabled);

        row.append(
            $("<td>")
                .addClass("table-cell-truncate")
                .append($("<strong>").text(check.name || check.slug || ("Check #" + check.id)))
                .append($("<div>").addClass("row-subtitle").text(check.slug || "-"))
        );
        row.append($("<td>").text(check.check_type || "-"));
        row.append($("<td>").text(Number(check.weight || 0)));
        row.append($("<td>").append(renderSeverityBadge(check.severity || "warning", !!check.required)));
        row.append($("<td>").append(renderStatusBadge(!!check.enabled, "Enabled", "Disabled")));
        row.append($("<td>").addClass("actions-cell").append(renderCheckActions(check)));

        return row;
    }

    function renderStandardActions(standard) {
        if (typeof window.makeActionMenu === "function") {
            return window.makeActionMenu({
                object: standard,
                items: [
                    {
                        label: "Edit",
                        icon: "fas fa-edit",
                        onClick: function () {
                            openStandardModal(standard);
                        },
                    },
                    {
                        label: standard.enabled ? "Disable" : "Enable",
                        icon: standard.enabled ? "fas fa-pause" : "fas fa-play",
                        onClick: function () {
                            toggleStandard(standard);
                        },
                    },
                    {
                        label: "Delete",
                        icon: "fas fa-trash",
                        danger: true,
                        onClick: function () {
                            deleteStandard(standard);
                        },
                    },
                ],
            });
        }

        return renderInlineActionFallback([
            ["Edit", function () {
                openStandardModal(standard);
            }],
            [standard.enabled ? "Disable" : "Enable", function () {
                toggleStandard(standard);
            }],
            ["Delete", function () {
                deleteStandard(standard);
            }, true],
        ]);
    }

    function renderCheckActions(check) {
        if (typeof window.makeActionMenu === "function") {
            return window.makeActionMenu({
                object: getSelectedStandard() || {},
                items: [
                    {
                        label: "Edit",
                        icon: "fas fa-edit",
                        onClick: function () {
                            openCheckModal(check);
                        },
                    },
                    {
                        label: check.enabled ? "Disable" : "Enable",
                        icon: check.enabled ? "fas fa-pause" : "fas fa-play",
                        onClick: function () {
                            toggleCheck(check);
                        },
                    },
                    {
                        label: "Delete",
                        icon: "fas fa-trash",
                        danger: true,
                        onClick: function () {
                            deleteCheck(check);
                        },
                    },
                ],
            });
        }

        return renderInlineActionFallback([
            ["Edit", function () {
                openCheckModal(check);
            }],
            [check.enabled ? "Disable" : "Enable", function () {
                toggleCheck(check);
            }],
            ["Delete", function () {
                deleteCheck(check);
            }, true],
        ]);
    }

    function renderInlineActionFallback(items) {
        const wrapper = $("<div>").addClass("action-buttons");

        items.forEach(function (item) {
            wrapper.append(
                $("<button>")
                    .attr("type", "button")
                    .addClass(item[2] ? "btn btn-danger" : "btn")
                    .text(item[0])
                    .on("click", item[1])
            );
        });

        return wrapper;
    }

    function renderSeverityBadge(severity, required) {
        const text = required ? severity + " / required" : severity;
        const cssClass = severity === "critical"
            ? "status-pill status-inactive"
            : severity === "warning"
                ? "status-pill status-scheduled"
                : "status-pill status-neutral";

        return $("<span>").addClass(cssClass).text(text);
    }

    function formatAppliesTo(appliesTo) {
        appliesTo = appliesTo || {};

        const parts = [];

        if (appliesTo.kinds && appliesTo.kinds.length) {
            parts.push("kind: " + appliesTo.kinds.join(", "));
        }

        if (appliesTo.lifecycles && appliesTo.lifecycles.length) {
            parts.push("lifecycle: " + appliesTo.lifecycles.join(", "));
        }

        if (appliesTo.environments && appliesTo.environments.length) {
            parts.push("env: " + appliesTo.environments.join(", "));
        }

        if (appliesTo.tiers && appliesTo.tiers.length) {
            parts.push("tier: " + appliesTo.tiers.join(", "));
        }

        if (appliesTo.criticalities && appliesTo.criticalities.length) {
            parts.push("criticality: " + appliesTo.criticalities.join(", "));
        }

        if (appliesTo.service_types && appliesTo.service_types.length) {
            parts.push("type: " + appliesTo.service_types.join(", "));
        }

        return parts.length ? parts.join(" / ") : "all services";
    }

    function getStandardById(id) {
        return standardsState.standards.find(function (standard) {
            return Number(standard.id) === Number(id);
        }) || null;
    }

    function getSelectedStandard() {
        return getStandardById(standardsState.selectedStandardId);
    }

    function getCheckById(id) {
        return standardsState.checks.find(function (check) {
            return Number(check.id) === Number(id);
        }) || null;
    }

    function selectStandard(standardId) {
        standardsState.selectedStandardId = standardId;
        renderStandardsTable();
        loadStandardChecks(standardId);
    }

    function restoreBasicStandard() {
        const groupId = getSelectedGroupId();

        if (!groupId) {
            notifyError("Group is required to restore the default service standard.");
            return;
        }

        standardsApi("POST", "/api/services/standards/presets/basic-operational", {
            group_id: groupId,
        })
            .then(function (standard) {
                standardsState.selectedStandardId = standard.id;
                refreshAfterStandardsChange();
                loadServiceStandards();
            })
            .catch(function (xhr) {
                notifyError(getErrorMessage(xhr, "Failed to restore default service standard."));
            });
    }

    function toggleStandard(standard) {
        const payload = buildStandardPayload(standard);
        payload.enabled = !standard.enabled;

        standardsApi("PUT", "/api/services/standards/" + encodeURIComponent(standard.id), payload)
            .then(function () {
                refreshAfterStandardsChange();
                loadServiceStandards();
            })
            .catch(function (xhr) {
                notifyError(getErrorMessage(xhr, "Failed to update service standard."));
            });
    }

    function deleteStandard(standard) {
        confirmAction({
            title: "Delete this service standard?",
            message: "Delete service standard \"" + (standard.name || standard.slug || standard.id) + "\"?",
            confirmText: "Delete",
            confirmClass: "btn-danger",
        }, function () {
            standardsApi("DELETE", "/api/services/standards/" + encodeURIComponent(standard.id))
                .then(function () {
                    standardsState.selectedStandardId = null;
                    standardsState.checks = [];
                    refreshAfterStandardsChange();
                    loadServiceStandards();
                })
                .catch(function (xhr) {
                    notifyError(getErrorMessage(xhr, "Failed to delete service standard."));
                });
        });
    }

    function toggleCheck(check) {
        const standard = getSelectedStandard();
        const payload = buildCheckPayload(check);
        payload.enabled = !check.enabled;

        standardsApi(
            "PUT",
            "/api/services/standards/" + encodeURIComponent(standard.id) + "/checks/" + encodeURIComponent(check.id),
            payload
        )
            .then(function () {
                refreshAfterStandardsChange();
                loadStandardChecks(standard.id);
                loadServiceStandards();
            })
            .catch(function (xhr) {
                notifyError(getErrorMessage(xhr, "Failed to update readiness check."));
            });
    }

    function deleteCheck(check) {
        const standard = getSelectedStandard();

        confirmAction({
            title: "Delete this readiness check?",
            message: "Delete readiness check \"" + (check.name || check.slug || check.id) + "\"?",
            confirmText: "Delete",
            confirmClass: "btn-danger",
        }, function () {
            standardsApi("DELETE", "/api/services/standards/" + encodeURIComponent(standard.id) + "/checks/" + encodeURIComponent(check.id))
                .then(function () {
                    refreshAfterStandardsChange();
                    loadStandardChecks(standard.id);
                    loadServiceStandards();
                })
                .catch(function (xhr) {
                    notifyError(getErrorMessage(xhr, "Failed to delete readiness check."));
                });
        });
    }

    function bindStandardSlugAutofill(isNewStandard) {
        const nameSelector = "#service-standard-name";
        const slugSelector = "#service-standard-slug";

        if (!$(nameSelector).length || !$(slugSelector).length) {
            return;
        }

        if (window.AppSlug) {
            window.AppSlug.bind(nameSelector, slugSelector, {
                manualWhenHasValue: true,
                initialUpdate: !!isNewStandard,
            });
            return;
        }

        $(nameSelector).off(".standardSlug").on("input.standardSlug change.standardSlug", function () {
            const slugInput = $(slugSelector);

            if (slugInput.data("slug-manual")) {
                return;
            }

            slugInput.val(slugifyFallback($(this).val()));
        });

        $(slugSelector).off(".standardSlug").on("input.standardSlug change.standardSlug", function () {
            const current = $(this).val();
            const autoValue = slugifyFallback($(nameSelector).val());

            if (!current) {
                $(this).data("slug-manual", false);
                $(this).val(autoValue);
                return;
            }

            $(this).data("slug-manual", current !== autoValue);
        });
    }


    function slugifyFallback(value) {
        return String(value || "")
            .toLowerCase()
            .trim()
            .replace(/['"`]/g, "")
            .replace(/[^a-z0-9]+/g, "-")
            .replace(/^-+|-+$/g, "")
            .replace(/-{2,}/g, "-");
    }

    function openStandardModal(standard) {
        const groupId = standard ? standard.group_id : getSelectedGroupId();

        if (!groupId) {
            notifyError("Group is required to create a service standard.");
            return;
        }

        $("#service-standard-modal").remove();
        $("body").append(renderStandardModal(standard, groupId));
        openAppModal("#service-standard-modal");

        bindStandardSlugAutofill(!standard);
    }

    function openCheckModal(check) {
        const standard = getSelectedStandard();

        if (!standard) {
            return;
        }

        $("#service-standard-check-modal").remove();
        $("body").append(renderCheckModal(standard, check));
        openAppModal("#service-standard-check-modal");
        if (window.AppSlug) {
            window.AppSlug.bind("#service-standard-name", "#service-standard-slug", {
                manualWhenHasValue: true,
                initialUpdate: !standard,
            });
        }
    }

    function renderStandardModal(standard, groupId) {
        standard = standard || {
            group_id: groupId,
            slug: "",
            name: "",
            description: "",
            applies_to: {
                kinds: ["technical"],
                lifecycles: ["production"],
            },
            enabled: true,
        };

        const appliesTo = standard.applies_to || {};

        return $("<div>")
            .attr("id", "service-standard-modal")
            .addClass("app-modal")
            .hide()
            .append(
                $("<div>")
                    .addClass("app-modal-dialog app-modal-dialog-wide")
                    .append(
                        $("<div>")
                            .addClass("app-modal-header")
                            .append(
                                $("<div>")
                                    .append($("<h2>").text(standard.id ? "Edit service standard" : "New service standard"))
                                    .append($("<div>").addClass("card-subtitle").text("Readiness requirements for matching services."))
                            )
                            .append(
                                $("<button>")
                                    .attr("type", "button")
                                    .addClass("app-modal-close")
                                    .attr("aria-label", "Close")
                                    .text("×")
                                    .on("click", function () {
                                        closeServiceStandardModal("#service-standard-modal");
                                    })
                            )
                    )
                    .append(
                        $("<div>")
                            .addClass("app-modal-body")
                            .append(
                                $("<div>")
                                    .addClass("form-body")
                                    .append(hiddenInput("standard-id", standard.id || ""))
                                    .append(hiddenInput("standard-group-id", standard.group_id || groupId))
                                    .append(formLabel("service-standard-name", "Name"))
                                    .append(textInput("service-standard-name", standard.name || "", "Basic operational readiness"))
                                    .append(formLabel("service-standard-slug", "Slug"))
                                    .append(textInput("service-standard-slug", standard.slug || "", "basic-operational-readiness"))
                                    .append(formLabel("service-standard-description", "Description"))
                                    .append(textArea("service-standard-description", standard.description || ""))
                                    .append(formLabel("service-standard-kind", "Kinds"))
                                    .append(multiSelectInput("service-standard-kind", KIND_OPTIONS, appliesTo.kinds || [], "Select kinds"))
                                    .append(formLabel("service-standard-lifecycle", "Lifecycles"))
                                    .append(multiSelectInput("service-standard-lifecycle", LIFECYCLE_OPTIONS, appliesTo.lifecycles || [], "Select lifecycles"))
                                    .append(formLabel("service-standard-tier", "Tiers"))
                                    .append(multiSelectInput("service-standard-tier", TIER_OPTIONS, appliesTo.tiers || [], "Select tiers"))
                                    .append(formLabel("service-standard-criticality", "Criticalities"))
                                    .append(multiSelectInput("service-standard-criticality", CRITICALITY_OPTIONS, appliesTo.criticalities || [], "Select criticalities"))
                                    .append(formLabel("service-standard-environment", "Environments"))
                                    .append(multiSelectInput("service-standard-environment", ENVIRONMENT_OPTIONS, appliesTo.environments || [], "Select environments"))
                                    .append(formLabel("service-standard-service-type", "Service types"))
                                    .append(multiSelectInput("service-standard-service-type", SERVICE_TYPE_OPTIONS, appliesTo.service_types || [], "Select service types"))
                                    .append(checkboxLine("service-standard-enabled", "Enabled", standard.enabled !== false))
                                    .append(
                                        $("<div>")
                                            .addClass("form-actions")
                                            .append(
                                                $("<button>")
                                                    .attr("type", "button")
                                                    .addClass("btn")
                                                    .text("Cancel")
                                                    .on("click", function () {
                                                        closeServiceStandardModal("#service-standard-modal");
                                                    })
                                            )
                                            .append(
                                                $("<button>")
                                                    .attr("type", "button")
                                                    .addClass("btn btn-primary")
                                                    .text("Save standard")
                                                    .on("click", saveStandard)
                                            )
                                    )
                            )
                    )
            );
    }

    function renderCheckModal(standard, check) {
        check = check || {
            slug: "",
            name: "",
            description: "",
            check_type: "owner_exists",
            configuration: {},
            weight: 10,
            severity: "critical",
            required: true,
            enabled: true,
            position: nextCheckPosition(),
        };

        return $("<div>")
            .attr("id", "service-standard-check-modal")
            .addClass("app-modal")
            .hide()
            .append(
                $("<div>")
                    .addClass("app-modal-dialog app-modal-dialog-wide")
                    .append(
                        $("<div>")
                            .addClass("app-modal-header")
                            .append(
                                $("<div>")
                                    .append($("<h2>").text(check.id ? "Edit readiness check" : "New readiness check"))
                                    .append($("<div>").addClass("card-subtitle").text(standard.name || standard.slug || "Selected standard"))
                            )
                            .append(
                                $("<button>")
                                    .attr("type", "button")
                                    .addClass("app-modal-close")
                                    .attr("aria-label", "Close")
                                    .text("×")
                                    .on("click", function () {
                                        closeAppModal("#service-standard-check-modal");
                                    })
                            )
                    )
                    .append(
                        $("<div>")
                            .addClass("app-modal-body")
                            .append(
                                $("<div>")
                                    .addClass("form-body")
                                    .append(hiddenInput("service-standard-check-id", check.id || ""))
                                    .append(formLabel("service-standard-check-name", "Name"))
                                    .append(textInput("service-standard-check-name", check.name || "", "Owner configured"))
                                    .append(formLabel("service-standard-check-slug", "Slug"))
                                    .append(textInput("service-standard-check-slug", check.slug || "", "owner"))
                                    .append(formLabel("service-standard-check-description", "Description"))
                                    .append(textArea("service-standard-check-description", check.description || ""))
                                    .append(formLabel("service-standard-check-type", "Check type"))
                                    .append(selectInput("service-standard-check-type", CHECK_TYPES, check.check_type || "owner_exists"))
                                    .append(formLabel("service-standard-check-configuration", "Configuration JSON"))
                                    .append(textArea("service-standard-check-configuration", JSON.stringify(check.configuration || {}, null, 2)))
                                    .append(formLabel("service-standard-check-weight", "Weight"))
                                    .append(numberInput("service-standard-check-weight", check.weight || 0, 0, 100))
                                    .append(formLabel("service-standard-check-position", "Position"))
                                    .append(numberInput("service-standard-check-position", check.position || 0, 0, 10000))
                                    .append(formLabel("service-standard-check-severity", "Severity"))
                                    .append(selectInput("service-standard-check-severity", SEVERITIES, check.severity || "warning"))
                                    .append(checkboxLine("service-standard-check-required", "Required", !!check.required))
                                    .append(checkboxLine("service-standard-check-enabled", "Enabled", check.enabled !== false))
                                    .append(
                                        $("<div>")
                                            .addClass("form-actions")
                                            .append(
                                                $("<button>")
                                                    .attr("type", "button")
                                                    .addClass("btn")
                                                    .text("Cancel")
                                                    .on("click", function () {
                                                        closeAppModal("#service-standard-check-modal");
                                                    })
                                            )
                                            .append(
                                                $("<button>")
                                                    .attr("type", "button")
                                                    .addClass("btn btn-primary")
                                                    .text("Save check")
                                                    .on("click", saveCheck)
                                            )
                                    )
                            )
                    )
            );
    }

    function formLabel(forId, text) {
        const label = $("<label>").text(text);

        if (forId) {
            label.attr("for", forId);
        }

        return label;
    }

    function hiddenInput(id, value) {
        return $("<input>").attr("type", "hidden").attr("id", id).val(value);
    }

    function textInput(id, value, placeholder) {
        return $("<input>")
            .attr("id", id)
            .attr("type", "text")
            .addClass("input")
            .attr("placeholder", placeholder || "")
            .val(value || "");
    }

    function numberInput(id, value, min, max) {
        return $("<input>")
            .attr("id", id)
            .attr("type", "number")
            .attr("min", min)
            .attr("max", max)
            .addClass("input")
            .val(value || 0);
    }

    function textArea(id, value) {
        return $("<textarea>")
            .attr("id", id)
            .addClass("input")
            .attr("rows", 4)
            .val(value || "");
    }

    function selectInput(id, options, selected) {
        const select = $("<select>").attr("id", id);

        options.forEach(function (option) {
            select.append(
                $("<option>")
                    .val(option[0])
                    .text(option[1])
                    .prop("selected", option[0] === selected)
            );
        });

        return select;
    }

    function multiSelectInput(id, options, selectedValues, placeholder) {
        const selected = (selectedValues || []).map(String);
        const select = $("<select>")
            .attr("id", id)
            .attr("multiple", "multiple")
            .attr("data-standard-tomselect", "1")
            .attr("data-placeholder", placeholder || "Select values")

        options.forEach(function (option) {
            const value = String(option[0]);

            select.append(
                $("<option>")
                    .val(value)
                    .text(option[1])
                    .prop("selected", selected.indexOf(value) !== -1)
            );
        });

        return select;
    }

    function checkboxLine(id, label, checked) {
        return $("<label>")
            .addClass("md-checkbox")
            .append($("<input>").attr("id", id).attr("type", "checkbox").prop("checked", !!checked))
            .append($("<span>").text(label));
    }

    function checkboxGroup(name, options, selectedValues) {
        const wrapper = $("<div>").addClass("form-grid-3");
        selectedValues = selectedValues || [];

        options.forEach(function (option) {
            wrapper.append(
                $("<label>")
                    .addClass("md-checkbox")
                    .append(
                        $("<input>")
                            .attr("type", "checkbox")
                            .attr("name", name)
                            .val(option[0])
                            .prop("checked", selectedValues.indexOf(option[0]) !== -1)
                    )
                    .append($("<span>").text(option[1]))
            );
        });

        return wrapper;
    }

    function saveStandard() {
        const standardId = $("#standard-id").val();
        const payload = {
            group_id: Number($("#standard-group-id").val()),
            name: $("#service-standard-name").val().trim(),
            slug: $("#service-standard-slug").val().trim(),
            description: $("#service-standard-description").val().trim(),
            applies_to: buildAppliesToPayload(),
            enabled: $("#service-standard-enabled").is(":checked"),
        };

        if (!payload.name || !payload.slug) {
            notifyError("Name and slug are required.");
            return;
        }

        const method = standardId ? "PUT" : "POST";
        const url = standardId
            ? "/api/services/standards/" + encodeURIComponent(standardId)
            : "/api/services/standards";

        standardsApi(method, url, payload)
            .then(function (standard) {
                closeServiceStandardModal("#service-standard-modal");
                standardsState.selectedStandardId = standard.id || standardsState.selectedStandardId;
                refreshAfterStandardsChange();
                loadServiceStandards();
            })
            .catch(function (xhr) {
                notifyError(getErrorMessage(xhr, "Failed to save service standard."));
            });
    }

    function saveCheck() {
        const standard = getSelectedStandard();
        const checkId = $("#service-standard-check-id").val();
        let configuration = {};

        try {
            configuration = JSON.parse($("#service-standard-check-configuration").val() || "{}");
        } catch (error) {
            notifyError("Configuration must be valid JSON.");
            return;
        }

        const payload = {
            name: $("#service-standard-check-name").val().trim(),
            slug: $("#service-standard-check-slug").val().trim(),
            description: $("#service-standard-check-description").val().trim(),
            check_type: $("#service-standard-check-type").val(),
            configuration: configuration,
            weight: Number($("#service-standard-check-weight").val() || 0),
            position: Number($("#service-standard-check-position").val() || 0),
            severity: $("#service-standard-check-severity").val(),
            required: $("#service-standard-check-required").is(":checked"),
            enabled: $("#service-standard-check-enabled").is(":checked"),
        };

        if (!standard || !payload.name || !payload.slug || !payload.check_type) {
            notifyError("Name, slug and check type are required.");
            return;
        }

        const method = checkId ? "PUT" : "POST";
        const url = checkId
            ? "/api/services/standards/" + encodeURIComponent(standard.id) + "/checks/" + encodeURIComponent(checkId)
            : "/api/services/standards/" + encodeURIComponent(standard.id) + "/checks";

        standardsApi(method, url, payload)
            .then(function () {
                closeAppModal("#service-standard-check-modal");
                refreshAfterStandardsChange();
                loadStandardChecks(standard.id);
                loadServiceStandards();
            })
            .catch(function (xhr) {
                notifyError(getErrorMessage(xhr, "Failed to save readiness check."));
            });
    }

    function buildStandardPayload(standard) {
        return {
            group_id: standard.group_id,
            slug: standard.slug,
            name: standard.name,
            description: standard.description || "",
            applies_to: standard.applies_to || {},
            enabled: !!standard.enabled,
        };
    }

    function buildCheckPayload(check) {
        return {
            slug: check.slug,
            name: check.name,
            description: check.description || "",
            check_type: check.check_type,
            configuration: check.configuration || {},
            weight: Number(check.weight || 0),
            position: Number(check.position || 0),
            severity: check.severity || "warning",
            required: !!check.required,
            enabled: !!check.enabled,
        };
    }

    function buildAppliesToPayload() {
        const appliesTo = {};
        const kinds = selectedValues("service-standard-kind");
        const lifecycles = selectedValues("service-standard-lifecycle");
        const tiers = selectedValues("service-standard-tier");
        const criticalities = selectedValues("service-standard-criticality");
        const environments = selectedValues("service-standard-environment");
        const serviceTypes = selectedValues("service-standard-service-type");

        if (kinds.length) {
            appliesTo.kinds = kinds;
        }

        if (lifecycles.length) {
            appliesTo.lifecycles = lifecycles;
        }

        if (tiers.length) {
            appliesTo.tiers = tiers;
        }

        if (criticalities.length) {
            appliesTo.criticalities = criticalities;
        }

        if (environments.length) {
            appliesTo.environments = environments;
        }

        if (serviceTypes.length) {
            appliesTo.service_types = serviceTypes;
        }

        return appliesTo;
    }

    function selectedValues(id) {
        const field = $("#" + id);

        if (field.length) {
            const value = field.val();

            if (Array.isArray(value)) {
                return value;
            }

            return value ? [value] : [];
        }

        return $("input[name='" + id + "']:checked").map(function () {
            return $(this).val();
        }).get();
    }

    function csvToArray(value) {
        if (!value) {
            return [];
        }

        return value
            .split(",")
            .map(function (item) {
                return item.trim();
            })
            .filter(Boolean);
    }

    function arrayToCsv(value) {
        return Array.isArray(value) ? value.join(",") : "";
    }

    function nextCheckPosition() {
        if (!standardsState.checks.length) {
            return 10;
        }

        return standardsState.checks.reduce(function (max, check) {
            return Math.max(max, Number(check.position || 0));
        }, 0) + 10;
    }

    function refreshAfterStandardsChange() {
        if (typeof window.refreshServices === "function") {
            window.refreshServices();
        }

        if (
            window.selectedServiceId &&
            $("#service-details-modal").is(":visible") &&
            typeof window.loadServiceDetails === "function"
        ) {
            window.loadServiceDetails(window.selectedServiceId);
        }
    }

    function bindStandardsEvents() {
        $(document).on("click", "#restore-basic-standard-btn", restoreBasicStandard);
        $(document).on("click", "#new-service-standard-btn", function () {
            openStandardModal(null);
        });
        $(document).on("click", "#new-service-standard-check-btn", function () {
            openCheckModal(null);
        });

        $(document).on("click", "#service-standard-modal, #service-standard-check-modal", function (event) {
            if (event.target !== this) {
                return;
            }

            if (this.id === "service-standard-modal") {
                closeServiceStandardModal("#service-standard-modal");
                return;
            }

            closeAppModal("#" + this.id);
        });
    }

    window.loadServiceStandards = loadServiceStandards;

    $(function () {
        bindStandardsEvents();
        loadServiceStandards();
    });
})();
