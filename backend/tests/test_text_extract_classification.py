import os
import sys
import asyncio
import json
import re
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from text_extract import classify, protect_glossary_terms


def test_all_caps_menu_phrase_is_translatable():
    story, names, _ = classify([(100, 8, "NEW GAME")])

    assert [item[2] for item in story] == ["NEW GAME"]
    assert "NEW GAME" not in names


def test_single_word_pokemon_name_is_excluded():
    story, names, _ = classify([(100, 8, "PIKACHU")])

    assert story == []
    assert "PIKACHU" in names


def test_fixed_stride_name_table_does_not_crash():
    candidates = [(offset * 16, 8, name) for offset, name in enumerate(
        ("BULBASAUR", "IVYSAUR", "VENUSAUR", "CHARMANDER", "CHARMELEON", "CHARIZARD")
    )]

    story, names, _ = classify(candidates)

    assert story == []
    assert "BULBASAUR" in names
    assert "CHARIZARD" in names


def test_translation_protects_detected_names_exactly():
    from server import ExtractedString, _translate_batch

    original = "Pikachu used Tackle with Potion."
    names = {"PIKACHU", "TACKLE", "POTION"}
    protected, _ = protect_glossary_terms(original, names)
    markers = re.findall(r"\{KEEP\d{4}\}", protected)
    assert len(markers) == 3

    async def fake_call(prompt, provider, model, api_key):
        assert protected in prompt
        assert all(name.lower() not in prompt.lower() for name in names)
        return json.dumps([{"id": "test", "translated": "Pouzil " + " ".join(markers) + "."}])

    item = ExtractedString(id="test", offset=0, length=len(original), text=original)
    with patch("server._call_llm", side_effect=fake_call):
        loop = asyncio.new_event_loop()
        try:
            translated = loop.run_until_complete(_translate_batch(
                "Czech", [item], "freetheai", "test-model", "test-key", names=names
            ))
        finally:
            loop.close()

    assert translated[0].translated == "Pouzil Pikachu Tackle Potion."