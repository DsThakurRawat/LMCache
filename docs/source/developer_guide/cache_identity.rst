Cache identity and L1 attributes
================================

Clients pass matching tags and transient attributes through the existing
``IPCCacheServerKey.request_configs`` dictionary. The IPC key and its wire
schema retain their dev definitions.

.. code-block:: python

   request_configs = {
       "lmcache.tag.adapter_revision": "abc123",
       "lmcache.xattr.owner": "alice",
       "lmcache.xattr.priority": 1,
   }

The server extracts ``lmcache.tag.*`` into ``ObjectKey.identity.tags`` and
``lmcache.xattr.*`` into ``ObjectKey.attrs``, removing each prefix. Unrelated
request configurations keep their existing meaning. Tags use nonempty names
and string values; attrs preserve their request-config values.

``ObjectKeyIdentity`` contains ``chunk_hash``, ``kv_rank``, ``model_name``,
``object_group_id``, ``cache_salt`` and immutable, name-sorted ``tags``.
Read-only key properties forward reads to the identity without duplicating it.

``attrs`` is mutable, copied per object and excluded from equality/hashing.
An L1 consumer can delete one attribute directly:

.. code-block:: python

   owner = key.attrs.pop("owner", None)

Changing attrs does not change a cache hit or create another entry. Attrs are
omitted from L2 store queues, P2P messages, persistent key names, HTTP/JSON key
projections, traces and coordinator captures/pins.

L2 adapters call ``ObjectKey.to_storage_key()``, ``to_filename()`` or
``format_storage_key()``. Untagged names remain unchanged; sorted tags use a
reversible token. Extended FS filenames must fit within 255 UTF-8 bytes.

``EncodedObjectKey`` carries an ``EncodedObjectKeyIdentity`` under ``identity``
for HTTP/JSON, with ``chunk_hash_hex`` instead of bytes. Object/P2P and
control-plane consumers need coordinated schema upgrades. IPC clients retain
the dev message shape. This API does not activate precision isolation in an
engine integration.
