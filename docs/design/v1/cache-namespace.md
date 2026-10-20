# Cache namespaces and storage identity

Status: draft, motivated by [PR #5615](https://github.com/LMCache/LMCache/pull/5615).

## Model

`ObjectKey.namespace` is a `CacheNamespace` shared with `IPCCacheServerKey` and
`EncodedObjectKey`. Every namespace field participates in equality, hashing and
persistent storage identity:

```python
namespace = CacheNamespace(
    kv_encoding=KVCacheEncoding(dtype="bfloat16", layout="NHD"),
    tags={"adapter_revision": "abc123"},
)
```

`kv_encoding` has explicit typed fields for consumers that need to interpret the
KV representation. Producers supply resolved dtype and layout names; the model
does not infer compatibility from user aliases. `None` means unspecified, not a
guessed representation. Add future interpreted properties as typed fields rather
than serialized classes inside string attributes.

`tags` is a string-to-string map for additional opaque identity dimensions.
Construction copies and freezes the supplied map. Callers read it as a
`Mapping[str, str]`; insertion order does not affect identity or storage names.
The dict-backed immutable snapshot allows msgspec to serialize it without custom
transport hooks. Names must be non-empty and values must be strings.

Non-matching information belongs to its owner, outside `ObjectKey`: request
configuration and session tracking remain on the request, while durable object
metadata belongs in an object header or descriptor. This PR does not introduce
an object-metadata persistence contract.

## Request and object keys

`IPCCacheServerKey` describes a token range and request context. The server hashes
chunks and expands ranks and object groups into individual `ObjectKey` values.
The conversion carries the complete namespace. Session release checks and store
batch grouping also include it.

Msgspec uses the same Python value objects. Protobuf defines `CacheNamespace`
with an optional `KVCacheEncoding` message and `map<string, string> tags`. Both
engine/server and P2P key messages carry the namespace. Traces, coordinator
captures and pins, encoded keys and temporary serde keys preserve it too.

## Storage API

Backends call `ObjectKey.to_storage_key()`, `to_filename()` or
`format_storage_key()` rather than selecting namespace fields themselves.
`from_storage_key()` and `from_filename()` restore the namespace. The formatter
retains existing backend templates, model escaping and rank formatting; it adds
the namespace token even when a custom Bigtable template omits that field.

```text
empty namespace, no salt: <existing four fields>
empty namespace, salt:    <existing four fields>@<salt>
nonempty namespace:       <existing four fields>@<salt>@x1-<token>
```

The token is unpadded base64url of the namespace's compact JSON, with tags sorted
by name. It is reversible so storage recovery retains typed properties. Decoding
rejects unsupported versions and noncanonical payloads. The salt placeholder is
present even when empty, preventing collision with a legacy salted key.

FS, native connectors, S3, Bigtable, HF bucket, SageMaker, raw-block and dynamic
NIXL retain their existing names for empty namespaces. Native `keys.h` accepts
and preserves the extra opaque token; it does not interpret namespace fields.
Python/native FS reject extended filenames exceeding 255 UTF-8 bytes. Keep
identity values compact; large descriptions should use producer-computed digest
tags, while interpreted object metadata needs a separate storage contract.

## Scope and rollout

This PR provides the identity model and end-to-end propagation, including L2. It
does not activate a vLLM precision producer or define exhaustive cross-engine KV
compatibility. Integration must describe resolved bytes, including relevant
scales/layouts, and normalize equivalent aliases before constructing namespaces.

Empty namespaces preserve legacy names. Upgrade clients, servers and P2P peers
together before enabling nonempty namespaces: older peers can ignore unknown
fields. This PR adds neither capability negotiation nor fallback to legacy
objects of unknown representation. Existing objects are not rewritten.

Token-addressed cache-control and CacheBlend producer APIs still address the
empty namespace. Explicit `EncodedObjectKey` APIs carry namespaces; enabling the
precision producer must update its other entry points as needed.

Tests cover immutable/order-independent tags, matching, protocol propagation,
session ownership, coordinator recovery, L2 round trips and native/Python codec
parity. Mixed-precision inference requires validation with the eventual producer.
