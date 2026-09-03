import json
import re
import subprocess
from pathlib import Path

from app.i18n import SUPPORTED_LOCALES


ROOT = Path(__file__).resolve().parents[1]
CATALOG_ROOT = ROOT / "app" / "static" / "i18n"
PLACEHOLDER_RE = re.compile(r"\{[A-Za-z0-9_]+\}")
SRE_ABBREVIATION_RE = re.compile(
    r"\b(SLA|SLI|SLO|MTTA|MTTR|MTBF|RTO|RPO)(?:s)?\b"
)


def load_catalog_file(locale, filename):
    return json.loads(
        (CATALOG_ROOT / locale / filename).read_text(encoding="utf-8")
    )


def test_chinese_locale_is_registered():
    assert SUPPORTED_LOCALES["zh"] == "简体中文"


def test_chinese_catalog_files_and_keys_match_english():
    english_files = sorted(path.name for path in (CATALOG_ROOT / "en").glob("*.json"))
    chinese_files = sorted(path.name for path in (CATALOG_ROOT / "zh").glob("*.json"))

    assert chinese_files == english_files

    for filename in english_files:
        english = load_catalog_file("en", filename)
        chinese = load_catalog_file("zh", filename)

        assert set(chinese) == set(english), filename


def test_chinese_catalog_preserves_format_placeholders():
    for path in sorted((CATALOG_ROOT / "en").glob("*.json")):
        english = load_catalog_file("en", path.name)
        chinese = load_catalog_file("zh", path.name)

        for key, english_value in english.items():
            assert sorted(PLACEHOLDER_RE.findall(chinese[key])) == sorted(
                PLACEHOLDER_RE.findall(english_value)
            ), key


def test_chinese_catalog_preserves_sre_abbreviations():
    for path in sorted((CATALOG_ROOT / "en").glob("*.json")):
        english = load_catalog_file("en", path.name)
        chinese = load_catalog_file("zh", path.name)

        for key, english_value in english.items():
            abbreviations = SRE_ABBREVIATION_RE.findall(english_value)
            if abbreviations:
                assert SRE_ABBREVIATION_RE.findall(chinese[key]) == abbreviations, key


def test_chinese_services_ui_preserves_latency_metric_abbreviations():
    template = (ROOT / "app" / "templates" / "pages" / "services.html").read_text(
        encoding="utf-8"
    )

    assert "<th>MTTA</th>" in template
    assert "<th>MTTR</th>" in template


def test_services_runtime_contains_chinese_dynamic_translations():
    script = (
        ROOT / "app" / "static" / "js" / "pages" / "services" / "i18n_runtime.js"
    ).read_text(encoding="utf-8")

    assert 'i18n.locale === "zh"' in script
    assert "const numberedChinese = [" in script
    assert 'return "已使用错误预算：" + match[1];' in script
    assert 'return "剩余错误预算：" + match[1];' in script
    assert 'return "超出错误预算：" + match[1];' in script
    assert 'return match[2] + " 天内可用性为 " + match[1] + "%";' in script


def test_services_runtime_executes_chinese_dynamic_translations():
    runtime = ROOT / "app" / "static" / "js" / "pages" / "services" / "i18n_runtime.js"
    catalog = CATALOG_ROOT / "zh" / "services_full.json"
    cases = {
        "Target ≥ 99.9%": "目标值 ≥ 99.9%",
        "Threshold ≤ 5m": "阈值 ≤ 5m",
        "Max incidents ≤ 3": "最大事件数 ≤ 3",
        "Budget used: 1h of 2h": "已使用错误预算：1h / 总计 2h",
        "remaining 30m": "剩余错误预算：30m",
        "over budget by 15m": "超出错误预算：15m",
        "99.9% availability over 30 days": "30 天内可用性为 99.9%",
        "3 matching incidents over 30 days": "30 天内有 3 个匹配事件",
        "≤ 3 incidents": "事件数 ≤ 3",
        "severity: critical": "严重程度：严重",
        "priority: P1": "优先级：P1",
        "severity: critical / priority: P1 / maintenance excluded": (
            "严重程度：严重 / 优先级：P1 / 已排除维护时段"
        ),
        "+3 more path(s)": "另有 3 条路径",
        "+2 more downstream path(s)": "另有 2 条下游路径",
    }
    runner = r'''const fs = require("fs");
const catalog = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
global.window = {
    i18n: {
        locale: "zh",
        t: (key, _params, fallback) => catalog[key] || fallback,
    },
    location: {pathname: "/services"},
};
global.i18n = global.window.i18n;
global.document = {
    readyState: "loading",
    addEventListener: () => {},
};
eval(fs.readFileSync(process.argv[1], "utf8"));
const cases = JSON.parse(process.argv[3]);
const actual = Object.fromEntries(
    Object.keys(cases).map((source) => [source, window.servicesI18nText(source)])
);
process.stdout.write(JSON.stringify(actual));'''

    result = subprocess.run(
        ["node", "-e", runner, str(runtime), str(catalog), json.dumps(cases)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == cases
