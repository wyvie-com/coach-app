"""The trivial test the brief asks for: the package imports and names itself."""

from importlib.metadata import version

import coach


def test_package_version_matches_its_metadata() -> None:
    # The package and pyproject.toml each state the version; this keeps them in step.
    assert coach.__version__ == version("coach")
