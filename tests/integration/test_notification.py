"""Integration tests: notification read/ack APIs, filtering, tenant isolation.

Notifications are inserted directly through the repository in the test session
(the event listener is disabled in the test env, D3); these tests cover the read
and acknowledgement API surface and its tenant scoping.
"""

from __future__ import annotations

from app.notification.models import Notification, NotificationType
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.integration.helpers import auth_header, register_business


def _insert(session: Session, business_id: int, *, dedup: str, read: bool = False) -> int:
    n = Notification(
        business_id=business_id,
        type=NotificationType.LOW_STOCK,
        title="Low stock",
        body="A product is low.",
        related_entity_type="product",
        related_entity_id=1,
        is_read=read,
        dedup_key=dedup,
    )
    session.add(n)
    session.commit()
    session.refresh(n)
    return n.id


def test_list_and_get(api: TestClient, db_session: Session) -> None:
    reg = register_business(api)
    nid = _insert(db_session, reg.business_id, dedup="a")
    _insert(db_session, reg.business_id, dedup="b")
    listing = api.get("/api/notifications", headers=auth_header(reg.access)).json()
    assert len(listing) == 2
    got = api.get(f"/api/notifications/{nid}", headers=auth_header(reg.access))
    assert got.status_code == 200
    assert got.json()["title"] == "Low stock"


def test_unread_filter_and_mark_read(api: TestClient, db_session: Session) -> None:
    reg = register_business(api)
    nid = _insert(db_session, reg.business_id, dedup="a")
    assert (
        len(api.get("/api/notifications?unread_only=true", headers=auth_header(reg.access)).json())
        == 1
    )
    resp = api.post(f"/api/notifications/{nid}/read", headers=auth_header(reg.access))
    assert resp.status_code == 200
    assert resp.json()["is_read"] is True
    assert (
        api.get("/api/notifications?unread_only=true", headers=auth_header(reg.access)).json() == []
    )


def test_mark_all_read(api: TestClient, db_session: Session) -> None:
    reg = register_business(api)
    _insert(db_session, reg.business_id, dedup="a")
    _insert(db_session, reg.business_id, dedup="b")
    resp = api.post("/api/notifications/read-all", headers=auth_header(reg.access))
    assert resp.status_code == 200
    assert resp.json()["updated"] == 2
    assert (
        api.get("/api/notifications?unread_only=true", headers=auth_header(reg.access)).json() == []
    )


# --- security ---------------------------------------------------------------


def test_unauthenticated_denied(api: TestClient) -> None:
    assert api.get("/api/notifications").status_code == 401


def test_cross_tenant_notification_access(api: TestClient, db_session: Session) -> None:
    a = register_business(api, email="a@shop.co", name="A")
    b = register_business(api, email="b@shop.co", name="B")
    b_nid = _insert(db_session, b.business_id, dedup="b")
    # A cannot see B's notification in the list or by id.
    assert api.get("/api/notifications", headers=auth_header(a.access)).json() == []
    assert api.get(f"/api/notifications/{b_nid}", headers=auth_header(a.access)).status_code == 404
    # A cannot mark B's notification read.
    assert (
        api.post(f"/api/notifications/{b_nid}/read", headers=auth_header(a.access)).status_code
        == 404
    )
