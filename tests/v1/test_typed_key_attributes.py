# SPDX-License-Identifier: Apache-2.0
"""Module-owned schemas over the generic attribute wire representation."""

# Standard
from dataclasses import dataclass, field, replace
from typing import ClassVar, Literal
import base64
import json

# Third Party
import msgspec
import pytest

# First Party
from lmcache.v1.distributed.api import ObjectKey
from lmcache.v1.key_attributes import (
    KeyAttribute,
    decode_matching_attributes,
    decode_typed_attribute,
    encode_matching_attributes,
    encode_typed_attribute,
)
from lmcache.v1.storage_backend.raw_block.key_codec import (
    decode_object_key,
    encode_object_key,
)


class KVCacheEncoding(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    """Illustrative closed schema owned by an engine integration module."""

    ATTRIBUTE_NAME: ClassVar[str] = "lmcache.kv_encoding.v1"
    dtype: Literal["bfloat16", "float8_e4m3fn"]
    layout: Literal["NHD", "HND"]

    def to_attribute(self) -> KeyAttribute:
        """Produce the canonical value used on generic keys."""
        return encode_typed_attribute(self.ATTRIBUTE_NAME, self)

    @classmethod
    def from_attribute(cls, attribute: KeyAttribute) -> "KVCacheEncoding":
        """Interpret a value only at the owner module's boundary."""
        return decode_typed_attribute(attribute, cls.ATTRIBUTE_NAME, cls)


@dataclass(frozen=True)
class PrefetchHints:
    """An example non-matching metadata schema with an owner invariant."""

    budget_ms: int

    def __post_init__(self) -> None:
        if self.budget_ms < 0:
            raise ValueError("budget_ms must be non-negative")


@dataclass(frozen=True)
class EncodingOptions:
    """A producer schema containing an unordered map."""

    options: dict[str, int] = field(default_factory=dict)


def test_owner_class_round_trip_through_key_storage() -> None:
    encoding = KVCacheEncoding("bfloat16", "NHD")
    attribute = encoding.to_attribute()
    key = ObjectKey(b"1234", "model", 0, identity_metadata=(attribute,))
    recovered = decode_object_key(encode_object_key(key).encoded)
    assert KVCacheEncoding.from_attribute(recovered.identity_metadata[0]) == encoding
    assert not hasattr(key, "kv_encoding")
    different = replace(
        key, identity_metadata=(KVCacheEncoding("float8_e4m3fn", "NHD").to_attribute(),)
    )
    assert different != key


def test_metadata_schema_is_typed_but_does_not_change_matching() -> None:
    attribute = encode_typed_attribute("lmcache.prefetch.v1", PrefetchHints(20))
    key = ObjectKey(b"1234", "model", 0, metadata=(attribute,))
    hints = decode_typed_attribute(
        key.metadata[0], "lmcache.prefetch.v1", PrefetchHints
    )
    assert hints.budget_ms == 20
    assert key == replace(
        key,
        metadata=(encode_typed_attribute("lmcache.prefetch.v1", PrefetchHints(30)),),
    )
    with pytest.raises(ValueError, match="non-negative"):
        decode_typed_attribute(
            KeyAttribute("lmcache.prefetch.v1", '{"budget_ms":-1}'),
            "lmcache.prefetch.v1",
            PrefetchHints,
        )


def test_typed_values_have_deterministic_canonical_json() -> None:
    first = encode_typed_attribute(
        "encoding.options.v1", EncodingOptions({"z": 2, "a": 1})
    )
    second = encode_typed_attribute(
        "encoding.options.v1", EncodingOptions({"a": 1, "z": 2})
    )
    assert first == second
    assert first.value == '{"options":{"a":1,"z":2}}'
    assert encode_matching_attributes((), (first,)) == encode_matching_attributes(
        (), (second,)
    )


@pytest.mark.parametrize(
    "payload",
    [
        '{"dtype":"bfloat16"}',
        '{"dtype":1,"layout":"NHD"}',
        '{"dtype":"auto","layout":"NHD"}',
        '{"dtype":"bfloat16","layout":"NHD","extra":true}',
        "not-json",
    ],
)
def test_owner_rejects_invalid_schema(payload: str) -> None:
    with pytest.raises(ValueError):
        KVCacheEncoding.from_attribute(
            KeyAttribute(KVCacheEncoding.ATTRIBUTE_NAME, payload)
        )


def test_owner_rejects_wrong_name_and_version() -> None:
    valid = KVCacheEncoding("bfloat16", "NHD").to_attribute()
    for name in ("lmcache.kv_encoding.v2", "vendor.other.v1"):
        with pytest.raises(ValueError, match="expected attribute"):
            KVCacheEncoding.from_attribute(replace(valid, name=name))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_matching_values_are_rejected(value: float) -> None:
    with pytest.raises(ValueError):
        encode_typed_attribute("matching.value.v1", {"nested": [value]})


def test_unknown_schema_is_preserved_without_core_interpretation() -> None:
    attribute = KeyAttribute("vendor.codec.v9", "module-defined opaque content")
    key = ObjectKey(b"1234", "model", 0, identity_metadata=(attribute,))
    recovered = decode_object_key(encode_object_key(key).encoded)
    assert recovered.identity_metadata == (attribute,)


@pytest.mark.parametrize(
    "categories",
    [
        ("opaque_identity", "metadata"),
        ("opaque_identity", "identity_metadata"),
        ("metadata", "identity_metadata"),
    ],
)
def test_attribute_name_cannot_belong_to_two_categories(
    categories: tuple[str, str],
) -> None:
    key = ObjectKey(b"1234", "model", 0)
    kwargs = {category: (KeyAttribute("dtype", "bf16"),) for category in categories}
    # Round-trip at the protocol boundary validates dynamic field names too.
    payload = {"chunk_hash": "MTIzNA==", "model_name": "model", "kv_rank": 0}
    payload.update({name: msgspec.to_builtins(value) for name, value in kwargs.items()})
    with pytest.raises(ValueError, match="duplicate"):
        msgspec.json.decode(json.dumps(payload), type=ObjectKey)
    assert key.opaque_identity == key.metadata == key.identity_metadata == ()


def test_matching_token_rejects_cross_category_duplicate_names() -> None:
    attribute = KeyAttribute("dtype", "bf16")
    with pytest.raises(ValueError, match="duplicate"):
        encode_matching_attributes((attribute,), (attribute,))
    # Hand-crafted persisted data must not bypass the same validation.
    payload = msgspec.json.encode([[["dtype", "bf16"]], [["dtype", "bf16"]]])
    token = "x1-" + base64.urlsafe_b64encode(payload).decode().rstrip("=")
    with pytest.raises(ValueError, match="duplicate"):
        decode_matching_attributes(token)
