import pytest

from QQBot import main


def test_python_version_follows_installed_pythonnet_metadata(monkeypatch):
    monkeypatch.setattr(main, "metadata", lambda _: {"Requires-Python": ">=3.11,<3.17"})
    main.check_python_version("3.16.1")
    with pytest.raises(RuntimeError, match="pythonnet"):
        main.check_python_version("3.17.0")
    with pytest.raises(RuntimeError, match="3.14"):
        main.check_python_version("3.13.1")


def test_python_version_fails_clearly_when_metadata_is_missing(monkeypatch):
    monkeypatch.setattr(main, "metadata", lambda _: {})
    with pytest.raises(RuntimeError, match="无法读取 pythonnet"):
        main.check_python_version("3.15.0")
