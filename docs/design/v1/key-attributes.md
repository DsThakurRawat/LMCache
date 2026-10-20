# Key attributes: generic transport, module-owned schemas

Status: draft API, motivated by [PR #5615](https://github.com/LMCache/LMCache/pull/5615).

## Categories and names

`ObjectKey`, `IPCCacheServerKey` and `EncodedObjectKey` directly hold three
collections of the same `KeyAttribute(name: str, value: str)` type:

| Field | Participates in matching | Module interpretation |
| --- | --- | --- |
| `opaque_identity` | yes | values are opaque outside the producer |
| `metadata` | no | values may be interpreted by a consuming module |
| `identity_metadata` | yes | values may be interpreted by a consuming module |

All categories have names, so `named_identity` would not distinguish the third
category. `opaque_identity` describes the first category's consumer contract;
`identity_metadata` describes the intersection of metadata and matching identity.
These names describe semantics, not whether a value happens to be JSON or a hash.
For example, a versioned precision digest belongs in `opaque_identity`, while a
codec description that a deserializer must read belongs in `identity_metadata`.

Python uses immutable tuples of frozen attributes; protobuf uses three direct
`repeated KeyAttribute` fields. The key sorts each category by name. Names must
be non-empty strings and must be unique across the entire key, preventing the
same property from carrying conflicting values in two categories.

Names and values in both matching categories participate in equality and hashing.
Metadata is excluded from equality, hashing and IPC-key ordering. The category
is also part of identity: moving a property between the two matching collections
changes the namespace. Categories are stable schema decisions, not something
that changes when a new consumer starts reading a value.

## Module-owned structured values

The key/transport layer preserves names and strings. A consuming module owns the
class, fields, validation rules, defaults and schema version for a structured
value. It parses once at its boundary rather than spreading string lookups and
conversions through business code. Simple scalar attributes do not need a class.

`encode_typed_attribute` and `decode_typed_attribute` are stateless helpers for
this boundary. They do not introduce a wrapper, registry, inheritance requirement
or domain-specific fields on ObjectKey. A module can use a dataclass or a
`msgspec.Struct`; it decides whether unknown fields are allowed.

The following is an illustrative integration-owned schema, not a new core KV
format definition or an activation of precision isolation:

```python
from typing import ClassVar, Literal
import msgspec
from lmcache.v1.key_attributes import (
    KeyAttribute, decode_typed_attribute, encode_typed_attribute,
)

class KVCacheEncoding(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
    ATTRIBUTE_NAME: ClassVar[str] = "lmcache.kv_encoding.v1"
    dtype: Literal["bfloat16", "float8_e4m3fn"]
    layout: Literal["NHD", "HND"]

    def to_attribute(self) -> KeyAttribute:
        return encode_typed_attribute(self.ATTRIBUTE_NAME, self)

    @classmethod
    def from_attribute(cls, attribute: KeyAttribute) -> "KVCacheEncoding":
        return decode_typed_attribute(attribute, cls.ATTRIBUTE_NAME, cls)
```

The producer places `encoding.to_attribute()` in `identity_metadata`. The owning
consumer locates that name and calls `KVCacheEncoding.from_attribute(attribute)`.
Unrelated modules forward it without importing the schema. The same pattern
works for `metadata`; the collection determines matching, not the Python class.
A required attribute missing at the owner boundary is an error unless the owner
explicitly defines a default. Unknown names/versions must not select a decoder
or precision layout through an implicit fallback.

The encoder produces compact JSON with sorted object keys and deterministic
unordered collection ordering. Non-finite numbers are rejected, avoiding the
NaN/infinity-to-null alias produced by some encoders. The decoder checks the
exact expected name/version and validates against the owner's type and
construction hooks. A closed Struct rejects unknown fields too. Producers must
still normalize equivalent aliases, units and defaults: deterministic JSON does
not establish semantic or cross-engine byte compatibility. Version the attribute
name whenever the schema or interpretation changes incompatibly.

## Propagation and ownership

The three fields propagate through msgspec, gRPC/P2P, worker-free keys,
rank/group expansion, JSON projections and temporary serde keys. Session
lock-release ownership and store batching include both matching categories.
Coordinator captures retain matching attributes; pins and traces retain all
three categories. Generic storage does not interpret a module's schema and
preserves even unknown attribute names and value encodings.

Non-matching metadata does **not** inherently mean transient metadata. Matching
and persistence are separate contracts. This implementation transports metadata
with operations and excludes it from storage names; it does not add a durable
object-metadata header. A module that needs object metadata after recovery must
use an object header or backend metadata contract. It should not move a
non-matching property into `identity_metadata` merely to obtain persistence.

An equal key retained in a dictionary can carry an earlier operation's metadata.
Operation hints must be read from the incoming key; persistent object metadata
must be read from the object's metadata record. Do not put secrets in matching
attributes, which are exposed in storage names and diagnostics.

## Storage representation

`encode_matching_attributes`, `decode_matching_attributes` and
`matching_attributes_suffix` explicitly operate on the matching collections.
Existing model/rank/group/hash fields, escaping and sharding remain specific to
each backend. The common suffix is:

```text
empty matching attributes, no salt: <existing four fields>
empty matching attributes, salt:    <existing four fields>@<salt>
matching attributes:               <existing four fields>@<salt>@x1-<token>
```

The salt placeholder remains even when empty to avoid collision with a legacy
salted key. The token is unpadded base64url of compact JSON
`[opaque_identity_pairs, identity_metadata_pairs]`; each pair is `[name, value]`
and each collection is sorted by name. Metadata is excluded. Unknown versions,
malformed schemas, duplicate names and noncanonical encodings are rejected.
Both matching collections are reversible, so recovery retains module-readable
values without a separate identity catalog.

All independent L2 encoders include both matching collections: native
connectors, filesystem, raw-block, S3, HF bucket, Bigtable (including custom
templates), SageMaker and dynamic NIXL. Delegating adapters inherit the codecs.
Python/native FS reject extended filenames exceeding 255 UTF-8 bytes before I/O.
Use compact digests for large opaque descriptions and keep module-readable
matching values compact; large structured metadata cannot simply be placed in
a filename without a separate payload/header design.

## Precision integration and rollout

This PR implements the attribute mechanism and typed value boundary. It does not
activate vLLM precision isolation or define an exhaustive KV compatibility
schema. The precision producer must describe the resolved byte representation,
including relevant scales and layouts. Raw user aliases alone are insufficient:
`auto` and explicit BF16 can resolve to the same bytes, while FP8 aliases can
differ across CUDA and ROCm.

Empty collections preserve legacy storage names. Upgrade clients, servers and
P2P peers together before enabling matching attributes: older peers may ignore
unknown fields, and capability negotiation is not added here. Extended keys
never fall back to legacy entries whose precision is unknown. Existing objects
are not rewritten.

Existing cache_salt, request_id and request_configs APIs stay in place.
Token-addressed cache-control and CacheBlend producer APIs still address the
empty-attribute namespace. Their activation contracts must be updated with the
precision producer if it uses them; explicit EncodedObjectKey APIs already
carry the three collections.

Tests cover typed owner schemas and invalid versions/types/fields, deterministic
JSON, non-finite rejection, unknown-schema pass-through, global name uniqueness,
matching and metadata independence, IPC/protobuf propagation, storage recovery,
native/Python codec parity and session/coordinator ownership. Mixed BF16/FP8
inference requires GPU validation with the eventual precision integration.
