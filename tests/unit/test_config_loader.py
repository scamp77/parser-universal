"""Unit tests for config_loader (Phase 4 YAML declarative pipeline).

We test the schema validator without spinning up a real pipeline.
"""

import pytest

from parser_universal.config_loader import load_config, validate_config


def test_load_config_returns_raw_dict(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("adapter: gpx\nlocator: foo.gpx\n")
    d = load_config(cfg)
    assert d["adapter"] == "gpx"
    assert d["locator"] == "foo.gpx"


def test_load_config_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yaml")


def test_validate_minimal():
    cfg = validate_config({"adapter": "gpx", "locator": "foo.gpx"})
    assert cfg.adapter == "gpx"
    assert cfg.all_locators() == ["foo.gpx"]
    assert cfg.sink.type == "dryrun"
    assert cfg.fetcher.persistent is True
    assert cfg.parallel.workers == 1


def test_validate_locators_list():
    cfg = validate_config(
        {"adapter": "url", "locators": ["a", "b", "c"]}
    )
    assert cfg.all_locators() == ["a", "b", "c"]


def test_validate_raises_on_missing_adapter():
    with pytest.raises(ValueError, match="adapter"):
        validate_config({"locator": "foo"})


def test_validate_raises_on_non_dict():
    with pytest.raises(ValueError, match="mapping"):
        validate_config("not a dict")


def test_validate_full_pipeline():
    raw = {
        "adapter": "url",
        "locator": "https://example.com/maps",
        "sink": {"type": "postgres", "table": "my_entities"},
        "enrichers": ["brouter"],
        "failure_sink": True,
        "daily_log": True,
        "fetcher": {
            "persistent": True,
            "strategies": ["httpx_persistent"],
        },
        "rate_limiter": {"rate_per_sec": 5.0, "burst": 8},
        "parallel": {"workers": 4, "batch_size": 16},
        "source_name": "url_test",
    }
    cfg = validate_config(raw)
    assert cfg.adapter == "url"
    assert cfg.sink.type == "postgres"
    assert cfg.sink.table == "my_entities"
    assert cfg.enrichers == ["brouter"]
    assert cfg.failure_sink is True
    assert cfg.daily_log is True
    assert cfg.rate_limiter.rate_per_sec == 5.0
    assert cfg.rate_limiter.burst == 8
    assert cfg.parallel.workers == 4
    assert cfg.parallel.batch_size == 16
    assert cfg.source_name == "url_test"


def test_validate_rejects_non_string_adapter():
    with pytest.raises(ValueError):
        validate_config({"adapter": 123})


def test_validate_rejects_non_list_locators():
    with pytest.raises(ValueError, match="locators"):
        validate_config({"adapter": "gpx", "locators": "foo,bar"})


def test_validate_no_locators_allowed_with_enrichers_only():
    """locators/locator may be empty if user intends refill later."""
    cfg = validate_config({"adapter": "overpass", "enrichers": ["brouter"]})
    assert cfg.all_locators() == []
