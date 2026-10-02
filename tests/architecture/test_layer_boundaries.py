"""Enforce the architectural boundaries described in docs/ARCHITECTURE.md.

The roadmap's completion gate requires that no milestone weakens an unrelated boundary.
These tests make that mechanical: a forbidden import fails the build. If a rule here
needs to change, change docs/ARCHITECTURE.md in the same commit and say why.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "front_office"
PACKAGE_DIR = REPO_ROOT / "src" / PACKAGE
APPS_DIR = REPO_ROOT / "apps"

# Which other layers each layer may import. A layer may always import itself.
LAYER_RULES: dict[str, set[str]] = {
    "domain": set(),
    "config": {"domain"},
    "providers": {"domain"},
    "rawstore": {"domain"},
    "processing": {"domain"},
    "storage": {"domain"},
    "quality": {"domain"},
    "analytics": {"domain"},
    "modeling": {"domain", "analytics"},
    "pipelines": {
        "domain",
        "config",
        "providers",
        "rawstore",
        "processing",
        "storage",
        "quality",
        "modeling",
    },
    "services": {"domain", "config", "storage", "analytics", "quality", "modeling"},
    "interfaces": {"domain", "config", "pipelines", "services"},
}

# The user interface displays what services return; it never reaches past them.
APP_RULES: set[str] = {"domain", "services"}

# Third-party libraries that belong to exactly one place. "apps" is the Streamlit UI.
LIBRARY_OWNERS: dict[str, set[str]] = {
    "nba_api": {"providers"},
    "requests": {"providers"},
    "sqlalchemy": {"storage"},
    "sqlite3": {"storage"},
    "yaml": {"config"},
    "typer": {"interfaces"},
    "rich": {"interfaces"},
    "streamlit": {"apps"},
    "plotly": {"apps"},
}

# Whole-dollar amounts this large in source code are almost certainly a cap figure that
# belongs in configs/seasons instead.
LARGEST_ALLOWED_LITERAL = 9_999_999


def python_files(directory: Path) -> list[Path]:
    return sorted(path for path in directory.rglob("*.py") if "__pycache__" not in path.parts)


def module_name(path: Path) -> str:
    parts = list(path.relative_to(REPO_ROOT / "src").with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def imported_modules(path: Path, current_module: str | None) -> Iterator[tuple[str, int]]:
    """Yield ``(absolute module name, line number)`` for every import in a file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = node.module or ""
            else:
                if current_module is None:
                    continue
                is_package = path.name == "__init__.py"
                package_parts = (
                    current_module.split(".") if is_package else current_module.split(".")[:-1]
                )
                anchor = package_parts[: len(package_parts) - (node.level - 1)]
                base = ".".join([*anchor, node.module] if node.module else anchor)
            yield base, node.lineno
            # "from front_office import analytics" imports a layer by name;
            # "from front_office import __version__" does not.
            if base == PACKAGE:
                for alias in node.names:
                    if (PACKAGE_DIR / alias.name).is_dir() or (
                        PACKAGE_DIR / f"{alias.name}.py"
                    ).is_file():
                        yield f"{PACKAGE}.{alias.name}", node.lineno


def layer_of(module: str) -> str | None:
    parts = module.split(".")
    if parts[0] != PACKAGE or len(parts) < 2:
        return None
    return parts[1]


class TestTheImportScanner:
    """The boundary tests are only as good as the scanner, so prove it sees imports."""

    def scan(self, tmp_path: Path, source: str, name: str = "module.py") -> set[str]:
        path = tmp_path / name
        path.write_text(source, encoding="utf-8")
        module = f"{PACKAGE}.analytics" if name == "__init__.py" else f"{PACKAGE}.analytics.module"
        return {imported for imported, _ in imported_modules(path, module)}

    def test_sees_absolute_imports(self, tmp_path: Path) -> None:
        found = self.scan(tmp_path, "import front_office.storage.engine\nimport sqlalchemy as sa\n")
        assert {"front_office.storage.engine", "sqlalchemy"} <= found

    def test_sees_from_imports(self, tmp_path: Path) -> None:
        found = self.scan(tmp_path, "from front_office.providers.nba import client\n")
        assert "front_office.providers.nba" in found

    def test_sees_a_layer_imported_from_the_package_root(self, tmp_path: Path) -> None:
        found = self.scan(tmp_path, "from front_office import storage, __version__\n")
        assert "front_office.storage" in found
        assert "front_office.__version__" not in found

    def test_resolves_relative_imports(self, tmp_path: Path) -> None:
        found = self.scan(tmp_path, "from . import sibling\nfrom ..storage import engine\n")
        assert {"front_office.analytics", "front_office.storage"} <= found

    def test_resolves_relative_imports_in_a_package_init(self, tmp_path: Path) -> None:
        found = self.scan(tmp_path, "from .core import x\nfrom ..storage import y\n", "__init__.py")
        assert {"front_office.analytics.core", "front_office.storage"} <= found

    def test_sees_imports_inside_functions(self, tmp_path: Path) -> None:
        found = self.scan(tmp_path, "def f():\n    import front_office.pipelines\n")
        assert "front_office.pipelines" in found

    def test_layer_of(self) -> None:
        assert layer_of("front_office.storage.engine") == "storage"
        assert layer_of("front_office") is None
        assert layer_of("pandas.core") is None


