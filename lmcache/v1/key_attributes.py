# SPDX-License-Identifier: Apache-2.0
"""Named key attributes and stateless storage encoding helpers."""

# Standard
from dataclasses import dataclass
from typing import TypeVar
import base64
import binascii
import json

# Third Party
import msgspec

AttributeValueT = TypeVar("AttributeValueT")


@dataclass(frozen=True, order=True)
class KeyAttribute:
    """A named string value used in any of the three key attribute categories.

    Producers own the value schema and its version. Names must be non-empty;
    both names and values must be strings.
    """

    name: str
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("key attribute name must be a non-empty string")
        if not isinstance(self.value, str):
            raise ValueError("key attribute value must be a string")


def encode_typed_attribute(name: str, value: object) -> KeyAttribute:
    """Encode a module-owned value as canonical JSON in a named attribute.

    Args:
        name: Module-owned, versioned schema name, e.g. ``lmcache.kv_encoding.v1``.
        value: A dataclass, msgspec Struct or JSON-compatible value. The owner
            must normalize aliases, units and defaults before encoding.

    Returns:
        An attribute whose JSON object keys and unordered collections have
        deterministic ordering. Non-finite numbers are rejected rather than
        converted to null, which could alias distinct matching values.

    Raises:
        ValueError: The name is invalid or the value contains non-finite numbers.
        TypeError: The value cannot be represented as JSON.
    """
    payload = msgspec.to_builtins(value, order="deterministic")
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return KeyAttribute(name, encoded)


def decode_typed_attribute(
    attribute: KeyAttribute, expected_name: str, value_type: type[AttributeValueT]
) -> AttributeValueT:
    """Decode one attribute using the consuming module's schema.

    Args:
        attribute: Attribute received on a key.
        expected_name: Exact module/schema version name expected by the consumer.
        value_type: The module's dataclass or msgspec Struct type. Structs may
            use ``forbid_unknown_fields=True`` for a closed schema.

    Returns:
        A typed value validated by msgspec and the owner's construction hooks.

    Raises:
        ValueError: The name/version, JSON or value schema does not match.
        TypeError: ``value_type`` is unsupported by msgspec.
    """
    if attribute.name != expected_name:
        raise ValueError(
            f"expected attribute {expected_name!r}, got {attribute.name!r}"
        )
    return msgspec.json.decode(attribute.value, type=value_type)


def validate_key_attribute_names(*categories: tuple[KeyAttribute, ...]) -> None:
    """Reject conflicting attribute names across a key's categories.

    Args:
        categories: The attribute collections directly held by the key.

    Raises:
        ValueError: A name occurs more than once, including across categories.
    """
    names = [attribute.name for category in categories for attribute in category]
    if len(set(names)) != len(names):
        raise ValueError("duplicate key attribute names across categories")


def canonicalize_key_attributes(
    attributes: tuple[KeyAttribute, ...],
) -> tuple[KeyAttribute, ...]:
    """Copy attributes into name order, rejecting duplicate names.

    Args:
        attributes: One category of attributes supplied by a key producer.

    Returns:
        An immutable, sorted tuple, independent of input order.

    Raises:
        ValueError: A name occurs more than once in this category.
    """
    result = tuple(sorted(attributes))
    if len({attribute.name for attribute in result}) != len(result):
        raise ValueError("duplicate key attribute names")
    return result


def encode_matching_attributes(
    opaque_identity: tuple[KeyAttribute, ...],
    identity_metadata: tuple[KeyAttribute, ...],
) -> str:
    """Encode the matching categories as a reversible, path-safe token.

    Args:
        opaque_identity: Attributes used only for matching.
        identity_metadata: Attributes also interpreted by other modules.

    Returns:
        A versioned base64url token, or "" when both categories are empty.
        Metadata is not an argument because it never changes storage names.
    """
    validate_key_attribute_names(opaque_identity, identity_metadata)
    if not opaque_identity and not identity_metadata:
        return ""
    payload = msgspec.json.encode(
        tuple(
            tuple(
                (attribute.name, attribute.value)
                for attribute in canonicalize_key_attributes(category)
            )
            for category in (opaque_identity, identity_metadata)
        )
    )
    return "x1-" + base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_matching_attributes(
    token: str,
) -> tuple[tuple[KeyAttribute, ...], tuple[KeyAttribute, ...]]:
    """Recover the two matching categories from a canonical storage token.

    Args:
        token: Token from :func:`encode_matching_attributes`, including "".

    Returns:
        Opaque identity and identity metadata; non-matching metadata is not stored.

    Raises:
        ValueError: The version, encoding or attribute schema is invalid.
    """
    if not token:
        return (), ()
    if not token.startswith("x1-"):
        raise ValueError("unsupported key attribute version")
    try:
        payload = base64.b64decode(
            token[3:] + "=" * (-len(token[3:]) % 4), altchars=b"-_", validate=True
        )
        opaque_identity, identity_metadata = msgspec.json.decode(
            payload,
            type=tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]],
        )
    except (binascii.Error, msgspec.DecodeError) as exc:
        raise ValueError("invalid key attribute token") from exc
    result = (
        tuple(KeyAttribute(name, value) for name, value in opaque_identity),
        tuple(KeyAttribute(name, value) for name, value in identity_metadata),
    )
    if encode_matching_attributes(*result) != token:
        raise ValueError("non-canonical key attribute token")
    return result


def matching_attributes_suffix(
    cache_salt: str,
    opaque_identity: tuple[KeyAttribute, ...],
    identity_metadata: tuple[KeyAttribute, ...],
) -> str:
    """Return salt and matching attributes as a storage-name suffix.

    Args:
        cache_salt: Validated isolation salt from the containing key.
        opaque_identity: Matching attributes from the containing key.
        identity_metadata: Module-consumed matching attributes.

    Returns:
        The legacy salt suffix for empty matching categories, otherwise the
        salt placeholder and a versioned token in two separate fields.
    """
    token = encode_matching_attributes(opaque_identity, identity_metadata)
    if token:
        return f"@{cache_salt}@{token}"
    return f"@{cache_salt}" if cache_salt else ""
