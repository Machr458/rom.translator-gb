import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from server import apply_translations
from text_extract import CODECS, GEN1, GEN2


@pytest.mark.parametrize(
    ("encoding", "codec"),
    [("pokemon_gen1", GEN1), ("pokemon_gen2", GEN2)],
)
def test_long_gb_translation_relocates_within_bank(encoding, codec):
    original = "HELLO"
    translated = "A LONGER GAME TEXT"
    offset = 0x4123
    sites = (0x4020, 0x4040)
    encoded = CODECS[encoding].encode(original)
    data = bytearray(b"\x00" * 0x8000)
    data[offset:offset + len(encoded)] = encoded
    data[offset + len(encoded)] = 0x50
    for site in sites:
        data[site:site + 6] = b"\x11" + offset.to_bytes(2, "little") + b"\xcd\x34\x12"

    patched = apply_translations(
        data,
        encoding,
        {original: [(offset, len(encoded))]},
        [(original, translated)],
    )

    addresses = [int.from_bytes(data[site + 1:site + 3], "little") for site in sites]
    targets = [0x4000 + address - 0x4000 for address in addresses]
    assert patched == 1
    assert addresses[0] == addresses[1]
    assert 0x4000 <= addresses[0] < 0x8000
    assert codec.decode(data, targets[0])[1] == translated
    expected_checksum = (sum(data[:0x14E]) + sum(data[0x150:])) & 0xFFFF
    assert int.from_bytes(data[0x14E:0x150], "big") == expected_checksum


@pytest.mark.parametrize(
    ("encoding", "codec"),
    [("pokemon_gen1", GEN1), ("pokemon_gen2", GEN2)],
)
def test_long_gb_translation_without_direct_reference_falls_back_to_fitting_text(encoding, codec):
    original = "HELLO"
    translated = "A LONGER GAME TEXT"
    offset = 0x4123
    encoded = CODECS[encoding].encode(original)
    data = bytearray(b"\x00" * 0x8000)
    data[offset:offset + len(encoded)] = encoded
    data[offset + len(encoded)] = 0x50
    patched = apply_translations(
        data,
        encoding,
        {original: [(offset, len(encoded))]},
        [(original, translated)],
    )

    assert patched == 1
    assert codec.decode(data, offset)[1] == "A LON"