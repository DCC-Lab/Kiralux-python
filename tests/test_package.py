"""Package surface: public names and the version fallback."""
import importlib
import importlib.metadata

import kiralux


def test_every_public_name_exists():
    for name in kiralux.__all__:
        assert hasattr(kiralux, name), name


def test_version_is_a_string():
    assert isinstance(kiralux.__version__, str)


def test_version_falls_back_when_the_distribution_is_not_installed(monkeypatch):
    def missing(name):
        raise importlib.metadata.PackageNotFoundError(name)
    monkeypatch.setattr(importlib.metadata, "version", missing)
    try:
        assert importlib.reload(kiralux).__version__ == "0+unknown"
    finally:
        monkeypatch.undo()
        importlib.reload(kiralux)
