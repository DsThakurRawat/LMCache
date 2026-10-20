# SPDX-License-Identifier: Apache-2.0
"""Cache-sharing identity carried by requests and stored objects."""

# Standard
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import NoReturn
import base64

# Third Party
import msgspec


class _FrozenTags(dict[str, str]):
    """An immutable dict snapshot that msgspec can serialize."""

    def _immutable(self, *args: object, **kwargs: object) -> NoReturn:
        raise TypeError("cache namespace tags are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


@dataclass(frozen=True)
class KVCacheEncoding:
    """Resolved KV representation; producers normalize dtype and layout names."""

    dtype: str
    layout: str


@dataclass(frozen=True)
class CacheNamespace:
    """Typed cache properties and opaque tags, all participating in identity."""

    kv_encoding: KVCacheEncoding | None = None
    tags: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, value in self.tags.items():
            if not isinstance(name, str) or not name or not isinstance(value, str):
                raise ValueError(
                    "tags require non-empty string names and string values"
                )
        object.__setattr__(self, "tags", _FrozenTags(sorted(self.tags.items())))

    def __hash__(self) -> int:
        return hash((self.kv_encoding, tuple(self.tags.items())))

    def __lt__(self, other: "CacheNamespace") -> bool:
        return self.to_token() < other.to_token()

    def to_token(self) -> str:
        """Return a reversible path-safe identity token; empty preserves legacy keys."""
        if self.kv_encoding is None and not self.tags:
            return ""
        payload = msgspec.json.encode(self)
        return "x1-" + base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")

    @classmethod
    def from_token(cls, token: str) -> "CacheNamespace":
        """Recover a namespace, rejecting malformed or noncanonical tokens."""
        if not token:
            return cls()
        if not token.startswith("x1-"):
            raise ValueError("unsupported cache namespace version")
        encoded = token[3:]
        payload = base64.b64decode(
            encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True
        )
        result = msgspec.json.decode(payload, type=cls)
        if result.to_token() != token:
            raise ValueError("non-canonical cache namespace token")
        return result
