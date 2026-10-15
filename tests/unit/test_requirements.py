"""requirements.txt and requirements-dev.txt pin what pyproject.toml declares.

pyproject.toml states each dependency with the lowest version that works; the requirements
files pin the version the lab is tested with, for a reproducible install (the capstone's
brief, and the Docker image, install from them). These tests keep the three in step: no
dependency declared but not pinned, none pinned but not declared, every pin within its
declaration - and every pin the version installed here, so a pin cannot drift from what the
suite ran against.
"""

from __future__ import annotations

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[2]


def declared(group: str) -> dict[str, Requirement]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    items = (
        project["dependencies"] if group == "runtime" else project["optional-dependencies"][group]
    )
    return {canonicalize_name(Requirement(item).name): Requirement(item) for item in items}


def pinned(name: str) -> dict[str, str]:
    """Each package a requirements file pins, by its canonical name: name -> version."""
    found: dict[str, str] = {}
    for line in (ROOT / name).read_text(encoding="utf-8").splitlines():
        text = line.split("#", 1)[0].strip()
        if not text or text.startswith("-r "):
            continue
        requirement = Requirement(text)
        (specifier,) = requirement.specifier
        assert specifier.operator == "==", f"{name}: {text} is not pinned with =="
        key = canonicalize_name(requirement.name)
        assert key not in found, f"{name} pins {requirement.name} twice"
        found[key] = specifier.version
    return found


@pytest.mark.parametrize(
    ("group", "file"), [("runtime", "requirements.txt"), ("dev", "requirements-dev.txt")]
)
def test_every_declared_dependency_is_pinned_within_its_declaration(group: str, file: str) -> None:
    wanted, pins = declared(group), pinned(file)
    assert set(pins) == set(wanted), f"{file} and pyproject.toml ({group}) list different packages"
    outside = {
        name: pin
        for name, pin in pins.items()
        if not wanted[name].specifier.contains(pin, prereleases=True)
    }
    assert outside == {}, f"pinned outside what pyproject.toml declares: {outside}"


def test_the_dev_file_installs_the_runtime_file_too() -> None:
    lines = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8").splitlines()
    assert "-r requirements.txt" in lines


@pytest.mark.parametrize("file", ["requirements.txt", "requirements-dev.txt"])
def test_every_pin_is_the_version_installed_here(file: str) -> None:
    """The pins are what the suite runs against: after an upgrade, pin the new version."""
    drifted = {}
    for name, pin in pinned(file).items():
        try:
            installed = version(name)
        except PackageNotFoundError:
            installed = None
        if installed != pin:
            drifted[name] = (pin, installed)
    assert drifted == {}, f"{file} pins (pinned, installed): {drifted}"
