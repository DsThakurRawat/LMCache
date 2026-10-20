# SPDX-License-Identifier: Apache-2.0

# First Party
from lmcache.v1.cache_identity import ObjectKeyIdentity
from lmcache.v1.distributed.api import ObjectKey
from lmcache.v1.storage_backend.raw_block.key_codec import (
    decode_object_key,
    object_key_to_string,
)


def test_raw_block_object_key_codec_preserves_sep_literal() -> None:
    """Object-key encoding must not treat literal -SEP- as a slash escape."""
    key = ObjectKey(
        identity=ObjectKeyIdentity(
            model_name="my-SEP-model",
            cache_salt="tenant",
            chunk_hash=ObjectKey.IntHash2Bytes(123),
            kv_rank=1,
        )
    )

    decoded = decode_object_key(object_key_to_string(key))

    assert decoded == key


def test_raw_block_object_key_codec_roundtrips_slash_and_sep() -> None:
    """Object-key encoding must round-trip slashes and literal -SEP- strings."""
    key = ObjectKey(
        identity=ObjectKeyIdentity(
            model_name="org/model-SEP-name",
            chunk_hash=ObjectKey.IntHash2Bytes(456),
            kv_rank=2,
        )
    )

    encoded = object_key_to_string(key)
    decoded = decode_object_key(encoded)

    assert "%2F" in encoded
    assert decoded == key


def test_raw_block_object_key_codec_roundtrips_object_group_id() -> None:
    """object_group_id must survive encode/decode for salted and unsalted keys."""
    for object_group_id in (0, 1, 255):
        for cache_salt in ("", "tenant"):
            key = ObjectKey(
                identity=ObjectKeyIdentity(
                    model_name="org/model",
                    cache_salt=cache_salt,
                    chunk_hash=ObjectKey.IntHash2Bytes(789),
                    kv_rank=7,
                    object_group_id=object_group_id,
                )
            )
            assert decode_object_key(object_key_to_string(key)) == key


def test_raw_block_object_group_id_distinguishes_encoding() -> None:
    """Keys differing only in object_group_id must encode differently."""
    chunk_hash = ObjectKey.IntHash2Bytes(1)
    enc0 = object_key_to_string(
        ObjectKey(
            identity=ObjectKeyIdentity(
                model_name="m", chunk_hash=chunk_hash, kv_rank=0, object_group_id=0
            )
        )
    )
    enc1 = object_key_to_string(
        ObjectKey(
            identity=ObjectKeyIdentity(
                model_name="m", chunk_hash=chunk_hash, kv_rank=0, object_group_id=1
            )
        )
    )
    assert enc0 != enc1
