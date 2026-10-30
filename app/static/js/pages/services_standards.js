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
        ["component", i18n.t("service_standards.kind.component")],
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

    // Service attributes read by the field_present / field_equals evaluators.
    const CHECK_SERVICE_FIELDS = [
        ["description", "string", "service_standards.form.description"],
        ["name", "string", "service_standards.form.name"],
        ["slug", "string", "service_standards.form.slug"],
        ["kind", "string", "service_standards.form.kinds", KIND_OPTIONS],
        ["lifecycle", "string", "service_standards.form.lifecycles", LIFECYCLE_OPTIONS],
        ["environment", "string", "services.table.environment", ENVIRONMENT_OPTIONS],
        ["service_type", "string", "service_standards.form.service_types", SERVICE_TYPE_OPTIONS],
        ["criticality", "string", "services.table.criticality", CRITICALITY_OPTIONS],
        ["tier", "string", "service_standards.form.tiers", TIER_OPTIONS],
        ["status", "string", "services.table.status", ["operational", "degraded", "partial_outage", "major_outage", "maintenance", "unknown"]
            .map(value => [value, i18n.t("services.status." + value)])],
        ["status_message", "string"],
        ["status_source", "string"],
        ["enabled", "boolean", "service_standards.form.enabled"],
        ["public", "boolean"],
        ["public_name", "string"],
        ["public_description", "string"],
        ["public_order", "number"],
        ["team_id", "number", "services.table.team"],
        ["group_id", "number"],
        ["default_rotation_id", "number"],
        ["default_escalation_policy_id", "number"],
        ["notification_policy_id", "number"],
        ["priority_policy_id", "number"],
        ["labels", "json"],
        ["tags", "json"],
        ["metadata", "json", "services.form.metadata"],
        ["id", "number"],
        ["uid", "string"],
        ["created_at", "string"],
        ["updated_at", "string"],
        ["status_updated_at", "string"],
        ["status_updated_by_id", "number"],
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
                hidePlaceholder: true,
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
        if (typeof window.getApiErrorMessage === "function") {
            return window.getApiErrorMessage(xhr, fallback);
        }
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

    function closeStandardsActionMenu() {
        if (typeof window.closeOpenedActionMenu === "function" &&
            $("#service-standards-list .app-action-menu.is-open, #service-standard-checks-list .app-action-menu.is-open").length) {
            window.closeOpenedActionMenu();
        }
    }

    function renderStandardsLoading(message) {
        closeStandardsActionMenu();
        $("#service-standards-list").html(
            $("<tr>").append($("<td>").attr("colspan", 5).addClass("empty-cell").text(message))
        );
    }

    function renderStandardsEmpty(message) {
        closeStandardsActionMenu();
        $("#services-standards-count").text("0");

        $("#service-standards-list").html(
            $("<tr>").append($("<td>").attr("colspan", 5).addClass("empty-cell").text(message))
        );
    }

    function renderChecksLoading(message) {
        closeStandardsActionMenu();
        $("#service-standard-checks-list").html(
            $("<tr>").append($("<td>").attr("colspan", 6).addClass("empty-cell").text(message))
        );
    }

    function renderChecksEmpty(message) {
        closeStandardsActionMenu();
        $("#new-service-standard-check-btn").prop("disabled", !getSelectedStandard());
        $("#service-standard-checks-list").html(
            $("<tr>").append($("<td>").attr("colspan", 6).addClass("empty-cell").text(message))
        );
    }

    function renderStandardsTable() {
        closeStandardsActionMenu();
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
        closeStandardsActionMenu();
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

        destroyServiceStandardTomSelects();
        $("#service-standard-modal").remove();
        $("body").append(renderStandardModal(standard, groupId));
        openAppModal("#service-standard-modal");
        initializeServiceStandardTomSelects();

        bindStandardSlugAutofill(!standard);
        $("#service-standard-name").trigger("focus");
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
            window.AppSlug.bind("#service-standard-check-name", "#service-standard-check-slug", {
                manualWhenHasValue: true,
                initialUpdate: !check,
            });
        }
        $("#service-standard-check-name").trigger("focus");
    }

    function editorField(id, labelKey, input, fullWidth) {
        return $("<div>").addClass("service-editor-field")
            .toggleClass("service-editor-full", !!fullWidth)
            .append(formLabel(id, i18n.t("service_standards.form." + labelKey)))
            .append(input);
    }

    function editorSection(id, icon, titleKey, hintKey, content) {
        return $("<section>").addClass("service-editor-section").attr("aria-labelledby", id)
            .append($("<div>").addClass("service-editor-heading")
                .append($("<span>").addClass("service-editor-icon").attr("aria-hidden", "true")
                    .append($("<i>").addClass("fas " + icon)))
                .append($("<div>")
                    .append($("<h3>").attr("id", id).text(i18n.t("service_standards.form." + titleKey)))
                    .append($("<p>").text(i18n.t("service_standards.form." + hintKey)))))
            .append(content);
    }

    function editorModal(id, title, subtitle, content, saveId, saveLabel, onSave) {
        const close = function () {
            if (!$("#" + id).data("saving")) {
                closeServiceStandardModal("#" + id);
            }
        };
        return $("<div>").attr({id: id, role: "dialog", "aria-modal": "true", "aria-labelledby": id + "-title"})
            .addClass("app-modal standard-editor-modal").hide()
            .append($("<div>").addClass("app-modal-dialog service-editor-dialog")
                .append($("<div>").addClass("app-modal-header")
                    .append($("<div>")
                        .append($("<h2>").attr("id", id + "-title").text(title))
                        .append($("<div>").addClass("card-subtitle").text(subtitle)))
                    .append(makeButton({className: "app-modal-close", label: "×",
                        ariaLabel: i18n.t("common.close"), onClick: close})))
                .append($("<div>").addClass("app-modal-body service-editor-body").append(content))
                .append($("<div>").addClass("app-modal-footer service-editor-footer")
                    .append($("<p>").addClass("service-editor-error standard-editor-error")
                        .attr("role", "alert").prop("hidden", true))
                    .append(makeButton({className: "btn", label: i18n.t("service_standards.actions.cancel"),
                        onClick: close}).attr("data-editor-cancel", "1"))
                    .append(makeButton({className: "btn btn-primary", label: saveLabel,
                        onClick: onSave}).attr("id", saveId))));
    }

    function renderStandardModal(standard, groupId) {
        standard = standard || {
            group_id: groupId, slug: "", name: "", description: "",
            applies_to: {kinds: ["technical"], lifecycles: ["production"]}, enabled: true,
        };
        const appliesTo = standard.applies_to || {};
        const identity = $("<div>").addClass("service-editor-fields")
            .append(hiddenInput("standard-id", standard.id || ""))
            .append(hiddenInput("standard-group-id", standard.group_id || groupId))
            .append(editorField("service-standard-name", "name",
                textInput("service-standard-name", standard.name, i18n.t("service_standards.form.standard_name_placeholder")), true))
            .append(editorField("service-standard-slug", "slug",
                textInput("service-standard-slug", standard.slug, "basic-operational-readiness"), true))
            .append(editorField("service-standard-description", "description",
                textArea("service-standard-description", standard.description), true))
            .append($("<div>").addClass("service-editor-options service-editor-full")
                .append(checkboxLine("service-standard-enabled", i18n.t("service_standards.form.enabled"), standard.enabled !== false))
                .append($("<p>").addClass("help-text").text(i18n.t("service_standards.form.enabled_hint"))));
        const scope = $("<div>").addClass("service-editor-fields");
        const filters = [
            ["kind", "kinds", KIND_OPTIONS],
            ["lifecycle", "lifecycles", LIFECYCLE_OPTIONS],
            ["environment", "environments", ENVIRONMENT_OPTIONS],
            ["tier", "tiers", TIER_OPTIONS],
            ["criticality", "criticalities", CRITICALITY_OPTIONS],
            ["service-type", "service_types", SERVICE_TYPE_OPTIONS],
        ];
        filters.forEach(function ([field, key, options]) {
            const id = "service-standard-" + field;
            scope.append(editorField(id, key, multiSelectInput(
                id, options, appliesTo[key] || [], i18n.t("service_standards.form.any_value")
            )));
        });
        scope.append($("<p>").addClass("standard-editor-note service-editor-full")
            .text(i18n.t("service_standards.form.scope_note")));
        if (appliesTo.labels && Object.keys(appliesTo.labels).length) {
            scope.append($("<div>").addClass("service-editor-field service-editor-full")
                .append($("<span>").addClass("service-editor-label").text(i18n.t("service_standards.form.label_filters")))
                .append($("<pre>").addClass("standard-editor-labels").text(JSON.stringify(appliesTo.labels, null, 2))));
        }
        const grid = $("<div>").addClass("service-editor-grid")
            .append(editorSection("standard-identity-heading", "fa-clipboard-check", "identity", "identity_hint", identity))
            .append(editorSection("standard-scope-heading", "fa-filter", "scope", "scope_hint", scope));
        return editorModal("service-standard-modal",
            i18n.t(standard.id ? "service_standards.form.edit_standard" : "service_standards.form.new_standard"),
            i18n.t("service_standards.form.standard_subtitle"), grid,
            "save-service-standard", i18n.t("service_standards.actions.save_standard"), saveStandard
        ).data("applies-to", appliesTo);
    }

    function renderCheckModal(standard, check) {
        check = check || {
            slug: "", name: "", description: "", check_type: "owner_exists", configuration: {},
            weight: 10, severity: "critical", required: true, enabled: true, position: nextCheckPosition(),
        };
        const identity = $("<div>").addClass("service-editor-fields")
            .append(hiddenInput("service-standard-check-id", check.id || ""))
            .append(editorField("service-standard-check-name", "name",
                textInput("service-standard-check-name", check.name, i18n.t("service_standards.form.check_name_placeholder")), true))
            .append(editorField("service-standard-check-slug", "slug",
                textInput("service-standard-check-slug", check.slug, "owner"), true))
            .append(editorField("service-standard-check-description", "description",
                textArea("service-standard-check-description", check.description), true));
        const scoring = $("<div>").addClass("service-editor-fields")
            .append(editorField("service-standard-check-weight", "weight",
                numberInput("service-standard-check-weight", check.weight, 1, 100)))
            .append(editorField("service-standard-check-position", "position",
                numberInput("service-standard-check-position", check.position, 0)))
            .append(editorField("service-standard-check-severity", "severity",
                selectInput("service-standard-check-severity", SEVERITIES, check.severity), true))
            .append($("<div>").addClass("service-editor-options service-editor-full")
                .append(checkboxLine("service-standard-check-required", i18n.t("service_standards.form.required"), !!check.required))
                .append(checkboxLine("service-standard-check-enabled", i18n.t("service_standards.form.enabled"), check.enabled !== false)));
        const checkType = selectInput("service-standard-check-type", CHECK_TYPES, check.check_type);
        const configuration = $("<div>").addClass("service-editor-fields")
            .append(editorField("service-standard-check-type", "check_type",
                checkType, true))
            .append(createCheckConfigurationEditor(checkType, check));
        const grid = $("<div>").addClass("service-editor-grid")
            .append($("<div>").addClass("standard-editor-stack")
                .append(editorSection("check-identity-heading", "fa-clipboard-check", "check_identity", "check_identity_hint", identity))
                .append(editorSection("check-scoring-heading", "fa-sliders-h", "scoring", "scoring_hint", scoring)))
            .append(editorSection("check-condition-heading", "fa-code", "condition", "condition_hint", configuration));
        return editorModal("service-standard-check-modal",
            i18n.t(check.id ? "service_standards.form.edit_check" : "service_standards.form.new_check"),
            standardDisplayName(standard), grid,
            "save-service-standard-check", i18n.t("service_standards.actions.save_check"), saveCheck);
    }

    function isFieldCheck(type) {
        return type === "field_present" || type === "field_equals";
    }

    function fieldConfigurationDraft(configuration) {
        const field = CHECK_SERVICE_FIELDS.find(option => option[0] === configuration.field);
        const hasValue = Object.prototype.hasOwnProperty.call(configuration, "value");
        const value = configuration.value;
        const valueType = !hasValue ? (field ? field[1] : "string")
            : value === null ? "null" : typeof value === "object" ? "json" : typeof value;
        return {
            original: configuration,
            field: configuration.field || "",
            valueType: valueType,
            rawValue: !hasValue ? "" : valueType === "string" ? value : JSON.stringify(value, null, 2),
        };
    }

    function createCheckConfigurationEditor(typeSelect, check) {
        const editor = $("<div>").attr("id", "standard-check-configuration-editor").addClass("service-editor-full");
        const drafts = new Map();
        let activeType = check.check_type;
        drafts.set(activeType, isFieldCheck(activeType) ? fieldConfigurationDraft(check.configuration || {})
            : {raw: JSON.stringify(check.configuration || {}, null, 2)});

        function render() {
            editor.empty().removeData("read");
            const draft = drafts.get(activeType);
            if (isFieldCheck(activeType)) {
                renderFieldCheckConfiguration(editor, activeType, draft);
            } else {
                editor.append(renderJsonCheckConfiguration(draft.raw));
                editor.data("capture", () => ({raw: editor.find("textarea").val()}));
            }
        }

        typeSelect.on("change", function () {
            const previousDraft = editor.data("capture")();
            drafts.set(activeType, previousDraft);
            const nextType = typeSelect.val();
            if (!drafts.has(nextType)) {
                drafts.set(nextType, isFieldCheck(nextType)
                    ? fieldConfigurationDraft(isFieldCheck(activeType) ? {field: previousDraft.field} : {})
                    : {raw: "{}"});
            }
            activeType = nextType;
            render();
        });
        render();
        return editor;
    }

    function renderFieldCheckConfiguration(editor, checkType, draft) {
        const options = [["", i18n.t("service_standards.form.choose_field")]].concat(CHECK_SERVICE_FIELDS.map(function (field) {
            return [field[0], field[2] ? i18n.t(field[2]) + " · " + field[0] : field[0]];
        }));
        // Keep older/custom attributes selectable instead of silently replacing them.
        if (draft.field && !options.some(option => option[0] === draft.field)) {
            options.push([draft.field, draft.field]);
        }
        const field = selectInput("service-standard-check-field", options, draft.field);
        const error = $("<p>").attr({id: "standard-check-field-error", role: "alert"})
            .addClass("service-editor-error service-editor-full").prop("hidden", true);
        const fields = $("<div>").addClass("service-editor-fields")
            .append(editorField("service-standard-check-field", "service_field", field, true))
            .append($("<p>").addClass("help-text service-editor-full")
                .text(i18n.t("service_standards.form." + checkType + "_hint")));
        const valueTypes = ["string", "number", "boolean", "null", "json"].map(type => [
            type, i18n.t("service_standards.value_type." + type),
        ]);
        const valueType = selectInput("service-standard-check-value-type", valueTypes, draft.valueType);
        const valueContainer = $("<div>").addClass("service-editor-full");
        let valueInput = $();

        function clearError() {
            error.text("").prop("hidden", true);
            fields.find("[aria-invalid]").removeAttr("aria-invalid");
        }

        function renderValue(rawValue) {
            const type = valueType.val();
            const id = "service-standard-check-value";
            valueContainer.empty();
            valueInput = $();
            if (type === "null") {
                valueContainer.append($("<p>").addClass("standard-editor-note")
                    .text(i18n.t("service_standards.form.null_value_hint")));
                return;
            }
            if (type === "boolean") {
                valueInput = selectInput(id, [["true", i18n.t("service_standards.value.true")],
                    ["false", i18n.t("service_standards.value.false")]], rawValue === "false" ? "false" : "true");
            } else if (type === "json") {
                valueInput = textArea(id, rawValue || "{}").addClass("standard-editor-json").attr("spellcheck", "false");
            } else {
                valueInput = textInput(id, rawValue).attr("autocomplete", "off");
                if (type === "number") {
                    valueInput.attr({type: "number", step: "any", required: true});
                }
            }
            valueInput.attr("aria-describedby", "standard-check-field-error").on("input change", clearError);
            valueContainer.append(editorField(id, "expected_value", valueInput, true));
            const definition = CHECK_SERVICE_FIELDS.find(option => option[0] === field.val());
            if (type === "string" && definition && definition[3]) {
                const suggestions = $("<datalist>").attr("id", "standard-check-value-options");
                definition[3].forEach(option => suggestions.append($("<option>").val(option[0]).text(option[1])));
                valueInput.attr("list", "standard-check-value-options");
                valueContainer.append(suggestions);
            }
        }

        field.attr("aria-describedby", "standard-check-field-error").on("change", function () {
            clearError();
            const definition = CHECK_SERVICE_FIELDS.find(option => option[0] === field.val());
            const nextType = definition ? definition[1] : "string";
            const previousValue = nextType === valueType.val() ? valueInput.val() : "";
            valueType.val(nextType);
            renderValue(previousValue || "");
        });
        valueType.on("change", function () {
            clearError();
            renderValue("");
        });
        if (checkType === "field_equals") {
            fields.append(editorField("service-standard-check-value-type", "value_type", valueType, true))
                .append(valueContainer);
            renderValue(draft.rawValue);
        }
        editor.append(fields.append(error));
        editor.data("capture", () => ({original: draft.original, field: field.val(),
            valueType: valueType.val(), rawValue: valueInput.val() || ""}));
        editor.data("read", function () {
            clearError();
            function invalid(input, message) {
                error.text(i18n.t("service_standards.validation." + message)).prop("hidden", false);
                input.attr("aria-invalid", "true").trigger("focus");
                return null;
            }
            if (!field.val()) {
                return invalid(field, "field_required");
            }
            const configuration = Object.assign({}, draft.original, {field: field.val()});
            if (checkType === "field_present") {
                delete configuration.value;
                return configuration;
            }
            const raw = valueInput.val();
            switch (valueType.val()) {
                case "number":
                    if (!raw || !valueInput[0].checkValidity() || !Number.isFinite(Number(raw))) {
                        return invalid(valueInput, "number_value");
                    }
                    configuration.value = Number(raw);
                    break;
                case "boolean": configuration.value = raw === "true"; break;
                case "null": configuration.value = null; break;
                case "json":
                    try {
                        configuration.value = JSON.parse(raw);
                    } catch (error) {
                        if (!(error instanceof SyntaxError)) {
                            throw error;
                        }
                        return invalid(valueInput, "config_json");
                    }
                    break;
                default: configuration.value = raw;
            }
            return configuration;
        });
    }

    function renderJsonCheckConfiguration(raw) {
        return $("<div>").addClass("service-editor-field")
            .append($("<div>").addClass("service-metadata-toolbar")
                .append(formLabel("service-standard-check-configuration", i18n.t("service_standards.form.configuration")))
                .append(makeButton({className: "btn btn-sm", label: i18n.t("service_standards.form.format_json"),
                    onClick: function () {
                        formatJsonTextarea("#service-standard-check-configuration", {}, "", checkConfigurationOptions());
                    }}).attr("id", "format-standard-check-json")))
            .append(textArea("service-standard-check-configuration", raw)
                .attr({rows: 12, spellcheck: "false", "aria-describedby": "standard-check-config-hint standard-check-config-error"})
                .addClass("standard-editor-json")
                .on("input", function () {
                    clearJsonInputError(this, "#standard-check-config-error");
                }))
            .append($("<p>").attr("id", "standard-check-config-hint").addClass("help-text")
                .text(i18n.t("service_standards.form.configuration_hint")))
            .append($("<p>").attr({id: "standard-check-config-error", role: "alert"})
                .addClass("service-editor-error").prop("hidden", true));
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
        const select = $("<select>").attr("id", id).addClass("input");

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
        const modal = $("#service-standard-modal");
        if (modal.data("saving")) {
            return;
        }
        modal.find(".standard-editor-error").text("").prop("hidden", true);
        const standardId = $("#standard-id").val();
        const payload = {
            name: $("#service-standard-name").val().trim(),
            slug: $("#service-standard-slug").val().trim(),
            description: $("#service-standard-description").val().trim(),
            applies_to: buildAppliesToPayload(),
            enabled: $("#service-standard-enabled").is(":checked"),
        };
        if (!standardId) {
            payload.group_id = Number($("#standard-group-id").val());
        }

        if (!payload.name || !payload.slug) {
            notifyError(i18n.t("service_standards.validation.name_slug"));
            return;
        }

        const method = standardId ? "PUT" : "POST";
        const url = standardId
            ? "/api/services/standards/" + encodeURIComponent(standardId)
            : "/api/services/standards";

        setAppModalSaving(modal, true);
        standardsApi(method, url, payload)
            .then(function (standard) {
                setAppModalSaving(modal, false);
                closeServiceStandardModal("#service-standard-modal");
                standardsState.selectedStandardId = standard.id || standardsState.selectedStandardId;
                refreshAfterStandardsChange();
                loadServiceStandards();
            })
            .catch(function (xhr) {
                setAppModalSaving(modal, false);
                modal.find(".standard-editor-error")
                    .text(getErrorMessage(xhr, i18n.t("service_standards.errors.save_standard")))
                    .prop("hidden", false);
            });
    }

    function checkConfigurationOptions() {
        return {
            objectOnly: true,
            errorTarget: "#standard-check-config-error",
            invalidMessage: i18n.t("service_standards.validation.config_json"),
            objectMessage: i18n.t("service_standards.validation.config_object"),
        };
    }

    function readCheckConfiguration() {
        const readFieldConfiguration = $("#standard-check-configuration-editor").data("read");
        return readFieldConfiguration ? readFieldConfiguration()
            : readJsonObjectInput("#service-standard-check-configuration", checkConfigurationOptions());
    }

    function saveCheck() {
        const modal = $("#service-standard-check-modal");
        if (modal.data("saving")) {
            return;
        }
        modal.find(".standard-editor-error").text("").prop("hidden", true);
        const standard = getSelectedStandard();
        const checkId = $("#service-standard-check-id").val();
        const configuration = readCheckConfiguration();
        if (configuration === null) {
            return;
        }
        const invalidNumber = modal.find("input[type=number]").toArray().find(function (input) {
            return !input.checkValidity() || input.value === "";
        });
        if (invalidNumber) {
            invalidNumber.required = true;
            invalidNumber.reportValidity();
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

        setAppModalSaving(modal, true);
        standardsApi(method, url, payload)
            .then(function () {
                setAppModalSaving(modal, false);
                closeAppModal("#service-standard-check-modal");
                refreshAfterStandardsChange();
                loadStandardChecks(standard.id);
                loadServiceStandards();
            })
            .catch(function (xhr) {
                setAppModalSaving(modal, false);
                modal.find(".standard-editor-error")
                    .text(getErrorMessage(xhr, i18n.t("service_standards.errors.save_check")))
                    .prop("hidden", false);
            });
    }

    function buildStandardPayload(standard) {
        return {
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
        const appliesTo = Object.assign({}, $("#service-standard-modal").data("applies-to") || {});
        ["kinds", "lifecycles", "tiers", "criticalities", "environments", "service_types"].forEach(function (key) {
            delete appliesTo[key];
        });
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
