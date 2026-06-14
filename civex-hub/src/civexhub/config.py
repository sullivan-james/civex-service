from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from civex.domain.exceptions import ConfigError


@dataclass
class HubConfig:
    database_url: str
    object_store: str        # "filesystem" | "s3"
    objects_dir: Path | None
    s3_bucket: str | None
    s3_prefix: str
    s3_endpoint_url: str | None
    s3_access_key: str | None
    s3_secret_key: str | None
    secret_key: str


def load_config() -> HubConfig:
    database_url = os.environ.get("CIVEXHUB_DATABASE_URL")
    if not database_url:
        raise ConfigError("CIVEXHUB_DATABASE_URL is required")

    object_store = os.environ.get("CIVEXHUB_OBJECT_STORE", "filesystem")
    if object_store not in ("filesystem", "s3"):
        raise ConfigError("CIVEXHUB_OBJECT_STORE must be 'filesystem' or 's3'")

    objects_dir: Path | None = None
    if object_store == "filesystem":
        raw = os.environ.get("CIVEXHUB_OBJECTS_DIR")
        if not raw:
            raise ConfigError("CIVEXHUB_OBJECTS_DIR is required when CIVEXHUB_OBJECT_STORE=filesystem")
        objects_dir = Path(raw)

    secret_key = os.environ.get("CIVEXHUB_SECRET_KEY", "")

    return HubConfig(
        database_url=database_url,
        object_store=object_store,
        objects_dir=objects_dir,
        s3_bucket=os.environ.get("CIVEXHUB_S3_BUCKET"),
        s3_prefix=os.environ.get("CIVEXHUB_S3_PREFIX", "objects/"),
        s3_endpoint_url=os.environ.get("CIVEXHUB_S3_ENDPOINT_URL"),
        s3_access_key=os.environ.get("CIVEXHUB_S3_ACCESS_KEY"),
        s3_secret_key=os.environ.get("CIVEXHUB_S3_SECRET_KEY"),
        secret_key=secret_key,
    )
