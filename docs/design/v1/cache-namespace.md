# Cache namespaces and storage identity

Status: draft, motivated by [PR #5615](https://github.com/LMCache/LMCache/pull/5615).

## Model and ownership

`CacheNamespace` owns the identity shared by requests and stored objects:

```python
namespace = CacheNamespace(
    model_name="org/model",
    cache_salt="tenant-a",
    tags={"adapter_revision": "abc123"},
)
key = ObjectKey(chunk_hash=b"1234", namespace=namespace, kv_rank=0)
```

`model_name` selects the model, `cache_salt` isolates users, and `tags` adds
opaque string-valued identity dimensions. All three participate in equality,
hashing and ordering. Tags are copied, sorted by name and frozen at construction,
so insertion order and later changes to the input dictionary cannot change key
identity. Msgspec serializes the immutable dict snapshot without custom hooks.

`ObjectKey`, `EncodedObjectKey` and `IPCCacheServerKey` store the namespace once.
Their read-only `model_name` and `cache_salt` properties forward to it. The outer
object key retains `chunk_hash`, `kv_rank` and `object_group_id`: those identify
the concrete chunk, shard and group within the cache namespace. IPC keys retain
token ranges, parallelism and request context instead; expansion carries the
same namespace into each object key.

Model-name and salt validation live in `CacheNamespace`. Model names exclude
`@`; salts exclude `@`, `/`, `\` and NUL and are limited to 128 characters.
These constraints preserve existing backend key formats.

Non-matching information belongs to its request or object descriptor, outside
ObjectKey. This PR does not introduce a durable metadata header or a speculative
KV encoding schema. Add interpreted identity properties as explicit typed fields
when their producer/consumer and compatibility rules are established.

## Protocol and propagation

Msgspec and protobuf encode the namespace as a nested value with `model_name`,
`cache_salt` and a string-map `tags`. Removed outer protobuf fields are reserved.
Clients, servers, P2P peers and control-plane consumers must upgrade together;
the new request/key wire shape requires `namespace` rather than flat identity
fields. Read-only Python access properties do not preserve old constructor or
wire formats. Namespace validation also occurs during HTTP request parsing
(`422` for invalid nested identity fields); invalid chunk hex is still rejected
by key conversion (`400`).

Session release checks and store batching use the complete namespace. Traces,
coordinator captures/pins, encoded keys and temporary serde keys preserve it.
Existing positional coordinator captures and flattened trace/pin records remain
readable; new JSON key projections contain the nested namespace.

## Storage API and compatibility

Adapters call `ObjectKey.to_storage_key()`, `to_filename()` or
`format_storage_key()`. Decoding and dynamic NIXL sharding also use key methods;
adapters do not select namespace fields for storage identity.

```text
no tags, no salt: <model>@<rank>@<group>@<hash>
no tags, salt:    <model>@<rank>@<group>@<hash>@<salt>
tags:            <model>@<rank>@<group>@<hash>@<salt>@x1-<token>
```

Model and salt retain their original prefix positions. The token is unpadded
base64url of the compact JSON tag map, sorted by name. Decoding uses the prefix
and token to reconstruct one complete namespace. The empty salt placeholder
prevents collision with legacy salted keys. Unknown versions, malformed tag maps
and noncanonical tokens are rejected.

Untagged names remain unchanged across FS, native connectors, S3, Bigtable,
HF bucket, SageMaker, raw-block and dynamic NIXL. Native `keys.h` only preserves
the opaque token. Python/native FS reject extended names exceeding 255 UTF-8
bytes. Existing untagged objects are not rewritten. Tagged formats in this draft
are not a released storage compatibility contract.

## Scope and validation

This PR provides the identity model and propagation, including L2. It does not
activate an engine precision producer or establish cross-engine KV compatibility.
Token-addressed cache-control and CacheBlend producer APIs continue to use the
untagged namespace until their integration explicitly supplies tags.

Tests cover sorted immutable tags, model/salt isolation, protocol round trips,
session ownership, coordinator/trace recovery and Python/native storage parity.
Existing tests and fixtures migrate to the nested identity model; no hardware
inference claim is made by these CPU checks.
