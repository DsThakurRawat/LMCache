# SPDX-License-Identifier: Apache-2.0
"""Contracts for extensible identity and request metadata."""

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
from lmcache.v1.key_extensions import KeyExtensions
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


def test_three_categories_and_canonical_names() -> None:
    base = KeyExtensions(
        identity=("bf16",),
        metadata=(("trace", "a"),),
        named_identity=(("layout", "NHD"), ("codec", "raw-v1")),
    )
    same = KeyExtensions(
        identity=("bf16",),
        metadata=(("trace", "b"),),
        named_identity=(("codec", "raw-v1"), ("layout", "NHD")),
    )
    key = ObjectKey(b"1234", "model", 1, extensions=base)
    assert key == replace(key, extensions=same)
    assert hash(key) == hash(replace(key, extensions=same))
    assert {key: "hit"}[replace(key, extensions=same)] == "hit"
    assert key != replace(key, extensions=replace(base, identity=("fp8",)))
    assert key != replace(
        key, extensions=replace(base, named_identity=(("layout", "HND"),))
    )
    assert base.to_storage_token() == same.to_storage_token()
    assert dict(base.metadata)["trace"] == "a"
    assert dict(base.named_identity)["layout"] == "NHD"
    with pytest.raises(FrozenInstanceError):
        base.identity = ()  # type: ignore[misc]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"metadata": (("a", "1"), ("a", "2"))},
        {"named_identity": (("", "x"),)},
        {"metadata": (("a", "1"),), "named_identity": (("a", "2"),)},
        {"identity": (3,)},
    ],
)
def test_invalid_attributes_rejected(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        KeyExtensions(**kwargs)


@pytest.mark.parametrize("salt", ["", "tenant"])
def test_storage_round_trip_and_metadata_independence(salt: str) -> None:
    ext = KeyExtensions(
        identity=("dtype-v1:bf16", "unicode/中@\\\x00"),
        metadata=(("trace", "a"),),
        named_identity=(("layout", "NHD"),),
    )
    key = ObjectKey(b"1234", "model", 1, cache_salt=salt, extensions=ext)
    spec = encode_object_key(key)
    recovered = decode_object_key(spec.encoded)
    assert recovered == key
    assert recovered.extensions.metadata == ()
    assert recovered.extensions.named_identity == ext.named_identity
    assert spec == encode_object_key(replace(key, extensions=replace(ext, metadata=())))
    assert (
        spec.slot_identity
        != encode_object_key(replace(key, extensions=KeyExtensions())).slot_identity
    )
    assert encode_key(key) != encode_key(replace(key, extensions=KeyExtensions()))
    assert decode_key(encode_key(key)) == key


@pytest.mark.parametrize(
    "token", ["x2-W10", "x1-@@", "x1-W10", "x1-W1tdLFtdXQ", "x1-W1tdLFtdXQ=="]
)
def test_invalid_or_noncanonical_token_rejected(token: str) -> None:
    with pytest.raises(ValueError):
        KeyExtensions.from_storage_token(token)


def test_legacy_storage_names_and_captures_unchanged() -> None:
    key = ObjectKey(b"1234", "model", 1)
    assert encode_object_key(key).encoded == "model@0x00000001@0@31323334"
    assert len(encode_key(key)) == 5
    hints = replace(key, extensions=KeyExtensions(metadata=(("trace", "x"),)))
    assert encode_object_key(hints) == encode_object_key(key)
    assert KeyExtensions().storage_suffix("salt") == "@salt"


def test_ipc_msgpack_json_and_key_derivation() -> None:
    ext = KeyExtensions(identity=("precision-v1:bf16",), metadata=(("trace", "a"),))
    ipc = IPCCacheServerKey.from_token_ids("model", 2, 0, [1, 2], end=2, extensions=ext)
    for codec in (msgspec.msgpack, msgspec.json):
        decoded = codec.decode(codec.encode(ipc), type=IPCCacheServerKey)
        assert decoded.extensions == ext
        assert decoded.extensions.metadata == ext.metadata
        rows = ipc_key_to_grouped_object_keys(
            decoded.no_worker_id_version(),
            [b"1234"],
            [0],
            {0: MemoryLayoutDesc(shapes=[], dtypes=[])},
            AttnWindowDesc([-1]),
        )
        assert len(rows) == 2
        assert all(
            key.extensions.metadata == ext.metadata for row in rows for key in row.keys
        )
        keys = ipc_key_to_object_keys(decoded.no_worker_id_version(), [b"1234"], [0, 1])
        assert len(keys) == 2 and all(len(group) == 2 for group in keys)
        assert all(
            key.extensions.metadata == ext.metadata for group in keys for key in group
        )
    changed = replace(ipc, extensions=replace(ext, metadata=(("trace", "b"),)))
    assert ipc == changed and hash(ipc) == hash(changed)
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
    assert legacy.extensions == KeyExtensions()


def test_json_safe_projection_preserves_named_attributes() -> None:
    key = ObjectKey(
        b"1234",
        "model",
        1,
        extensions=KeyExtensions(
            named_identity=(("layout", "NHD"),), metadata=(("trace", "a"),)
        ),
    )
    wire = key.to_encoded_object_key()
    decoded = msgspec.json.decode(
        msgspec.json.encode(wire), type=type(wire)
    ).to_object_key()
    assert decoded == key
    assert decoded.extensions.metadata == key.extensions.metadata


def test_protobuf_preserves_all_categories() -> None:
    ext = KeyExtensions(
        identity=("precision-v1:bf16",),
        metadata=(("trace", "a"),),
        named_identity=(("codec", "raw-v1"),),
    )
    ipc = IPCCacheServerKey.from_token_ids("model", 1, 0, [1], extensions=ext)
    key = ObjectKey(b"1234", "model", 0, extensions=ext)
    for message_type, value in (
        (common_pb2.IpcCacheServerKey, ipc),
        (p2p_service_pb2.ObjectKey, key),
    ):
        encode, decode = compile_request_codec_for_types(message_type, (type(value),))
        message = encode((value,), {})
        (recovered,) = decode(message_type.FromString(message.SerializeToString()))
        assert recovered == value
        assert recovered.extensions.metadata == ext.metadata
        assert recovered.extensions.named_identity == ext.named_identity
    # A legacy message omits the nested extension field entirely.
    encode, decode = compile_request_codec_for_types(
        p2p_service_pb2.ObjectKey, (ObjectKey,)
    )
    legacy = p2p_service_pb2.ObjectKey(chunk_hash=b"1234", model_name="model")
    (recovered,) = decode(legacy)
    assert recovered.extensions == KeyExtensions()


def test_session_release_does_not_cross_matching_extensions() -> None:
    ext = KeyExtensions(identity=("bf16",), metadata=(("trace", "a"),))
    lookup = IPCCacheServerKey.from_token_ids(
        "model", 1, None, [1], end=1, extensions=ext
    )
    session = Session("r", TokenHasher(chunk_size=1))
    session.begin_lookup(lookup, (-1,))
    session.record_prefetch_result(1, (0,))
    worker = replace(lookup, worker_id=0)
    snapshot = session.prepare_failed_retrieve_release(worker)
    assert snapshot is not None
    generation = snapshot[-1]
    wrong = replace(worker, extensions=KeyExtensions(identity=("fp8",)))
    assert session.prepare_failed_retrieve_release(wrong) is None
    assert not session.claim_failed_retrieve_release(1, wrong, generation)
    hinted = replace(worker, extensions=replace(ext, metadata=(("trace", "b"),)))
    assert session.claim_failed_retrieve_release(1, hinted, generation)


@pytest.mark.parametrize("field_count", [4, 7])
def test_capture_rejects_unknown_key_schema(field_count: int) -> None:
    ext = KeyExtensions(identity=("bf16",))
    encoded = (b"1234", "model", 1, 0, "", ext.to_storage_token(), "future")
    with pytest.raises(ValueError):
        decode_key(encoded[:field_count])
