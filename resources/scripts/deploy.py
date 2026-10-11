from __future__ import annotations

import fnmatch
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from typing import Annotated

import typer
from tqdm import tqdm

app = typer.Typer(no_args_is_help=True)

PACKAGE_NAME = "altira"

RELEASE_SETUP = """\
from __future__ import annotations

import glob
import os
from typing import Any

from Cython.Build import cythonize
from setuptools import setup
from setuptools.command.build_py import build_py


PYTHON_FILES = set(
    glob.glob(os.path.join("src", "**", "*.py"), recursive=True)
)
INIT_FILES = set(
    glob.glob(os.path.join("src", "**", "__init__.py"), recursive=True)
)

MODULES_TO_COMPILE = sorted(PYTHON_FILES - INIT_FILES)
MODULES_TO_COMPILE_SET = set(map(os.path.normpath, MODULES_TO_COMPILE))


class ReleaseBuildPy(build_py):
    \"\"\"Build package files without copying Cythonized Python sources.\"\"\"

    def build_module(
        self,
        module: str,
        module_file: str,
        package: str,
    ) -> Any:
        \"\"\"Build a Python module unless Cython provides the implementation.

        Parameters
        ----------
        module
            Module name.
        module_file
            Path to the Python source file.
        package
            Parent package name.

        Returns
        -------
        Any
            Result from the standard setuptools build process, or ``None``
            when the module is compiled by Cython.
        \"\"\"
        if os.path.normpath(module_file) in MODULES_TO_COMPILE_SET:
            return None

        return super().build_module(module, module_file, package)


setup(
    ext_modules=cythonize(
        MODULES_TO_COMPILE,
        compiler_directives={"language_level": "3"},
        nthreads=4,
    ),
    cmdclass={
        "build_py": ReleaseBuildPy,
    },
)
"""


def validate_source_root(source_root: str) -> None:
    """Validate that the supplied directory is the repository root.

    Parameters
    ----------
    source_root
        Absolute path to the source repository.

    Raises
    ------
    RuntimeError
        If required project files are missing or a root ``setup.py`` exists.
    """
    pyproject_path = os.path.join(source_root, "pyproject.toml")
    package_path = os.path.join(source_root, "src", PACKAGE_NAME)
    setup_path = os.path.join(source_root, "setup.py")

    if not os.path.isfile(pyproject_path):
        raise RuntimeError(
            f"pyproject.toml not found in source directory: {source_root}"
        )

    if not os.path.isdir(package_path):
        raise RuntimeError(f"Package directory not found: {package_path}")

    if os.path.exists(setup_path):
        raise RuntimeError(
            "Root setup.py must not exist. "
            "Cython build configuration is deployment-only."
        )


def copy_repository(source_root: str, staging_root: str) -> None:
    """Copy the repository into an isolated release staging directory.

    Parameters
    ----------
    source_root
        Repository to copy.
    staging_root
        Destination for the isolated release build.
    """
    shutil.copytree(
        source_root,
        staging_root,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv",
            ".pytest_cache",
            ".ruff_cache",
            "__pycache__",
            "*.egg-info",
            "build",
            "dist",
            "wheelhouse",
        ),
    )


def enable_cython_build(pyproject_path: str) -> None:
    """Enable Cython only inside the isolated release project.

    Parameters
    ----------
    pyproject_path
        Path to the staged ``pyproject.toml``.

    Raises
    ------
    RuntimeError
        If the expected normal build configuration cannot be found.
    """
    with open(pyproject_path, encoding="utf-8") as file:
        content = file.read()

    normal_requirements = 'requires = [\n    "setuptools>=69",\n    "wheel",\n]'
    release_requirements = 'requires = [\n    "setuptools>=69",\n    "wheel",\n    "Cython",\n]'

    if release_requirements in content:
        return

    if normal_requirements not in content:
        raise RuntimeError(
            "Unexpected [build-system].requires configuration. "
            "Expected the multiline setuptools>=69 and wheel requirements."
        )

    content = content.replace(
        normal_requirements,
        release_requirements,
        1,
    )

    with open(pyproject_path, "w", encoding="utf-8") as file:
        file.write(content)


def configure_release_manifest(manifest_path: str) -> None:
    """Ensure generated C sources cannot enter the release artifact.

    Parameters
    ----------
    manifest_path
        Path to the staged ``MANIFEST.in``.
    """
    with open(manifest_path, encoding="utf-8") as file:
        content = file.read()

    exclusion = "global-exclude *.c"

    if exclusion not in content:
        content = f"{content.rstrip()}\n{exclusion}\n"

    with open(manifest_path, "w", encoding="utf-8") as file:
        file.write(content)


