let currentUser = null;

const routes = {
    "/": { page: "dashboard", title: "Overview", subtitle: "Real-time summary of active incidents and affected teams", load: function () { loadDashboard(); } },
    "/alerts": { page: "alerts", title: "Alerts", subtitle: "Search, inspect, acknowledge and resolve routed incidents", load: function () { loadAlerts(); } },
    "/rotations": { page: "rotations", title: "Rotations", subtitle: "Manage on-call rotations", load: function () { loadRotations(); } },
    "/calendar": { page: "calendar", title: "Calendar", subtitle: "On-call calendar by team", load: function () { loadCalendar(); } },
    "/routes": { page: "routes", title: "Routes", subtitle: "Connect alert sources, rotations and channels", load: function () { loadRoutes(); } },
    "/services": { page: "services", title: "Services", subtitle: "Technical services, ownership and status", load: function () { loadServices(); } },
    "/business-services": { page: "business-services", title: "Business Services", subtitle: "Customer-facing capabilities, business impact and status page services", load: function () { loadBusinessServices(); }},
    "/heartbeats": { page: "heartbeats", title: "Heartbeats", subtitle: "Dead-man checks for jobs, monitoring pipelines and alert delivery paths", load: function () { loadHeartbeats(); }},
    "/maintenance-windows": { page: "maintenance-windows", title: "Maintenance Windows", subtitle: "Planned maintenance, notification suppression and escalation handling", load: function () {loadMaintenanceWindows();}},
    "/event-orchestration": { page: "orchestrations", title: "Event Orchestration", subtitle: "Route, enrich, suppress and automate incoming events", load: function () { loadOrchestrations(); } },
    "/escalation-policies": { page: "escalation-policies", title: "Escalation Policies", subtitle: "Define alert escalation chains by team", load: function () { loadEscalationPolicies(); } },
    "/notification-policies": { page: "notification-policies", title: "Notification Policies", subtitle: "Select shared notification channels for service events", load: function () { loadNotificationPolicies(); }},
    "/matcher-presets": { page: "matcher-presets", title: "Matcher Presets", subtitle: "Reusable alert matchers for service policies", load: function () { loadMatcherPresets(); } },
    "/priority-policies": { page: "priority-policies", title: "Priority Policies", subtitle: "Automatic incident priority rules", load: function () { loadPriorityPolicies(); }},
    "/channels": { page: "channels", title: "Channels", subtitle: "Notification channels", load: function () { loadChannels(); } },
    "/silences": { page: "silences", title: "Silences", subtitle: "Mute alerts by matchers", load: function () { loadSilences(); } },
    "/teams": { page: "teams", title: "Teams", subtitle: "Independent duty teams", load: function () { loadTeams(); } },
    "/groups": { page: "groups", title: "Groups", subtitle: "Access boundaries and user roles", load: function () { loadGroups(); } },
    "/profile": { page: "profile", title: "Profile", subtitle: "User profile and personal API token", load: function () { loadProfile(); } },
    "/admin/users": { page: "admin-users", title: "Admin users", subtitle: "Admin-only user workspace", load: function () { loadAdminUsers(); } },
    "/admin/sso": { page: "sso", title: "SSO", subtitle: "OIDC and SAML login providers", load: function () {  loadSsoAdmin(); } },
    "/login": { page: "login", title: "Login", subtitle: "JWT authentication", load: function () { loadLogin(); } }
};
