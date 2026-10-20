# SPDX-License-Identifier: Apache-2.0
"""Cache identity identity and transport contracts."""

# Standard
from dataclasses import replace

# Third Party
import msgspec
import pytest

# First Party
from lmcache.v1.cache_identity import ObjectKeyIdentity, decode_tags
from lmcache.v1.distributed.api import ObjectKey, ipc_key_to_object_keys
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


def test_identity_and_immutable_tags() -> None:
    tags = {"tenant": "a", "version": "1"}
    identity = ObjectKeyIdentity(
        chunk_hash=b"1234", kv_rank=1, model_name="model", tags=tags
    )
    key = ObjectKey(identity=identity)
    same = replace(key, identity=replace(identity, tags=dict(reversed(tags.items()))))
    assert key == same and hash(key) == hash(same)
    assert key.to_storage_key() == same.to_storage_key()
    tags["tenant"] = "b"
    assert identity.tags["tenant"] == "a"
    with pytest.raises(TypeError, match="immutable"):
        identity.tags["tenant"] = "b"  # type: ignore[index]
    assert key != replace(key, identity=replace(identity, tags=tags))
    assert key != replace(key, identity=replace(identity, model_name="another"))
    assert key != replace(key, identity=replace(identity, cache_salt="tenant-b"))
    assert key != ObjectKey(identity=replace(identity, chunk_hash=b"5678"))
    assert key != ObjectKey(identity=replace(identity, kv_rank=2))
    assert key != ObjectKey(identity=replace(identity, object_group_id=1))
    assert decode_tags(identity.tags_token()) == identity.tags
    assert (
        ObjectKeyIdentity(
            chunk_hash=b"1234", kv_rank=1, model_name="model"
        ).tags_token()
        == ""
    )


@pytest.mark.parametrize("token", ["x2-abc", "x1-!", "x1-e30"])
def test_identity_rejects_invalid_tokens(token: str) -> None:
    with pytest.raises(ValueError):
        decode_tags(token)


@pytest.mark.parametrize("tags", [{"": "v"}, {"a": 1}])
def test_invalid_tags(tags: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        ObjectKeyIdentity(chunk_hash=b"1234", kv_rank=1, model_name="model", tags=tags)


def test_identity_transport_and_object_expansion() -> None:
    ipc = IPCCacheServerKey.from_token_ids(
        "model",
        2,
        None,
        [1, 2],
        end=2,
        tags={"tenant": "a", "app": "v1"},
    )
    for codec in (msgspec.msgpack, msgspec.json):
        decoded = codec.decode(codec.encode(ipc), type=IPCCacheServerKey)
        assert decoded == ipc and hash(decoded) == hash(ipc)
        assert list(decoded.identity.tags) == ["app", "tenant"]
        assert decoded.identity.tags_token() == ipc.identity.tags_token()
        groups = ipc_key_to_object_keys(decoded, [b"1234", b"5678"], [0, 1])
        assert len(groups) == 2 and all(len(group) == 4 for group in groups)
        for key in (key for group in groups for key in group):
            assert key.identity.model_name == ipc.identity.model_name
            assert key.identity.tags == ipc.identity.tags
            encoded = key.to_encoded_object_key()
            assert (
                codec.decode(codec.encode(encoded), type=type(encoded)).to_object_key()
                == key
            )
            assert decode_key(encode_key(key)) == key
    assert (
        replace(
            ipc, request_id="another", request_configs={"hint": 1}, num_kv_readers=3
        )
        == ipc
    )
    legacy = msgspec.to_builtins(ipc)
    del legacy["identity"]
    with pytest.raises(msgspec.ValidationError, match="identity"):
        msgspec.convert(legacy, type=IPCCacheServerKey)


def test_identity_protobuf_roundtrip() -> None:
    identity = ObjectKeyIdentity(
        chunk_hash=b"1234",
        kv_rank=0,
        model_name="model",
        tags={"tenant": "a", "app": "v1"},
    )
    ipc = IPCCacheServerKey.from_token_ids("model", 1, 0, [1], tags=identity.tags)
    key = ObjectKey(identity=identity)
    for message_type, value in (
        (common_pb2.IpcCacheServerKey, ipc),
        (p2p_service_pb2.ObjectKey, key),
    ):
        encode, decode = compile_request_codec_for_types(message_type, (type(value),))
        message = encode((value,), {})
        assert message.identity.tags["tenant"] == "a"
        assert message.identity.model_name == "model"
        (recovered,) = decode(message_type.FromString(message.SerializeToString()))
        assert recovered == value and hash(recovered) == hash(value)
        assert list(recovered.identity.tags) == ["app", "tenant"]
        assert recovered.identity.tags_token() == identity.tags_token()
    _, decode = compile_request_codec_for_types(p2p_service_pb2.ObjectKey, (ObjectKey,))
    (legacy,) = decode(
        p2p_service_pb2.ObjectKey(
            identity=common_pb2.ObjectKeyIdentity(
                model_name="model", chunk_hash=b"1234"
            )
        )
    )
    assert legacy.identity == ObjectKeyIdentity(
        chunk_hash=b"1234", kv_rank=0, model_name="model"
    )


def test_session_release_checks_identity() -> None:
    lookup = IPCCacheServerKey.from_token_ids(
        "model",
        1,
        None,
        [1],
        end=1,
        tags={"dtype": "bf16"},
    )
    session = Session("r", TokenHasher(chunk_size=1))
    session.begin_lookup(lookup, (-1,))
    session.record_prefetch_result(1, (0,))
    worker = replace(lookup, identity=replace(lookup.identity, worker_id=0))
    snapshot = session.prepare_failed_retrieve_release(worker)
    assert snapshot is not None
    wrong = replace(worker, identity=replace(worker.identity, tags={"dtype": "fp8"}))
    assert session.prepare_failed_retrieve_release(wrong) is None
    assert not session.claim_failed_retrieve_release(1, wrong, snapshot[-1])
    assert session.claim_failed_retrieve_release(1, worker, snapshot[-1])
