"""WhatsApp / Meta Cloud API channel.

This package contains *all* Meta-specific protocol details: the outbound provider
adapter, the inbound webhook parser/router, and webhook idempotency. Meta payload
shapes never leak past this boundary - the rest of the application sees only the
vendor-neutral ``IncomingMessage`` / ``OutgoingMessage`` models and the existing
domain services. WhatsApp is a communication channel, not a business layer.
"""
