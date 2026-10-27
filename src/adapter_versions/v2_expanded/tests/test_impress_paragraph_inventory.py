"""Native paragraph identity and empty state survive bounded presentation reads."""
from copy import deepcopy

from integrations.lite_agent.adapter_results import compact_presentation_hint_for_model


def test_inventory_distinguishes_empty_whitespace_and_nonempty_without_changing_text():
    texts = ["Heading", " \t", "", "Last sentence", ""]
    observation = {"slide_count": 9, "inspected_slides": [6], "slides": [{
        "slide": 6, "text_shapes": [{"index": 2, "path": [2],
        "paragraphs": [{"index": i, "text": text} for i, text in enumerate(texts)]}],
    }]}
    original = deepcopy(observation)
    result = compact_presentation_hint_for_model(observation)
    assert result["paragraph_inventory"] == [[6, [2], 5, 0, [[0, 7], [1, 2], [2, 0], [3, 13], [4, 0]]]]
    assert result["paragraph_inventory_count"] == 1
    assert observation == original
    assert result["slides"][0]["text_shapes"][0]["paragraphs"] == observation["slides"][0]["text_shapes"][0]["paragraphs"]


def test_long_inventory_preserves_native_tail_index_and_declares_omission():
    observation = {"slide_count": 1, "slides": [{"slide": 0, "text_shapes": [{
        "index": 1, "path": [1], "paragraphs": [
            {"index": i, "text": "" if i == 19 else "x"} for i in range(20)
        ],
    }]}]}
    result = compact_presentation_hint_for_model(observation)
    slide, path, count, omitted, pairs = result["paragraph_inventory"][0]
    assert (slide, path, count, omitted) == (0, [1], 20, 8)
    assert len(pairs) == 12
    assert pairs[-1] == [19, 0]
    assert [pair[0] for pair in pairs] == [0, 1, 2, 3, 4, 5, 14, 15, 16, 17, 18, 19]
