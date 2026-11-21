"""Gate unused public module functions/classes without importing the application.

Vulture also reports ORM fields, framework methods and local variables. Those
remain in the nightly advisory audit; this gate covers module-level public
definitions in app, using application, CLI, tool and test callers as references.
"""

import ast
import json
import os
from pathlib import Path

from vulture import Vulture


REGISTERED_DECORATORS = (
    "@*.route",
    "@*.get",
    "@*.post",
    "@*.put",
    "@*.patch",
    "@*.delete",
    "@*.errorhandler",
    "@*.app_errorhandler",
    "@*.before_request",
    "@*.before_app_request",
    "@*.after_request",
    "@*.after_app_request",
    "@*.context_processor",
    "@*.app_context_processor",
    "@*.teardown_request",
    "@*.teardown_appcontext",
)


def source_files(root):
    """Collect callers while excluding temporary checkouts and generated files."""
    paths = []
    for directory in ("app", "tests", "tools", "docker", "examples", "docs/examples"):
        for current, directories, files in os.walk(root / directory):
            directories[:] = sorted(
                name for name in directories
                if not name.startswith(".") and name != "__pycache__"
            )
            paths.extend(Path(current) / name for name in sorted(files) if name.endswith(".py"))
    paths.extend(sorted(root.glob("*.py")))
    return paths


def unused_public_definitions(paths, application_root):
    """Return Vulture candidates with a path, name and definition line."""
    scanner = Vulture(ignore_decorators=REGISTERED_DECORATORS)
    scanner.scavenge([str(path) for path in paths])
    if scanner.exit_code:
        raise ValueError("Dead-code analysis could not parse all source files")

    modules = {}
    candidates = []
    for item in scanner.get_unused_code(min_confidence=60):
        if item.typ not in {"function", "class"} or item.name.startswith("_"):
            continue
        path = item.filename.resolve()
        if not path.is_relative_to(application_root.resolve()):
            continue
        if path not in modules:
            modules[path] = {
                node.name: node for node in ast.parse(path.read_text(encoding="utf-8")).body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            }
        node = modules[path].get(item.name)
        if node is not None:
            candidates.append((path, item.name, node.lineno))
    return candidates


def main():
    """Fail on new unused definitions or stale, undocumented exceptions."""
    root = Path(__file__).resolve().parents[1]
    exceptions = json.loads((root / "tools/dead_code_allowlist.json").read_text(encoding="utf-8"))
    candidates = unused_public_definitions(source_files(root), root / "app")
    remaining = set(exceptions)
    failed = False
    for path, name, line in candidates:
        relative = path.relative_to(root).as_posix()
        key = relative + ":" + name
        if key in exceptions and isinstance(exceptions[key], str) and exceptions[key].strip():
            remaining.discard(key)
            continue
        print(f"{relative}:{line}: unused public definition {name}")
        failed = True
    for key in sorted(remaining):
        print(f"Invalid or stale dead-code exception: {key}")
        failed = True
    if not failed:
        print("Unused public code check passed (Vulture, minimum confidence 60).")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
