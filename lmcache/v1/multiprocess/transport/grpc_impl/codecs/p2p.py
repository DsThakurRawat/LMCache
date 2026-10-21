# SPDX-License-Identifier: Apache-2.0
"""Custom protobuf codecs owned by the P2P gRPC service."""

# Third Party
import torch

# First Party
from lmcache.v1.cache_identity import ObjectKeyIdentity
from lmcache.v1.distributed.api import ObjectKey
from lmcache.v1.multiprocess.transport.grpc_impl._proto_gen import p2p_service_pb2
from lmcache.v1.multiprocess.transport.grpc_impl.codecs.base import (
    RegisteredMessageCodec,
)


def _write_tensor_shape(
    message: p2p_service_pb2.TensorShape, value: torch.Size
) -> None:
    message.dims.extend(value)


def _read_tensor_shape(message: p2p_service_pb2.TensorShape) -> torch.Size:
    return torch.Size(message.dims)


def _write_object_key(message: p2p_service_pb2.ObjectKey, value: ObjectKey) -> None:
    identity = message.identity
    identity.chunk_hash = value.chunk_hash
    identity.kv_rank = value.kv_rank
    identity.model_name = value.model_name
    identity.object_group_id = value.object_group_id
    identity.cache_salt = value.cache_salt
    identity.tags.update(value.identity.tags)


def _read_object_key(message: p2p_service_pb2.ObjectKey) -> ObjectKey:
    identity = message.identity
    return ObjectKey(
        identity=ObjectKeyIdentity(
            chunk_hash=identity.chunk_hash,
            kv_rank=identity.kv_rank,
            model_name=identity.model_name,
            object_group_id=identity.object_group_id,
            cache_salt=identity.cache_salt,
            tags=identity.tags,
        )
    )


def get_message_codecs() -> tuple[
    RegisteredMessageCodec[p2p_service_pb2.TensorShape, torch.Size],
    RegisteredMessageCodec[p2p_service_pb2.ObjectKey, ObjectKey],
]:
    """Return custom codecs used by the P2P protobuf service.

    Returns:
        Explicit registrations for P2P non-structural message types.
    """
    return (
        RegisteredMessageCodec(
            protobuf_type="lmcache.mp.TensorShape",
            python_type=torch.Size,
            writer=_write_tensor_shape,
            reader=_read_tensor_shape,
        ),
        RegisteredMessageCodec(
            protobuf_type="lmcache.mp.ObjectKey",
            python_type=ObjectKey,
            writer=_write_object_key,
            reader=_read_object_key,
        ),
    )
