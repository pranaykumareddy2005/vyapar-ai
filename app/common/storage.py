"""Object storage abstraction.

Product images and invoice PDFs live in object storage, never in Postgres. The
domain depends only on the :class:`ObjectStorage` protocol; the concrete backend
(in-memory fake for dev/test, S3/MinIO for staging/prod) is selected by config.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.config import Settings


@runtime_checkable
class ObjectStorage(Protocol):
    """Storage boundary. Implementations must be swappable by environment."""

    def put(self, key: str, data: bytes, content_type: str) -> str:
        """Store ``data`` under ``key`` and return a retrievable URL/reference."""
        ...

    def get(self, key: str) -> bytes:
        """Return the bytes previously stored under ``key``."""
        ...

    def url_for(self, key: str) -> str:
        """Return the reference URL for ``key`` (no existence guarantee)."""
        ...


class InMemoryStorage:
    """Process-local fake used for development and tests.

    URLs are synthetic (``memory://<bucket>/<key>``); useful for asserting that
    an image/PDF was stored without needing a live MinIO/S3.
    """

    def __init__(self, bucket: str = "vyapar") -> None:
        self._bucket = bucket
        self._objects: dict[str, bytes] = {}

    def put(self, key: str, data: bytes, content_type: str) -> str:
        self._objects[key] = data
        return self.url_for(key)

    def get(self, key: str) -> bytes:
        return self._objects[key]

    def url_for(self, key: str) -> str:
        return f"memory://{self._bucket}/{key}"


class S3Storage:
    """S3/MinIO-backed storage.

    ``boto3`` is imported lazily so the core package installs without the
    ``storage`` extra; only environments using this backend need it.
    """

    def __init__(self, settings: Settings) -> None:
        import boto3  # lazy import: optional 'storage' extra

        self._bucket = settings.s3_bucket
        self._endpoint = settings.s3_endpoint_url
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        """Create the bucket if it does not exist (idempotent).

        Convenient for MinIO/dev where buckets are not pre-provisioned; on
        managed S3 the bucket usually already exists and head_bucket succeeds.
        """
        import contextlib

        from botocore.exceptions import ClientError  # lazy: optional extra

        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError:
            # Create it; suppress races where another worker just created it.
            with contextlib.suppress(ClientError):
                self._client.create_bucket(Bucket=self._bucket)

    def put(self, key: str, data: bytes, content_type: str) -> str:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)
        return self.url_for(key)

    def get(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        body: bytes = response["Body"].read()
        return body

    def url_for(self, key: str) -> str:
        return f"{self._endpoint.rstrip('/')}/{self._bucket}/{key}"


def build_storage(settings: Settings) -> ObjectStorage:
    """Factory selecting the storage backend from configuration."""
    if settings.storage_backend == "s3":
        return S3Storage(settings)
    return InMemoryStorage(bucket=settings.s3_bucket)
