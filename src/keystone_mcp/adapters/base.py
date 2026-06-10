from typing import Any, Protocol

from ..payload import ContextDoc


class Adapter(Protocol):
    name: str

    async def fetch(
        self, query: dict[str, Any], classify: dict[str, Any]
    ) -> list[ContextDoc]:
        """Return classified context docs for one query.

        `classify` declares which chunks become rules vs reasoning. Selector
        vocabulary is adapter-specific (e.g. heading names for markdown).
        """
        ...

    async def health(self) -> dict[str, Any]: ...
