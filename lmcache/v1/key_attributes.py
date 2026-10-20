# SPDX-License-Identifier: Apache-2.0
"""Named key attributes and stateless storage encoding helpers."""

# Standard
from dataclasses import dataclass
import base64
import binascii

# Third Party
import msgspec


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


def encode_key_attributes(
    identity: tuple[KeyAttribute, ...], named_identity: tuple[KeyAttribute, ...]
) -> str:
    """Encode the matching categories as a reversible, path-safe token.

    Args:
        identity: Attributes used only for matching.
        named_identity: Attributes also interpreted by other modules.

    Returns:
        A versioned base64url token, or "" when both categories are empty.
        Metadata is not an argument because it never changes storage names.
    """
    if not identity and not named_identity:
        return ""
    payload = msgspec.json.encode(
        tuple(
            tuple(
                (attribute.name, attribute.value)
                for attribute in canonicalize_key_attributes(category)
            )
            for category in (identity, named_identity)
        )
    )
    return "x1-" + base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_key_attributes(
    token: str,
) -> tuple[tuple[KeyAttribute, ...], tuple[KeyAttribute, ...]]:
    """Recover the two matching categories from a canonical storage token.

    Args:
        token: Token from :func:`encode_key_attributes`, including "".

    Returns:
        Identity and named identity; operation metadata is not stored.

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
        identity, named_identity = msgspec.json.decode(
            payload,
            type=tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]],
        )
    except (binascii.Error, msgspec.DecodeError) as exc:
        raise ValueError("invalid key attribute token") from exc
    result = (
        tuple(KeyAttribute(name, value) for name, value in identity),
        tuple(KeyAttribute(name, value) for name, value in named_identity),
    )
    if encode_key_attributes(*result) != token:
        raise ValueError("non-canonical key attribute token")
    return result


def key_attribute_suffix(
    cache_salt: str,
    identity: tuple[KeyAttribute, ...],
    named_identity: tuple[KeyAttribute, ...],
) -> str:
    """Return salt and matching attributes as a storage-name suffix.

    Args:
        cache_salt: Validated isolation salt from the containing key.
        identity: Matching attributes from the containing key.
        named_identity: Module-consumed matching attributes.

    Returns:
        The legacy salt suffix for empty matching categories, otherwise the
        salt placeholder and a versioned token in two separate fields.
    """
    token = encode_key_attributes(identity, named_identity)
    if token:
        return f"@{cache_salt}@{token}"
    return f"@{cache_salt}" if cache_salt else ""
