(function (window, document) {
    "use strict";

    const EXACT_KEYS = {
    "95% critical alerts acknowledged within 15 minutes": "services_full.95_critical_alerts_acknowledged_within_15_minutes",
    "API": "services_full.api",
    "Ack latency": "services_full.ack_latency",
    "Acknowledged": "services_full.acknowledged",
    "Actions": "services_full.actions",
    "Active": "services_full.active",
    "Active and upcoming maintenance that can affect this service.": "services_full.active_and_upcoming_maintenance_that_can_affect_this_service",
    "Actor": "services_full.actor",
    "Add SLI": "services_full.add_sli",
    "Add SLO": "services_full.add_slo",
    "Add default stakeholder": "services_full.add_default_stakeholder",
    "Add stakeholder": "services_full.add_stakeholder",
    "Additional matchers": "services_full.additional_matchers",
    "Additional matchers JSON": "services_full.additional_matchers_json",
    "Affected": "services_full.affected",
    "Affected %": "services_full.affected_9cd42f9d",
    "Affected samples": "services_full.affected_samples",
    "Alert acknowledgement latency": "services_full.alert_acknowledgement_latency",
    "Alert group": "services_full.alert_group",
    "Alert groups": "services_full.alert_groups",
    "Alert groups trend": "services_full.alert_groups_trend",
    "Alert impact": "services_full.alert_impact",
    "Alert resolution latency": "services_full.alert_resolution_latency",
    "Alert volume grouped by service for the selected scope.": "services_full.alert_volume_grouped_by_service_for_the_selected_scope",
    "Alerts": "services_full.alerts",
    "All": "services_full.all",
    "All criticalities": "services_full.all_criticalities",
    "All effective statuses": "services_full.all_effective_statuses",
    "All readiness": "services_full.all_readiness",
    "All reasons": "services_full.all_reasons",
    "All services": "services_full.all_services",
    "All severities": "services_full.all_severities",
    "All statuses": "services_full.all_statuses",
    "Analytics": "services_full.analytics",
    "Analytics by affected system": "services_full.analytics_by_affected_system",
    "Analytics version": "services_full.analytics_version",
    "Analytics window": "services_full.analytics_window",
    "At risk": "services_full.at_risk",
    "Attach response instructions to a service.": "services_full.attach_response_instructions_to_a_service",
    "Average and maximum affected services from persisted impact snapshots.": "services_full.average_and_maximum_affected_services_from_persisted_impact_snap",
    "Avg affected": "services_full.avg_affected",
    "Behavior": "services_full.behavior",
    "Blast radius": "services_full.blast_radius",
    "Breached": "services_full.breached",
    "Breached alert groups": "services_full.breached_alert_groups",
    "Budget": "services_full.budget",
    "Budget used:": "services_full.budget_used",
    "Business": "services_full.business",
    "Business component": "services_full.business_component",
    "Business owner": "services_full.business_owner",
    "Business service": "services_full.business_service",
    "Cache": "services_full.cache",
    "Cancel": "services_full.cancel",
    "Capture snapshot": "services_full.capture_snapshot",
    "Category": "services_full.category",
    "Circle": "services_full.circle",
    "Close": "services_full.close",
    "Cloud PostgreSQL": "services_full.cloud_postgresql",
    "Collapse by prefix": "services_full.collapse_by_prefix",
    "Collapse by team": "services_full.collapse_by_team",
    "Collapse graph sections": "services_full.collapse_graph_sections",
    "Comment added": "services_full.comment_added",
    "Comparison": "services_full.comparison",
    "Connected to selected": "services_full.connected_to_selected",
    "Correlation": "services_full.correlation",
    "Correlation off": "services_full.correlation_off",
    "Correlation uses this dependency to connect related active alert groups. Propagation delay controls how far apart alerts may be and still match.": "services_full.correlation_uses_this_dependency_to_connect_related_active_alert",
    "Counters": "services_full.counters",
    "Create an SLI first, then add an SLO for it.": "services_full.create_an_sli_first_then_add_an_slo_for_it",
    "Create dependency": "services_full.create_dependency",
    "Create link": "services_full.create_link",
    "Create runbook": "services_full.create_runbook",
    "Create service": "services_full.create_service",
    "Critical": "services_full.critical",
    "Critical alert acknowledgement latency": "services_full.critical_alert_acknowledgement_latency",
    "Critical downstream": "services_full.critical_downstream",
    "Critical open": "services_full.critical_open",
    "Criticality": "services_full.criticality",
    "Cron": "services_full.cron",
    "Cross-service and cross-team dependencies.": "services_full.cross_service_and_cross_team_dependencies",
    "Current": "services_full.current",
    "Current availability": "services_full.current_availability",
    "Current compliance": "services_full.current_compliance",
    "Current impact": "services_full.current_impact",
    "Custom": "services_full.custom",
    "Customer success": "services_full.customer_success",
    "Cycle detected": "services_full.cycle_detected",
    "Cycles/depth 0/0": "services_full.cycles_depth_0_0",
    "Dashboard": "services_full.dashboard",
    "Dashboard, logs, docs, repository or another service link.": "services_full.dashboard_logs_docs_repository_or_another_service_link",
    "Dashboards, logs, documentation and repositories.": "services_full.dashboards_logs_documentation_and_repositories",
    "Dashboards, logs, traces, repositories and documentation.": "services_full.dashboards_logs_traces_repositories_and_documentation",
    "Database": "services_full.database",
    "Declare another service this service depends on.": "services_full.declare_another_service_this_service_depends_on",
    "Dedup ratio": "services_full.dedup_ratio",
    "Default escalation policy": "services_full.default_escalation_policy",
    "Default rotation": "services_full.default_rotation",
    "Default stakeholders": "services_full.default_stakeholders",
    "Default stakeholders are copied to new incidents for this service. Existing incidents are not changed.": "services_full.default_stakeholders_are_copied_to_new_incidents_for_this_servic",
    "Defaults": "services_full.defaults",
    "Degraded": "services_full.degraded",
    "Degraded path": "services_full.degraded_path",
    "Delete": "services_full.delete",
    "Delete dependency": "services_full.delete_dependency",
    "Delete link": "services_full.delete_link",
    "Delete runbook": "services_full.delete_runbook",
    "Delete service": "services_full.delete_service",
    "Delete this SLI?": "services_full.delete_this_sli",
    "Delete this SLO?": "services_full.delete_this_slo",
    "Delete this default stakeholder?": "services_full.delete_this_default_stakeholder",
    "Delete this dependency?": "services_full.delete_this_dependency",
    "Delete this link?": "services_full.delete_this_link",
    "Delete this runbook?": "services_full.delete_this_runbook",
    "Delete this service?": "services_full.delete_this_service",
    "Dependencies": "services_full.dependencies",
    "Dependencies of selected": "services_full.dependencies_of_selected",
    "Dependencies view": "services_full.dependencies_view",
    "Dependency": "services_full.dependency",
    "Dependency impact": "services_full.dependency_impact",
    "Dependency service is required.": "services_full.dependency_service_is_required",
    "Dependency strength": "services_full.dependency_strength",
    "Dependency type": "services_full.dependency_type",
    "Dependents of selected": "services_full.dependents_of_selected",
    "Depends on": "services_full.depends_on",
    "Depends on service": "services_full.depends_on_service",
    "Deprecated": "services_full.deprecated",
    "Depth 1": "services_full.depth_1",
    "Depth 2": "services_full.depth_2",
    "Depth 3": "services_full.depth_3",
    "Depth 5": "services_full.depth_5",
    "Depth all": "services_full.depth_all",
    "Depth limited": "services_full.depth_limited",
    "Description": "services_full.description",
    "Development": "services_full.development",
    "Direct": "services_full.direct",
    "Direct downstream": "services_full.direct_downstream",
    "Disabled": "services_full.disabled",
    "Documentation": "services_full.documentation",
    "Downtime": "services_full.downtime",
    "Edit": "services_full.edit",
    "Edit SLI": "services_full.edit_sli",
    "Edit SLO": "services_full.edit_slo",
    "Edit default stakeholder": "services_full.edit_default_stakeholder",
    "Edit dependency": "services_full.edit_dependency",
    "Edit link": "services_full.edit_link",
    "Edit runbook": "services_full.edit_runbook",
    "Edit service": "services_full.edit_service",
    "Effective status": "services_full.effective_status",
    "Effective status, root cause and downstream blast radius.": "services_full.effective_status_root_cause_and_downstream_blast_radius",
    "Enabled": "services_full.enabled",
    "Environment": "services_full.environment",
    "Escalation policy": "services_full.escalation_policy",
    "Event": "services_full.event",
    "Exclude maintenance from availability calculations": "services_full.exclude_maintenance_from_availability_calculations",
    "Executive": "services_full.executive",
    "Experimental": "services_full.experimental",
    "Explanation": "services_full.explanation",
    "External": "services_full.external",
    "Firing": "services_full.firing",
    "Firing grouped alerts": "services_full.firing_grouped_alerts",
    "Firing grouped alerts by day.": "services_full.firing_grouped_alerts_by_day",
    "Firing groups": "services_full.firing_groups",
    "Fit": "services_full.fit",
    "Focus depth": "services_full.focus_depth",
    "Force-directed": "services_full.force_directed",
    "Full graph": "services_full.full_graph",
    "Good alert groups": "services_full.good_alert_groups",
    "Good time": "services_full.good_time",
    "Grafana dashboard": "services_full.grafana_dashboard",
    "Graph": "services_full.graph",
    "Graph view mode": "services_full.graph_view_mode",
    "Grid": "services_full.grid",
    "Grouped alerts by day in the selected window.": "services_full.grouped_alerts_by_day_in_the_selected_window",
    "Grouped open alerts": "services_full.grouped_open_alerts",
    "Hard": "services_full.hard",
    "Hide healthy leaves": "services_full.hide_healthy_leaves",
    "Hierarchy": "services_full.hierarchy",
    "High": "services_full.high",
    "Historical affected services": "services_full.historical_affected_services",
    "Historical impact": "services_full.historical_impact",
    "Historical impact reasons": "services_full.historical_impact_reasons",
    "Historically affected service": "services_full.historically_affected_service",
    "History": "services_full.history",
    "Identity": "services_full.identity",
    "Impact": "services_full.impact",
    "Impact incident count": "services_full.impact_incident_count",
    "Impact incidents": "services_full.impact_incidents",
    "Impact only": "services_full.impact_only",
    "Impact snapshot captured": "services_full.impact_snapshot_captured",
    "Impact v2 explains effective status, primary reason, root causes, paths and downstream blast radius.": "services_full.impact_v2_explains_effective_status_primary_reason_root_causes_p",
    "Important": "services_full.important",
    "Inactive": "services_full.inactive",
    "Incident availability": "services_full.incident_availability",
    "Incident availability and incident count are calculated from impact priorities. Default: P1/P2.": "services_full.incident_availability_and_incident_count_are_calculated_from_imp",
    "Incident count": "services_full.incident_count",
    "Incident count SLO requires Max incidents.": "services_full.incident_count_slo_requires_max_incidents",
    "Incident created": "services_full.incident_created",
    "Incident resolved": "services_full.incident_resolved",
    "Incident-based availability": "services_full.incident_based_availability",
    "Indicators describe what is measured. Objectives define the target for those indicators.": "services_full.indicators_describe_what_is_measured_objectives_define_the_targe",
    "Info": "services_full.info",
    "Informational": "services_full.informational",
    "Infrastructure": "services_full.infrastructure",
    "Kind": "services_full.kind",
    "Label": "services_full.label",
    "Last": "services_full.last",
    "Last 30 days": "services_full.last_30_days",
    "Last 365 days": "services_full.last_365_days",
    "Last 7 days": "services_full.last_7_days",
    "Last 90 days": "services_full.last_90_days",
    "Last affected": "services_full.last_affected",
    "Last status": "services_full.last_status",
    "Latency SLO requires threshold minutes.": "services_full.latency_slo_requires_threshold_minutes",
    "Latest SLO measurements for services in the selected scope.": "services_full.latest_slo_measurements_for_services_in_the_selected_scope",
    "Latest affected": "services_full.latest_affected",
    "Lifecycle": "services_full.lifecycle",
    "Link": "services_full.link",
    "Links": "services_full.links",
    "Load more": "services_full.load_more",
    "Loading SLO health...": "services_full.loading_slo_health",
    "Loading SLO measurements...": "services_full.loading_slo_measurements",
    "Loading...": "services_full.loading",
    "Logs": "services_full.logs",
    "Low": "services_full.low",
    "Maintenance": "services_full.maintenance",
    "Maintenance / Blast": "services_full.maintenance_blast",
    "Maintenance excluded": "services_full.maintenance_excluded",
    "Maintenance windows": "services_full.maintenance_windows",
    "Major outage": "services_full.major_outage",
    "Major outage path": "services_full.major_outage_path",
    "Matcher preset": "services_full.matcher_preset",
    "Matching": "services_full.matching",
    "Max alerts": "services_full.max_alerts",
    "Max incidents": "services_full.max_incidents",
    "Max incidents â¤": "services_full.max_incidents_7c4192bf",
    "Max incidents ≤": "services_full.max_incidents_b48e899b",
    "Max upstream": "services_full.max_upstream",
    "Medium": "services_full.medium",
    "Met": "services_full.met",
    "Metrics": "services_full.metrics",
    "Name": "services_full.name",
    "Network": "services_full.network",
    "New SLI": "services_full.new_sli",
    "New SLO": "services_full.new_slo",
    "New dependency": "services_full.new_dependency",
    "New link": "services_full.new_link",
    "New runbook": "services_full.new_runbook",
    "New service": "services_full.new_service",
    "No": "services_full.no",
    "No SLI/SLO configured for this service.": "services_full.no_sli_slo_configured_for_this_service",
    "No SLIs configured.": "services_full.no_slis_configured",
    "No SLO measurements": "services_full.no_slo_measurements",
    "No SLOs configured.": "services_full.no_slos_configured",
    "No active or upcoming maintenance windows.": "services_full.no_active_or_upcoming_maintenance_windows",
    "No analytics": "services_full.no_analytics",
    "No analytics loaded": "services_full.no_analytics_loaded",
    "No collapse": "services_full.no_collapse",
    "No data": "services_full.no_data",
    "No default policy": "services_full.no_default_policy",
    "No default rotation": "services_full.no_default_rotation",
    "No default stakeholders.": "services_full.no_default_stakeholders",
    "No dependencies": "services_full.no_dependencies",
    "No dependency graph loaded": "services_full.no_dependency_graph_loaded",
    "No description": "services_full.no_description",
    "No downstream services in blast radius.": "services_full.no_downstream_services_in_blast_radius",
    "No historical impact snapshots": "services_full.no_historical_impact_snapshots",
    "No historical impact snapshots. Use Capture snapshot or wait for the scheduler.": "services_full.no_historical_impact_snapshots_use_capture_snapshot_or_wait_for_",
    "No impact data": "services_full.no_impact_data",
    "No impact data loaded": "services_full.no_impact_data_loaded",
    "No impact detected": "services_full.no_impact_detected",
    "No links": "services_full.no_links",
    "No links.": "services_full.no_links_3f8a499b",
    "No notification policy": "services_full.no_notification_policy",
    "No preset": "services_full.no_preset",
    "No preset selected. Only the additional matchers below will be evaluated.": "services_full.no_preset_selected_only_the_additional_matchers_below_will_be_ev",
    "No runbooks": "services_full.no_runbooks",
    "No runbooks.": "services_full.no_runbooks_2a27eaad",
    "No services loaded": "services_full.no_services_loaded",
    "No timeline events.": "services_full.no_timeline_events",
    "Nodes": "services_full.nodes",
    "None": "services_full.none",
    "Not applicable": "services_full.not_applicable",
    "Not evaluated": "services_full.not_evaluated",
    "Not operational": "services_full.not_operational",
    "Not ready": "services_full.not_ready",
    "Notification policy": "services_full.notification_policy",
    "Notifications": "services_full.notifications",
    "Open alert groups": "services_full.open_alert_groups",
    "Open alerts": "services_full.open_alerts",
    "Open groups": "services_full.open_groups",
    "Operational": "services_full.operational",
    "Operational path": "services_full.operational_path",
    "Optional": "services_full.optional",
    "Optional labels matcher for this runbook.": "services_full.optional_labels_matcher_for_this_runbook",
    "Other": "services_full.other",
    "Overrides the team's default priority policy for incidents assigned to this service.": "services_full.overrides_the_team_s_default_priority_policy_for_incidents_assig",
    "Overview": "services_full.overview",
    "Own status": "services_full.own_status",
    "Owner": "services_full.owner",
    "Ownership, identity and classification.": "services_full.ownership_identity_and_classification",
    "Partial outage": "services_full.partial_outage",
    "Partial outage path": "services_full.partial_outage_path",
    "Path": "services_full.path",
    "Peak affected": "services_full.peak_affected",
    "Peak critical": "services_full.peak_critical",
    "Pending alert groups": "services_full.pending_alert_groups",
    "PostgreSQL outage": "services_full.postgresql_outage",
    "Primary reason": "services_full.primary_reason",
    "Priority": "services_full.priority",
    "Priority changed": "services_full.priority_changed",
    "Priority policy": "services_full.priority_policy",
    "Priority scope": "services_full.priority_scope",
    "Production": "services_full.production",
    "Propagation delay, seconds": "services_full.propagation_delay_seconds",
    "Queue": "services_full.queue",
    "Quick actions": "services_full.quick_actions",
    "Raw alert events by day before grouping.": "services_full.raw_alert_events_by_day_before_grouping",
    "Raw alert volume": "services_full.raw_alert_volume",
    "Raw alerts": "services_full.raw_alerts",
    "Readiness": "services_full.readiness",
    "Readiness check could not be evaluated": "services_full.readiness_check_could_not_be_evaluated",
    "Ready": "services_full.ready",
    "Reason": "services_full.reason",
    "Recent alerts": "services_full.recent_alerts",
    "Recent service, readiness and configuration events.": "services_full.recent_service_readiness_and_configuration_events",
    "Reliability": "services_full.reliability",
    "Reload": "services_full.reload",
    "Repository": "services_full.repository",
    "Required": "services_full.required",
    "Reset": "services_full.reset",
    "Resolve latency": "services_full.resolve_latency",
    "Resolved": "services_full.resolved",
    "Response instructions attached to services.": "services_full.response_instructions_attached_to_services",
    "Response instructions for this service.": "services_full.response_instructions_for_this_service",
    "Retired": "services_full.retired",
    "Role": "services_full.role",
    "Runbook": "services_full.runbook",
    "Runbooks": "services_full.runbooks",
    "SLI / SLO": "services_full.sli_slo",
    "SLI / SLO health": "services_full.sli_slo_health",
    "SLI name": "services_full.sli_name",
    "SLI name and slug are required.": "services_full.sli_name_and_slug_are_required",
    "SLI type": "services_full.sli_type",
    "SLI/SLO health, latest measurements and error budget state.": "services_full.sli_slo_health_latest_measurements_and_error_budget_state",
    "SLIs": "services_full.slis",
    "SLO name": "services_full.slo_name",
    "SLO name and SLI are required.": "services_full.slo_name_and_sli_are_required",
    "SLO target percent is required.": "services_full.slo_target_percent_is_required",
    "SLOs": "services_full.slos",
    "Save": "services_full.save",
    "Save SLI": "services_full.save_sli",
    "Save SLO": "services_full.save_slo",
    "Save dependency": "services_full.save_dependency",
    "Save link": "services_full.save_link",
    "Save runbook": "services_full.save_runbook",
    "Save service": "services_full.save_service",
    "Scope": "services_full.scope",
    "Search dependencies...": "services_full.search_dependencies",
    "Search dependency service...": "services_full.search_dependency_service",
    "Search graph...": "services_full.search_graph",
    "Search impacted services, reasons, root causes or paths...": "services_full.search_impacted_services_reasons_root_causes_or_paths",
    "Search links...": "services_full.search_links",
    "Search runbooks...": "services_full.search_runbooks",
    "Search services, SLI or SLO...": "services_full.search_services_sli_or_slo",
    "Search services...": "services_full.search_services",
    "Search source service...": "services_full.search_source_service",
    "Select a service to view details.": "services_full.select_a_service_to_view_details",
    "Select dependency service...": "services_full.select_dependency_service",
    "Select service": "services_full.select_service",
    "Select user": "services_full.select_user",
    "Service": "services_full.service",
    "Service default rotation is disabled or deleted": "services_full.service_default_rotation_is_disabled_or_deleted",
    "Service details": "services_full.service_details",
    "Service escalation policy has no active rules": "services_full.service_escalation_policy_has_no_active_rules",
    "Service escalation policy is disabled or deleted": "services_full.service_escalation_policy_is_disabled_or_deleted",
    "Service has an active default rotation": "services_full.service_has_an_active_default_rotation",
    "Service has an active direct alert route": "services_full.service_has_an_active_direct_alert_route",
    "Service has an active escalation policy": "services_full.service_has_an_active_escalation_policy",
    "Service has an active notification policy": "services_full.service_has_an_active_notification_policy",
    "Service has an active route through a match rule": "services_full.service_has_an_active_route_through_a_match_rule",
    "Service has no active alert route": "services_full.service_has_no_active_alert_route",
    "Service has no default escalation policy": "services_full.service_has_no_default_escalation_policy",
    "Service has no default rotation": "services_full.service_has_no_default_rotation",
    "Service has no notification policy": "services_full.service_has_no_notification_policy",
    "Service impact": "services_full.service_impact",
    "Service impact view": "services_full.service_impact_view",
    "Service is not part of a dependency cycle": "services_full.service_is_not_part_of_a_dependency_cycle",
    "Service is part of a dependency cycle": "services_full.service_is_part_of_a_dependency_cycle",
    "Service is required.": "services_full.service_is_required",
    "Service links": "services_full.service_links",
    "Service notification policy has no active channels": "services_full.service_notification_policy_has_no_active_channels",
    "Service notification policy has no active rules": "services_full.service_notification_policy_has_no_active_rules",
    "Service notification policy is disabled or deleted": "services_full.service_notification_policy_is_disabled_or_deleted",
    "Service status": "services_full.service_status",
    "Service, title, URL and severity.": "services_full.service_title_url_and_severity",
    "Service-level counters for the selected analytics window.": "services_full.service_level_counters_for_the_selected_analytics_window",
    "Services": "services_full.services",
    "Services in scope": "services_full.services_in_scope",
    "Severity": "services_full.severity",
    "Severity scope": "services_full.severity_scope",
    "Shared": "services_full.shared",
    "Show on status page later": "services_full.show_on_status_page_later",
    "Show operational": "services_full.show_operational",
    "Showing": "services_full.showing",
    "Slug": "services_full.slug",
    "Snapshot item counts by primary reason.": "services_full.snapshot_item_counts_by_primary_reason",
    "Snapshots": "services_full.snapshots",
    "Soft": "services_full.soft",
    "Source": "services_full.source",
    "Staging": "services_full.staging",
    "Stakeholder": "services_full.stakeholder",
    "Status": "services_full.status",
    "Status and defaults": "services_full.status_and_defaults",
    "Status changed": "services_full.status_changed",
    "Status changes": "services_full.status_changes",
    "Status message": "services_full.status_message",
    "Status page": "services_full.status_page",
    "Status, rotation, escalation, notification and priority policies.": "services_full.status_rotation_escalation_notification_and_priority_policies",
    "Storage": "services_full.storage",
    "Support": "services_full.support",
    "TZ": "services_full.tz",
    "Table": "services_full.table",
    "Target": "services_full.target",
    "Target status": "services_full.target_status",
    "Target â¥": "services_full.target_1e61501c",
    "Target ≥": "services_full.target_bfd2eaea",
    "Target, %": "services_full.target_453c00c0",
    "Targets and evaluation window": "services_full.targets_and_evaluation_window",
    "Team": "services_full.team",
    "Team default": "services_full.team_default",
    "Team is required.": "services_full.team_is_required",
    "Technical": "services_full.technical",
    "Technical service or system affected by alerts.": "services_full.technical_service_or_system_affected_by_alerts",
    "Testing": "services_full.testing",
    "The preset and additional matchers are combined using AND. Empty {} means no additional conditions.": "services_full.the_preset_and_additional_matchers_are_combined_using_and_empty_",
    "Threshold â¤": "services_full.threshold",
    "Threshold ≤": "services_full.threshold_a1795ecd",
    "Threshold, minutes": "services_full.threshold_minutes",
    "Tier": "services_full.tier",
    "Tier 1": "services_full.tier_1",
    "Tier 1 downstream": "services_full.tier_1_downstream",
    "Tier 2": "services_full.tier_2",
    "Tier 3": "services_full.tier_3",
    "Tier 4": "services_full.tier_4",
    "Time": "services_full.time",
    "Timeline": "services_full.timeline",
    "Title": "services_full.title",
    "Total": "services_full.total",
    "Total SLOs": "services_full.total_slos",
    "Total alert groups": "services_full.total_alert_groups",
    "Total alerts": "services_full.total_alerts",
    "Total downstream": "services_full.total_downstream",
    "Total groups": "services_full.total_groups",
    "Total matching alert groups": "services_full.total_matching_alert_groups",
    "Total window": "services_full.total_window",
    "Traces": "services_full.traces",
    "Track open alerts as pending/breached": "services_full.track_open_alerts_as_pending_breached",
    "Type": "services_full.type",
    "URL": "services_full.url",
    "Unknown": "services_full.unknown",
    "Unknown path": "services_full.unknown_path",
    "Upstream dependency": "services_full.upstream_dependency",
    "Upstream issues": "services_full.upstream_issues",
    "Upstream services this service needs and downstream services that depend on it.": "services_full.upstream_services_this_service_needs_and_downstream_services_tha",
    "Use team default": "services_full.use_team_default",
    "Use this dependency for alert correlation": "services_full.use_this_dependency_for_alert_correlation",
    "Use this owner for new incidents": "services_full.use_this_owner_for_new_incidents",
    "Use {} when the preset alone should determine whether the runbook matches.": "services_full.use_when_the_preset_alone_should_determine_whether_the_runbook_m",
    "Used by": "services_full.used_by",
    "Used when a route is configured to deliver through the service notification policy.": "services_full.used_when_a_route_is_configured_to_deliver_through_the_service_n",
    "User": "services_full.user",
    "User is required.": "services_full.user_is_required",
    "Warning": "services_full.warning",
    "Web": "services_full.web",
    "Wiki": "services_full.wiki",
    "Window": "services_full.window",
    "Window, days": "services_full.window_days",
    "Windows": "services_full.windows",
    "Worker": "services_full.worker",
    "Worst status": "services_full.worst_status",
    "Yes": "services_full.yes",
    "You do not have permission to edit this service.": "services_full.you_do_not_have_permission_to_edit_this_service",
    "You do not have permission to update this service.": "services_full.you_do_not_have_permission_to_update_this_service",
    "all matching alert groups": "services_full.all_matching_alert_groups",
    "correlation off": "services_full.correlation_off_c0b08de1",
    "correlation on": "services_full.correlation_on",
    "cycle detected": "services_full.cycle_detected_e29cd94b",
    "day window": "services_full.day_window",
    "effective status": "services_full.effective_status_dd133723",
    "maintenance excluded": "services_full.maintenance_excluded_80b4b014",
    "major outages": "services_full.major_outages",
    "no snapshots": "services_full.no_snapshots",
    "not operational": "services_full.not_operational_43ac205c",
    "of": "services_full.of",
    "over budget by": "services_full.over_budget_by",
    "selected window": "services_full.selected_window",
    "services": "services_full.services_3e7aaa79",
    "services in impact scope": "services_full.services_in_impact_scope",
    "upstream / downstream": "services_full.upstream_downstream",
    "Â· Team default": "services_full.team_default_129a7b2f"
};
    const ATTRIBUTES = ["placeholder", "title", "aria-label", "data-placeholder"];
    let mutationGuard = false;

    function isServicesContext() {
        return window.location.pathname === "/services"
            || !!document.querySelector(".services-page");
    }

    function normalize(value) {
        return String(value == null ? "" : value).replace(/\s+/g, " ").trim();
    }

    function exactTranslation(value) {
        const normalized = normalize(value);
        const key = EXACT_KEYS[normalized];

        if (!key || !window.i18n) {
            return null;
        }

        return i18n.t(key, {}, normalized);
    }

    function translatePattern(value) {
        const normalized = normalize(value);
        let match;

        const numbered = [
            [/^Service #(\d+)$/i, "Сервис №$1"],
            [/^Runbook #(\d+)$/i, "Инструкция №$1"],
            [/^Link #(\d+)$/i, "Ссылка №$1"],
            [/^Window #(\d+)$/i, "Окно №$1"],
            [/^User #(\d+)$/i, "Пользователь №$1"],
            [/^SLI #(\d+)$/i, "SLI №$1"],
            [/^SLO #(\d+)$/i, "SLO №$1"],
            [/^Edit SLI #(\d+)$/i, "Изменить SLI №$1"],
            [/^Edit SLO #(\d+)$/i, "Изменить SLO №$1"],
        ];

        const numberedGerman = [
            [/^Service #(\d+)$/i, "Service Nr. $1"],
            [/^Runbook #(\d+)$/i, "Runbook Nr. $1"],
            [/^Link #(\d+)$/i, "Link Nr. $1"],
            [/^Window #(\d+)$/i, "Fenster Nr. $1"],
            [/^User #(\d+)$/i, "Benutzer Nr. $1"],
            [/^SLI #(\d+)$/i, "SLI Nr. $1"],
            [/^SLO #(\d+)$/i, "SLO Nr. $1"],
            [/^Edit SLI #(\d+)$/i, "SLI Nr. $1 bearbeiten"],
            [/^Edit SLO #(\d+)$/i, "SLO Nr. $1 bearbeiten"],
        ];

        const numberedFrench = [
            [/^Service #(\d+)$/i, "Service n° $1"],
            [/^Runbook #(\d+)$/i, "Procédure n° $1"],
            [/^Link #(\d+)$/i, "Lien n° $1"],
            [/^Window #(\d+)$/i, "Fenêtre n° $1"],
            [/^User #(\d+)$/i, "Utilisateur n° $1"],
            [/^SLI #(\d+)$/i, "SLI n° $1"],
            [/^SLO #(\d+)$/i, "SLO n° $1"],
            [/^Edit SLI #(\d+)$/i, "Modifier le SLI n° $1"],
            [/^Edit SLO #(\d+)$/i, "Modifier le SLO n° $1"],
        ];

        if (window.i18n && i18n.locale === "ru") {
            for (const pair of numbered) {
                if (pair[0].test(normalized)) {
                    return normalized.replace(pair[0], pair[1]);
                }
            }

            match = normalized.match(/^Correlation (\d+)s$/i);
            if (match) {
                return "Корреляция: " + match[1] + " с";
            }

            match = normalized.match(/^(\d+) day window$/i);
            if (match) {
                return "Период: " + match[1] + " дней";
            }

            match = normalized.match(/^Loading service details for\s+(.+?)(?:\.\.\.)?$/i);
            if (match) {
                return "Загрузка данных сервиса «" + match[1] + "»...";
            }

            match = normalized.match(/^(\d+) more path\(s\)$/i);
            if (match) {
                return "Ещё путей: " + match[1];
            }

            match = normalized.match(/^(\d+) more downstream path\(s\)$/i);
            if (match) {
                return "Ещё нижестоящих путей: " + match[1];
            }

            match = normalized.match(/^Budget used:\s*(.+)$/i);
            if (match) {
                return "Использовано бюджета: " + match[1];
            }

            match = normalized.match(/^Delete SLI [“\"]?(.+?)[”\"]?\? SLOs attached to it will be deleted by the database\.$/i);
            if (match) {
                return "Удалить SLI «" + match[1] + "»? Связанные с ним SLO будут удалены базой данных.";
            }

            match = normalized.match(/^Delete (service|link|runbook|dependency|SLI|SLO|default stakeholder) [“\"]?(.+?)[”\"]?\?$/i);
            if (match) {
                const names = {
                    service: "сервис",
                    link: "ссылку",
                    runbook: "инструкцию",
                    dependency: "зависимость",
                    sli: "SLI",
                    slo: "SLO",
                    "default stakeholder": "стейкхолдера по умолчанию",
                };
                return "Удалить " + names[match[1].toLowerCase()] + " «" + match[2] + "»?";
            }

            match = normalized.match(/^Delete dependency on [“\"]?(.+?)[”\"]?\?$/i);
            if (match) {
                return "Удалить зависимость от «" + match[1] + "»?";
            }

            match = normalized.match(/^([0-9]+) upstream \/ ([0-9]+) downstream$/i);
            if (match) {
                return "Вышестоящих: " + match[1] + " / нижестоящих: " + match[2];
            }

            match = normalized.match(/^([0-9]+) \/ ([0-9]+) upstream \/ downstream$/i);
            if (match) {
                return "Вышестоящих: " + match[1] + " / нижестоящих: " + match[2];
            }
        }

        if (window.i18n && i18n.locale === "fr") {
            for (const pair of numberedFrench) {
                if (pair[0].test(normalized)) {
                    return normalized.replace(pair[0], pair[1]);
                }
            }

            match = normalized.match(/^Correlation (\d+)s$/i);
            if (match) {
                return "Corrélation : " + match[1] + " s";
            }

            match = normalized.match(/^(\d+) day window$/i);
            if (match) {
                return "Fenêtre : " + match[1] + " jours";
            }

            match = normalized.match(/^Loading service details for\s+(.+?)(?:\.\.\.)?$/i);
            if (match) {
                return "Chargement des détails du service « " + match[1] + " »...";
            }

            match = normalized.match(/^(\d+) more path\(s\)$/i);
            if (match) {
                return match[1] + " autre(s) chemin(s)";
            }

            match = normalized.match(/^(\d+) more downstream path\(s\)$/i);
            if (match) {
                return match[1] + " autre(s) chemin(s) en aval";
            }

            match = normalized.match(/^Budget used:\s*(.+)$/i);
            if (match) {
                return "Budget utilisé : " + match[1];
            }

            match = normalized.match(/^Delete SLI [“\"]?(.+?)[”\"]?\? SLOs attached to it will be deleted by the database\.$/i);
            if (match) {
                return "Supprimer le SLI « " + match[1] + " » ? Les SLO associés seront supprimés par la base de données.";
            }

            match = normalized.match(/^Delete (service|link|runbook|dependency|SLI|SLO|default stakeholder) [“\"]?(.+?)[”\"]?\?$/i);
            if (match) {
                const names = {
                    service: "le service",
                    link: "le lien",
                    runbook: "la procédure",
                    dependency: "la dépendance",
                    sli: "le SLI",
                    slo: "le SLO",
                    "default stakeholder": "la partie prenante par défaut",
                };
                return "Supprimer " + names[match[1].toLowerCase()] + " « " + match[2] + " » ?";
            }

            match = normalized.match(/^Delete dependency on [“\"]?(.+?)[”\"]?\?$/i);
            if (match) {
                return "Supprimer la dépendance envers « " + match[1] + " » ?";
            }

            match = normalized.match(/^([0-9]+) upstream \/ ([0-9]+) downstream$/i);
            if (match) {
                return "En amont : " + match[1] + " / en aval : " + match[2];
            }

            match = normalized.match(/^([0-9]+) \/ ([0-9]+) upstream \/ downstream$/i);
            if (match) {
                return "En amont : " + match[1] + " / en aval : " + match[2];
            }
        }

        if (window.i18n && i18n.locale === "de") {
            for (const pair of numberedGerman) {
                if (pair[0].test(normalized)) {
                    return normalized.replace(pair[0], pair[1]);
                }
            }

            match = normalized.match(/^Correlation (\d+)s$/i);
            if (match) {
                return "Korrelation: " + match[1] + " s";
            }

            match = normalized.match(/^(\d+) day window$/i);
            if (match) {
                return "Zeitraum: " + match[1] + " Tage";
            }

            match = normalized.match(/^Loading service details for\s+(.+?)(?:\.\.\.)?$/i);
            if (match) {
                return "Servicedetails für „" + match[1] + "“ werden geladen...";
            }

            match = normalized.match(/^(\d+) more path\(s\)$/i);
            if (match) {
                return match[1] + " weitere Pfade";
            }

            match = normalized.match(/^(\d+) more downstream path\(s\)$/i);
            if (match) {
                return match[1] + " weitere nachgelagerte Pfade";
            }

            match = normalized.match(/^Budget used:\s*(.+)$/i);
            if (match) {
                return "Verwendetes Budget: " + match[1];
            }

            match = normalized.match(/^Delete SLI [“\"]?(.+?)[”\"]?\? SLOs attached to it will be deleted by the database\.$/i);
            if (match) {
                return "SLI „" + match[1] + "“ löschen? Zugehörige SLOs werden von der Datenbank gelöscht.";
            }

            match = normalized.match(/^Delete (service|link|runbook|dependency|SLI|SLO|default stakeholder) [“\"]?(.+?)[”\"]?\?$/i);
            if (match) {
                const names = {
                    service: "Service",
                    link: "Link",
                    runbook: "Runbook",
                    dependency: "Abhängigkeit",
                    sli: "SLI",
                    slo: "SLO",
                    "default stakeholder": "Standard-Stakeholder",
                };
                return names[match[1].toLowerCase()] + " „" + match[2] + "“ löschen?";
            }

            match = normalized.match(/^Delete dependency on [“\"]?(.+?)[”\"]?\?$/i);
            if (match) {
                return "Abhängigkeit von „" + match[1] + "“ löschen?";
            }

            match = normalized.match(/^([0-9]+) upstream \/ ([0-9]+) downstream$/i);
            if (match) {
                return "Vorgelagert: " + match[1] + " / nachgelagert: " + match[2];
            }

            match = normalized.match(/^([0-9]+) \/ ([0-9]+) upstream \/ downstream$/i);
            if (match) {
                return "Vorgelagert: " + match[1] + " / nachgelagert: " + match[2];
            }
        }

        return null;
    }

    function translateValue(value) {
        const source = String(value == null ? "" : value);
        const exact = exactTranslation(source);
        const pattern = translatePattern(source);
        return pattern || exact || source;
    }

    function preserveOuterWhitespace(source, translated) {
        const leading = String(source).match(/^\s*/)[0];
        const trailing = String(source).match(/\s*$/)[0];
        return leading + translated + trailing;
    }

    function translateTextNode(node) {
        if (!node || node.nodeType !== Node.TEXT_NODE) {
            return;
        }

        const normalized = normalize(node.nodeValue);
        if (!normalized) {
            return;
        }

        const translated = translateValue(normalized);
        if (translated !== normalized) {
            node.nodeValue = preserveOuterWhitespace(node.nodeValue, translated);
        }
    }

    function translateAttributes(element) {
        ATTRIBUTES.forEach(function (attribute) {
            if (!element.hasAttribute || !element.hasAttribute(attribute)) {
                return;
            }
            const current = element.getAttribute(attribute);
            const translated = translateValue(current);
            if (translated !== current) {
                element.setAttribute(attribute, translated);
            }
        });
    }

    function translateElement(root) {
        if (!root) {
            return;
        }

        if (root.nodeType === Node.TEXT_NODE) {
            translateTextNode(root);
            return;
        }

        if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_FRAGMENT_NODE) {
            return;
        }

        if (root.nodeType === Node.ELEMENT_NODE) {
            translateAttributes(root);
        }

        const walker = document.createTreeWalker(
            root,
            NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT
        );
        let node = walker.currentNode;
        while (node) {
            if (node.nodeType === Node.TEXT_NODE) {
                translateTextNode(node);
            } else if (node.nodeType === Node.ELEMENT_NODE) {
                translateAttributes(node);
            }
            node = walker.nextNode();
        }
    }

    function translateServicesUi(root) {
        if (!isServicesContext() || mutationGuard) {
            return;
        }
        mutationGuard = true;
        try {
            translateElement(root || document.body);
        } finally {
            mutationGuard = false;
        }
    }

    function translateChartConfig(config) {
        if (!config || typeof config !== "object") {
            return config;
        }

        if (Array.isArray(config.labels)) {
            config.labels = config.labels.map(translateValue);
        }

        if (Array.isArray(config.datasets)) {
            config.datasets.forEach(function (dataset) {
                if (dataset && typeof dataset.label === "string") {
                    dataset.label = translateValue(dataset.label);
                }
            });
        }

        return config;
    }

    function wrapMessageFunction(name, translator) {
        const original = window[name];
        if (typeof original !== "function" || original.__servicesI18nWrapped) {
            return;
        }

        const wrapped = function () {
            const args = Array.prototype.slice.call(arguments);
            if (isServicesContext()) {
                translator(args);
            }
            return original.apply(this, args);
        };
        wrapped.__servicesI18nWrapped = true;
        window[name] = wrapped;
    }

    function installFunctionWrappers() {
        wrapMessageFunction("showAppError", function (args) {
            if (typeof args[0] === "string") args[0] = translateValue(args[0]);
            if (typeof args[1] === "string") args[1] = translateValue(args[1]);
        });
        wrapMessageFunction("showToast", function (args) {
            if (typeof args[0] === "string") args[0] = translateValue(args[0]);
        });
        wrapMessageFunction("showAppSuccess", function (args) {
            if (typeof args[0] === "string") args[0] = translateValue(args[0]);
            if (typeof args[1] === "string") args[1] = translateValue(args[1]);
        });
        wrapMessageFunction("showAppConfirm", function (args) {
            const options = args[0];
            if (!options || typeof options !== "object") return;
            ["title", "message", "confirmText", "cancelText"].forEach(function (key) {
                if (typeof options[key] === "string") options[key] = translateValue(options[key]);
            });
        });
        wrapMessageFunction("showAppDialog", function (args) {
            const options = args[0];
            if (options && typeof options === "object") {
                ["title", "message", "confirmText"].forEach(function (key) {
                    if (typeof options[key] === "string") options[key] = translateValue(options[key]);
                });
            } else if (typeof args[0] === "string") {
                args[0] = translateValue(args[0]);
            }
        });
    }

    function initialize() {
        installFunctionWrappers();
        translateServicesUi(document.body);

        const observer = new MutationObserver(function (mutations) {
            if (!isServicesContext() || mutationGuard) {
                return;
            }
            mutations.forEach(function (mutation) {
                mutation.addedNodes.forEach(function (node) {
                    translateServicesUi(node);
                });
                if (mutation.type === "characterData") {
                    translateServicesUi(mutation.target);
                }
            });
        });

        observer.observe(document.body, {
            childList: true,
            subtree: true,
            characterData: true,
        });

        window.addEventListener("popstate", function () {
            window.setTimeout(function () { translateServicesUi(document.body); }, 0);
        });
        document.addEventListener("click", function () {
            if (isServicesContext()) {
                window.setTimeout(function () { translateServicesUi(document.body); }, 0);
            }
        });
    }

    window.servicesI18nText = translateValue;
    window.servicesI18nTranslateChartConfig = translateChartConfig;
    window.translateServicesUi = translateServicesUi;

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize);
    } else {
        initialize();
    }
})(window, document);
