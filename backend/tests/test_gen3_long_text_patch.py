import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from server import apply_translations
from text_extract import CODECS, GEN3


def _rom_with_text_and_pointers(original, offset=0x200):
    encoded = CODECS["pokemon_gen3"].encode(original)
    data = bytearray(b"\x00" * 0x400)
    data[offset:offset + len(encoded)] = encoded
    data[offset + len(encoded)] = 0xFF
    pointer = (0x08000000 + offset).to_bytes(4, "little")
    sites = (0xC1, 0xD0)
    for site in sites:
        data[site:site + 4] = pointer
    return data, encoded, sites


def test_long_gen3_translation_relocates_and_updates_all_pointers():
    original = "HELLO"
    translated = "A MUCH LONGER TRANSLATION"
    offset = 0x200
    data, encoded, sites = _rom_with_text_and_pointers(original, offset)

    patched = apply_translations(
        data,
        "pokemon_gen3",
        {original: [(offset, len(encoded))]},
        [(original, translated)],
    )

    pointers = [int.from_bytes(data[site:site + 4], "little") for site in sites]
    target_offsets = [pointer - 0x08000000 for pointer in pointers]
    assert patched == 1
    assert target_offsets[0] == target_offsets[1] >= 0x400
    assert GEN3.decode(data, target_offsets[0])[1] == translated
    assert len(data) & (len(data) - 1) == 0
    assert data[0xBD] == (-sum(data[0xA0:0xBD]) - 0x19) & 0xFF


def test_long_gen3_translation_without_pointer_is_left_unchanged():
    original = "HELLO"
    translated = "A MUCH LONGER TRANSLATION"
    data, encoded, _ = _rom_with_text_and_pointers(original)
    data[0xC1:0xC5] = b"\x00" * 4
    data[0xD0:0xD4] = b"\x00" * 4
    before = bytes(data)

    patched = apply_translations(
        data,
        "pokemon_gen3",
        {original: [(0x200, len(encoded))]},
        [(original, translated)],
    )

    assert patched == 0
    assert bytes(data) == before