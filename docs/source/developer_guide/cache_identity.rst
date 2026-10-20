Cache key identity
==================

Each key stores a typed ``identity`` containing all fields used for matching.
``ObjectKeyIdentity`` addresses stored chunks; ``IPCKeyIdentity`` addresses
request token ranges and workers. Their fields differ, so they are separate
classes rather than a shared namespace.

.. code-block:: python

   from lmcache.v1.cache_identity import ObjectKeyIdentity
   from lmcache.v1.distributed.api import ObjectKey

   key = ObjectKey(identity=ObjectKeyIdentity(
       chunk_hash=b"1234",
       kv_rank=0,
       model_name="org/model",
       cache_salt="tenant-a",
       tags={"adapter_revision": "abc123"},
   ))
   assert key.chunk_hash == key.identity.chunk_hash

``ObjectKeyIdentity`` contains ``chunk_hash``, ``kv_rank``, ``model_name``,
``object_group_id``, ``cache_salt`` and ``tags``. ``IPCKeyIdentity`` contains
``world_size``, ``worker_id``, ``token_ids``, ``start``, ``end``, ``model_name``,
``cache_salt`` and ``tags``. IPC conversion constructs object identities
explicitly, preserving model, salt and tags.

Tags accept a dictionary, copy and sort it, and expose an immutable mapping.
Insertion order does not affect matching, hashing or storage names. Key
properties are read-only views of the identity; they do not duplicate state.
Session/request metadata remains outside identity and does not affect matching.

L2 adapters call ``ObjectKey.to_storage_key()``, ``to_filename()`` or
``format_storage_key()``. Untagged storage names remain unchanged. Sorted tags
use a reversible token; extended FS filenames must fit within 255 UTF-8 bytes.

``EncodedObjectKey`` carries an ``EncodedObjectKeyIdentity`` under ``identity``
for HTTP/JSON, with ``chunk_hash_hex`` instead of bytes. Constructors and
msgspec/protobuf messages also use nested identities. Upgrade clients, servers,
P2P peers and control-plane consumers together. This API does not activate
precision isolation in an engine integration.
