"""Static guards for the shared light/dark theme contract."""

from __future__ import annotations

import re
from pathlib import Path


CSS_ROOT = Path("app/static/css")
FIRST_PARTY_STYLES = tuple(
    sorted(
        path.name
        for path in CSS_ROOT.glob("*.css")
        if path.name not in {"material.css", "theme_dark.css"}
    )
)

# Recurring light-theme literals previously used by page-specific styles.
# Semantic/status colors are intentionally not forbidden here.
LIGHT_SURFACE = re.compile(
    r"(?:background|background-color)\s*:\s*(?:"
    r"white|#fff(?:fff)?|#fbfcfe|#fbfdff|#f9fbff|#f8fbff|#f8fafc|"
    r"#f2f4f7|#f1f5f9|#eef4ff"
    r")\b",
    re.IGNORECASE,
)
LIGHT_TEXT = re.compile(
    r"color\s*:\s*(?:#101828|#344054|#475467|#64748b|#667085|#7b8794)\b",
    re.IGNORECASE,
)
LIGHT_FALLBACK = re.compile(
    r"var\([^)]*,\s*(?:white|#fff(?:fff)?|#f8fafc|#101828|#344054|#667085)",
    re.IGNORECASE,
)


def _without_comments(source: str) -> str:
    return re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)


def _selector_count(source: str, selector: str) -> int:
    return len(
        re.findall(
            rf"(?m)^\s*{re.escape(selector)}\s*\{{",
            source,
        )
    )


def test_first_party_component_styles_use_shared_theme_tokens():
    violations: dict[str, list[str]] = {}

    for filename in FIRST_PARTY_STYLES:
        path = CSS_ROOT / filename
        source = _without_comments(path.read_text(encoding="utf-8"))
        bad_lines = []

        for line in source.splitlines():
            stripped = line.strip()
            if (
                LIGHT_SURFACE.search(stripped)
                or LIGHT_TEXT.search(stripped)
                or LIGHT_FALLBACK.search(stripped)
            ):
                bad_lines.append(stripped)

        if bad_lines:
            violations[filename] = bad_lines

    assert violations == {}


def test_page_styles_do_not_define_their_own_color_scheme_overrides():
    offenders = []

    for filename in FIRST_PARTY_STYLES:
        source = (CSS_ROOT / filename).read_text(encoding="utf-8")
        if "data-color-scheme" in source:
            offenders.append(filename)

    assert offenders == []


def test_dark_theme_is_token_layer_not_page_override_catalog():
    source = (CSS_ROOT / "theme_dark.css").read_text(encoding="utf-8")

    assert "--md-surface: #111827" in source
    assert "--md-text: #e5edf6" in source
    assert "--md-input-bg: #0f172a" in source
    assert "--md-operational: #4ade80" in source
    assert "--md-chart-grid: rgba(148, 163, 184, 0.22)" in source

    # Vendor controls need compatibility overrides because their bundled CSS
    # uses hard-coded colors. First-party page components should not live here.
    assert ".select2-container" in source
    assert ".ts-wrapper" in source
    for selector in (
        ".detail-item",
        ".event-item",
        ".stack-card-header",
        ".alert-service-context",
        ".impact-path-node",
        ".orchestration-rule-card",
    ):
        assert selector not in source


def test_shared_component_styles_do_not_restore_known_duplicate_blocks():
    oncall = (CSS_ROOT / "oncall.css").read_text(encoding="utf-8")
    services = (CSS_ROOT / "services.css").read_text(encoding="utf-8")
    health = (CSS_ROOT / "oncall_health.css").read_text(encoding="utf-8")
    calendar = (CSS_ROOT / "calendar_week.css").read_text(encoding="utf-8")

    for selector in (
        ".sidebar {",
        ".brand {",
        ".menu-link {",
        ".topbar-icon-button {",
        ".table-wrapper {",
    ):
        assert _selector_count(oncall, selector.removesuffix(" {")) == 1

    assert _selector_count(services, ".impact-path-row") == 1
    assert _selector_count(services, ".impact-flag-warning") == 1
    assert _selector_count(services, ".service-dependency-graph-legend") == 1
    assert health.count("@media (max-width: 560px)") == 1

    for selector in (
        ".calendar-assignment {",
        ".calendar-assignment-badge {",
        ".calendar-assignment-user {",
        ".calendar-day-cell {",
        ".calendar-legend-item {",
    ):
        assert _selector_count(calendar, selector.removesuffix(" {")) == 1


def test_dependency_graph_reads_shared_theme_tokens_and_reacts_to_theme_change():
    source = Path("app/static/js/components/dependency_graph.js").read_text(
        encoding="utf-8"
    )

    assert "serviceDependencyGraphThemeColor" in source
    assert '"--md-surface"' in source
    assert '"--md-partial-outage"' in source
    assert '"incidentrelay:theme-change"' in source
    assert '"border-color": theme.majorOutage' in source
    assert '"border-color": theme.maintenance' in source


def test_chart_defaults_read_shared_theme_tokens():
    source = Path("app/static/js/core/theme.js").read_text(encoding="utf-8")

    assert 'themeToken("--md-text-soft"' in source
    assert '"--md-chart-grid"' in source


def test_login_and_offline_shells_have_dark_theme_support():
    login = Path("app/templates/login_only.html").read_text(encoding="utf-8")
    offline = Path("app/static/offline.html").read_text(encoding="utf-8")

    assert 'data-theme="system"' in login
    assert 'js/core/theme.js' in login
    assert 'css/theme_dark.css' in login
    assert 'class="md-theme login-shell"' in login

    assert "prefers-color-scheme: dark" in offline
    assert "--offline-surface: #111827" in offline
    assert "background: var(--offline-surface)" in offline
