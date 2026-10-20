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
class CacheNamespace:
    """Shared model, isolation salt and sorted tags defining cache identity."""

    model_name: str
    cache_salt: str = ""
    tags: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if "@" in self.model_name:
            raise ValueError("model_name must not contain '@'")
        if any(char in self.cache_salt for char in "@/\\\x00"):
            raise ValueError("cache_salt must not contain '@', '/', '\\' or NUL")
        if len(self.cache_salt) > 128:
            raise ValueError("cache_salt exceeds max length 128")
        for name, value in self.tags.items():
            if not isinstance(name, str) or not name or not isinstance(value, str):
                raise ValueError(
                    "tags require non-empty string names and string values"
                )
        object.__setattr__(self, "tags", _FrozenTags(sorted(self.tags.items())))

    def __hash__(self) -> int:
        return hash((self.model_name, self.cache_salt, tuple(self.tags.items())))

    def __lt__(self, other: "CacheNamespace") -> bool:
        return (self.model_name, self.cache_salt, tuple(self.tags.items())) < (
            other.model_name,
            other.cache_salt,
            tuple(other.tags.items()),
        )

    def to_token(self) -> str:
        """Encode additional identity fields; model and salt stay in the key prefix."""
        if not self.tags:
            return ""
        payload = msgspec.json.encode(self.tags)
        return "x1-" + base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")

    @classmethod
    def from_token(
        cls, token: str, *, model_name: str, cache_salt: str = ""
    ) -> "CacheNamespace":
        """Recover a namespace from its storage prefix and additional identity token."""
        if not token:
            return cls(model_name=model_name, cache_salt=cache_salt)
        if not token.startswith("x1-"):
            raise ValueError("unsupported cache namespace version")
        encoded = token[3:]
        payload = base64.b64decode(
            encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True
        )
        tags = msgspec.json.decode(payload, type=dict[str, str])
        result = cls(model_name=model_name, cache_salt=cache_salt, tags=tags)
        if result.to_token() != token:
            raise ValueError("non-canonical cache namespace token")
        return result
