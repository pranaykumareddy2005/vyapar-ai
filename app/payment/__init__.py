"""Payment domain (Phase 8).

Owns payment records and the payment state machine. Payment success reaches the
order's PAID state only through ``OrderService`` (never a direct Order write) and
never touches inventory. External gateways sit behind the vendor-neutral
``PaymentProvider`` seam; the server (not the client or the raw provider) is
authoritative over amount, currency, and provider-reference validation.
"""
