"""Notification domain (Phase 10).

In-app, tenant-scoped notifications persisted from existing domain events
(low-stock, order lifecycle, payment). A listener consumes the Phase-1 EventBus
and calls NotificationService post-commit, best-effort - notification writes never
affect committed transactional state. No WhatsApp/email delivery is implemented
(deferred); notifications are read through the API/dashboard.
"""
