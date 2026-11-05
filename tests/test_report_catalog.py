from app.core.report_catalog import names, rename
import pytest


def test_persistence_direction_and_clear(tmp_path):
    path = tmp_path / "catalog.sqlite3"
    assert names(path, "visa") == {}
    rename(path, "visa", "post", "fixture-code", "Тестовый креатив")
    assert names(path, "visa") == {("post", "fixture-code"): "Тестовый креатив"}
    assert names(path, "tours") == {}
    rename(path, "visa", "post", "fixture-code", "")
    assert names(path, "visa") == {}


def test_invalid_input_does_not_create_storage(tmp_path):
    path = tmp_path / "catalog.sqlite3"
    with pytest.raises(ValueError):
        rename(path, "other", "post", "code", "label")
    assert not path.exists()
