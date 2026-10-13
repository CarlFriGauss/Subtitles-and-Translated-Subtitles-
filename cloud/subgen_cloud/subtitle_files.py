"""Publish edited subtitle downloads alongside the durable cloud review."""
import hashlib
import json
import tempfile
from pathlib import Path

from sqlalchemy import select

from subgen_editor import review_subtitle_files
from .db import Artifact


def save_subtitle_artifacts(session, storage, job, review):
    base = Path(job.video.original_name).stem
    source = review.get("source_language") or "source"
    target = review.get("target_language") or source
    files = review_subtitle_files(review, base)
    files[f"{base}.review.json"] = json.dumps(review, ensure_ascii=False, indent=2).encode("utf-8")
    with tempfile.TemporaryDirectory(prefix="subgen-edited-subtitles-") as temporary:
        for name, content in files.items():
            if name.endswith(".review.json"):
                kind, language, mime = "review_manifest", None, "application/json"
            elif name.endswith(".api_transcript.txt"):
                kind, language, mime = "api_transcript", source, "text/plain; charset=utf-8"
            else:
                language = source if name.endswith((f".{source}.srt", f".{source}.txt")) else target
                role = "source" if language == source else "target"
                kind = f"{role}_{'srt' if name.endswith('.srt') else 'text'}"
                mime = "application/x-subrip" if name.endswith(".srt") else "text/plain; charset=utf-8"
            digest = hashlib.sha256(content).hexdigest()
            key = f"users/{job.user_id}/videos/{job.video_id}/jobs/{job.id}/edited/{digest}/{name}"
            path = Path(temporary) / name
            path.write_bytes(content)
            storage.upload_file(path, key, mime)
            artifact = session.scalar(select(Artifact).where(
                Artifact.job_id == job.id, Artifact.user_id == job.user_id, Artifact.kind == kind,
            ).order_by(Artifact.created_at.desc()))
            if artifact is None:
                artifact = Artifact(user_id=job.user_id, video_id=job.video_id, job_id=job.id, kind=kind)
                session.add(artifact)
            artifact.language = language
            artifact.object_key = key
            artifact.sha256 = digest
            artifact.provenance = {"review_revision_hash": review.get("revision_hash"), "editor_saved": True}
