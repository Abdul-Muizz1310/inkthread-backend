"""Spec 10 T-OPS-7: the uv constraints admit Dependabot's uv and the image's pinned uv."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet

ROOT = Path(__file__).resolve().parents[2]
DEPENDABOT_UV = "0.12.18"


def _pyproject() -> dict[str, object]:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def _required_version() -> SpecifierSet:
    tool = _pyproject()["tool"]
    assert isinstance(tool, dict)
    return SpecifierSet(tool["uv"]["required-version"])


def _build_backend() -> SpecifierSet:
    build = _pyproject()["build-system"]
    assert isinstance(build, dict)
    (requirement,) = [Requirement(r) for r in build["requires"]]
    assert requirement.name in {"uv-build", "uv_build"}
    return requirement.specifier


def _image_uv() -> str:
    found = re.search(r"ghcr\.io/astral-sh/uv:(\d+\.\d+\.\d+)", (ROOT / "Dockerfile").read_text())
    assert found is not None
    return found.group(1)


def test_t_ops_7_constraints_admit_dependabots_uv() -> None:
    assert _required_version().contains(DEPENDABOT_UV)
    assert _build_backend().contains(DEPENDABOT_UV)


def test_t_ops_7_constraints_admit_the_images_uv() -> None:
    assert _required_version().contains(_image_uv())
    assert _build_backend().contains(_image_uv())
