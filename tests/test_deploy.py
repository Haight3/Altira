"""Release staging and protected wheel regression checks.

Copyright (C) 2026
"""

import os
import shutil
import tomllib
import zipfile

import pytest

from resources.scripts.deploy import enable_cython_build, validate_source_root, verify_release_wheel


def test_validate_repository_source() -> None:
    source_root = os.path.dirname(os.path.dirname(__file__))
    validate_source_root(source_root)


def test_package_dependencies_allow_pypi_publication() -> None:
    source_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pyproject.toml")
    with open(source_path, "rb") as file:
        project = tomllib.load(file)["project"]
    dependencies = list(project["dependencies"])
    for extra in project["optional-dependencies"].values():
        dependencies.extend(extra)
    assert all("@" not in requirement for requirement in dependencies)


def test_enable_cython_in_staged_project(tmp_path: os.PathLike[str]) -> None:
    source_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pyproject.toml")
    staged_path = os.path.join(tmp_path, "pyproject.toml")
    shutil.copy2(source_path, staged_path)
    with open(source_path, "rb") as file:
        original = tomllib.load(file)

    enable_cython_build(staged_path)
    enable_cython_build(staged_path)

    with open(staged_path, "rb") as file:
        staged = tomllib.load(file)
    assert staged["build-system"]["requires"] == [*original["build-system"]["requires"], "Cython"]
    staged["build-system"]["requires"].remove("Cython")
    assert staged == original
    with open(source_path, "rb") as file:
        assert tomllib.load(file) == original


@pytest.mark.parametrize("extension", ["so", "pyd"])
def test_accept_compiled_altira_wheel(tmp_path: os.PathLike[str], extension: str) -> None:
    wheel_path = os.path.join(tmp_path, "altira.whl")
    with zipfile.ZipFile(wheel_path, "w") as archive:
        archive.writestr("altira/__init__.py", "")
        archive.writestr(f"altira/cli.{extension}", b"compiled extension")
    verify_release_wheel(wheel_path)


@pytest.mark.parametrize("source", ["altira/cli.py", "altira/nested/module.py"])
def test_reject_protected_python_sources(tmp_path: os.PathLike[str], source: str) -> None:
    wheel_path = os.path.join(tmp_path, "altira.whl")
    with zipfile.ZipFile(wheel_path, "w") as archive:
        archive.writestr("altira/cli.so", b"compiled extension")
        archive.writestr(source, "")
    with pytest.raises(RuntimeError, match="protected Python source files"):
        verify_release_wheel(wheel_path)
