"""WhatsApp sender role resolution (multi-tenant, trusted).

Role is derived server-side, never from message content: a sender is STAFF only
if their phone is explicitly mapped to the resolved business in ``whatsapp_staff``
(populated by onboarding/config). Everyone else is a CUSTOMER. A user can never
gain seller privileges by *claiming* to be staff.
"""

from __future__ import annotations

import enum

from app.whatsapp.repository import WhatsAppStaffRepository


class WhatsAppRole(enum.StrEnum):
    CUSTOMER = "CUSTOMER"
    STAFF = "STAFF"


def resolve_role(staff: WhatsAppStaffRepository, business_id: int, phone: str) -> WhatsAppRole:
    """Return STAFF iff the phone is a configured staff number for this business."""
    return WhatsAppRole.STAFF if staff.is_staff(business_id, phone) else WhatsAppRole.CUSTOMER
