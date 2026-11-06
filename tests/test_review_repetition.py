"""Repetition detection must not flag cues that contain no words."""

import subgen_review


def cues(*texts):
    return [{"id": f"c{i}", "start": float(i), "end": float(i) + 1, "text": text} for i, text in enumerate(texts)]


def test_music_and_ellipsis_cues_are_not_repetitions():
    report = subgen_review.repetition_anomaly_report("vid", cues("♪♪", "♪♪", "...", "♪"))
    assert report["runs"] == []
    assert report["issues"] == []


def test_real_repeated_speech_is_still_detected():
    report = subgen_review.repetition_anomaly_report("vid", cues("thank you very much", "thank you very much", "goodbye"))
    assert report["runs"]
    assert report["issues"]
