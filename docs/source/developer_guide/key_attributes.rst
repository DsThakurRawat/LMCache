Object key attributes
=====================

MP producers attach attributes directly to ``IPCCacheServerKey``. The resulting
``ObjectKey`` values carry the same three collections:

.. code-block:: python

   from lmcache.v1.key_attributes import KeyAttribute
   from lmcache.v1.multiprocess.custom_types import IPCCacheServerKey

   key = IPCCacheServerKey.from_token_ids(
       model_name="model", world_size=1, worker_id=0,
       token_ids=[1, 2], end=2,
       identity=(KeyAttribute("kv.precision.v1", "bf16"),),
       metadata=(KeyAttribute("trace.id", "request-123"),),
       named_identity=(KeyAttribute("lmcache.codec.v1", "raw"),),
   )

All three collections use ``KeyAttribute(name, value)``. ``identity`` contains
attributes used for matching only. ``named_identity`` contains matching
attributes whose values are also interpreted by modules. Names and values both
participate in matching. Each collection is sorted by name, so input order does
not affect matching; duplicate or empty names are rejected.

``metadata`` is available to modules on the current operation but does not affect
equality, hashing, ordering or storage names. It is not recovered from disk and
must not determine how to decode stored bytes.

Names and values are strings. Producers own their schemas and canonical
encodings. Use compact versioned digests for large matching descriptions and
compact module-readable matching values: extended filesystem names must fit
within 255 UTF-8 bytes.

Empty matching collections retain existing storage names. Upgrade all clients,
servers and P2P peers before enabling matching attributes, because older peers
can ignore the new fields. This API does not automatically enable vLLM precision
isolation or extend token-addressed cache-control APIs.

The full design and storage contract are in
`key-attributes.md <https://github.com/LMCache/LMCache/blob/dev/docs/design/v1/key-attributes.md>`_.
