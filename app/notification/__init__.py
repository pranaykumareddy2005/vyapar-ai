"""Notification domain.

In-app, tenant-scoped notifications persisted from domain events (low-stock,
order lifecycle, payment). A listener consumes the in-process EventBus and calls
NotificationService post-commit, best-effort - notification writes never affect
committed transactional state. External (WhatsApp/email) delivery is not
implemented; notifications are read through the API/dashboard.
"""
