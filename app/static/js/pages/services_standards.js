(function () {
    let standardsState = {
        standards: [],
        selectedStandardId: null,
        checks: [],
    };
    let serviceStandardTomSelects = [];

    const CHECK_TYPES = [
        ["field_present", i18n.t("service_standards.check_type.field_present")],
        ["field_equals", i18n.t("service_standards.check_type.field_equals")],
        ["owner_exists", i18n.t("service_standards.check_type.owner_exists")],
        ["active_rotation_exists", i18n.t("service_standards.check_type.active_rotation_exists")],
        ["escalation_policy_exists", i18n.t("service_standards.check_type.escalation_policy_exists")],
        ["notification_policy_exists", i18n.t("service_standards.check_type.notification_policy_exists")],
        ["service_channel_exists", i18n.t("service_standards.check_type.service_channel_exists")],
        ["route_exists", i18n.t("service_standards.check_type.route_exists")],
        ["match_rule_exists", i18n.t("service_standards.check_type.match_rule_exists")],
        ["runbook_exists", i18n.t("service_standards.check_type.runbook_exists")],
        ["link_type_exists", i18n.t("service_standards.check_type.link_type_exists")],
        ["dependency_exists", i18n.t("service_standards.check_type.dependency_exists")],
        ["dependency_cycle_absent", i18n.t("service_standards.check_type.dependency_cycle_absent")],
        ["metadata_value", i18n.t("service_standards.check_type.metadata_value")],
    ];

    const SEVERITIES = [
        ["info", i18n.t("service_standards.severity.info")],
        ["warning", i18n.t("service_standards.severity.warning")],
        ["critical", i18n.t("service_standards.severity.critical")],
    ];

    const KIND_OPTIONS = [
        ["technical", i18n.t("service_standards.kind.technical")],
        ["business", i18n.t("service_standards.kind.business")],
    ];

    const LIFECYCLE_OPTIONS = [
        ["experimental", i18n.t("service_standards.lifecycle.experimental")],
        ["development", i18n.t("service_standards.lifecycle.development")],
        ["production", i18n.t("service_standards.lifecycle.production")],
        ["deprecated", i18n.t("service_standards.lifecycle.deprecated")],
        ["retired", i18n.t("service_standards.lifecycle.retired")],
    ];

    const TIER_OPTIONS = [
        ["tier_1", i18n.t("service_standards.tier.tier_1")],
        ["tier_2", i18n.t("service_standards.tier.tier_2")],
        ["tier_3", i18n.t("service_standards.tier.tier_3")],
        ["tier_4", i18n.t("service_standards.tier.tier_4")],
    ];

    const CRITICALITY_OPTIONS = [
        ["critical", i18n.t("service_standards.criticality.critical")],
        ["high", i18n.t("service_standards.criticality.high")],
        ["medium", i18n.t("service_standards.criticality.medium")],
        ["low", i18n.t("service_standards.criticality.low")],
    ];

    const ENVIRONMENT_OPTIONS = [
        ["production", i18n.t("service_standards.environment.production")],
        ["staging", i18n.t("service_standards.environment.staging")],
        ["development", i18n.t("service_standards.environment.development")],
        ["testing", i18n.t("service_standards.environment.testing")],
        ["shared", i18n.t("service_standards.environment.shared")],
    ];

    const SERVICE_TYPE_OPTIONS = [
        ["api", i18n.t("service_standards.service_type.api")],
        ["web", i18n.t("service_standards.service_type.web")],
        ["database", i18n.t("service_standards.service_type.database")],
        ["queue", i18n.t("service_standards.service_type.queue")],
        ["cache", i18n.t("service_standards.service_type.cache")],
        ["worker", i18n.t("service_standards.service_type.worker")],
        ["cron", i18n.t("service_standards.service_type.cron")],
        ["network", i18n.t("service_standards.service_type.network")],
        ["storage", i18n.t("service_standards.service_type.storage")],
        ["infrastructure", i18n.t("service_standards.service_type.infrastructure")],
        ["external", i18n.t("service_standards.service_type.external")],
        ["other", i18n.t("service_standards.service_type.other")],
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
                placeholder: $(this).data("placeholder") || i18n.t("service_standards.form.select_values"),
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

        if (confirm(options.message || options.title || i18n.t("service_standards.confirm.default"))) {
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

        renderStandardsLoading(i18n.t("service_standards.loading.standards"));
        renderChecksEmpty(i18n.t("service_standards.empty.select"));

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
                    renderChecksEmpty(i18n.t("service_standards.empty.select"));
                }
            })
            .catch(function (xhr) {
                renderStandardsEmpty(getErrorMessage(xhr, i18n.t("service_standards.errors.load_standards")));
            });
    }

    function loadStandardChecks(standardId) {
        renderChecksLoading(i18n.t("service_standards.loading.checks"));
        $("#new-service-standard-check-btn").prop("disabled", true);

        standardsApi("GET", "/api/services/standards/" + encodeURIComponent(standardId) + "/checks?include_disabled=1")
            .then(function (payload) {
                standardsState.checks = normalizeListResponse(payload);
                renderChecksTable();
            })
            .catch(function (xhr) {
                renderChecksEmpty(getErrorMessage(xhr, i18n.t("service_standards.errors.load_checks")));
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
            renderStandardsEmpty(i18n.t("service_standards.empty.none"));
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
                        .text(standardDisplayName(standard))
                        .on("click", function () {
                            selectStandard(standard.id);
                        })
                )
                .append($("<div>").addClass("row-subtitle").text(standard.slug || "-"))
        );
        row.append($("<td>").addClass("table-cell-truncate-wide").text(formatAppliesTo(standard.applies_to)));
        row.append($("<td>").text(Number(standard.checks_count || 0)));
        row.append($("<td>").append(renderStatusBadge(!!standard.enabled, i18n.t("service_standards.status.enabled"), i18n.t("service_standards.status.disabled"))));
        row.append($("<td>").addClass("actions-cell").append(renderStandardActions(standard)));

        return row;
    }

    function renderChecksTable() {
        const tbody = $("#service-standard-checks-list");
        const standard = getSelectedStandard();

        tbody.empty();
        $("#new-service-standard-check-btn").prop("disabled", !standard);
        $("#service-standard-checks-subtitle").text(
            standard ? standardDisplayName(standard) : i18n.t("service_standards.empty.select")
        );

        if (!standard) {
            renderChecksEmpty(i18n.t("service_standards.empty.select"));
            return;
        }

        if (!standardsState.checks.length) {
            renderChecksEmpty(i18n.t("service_standards.empty.no_checks"));
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
                .append($("<strong>").text(checkDisplayName(check)))
                .append($("<div>").addClass("row-subtitle").text(check.slug || "-"))
        );
        row.append($("<td>").text(optionLabel(CHECK_TYPES, check.check_type)));
        row.append($("<td>").text(Number(check.weight || 0)));
        row.append($("<td>").append(renderSeverityBadge(check.severity || "warning", !!check.required)));
        row.append($("<td>").append(renderStatusBadge(!!check.enabled, i18n.t("service_standards.status.enabled"), i18n.t("service_standards.status.disabled"))));
        row.append($("<td>").addClass("actions-cell").append(renderCheckActions(check)));

        return row;
    }

    function renderStandardActions(standard) {
        if (typeof window.makeActionMenu === "function") {
            return window.makeActionMenu({
                object: standard,
                items: [
                    {
                        label: i18n.t("service_standards.actions.edit"),
                        icon: "fas fa-edit",
                        onClick: function () {
                            openStandardModal(standard);
                        },
                    },
                    {
                        label: standard.enabled ? i18n.t("service_standards.actions.disable") : i18n.t("service_standards.actions.enable"),
                        icon: standard.enabled ? "fas fa-pause" : "fas fa-play",
                        onClick: function () {
                            toggleStandard(standard);
                        },
                    },
                    {
                        label: i18n.t("service_standards.actions.delete"),
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
            [i18n.t("service_standards.actions.edit"), function () {
                openStandardModal(standard);
            }],
            [standard.enabled ? i18n.t("service_standards.actions.disable") : i18n.t("service_standards.actions.enable"), function () {
                toggleStandard(standard);
            }],
            [i18n.t("service_standards.actions.delete"), function () {
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
                        label: i18n.t("service_standards.actions.edit"),
                        icon: "fas fa-edit",
                        onClick: function () {
                            openCheckModal(check);
                        },
                    },
                    {
                        label: check.enabled ? i18n.t("service_standards.actions.disable") : i18n.t("service_standards.actions.enable"),
                        icon: check.enabled ? "fas fa-pause" : "fas fa-play",
                        onClick: function () {
                            toggleCheck(check);
                        },
                    },
                    {
                        label: i18n.t("service_standards.actions.delete"),
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
            [i18n.t("service_standards.actions.edit"), function () {
                openCheckModal(check);
            }],
            [check.enabled ? i18n.t("service_standards.actions.disable") : i18n.t("service_standards.actions.enable"), function () {
                toggleCheck(check);
            }],
            [i18n.t("service_standards.actions.delete"), function () {
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

    function optionLabel(options, value) {
        const match = options.find(function (option) {
            return String(option[0]) === String(value || "");
        });

        return match ? match[1] : (value || "-");
    }

    function optionLabels(options, values) {
        return (values || []).map(function (value) {
            return optionLabel(options, value);
        }).join(", ");
    }

    function standardDisplayName(standard) {
        standard = standard || {};

        if (standard.slug === "basic-operational-readiness") {
            return i18n.t("service_standards.builtin.standard.basic");
        }

        return standard.name || standard.slug || i18n.t("service_standards.standard_number", {id: standard.id});
    }

    function checkDisplayName(check) {
        check = check || {};
        const builtin = {
            owner: "service_standards.builtin.check.owner",
            "escalation-policy": "service_standards.builtin.check.escalation_policy",
            "notification-policy": "service_standards.builtin.check.notification_policy",
            "alert-route": "service_standards.builtin.check.alert_route",
            runbook: "service_standards.builtin.check.runbook",
            "dependency-cycle": "service_standards.builtin.check.dependency_cycle",
        };

        if (Object.prototype.hasOwnProperty.call(builtin, check.slug)) {
            return i18n.t(builtin[check.slug]);
        }

        return check.name || check.slug || i18n.t("service_standards.check_number", {id: check.id});
    }

    function renderSeverityBadge(severity, required) {
        const severityLabel = optionLabel(SEVERITIES, severity);
        const text = required
            ? i18n.t("service_standards.severity.required", {severity: severityLabel})
            : severityLabel;
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
            parts.push(i18n.t("service_standards.applies.kind", {
                values: optionLabels(KIND_OPTIONS, appliesTo.kinds),
            }));
        }

        if (appliesTo.lifecycles && appliesTo.lifecycles.length) {
            parts.push(i18n.t("service_standards.applies.lifecycle", {
                values: optionLabels(LIFECYCLE_OPTIONS, appliesTo.lifecycles),
            }));
        }

        if (appliesTo.environments && appliesTo.environments.length) {
            parts.push(i18n.t("service_standards.applies.environment", {
                values: optionLabels(ENVIRONMENT_OPTIONS, appliesTo.environments),
            }));
        }

        if (appliesTo.tiers && appliesTo.tiers.length) {
            parts.push(i18n.t("service_standards.applies.tier", {
                values: optionLabels(TIER_OPTIONS, appliesTo.tiers),
            }));
        }

        if (appliesTo.criticalities && appliesTo.criticalities.length) {
            parts.push(i18n.t("service_standards.applies.criticality", {
                values: optionLabels(CRITICALITY_OPTIONS, appliesTo.criticalities),
            }));
        }

        if (appliesTo.service_types && appliesTo.service_types.length) {
            parts.push(i18n.t("service_standards.applies.type", {
                values: optionLabels(SERVICE_TYPE_OPTIONS, appliesTo.service_types),
            }));
        }

        return parts.length ? parts.join(" / ") : i18n.t("service_standards.applies.all");
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
            notifyError(i18n.t("service_standards.errors.restore_group"));
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
                notifyError(getErrorMessage(xhr, i18n.t("service_standards.errors.restore")));
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
                notifyError(getErrorMessage(xhr, i18n.t("service_standards.errors.update_standard")));
            });
    }

    function deleteStandard(standard) {
        confirmAction({
            title: i18n.t("service_standards.confirm.delete_standard_title"),
            message: i18n.t("service_standards.confirm.delete_standard_message", {name: standard.name || standard.slug || standard.id}),
            confirmText: i18n.t("service_standards.actions.delete"),
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
                    notifyError(getErrorMessage(xhr, i18n.t("service_standards.errors.delete_standard")));
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
                notifyError(getErrorMessage(xhr, i18n.t("service_standards.errors.update_check")));
            });
    }

    function deleteCheck(check) {
        const standard = getSelectedStandard();

        confirmAction({
            title: i18n.t("service_standards.confirm.delete_check_title"),
            message: i18n.t("service_standards.confirm.delete_check_message", {name: check.name || check.slug || check.id}),
            confirmText: i18n.t("service_standards.actions.delete"),
            confirmClass: "btn-danger",
        }, function () {
            standardsApi("DELETE", "/api/services/standards/" + encodeURIComponent(standard.id) + "/checks/" + encodeURIComponent(check.id))
                .then(function () {
                    refreshAfterStandardsChange();
                    loadStandardChecks(standard.id);
                    loadServiceStandards();
                })
                .catch(function (xhr) {
                    notifyError(getErrorMessage(xhr, i18n.t("service_standards.errors.delete_check")));
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
            notifyError(i18n.t("service_standards.errors.create_group"));
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
                                    .append($("<h2>").text(standard.id ? i18n.t("service_standards.form.edit_standard") : i18n.t("service_standards.form.new_standard")))
                                    .append($("<div>").addClass("card-subtitle").text(i18n.t("service_standards.form.standard_subtitle")))
                            )
                            .append(
                                $("<button>")
                                    .attr("type", "button")
                                    .addClass("app-modal-close")
                                    .attr("aria-label", i18n.t("common.close", {}, "Close"))
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
                                    .append(formLabel("service-standard-name", i18n.t("service_standards.form.name")))
                                    .append(textInput("service-standard-name", standard.name || "", i18n.t("service_standards.form.standard_name_placeholder")))
                                    .append(formLabel("service-standard-slug", i18n.t("service_standards.form.slug")))
                                    .append(textInput("service-standard-slug", standard.slug || "", "basic-operational-readiness"))
                                    .append(formLabel("service-standard-description", i18n.t("service_standards.form.description")))
                                    .append(textArea("service-standard-description", standard.description || ""))
                                    .append(formLabel("service-standard-kind", i18n.t("service_standards.form.kinds")))
                                    .append(multiSelectInput("service-standard-kind", KIND_OPTIONS, appliesTo.kinds || [], i18n.t("service_standards.form.select_kinds")))
                                    .append(formLabel("service-standard-lifecycle", i18n.t("service_standards.form.lifecycles")))
                                    .append(multiSelectInput("service-standard-lifecycle", LIFECYCLE_OPTIONS, appliesTo.lifecycles || [], i18n.t("service_standards.form.select_lifecycles")))
                                    .append(formLabel("service-standard-tier", i18n.t("service_standards.form.tiers")))
                                    .append(multiSelectInput("service-standard-tier", TIER_OPTIONS, appliesTo.tiers || [], i18n.t("service_standards.form.select_tiers")))
                                    .append(formLabel("service-standard-criticality", i18n.t("service_standards.form.criticalities")))
                                    .append(multiSelectInput("service-standard-criticality", CRITICALITY_OPTIONS, appliesTo.criticalities || [], i18n.t("service_standards.form.select_criticalities")))
                                    .append(formLabel("service-standard-environment", i18n.t("service_standards.form.environments")))
                                    .append(multiSelectInput("service-standard-environment", ENVIRONMENT_OPTIONS, appliesTo.environments || [], i18n.t("service_standards.form.select_environments")))
                                    .append(formLabel("service-standard-service-type", i18n.t("service_standards.form.service_types")))
                                    .append(multiSelectInput("service-standard-service-type", SERVICE_TYPE_OPTIONS, appliesTo.service_types || [], i18n.t("service_standards.form.select_service_types")))
                                    .append(checkboxLine("service-standard-enabled", i18n.t("service_standards.form.enabled"), standard.enabled !== false))
                                    .append(
                                        $("<div>")
                                            .addClass("form-actions")
                                            .append(
                                                $("<button>")
                                                    .attr("type", "button")
                                                    .addClass("btn")
                                                    .text(i18n.t("service_standards.actions.cancel"))
                                                    .on("click", function () {
                                                        closeServiceStandardModal("#service-standard-modal");
                                                    })
                                            )
                                            .append(
                                                $("<button>")
                                                    .attr("type", "button")
                                                    .addClass("btn btn-primary")
                                                    .text(i18n.t("service_standards.actions.save_standard"))
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
                                    .append($("<h2>").text(check.id ? i18n.t("service_standards.form.edit_check") : i18n.t("service_standards.form.new_check")))
                                    .append($("<div>").addClass("card-subtitle").text(standardDisplayName(standard)))
                            )
                            .append(
                                $("<button>")
                                    .attr("type", "button")
                                    .addClass("app-modal-close")
                                    .attr("aria-label", i18n.t("common.close", {}, "Close"))
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
                                    .append(formLabel("service-standard-check-name", i18n.t("service_standards.form.name")))
                                    .append(textInput("service-standard-check-name", check.name || "", i18n.t("service_standards.form.check_name_placeholder")))
                                    .append(formLabel("service-standard-check-slug", i18n.t("service_standards.form.slug")))
                                    .append(textInput("service-standard-check-slug", check.slug || "", "owner"))
                                    .append(formLabel("service-standard-check-description", i18n.t("service_standards.form.description")))
                                    .append(textArea("service-standard-check-description", check.description || ""))
                                    .append(formLabel("service-standard-check-type", i18n.t("service_standards.form.check_type")))
                                    .append(selectInput("service-standard-check-type", CHECK_TYPES, check.check_type || "owner_exists"))
                                    .append(formLabel("service-standard-check-configuration", i18n.t("service_standards.form.configuration")))
                                    .append(textArea("service-standard-check-configuration", JSON.stringify(check.configuration || {}, null, 2)))
                                    .append(formLabel("service-standard-check-weight", i18n.t("service_standards.form.weight")))
                                    .append(numberInput("service-standard-check-weight", check.weight || 0, 0, 100))
                                    .append(formLabel("service-standard-check-position", i18n.t("service_standards.form.position")))
                                    .append(numberInput("service-standard-check-position", check.position || 0, 0, 10000))
                                    .append(formLabel("service-standard-check-severity", i18n.t("service_standards.form.severity")))
                                    .append(selectInput("service-standard-check-severity", SEVERITIES, check.severity || "warning"))
                                    .append(checkboxLine("service-standard-check-required", i18n.t("service_standards.form.required"), !!check.required))
                                    .append(checkboxLine("service-standard-check-enabled", i18n.t("service_standards.form.enabled"), check.enabled !== false))
                                    .append(
                                        $("<div>")
                                            .addClass("form-actions")
                                            .append(
                                                $("<button>")
                                                    .attr("type", "button")
                                                    .addClass("btn")
                                                    .text(i18n.t("service_standards.actions.cancel"))
                                                    .on("click", function () {
                                                        closeAppModal("#service-standard-check-modal");
                                                    })
                                            )
                                            .append(
                                                $("<button>")
                                                    .attr("type", "button")
                                                    .addClass("btn btn-primary")
                                                    .text(i18n.t("service_standards.actions.save_check"))
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
            .attr("data-placeholder", placeholder || i18n.t("service_standards.form.select_values"))

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
            notifyError(i18n.t("service_standards.validation.name_slug"));
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
                notifyError(getErrorMessage(xhr, i18n.t("service_standards.errors.save_standard")));
            });
    }

    function saveCheck() {
        const standard = getSelectedStandard();
        const checkId = $("#service-standard-check-id").val();
        let configuration = {};

        try {
            configuration = JSON.parse($("#service-standard-check-configuration").val() || "{}");
        } catch (error) {
            notifyError(i18n.t("service_standards.validation.config_json"));
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
            notifyError(i18n.t("service_standards.validation.check_required"));
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
                notifyError(getErrorMessage(xhr, i18n.t("service_standards.errors.save_check")));
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
