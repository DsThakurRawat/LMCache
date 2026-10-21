# Cache identity and L1 xattrs

## Request transport

`IPCCacheServerKey` and its protobuf message remain unchanged from dev. Clients
use the existing `request_configs` field:

```python
request_configs = {
    "lmcache.tag.adapter_revision": "abc123",
    "lmcache.xattr.owner": "alice",
    "lmcache.xattr.priority": 1,
    "lmcache.skip_load": True,
}
```

Server-side IPC-to-object expansion strips `lmcache.tag.` into matching tags
and `lmcache.xattr.` into xattrs. Other request configurations
remain available to their existing consumers. Tags require nonempty names and
string values. Xattrs preserve their request-config values.

## Object identity and xattrs

`ObjectKeyIdentity` contains `chunk_hash`, `kv_rank`, `model_name`,
`object_group_id`, `cache_salt` and `tags`. Tags are copied into an immutable
mapping sorted by name. Insertion order cannot change equality, hashing,
serialization or storage names. Explicit interpreted identity fields remain
typed; opaque matching dimensions use tags.

`ObjectKey.xattrs` is a separate mutable dictionary, excluded from equality,
hashing and storage names. Every expanded object receives its own dictionary.
An L1 consumer can remove an attribute without changing object identity:

```python
owner = key.xattrs.pop("owner", None)
```

Changing xattrs does not create another cache entry. Model/salt validation and
nonnegative object-group validation remain on object identity. Read-only key
properties forward field reads without duplicating identity state.

## Server state and storage boundaries

IPC equality still ignores `request_configs`, as on dev. Session lock release
therefore compares extracted matching tags explicitly. Pending SHM transfers
include canonical tags in their server-side lookup key, so otherwise equal IPC
requests with different tags do not overwrite or commit each other's state.
Store batching groups by model, rank and tags, allowing compatible chunks
to share a batch.

Xattrs are available during L1 insertion. Consumers remove individual entries
with `pop`; key forwarding, store queues and temporary serde keys preserve the
dictionary. The implementation does not automatically clear xattrs.

P2P messages carry identity and encoded xattrs through the existing structural
gRPC codec. Both services upgrade together; the internal P2P schema has no
legacy field reservations. Traces preserve xattrs for operation replay.
HTTP/control-plane projections, coordinator captures/pins and persistent key
names address identity only. L2 adapters obtain names and shards through key
methods; xattrs never affect those names.

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

## Compatibility and scope

IPC constructors, msgspec messages and protobuf wire shape retain dev behavior.
Object/P2P and HTTP/control-plane schemas use nested object identity and require
coordinated upgrades of their consumers. `EncodedObjectKeyIdentity` retains
hexadecimal chunk hashes for JSON. Legacy untagged L2 data, flattened trace/pin
records and positional coordinator captures remain readable.

This PR does not predefine KV encoding fields or activate an engine precision
producer. Tests cover request-config extraction, sorted tags, mutable xattrs,
identity isolation, session/transfer separation, protocol projections and L2
naming. CPU checks do not establish hardware inference correctness.
