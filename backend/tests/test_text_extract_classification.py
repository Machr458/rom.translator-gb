import os
import sys
import asyncio
import json
import re
import pytest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from text_extract import classify, protect_glossary_terms


def test_all_caps_menu_phrase_is_translatable():
    story, names, _ = classify([(100, 8, "NEW GAME")])

    assert [item[2] for item in story] == ["NEW GAME"]
    assert "NEW GAME" not in names


@pytest.mark.parametrize("label", ["START", "BAG", "FIGHT", "RUN", "OPTIONS", "CONTINUE"])
def test_uppercase_menu_labels_are_translatable(label):
    story, names, _ = classify([(100, len(label), label)])

    assert [item[2] for item in story] == [label]
    assert label not in names


def test_single_word_pokemon_name_in_fixed_stride_table_is_excluded():
    names_in_table = ("BULBASAUR", "IVYSAUR", "VENUSAUR", "CHARMANDER", "CHARMELEON", "CHARIZARD")
    candidates = [(offset * 16, len(name), name) for offset, name in enumerate(names_in_table)]

    story, names, _ = classify(candidates)

    assert story == []
    assert set(names_in_table) <= names


def test_short_result_messages_in_fixed_stride_table_are_translatable():
    candidates_text = (
        "YOU WIN", "BULBASAUR", "You win", "IVYSAUR", "YOU LOSE", "VENUSAUR",
        "You lose", "CHARMANDER",
    )
    candidates = [(offset * 16, len(text), text) for offset, text in enumerate(candidates_text)]

    story, names, _ = classify(candidates)

    assert {"YOU WIN", "You win", "YOU LOSE", "You lose"} <= {item[2] for item in story}
    assert {"BULBASAUR", "IVYSAUR", "VENUSAUR", "CHARMANDER"} <= names
    assert "YOU WIN" not in names
    assert "YOU LOSE" not in names


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


def test_translation_retries_when_ai_copies_source_text():
    from server import ExtractedString, _translate_batch

    original = "Hello there."
    item = ExtractedString(id="copy-test", offset=0, length=len(original), text=original)
    prompts = []

    async def fake_call(prompt, provider, model, api_key):
        prompts.append(prompt)
        translated = "Ahoj." if "CORRECTION:" in prompt else original
        return json.dumps([{"id": "copy-test", "translated": translated}])

    with patch("server._call_llm", side_effect=fake_call):
        translated = asyncio.run(_translate_batch(
            "Czech", [item], "freetheai", "test-model", "test-key"
        ))

    assert translated[0].translated == "Ahoj."
    assert len(prompts) == 2
    assert "left natural-language source text untranslated" in prompts[1]


def test_translation_does_not_return_source_when_ai_copies_it_twice():
    from server import ExtractedString, _translate_batch

    original = "I have to find{n}stronger POKéMON."
    item = ExtractedString(id="persistent-copy-test", offset=0, length=len(original), text=original)

    async def fake_call(prompt, provider, model, api_key):
        return json.dumps([{"id": "persistent-copy-test", "translated": original}])

    with patch("server._call_llm", side_effect=fake_call):
        translated = asyncio.run(_translate_batch(
            "Czech", [item], "freetheai", "test-model", "test-key",
            names={"POKéMON"},
        ))

    assert translated[0].translated == ""
    assert translated[0].error == "AI returned untranslated or invalid text after retry."


def test_translation_rejects_added_page_breaks():
    from server import ExtractedString, _translate_batch

    original = "A{p}B"
    item = ExtractedString(id="page-test", offset=0, length=3, text=original)

    async def fake_call(prompt, provider, model, api_key):
        return json.dumps([{"id": "page-test", "translated": "A{p}B{p}C"}])

    with patch("server._call_llm", side_effect=fake_call):
        translated = asyncio.run(_translate_batch(
            "Czech", [item], "freetheai", "test-model", "test-key"
        ))

    assert translated[0].translated == original


def test_long_translation_and_reflow_are_accepted_when_tokens_are_preserved():
    from server import _translation_preserves_structure

    source = "Phone numbers are{n}stored in memory.{p}Just choose a name{n}you want to call.{p}Gee, isn't that{n}convenient?"
    oversized = "Telefonni cisla{n}se ukladaji do{p}pameti. Staci vybrat{n}jmeno, kteremu{p}chces zavolat.{p}To je ale pohodlne,{n}co?"
    fitted = "Telefonni cisla{n}jsou v pameti.{p}Staci vybrat{n}jmeno k zavolani.{p}To je pohodlne,{n}ze?"
    wrapped = "Telefonni {n}cisla se ukladaji {n}do{p}pameti. Staci {n}vybrat{n}jmeno, kteremu{p}chces zavolat.{p}To je ale pohodlne,{n}co?"

    assert _translation_preserves_structure(source, oversized)
    assert _translation_preserves_structure(source, fitted)
    assert _translation_preserves_structure(source, wrapped, "pokemon_gen2")
    assert not _translation_preserves_structure(source, oversized, "pokemon_gen2")
    assert not _translation_preserves_structure(source, wrapped.replace("Telefonni {n}", "Telefon{n}ni "), "pokemon_gen2")
    assert not _translation_preserves_structure(source, fitted.replace("{p}", "", 1))
    assert not _translation_preserves_structure(source, wrapped.replace("{p}", "{p}{p}", 1))
    assert not _translation_preserves_structure(source, source.replace("{n}", "", 1).replace("{p}", "{n}{p}", 1))


