Cache namespaces
================

Cache keys share a ``CacheNamespace`` value. All of its fields participate in
cache identity, including L2 storage names.

Use explicit fields for properties consumed by other modules and ``tags`` for
additional opaque identity dimensions:

.. code-block:: python

   from lmcache.v1.cache_namespace import CacheNamespace, KVCacheEncoding
   from lmcache.v1.multiprocess.custom_types import IPCCacheServerKey

   namespace = CacheNamespace(
       kv_encoding=KVCacheEncoding(dtype="bfloat16", layout="NHD"),
       tags={"adapter_revision": "abc123"},
   )
   key = IPCCacheServerKey.from_token_ids(
       "model", 1, 0, [1, 2], end=2, namespace=namespace,
   )
   assert key.namespace.kv_encoding.dtype == "bfloat16"

Tags accept a dictionary at construction, copy it and expose an immutable
mapping. Insertion order does not affect matching or storage names. Producers
must normalize resolved representation names before constructing namespaces.
An unspecified encoding does not imply any particular dtype or layout.

Request hints and session information belong outside ``ObjectKey``. Durable
non-matching metadata belongs in an object header or descriptor; this API does
not add a metadata persistence format.

L2 adapters call ``ObjectKey.to_storage_key()``, ``to_filename()`` or
``format_storage_key()``. These methods include the entire namespace without
requiring adapters to inspect its fields. The corresponding decoding methods
restore typed fields and tags.

Empty namespaces preserve existing storage names. Nonempty namespaces append a
reversible versioned token. Keep values compact: extended FS filenames must fit
within 255 UTF-8 bytes. Upgrade clients, servers and P2P peers together before
enabling namespaces. Older peers may ignore unknown identity fields.

This API does not activate precision isolation in an engine integration.
