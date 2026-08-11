"""Business analytics (Phase 10).

Read-only PostgreSQL aggregation over the existing transactional tables (Order,
OrderItem, Payment, Inventory). No analytics tables, no warehouse, no ML. Financial
values use the authoritative Decimal columns. Metric semantics are documented in
docs/phase10_architecture_decision.md.
"""
