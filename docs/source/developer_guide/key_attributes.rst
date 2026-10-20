Object key attributes
=====================

MP producers attach three collections of ``KeyAttribute(name, value)`` directly
to ``IPCCacheServerKey`` and the resulting ``ObjectKey``:

* ``opaque_identity``: matching factors whose values other modules do not interpret.
* ``metadata``: module-readable values excluded from matching.
* ``identity_metadata``: module-readable values also included in matching.

All names are unique across a key's three collections. Collections are sorted
by name; names and values in both matching categories affect equality and
hashing. Metadata does not affect equality, hashing, ordering or storage names.

Structured values belong to module-owned types. The generic transport still
carries names and strings; use the stateless typed helpers at the module boundary:

.. code-block:: python

   from typing import Literal
   import msgspec
   from lmcache.v1.key_attributes import (
       decode_typed_attribute, encode_typed_attribute,
   )
   from lmcache.v1.multiprocess.custom_types import IPCCacheServerKey

   class KVCacheEncoding(msgspec.Struct, frozen=True, forbid_unknown_fields=True):
       dtype: Literal["bfloat16", "float8_e4m3fn"]
       layout: Literal["NHD", "HND"]

   schema_name = "lmcache.kv_encoding.v1"
   attribute = encode_typed_attribute(
       schema_name, KVCacheEncoding("bfloat16", "NHD")
   )
   key = IPCCacheServerKey.from_token_ids(
       "model", 1, 0, [1, 2], end=2, identity_metadata=(attribute,),
   )
   encoding = decode_typed_attribute(
       key.identity_metadata[0], schema_name, KVCacheEncoding
   )
   assert encoding.layout == "NHD"

This example is illustrative, not an exhaustive precision compatibility schema.
The owning module defines fields, validates values and versions the schema name.
Other modules preserve unknown attributes without parsing them. Typed helpers
provide deterministic JSON, reject non-finite numbers and validate names, versions
and decoded types. Producers still need to normalize aliases, units and defaults.
A simple scalar value can remain a plain ``KeyAttribute`` without a new class.

The same typed value may be used as non-matching metadata when its semantics
require that; using a class does not determine whether the value affects identity.
Changing an attribute's category changes the matching namespace.

Non-matching does not imply transient. This API transports operation metadata but
does not persist it in object names. A module needing durable object metadata must
use an object header or backend metadata contract. Read current operation hints
from the incoming key rather than a previously stored equal dictionary key.

Empty matching collections preserve existing storage names. Extended filesystem
names must fit within 255 UTF-8 bytes; keep matching values compact. Upgrade all
clients, servers and P2P peers before enabling matching attributes, since older
peers can ignore new fields. This API does not automatically enable precision
isolation or extend token-addressed cache-control APIs.

The full design is in
`key-attributes.md <https://github.com/LMCache/LMCache/blob/dev/docs/design/v1/key-attributes.md>`_.
