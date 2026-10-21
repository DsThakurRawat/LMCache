# Cache identity and transient L1 attributes

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
and `lmcache.xattr.` into transient attributes. Other request configurations
remain available to their existing consumers. Tags require nonempty names and
string values. Xattrs preserve their request-config values.

## Object identity and attrs

`ObjectKeyIdentity` contains `chunk_hash`, `kv_rank`, `model_name`,
`object_group_id`, `cache_salt` and `tags`. Tags are copied into an immutable
mapping sorted by name. Insertion order cannot change equality, hashing,
serialization or storage names. Explicit interpreted identity fields remain
typed; opaque matching dimensions use tags.

`ObjectKey.attrs` is a separate mutable dictionary, excluded from equality,
hashing and storage names. Every expanded object receives its own dictionary.
An L1 consumer can remove an attribute without changing object identity:

```python
owner = key.attrs.pop("owner", None)
```

Changing xattrs does not create another cache entry. Model/salt validation and
nonnegative object-group validation remain on object identity. Read-only key
properties forward field reads without duplicating identity state.

## Server state and storage boundaries

IPC equality still ignores `request_configs`, as on dev. Session lock release
therefore compares extracted matching tags explicitly. Pending SHM transfers
include canonical tags in their server-side lookup key, so otherwise equal IPC
requests with different tags do not overwrite or commit each other's state.
Store batching groups by rank, model, salt and tags, allowing compatible chunks
to share a batch.

Attrs are available during L1 insertion. L2 store queues and P2P lookup/unlock
calls remove them using `ObjectKey.without_attrs()`. The explicit P2P gRPC codec
and HTTP/JSON projections carry identity only; transient attrs do not add proto
fields. Traces, coordinator captures/pins and serde temporary keys also omit
attrs. L2 adapters obtain names and shards through key methods.

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
producer. Tests cover request-config extraction, sorted tags, mutable attrs,
identity isolation, session/transfer separation, protocol projections and L2
naming. CPU checks do not establish hardware inference correctness.
