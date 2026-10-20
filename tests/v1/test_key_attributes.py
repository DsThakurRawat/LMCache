# SPDX-License-Identifier: Apache-2.0
"""Contracts for the three attribute collections held directly by cache keys."""

# Standard
from dataclasses import FrozenInstanceError, replace

# Third Party
import msgspec
import pytest

# First Party
from lmcache.v1.distributed.api import (
    AttnWindowDesc,
    MemoryLayoutDesc,
    ObjectKey,
    ipc_key_to_grouped_object_keys,
    ipc_key_to_object_keys,
)
from lmcache.v1.key_attributes import (
    KeyAttribute,
    decode_key_attributes,
    encode_key_attributes,
    key_attribute_suffix,
)
from lmcache.v1.mp_coordinator.utils.encoding import decode_key, encode_key
from lmcache.v1.multiprocess.custom_types import IPCCacheServerKey
from lmcache.v1.multiprocess.session import Session
from lmcache.v1.multiprocess.token_hasher import TokenHasher
from lmcache.v1.multiprocess.transport.grpc_impl._proto_gen import (
    common_pb2,
    p2p_service_pb2,
)
from lmcache.v1.multiprocess.transport.grpc_impl.proto_codec import (
    compile_request_codec_for_types,
)
from lmcache.v1.storage_backend.raw_block.key_codec import (
    decode_object_key,
    encode_object_key,
)


def test_direct_attributes_and_matching_semantics() -> None:
    key = ObjectKey(
        b"1234",
        "model",
        1,
        identity=(KeyAttribute("precision", "bf16"), KeyAttribute("arch", "v1")),
        metadata=(KeyAttribute("trace", "a"),),
        named_identity=(KeyAttribute("layout", "NHD"), KeyAttribute("codec", "raw-v1")),
    )
    same = replace(
        key,
        identity=tuple(reversed(key.identity)),
        metadata=(KeyAttribute("trace", "b"),),
        named_identity=tuple(reversed(key.named_identity)),
    )
    assert key == same and hash(key) == hash(same)
    assert {key: "hit"}[same] == "hit"
    assert key.identity[0].name == "arch"
    assert key.named_identity[0].name == "codec"
    assert key.metadata[0].value == "a"
    assert not hasattr(key, "extensions")
    assert key != replace(key, identity=(KeyAttribute("precision", "fp8"),))
    assert key != replace(
        key, identity=(KeyAttribute("renamed", "bf16"), *key.identity[:1])
    )
    assert key != replace(key, named_identity=(KeyAttribute("layout", "HND"),))
    with pytest.raises(FrozenInstanceError):
        key.identity[0].value = "v2"  # type: ignore[misc]


@pytest.mark.parametrize("name,value", [("", "v"), (1, "v"), ("name", 2)])
def test_invalid_attribute_rejected(name: str, value: str) -> None:
    with pytest.raises(ValueError):
        KeyAttribute(name, value)


@pytest.mark.parametrize("category", ["identity", "metadata", "named_identity"])
def test_duplicate_names_rejected_by_each_key_type(category: str) -> None:
    duplicates = (KeyAttribute("a", "1"), KeyAttribute("a", "2"))
    identity = duplicates if category == "identity" else ()
    metadata = duplicates if category == "metadata" else ()
    named_identity = duplicates if category == "named_identity" else ()
    with pytest.raises(ValueError, match="duplicate"):
        ObjectKey(
            b"1234",
            "model",
            1,
            identity=identity,
            metadata=metadata,
            named_identity=named_identity,
        )
    with pytest.raises(ValueError, match="duplicate"):
        IPCCacheServerKey.from_token_ids(
            "model",
            1,
            0,
            [1],
            identity=identity,
            metadata=metadata,
            named_identity=named_identity,
        )


@pytest.mark.parametrize("salt", ["", "tenant"])
def test_storage_round_trip(salt: str) -> None:
    key = ObjectKey(
        b"1234",
        "model",
        1,
        cache_salt=salt,
        identity=(
            KeyAttribute("precision", "bf16"),
            KeyAttribute("unicode", "中/@\\\x00"),
        ),
        metadata=(KeyAttribute("trace", "a"),),
        named_identity=(KeyAttribute("layout", "NHD"),),
    )
    spec = encode_object_key(key)
    recovered = decode_object_key(spec.encoded)
    assert recovered == key
    assert recovered.metadata == ()
    assert recovered.named_identity == key.named_identity
    assert spec == encode_object_key(replace(key, metadata=()))
    empty = replace(key, identity=(), named_identity=())
    assert spec.slot_identity != encode_object_key(empty).slot_identity
    assert encode_key(key) != encode_key(empty)
    assert decode_key(encode_key(key)) == key


@pytest.mark.parametrize(
    "token", ["x2-W10", "x1-@@", "x1-W10", "x1-W1tdLFtdXQ", "x1-W1tdLFtdXQ=="]
)
def test_invalid_storage_token_rejected(token: str) -> None:
    with pytest.raises(ValueError):
        decode_key_attributes(token)


