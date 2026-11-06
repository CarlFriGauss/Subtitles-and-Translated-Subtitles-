"""Environment and configuration hygiene for subprocesses run on behalf of users.

The cloud API and worker hold platform secrets in their environment
(SUBGEN_CREDENTIAL_MASTER_KEY, SUBGEN_CLOUD_DATABASE_URL, storage keys). The
pipeline subprocess runs with a user-supplied pipeline_config, and the provider
layer reads ``os.environ[provider["env_key"]]`` and sends it as a Bearer token to
``provider["base_url"]``. A user who could choose ``env_key`` and ``base_url``
(through ``custom_providers``) could therefore make the pipeline post any
environment variable to a server they control.

Two independent defences live here:

* ``subprocess_environment`` builds a child environment from an allowlist, so
  platform secrets are never present in a user-driven subprocess.
* ``find_forbidden_config_key`` / ``sanitize_pipeline_config`` reject or strip
  configuration keys that redirect credentials or endpoints.
"""

import os

# Variables a Python/ffmpeg/torch subprocess legitimately needs. Compared
# case-insensitively because Windows environment names are case-insensitive.
SAFE_ENV_KEYS = frozenset(
    name.upper()
    for name in (
        # process basics
        "PATH", "PATHEXT", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LANGUAGE",
        "LC_ALL", "LC_CTYPE", "TZ", "TERM",
        "TMPDIR", "TEMP", "TMP",
        # Windows basics (local development of the cloud edition)
        "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "USERPROFILE",
        "LOCALAPPDATA", "APPDATA", "PROGRAMDATA", "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
        # Python
        "PYTHONPATH", "PYTHONHOME", "PYTHONIOENCODING", "PYTHONUTF8",
        "PYTHONUNBUFFERED", "PYTHONDONTWRITEBYTECODE", "VIRTUAL_ENV",
        # TLS trust stores
        "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
        # model caches and accelerators
        "HF_HOME", "HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE", "TRANSFORMERS_CACHE",
        "TORCH_HOME", "XDG_CACHE_HOME", "CUDA_VISIBLE_DEVICES",
        "NVIDIA_VISIBLE_DEVICES", "NVIDIA_DRIVER_CAPABILITIES", "LD_LIBRARY_PATH",
        "OMP_NUM_THREADS", "MKL_NUM_THREADS",
    )
)

FORBIDDEN_CONFIG_KEYS = frozenset({"custom_providers", "base_url"})


def subprocess_environment(extra=None):
    """Return a minimal environment for a user-driven subprocess.

    Only allowlisted variables are copied from ``os.environ``; ``extra`` (for
    example SUBGEN_DATA_DIR and the user's own decrypted provider key) is added
    on top. Nothing named SUBGEN_* is inherited.
    """
    env = {key: value for key, value in os.environ.items() if key.upper() in SAFE_ENV_KEYS}
    env.update({str(key): str(value) for key, value in (extra or {}).items()})
    return env


def is_forbidden_config_key(key):
    normalized = str(key).strip().lower()
    return normalized in FORBIDDEN_CONFIG_KEYS or normalized.endswith("env_key")


def find_forbidden_config_key(value, path="config"):
    """Return the dotted path of the first forbidden key in ``value``, or None."""
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if is_forbidden_config_key(key):
                return child_path
            found = find_forbidden_config_key(child, child_path)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_forbidden_config_key(child, path)
            if found:
                return found
    return None


def sanitize_pipeline_config(value):
    """Return a deep copy of ``value`` without forbidden keys.

    Used by the worker as a second line of defence for jobs that were queued
    before the API started rejecting these keys.
    """
    if isinstance(value, dict):
        return {
            key: sanitize_pipeline_config(child)
            for key, child in value.items()
            if not is_forbidden_config_key(key)
        }
    if isinstance(value, list):
        return [sanitize_pipeline_config(child) for child in value]
    return value
