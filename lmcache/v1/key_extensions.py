# SPDX-License-Identifier: Apache-2.0
"""Immutable extension attributes shared by IPC and storage keys."""

# Standard
from dataclasses import dataclass, field
import base64
import binascii

# Third Party
import msgspec


@dataclass(frozen=True, order=True)
class KeyExtensions:
    """Extend a key without adding a field for every new feature.

    ``identity`` is an ordered tuple of opaque, producer-defined strings.
    ``metadata`` contains named, request-scoped hints and is excluded from
    equality, hashing, ordering and storage names. ``named_identity`` contains
    named attributes that both identify an object and are consumed by modules.
    Named categories are sorted by name; duplicate or empty names are rejected.
    Values are strings, so producers own typed schemas and their versions.
    """

    identity: tuple[str, ...] = ()
    metadata: tuple[tuple[str, str], ...] = field(default=(), compare=False)
    named_identity: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        # Copy containers so frozen keys cannot retain caller-owned lists.
        object.__setattr__(self, "identity", tuple(self.identity))
        if any(not isinstance(value, str) for value in self.identity):
            raise ValueError("identity values must be strings")
        names_by_category: list[set[str]] = []
        for category in ("metadata", "named_identity"):
            pairs = tuple(tuple(pair) for pair in getattr(self, category))
            if any(
                len(pair) != 2
                or not all(isinstance(value, str) for value in pair)
                or not pair[0]
                for pair in pairs
            ):
                raise ValueError(f"{category} must contain non-empty names and strings")
            names = {pair[0] for pair in pairs}
            if len(names) != len(pairs):
                raise ValueError(f"duplicate names in {category}")
            names_by_category.append(names)
            object.__setattr__(self, category, tuple(sorted(pairs)))
        if names_by_category[0] & names_by_category[1]:
            raise ValueError("a name cannot be both metadata and named_identity")

    def to_storage_token(self) -> str:
        """Return a reversible, path-safe identity token, or an empty string.

        Metadata is intentionally omitted. The version prefix fixes the JSON
        tuple schema and base64url encoding; unknown versions fail on decode.
        """
        if not self.identity and not self.named_identity:
            return ""
        payload = msgspec.json.encode((self.identity, self.named_identity))
        return "x1-" + base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")

    @classmethod
    def from_storage_token(cls, token: str) -> "KeyExtensions":
        """Decode an identity token; recovered keys have no request metadata.

        Args:
            token: Canonical token from :meth:`to_storage_token`, including "".

        Returns:
            Extensions with the original matching attributes.

        Raises:
            ValueError: The version, encoding or attribute schema is invalid.
        """
        if not token:
            return cls()
        if not token.startswith("x1-"):
            raise ValueError("unsupported key extension version")
        try:
            payload = base64.b64decode(
                token[3:] + "=" * (-len(token[3:]) % 4), altchars=b"-_", validate=True
            )
            identity, named_identity = msgspec.json.decode(
                payload, type=tuple[tuple[str, ...], tuple[tuple[str, str], ...]]
            )
        except (binascii.Error, msgspec.DecodeError) as exc:
            raise ValueError("invalid key extension token") from exc
        result = cls(identity=identity, named_identity=named_identity)
        if result.to_storage_token() != token:
            raise ValueError("non-canonical key extension token")
        return result

    def storage_suffix(self, cache_salt: str) -> str:
        """Return the optional salt and extension fields for storage codecs.

        Args:
            cache_salt: Validated isolation salt from the containing key.

        Returns:
            Legacy salt suffix when identity is empty, otherwise two fields
            (including an empty salt placeholder) ending in the versioned token.
        """
        token = self.to_storage_token()
        if token:
            return f"@{cache_salt}@{token}"
        return f"@{cache_salt}" if cache_salt else ""
