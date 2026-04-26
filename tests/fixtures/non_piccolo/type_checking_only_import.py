"""TYPE_CHECKING-only Piccolo import must not activate scope at runtime."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from piccolo import Table  # noqa: F401


class SomethingElse:
    """Looks like a method but receiver is not a Piccolo Table."""

    def raw(self, template: str) -> str:
        # Using the literal here would not normally be flagged, but a naive
        # scope builder might treat this file as "has Piccolo imports".
        name = "bob"
        return self.raw(f"SELECT * FROM users WHERE name = {name}")
