"""Customer domain (Phase 7).

Owns customer identity, contact info, and saved delivery addresses. Tenant-scoped
by ``business_id``. Customers are soft-deleted so historical orders that reference
them stay valid. This module has no dependency on Order (Order depends on it).
"""