def write_release_setup(staging_root: str) -> None:
    """Create the deployment-only ``setup.py`` in the staging project.

    Parameters
    ----------
    staging_root
        Isolated release source directory.
    """
    setup_path = os.path.join(staging_root, "setup.py")

    with open(setup_path, "w", encoding="utf-8") as file:
        file.write(RELEASE_SETUP)


def build_wheels(staging_root: str) -> str:
    """Build platform wheels using cibuildwheel.

    Parameters
    ----------
    staging_root
        Isolated release source directory.

    Returns
    -------
    str
        Directory containing the generated wheels.
    """
    wheelhouse = os.path.join(staging_root, "wheelhouse")

    subprocess.run(
        [
            sys.executable,
            "-m",
            "cibuildwheel",
            ".",
            "--output-dir",
            "wheelhouse",
        ],
        cwd=staging_root,
        check=True,
    )

    return wheelhouse


def verify_release_wheel(wheel_path: str) -> None:
    """Verify that a release wheel contains compiled code only.

    Parameters
    ----------
    wheel_path
        Wheel to inspect.

    Raises
    ------
    RuntimeError
        If protected Python sources, generated C sources, or no compiled
        extensions are present.
    """
    with zipfile.ZipFile(wheel_path) as archive:
        names = archive.namelist()

    python_sources = set(fnmatch.filter(names, f"{PACKAGE_NAME}/*.py"))
    init_sources = set(fnmatch.filter(names, "*/__init__.py"))
    protected_sources = python_sources - init_sources

    c_sources = set(fnmatch.filter(names, "*.c"))

    compiled_extensions = set(fnmatch.filter(names, f"{PACKAGE_NAME}/*.so"))
    compiled_extensions.update(fnmatch.filter(names, f"{PACKAGE_NAME}/*.pyd"))

    if protected_sources:
        raise RuntimeError(
            "Release wheel contains protected Python source files: "
            f"{sorted(protected_sources)}"
        )

    if c_sources:
        raise RuntimeError(
            f"Release wheel contains generated C source files: {sorted(c_sources)}"
        )

    if not compiled_extensions:
        raise RuntimeError("Release wheel contains no compiled Cython extensions.")


def publish_wheels(
    wheelhouse: str,
    output_directory: str,
) -> None:
    """Verify and copy release wheels to the requested output directory.

    Parameters
    ----------
    wheelhouse
        Temporary cibuildwheel output directory.
    output_directory
        Final directory receiving verified wheels.

    Raises
    ------
    RuntimeError
        If cibuildwheel produced no wheels.
    """
    wheel_paths = sorted(glob.glob(os.path.join(wheelhouse, "*.whl")))

    if not wheel_paths:
        raise RuntimeError("cibuildwheel produced no wheels.")

    os.makedirs(output_directory, exist_ok=True)

    for wheel_path in tqdm(
        wheel_paths,
        desc="Verifying release wheels",
        unit="wheel",
    ):
        verify_release_wheel(wheel_path)

        destination = os.path.join(
            output_directory,
            os.path.basename(wheel_path),
        )
        shutil.copy2(wheel_path, destination)


@app.command()
def main(
    src: Annotated[
        str,
        typer.Option(
            "--src",
            help="Repository root to build.",
        ),
    ],
    output_dir: Annotated[
        str,
        typer.Option(
            "--output-dir",
            help="Output directory relative to --src.",
        ),
    ] = "wheelhouse",
) -> None:
    """Build protected binary release wheels.

    Parameters
    ----------
    src
        Repository root.
    output_dir
        Directory receiving the verified binary wheels.
    """
    source_root = os.path.abspath(src)

    if os.path.isabs(output_dir):
        final_output = output_dir
    else:
        final_output = os.path.join(source_root, output_dir)

    validate_source_root(source_root)

    with tempfile.TemporaryDirectory(prefix="altira-release-") as temporary_root:
        staging_root = os.path.join(
            temporary_root,
            "repository",
        )

        copy_repository(
            source_root=source_root,
            staging_root=staging_root,
        )

        enable_cython_build(os.path.join(staging_root, "pyproject.toml"))

        configure_release_manifest(os.path.join(staging_root, "MANIFEST.in"))

        write_release_setup(staging_root)

        wheelhouse = build_wheels(staging_root)

        publish_wheels(
            wheelhouse=wheelhouse,
            output_directory=final_output,
        )

    typer.echo(f"Release wheels written to: {final_output}")


if __name__ == "__main__":
    app()
