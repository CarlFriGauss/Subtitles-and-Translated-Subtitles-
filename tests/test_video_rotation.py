"""BUG-8: portrait phone videos must be measured as displayed."""

import shutil
import subprocess

import pytest

import subgen_pipeline as pipeline


@pytest.mark.parametrize("stream,expected", [
    ({"width": 1920, "height": 1080, "side_data_list": [{"rotation": -90}]}, (1080, 1920)),
    ({"width": 1920, "height": 1080, "side_data_list": [{"rotation": 90}]}, (1080, 1920)),
    ({"width": 1920, "height": 1080, "side_data_list": [{"rotation": 180}]}, (1920, 1080)),
    ({"width": 1920, "height": 1080, "tags": {"rotate": "270"}}, (1080, 1920)),
    ({"width": 1920, "height": 1080}, (1920, 1080)),
    ({"width": 1920, "height": 1080, "side_data_list": [{"side_data_type": "other"}]}, (1920, 1080)),
])
def test_display_dimensions(stream, expected):
    assert pipeline.display_dimensions(stream) == expected


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg not installed")
def test_rotated_phone_clip_is_vertical(tmp_path):
    base = tmp_path / "base.mp4"
    rotated = tmp_path / "rotated.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=320x240:d=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(base)], check=True, timeout=120)
    subprocess.run(["ffmpeg", "-v", "error", "-display_rotation", "90", "-i", str(base),
                    "-c", "copy", str(rotated)], check=True, timeout=120)
    metadata = pipeline.probe_video_metadata(rotated)
    assert (metadata["width"], metadata["height"]) == (240, 320)
    assert metadata["orientation"] == "vertical_short_form"
