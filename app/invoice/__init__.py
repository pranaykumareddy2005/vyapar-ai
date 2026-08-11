"""Invoice domain (Phase 9).

Generates an immutable, numbered PDF invoice from a PAID order. Every financial,
customer, and line-item value is a snapshot captured at issuance, so later Product,
Customer, Order, or tax-config changes never alter an issued invoice. Invoice code
reads authoritative Order/Payment data but never mutates orders, inventory, or
payment state. PDFs are rendered from the snapshot and stored via ObjectStorage.
"""
