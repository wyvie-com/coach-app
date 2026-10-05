"""The trivial test the brief asks for: the package imports and names itself."""

import coach


def test_package_has_version() -> None:
    assert coach.__version__ == "0.0.1"
