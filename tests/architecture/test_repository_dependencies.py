"""Keep persistence independent of application services and delivery adapters."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN = ("app.services", "app.views", "app.notifiers")


def test_repositories_do_not_import_application_layers():
    """Check local imports too: delaying an import does not remove a dependency."""
    violations = []
    paths = [ROOT / "app" / "db.py", *(ROOT / "app" / "modules" / "db").rglob("*.py")]
    for path in sorted(paths):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level:
                    package = path.relative_to(ROOT).with_suffix("").parts[:-1]
                    parts = (*package[: len(package) - node.level + 1], module)
                    module = ".".join(part for part in parts if part)
                modules = [module, *(f"{module}.{alias.name}" for alias in node.names)]
            elif isinstance(node, ast.Call) and node.args:
                function = node.func
                dynamic_import = (
                    isinstance(function, ast.Name) and function.id == "__import__"
                ) or (
                    isinstance(function, ast.Attribute)
                    and function.attr == "import_module"
                )
                if dynamic_import and isinstance(node.args[0], ast.Constant):
                    modules = [node.args[0].value]
            for module in modules:
                if isinstance(module, str) and any(
                    module == prefix or module.startswith(prefix + ".")
                    for prefix in FORBIDDEN
                ):
                    violations.append(
                        f"{path.relative_to(ROOT)}:{node.lineno}: {module}"
                    )
                    break
    assert not violations, "Persistence imports application code:\n" + "\n".join(
        violations
    )
