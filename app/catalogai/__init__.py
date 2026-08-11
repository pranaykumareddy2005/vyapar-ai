"""AI Catalog Generator (hero feature, Phase 4).

Turns a product photograph into a *drafted* listing via a multimodal provider,
then requires explicit merchant approval before any final ``Product`` is created.
This module depends on the ``catalog`` application boundary (``CatalogService``);
``catalog`` never depends on ``catalogai``.
"""
