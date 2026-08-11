from __future__ import annotations

from fastapi.testclient import TestClient


def test_healthz(client: TestClient) -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["environment"] == "test"


def test_dev_simulate_message_roundtrip(client: TestClient) -> None:
    resp = client.post(
        "/dev/simulate-message",
        json={"business_id": 1, "sender_phone": "+9199", "text": "add 10 notebooks"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["normalized"]["text"] == "add 10 notebooks"
    assert body["normalized"]["message_type"] == "text"
    assert body["reply_text"] == "Received: add 10 notebooks"
    assert body["provider_message_id"].startswith("mock-")


def test_dev_simulate_message_validates_input(client: TestClient) -> None:
    resp = client.post(
        "/dev/simulate-message",
        json={"business_id": 0, "sender_phone": "+9199", "text": "hi"},
    )
    assert resp.status_code == 422
