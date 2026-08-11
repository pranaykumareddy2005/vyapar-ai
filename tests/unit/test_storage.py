from __future__ import annotations

from app.common.storage import InMemoryStorage, ObjectStorage, build_storage
from app.config import Settings


def test_in_memory_put_get_url() -> None:
    storage = InMemoryStorage(bucket="test-bucket")
    url = storage.put("images/a.jpg", b"bytes", "image/jpeg")
    assert url == "memory://test-bucket/images/a.jpg"
    assert storage.get("images/a.jpg") == b"bytes"


def test_in_memory_satisfies_protocol() -> None:
    assert isinstance(InMemoryStorage(), ObjectStorage)


def test_build_storage_defaults_to_memory() -> None:
    settings = Settings(storage_backend="memory", s3_bucket="vyapar")
    storage = build_storage(settings)
    assert isinstance(storage, InMemoryStorage)
