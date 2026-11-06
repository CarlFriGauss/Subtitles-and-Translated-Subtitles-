"""SEC-6: subtitle filter strings must survive hostile paths and font names."""

import shutil
import subprocess

import pytest

import subgen_pipeline as pipeline

HOSTILE_DIR = "O'Brien, [clips]; take 2"
HOSTILE_SRT = "Don't stop,me.he.srt"


def test_font_name_injection_is_neutralised():
    assert pipeline.sanitize_font_name("Arial',drawtext=textfile=/etc/passwd") == "Arial"
    assert pipeline.sanitize_font_name("Arial,PrimaryColour=&H0000FF&") == "Arial"
    assert pipeline.sanitize_font_name("") == "Arial"


@pytest.mark.parametrize("name", ["Arial", "Amiri", "Noto Sans Hebrew", "DejaVu Sans-Bold", "Open_Sans 2.0"])
def test_legitimate_font_names_are_kept(name):
    assert pipeline.sanitize_font_name(name) == name


def test_validate_visual_style_sanitises_font_name():
    style = pipeline.validate_visual_style({}, {"font_name": "x',drawbox"}, {"width": 1920, "height": 1080})
    assert style["font_name"] == "Arial"


def test_filter_has_no_unescaped_quote_or_separator_from_input():
    vf = pipeline.build_subtitles_filter(
        f"C:\\{HOSTILE_DIR}\\{HOSTILE_SRT}", "1920x1080", force_style=[("FontSize", 20)]
    )
    # Every quote, comma, semicolon and bracket coming from the path is escaped.
    stripped = vf.replace("\\\\", "").replace("\\'", "").replace("\\,", "").replace("\\;", "")
    stripped = stripped.replace("\\[", "").replace("\\]", "")
    assert "'" not in stripped and ";" not in stripped and "[" not in stripped
    assert stripped.count(",") == 0


def _render_gray_frame(cwd, vf):
    result = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=320x240:d=1",
            "-vf", vf, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-",
        ],
        cwd=cwd, capture_output=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return result.stdout


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
@pytest.mark.parametrize("relative", [False, True])
def test_real_burn_with_hostile_path(tmp_path, relative):
    folder = tmp_path / HOSTILE_DIR
    folder.mkdir()
    srt = folder / HOSTILE_SRT
    srt.write_text("1\n00:00:00,000 --> 00:00:05,000\nHELLO\n", encoding="utf-8")
    srt_argument = srt.relative_to(tmp_path).as_posix() if relative else str(srt)
    vf = pipeline.build_subtitles_filter(
        srt_argument, "320x240",
        force_style=[("FontName", pipeline.sanitize_font_name("Arial")), ("FontSize", 40),
                     ("PrimaryColour", "&HFFFFFF&")],
    )
    frame = _render_gray_frame(tmp_path, vf)
    assert len(frame) == 320 * 240
    assert max(frame) > 128, "subtitle text was not drawn"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_real_burn_with_bundled_font_dir(tmp_path):
    srt = tmp_path / "a.ar.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:05,000\nمرحبا\n", encoding="utf-8")
    vf = pipeline.build_subtitles_filter(
        str(srt), "320x240",
        force_style=[("FontName", "Amiri"), ("FontSize", 40)],
        fonts_dir=pipeline.bundled_subtitle_fonts_dir(),
    )
    frame = _render_gray_frame(tmp_path, vf)
    assert max(frame) > 128
