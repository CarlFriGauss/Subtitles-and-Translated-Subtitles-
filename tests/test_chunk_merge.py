"""BUG-5: speech at audio-chunk boundaries must appear exactly once."""

import subgen_pipeline as pipeline


def group(index, start, end, *segments, granularity=None):
    items = []
    for seg_start, seg_end, text in segments:
        item = {"start": seg_start, "end": seg_end, "text": text}
        if granularity:
            item["_granularity"] = granularity
        items.append(item)
    return {"index": index, "start": start, "end": end, "segments": items}


def merged_text(groups, overlap=8):
    text, segments, info = pipeline.merge_timed_transcript_segments(groups, overlap_seconds=overlap)
    return text, segments, info


def test_sentence_cut_by_chunk_boundary_is_not_duplicated():
    # Chunk 1 audio ends at 180 mid-sentence; chunk 2 starts at 172 (8 s overlap).
    groups = [
        group(1, 0, 180, (170.0, 172.0, "Hello there."), (176.0, 180.0, "we went to the")),
        group(2, 172, 360, (172.0, 175.0, "there."), (176.2, 182.5, "we went to the store")),
    ]
    text, segments, info = merged_text(groups)
    assert text == "Hello there. we went to the store"
    assert info[0]["boundary_text_dedupes"][0]["removed_words"] == 4


def test_partial_overlap_keeps_the_unrepeated_words():
    groups = [
        group(1, 0, 180, (174.0, 180.0, "I said we went to the")),
        group(2, 172, 360, (177.0, 182.5, "we went to the store")),
    ]
    text, segments, _ = merged_text(groups)
    assert text == "I said we went to the store"
    assert segments[0]["text"] == "I said"
    assert segments[0]["end"] <= segments[1]["start"]


def test_unrelated_neighbouring_segments_are_untouched():
    groups = [
        group(1, 0, 180, (176.0, 180.0, "the end of one thought")),
        group(2, 172, 360, (178.0, 183.0, "a completely new sentence")),
    ]
    text, _, _ = merged_text(groups)
    assert text == "the end of one thought a completely new sentence"


def test_single_shared_word_is_not_treated_as_a_repeat():
    groups = [
        group(1, 0, 180, (176.0, 180.0, "look at the")),
        group(2, 172, 360, (179.0, 183.0, "the dog runs")),
    ]
    text, _, _ = merged_text(groups)
    assert text == "look at the the dog runs"


def test_context_retry_does_not_leak_into_the_next_chunk():
    # Chunk 2 was re-transcribed with 6 s of extra context on both sides,
    # so it returned speech up to 366 s; chunk 3 covers 352-540 itself.
    groups = [
        group(1, 0, 180, (0.0, 5.0, "intro")),
        group(2, 172, 360, (180.5, 185.0, "middle part"), (361.0, 365.0, "late words")),
        group(3, 352, 540, (361.0, 365.0, "late words"), (370.0, 372.0, "end")),
    ]
    text, _, info = merged_text(groups)
    assert text.count("late words") == 1
    assert info[0]["segments_beyond_chunk_end"] == 1


def test_last_chunk_keeps_everything():
    groups = [group(1, 0, 60, (0.0, 2.0, "a"), (58.0, 61.0, "tail after nominal end"))]
    text, _, _ = merged_text(groups)
    assert "tail after nominal end" in text


def test_word_granularity_path_unchanged():
    groups = [
        group(1, 0, 180, (179.0, 180.0, "stor"), granularity="word"),
        group(2, 172, 360, (179.0, 180.4, "store"), granularity="word"),
    ]
    text, _, _ = merged_text(groups)
    assert text == "store"