def test_legacy_storage_names_unchanged() -> None:
    key = ObjectKey(b"1234", "model", 1)
    assert encode_object_key(key).encoded == "model@0x00000001@0@31323334"
    assert len(encode_key(key)) == 5
    assert encode_object_key(
        replace(key, metadata=(KeyAttribute("trace", "a"),))
    ) == encode_object_key(key)
    assert key_attribute_suffix("salt", (), ()) == "@salt"


def test_msgpack_json_projections_and_expansion() -> None:
    ipc = IPCCacheServerKey.from_token_ids(
        "model",
        2,
        0,
        [1, 2],
        end=2,
        identity=(KeyAttribute("precision", "bf16"),),
        metadata=(KeyAttribute("trace", "a"),),
        named_identity=(KeyAttribute("codec", "raw-v1"),),
    )
    for codec in (msgspec.msgpack, msgspec.json):
        decoded = codec.decode(codec.encode(ipc), type=IPCCacheServerKey)
        assert decoded == ipc and decoded.metadata == ipc.metadata
        assert not hasattr(decoded, "extensions")
        keys = ipc_key_to_object_keys(decoded.no_worker_id_version(), [b"1234"], [0, 1])
        assert len(keys) == 2 and all(len(group) == 2 for group in keys)
        rows = ipc_key_to_grouped_object_keys(
            decoded.no_worker_id_version(),
            [b"1234"],
            [0],
            {0: MemoryLayoutDesc(shapes=[], dtypes=[])},
            AttnWindowDesc([-1]),
        )
        for key in [k for group in keys for k in group] + [
            k for row in rows for k in row.keys
        ]:
            assert key.identity == ipc.identity
            assert key.metadata == ipc.metadata
            assert key.named_identity == ipc.named_identity
            wire = key.to_encoded_object_key()
            recovered = msgspec.json.decode(
                msgspec.json.encode(wire), type=type(wire)
            ).to_object_key()
            assert recovered == key and recovered.metadata == key.metadata
    hinted = replace(ipc, metadata=(KeyAttribute("trace", "b"),))
    assert ipc == hinted and hash(ipc) == hash(hinted)
    assert not (ipc < hinted or hinted < ipc)
    legacy = msgspec.msgpack.decode(
        msgspec.msgpack.encode(
            {
                "model_name": "model",
                "world_size": 1,
                "worker_id": 0,
                "token_ids": [1],
                "start": 0,
                "end": 1,
                "request_id": "r",
            }
        ),
        type=IPCCacheServerKey,
    )
    assert legacy.identity == legacy.metadata == legacy.named_identity == ()


def test_protobuf_uses_three_direct_repeated_attributes() -> None:
    ipc = IPCCacheServerKey.from_token_ids(
        "model",
        1,
        0,
        [1],
        identity=(KeyAttribute("precision", "bf16"),),
        metadata=(KeyAttribute("trace", "a"),),
        named_identity=(KeyAttribute("codec", "raw-v1"),),
    )
    key = ObjectKey(
        b"1234",
        "model",
        0,
        identity=ipc.identity,
        metadata=ipc.metadata,
        named_identity=ipc.named_identity,
    )
    for message_type, value in (
        (common_pb2.IpcCacheServerKey, ipc),
        (p2p_service_pb2.ObjectKey, key),
    ):
        encode, decode = compile_request_codec_for_types(message_type, (type(value),))
        message = encode((value,), {})
        assert message.identity[0].name == "precision"
        assert message.metadata[0].value == "a"
        assert message.named_identity[0].name == "codec"
        assert "extensions" not in message.DESCRIPTOR.fields_by_name
        (recovered,) = decode(message_type.FromString(message.SerializeToString()))
        assert recovered == value and recovered.metadata == value.metadata
    _, decode = compile_request_codec_for_types(p2p_service_pb2.ObjectKey, (ObjectKey,))
    (recovered,) = decode(
        p2p_service_pb2.ObjectKey(chunk_hash=b"1234", model_name="model")
    )
    assert recovered.identity == recovered.metadata == recovered.named_identity == ()


def test_session_release_checks_matching_attributes_only() -> None:
    lookup = IPCCacheServerKey.from_token_ids(
        "model",
        1,
        None,
        [1],
        end=1,
        identity=(KeyAttribute("precision", "bf16"),),
        metadata=(KeyAttribute("trace", "a"),),
    )
    session = Session("r", TokenHasher(chunk_size=1))
    session.begin_lookup(lookup, (-1,))
    session.record_prefetch_result(1, (0,))
    worker = replace(lookup, worker_id=0)
    snapshot = session.prepare_failed_retrieve_release(worker)
    assert snapshot is not None
    generation = snapshot[-1]
    wrong = replace(worker, identity=(KeyAttribute("precision", "fp8"),))
    assert session.prepare_failed_retrieve_release(wrong) is None
    assert not session.claim_failed_retrieve_release(1, wrong, generation)
    assert session.claim_failed_retrieve_release(
        1, replace(worker, metadata=()), generation
    )


@pytest.mark.parametrize("field_count", [4, 7])
def test_capture_rejects_unknown_key_schema(field_count: int) -> None:
    token = encode_key_attributes((KeyAttribute("precision", "bf16"),), ())
    encoded = (b"1234", "model", 1, 0, "", token, "future")
    with pytest.raises(ValueError):
        decode_key(encoded[:field_count])
