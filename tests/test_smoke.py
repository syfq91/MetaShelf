"""Smoke tests for package setup."""

import metashelf


def test_version_defined() -> None:
    assert metashelf.__version__ == "0.1.0"
