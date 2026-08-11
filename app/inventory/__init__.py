"""Inventory Management domain (Phase 5).

Owns stock quantity, the low-stock threshold, and the immutable stock-movement
history. Every mutation of ``inventory.quantity`` goes through the authoritative
:class:`~app.inventory.service.InventoryService`, which holds a PostgreSQL row
lock for the read-modify-write. Inventory references the Catalog ``Product``
(read-only); Catalog never depends on Inventory.
"""
