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
    "assistant": {"domain", "config", "providers", "pipelines", "services"},
    # The capstone's HTTP API (decision 0019): outermost, beside the workbench.
    "server": {"domain", "config", "pipelines", "services", "assistant"},
}

# The user interface displays what services return; it never reaches past them. The
# assistant is the one outer layer it may call, through a single module.
APP_RULES: set[str] = {"domain", "services", "assistant"}
APP_ASSISTANT_MODULES: set[str] = {"front_office.assistant.api"}
# The API reaches the assistant the same way (decision 0019).
SERVER_ASSISTANT_MODULES: set[str] = {"front_office.assistant.api"}

# Of the layers that touch the network or the data, the assistant may use only these
# modules: the local model and the web, the current-data refresh and the reading of a web
# page - never the stats.nba.com ingest, a build, a fit or a contract import (decision 0018).
ASSISTANT_REACH: dict[str, set[str]] = {
    "providers": {"front_office.providers.ollama", "front_office.providers.web"},
    "pipelines": {
        "front_office.pipelines.current",
        "front_office.pipelines.web",
        # A7: reads a contract file and the raw store, and stores nothing - unlike the
        # import beside it in pipelines.contracts, which the assistant may not reach.
        "front_office.pipelines.contract_review",
    },
}

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
    "pypdf": {"processing"},
    # The capstone (decision 0019): the HTTP framework and its tokens belong to the API,
    # password hashing to the service that keeps the accounts.
    "fastapi": {"server"},
    "starlette": {"server"},
    "jwt": {"server"},
    "bcrypt": {"services"},
    # The documents' vector index is stored state, like a database (C3).
    "chromadb": {"storage"},
}

# What can open a connection (the A9 network audit). The lab reaches the network through
# providers alone; the command line's check that `fol ui` has started asks this machine's own
# server. The workbench and the scripts reach the network only through the providers.
NETWORK_MODULES: dict[str, set[str]] = {
    "requests": {"providers"},
    "nba_api": {"providers"},
    "httpx": {"providers"},
    "aiohttp": {"providers"},
    "socket": {"providers"},
    "http.client": {"providers"},
    "urllib.request": {"providers", "interfaces"},
}
SCRIPTS_DIR = REPO_ROOT / "scripts"

# The one workbench module that opens a connection: to the lab's own API, at the address
# FOL_API_URL names - the Ask the Docs page's way in (decision 0019). Nothing else in apps/
# or scripts/ may.
APP_API_CLIENT = APPS_DIR / "workbench" / "wb" / "api_client.py"
APP_API_CLIENT_LIBRARIES = {"requests"}

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
    assert not problems, (
        "the UI may only import services, domain and the assistant's facade:\n"
        + "\n".join(problems)
    )


def _within(module: str, allowed: set[str]) -> bool:
    return any(module == name or module.startswith(f"{name}.") for name in allowed)


def test_apps_reach_the_assistant_only_through_its_facade() -> None:
    if not APPS_DIR.is_dir():
        pytest.skip("no user interface yet")
    problems = [
        f"{path.relative_to(REPO_ROOT)}:{line} apps -> {imported}"
        for path in python_files(APPS_DIR)
        for imported, line in imported_modules(path, None)
        if layer_of(imported) == "assistant" and not _within(imported, APP_ASSISTANT_MODULES)
    ]
    assert not problems, "the UI may import only front_office.assistant.api:\n" + "\n".join(
        problems
    )


def test_the_server_reaches_the_assistant_only_through_its_facade() -> None:
    problems = []
    for path in python_files(PACKAGE_DIR / "server"):
        module = module_name(path)
        for imported, line in imported_modules(path, module):
            if layer_of(imported) == "assistant" and not _within(
                imported, SERVER_ASSISTANT_MODULES
            ):
                problems.append(f"{path.relative_to(REPO_ROOT)}:{line} server -> {imported}")
    assert not problems, "the API may import only front_office.assistant.api:\n" + "\n".join(
        problems
    )


def test_the_assistant_reaches_providers_and_pipelines_only_through_named_modules() -> None:
    """``from front_office.providers import x`` names the whole layer, and is refused too."""
    problems = []
    for path in python_files(PACKAGE_DIR / "assistant"):
        module = module_name(path)
        for imported, line in imported_modules(path, module):
            target = layer_of(imported)
            if target in ASSISTANT_REACH and not _within(imported, ASSISTANT_REACH[target]):
                problems.append(f"{path.relative_to(REPO_ROOT)}:{line} assistant -> {imported}")
    assert not problems, (
        "the assistant may use only these provider and pipeline modules "
        f"{sorted(set().union(*ASSISTANT_REACH.values()))}:\n" + "\n".join(problems)
    )


def test_a_named_module_is_matched_by_name_not_by_prefix() -> None:
    allowed = {"front_office.providers.ollama"}
    assert _within("front_office.providers.ollama", allowed)
    assert _within("front_office.providers.ollama.parts", allowed)
    assert not _within("front_office.providers", allowed)
    assert not _within("front_office.providers.ollama_cloud", allowed)


def test_the_named_assistant_modules_belong_to_their_layers() -> None:
    for layer, modules in ASSISTANT_REACH.items():
        assert layer in LAYER_RULES["assistant"]
        assert all(layer_of(module) == layer for module in modules)
    assert all(layer_of(module) == "assistant" for module in APP_ASSISTANT_MODULES)


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
                allowed = path == APP_API_CLIENT and library in APP_API_CLIENT_LIBRARIES
                if owners is not None and "apps" not in owners and not allowed:
                    problems.append(f"{path.relative_to(REPO_ROOT)}:{line} apps imports {library}")
    assert not problems, "third-party library used outside its layer:\n" + "\n".join(problems)


def network_imports(path: Path) -> Iterator[tuple[str, int]]:
    """Every import of a module that can open a connection, ``from urllib import request``
    included."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module, *(f"{node.module}.{alias.name}" for alias in node.names)]
        for name in names:
            owner = next(
                (key for key in NETWORK_MODULES if name == key or name.startswith(key + ".")),
                None,
            )
            if owner is not None:
                yield owner, node.lineno


def test_network_access_is_imported_by_the_providers_alone(tmp_path: Path) -> None:
    probe = tmp_path / "probe.py"
    probe.write_text("from urllib import request\nimport http.client\n", encoding="utf-8")
    assert [name for name, _ in network_imports(probe)] == ["urllib.request", "http.client"]
    problems = []
    for path in python_files(PACKAGE_DIR):
        layer = layer_of(module_name(path)) or "<root>"
        problems += [
            f"{path.relative_to(REPO_ROOT)}:{line} {layer} imports {name}"
            for name, line in network_imports(path)
            if layer not in NETWORK_MODULES[name]
        ]
    for folder in (APPS_DIR, SCRIPTS_DIR):
        for path in python_files(folder) if folder.is_dir() else []:
            problems += [
                f"{path.relative_to(REPO_ROOT)}:{line} imports {name}"
                for name, line in network_imports(path)
                if not (path == APP_API_CLIENT and name in APP_API_CLIENT_LIBRARIES)
            ]
    assert not problems, "network access outside the providers:\n" + "\n".join(problems)


def test_the_workbenchs_one_connection_is_the_api_client() -> None:
    """The exception above names a module that exists and does connect - a rule that
    excepts nothing would hide a move - and only with the library it names."""
    found = {name for name, _ in network_imports(APP_API_CLIENT)}
    assert found == APP_API_CLIENT_LIBRARIES


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
