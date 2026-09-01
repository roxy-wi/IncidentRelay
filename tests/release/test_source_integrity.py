"""Release guards against declarations that silently shadow earlier code."""

from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path


APP_ROOT = Path("app")
JS_ROOT = APP_ROOT / "static" / "js"
JS_FUNCTION_RE = re.compile(r"^function\s+([A-Za-z_$][\w$]*)\s*\(")


def _python_top_level_declarations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]


def test_application_modules_do_not_redeclare_top_level_python_symbols():
    duplicates: dict[str, list[str]] = {}

    for path in sorted(APP_ROOT.rglob("*.py")):
        if "migrations" in path.parts:
            continue

        counts = Counter(_python_top_level_declarations(path))
        repeated = sorted(name for name, count in counts.items() if count > 1)
        if repeated:
            duplicates[str(path)] = repeated

    assert duplicates == {}


def test_first_party_javascript_does_not_redeclare_top_level_functions():
    duplicates: dict[str, list[str]] = {}

    for path in sorted(JS_ROOT.rglob("*.js")):
        if "vendor" in path.parts or path.name.endswith(".min.js"):
            continue

        names = []
        for line in path.read_text(encoding="utf-8").splitlines():
            match = JS_FUNCTION_RE.match(line)
            if match:
                names.append(match.group(1))

        counts = Counter(names)
        repeated = sorted(name for name, count in counts.items() if count > 1)
        if repeated:
            duplicates[str(path)] = repeated

    assert duplicates == {}


def _python_string_assignment(path: Path, name: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return node.value.value
    raise AssertionError(f"{name} is not a top-level string assignment in {path}")


def _yaml_scalar(path: Path, key: str) -> str:
    prefix = f"{key}:"
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith(prefix):
            continue
        value = line[len(prefix):].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value
    raise AssertionError(f"{key} is missing from {path}")



def test_release_artifact_versions_match_application_version():
    service_version = _python_string_assignment(
        APP_ROOT / "version.py", "SERVICE_VERSION"
    )
    chart_app_version = _yaml_scalar(
        Path("helm") / "incidentrelay" / "Chart.yaml",
        "appVersion",
    )
    assert chart_app_version == service_version
