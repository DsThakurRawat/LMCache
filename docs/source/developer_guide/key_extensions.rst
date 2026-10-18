Extensible object keys
======================

MP producers can attach three categories of attributes to an
``IPCCacheServerKey`` through ``KeyExtensions``. They are forwarded to the
resulting ``ObjectKey`` values:

.. code-block:: python

   from lmcache.v1.key_extensions import KeyExtensions
   from lmcache.v1.multiprocess.custom_types import IPCCacheServerKey

   key = IPCCacheServerKey.from_token_ids(
       model_name="model",
       world_size=1,
       worker_id=0,
       token_ids=[1, 2],
       end=2,
       extensions=KeyExtensions(
           identity=("precision-v1:bf16",),
           metadata=(("trace.id", "request-123"),),
           named_identity=(("lmcache.codec.v1", "raw"),),
       ),
   )

``identity`` is ordered and participates in matching. ``named_identity`` also
participates in matching and lets modules look up values by name. ``metadata``
is available to modules on the current operation but does not affect equality,
hashing, ordering or persistent storage names. Metadata is not recovered from
disk and must not be used to determine how to decode stored bytes.

Values are strings. Named attributes are sorted by name; duplicate or empty
names are rejected. Producers own the schema and canonical encoding of structured
values. Use compact versioned digests for opaque compatibility factors and
compact named values: extended filesystem names must fit within 255 UTF-8 bytes.

Empty extensions retain existing storage names. Upgrade all clients, servers and
P2P peers before a producer enables non-empty matching attributes; older peers
can ignore the new fields. Extended keys intentionally miss legacy objects
whose byte compatibility cannot be established. This API does not automatically
enable vLLM precision isolation or extend token-addressed cache-control APIs.

The full design, encoding contract and rollout discussion are in
`key-extensions.md <https://github.com/LMCache/LMCache/blob/dev/docs/design/v1/key-extensions.md>`_.
