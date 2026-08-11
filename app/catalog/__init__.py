"""Catalog domain: categories, products, and product image metadata.

Owns product/catalog *state* only. It does not own inventory quantity, stock
movements, orders, payments, invoices, or AI inference. The future AI Catalog
Generator will call :class:`~app.catalog.service.CatalogService` after merchant
approval; this domain stays independent of AI and messaging.
"""
