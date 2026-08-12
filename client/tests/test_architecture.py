from __future__ import annotations

import ast
from pathlib import Path


PROHIBITED_PACKAGES = {
    "aircraft",
    "checklists",
    "events",
    "habits",
    "replay",
    "rules",
    "state",
    "tools",
}


def test_client_has_no_product_logic_packages_or_imports() -> None:
    package_root = Path(__file__).parents[1] / "dcs_copilot"

    assert not {
        name for name in PROHIBITED_PACKAGES if (package_root / name).exists()
    }

    prohibited_imports: list[str] = []
    for path in package_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                modules = [node.module]
            else:
                continue
            for module in modules:
                parts = module.split(".")
                if (
                    len(parts) >= 2
                    and parts[0] == "dcs_copilot"
                    and parts[1] in PROHIBITED_PACKAGES
                ):
                    prohibited_imports.append(f"{path.relative_to(package_root)}: {module}")

    assert prohibited_imports == []
