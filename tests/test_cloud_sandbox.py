"""SEC-4: user-driven cloud subprocesses must never see platform secrets."""

import pytest

from subgen_cloud.sandbox import (
    find_forbidden_config_key,
    sanitize_pipeline_config,
    subprocess_environment,
)

ATTACK_CONFIG = {
    "translation_provider": "x",
    "custom_providers": {
        "x": {"env_key": "SUBGEN_CREDENTIAL_MASTER_KEY", "base_url": "https://attacker.example"},
    },
}

PLATFORM_SECRETS = {
    "SUBGEN_CREDENTIAL_MASTER_KEY": "master",
    "SUBGEN_CLOUD_DATABASE_URL": "postgresql://user:pw@db/x",
    "SUBGEN_STORAGE_SECRET_KEY": "r2-secret",
    "SUBGEN_STORAGE_ACCESS_KEY": "r2-access",
    "SUBGEN_AUTH_PUBLIC_KEY": "anon",
    "AWS_SECRET_ACCESS_KEY": "aws",
}


def test_subprocess_environment_drops_platform_secrets(monkeypatch):
    for key, value in PLATFORM_SECRETS.items():
        monkeypatch.setenv(key, value)
    env = subprocess_environment({"SUBGEN_DATA_DIR": "/tmp/job"})
    for key in PLATFORM_SECRETS:
        assert key not in env
    assert env["SUBGEN_DATA_DIR"] == "/tmp/job"
    assert "PATH" in {k.upper() for k in env}


def test_subprocess_environment_keeps_explicit_provider_key(monkeypatch):
    env = subprocess_environment({"OPENAI_API_KEY": "sk-test-000"})
    assert env["OPENAI_API_KEY"] == "sk-test-000"


def test_attack_config_is_detected():
    assert find_forbidden_config_key(ATTACK_CONFIG, "pipeline_config") == "pipeline_config.custom_providers"


@pytest.mark.parametrize("config", [
    {"translation_env_key": "SUBGEN_CLOUD_DATABASE_URL"},
    {"nested": {"base_url": "https://attacker.example"}},
    {"list": [{"openai_env_key": "X"}]},
])
def test_other_redirect_keys_are_detected(config):
    assert find_forbidden_config_key(config) is not None


def test_normal_config_is_allowed():
    config = {"translation_provider": "openai", "translation_model": "gpt-4o-mini", "credential_profiles": {"openai": "default"}}
    assert find_forbidden_config_key(config) is None
    assert sanitize_pipeline_config(config) == config


def test_sanitize_strips_redirect_keys_for_already_queued_jobs():
    cleaned = sanitize_pipeline_config(ATTACK_CONFIG)
    assert cleaned == {"translation_provider": "x"}


def test_api_rejects_attack_config():
    api = pytest.importorskip("subgen_cloud.api", reason="cloud extras (sqlalchemy, jwt, boto3) not installed")
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        api.reject_embedded_secrets(ATTACK_CONFIG, "pipeline_config")
    assert excinfo.value.status_code == 400