def test_oversized_ascii_patch_writes_fitting_prefix_as_last_resort():
    from server import apply_translations

    data = bytearray(b"HELLO\x00")
    patched = apply_translations(
        data,
        "ascii",
        {"HELLO": [(0, 5)]},
        [("HELLO", "A MUCH LONGER TRANSLATION")],
    )

    assert patched == 1
    assert bytes(data) == b"A MUC\x00"


def test_long_translation_is_not_retried_or_shortened_to_fit():
    from server import ExtractedString, _translate_batch

    source = "Phone numbers are{n}stored in memory.{p}Just choose a name{n}you want to call.{p}Gee, isn't that{n}convenient?"
    oversized = "Telefonni cisla{n}se ukladaji do{p}pameti. Staci vybrat{n}jmeno, kteremu{p}chces zavolat.{p}To je ale pohodlne,{n}co?"
    item = ExtractedString(id="phone", offset=0, length=99, text=source)
    calls = []

    async def fake_call(prompt, provider, model, api_key):
        calls.append(prompt)
        return json.dumps([{"id": "phone", "translated": oversized}])

    with patch("server._call_llm", side_effect=fake_call):
        result = asyncio.run(_translate_batch(
            "Czech", [item], "freetheai", "test-model", "test-key", encoding="pokemon_gen2"
        ))

    assert len(calls) == 1
    assert "CORRECTION:" not in calls[0]
    assert result[0].translated == oversized


@pytest.mark.parametrize(
    ("cached_kind", "expected_cached", "expected_translation_calls"),
    [("over_capacity", 1, 0), ("unchanged", 0, 1)],
)
def test_cache_keeps_full_translations_but_retranslates_unchanged_values(
    cached_kind, expected_cached, expected_translation_calls
):
    import server
    from server import ExtractedString, TranslatedString, TranslateRequest
    from unittest.mock import AsyncMock

    source = "Phone numbers are{n}stored in memory.{p}Just choose a name{n}you want to call.{p}Gee, isn't that{n}convenient?"
    oversized = "Telefonni cisla{n}se ukladaji do{p}pameti. Staci vybrat{n}jmeno, kteremu{p}chces zavolat.{p}To je ale pohodlne,{n}co?"
    fitted = "Telefonni cisla{n}jsou v pameti.{p}Staci vybrat{n}jmeno k zavolani.{p}To je pohodlne,{n}ze?"
    cached = source if cached_kind == "unchanged" else oversized
    item = ExtractedString(id="phone-cache", offset=0, length=99, text=source)
    request = TranslateRequest(
        session_id="cache-test",
        target_language="cs",
        strings=[item],
        provider="emergent",
    )
    created_tasks = []
    translated_batch = AsyncMock(return_value=[
        TranslatedString(id=item.id, original=source, translated=fitted)
    ])
    cache_lookup = AsyncMock(return_value={("cs", source): cached})
    cache_delete = AsyncMock()

    loop = asyncio.new_event_loop()
    try:
        with (
            patch.object(server, "_get_session", return_value={"encoding": "pokemon_gen2"}),
            patch.object(server, "_get_glossary", return_value=[]),
            patch.object(server, "_cache_lookup", cache_lookup),
            patch.object(server, "_cache_delete_many", cache_delete),
            patch.object(server, "_translate_batch", translated_batch),
            patch.object(server, "_cache_store_many", new_callable=AsyncMock),
            patch.object(server, "_update_session"),
            patch("asyncio.create_task", side_effect=lambda task: created_tasks.append(task)),
        ):
            started = loop.run_until_complete(server.translate_rom_start(request))
            async def finish_worker():
                await asyncio.gather(*created_tasks)

            loop.run_until_complete(finish_worker())
    finally:
        loop.close()

    job = server.JOBS[started["job_id"]]
    assert job["status"] == "done"
    assert job["cached_count"] == expected_cached
    assert translated_batch.await_count == expected_translation_calls
    assert job["translations"][0]["translated"] == (oversized if cached_kind == "over_capacity" else fitted)
    if cached_kind == "unchanged":
        cache_delete.assert_awaited_once_with([server._cache_key(source, "cs")])
    else:
        cache_delete.assert_not_awaited()


def test_missing_model_rows_are_retried_in_smaller_batches():
    from server import ExtractedString, _translate_batch

    batch = [
        ExtractedString(id=f"id-{i}", offset=i, length=11, text=f"Original {i}")
        for i in range(4)
    ]
    calls = []

    async def fake_call(prompt, provider, model, api_key):
        ids = re.findall(r'"id":"([^"]+)"', prompt)
        calls.append(ids)
        if len(ids) == 4:
            return json.dumps([{"id": ids[0], "translated": "Prvni"}])
        return json.dumps([{"id": item_id, "translated": f"T-{item_id}"} for item_id in ids])

    loop = asyncio.new_event_loop()
    try:
        with patch("server._call_llm", side_effect=fake_call):
            result = loop.run_until_complete(_translate_batch(
                "Czech", batch, "freetheai", "test-model", "test-key"
            ))
    finally:
        loop.close()

    assert [len(call) for call in calls] == [4, 2, 2]
    assert [item.translated for item in result] == [f"T-id-{i}" for i in range(4)]