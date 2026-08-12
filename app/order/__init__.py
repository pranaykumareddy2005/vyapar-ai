"""Order domain.

Owns orders, order items, the guarded lifecycle state machine, and order totals.
Inventory is decremented on confirm and restored on cancel-from-confirmed, always
through ``InventoryService`` (the single stock write authority) inside one order
transaction. Order items snapshot the product name and price at sale so historical
orders stay correct after catalog changes. Payment/invoice remain separate domains.
"""
