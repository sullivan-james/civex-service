from __future__ import annotations

from pathlib import Path

from civex.domain.dtos import FileRef


class S3ObjectStore:
    """Content-addressed blob store backed by S3-compatible storage."""

    def __init__(
        self,
        bucket: str,
        prefix: str = "objects/",
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
    ) -> None:
        try:
            import boto3
        except ImportError:
            raise ImportError("Install civexhub[s3] to use S3 object storage")
        kwargs: dict = {"service_name": "s3"}
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url
        if access_key and secret_key:
            kwargs["aws_access_key_id"] = access_key
            kwargs["aws_secret_access_key"] = secret_key
        self._client = boto3.client(**kwargs)
        self._bucket = bucket
        self._prefix = prefix.rstrip("/") + "/"

    def _key(self, sha256: str) -> str:
        return f"{self._prefix}{sha256[:2]}/{sha256[2:]}"

    def put(self, data: bytes, original_filename: str) -> FileRef:
        import hashlib
        sha256 = hashlib.sha256(data).hexdigest()
        if not self.exists(sha256):
            self._client.put_object(Bucket=self._bucket, Key=self._key(sha256), Body=data)
        return FileRef(sha256=sha256, filename=original_filename, size=len(data))

    def get(self, sha256: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=self._key(sha256))
        return response["Body"].read()

    def exists(self, sha256: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=self._key(sha256))
            return True
        except Exception:
            return False

    def object_path(self, sha256: str) -> Path:
        raise NotImplementedError("S3ObjectStore does not support object_path(); use get() instead")
