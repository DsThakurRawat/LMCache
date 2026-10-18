# Extensible ObjectKey attributes

Status: draft implementation for API review.

## Problem and scope

[PR #5615](https://github.com/LMCache/LMCache/pull/5615) identifies a real
collision: BF16 and FP8 KV data can share a model name and token hash, despite
having incompatible bytes. Adding a dedicated `cache_format` member fixes one
case but requires changes to each key schema and codec for every future
attribute. This proposal adds one reusable `extensions` container to ObjectKey,
IPCCacheServerKey and EncodedObjectKey.

This PR implements the extension mechanism and its transport/storage paths.
It does not activate vLLM precision isolation or replace the engine's precision
resolution logic. #5615 can populate the container instead of adding a dedicated
field. Existing cache_salt, request_configs and request_id APIs stay in place;
migrating them would change established ownership and compatibility contracts.

## Three categories

| Attribute | Representation | Equality/hash/order | Other modules read it | Persisted in storage key |
| --- | --- | --- | --- | --- |
| Opaque identity | ordered tuple of strings | yes | producer need not expose a name | yes |
| Named metadata | tuple of (name, string value) | no | yes | no |
| Named identity | tuple of (name, string value) | yes, including names | yes | yes |

All categories default to empty. `KeyExtensions` is frozen and copies input
containers to tuples. Named categories are sorted by name and reject duplicates,
empty names and overlapping names between metadata and named identity. String
values avoid Python repr(), float and engine-specific object serialization.
A producer that needs structured values owns a typed schema and a canonical
string encoding, including its schema version. There is no automatic hashing of
arbitrary Python objects.

For a fixed core key K:

```text
match(K, A, B) =
    A.identity == B.identity AND A.named_identity == B.named_identity
```

Metadata is also excluded from ordering, so IPC keys remain sortable and
hashable. Two opaque values in different positions are different identities:
slots must have a stable meaning agreed by producers. Prefer one versioned,
composite digest when several modules contribute compatibility factors; do not
append independently in execution-dependent order. Named identity is suitable
when independent modules must compose or inspect attributes.

Names should use a module-owned prefix and include a schema version where their
meaning can evolve, such as `lmcache.codec.v1`. Classification is part of the
schema: moving an attribute from metadata to identity creates a new cache
namespace and must be deployed deliberately.

## Example: precision, tracing and a codec

```python
from lmcache.v1.key_extensions import KeyExtensions

extensions = KeyExtensions(
    identity=("kv-precision-v1:<canonical-precision-digest>",),
    metadata=(("trace.id", "request-123"),),
    named_identity=(("lmcache.codec.v1", "raw"),),
)
```

The precision producer computes a deterministic engine-neutral digest from a
typed, versioned description of the **resolved byte representation**. The digest
is opaque to storage. A codec that needs to choose a decoder reads
`dict(key.extensions.named_identity)["lmcache.codec.v1"]`; changing the codec
also changes identity. Changing a trace ID does not affect cache hits.

A digest of raw user settings can conservatively isolate configurations, but
cannot establish cross-engine compatibility. `auto` and explicit BF16 can
resolve to the same format; FP8 aliases can resolve differently across CUDA and
ROCm. Resolving scales, layouts and engine-specific formats remains the producer's
responsibility. The generic container neither equates nor guesses these formats.

## Propagation and ownership

```text
producer -> IPCCacheServerKey.extensions -> msgspec / gRPC
         -> worker-free lookup key -> rank/group expansion -> ObjectKey
         -> L1 equality and session ownership comparisons
         -> L2 identity encoding / P2P full-key encoding
```

The same container is passed through both legacy and grouped object-key
expansion, temporary serde keys and JSON-safe projections. Session matching
checks extensions before claiming a failed retrieve's lock release. Store
batching includes matching extensions so different precision/layout namespaces
cannot share a serde allocation based only on the first object's layout. ZMQ/msgspec
and gRPC preserve all three categories; nested protobuf messages use the same
structural codecs as the existing keys. Coordinator captures persist matching
attributes; diagnostic traces preserve all attributes.

Metadata belongs to the current operation. It is not an authoritative object
header: an equal key retained in a dict may contain an earlier operation's
metadata, and disk recovery has no metadata to restore. Consumers must read
operation hints from the incoming key, not from an existing dict's key object.
Persistent properties required to decode or safely use bytes belong in named
identity (or a separately designed payload header). Do not put secrets in keys;
matching attributes are visible in object names and diagnostic data.

## Storage encoding

Existing encoders keep their model/rank/group/hash formatting, including backend
specific escaping and sharding. They share the extension suffix:

```text
no identity extension, no salt: <existing four core fields>
no identity extension, salt:    <existing four core fields>@<salt>
identity extension:            <existing four core fields>@<salt>@x1-<token>
```

The salt placeholder is mandatory for extended keys even when empty. `token` is
unpadded base64url of compact JSON `[identity, named_identity]`. Named entries
are sorted; metadata is excluded. Version `x1-` fixes the serialization schema.
Decoders reject unknown versions, invalid types and noncanonical encodings
rather than silently dropping identity. Empty matching categories produce no
token, even when metadata is present: legacy storage names remain byte-for-byte
unchanged. Recovery reconstructs both opaque and named matching attributes.

This deliberately uses a reversible representation instead of an opaque digest
of all attributes: filesystem/S3 listings and raw-block recovery must reconstruct
named identity without an additional index or sidecar. A digest-only filename
would need a separately durable identity/metadata catalog. Native C++ treats the
versioned token as opaque and preserves it through filename conversion.

All independent L2 encoders include matching extensions: native connectors,
filesystem, raw-block, S3, HF bucket, Bigtable (including custom templates),
SageMaker and dynamic NIXL names. Valkey and other adapters that delegate to
these helpers inherit their behavior. Bigtable templates receive a trailing
extension token even if the user template predates extensions.

Long extensions can exceed filesystem NAME_MAX. Python FS and native FS reject
extended names exceeding 255 UTF-8 bytes before I/O, rather than truncating and
creating collisions. Producers should use compact digests for opaque factors;
named values intended for filesystem storage must stay compact. Large metadata
does not lengthen filenames. A future catalog-backed format can remove this
size limit without changing the three semantic categories.

## Rollout

Empty extensions are the default and preserve existing storage identity. No
config flag is needed for the mechanism itself. Enabling a producer's non-empty
identity is a coordinated deployment decision: upgrade clients, servers and P2P
peers together before enabling it. Older msgspec/protobuf peers may ignore new
fields and are unsafe for non-empty extensions; this PR does not negotiate peer
capabilities. Downgrading also requires disabling producers first.

New code can read old four/five-field names. Extended keys intentionally miss
legacy entries with unknown precision. Never probe an unqualified legacy key
on an extended-key miss: the original BF16/FP8 collision could return. This PR
does not move, delete, or rewrite existing objects.

Token-addressed cache-control APIs and CacheBlend producer schemas do not yet
accept extension parameters; their default namespace remains empty. Explicit
EncodedObjectKey control APIs preserve extensions. The engine integration that
activates precision identity must also extend its token-based control and blend
namespace APIs if it uses them. This draft keeps activation separate so those
producer contracts can be reviewed with the resolved precision schema.

## Validation

Tests cover the three matching semantics, frozen containers, canonical name
ordering, invalid inputs and tokens, legacy names, msgspec and protobuf
round trips, rank/group expansion, serde temporary keys, filesystem/S3 recovery,
raw-block slot identity, coordinator capture and native C++ filename parity.
CPU validation cannot prove GPU KV byte compatibility; the eventual precision
producer requires mixed BF16/FP8 shared-store GPU tests before activation.
