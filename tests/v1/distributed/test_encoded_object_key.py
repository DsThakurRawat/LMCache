# SPDX-License-Identifier: Apache-2.0
"""Tests for :class:`EncodedObjectKey` — the HTTP/JSON wire form of
:class:`ObjectKey`.

These tests stand alone from the heavier ``ObjectKey``-using machinery
so they can run without ``lmcache.lmcache_native`` being built.
"""

# Standard
from dataclasses import asdict

# Third Party
import pytest

# First Party
from lmcache.v1.cache_identity import EncodedObjectKeyIdentity, ObjectKeyIdentity
from lmcache.v1.distributed.api import EncodedObjectKey, ObjectKey


def _make_object_key(**overrides) -> ObjectKey:
    return ObjectKey(
        identity=ObjectKeyIdentity(
            model_name=overrides.get("model_name", "llama"),
            cache_salt=overrides.get("cache_salt", ""),
            chunk_hash=bytes.fromhex(overrides.get("chunk_hash_hex", "deadbeef")),
            kv_rank=overrides.get("kv_rank", 7),
            object_group_id=overrides.get("object_group_id", 0),
        )
    )


class TestRoundTrip:
    def test_encode_preserves_all_fields(self):
        obj = _make_object_key(
            chunk_hash_hex="cafebabe",
            model_name="llama",
            kv_rank=42,
            object_group_id=3,
            cache_salt="alice",
        )
        ck = obj.to_encoded_object_key()
        assert ck.chunk_hash_hex == "cafebabe"
        assert ck.model_name == "llama"
        assert ck.kv_rank == 42
        assert ck.object_group_id == 3
        assert ck.cache_salt == "alice"

    def test_round_trip_object_key(self):
        obj = _make_object_key(
            chunk_hash_hex="00010203",
            model_name="m",
            kv_rank=1,
            object_group_id=5,
            cache_salt="bob",
        )
        assert obj.to_encoded_object_key().to_object_key() == obj

    def test_uppercase_hex_round_trips_lowercased(self):
        # bytes.fromhex accepts uppercase; the recovered ObjectKey
        # then re-projects to lowercase via bytes.hex().
        ck = EncodedObjectKey(
            identity=EncodedObjectKeyIdentity(
                model_name="m", chunk_hash_hex="DEADBEEF", kv_rank=0
            )
        )
        obj = ck.to_object_key()
        assert obj.chunk_hash == b"\xde\xad\xbe\xef"
        assert obj.to_encoded_object_key().chunk_hash_hex == "deadbeef"

    def test_optional_fields_default(self):
        ck = EncodedObjectKey(
            identity=EncodedObjectKeyIdentity(
                model_name="m", chunk_hash_hex="aa", kv_rank=0
            )
        )
        assert ck.object_group_id == 0
        assert ck.cache_salt == ""

    def test_asdict_shape_is_stable(self):
        # Wire callers serialize via ``dataclasses.asdict`` — the field
        # set is the public contract.
        ck = EncodedObjectKey(
            identity=EncodedObjectKeyIdentity(
                model_name="m",
                cache_salt="x",
                chunk_hash_hex="aa",
                kv_rank=0,
                object_group_id=1,
            )
        )
        assert asdict(ck) == {
            "identity": {
                "model_name": "m",
                "cache_salt": "x",
                "tags": {},
                "chunk_hash_hex": "aa",
                "kv_rank": 0,
                "object_group_id": 1,
            }
        }


class TestToObjectKeyValidation:
    def test_rejects_non_hex_chunk_hash(self):
        ck = EncodedObjectKey(
            identity=EncodedObjectKeyIdentity(
                model_name="m", chunk_hash_hex="not-hex", kv_rank=0
            )
        )
        with pytest.raises(ValueError):
            ck.to_object_key()

    def test_namespace_rejects_invalid_model(self):
        with pytest.raises(ValueError, match="model_name"):
            EncodedObjectKey(
                identity=EncodedObjectKeyIdentity(
                    model_name="bad@name", chunk_hash_hex="aa", kv_rank=0
                )
            )


class TestSchemasReExport:
    def test_schemas_module_still_exposes_encoded_object_key(self):
        # The mp_coordinator schemas module re-exports the canonical
        # type from ``api.py`` for callers that import from there.
        # First Party
        from lmcache.v1.mp_coordinator import schemas

        assert schemas.EncodedObjectKey is EncodedObjectKey
