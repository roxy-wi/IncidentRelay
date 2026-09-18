"""Regression guards for the mobile notification-to-alert-details flow."""

from pathlib import Path


ROUTER = Path("app/static/js/core/router.js").read_text(encoding="utf-8")
ALERTS = Path("app/static/js/pages/alerts.js").read_text(encoding="utf-8")
PWA = Path("app/static/js/core/pwa.js").read_text(encoding="utf-8")
SERVICE_WORKER = Path("app/static/service-worker.js").read_text(encoding="utf-8")
ALERTS_CSS = Path("app/static/css/alerts.css").read_text(encoding="utf-8")
PAGES_VIEW = Path("app/views/pages_view.py").read_text(encoding="utf-8")
INDEX_TEMPLATE = Path("app/templates/index.html").read_text(encoding="utf-8")
ALERT_DETAILS_TEMPLATE = Path(
    "app/templates/pages/include/alerts_modal.html"
).read_text(encoding="utf-8")


def test_direct_route_shell_is_rendered_before_authenticated_bootstrap():
    immediate_render = ROUTER.index(
        "renderAppRoute(normalizeAppRoutePath(window.location.pathname));"
    )
    ready_handler = ROUTER.index("$(document).ready(function ()")
    render_route = ROUTER.index(
        "renderAppRoute(normalizeAppRoutePath(window.location.pathname));",
        ready_handler,
    )
    start_app = ROUTER.index("startAuthenticatedApp();", render_route)

    assert immediate_render < ready_handler
    assert render_route < start_app


def test_frontend_routes_normalize_trailing_slashes():
    assert 'normalizedPath.replace(/\\/+$/, "")' in ROUTER
    assert 'if (/^\\/alerts\\/\\d+$/.test(normalizedPath))' in ROUTER


def test_alert_details_sync_once_during_authenticated_navigation():
    navigate_start = ROUTER.index("function navigate(path, pushState)")
    authenticated_start = ROUTER.index("function startAuthenticatedApp()")
    ready_start = ROUTER.index("$(document).ready(function ()")

    assert ROUTER[navigate_start:authenticated_start].count(
        "syncAlertDetailsFromUrl();"
    ) == 1
    assert "syncAlertDetailsFromUrl();" not in ROUTER[
        authenticated_start:ready_start
    ]

    render_alerts_start = ALERTS.index("function renderAlertsPage()")
    render_pagination_start = ALERTS.index(
        "function renderAlertsPagination", render_alerts_start
    )
    assert "syncAlertDetailsFromUrl();" not in ALERTS[
        render_alerts_start:render_pagination_start
    ]


def test_server_renders_alert_details_shell_for_direct_links():
    assert "initial_alert_id=alert_id" in PAGES_VIEW
    assert "initial_alert_page" in INDEX_TEMPLATE
    assert "pages.alerts.title" in INDEX_TEMPLATE
    assert 'id="view-alerts"' in INDEX_TEMPLATE
    assert "{% if initial_alert_page %} view-visible{% endif %}" in INDEX_TEMPLATE

    assert "{% if initial_alert_id %} is-open{% endif %}" in ALERT_DETAILS_TEMPLATE
    assert "'flex' if initial_alert_id else 'none'" in ALERT_DETAILS_TEMPLATE
    assert "alert_details.entity.alert_number" in ALERT_DETAILS_TEMPLATE
    assert "alert_details.loading" in ALERT_DETAILS_TEMPLATE


def test_notification_navigation_reuses_the_running_spa_when_available():
    assert 'data.type === "INCIDENTRELAY_PREPARE_NAVIGATION"' in PWA
    assert "beginIncidentRelayPwaTransition();" in PWA
    assert 'data.type !== "INCIDENTRELAY_NAVIGATE"' in PWA
    assert "targetUrl.origin !== window.location.origin" in PWA
    assert "navigate(" in PWA
    assert "replyPort.postMessage({handled: true})" in PWA

    assert '"INCIDENTRELAY_NAVIGATE"' in SERVICE_WORKER
    assert '"INCIDENTRELAY_PREPARE_NAVIGATION"' in SERVICE_WORKER
    assert "await prepareClientNavigation(client, targetUrl)" in SERVICE_WORKER
    assert 'client.visibilityState === "visible"' in SERVICE_WORKER
    assert "await requestClientNavigation(client, targetUrl)" in SERVICE_WORKER
    assert "client.navigate(targetUrl)" in SERVICE_WORKER
    assert "target.origin !== self.location.origin" in SERVICE_WORKER

    running_app_check = SERVICE_WORKER.index("if (\n                canUseRunningApp")
    hard_navigation = SERVICE_WORKER.index(
        "client.navigate(targetUrl)",
        running_app_check,
    )
    assert running_app_check < hard_navigation


def test_standalone_pwa_masks_the_saved_home_snapshot_while_resuming():
    assert "incidentrelay-pwa-transition" in INDEX_TEMPLATE
    assert 'id="pwa-navigation-mask"' in INDEX_TEMPLATE
    assert "setupIncidentRelayPwaTransitionMask();" in PWA
    assert 'document.visibilityState === "hidden"' in PWA
    assert "window.addEventListener(\"pagehide\"" in PWA


def test_alert_deep_link_opens_loading_modal_before_request_completes():
    show_details = ALERTS.index("function showAlertDetails(alertId)")
    open_loading_modal = ALERTS.index("openAlertDetailsModal();", show_details)
    request = ALERTS.index("apiGet(", show_details)

    assert open_loading_modal < request
    assert "closeAlertDetailsModal({updateUrl: false});" in ALERTS[request:]
    assert "showApiError(xhr);" in ALERTS[request:]
    assert ALERTS[request:].count("currentDetailsAlertId !== alertId") >= 2


def test_alert_details_use_a_theme_aware_full_screen_mobile_layout():
    mobile_layout = ALERTS_CSS.index("body.md-theme #alert-details-modal {")
    mobile_dialog = ALERTS_CSS.index(
        "body.md-theme #alert-details-modal .app-modal-dialog {",
        mobile_layout,
    )

    assert "padding: 0;" in ALERTS_CSS[mobile_layout:mobile_dialog]
    assert "background: var(--md-surface);" in ALERTS_CSS[mobile_layout:mobile_dialog]
    assert "width: 100vw;" in ALERTS_CSS[mobile_dialog:]
    assert "height: 100dvh;" in ALERTS_CSS[mobile_dialog:]
    assert "border-radius: 0;" in ALERTS_CSS[mobile_dialog:]
