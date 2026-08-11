"""Natural-language product resolution via the Catalog domain.

Resolves a free-text product reference to the current business's products using
``CatalogService`` (never a direct DB/ORM query). Applies light singular/plural
and last-word fallbacks so "notebooks" matches a "Notebook" product. The AI's
text is only a search hint - tenant scoping and the actual matches come from the
catalog service.
"""

from __future__ import annotations

from app.catalog.models import Product
from app.catalog.service import CatalogService


class ProductResolver:
    def __init__(self, catalog: CatalogService) -> None:
        self._catalog = catalog

    def resolve(self, business_id: int, query: str) -> list[Product]:
        for candidate in self._candidates(query):
            matches = self._catalog.list_products(business_id, keyword=candidate)
            if matches:
                return matches
        return []

    @staticmethod
    def _candidates(query: str) -> list[str]:
        q = query.strip().lower()
        candidates: list[str] = []
        if q:
            candidates.append(q)
            if q.endswith("s"):
                candidates.append(q[:-1])
            last = q.split()[-1]
            if last != q:
                candidates.append(last)
                if last.endswith("s"):
                    candidates.append(last[:-1])
        # De-duplicate, preserve order.
        seen: set[str] = set()
        ordered: list[str] = []
        for candidate in candidates:
            if candidate and candidate not in seen:
                seen.add(candidate)
                ordered.append(candidate)
        return ordered
