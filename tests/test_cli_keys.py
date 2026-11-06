"""BUG-1: API keys saved to the OS keyring must be available to the CLI."""

import sys
import types

import pytest

import subgen_cli


class FakeKeyring(types.ModuleType):
    def __init__(self):
        super().__init__("keyring")
        self.store = {}

    def set_password(self, service, key, value):
        self.store[(service, key)] = value

    def get_password(self, service, key):
        return self.store.get((service, key))


@pytest.fixture()
def fake_keyring(monkeypatch, tmp_path):
    keyring = FakeKeyring()
    monkeypatch.setitem(sys.modules, "keyring", keyring)
    monkeypatch.setattr(subgen_cli, "ENV_PATH", tmp_path / ".env")
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "XAI_API_KEY", "COHERE_API_KEY", "OPENAI_API_KEY_WORK"):
        monkeypatch.delenv(key, raising=False)
    return keyring


def test_keys_survive_setup_then_new_process(fake_keyring, monkeypatch):
    subgen_cli.write_env_values({"OPENAI_API_KEY": "sk-test-000"})
    # setup moved the key to the keyring and left only a comment in .env
    assert "sk-test-000" not in subgen_cli.ENV_PATH.read_text(encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)  # simulate the next CLI run
    subgen_cli.load_api_keys()
    import os
    assert os.environ["OPENAI_API_KEY"] == "sk-test-000"


def test_non_default_providers_are_read_from_keyring(fake_keyring, monkeypatch):
    fake_keyring.set_password("SubGen", "XAI_API_KEY", "xai-test")
    fake_keyring.set_password("SubGen", "COHERE_API_KEY", "cohere-test")
    values = subgen_cli.read_env_values()
    assert values.get("XAI_API_KEY") == "xai-test"
    assert values.get("COHERE_API_KEY") == "cohere-test"


def test_openai_profile_keys_are_included():
    config = {"openai_profiles": {"work": {"label": "work", "env_key": "OPENAI_API_KEY_WORK"}}}
    assert "OPENAI_API_KEY_WORK" in subgen_cli.credential_env_keys(config)


def test_existing_environment_wins(fake_keyring, monkeypatch):
    fake_keyring.set_password("SubGen", "OPENAI_API_KEY", "from-keyring")
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    subgen_cli.load_api_keys()
    import os
    assert os.environ["OPENAI_API_KEY"] == "from-env"


def test_plaintext_fallback_strips_newlines(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "keyring", None)  # import keyring -> ImportError
    monkeypatch.setattr(subgen_cli, "ENV_PATH", tmp_path / ".env")
    subgen_cli.write_env_values({"OPENAI_API_KEY": "sk-1\nEVIL_KEY=1"})
    lines = [line for line in (tmp_path / ".env").read_text(encoding="utf-8").splitlines() if not line.startswith("#")]
    assert lines == ["OPENAI_API_KEY=sk-1EVIL_KEY=1"]


def test_dotenv_with_bom(tmp_path, monkeypatch):
    import subgen_pipeline
    env = tmp_path / ".env"
    env.write_bytes("﻿BOM_TEST_KEY=abc\n".encode("utf-8"))
    monkeypatch.delenv("BOM_TEST_KEY", raising=False)
    subgen_pipeline.load_dotenv(env)
    import os
    assert os.environ.get("BOM_TEST_KEY") == "abc"
    monkeypatch.delenv("BOM_TEST_KEY", raising=False)
