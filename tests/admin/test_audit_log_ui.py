from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_audit_log_page_is_registered_in_admin_navigation():
    index = (ROOT / "app/templates/index.html").read_text(encoding="utf-8")
    routes = (ROOT / "app/static/js/core/state.js").read_text(encoding="utf-8")
    router = (ROOT / "app/static/js/core/router.js").read_text(encoding="utf-8")

    assert 'href="/admin/audit-log"' in index
    assert 'id="view-audit-log"' in index
    assert '"/admin/audit-log"' in routes
    assert "hasAuditLogAccess" in router
    assert ".menu-link-audit" in router


def test_audit_log_translations_exist_for_all_supported_locales():
    required_keys = {
        "nav.audit_log",
        "pages.audit-log.title",
        "audit.list.title",
        "audit.filters.group",
        "audit.table.action",
        "audit.details.payload",
        "audit.errors.access_denied",
    }

    import json

    for locale in ("en", "de", "fr", "ru", "zh"):
        path = ROOT / "app/static/i18n" / locale / "audit_logs.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert required_keys <= payload.keys()
