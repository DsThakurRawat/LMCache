# Key attributes on ObjectKey and IPC keys

Status: draft implementation for API review, motivated by
[PR #5615](https://github.com/LMCache/LMCache/pull/5615).

## API and matching

`ObjectKey`, `IPCCacheServerKey` and `EncodedObjectKey` directly contain three
collections of the same `KeyAttribute(name: str, value: str)` type:

| Field | Participates in matching | Interpreted by other modules |
| --- | --- | --- |
| `identity` | yes | no requirement |
| `metadata` | no | yes |
| `named_identity` | yes | yes |

There is no container between the key and its attributes. All three collections
have names, including identity-only attributes. Names make composition explicit
and prevent matching from depending on a producer's append order. Names and
values in both matching categories participate in equality and hashing.
The difference between the matching categories is whether modules interpret
the values; their representation and matching rules are the same.

Python uses immutable tuples of frozen `KeyAttribute` values. Each key sorts
all three collections by name and rejects duplicate names within a collection.
Names must be non-empty strings; values must be strings. Producers own typed,
versioned schemas and canonical string encodings for structured values.
Metadata is excluded from equality, hashing and IPC-key ordering.

```python
key = IPCCacheServerKey.from_token_ids(
    "model", 1, 0, [1, 2], end=2,
    identity=(KeyAttribute("kv.precision.v1", "bf16"),),
    metadata=(KeyAttribute("trace.id", "request-123"),),
    named_identity=(KeyAttribute("lmcache.codec.v1", "raw"),),
)
```

The protobuf representation is equally direct:

```protobuf
message KeyAttribute {
  string name = 1;
  string value = 2;
}
// Inside IpcCacheServerKey:
repeated KeyAttribute identity = 11;
repeated KeyAttribute metadata = 12;
repeated KeyAttribute named_identity = 13;
```

ObjectKey uses the same three repeated fields. JSON and msgspec serialize the
three collections directly on the key. Attributes propagate through worker-free
keys, rank/group expansion, JSON projections, temporary serde keys and P2P.
Session lock-release ownership checks both matching collections; store batching
also includes both so incompatible layouts cannot share a serde allocation.
Coordinator captures retain matching attributes, pins retain all fields, and
traces retain all fields.

## Metadata ownership

Metadata is attached to the current operation and is not an authoritative object
header. A dictionary can retain an earlier equal key's metadata; consumers must
read current hints from the incoming key. Disk recovery does not restore
metadata. Properties needed to decode or safely use stored bytes belong in
`named_identity` or a separately designed payload header. Do not put secrets in
matching attributes, which are visible in object names and diagnostics.

## Storage representation

Storage codecs share stateless functions to encode/decode matching attributes;
there is no additional wrapper type. The existing model/rank/group/hash fields,
escaping and sharding remain backend-specific. Their common suffix is:

```text
empty matching attributes, no salt: <existing four fields>
empty matching attributes, salt:    <existing four fields>@<salt>
matching attributes:               <existing four fields>@<salt>@x1-<token>
```

The salt placeholder remains even when empty, avoiding collision with a legacy
salted key. The token is unpadded base64url of compact JSON
`[identity_pairs, named_identity_pairs]`, where each pair is `[name, value]` and
each collection is sorted by name. Metadata is excluded. Names and values are
both preserved, so FS/S3 listings and raw-block recovery reconstruct complete
matching attributes without a catalog or sidecar. Unknown versions, malformed
schemas, duplicate names and noncanonical encodings are rejected.

All L2 naming paths include both matching collections: native connectors,
filesystem, raw-block, S3, HF bucket, Bigtable (including custom templates),
SageMaker and dynamic NIXL. Delegating adapters inherit these codecs. Bigtable
retains an empty salt placeholder when appending matching attributes. Native
C++ preserves the opaque token during filename conversion.

Long attributes increase filename length. Python/native FS reject extended
names exceeding 255 UTF-8 bytes before I/O. Use compact, versioned digests for
large matching descriptions; keep module-readable matching values compact.
Metadata does not lengthen storage names.

## Precision integration and rollout

This PR implements the attribute mechanism. It does not activate vLLM precision
isolation. A precision producer should supply a deterministic digest of a typed,
versioned description of the resolved byte representation. Hashing raw aliases
alone does not establish compatibility: `auto` and explicit BF16 may resolve to
the same bytes, while FP8 aliases can differ across CUDA and ROCm. Scale/layout
resolution remains the producer's responsibility.

Empty collections are the default and preserve legacy storage names. Upgrade
clients, servers and P2P peers together before enabling matching attributes;
older peers may ignore new fields. This PR does not negotiate capabilities.
Extended keys deliberately miss legacy entries whose precision is unknown and
never fall back to unqualified legacy names. Existing objects are not rewritten.

Existing cache_salt, request_id and request_configs APIs remain in place.
Token-addressed cache-control and CacheBlend producer APIs still address the
empty-attribute namespace; their activation contracts must be updated with the
precision producer if it uses those APIs. Explicit EncodedObjectKey control APIs
already carry the three collections.

Tests cover order-independent matching, name/value sensitivity, metadata
independence, validation, direct msgspec/protobuf fields, key propagation,
storage recovery, native/Python codec parity, session ownership and coordinator
capture/pins. Mixed BF16/FP8 inference requires GPU validation when the precision
producer is integrated.
