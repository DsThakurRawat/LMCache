Cache namespaces
================

``CacheNamespace`` owns the model name, user isolation salt and additional
identity tags shared by request and object keys:

.. code-block:: python

   from lmcache.v1.cache_namespace import CacheNamespace
   from lmcache.v1.distributed.api import ObjectKey

   namespace = CacheNamespace(
       model_name="org/model",
       cache_salt="tenant-a",
       tags={"adapter_revision": "abc123"},
   )
   key = ObjectKey(chunk_hash=b"1234", namespace=namespace, kv_rank=0)
   assert key.model_name == key.namespace.model_name

All namespace fields affect cache identity. Tags accept a dictionary, copy and
sort it, and expose an immutable mapping. Insertion order does not affect
matching, hashing or storage names. The key's ``model_name`` and ``cache_salt``
properties are read-only views; they are not separate stored fields.

``ObjectKey`` retains chunk hash, rank and object group coordinates. Request
hints and session information belong outside it. Durable non-matching metadata
belongs in an object header or descriptor. This PR does not predefine a KV
encoding class; interpreted properties need actual producer/consumer contracts.

L2 adapters call ``ObjectKey.to_storage_key()``, ``to_filename()`` or
``format_storage_key()``. Their decoding counterparts restore the complete
namespace from the existing model/salt prefix and a reversible sorted-tags token.
Untagged storage names remain unchanged. Extended FS filenames must fit within
255 UTF-8 bytes.

Python constructors and msgspec/protobuf/JSON key messages now take a nested
``namespace`` instead of flat model/salt fields. Upgrade clients, servers, P2P
peers and control-plane consumers together. This API does not activate precision
isolation in an engine integration.
