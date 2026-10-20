# SPDX-License-Identifier: Apache-2.0
"""Cache namespace identity and transport contracts."""

# Standard
from dataclasses import replace

# Third Party
import msgspec
import pytest

# First Party
from lmcache.v1.cache_namespace import CacheNamespace, KVCacheEncoding
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


def test_namespace_identity_and_immutable_tags() -> None:
    tags = {"tenant": "a", "version": "1"}
    namespace = CacheNamespace(KVCacheEncoding("bfloat16", "NHD"), tags)
    key = ObjectKey(b"1234", "model", 1, namespace=namespace)
    same = replace(key, namespace=replace(namespace, tags=dict(reversed(tags.items()))))
    assert key == same and hash(key) == hash(same)
    assert key.to_storage_key() == same.to_storage_key()
    tags["tenant"] = "b"
    assert namespace.tags["tenant"] == "a"
    with pytest.raises(TypeError, match="immutable"):
        namespace.tags["tenant"] = "b"  # type: ignore[index]
    assert key != replace(key, namespace=replace(namespace, tags=tags))
    assert key != replace(
        key, namespace=replace(namespace, kv_encoding=KVCacheEncoding("fp8", "NHD"))
    )
    assert CacheNamespace.from_token(namespace.to_token()) == namespace
    assert CacheNamespace().to_token() == ""


@pytest.mark.parametrize("token", ["x2-abc", "x1-!", "x1-e30"])
def test_namespace_rejects_invalid_tokens(token: str) -> None:
    with pytest.raises(ValueError):
        CacheNamespace.from_token(token)


@pytest.mark.parametrize("tags", [{"": "v"}, {"a": 1}])
def test_invalid_tags(tags: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        CacheNamespace(tags=tags)


def test_namespace_transport_and_object_expansion() -> None:
    ipc = IPCCacheServerKey.from_token_ids(
        "model",
        2,
        None,
        [1, 2],
        end=2,
        namespace=CacheNamespace(KVCacheEncoding("bfloat16", "NHD"), {"tenant": "a"}),
    )
    for codec in (msgspec.msgpack, msgspec.json):
        decoded = codec.decode(codec.encode(ipc), type=IPCCacheServerKey)
        assert decoded == ipc and hash(decoded) == hash(ipc)
        groups = ipc_key_to_object_keys(decoded, [b"1234", b"5678"], [0, 1])
        assert len(groups) == 2 and all(len(group) == 4 for group in groups)
        for key in (key for group in groups for key in group):
            assert key.namespace == ipc.namespace
            encoded = key.to_encoded_object_key()
            assert (
                codec.decode(codec.encode(encoded), type=type(encoded)).to_object_key()
                == key
            )
            assert decode_key(encode_key(key)) == key
    assert replace(ipc, request_id="another", request_configs={"hint": 1}) == ipc
    legacy = msgspec.to_builtins(ipc)
    del legacy["namespace"]
    assert msgspec.convert(legacy, type=IPCCacheServerKey).namespace == CacheNamespace()


def test_namespace_protobuf_roundtrip() -> None:
    namespace = CacheNamespace(KVCacheEncoding("bfloat16", "NHD"), {"tenant": "a"})
    ipc = IPCCacheServerKey.from_token_ids("model", 1, 0, [1], namespace=namespace)
    key = ObjectKey(b"1234", "model", 0, namespace=namespace)
    for message_type, value in (
        (common_pb2.IpcCacheServerKey, ipc),
        (p2p_service_pb2.ObjectKey, key),
    ):
        encode, decode = compile_request_codec_for_types(message_type, (type(value),))
        message = encode((value,), {})
        assert message.namespace.tags["tenant"] == "a"
        assert message.namespace.kv_encoding.dtype == "bfloat16"
        (recovered,) = decode(message_type.FromString(message.SerializeToString()))
        assert recovered == value and hash(recovered) == hash(value)
    _, decode = compile_request_codec_for_types(p2p_service_pb2.ObjectKey, (ObjectKey,))
    (legacy,) = decode(
        p2p_service_pb2.ObjectKey(chunk_hash=b"1234", model_name="model")
    )
    assert legacy.namespace == CacheNamespace()


def test_session_release_checks_namespace() -> None:
    lookup = IPCCacheServerKey.from_token_ids(
        "model", 1, None, [1], end=1, namespace=CacheNamespace(tags={"dtype": "bf16"})
    )
    session = Session("r", TokenHasher(chunk_size=1))
    session.begin_lookup(lookup, (-1,))
    session.record_prefetch_result(1, (0,))
    worker = replace(lookup, worker_id=0)
    snapshot = session.prepare_failed_retrieve_release(worker)
    assert snapshot is not None
    wrong = replace(worker, namespace=CacheNamespace(tags={"dtype": "fp8"}))
    assert session.prepare_failed_retrieve_release(wrong) is None
    assert not session.claim_failed_retrieve_release(1, wrong, snapshot[-1])
    assert session.claim_failed_retrieve_release(1, worker, snapshot[-1])
