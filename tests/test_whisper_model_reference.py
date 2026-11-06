"""Community faster-whisper models (e.g. ivrit.ai Hebrew) resolve to a plain local folder."""

import subgen_pipeline as pipeline


def test_alias_and_community_repo_download_to_plain_folder(monkeypatch, tmp_path):
    calls = []

    def fake_snapshot_download(repo_id, local_dir):
        calls.append((repo_id, local_dir))
        return local_dir

    import huggingface_hub
    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot_download)
    monkeypatch.setattr(pipeline, "MODEL_CACHE_DIR", tmp_path)
    for name in ("ivrit-he", "ivrit-ai/whisper-large-v3-turbo-ct2"):
        resolved = pipeline.resolve_faster_whisper_model_reference(name)
        assert resolved == str(tmp_path / "ivrit-ai--whisper-large-v3-turbo-ct2")
    assert {repo for repo, _ in calls} == {"ivrit-ai/whisper-large-v3-turbo-ct2"}


def test_builtin_sizes_are_not_downloaded_here(monkeypatch):
    import huggingface_hub
    monkeypatch.setattr(huggingface_hub, "snapshot_download", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no download")))
    assert pipeline.resolve_faster_whisper_model_reference("small", hub_roots=[]) == "small"
    assert pipeline.resolve_faster_whisper_model_reference("Systran/faster-whisper-small", hub_roots=[]) == "Systran/faster-whisper-small"
