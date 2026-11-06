"""BUG-9: settings and batch progress must survive crashes and bad files."""

import json
import os

import pytest

import subgen_cli
import subgen_utils


def test_atomic_write_keeps_old_content_when_replace_fails(tmp_path, monkeypatch):
    target = tmp_path / "config.json"
    target.write_text('{"old": true}', encoding="utf-8")

    def crash(*args, **kwargs):
        raise OSError("power cut")

    monkeypatch.setattr(subgen_utils.os, "replace", crash)
    with pytest.raises(OSError):
        subgen_utils.atomic_write_text(target, '{"new": true}')
    assert json.loads(target.read_text(encoding="utf-8")) == {"old": True}


def test_atomic_write_replaces_content(tmp_path):
    target = tmp_path / "nested" / "state.json"
    subgen_utils.atomic_write_text(target, "שלום")
    assert target.read_text(encoding="utf-8") == "שלום"
    assert [p.name for p in target.parent.iterdir()] == ["state.json"]


def test_corrupt_config_is_preserved_not_discarded(tmp_path, monkeypatch):
    config_path = tmp_path / "subgen_config.json"
    config_path.write_text('{"output_dir": "D:/videos", ', encoding="utf-8")  # truncated
    monkeypatch.setattr(subgen_cli, "CONFIG_PATH", config_path)
    config = subgen_cli.load_config()
    assert config == subgen_cli.default_config() or config.get("setup_complete") is not True
    backups = list(tmp_path.glob("subgen_config.json.corrupt-*"))
    assert len(backups) == 1
    assert '"D:/videos"' in backups[0].read_text(encoding="utf-8")


def test_corrupt_batch_state_is_preserved(tmp_path, monkeypatch):
    path = subgen_cli.batch_state_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert subgen_cli.load_batch_state(tmp_path) is None
    assert list(path.parent.glob(f"{path.name}.corrupt-*"))


def test_save_config_round_trip(tmp_path, monkeypatch):
    config_path = tmp_path / "subgen_config.json"
    monkeypatch.setattr(subgen_cli, "CONFIG_PATH", config_path)
    config = subgen_cli.default_config()
    config["llm_model"] = "gpt-5.2"
    config.setdefault("provider_models", {}).setdefault("openai", {})["translation"] = "gpt-5.2"
    subgen_cli.save_config(config)
    reloaded = subgen_cli.load_config()
    assert reloaded["llm_model"] == "gpt-5.2", "explicit model choices must not be downgraded"
    assert reloaded["provider_models"]["openai"]["translation"] == "gpt-5.2"
