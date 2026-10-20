# Cache key identity

## Identity and metadata

Each key owns a complete, typed `identity`. A field belongs there when it
participates in matching; interpreted attributes use explicit fields, while
opaque matching dimensions use `tags`.

- `ObjectKeyIdentity`: `chunk_hash`, `kv_rank`, `model_name`, `object_group_id`,
  `cache_salt`, `tags`.
- `IPCKeyIdentity`: `world_size`, `worker_id`, `token_ids`, `start`, `end`,
  `model_name`, `cache_salt`, `tags`.

These are separate types because requests address token ranges and workers,
whereas stored objects address chunk hashes, KV ranks and object groups. They
share tag normalization, not a common identity container or base class.
`ObjectKey` stores only its identity. `IPCCacheServerKey` additionally carries
`request_id`, `request_configs` and `num_kv_readers`, excluded from matching.
Read-only properties on the keys forward existing field reads to the identity;
they do not duplicate state.

```python
from lmcache.v1.cache_identity import ObjectKeyIdentity
from lmcache.v1.distributed.api import ObjectKey

key = ObjectKey(identity=ObjectKeyIdentity(
    chunk_hash=b"1234", kv_rank=0, model_name="org/model",
    cache_salt="tenant-a", tags={"adapter_revision": "abc123"},
))
```

Tags are a copied, immutable mapping sorted by name. Insertion order cannot
change equality, hashing, serialization or persistent names. Model names exclude
`@`; salts exclude `@`, `/`, `\`, NUL and are at most 128 characters.
The object group id must be nonnegative.

## Conversion and transport

IPC-to-object expansion explicitly copies model, salt and tags, hashes tokens,
and expands worker/rank and object group coordinates. It constructs a new
`ObjectKeyIdentity`; the two identity types are never interchangeable.
Temporary serde keys replace only the identity's chunk hash. Session lock
release compares model, salt, tags, world size and tokens, then checks the
requested subrange; it cannot require complete identity equality because a
retrieve selects a worker and may narrow the lookup range. Store batching
similarly groups by rank, model, salt and tags rather than by complete identity,
so different chunks still share a batch.

`EncodedObjectKeyIdentity` is the JSON projection of `ObjectKeyIdentity`, using
`chunk_hash_hex` instead of bytes. `EncodedObjectKey` wraps this projection as
`identity`. Msgspec and protobuf IPC/P2P schemas likewise carry the appropriate
typed identity. These constructor and wire changes require coordinated client,
server, P2P and control-plane upgrades. Old protobuf field numbers are reserved.
Invalid nested fields fail HTTP body validation (`422`); invalid hex fails key
conversion (`400`).

Coordinator captures retain their positional format. Trace and pin decoders
also accept pre-PR flattened records; new records use nested `identity`.

## Storage encoding

L2 adapters call `ObjectKey.to_storage_key()`, `to_filename()` or
`format_storage_key()`, and decoding/sharding use key methods. Adapters do not
select individual identity fields.

```text
no tags, no salt: <model>@<rank>@<group>@<hash>
no tags, salt:    <model>@<rank>@<group>@<hash>@<salt>
tags:            <model>@<rank>@<group>@<hash>@<salt>@x1-<token>
```

The token is unpadded base64url of the compact JSON tag map sorted by name.
The empty salt placeholder prevents aliasing a legacy salted key. Unknown
versions, malformed maps and noncanonical tokens are rejected. Existing
untagged names remain unchanged. Native `keys.h` preserves the opaque tag token;
Python/native FS reject extended filenames exceeding 255 UTF-8 bytes.

## Scope and validation

This PR provides the identity model and propagation, including L2. It does not
predefine KV encoding attributes or activate an engine precision producer.
Interpreted properties need real producer/consumer contracts before being added.
Tests cover immutable sorted tags, identity matching, IPC/object conversion,
protocol round trips, sessions, batching, recovery and Python/native storage
parity. CPU validation does not establish hardware inference correctness.
