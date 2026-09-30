"""Strict deterministic JSON identity for paper evidence."""
import hashlib
import json
from math import isfinite


def canonical_bytes(value):
    """Strict JSON only: no coerced keys, tuples, non-finite numbers or defaults."""
    def check(item):
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is float and isfinite(item):
            return
        if type(item) is list:
            for child in item:
                check(child)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for child in item.values():
                check(child)
            return
        raise ValueError("noncanonical_json")
    check(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def content_sha256(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


