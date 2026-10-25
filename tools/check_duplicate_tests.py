"""Reject identical pytest test functions copied between files.

Only exact AST matches are flagged: tests with similar behavior but different
assertions or setup require human review and are deliberately left alone.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path
import sys


def duplicates(root: Path) -> list[list[tuple[Path, int, str]]]:
    by_body: dict[str, list[tuple[Path, int, str]]] = defaultdict(list)
    for path in sorted(root.rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            signature = ast.dump(node, include_attributes=False)
            by_body[signature].append((path, node.lineno, node.name))
    return [locations for locations in by_body.values() if len({p for p, _, _ in locations}) > 1]


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("tests")
    matches = duplicates(root)
    if not matches:
        print("No exact duplicate test functions across files")
        return 0
    for group in matches:
        print("Exact duplicate tests:", file=sys.stderr)
        for path, line, name in group:
            print(f"  {path}:{line} {name}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
