"""BUG-3: right-to-left subtitles must be burned with RTL base direction."""

import shutil
import subprocess

import pytest

import subgen_pipeline as pipeline

RLE, PDF = "‫", "‬"
HEBREW_SRT = "1\n00:00:00,000 --> 00:00:01,000\nשלום, מה שלומך?\n"


@pytest.mark.parametrize("code,expected", [
    ("he", True), ("he-IL", True), ("iw", True), ("ar", True), ("fa", True), ("yi", True),
    ("en", False), ("ru", False), (None, False), ("", False),
])
def test_rtl_language_detection(code, expected):
    assert pipeline.is_rtl_subtitle_language(code) is expected


def test_only_text_lines_are_marked():
    srt = "1\n00:00:00,000 --> 00:00:01,000\nשלום?\nשורה 2\n\n2\n00:00:01,000 --> 00:00:02,000\n2024\n"
    marked = pipeline.rtl_burn_srt_text(srt)
    blocks = marked.strip().split("\n\n")
    assert blocks[0].splitlines()[:2] == ["1", "00:00:00,000 --> 00:00:01,000"]
    assert blocks[0].splitlines()[2:] == [f"{RLE}שלום?{PDF}", f"{RLE}שורה 2{PDF}"]
    assert blocks[1].splitlines()[2] == f"{RLE}2024{PDF}"


def test_marking_is_idempotent_and_strips_bom():
    once = pipeline.rtl_burn_srt_text("﻿" + HEBREW_SRT)
    assert not once.startswith("﻿")
    assert pipeline.rtl_burn_srt_text(once) == once


def test_burn_uses_marked_copy_and_leaves_original_untouched(tmp_path, monkeypatch):
    srt = tmp_path / "clip.he.srt"
    srt.write_text(HEBREW_SRT, encoding="utf-8")
    seen = {}

    def fake_burn(video, srt_path, output, lang_code, style_config, manual_style):
        seen["text"] = open(srt_path, encoding="utf-8").read()
        seen["path"] = srt_path
        return {}

    monkeypatch.setattr(pipeline, "_burn_subtitles_file", fake_burn)
    pipeline.burn_subtitles("v.mp4", str(srt), "o.mp4", lang_code="he")
    assert f"{RLE}שלום, מה שלומך?{PDF}" in seen["text"]
    assert srt.read_text(encoding="utf-8") == HEBREW_SRT
    assert not seen["path"].exists(), "temporary burn copy must be removed"


def test_ltr_burn_uses_original_file(tmp_path, monkeypatch):
    srt = tmp_path / "clip.en.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello?\n", encoding="utf-8")
    seen = {}
    monkeypatch.setattr(pipeline, "_burn_subtitles_file",
                        lambda video, srt_path, *rest: seen.setdefault("path", srt_path))
    pipeline.burn_subtitles("v.mp4", str(srt), "o.mp4", lang_code="en")
    assert str(seen["path"]) == str(srt)


def _frame(tmp_path, name, text):
    """Render one right-aligned line (Alignment=3) so the right edge is fixed."""
    path = tmp_path / f"{name}.srt"
    path.write_text(f"1\n00:00:00,000 --> 00:00:01,000\n{text}\n", encoding="utf-8")
    vf = pipeline.build_subtitles_filter(
        path.name, "480x120",
        force_style=[("FontName", "Arial"), ("FontSize", 36), ("Alignment", 3), ("MarginR", 20)],
    )
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=480x120:d=1",
         "-vf", vf, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        cwd=tmp_path, capture_output=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _right_strip(frame, width=480, strip=80):
    rows = len(frame) // width
    return bytes(frame[y * width + x] for y in range(rows) for x in range(width - strip, width))


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_question_mark_renders_on_the_left(tmp_path):
    """Right-aligned: in correct RTL layout the sentence starts at the right
    edge, so appending '?' must not change the right-hand strip; it must
    appear on the left. Without marks the '?' lands at the right edge."""
    base = _frame(tmp_path, "base", pipeline.embed_rtl_line("שלום, מה שלומך"))
    if max(base) <= 128:
        pytest.skip("no font with Hebrew glyphs available to libass")
    marked = _frame(tmp_path, "marked", pipeline.embed_rtl_line("שלום, מה שלומך?"))
    plain = _frame(tmp_path, "plain", "שלום, מה שלומך?")
    assert _right_strip(marked) == _right_strip(base)
    assert _right_strip(plain) != _right_strip(base)
