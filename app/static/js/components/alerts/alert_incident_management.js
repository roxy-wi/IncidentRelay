window.AlertIncidentManagement = (function () {
    const priorityCache = {
        loaded: false,
        items: [],
    };

    const optionCache = {};

    const responderTargetFields = {
        user: "target_user_id",
        team: "target_team_id",
        rotation: "target_rotation_id",
        escalation_policy: "target_escalation_policy_id",
    };

    const responderTargetLabels = {
        user: i18n.t("alert_details.target.user"),
        team: i18n.t("alert_details.target.team"),
        rotation: i18n.t("alert_details.target.rotation"),
        escalation_policy: i18n.t("alert_details.target.escalation_policy"),
    };

    const responderTargetPlaceholders = {
        user: i18n.t("alert_details.target.select_user"),
        team: i18n.t("alert_details.manual.select_team"),
        rotation: i18n.t("alert_details.target.select_rotation"),
        escalation_policy: i18n.t("alert_details.target.select_policy"),
    };

    const responderTargetHelp = {
        user: i18n.t("alert_details.target.user_help"),
        team: i18n.t("alert_details.target.team_help"),
        rotation: i18n.t("alert_details.target.rotation_help"),
        escalation_policy: i18n.t("alert_details.target.policy_help"),
    };

    function render(alert, detailsModal, options) {
        const incidentId = getIncidentId(alert);

        if (!incidentId || !detailsModal || !detailsModal.length) {
            return;
        }

        const section = ensureSection(detailsModal);

        section.data("incident-id", incidentId);
        section.data("on-change", options && options.onChange ? options.onChange : null);

        renderLoading(section);

        loadIncident(incidentId, function (incident) {
            renderIncident(section, incident);
        });
    }

    function getIncidentId(alert) {
        if (!alert) {
            return null;
        }

        return alert.incident_id || alert.group_id || alert.id;
    }

    function loadIncident(incidentId, callback) {
        apiGet("/api/incidents/" + incidentId, function (incident) {
            callback(incident || {});
        });
    }

    function loadPriorities(callback) {
        if (priorityCache.loaded) {
            callback(priorityCache.items);
            return;
        }

        apiGet("/api/incidents/priorities", function (items) {
            priorityCache.loaded = true;
            priorityCache.items = Array.isArray(items) ? items : [];
            callback(priorityCache.items);
        });
    }

    function renderIncident(section, incident) {
        const incidentId = incident.incident_id || incident.id || section.data("incident-id");

        section.data("incident", incident);
        section.data("incident-id", incidentId);

        renderPriority(section, incident);
        renderResponders(section, incident);
        renderStakeholders(section, incident);
        bindSectionActions(section, incident);
    }

    function refreshIncident(section) {
        const incidentId = section.data("incident-id");

        if (!incidentId) {
            return;
        }

        loadIncident(incidentId, function (incident) {
            renderIncident(section, incident);
            runChangeCallback(section);
        });
    }

    function runChangeCallback(section) {
        const callback = section.data("on-change");

        if (typeof callback === "function") {
            callback();
        }
    }

    function canWriteIncident(incident) {
        const permissions = incident && incident.permissions ? incident.permissions : {};

        return Boolean(
            permissions.write ||
            permissions.can_write ||
            permissions.manage ||
            permissions.can_manage
        );
    }

    function getIncidentTeamId(incident) {
        if (!incident) {
            return null;
        }

        return incident.team_id || (incident.team && incident.team.id) || null;
    }

    function ensureSection(detailsModal) {
        let section = detailsModal.find(".incident-management-section");

        if (section.length) {
            return section;
        }

        section = $("<section>")
            .addClass("details-section incident-management-section")
            .append(renderSectionHeader())
            .append(renderSectionGrid());

        const commentsSection = detailsModal.find(".alert-comments-section");

        if (commentsSection.length) {
            section.insertBefore(commentsSection);
            return section;
        }

        const modalBody = detailsModal.find(".app-modal-body, .modal-body").first();

        if (modalBody.length) {
            modalBody.append(section);
        }

        return section;
    }

    function renderSectionHeader() {
        return $("<div>")
            .addClass("details-section-header")
            .append(
                $("<div>")
                    .append($("<h3>").text(i18n.t("alert_details.incident_management.title")))
                    .append(
                        $("<p>")
                            .addClass("details-section-subtitle")
                            .text(i18n.t("alert_details.incident_management.help"))
                    )
            );
    }

    function renderSectionGrid() {
        return $("<div>")
            .addClass("details-grid incident-management-grid")
            .append(renderPriorityCard())
            .append(renderRespondersCard())
            .append(renderStakeholdersCard());
    }

    function renderPriorityCard() {
        return $("<div>")
            .addClass("details-card incident-priority-card")
            .append(
                $("<div>")
                    .addClass("details-card-header")
                    .append(
                        $("<div>")
                            .append($("<h4>").text(i18n.t("alert_details.form.priority")))
                            .append(
                                $("<p>")
                                    .addClass("details-muted incident-priority-current")
                            )
                    )
            )
            .append($("<div>").addClass("incident-priority-control"));
    }

    function renderRespondersCard() {
        return $("<div>")
            .addClass("details-card incident-responders-card")
            .append(
                $("<div>")
                    .addClass("details-card-header")
                    .append(
                        $("<div>")
                            .append($("<h4>").text(i18n.t("alert_details.responders.title")))
                            .append(
                                $("<p>")
                                    .addClass("details-muted")
                                    .text(i18n.t("alert_details.responders.help"))
                            )
                    )
                    .append(
                        $("<button>")
                            .attr("type", "button")
                            .addClass("btn btn-secondary btn-sm incident-add-responder")
                            .text(i18n.t("alert_details.responder.add"))
                    )
            )
            .append($("<div>").addClass("incident-responders-list"));
    }

    function renderStakeholdersCard() {
        return $("<div>")
            .addClass("details-card incident-stakeholders-card")
            .append(
                $("<div>")
                    .addClass("details-card-header")
                    .append(
                        $("<div>")
                            .append($("<h4>").text(i18n.t("alert_details.stakeholders.title")))
                            .append(
                                $("<p>")
                                    .addClass("details-muted")
                                    .text(i18n.t("alert_details.stakeholders.help"))
                            )
                    )
                    .append(
                        $("<button>")
                            .attr("type", "button")
                            .addClass("btn btn-secondary btn-sm incident-add-stakeholder")
                            .text(i18n.t("alert_details.stakeholder.add"))
                    )
            )
            .append($("<div>").addClass("incident-stakeholders-list"));
    }

    function renderLoading(section) {
        section.find(".incident-priority-current").text(i18n.t("alert_details.loading"));
        section.find(".incident-priority-control").empty().append(renderEmpty(i18n.t("alert_details.loading.priority")));
        section.find(".incident-responders-list").empty().append(renderEmpty(i18n.t("alert_details.loading.responders")));
        section.find(".incident-stakeholders-list").empty().append(renderEmpty(i18n.t("alert_details.loading.stakeholders")));
    }

    function renderPriority(section, incident) {
        const priority = normalizePriority(incident.priority);
        const canWrite = canWriteIncident(incident);
        const container = section.find(".incident-priority-control");

        container.empty().append(renderEmpty(i18n.t("alert_details.loading.priority")));

        loadPriorities(function (priorities) {
            const configuredPriority = priorities.find(function (item) {
                return item.slug === priority.slug;
            });
            const priorityName = configuredPriority && configuredPriority.name
                ? configuredPriority.name
                : priority.name;
            const modeLabel = priority.setManually ? i18n.t("alert_details.priority.manual_override") : i18n.t("alert_details.priority.automatic");

            section.find(".incident-priority-current").text(
                i18n.t("alert_details.priority.current", {value: priorityName + " (" + priority.slug.toUpperCase() + ")"})
            );

            const controls = $("<div>").addClass("incident-priority-controls");
            const mode = $("<div>").addClass("incident-priority-mode");

            container.empty();

            if (canWrite) {
                controls.append(renderPrioritySelect(priorities, priority.slug));
            } else {
                controls.append(renderBadge(priority.slug.toUpperCase()));
            }

            mode.append(
                $("<span>")
                    .addClass("pill " + (priority.setManually ? "badge-warning" : "badge-muted"))
                    .text(modeLabel)
            );

            if (canWrite && priority.setManually) {
                mode.append(
                    $("<button>")
                        .attr("type", "button")
                        .addClass("btn btn-ghost btn-sm incident-priority-reset")
                        .text(i18n.t("alert_details.priority.reset_auto"))
                );
            }

            controls.append(mode);
            container.append(controls);
        });
    }

    function normalizePriority(priority) {
        const slug = priority && (priority.slug || priority.priority_slug)
            ? priority.slug || priority.priority_slug
            : "p3";

        return {
            slug: slug,
            name: priority && priority.name ? priority.name : slug.toUpperCase(),
            setManually: Boolean(priority && priority.set_manually),
            setById: priority ? priority.set_by_id : null,
            setAt: priority ? priority.set_at : null,
        };
    }

    function renderPrioritySelect(priorities, currentSlug) {
        const select = $("<select>")
            .addClass("input incident-priority-select")
            .attr("aria-label", i18n.t("alert_details.priority.incident_aria"));

        priorities.forEach(function (priority) {
            $("<option>")
                .val(priority.slug)
                .text(priority.slug.toUpperCase() + " — " + priority.name)
                .prop("selected", priority.slug === currentSlug)
                .appendTo(select);
        });

        return select;
    }

    function renderResponders(section, incident) {
        const container = section.find(".incident-responders-list");
        const responders = Array.isArray(incident.responders) ? incident.responders : [];

        container.empty();

        if (!responders.length) {
            container.append(renderEmpty(i18n.t("alert_details.responders.empty")));
            return;
        }

        responders.forEach(function (responder) {
            container.append(renderResponderItem(responder, incident));
        });
    }

    function renderResponderItem(responder, incident) {
        const canWrite = canWriteIncident(incident);
        const item = $("<div>").addClass("details-list-item incident-responder-item");

        const row = $("<div>").addClass("details-list-row").appendTo(item);

        $("<div>")
            .addClass("details-list-title")
            .text(responderTitle(responder))
            .appendTo(row);

        row.append(renderResponderStatusBadge(responder.status));

        const actions = renderResponderActions(responder, incident, canWrite);
        if (actions.children().length) {
            row.append(actions);
        }

        item.append(
            $("<div>")
                .addClass("details-list-meta")
                .text(responderMeta(responder))
        );

        item.append(renderOptionalText(responder.message));

        const responseText = responderResponseText(responder);
        if (responseText) {
            item.append(
                $("<div>")
                    .addClass("details-list-text")
                    .text(responseText)
            );
        }

        const warning = responderNotificationWarning(responder);
        if (warning) {
            item.append(
                $("<div>")
                    .addClass("alert alert-warning incident-responder-warning")
                    .text(warning)
            );
        }

        return item;
    }

    function responderTitle(responder) {
        if (responder.target && responder.target.label) {
            return responder.target.label;
        }

        if (responder.target && responder.target.user) {
            return displayObjectName(responder.target.user, i18n.t("alert_details.target.user"));
        }

        if (responder.target && responder.target.team) {
            return displayObjectName(responder.target.team, i18n.t("alert_details.target.team"));
        }

        if (responder.target && responder.target.rotation) {
            return displayObjectName(responder.target.rotation, i18n.t("alert_details.target.rotation"));
        }

        if (responder.target && responder.target.escalation_policy) {
            return displayObjectName(
                responder.target.escalation_policy,
                i18n.t("alert_details.target.escalation_policy")
            );
        }

        if (responder.target_user) {
            return displayObjectName(responder.target_user, i18n.t("alert_details.target.user"));
        }

        if (responder.target_team) {
            return displayObjectName(responder.target_team, i18n.t("alert_details.target.team"));
        }

        if (responder.target_rotation) {
            return displayObjectName(responder.target_rotation, i18n.t("alert_details.target.rotation"));
        }

        if (responder.target_escalation_policy) {
            return displayObjectName(
                responder.target_escalation_policy,
                i18n.t("alert_details.target.escalation_policy")
            );
        }

        if (responder.target_user_id) {
            return i18n.t("alert_details.entity.user_number", {id: responder.target_user_id});
        }

        if (responder.target_team_id) {
            return i18n.t("alert_details.entity.team_number", {id: responder.target_team_id});
        }

        if (responder.target_rotation_id) {
            return i18n.t("alert_details.entity.rotation_number", {id: responder.target_rotation_id});
        }

        if (responder.target_escalation_policy_id) {
            return i18n.t("alert_details.entity.policy_number", {id: responder.target_escalation_policy_id});
        }

        return i18n.t("alert_details.responder.title");
    }

    function renderResponderStatusBadge(status) {
        const value = String(status || "").toLowerCase();
        const labels = {
            requested: i18n.t("alert_details.responder.requested"),
            accepted: i18n.t("alert_details.responder.accepted"),
            declined: i18n.t("alert_details.responder.declined"),
            expired: i18n.t("alert_details.responder.expired"),
            resolved: i18n.t("alert_details.responder.resolved"),
        };

        return $("<span>")
            .addClass("pill")
            .addClass(responderStatusBadgeClass(value))
            .text(labels[value] || status || "-");
    }


    function responderStatusBadgeClass(status) {
        if (status === "requested") {
            return "badge-muted";
        }

        if (status === "accepted") {
            return "badge-success";
        }

        if (status === "declined") {
            return "badge-warning";
        }

        if (status === "expired") {
            return "badge-muted";
        }

        if (status === "resolved") {
            return "badge-success";
        }

        return "badge-muted";
    }


    function renderResponderActions(responder, incident, canWrite) {
        const actions = $("<div>").addClass("details-list-actions");
        const status = String(responder.status || "").toLowerCase();

        if (incidentIsResolved(incident)) {
            return actions;
        }

        if (status === "requested") {
            actions
                .append(
                    $("<button>")
                        .attr("type", "button")
                        .addClass("btn btn-success btn-sm incident-responder-action")
                        .attr("data-responder-id", responder.id)
                        .attr("data-status", "accepted")
                        .text(i18n.t("alert_details.actions.accept"))
                )
                .append(
                    $("<button>")
                        .attr("type", "button")
                        .addClass("btn btn-secondary btn-sm incident-responder-action")
                        .attr("data-responder-id", responder.id)
                        .attr("data-status", "declined")
                        .text(i18n.t("alert_details.actions.decline"))
                );

            return actions;
        }

        if (status === "accepted" && canWrite) {
            actions.append(
                $("<button>")
                    .attr("type", "button")
                    .addClass("btn btn-secondary btn-sm incident-responder-action")
                    .attr("data-responder-id", responder.id)
                    .attr("data-status", "resolved")
                    .text(i18n.t("alert_details.actions.resolve"))
            );
        }

        return actions;
    }


    function incidentIsResolved(incident) {
        return String((incident && incident.status) || "").toLowerCase() === "resolved";
    }


    function responderResponseText(responder) {
        const status = String(responder.status || "").toLowerCase();

        if (!responder.response_message) {
            return "";
        }

        if (status === "declined") {
            return i18n.t("alert_details.responder.decline_reason") + responder.response_message;
        }

        if (status === "resolved") {
            return i18n.t("alert_details.responder.resolution_note") + responder.response_message;
        }

        return i18n.t("alert_details.responder.response") + responder.response_message;
    }


    function responderNotificationWarning(responder) {
        const status = String(responder.notification_status || "").toLowerCase();

        if (status !== "failed") {
            return "";
        }

        return responder.notification_error
            ? i18n.t("alert_details.responder.notification_failed_prefix") + responder.notification_error
            : i18n.t("alert_details.responder.notification_failed");
    }

    function responderMeta(responder) {
        return [
            responder.target_type,
            responder.status,
            formatIncidentDate(responder.requested_at),
        ].filter(Boolean).join(" · ");
    }

    function renderStakeholders(section, incident) {
        const container = section.find(".incident-stakeholders-list");
        const stakeholders = Array.isArray(incident.stakeholders) ? incident.stakeholders : [];
        const canWrite = canWriteIncident(incident);

        container.empty();

        if (!stakeholders.length) {
            container.append(renderEmpty(i18n.t("alert_details.stakeholders.empty")));
            return;
        }

        stakeholders.forEach(function (stakeholder) {
            container.append(renderStakeholderItem(stakeholder, canWrite));
        });
    }

    function renderStakeholderItem(stakeholder, canWrite) {
        const item = $("<div>").addClass("details-list-item incident-stakeholder-item");
        const row = $("<div>").addClass("details-list-row").appendTo(item);

        $("<div>")
            .addClass("details-list-title")
            .text(stakeholderTitle(stakeholder))
            .appendTo(row);

        if (canWrite) {
            $("<button>")
                .attr("type", "button")
                .addClass("btn btn-ghost btn-sm incident-remove-stakeholder")
                .attr("data-stakeholder-id", stakeholder.id)
                .text(i18n.t("alert_details.actions.remove"))
                .appendTo(row);
        }

        $("<div>")
            .addClass("details-list-meta")
            .text(stakeholderMeta(stakeholder))
            .appendTo(item);

        return item;
    }

    function stakeholderTitle(stakeholder) {
        if (stakeholder.display_name) {
            return stakeholder.display_name;
        }

        if (stakeholder.email) {
            return stakeholder.email;
        }

        if (stakeholder.user) {
            return displayObjectName(stakeholder.user, i18n.t("alert_details.target.user"));
        }

        return i18n.t("alert_details.stakeholder.title");
    }

    function stakeholderMeta(stakeholder) {
        return [
            stakeholder.role,
            stakeholder.source,
            stakeholder.email,
        ].filter(Boolean).join(" · ") || "stakeholder";
    }

    function bindSectionActions(section, incident) {
        const canWrite = canWriteIncident(incident);

        section
            .find(".incident-add-responder")
            .toggle(canWrite)
            .off("click.incidentManagement")
            .on("click.incidentManagement", function () {
                openResponderModal(section);
            });

        section
            .find(".incident-add-stakeholder")
            .toggle(canWrite)
            .off("click.incidentManagement")
            .on("click.incidentManagement", function () {
                openStakeholderModal(section);
            });

        section
            .off("change.incidentManagement", ".incident-priority-select")
            .on("change.incidentManagement", ".incident-priority-select", function () {
                updatePriority(section, $(this).val());
            });

        section
            .off("click.incidentManagement", ".incident-priority-reset")
            .on("click.incidentManagement", ".incident-priority-reset", function () {
                resetPriority(section);
            });

        section
            .find(".incident-remove-stakeholder")
            .off("click.incidentManagement")
            .on("click.incidentManagement", function () {
                confirmStakeholderRemoval(section, $(this).data("stakeholder-id"));
            });
        section
            .find(".incident-responder-action")
            .off("click.incidentManagement")
            .on("click.incidentManagement", function () {
                updateResponderStatus(
                    section,
                    $(this).data("responder-id"),
                    $(this).data("status")
                );
            });
    }

    function updatePriority(section, priority) {
        const incidentId = section.data("incident-id");

        apiPut(
            "/api/incidents/" + incidentId + "/priority",
            {priority: priority},
            function () {
                refreshIncident(section);
            }
        );
    }
    function resetPriority(section) {
        const incidentId = section.data("incident-id");

        if (!incidentId) {
            return;
        }

        showAppConfirm({
            type: "warning",
            title: i18n.t("alert_details.priority.reset_title"),
            message: i18n.t("alert_details.priority.reset_message"),
            confirmText: i18n.t("alert_details.priority.reset_auto"),
            confirmClass: "btn-primary",
        }).done(function () {
            apiDelete("/api/incidents/" + incidentId + "/priority", function () {
                refreshIncident(section);
            });
        });
    }

    function confirmStakeholderRemoval(section, stakeholderId) {
        showAppConfirm({
            type: "warning",
            title: i18n.t("alert_details.stakeholder.remove_title"),
            message: i18n.t("alert_details.stakeholder.remove_message"),
            confirmText: i18n.t("alert_details.actions.remove"),
            confirmClass: "btn-danger",
        }).done(function () {
            apiDelete(
                "/api/incidents/" + section.data("incident-id") + "/stakeholders/" + stakeholderId,
                function () {
                    refreshIncident(section);
                }
            );
        });
    }

    function updateResponderStatus(section, responderId, status) {
        const incidentId = section.data("incident-id");

        if (!incidentId || !responderId || !status) {
            return;
        }

        const runUpdate = function () {
            apiPut(
                "/api/incidents/" + incidentId + "/responders/" + responderId,
                {
                    status: status,
                },
                function () {
                    refreshIncident(section);
                }
            );
        };

        if (status === "declined") {
            showAppConfirm({
                type: "warning",
                title: i18n.t("alert_details.responder.decline_title"),
                message: i18n.t("alert_details.responder.decline_message"),
                confirmText: i18n.t("alert_details.actions.decline"),
                confirmClass: "btn-warning",
            }).done(runUpdate);
            return;
        }

        if (status === "resolved") {
            showAppConfirm({
                type: "info",
                title: i18n.t("alert_details.responder.resolve_title"),
                message: i18n.t("alert_details.responder.resolve_message"),
                confirmText: i18n.t("alert_details.actions.resolve"),
                confirmClass: "btn-secondary",
            }).done(runUpdate);
            return;
        }

        runUpdate();
    }

    function openResponderModal(section) {
        const modal = $("#incident-responder-modal");

        if (!modal.length) {
            showMissingModalError("incident-responder-modal");
            return;
        }

        resetResponderForm(modal);
        modal.data("section", section);

        openAppModal(modal);

        loadResponderTargetOptions(modal);
    }

    function resetResponderForm(modal) {
        modal.find("#incident-responder-target-type").val("user");
        modal.find("#incident-responder-target-select").empty().append(
            $("<option>").val("").text(i18n.t("alert_details.loading.users"))
        );
        modal.find("#incident-responder-message").val(i18n.t("alert_details.responder.default_message"));
        modal.find("#incident-responder-expires").val("");

        clearFormError(modal);
        updateResponderTargetUi(modal);
    }

    function updateResponderTargetUi(modal) {
        const targetType = String(modal.find("#incident-responder-target-type").val() || "user");

        modal
            .find("#incident-responder-target-select-label")
            .text(responderTargetLabels[targetType] || i18n.t("alert_details.target.generic"));

        modal
            .find("#incident-responder-target-help")
            .text(responderTargetHelp[targetType] || "");
    }

    function loadResponderTargetOptions(modal) {
        const section = modal.data("section");
        const incident = section ? section.data("incident") || {} : {};
        const targetType = String(modal.find("#incident-responder-target-type").val() || "user");

        updateResponderTargetUi(modal);
        setTargetSelectLoading(modal, targetType);

        getResponderOptions(targetType, incident, function (items) {
            fillTargetSelect(
                modal.find("#incident-responder-target-select"),
                items,
                responderTargetPlaceholders[targetType] || i18n.t("alert_details.target.select_generic")
            );
        });
    }

    function getResponderOptions(targetType, incident, callback) {
        const teamId = getIncidentTeamId(incident);

        if (targetType === "user") {
            loadTeamUsers(teamId, callback);
            return;
        }

        if (targetType === "team") {
            loadTeams(callback);
            return;
        }

        if (targetType === "rotation") {
            loadRotations(callback);
            return;
        }

        if (targetType === "escalation_policy") {
            loadEscalationPolicies(callback);
            return;
        }

        callback([]);
    }

    function setTargetSelectLoading(modal, targetType) {
        const label = responderTargetLabels[targetType] || "targets";

        modal.find("#incident-responder-target-select")
            .empty()
            .append($("<option>").val("").text(i18n.t("alert_details.target.loading", {target: label.toLowerCase()})));
    }

    function fillTargetSelect(select, items, placeholder) {
        select.empty();
        select.append($("<option>").val("").text(placeholder));

        items.forEach(function (item) {
            $("<option>")
                .val(item.id)
                .text(item.label)
                .appendTo(select);
        });

        if (!items.length) {
            select.append($("<option>").val("").text(i18n.t("alert_details.target.none")));
        }
    }

    function loadTeamUsers(teamId, callback) {
        if (!teamId) {
            callback([]);
            return;
        }

        loadOptions(
            "team-users:" + teamId,
            "/api/teams/" + teamId + "/users",
            function (items) {
                return items
                    .filter(function (item) {
                        return item.active !== false;
                    })
                    .map(function (item) {
                        return {
                            id: item.user_id,
                            label: userOptionLabel(item),
                        };
                    });
            },
            callback
        );
    }

    function loadTeams(callback) {
        loadOptions(
            "teams",
            "/api/teams",
            function (items) {
                return items
                    .filter(function (item) {
                        return item.active !== false;
                    })
                    .map(function (item) {
                        return {
                            id: item.id,
                            label: teamOptionLabel(item),
                        };
                    });
            },
            callback
        );
    }

    function loadRotations(callback) {
        loadOptions(
            "rotations",
            "/api/rotations",
            function (items) {
                return normalizeApiItems(items)
                    .filter(function (item) {
                        return item.enabled !== false && item.active !== false;
                    })
                    .map(function (item) {
                        return {
                            id: item.id,
                            label: rotationOptionLabel(item),
                        };
                    });
            },
            callback
        );
    }


    function loadEscalationPolicies(callback) {
        loadOptions(
            "escalation-policies",
            "/api/escalation-policies",
            function (items) {
                return normalizeApiItems(items)
                    .filter(function (item) {
                        return item.enabled !== false && item.active !== false;
                    })
                    .map(function (item) {
                        return {
                            id: item.id,
                            label: escalationPolicyOptionLabel(item),
                        };
                    });
            },
            callback
        );
    }

    function loadUsers(callback) {
        loadOptions(
            "users",
            "/api/users",
            function (items) {
                return items
                    .filter(function (item) {
                        return item.active !== false;
                    })
                    .map(function (item) {
                        return {
                            id: item.id,
                            label: userOptionLabel(item),
                        };
                    });
            },
            callback
        );
    }

    function loadOptions(cacheKey, url, normalize, callback) {
        if (optionCache[cacheKey]) {
            callback(optionCache[cacheKey]);
            return;
        }

        apiGet(url, function (payload) {
            const normalized = normalize(payload);

            optionCache[cacheKey] = normalized;
            callback(normalized);
        });
    }

    function submitResponderModal(modal) {
        const section = modal.data("section");
        const incidentId = section ? section.data("incident-id") : null;
        const payload = buildResponderPayload(modal);

        if (!incidentId || !payload) {
            return;
        }

        apiPost(
            "/api/incidents/" + incidentId + "/responders",
            payload,
            function () {
                closeAppModal(modal);
                refreshIncident(section);
            }
        );
    }

    function buildResponderPayload(modal) {
        const targetType = String(modal.find("#incident-responder-target-type").val() || "");
        const targetField = responderTargetFields[targetType];
        const targetId = parsePositiveInt(modal.find("#incident-responder-target-select").val());
        const expiresAfter = parsePositiveInt(modal.find("#incident-responder-expires").val());

        clearFormError(modal);

        if (!targetField) {
            showFormError(modal, i18n.t("alert_details.target.invalid"));
            return null;
        }

        if (!targetId) {
            showFormError(modal, i18n.t("alert_details.target.required"));
            return null;
        }

        const payload = {
            target_type: targetType,
            message: getInputValue(modal, "#incident-responder-message"),
        };

        payload[targetField] = targetId;

        if (expiresAfter) {
            payload.expires_after_minutes = expiresAfter;
        }

        return payload;
    }

    function openStakeholderModal(section) {
        const modal = $("#incident-stakeholder-modal");

        if (!modal.length) {
            showMissingModalError("incident-stakeholder-modal");
            return;
        }

        resetStakeholderForm(modal);
        modal.data("section", section);

        openAppModal(modal);

        loadStakeholderUsers(modal);
    }

    function resetStakeholderForm(modal) {
        modal.find("#incident-stakeholder-user-select").empty().append(
            $("<option>").val("").text(i18n.t("alert_details.loading.users"))
        );
        modal.find("#incident-stakeholder-email").val("");
        modal.find("#incident-stakeholder-display-name").val("");
        modal.find("#incident-stakeholder-role").val("stakeholder");

        modal.find("#incident-stakeholder-notify-created").prop("checked", true);
        modal.find("#incident-stakeholder-notify-priority").prop("checked", true);
        modal.find("#incident-stakeholder-notify-status").prop("checked", true);
        modal.find("#incident-stakeholder-notify-resolved").prop("checked", true);

        clearFormError(modal);
    }

    function loadStakeholderUsers(modal) {
        loadUsers(function (items) {
            const select = modal.find("#incident-stakeholder-user-select");

            select.empty();
            select.append($("<option>").val("").text(i18n.t("alert_details.stakeholder.no_existing_user")));

            items.forEach(function (item) {
                $("<option>")
                    .val(item.id)
                    .text(item.label)
                    .appendTo(select);
            });
        });
    }

    function submitStakeholderModal(modal) {
        const section = modal.data("section");
        const incidentId = section ? section.data("incident-id") : null;
        const payload = buildStakeholderPayload(modal);

        if (!incidentId || !payload) {
            return;
        }

        apiPost(
            "/api/incidents/" + incidentId + "/stakeholders",
            payload,
            function () {
                closeAppModal(modal);
                refreshIncident(section);
            }
        );
    }

    function buildStakeholderPayload(modal) {
        const email = getInputValue(modal, "#incident-stakeholder-email");
        const userId = parsePositiveInt(modal.find("#incident-stakeholder-user-select").val());

        clearFormError(modal);

        if (!email && !userId) {
            showFormError(modal, i18n.t("alert_details.stakeholder.required"));
            return null;
        }

        return {
            email: email || null,
            user_id: userId || null,
            display_name: getInputValue(modal, "#incident-stakeholder-display-name") || null,
            role: modal.find("#incident-stakeholder-role").val() || "stakeholder",
            notify_on_created: modal.find("#incident-stakeholder-notify-created").is(":checked"),
            notify_on_priority_change: modal.find("#incident-stakeholder-notify-priority").is(":checked"),
            notify_on_status_change: modal.find("#incident-stakeholder-notify-status").is(":checked"),
            notify_on_resolved: modal.find("#incident-stakeholder-notify-resolved").is(":checked"),
        };
    }

    function showFormError(modal, message) {
        modal
            .find(".alert-danger")
            .text(message)
            .removeClass("is-hidden");
    }

    function clearFormError(modal) {
        modal
            .find(".alert-danger")
            .text("")
            .addClass("is-hidden");
    }

    function showMissingModalError(modalId) {
        if (typeof showAppDialog === "function") {
            showAppDialog({
                type: "error",
                title: i18n.t("alert_details.modal.missing_title"),
                message: i18n.t("alert_details.modal.missing", {id: modalId}),
            });
        }
    }

    function bindStaticModalActions() {
        $(document)
            .off("change.incidentManagement", "#incident-responder-target-type")
            .on("change.incidentManagement", "#incident-responder-target-type", function () {
                loadResponderTargetOptions($("#incident-responder-modal"));
            });

        $(document)
            .off("click.incidentManagement", "#save-incident-responder")
            .on("click.incidentManagement", "#save-incident-responder", function () {
                submitResponderModal($("#incident-responder-modal"));
            });

        $(document)
            .off("click.incidentManagement", "#save-incident-stakeholder")
            .on("click.incidentManagement", "#save-incident-stakeholder", function () {
                submitStakeholderModal($("#incident-stakeholder-modal"));
            });
    }

    function renderEmpty(text) {
        return $("<div>")
            .addClass("details-empty")
            .text(text);
    }

    function renderBadge(text) {
        return $("<span>")
            .addClass("pill badge-muted")
            .text(text);
    }

    function renderOptionalText(text) {
        if (!text) {
            return $();
        }

        return $("<div>")
            .addClass("details-list-text")
            .text(text);
    }

    function displayObjectName(value, fallback) {
        if (!value) {
            return fallback;
        }

        return value.name || value.display_name || value.username || value.slug || value.email || fallback;
    }

    function userOptionLabel(item) {
        const displayName = item.display_name || item.name;
        const username = item.username;
        const email = item.email;

        if (displayName && username) {
            return displayName + " (" + username + ")";
        }

        if (displayName) {
            return displayName;
        }

        if (username && email) {
            return username + " · " + email;
        }

        return username || email || (i18n.t("alert_details.entity.user_number", {id: item.user_id || item.id}));
    }

    function teamOptionLabel(item) {
        if (item.name && item.slug) {
            return item.name + " (" + item.slug + ")";
        }

        return item.name || item.slug || (i18n.t("alert_details.entity.team_number", {id: item.id}));
    }

    function getInputValue(scope, selector) {
        return String(scope.find(selector).val() || "").trim();
    }

    function normalizeApiItems(payload) {
        if (Array.isArray(payload)) {
            return payload;
        }

        if (payload && Array.isArray(payload.items)) {
            return payload.items;
        }

        if (payload && Array.isArray(payload.data)) {
            return payload.data;
        }

        return [];
    }

    function rotationOptionLabel(item) {
        const name = item.name || (i18n.t("alert_details.entity.rotation_number", {id: item.id}));
        const teamName = item.team_name || item.team_slug || getNestedName(item.team);

        if (teamName) {
            return name + " · " + teamName;
        }

        return name;
    }

    function escalationPolicyOptionLabel(item) {
        const name = item.name || (i18n.t("alert_details.entity.policy_number", {id: item.id}));
        const teamName = item.team_name || item.team_slug || getNestedName(item.team);

        if (teamName) {
            return name + " · " + teamName;
        }

        return name;
    }

    function getNestedName(value) {
        if (!value) {
            return "";
        }

        return value.name || value.slug || value.username || value.email || "";
    }

    function parsePositiveInt(value) {
        const parsed = parseInt(value, 10);

        if (!Number.isFinite(parsed) || parsed <= 0) {
            return null;
        }

        return parsed;
    }

    function formatIncidentDate(value) {
        if (!value) {
            return "";
        }

        if (typeof formatDateTimeMinutes === "function") {
            return formatDateTimeMinutes(value);
        }

        return value;
    }

    $(bindStaticModalActions);

    return {
        render: render,
    };
})();
