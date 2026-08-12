"""Conversational AI orchestration layer.

Vendor-neutral: it consumes the normalized messaging boundary
(``IncomingMessage``/``OutgoingMessage``/``MessagingProvider``) and drives the
existing ``CatalogService`` / ``InventoryService`` through an intent pipeline.
The AI only returns a constrained, validated ``ResolvedIntent`` - it is never an
authority over tenant, authorization, or the final business result.
"""
