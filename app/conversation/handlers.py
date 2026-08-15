"""Intent handlers + registry.

Each handler invokes a domain service and returns a deterministic reply plus an
operational ``Outcome``. Handlers never touch ORM/repositories directly and never
mutate inventory except through ``InventoryService`` (the single write authority).
Routing is a dict lookup - no if/elif chain (plan item 20).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Protocol

from app.catalog.service import CatalogService
from app.common.exceptions import InsufficientStockError, NotFoundError
from app.conversation import responses
from app.conversation.resolver import ProductResolver
from app.conversation.schemas import IntentType, Language, ResolvedIntent, StockDirection
from app.inventory.models import MovementType
from app.inventory.service import InventoryService


class Outcome(enum.StrEnum):
    EXECUTED = "EXECUTED"
    CLARIFICATION = "CLARIFICATION"
    UNSUPPORTED = "UNSUPPORTED"
    NOT_FOUND = "NOT_FOUND"
    REJECTED = "REJECTED"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class HandlerResult:
    reply: str
    outcome: Outcome


class IntentHandler(Protocol):
    def handle(
        self,
        business_id: int,
        intent: ResolvedIntent,
        *,
        actor_user_id: int | None,
        language: Language = Language.EN,
    ) -> HandlerResult: ...


class SearchProductHandler:
    def __init__(self, resolver: ProductResolver) -> None:
        self._resolver = resolver

    def handle(
        self,
        business_id: int,
        intent: ResolvedIntent,
        *,
        actor_user_id: int | None,
        language: Language = Language.EN,
    ) -> HandlerResult:
        query = intent.entities.product_query
        if not query:
            return HandlerResult(responses.missing_search_product(language), Outcome.CLARIFICATION)
        matches = self._resolver.resolve(business_id, query)
        if not matches:
            return HandlerResult(responses.not_found(query, language), Outcome.NOT_FOUND)
        return HandlerResult(responses.search_results(matches, language), Outcome.EXECUTED)


class GetStockHandler:
    def __init__(self, resolver: ProductResolver, inventory: InventoryService) -> None:
        self._resolver = resolver
        self._inventory = inventory

    def handle(
        self,
        business_id: int,
        intent: ResolvedIntent,
        *,
        actor_user_id: int | None,
        language: Language = Language.EN,
    ) -> HandlerResult:
        query = intent.entities.product_query
        if not query:
            return HandlerResult(responses.missing_search_product(language), Outcome.CLARIFICATION)
        matches = self._resolver.resolve(business_id, query)
        if not matches:
            return HandlerResult(responses.not_found(query, language), Outcome.NOT_FOUND)
        if len(matches) > 1:
            return HandlerResult(
                responses.multiple_matches(query, matches, language), Outcome.CLARIFICATION
            )
        product = matches[0]
        try:
            inventory = self._inventory.get_inventory_by_product(business_id, product.id)
        except NotFoundError:
            return HandlerResult(responses.no_inventory(product.name, language), Outcome.NOT_FOUND)
        return HandlerResult(
            responses.stock_level(product.name, inventory.quantity, language), Outcome.EXECUTED
        )


class AdjustStockHandler:
    def __init__(self, resolver: ProductResolver, inventory: InventoryService) -> None:
        self._resolver = resolver
        self._inventory = inventory

    def handle(
        self,
        business_id: int,
        intent: ResolvedIntent,
        *,
        actor_user_id: int | None,
        language: Language = Language.EN,
    ) -> HandlerResult:
        entities = intent.entities
        if not entities.product_query:
            return HandlerResult(responses.missing_product(language), Outcome.CLARIFICATION)
        increasing = entities.direction is not StockDirection.DECREASE
        if entities.quantity is None:
            return HandlerResult(
                responses.missing_quantity(entities.product_query, increasing, language),
                Outcome.CLARIFICATION,
            )

        matches = self._resolver.resolve(business_id, entities.product_query)
        if not matches:
            return HandlerResult(
                responses.not_found(entities.product_query, language), Outcome.NOT_FOUND
            )
        if len(matches) > 1:
            return HandlerResult(
                responses.multiple_matches(entities.product_query, matches, language),
                Outcome.CLARIFICATION,
            )
        product = matches[0]

        try:
            current = self._inventory.get_inventory_by_product(business_id, product.id)
        except NotFoundError:
            return HandlerResult(responses.no_inventory(product.name, language), Outcome.NOT_FOUND)

        delta = entities.quantity if increasing else -entities.quantity
        movement_type = entities.movement_type or (
            MovementType.RESTOCK if increasing else MovementType.SALE
        )
        try:
            updated = self._inventory.adjust_stock_by_product(
                business_id,
                product.id,
                delta=delta,
                movement_type=movement_type,
                actor_user_id=actor_user_id,
            )
        except InsufficientStockError:
            return HandlerResult(
                responses.insufficient_stock(
                    product.name, entities.quantity, current.quantity, language
                ),
                Outcome.REJECTED,
            )
        return HandlerResult(
            responses.adjusted(product.name, delta, updated.quantity, language), Outcome.EXECUTED
        )


class UnsupportedHandler:
    def handle(
        self,
        business_id: int,
        intent: ResolvedIntent,
        *,
        actor_user_id: int | None,
        language: Language = Language.EN,
    ) -> HandlerResult:
        return HandlerResult(responses.unsupported(language), Outcome.UNSUPPORTED)


class ClarificationHandler:
    def handle(
        self,
        business_id: int,
        intent: ResolvedIntent,
        *,
        actor_user_id: int | None,
        language: Language = Language.EN,
    ) -> HandlerResult:
        return HandlerResult(
            intent.clarification or responses.low_confidence(language), Outcome.CLARIFICATION
        )


def build_registry(
    catalog: CatalogService, inventory: InventoryService
) -> dict[IntentType, IntentHandler]:
    resolver = ProductResolver(catalog)
    return {
        IntentType.SEARCH_PRODUCT: SearchProductHandler(resolver),
        IntentType.GET_STOCK: GetStockHandler(resolver, inventory),
        IntentType.ADJUST_STOCK: AdjustStockHandler(resolver, inventory),
        IntentType.UNSUPPORTED: UnsupportedHandler(),
        IntentType.CLARIFICATION_REQUIRED: ClarificationHandler(),
    }
