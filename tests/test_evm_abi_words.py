import pytest

from stinky_core.evm_abi_words import address_array_at, address_from_word, uint_from_word, word_at
from stinky_core.evidence_pairing import compare_labels

A = "0x" + "11" * 20
B = "0x" + "22" * 20


def w(n):
    return n.to_bytes(32, "big")


def aw(address):
    return (b"\x00" * 12) + bytes.fromhex(address[2:])


def test_word_uint_and_address_decoders_preserve_exact_values():
    raw = w(7) + aw(A)
    assert uint_from_word(word_at(raw, 0)) == 7
    assert address_from_word("base", word_at(raw, 1)) == A


def test_dynamic_address_array_decodes_with_exact_end():
    raw = (b"\x00" * 64) + w(2) + aw(A) + aw(B)
    assert address_array_at(raw, offset=64, minimum_offset=64, chain="base") == (A, B)


def test_dynamic_array_offset_and_trailing_bytes_fail_closed():
    raw = (b"\x00" * 64) + w(1) + aw(A)
    with pytest.raises(ValueError, match="offset"):
        address_array_at(raw, offset=33, minimum_offset=64, chain="base")
    with pytest.raises(ValueError, match="trailing"):
        address_array_at(raw + w(9), offset=64, minimum_offset=64, chain="base")


def test_noncanonical_address_word_fails_closed():
    with pytest.raises(ValueError, match="canonically"):
        address_from_word("base", (b"\x01" * 12) + bytes.fromhex(A[2:]))


def test_pairing_equal_values():
    row = compare_labels("A", "A")
    assert row.left == "A"
    assert row.verdict == "CONSISTENT"