def test_every_layer_package_has_a_rule() -> None:
    packages = {path.name for path in PACKAGE_DIR.iterdir() if (path / "__init__.py").is_file()}
    assert packages == set(LAYER_RULES), (
        "src/front_office packages and LAYER_RULES have drifted apart; "
        "a new layer needs an explicit dependency rule"
    )


def test_architecture_document_states_the_same_rules() -> None:
    """The table in docs/ARCHITECTURE.md is the readable copy of LAYER_RULES."""
    documented: dict[str, set[str]] = {}
    for line in (REPO_ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 3 or not cells[0].startswith("`"):
            continue
        layer = cells[0].split("`")[1].rstrip("/")
        documented[layer] = set(cells[2].split("`")[1::2])
    assert documented.pop("apps") == APP_RULES
    assert documented == LAYER_RULES


def test_rules_only_reference_known_layers() -> None:
    known = set(LAYER_RULES)
    for layer, allowed in LAYER_RULES.items():
        assert allowed <= known, f"{layer} allows unknown layers {allowed - known}"
        assert layer not in allowed
    assert APP_RULES <= known


def test_layer_rules_have_no_cycles() -> None:
    resolved: set[str] = set()
    remaining = dict(LAYER_RULES)
    while remaining:
        ready = [layer for layer, allowed in remaining.items() if allowed <= resolved]
        assert ready, f"dependency cycle among layers: {sorted(remaining)}"
        resolved.update(ready)
        for layer in ready:
            del remaining[layer]


def test_layers_only_import_what_they_are_allowed_to() -> None:
    problems = []
    for path in python_files(PACKAGE_DIR):
        module = module_name(path)
        layer = layer_of(module)
        if layer is None:
            continue
        allowed = LAYER_RULES[layer] | {layer}
        for imported, line in imported_modules(path, module):
            target = layer_of(imported)
            if target is not None and target not in allowed:
                problems.append(
                    f"{path.relative_to(REPO_ROOT)}:{line} {layer} -> {target} ({imported})"
                )
    assert not problems, "forbidden cross-layer imports:\n" + "\n".join(problems)


def test_the_package_root_imports_no_layer() -> None:
    """``import front_office`` must stay cheap and free of side effects."""
    imported = [name for name, _ in imported_modules(PACKAGE_DIR / "__init__.py", PACKAGE)]
    assert not [name for name in imported if name.startswith(PACKAGE)]


def test_apps_only_import_services_and_domain() -> None:
    if not APPS_DIR.is_dir():
        pytest.skip("no user interface yet")
    problems = []
    for path in python_files(APPS_DIR):
        for imported, line in imported_modules(path, None):
            target = layer_of(imported)
            if imported == PACKAGE or (target is not None and target not in APP_RULES):
                problems.append(f"{path.relative_to(REPO_ROOT)}:{line} apps -> {imported}")
    assert not problems, "the UI may only import services and domain:\n" + "\n".join(problems)


def test_third_party_libraries_stay_in_their_layer() -> None:
    problems = []
    for path in python_files(PACKAGE_DIR):
        module = module_name(path)
        layer = layer_of(module) or "<root>"
        for imported, line in imported_modules(path, module):
            library = imported.split(".")[0]
            owners = LIBRARY_OWNERS.get(library)
            if owners is not None and layer not in owners:
                problems.append(
                    f"{path.relative_to(REPO_ROOT)}:{line} {layer} imports {library} "
                    f"(allowed in: {', '.join(sorted(owners))})"
                )
    if APPS_DIR.is_dir():
        for path in python_files(APPS_DIR):
            for imported, line in imported_modules(path, None):
                library = imported.split(".")[0]
                owners = LIBRARY_OWNERS.get(library)
                if owners is not None and "apps" not in owners:
                    problems.append(f"{path.relative_to(REPO_ROOT)}:{line} apps imports {library}")
    assert not problems, "third-party library used outside its layer:\n" + "\n".join(problems)


def test_no_cap_sized_dollar_figures_in_source_code() -> None:
    """Season-specific financial figures live in configs/seasons, never in Python."""
    problems = []
    directories = [PACKAGE_DIR, *([APPS_DIR] if APPS_DIR.is_dir() else [])]
    for directory in directories:
        for path in python_files(directory):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, int | float)
                    and not isinstance(node.value, bool)
                    and abs(node.value) > LARGEST_ALLOWED_LITERAL
                ):
                    problems.append(
                        f"{path.relative_to(REPO_ROOT)}:{node.lineno} literal {node.value}"
                    )
    assert not problems, "move these figures into configuration:\n" + "\n".join(problems)
