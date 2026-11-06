"""BUG-4: cache_action="reburn" must re-render, and manual style detection must
not be fooled by keys the pipeline adds itself."""

import shutil
import subprocess

import pytest

import subgen_pipeline as pipeline

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not installed",
)


@pytest.fixture()
def tiny_video(tmp_path):
    video = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=320x240:d=1",
         "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-shortest",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video)],
        check=True, timeout=120,
    )
    srt = tmp_path / "clip.en.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHELLO\n", encoding="utf-8")
    return video, srt


@pytest.fixture()
def burn_calls(monkeypatch):
    calls = []
    real = pipeline.burn_subtitles

    def counting_burn(*args, **kwargs):
        calls.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(pipeline, "burn_subtitles", counting_burn)
    return calls


def run(video, srt, out, **kwargs):
    # The approval gate is covered elsewhere; here only the cache/burn decision
    # is under test, so the gate is switched off for this run.
    config = {**pipeline.CONFIG, "review_before_burn": False}
    return pipeline.main(str(video), srt_path_arg=str(srt), target_language="en",
                         no_burn=False, output_dir=str(out), pipeline_config=config, **kwargs)


def test_reburn_renders_even_when_output_is_current(tiny_video, tmp_path, burn_calls, monkeypatch):
    video, srt = tiny_video
    # Isolate the cache decision from the style comparison: the stored style
    # matches the (empty) requested style, so only cache_action decides.
    monkeypatch.setattr(pipeline, "get_burned_style", lambda video_hash: {})
    out = tmp_path / "out"
    run(video, srt, out, cache_action="reuse_all")
    assert len(burn_calls) == 1
    run(video, srt, out, cache_action="reuse_all")
    assert len(burn_calls) == 1, "reuse_all should skip an up-to-date output"
    run(video, srt, out, cache_action="reburn")
    assert len(burn_calls) == 2, "reburn must render again"


def test_manual_style_flag_follows_the_caller(tiny_video, tmp_path, burn_calls):
    video, srt = tiny_video
    run(video, srt, tmp_path / "a", cache_action="reburn", style_config=None)
    run(video, srt, tmp_path / "b", cache_action="reburn", style_config={"font_size": 30})
    assert burn_calls[0]["manual_style"] is False
    assert burn_calls[1]["manual_style"] is True
