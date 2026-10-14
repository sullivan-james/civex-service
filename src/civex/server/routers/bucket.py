"""Where a project's files are kept: drives on this machine, or a bucket
(`BucketService`). Wholly `features.STORE_ADMIN`: a host that decides where
its projects' files go (the hub) leaves it out."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from civex.context import AppContext
from civex.domain.dtos import BucketCheck, BucketStatus
from civex.server.deps import get_ctx
from civex.services.bucket_service import settings_of

router = APIRouter(prefix="/store/bucket", tags=["store"])


class BucketSettingsRequest(BaseModel):
    bucket: str = Field(min_length=1, max_length=255, description="The bucket's name.")
    prefix: str = Field(
        default="",
        max_length=512,
        description="A folder inside the bucket to keep this project's files in.",
    )
    region: str | None = Field(default=None, description="The bucket's region.")
    endpoint: str | None = Field(
        default=None,
        description="The address of a service speaking S3's API other than AWS, "
        "e.g. http://127.0.0.1:9000 for MinIO.",
    )
    profile: str | None = Field(
        default=None,
        description="An AWS profile to take credentials from; else the "
        "environment or the machine's role. Credentials are never saved by civex.",
    )
    direct: bool = Field(
        default=True,
        description="Whether files go straight between a browser or device and "
        "the bucket by presigned URL, rather than through civex.",
    )

    def settings(self):  # noqa: ANN201 - S3Config
        return settings_of(
            self.bucket,
            self.prefix,
            self.region,
            self.endpoint,
            self.profile,
            self.direct,
        )


class BucketStatusResponse(BaseModel):
    bucket: str | None = Field(
        description="The bucket this project's files are kept in; null when "
        "they are kept on drives."
    )
    prefix: str = Field(description="The folder inside the bucket, or blank.")
    region: str | None
    endpoint: str | None
    profile: str | None
    direct: bool
    bucket_files: int = Field(description="Files recorded in the bucket.")
    bucket_bytes: int
    drive_files: int = Field(description="Files recorded on drives.")
    drive_bytes: int
    left_on_drives: int = Field(
        description="Files recorded on drives while a bucket is used: out of reach."
    )
    can_switch: bool = Field(
        description="Whether the place files are kept may change now: only "
        "while the place being left holds no files, since none are moved."
    )
    blocked: str | None = Field(description="Why not, in plain words.")

    @classmethod
    def from_dto(cls, s: BucketStatus) -> BucketStatusResponse:
        return cls(
            bucket=s.bucket,
            prefix=s.prefix,
            region=s.region,
            endpoint=s.endpoint,
            profile=s.profile,
            direct=s.direct,
            bucket_files=s.bucket_files,
            bucket_bytes=s.bucket_bytes,
            drive_files=s.drive_files,
            drive_bytes=s.drive_bytes,
            left_on_drives=s.left_on_drives,
            can_switch=s.can_switch,
            blocked=s.blocked,
        )


class BucketCheckResponse(BaseModel):
    ok: bool = Field(description="Whether the bucket can be used.")
    problems: list[str] = Field(description="What stops it being used.")
    warnings: list[str] = Field(description="Worth knowing; doesn't stop it.")

    @classmethod
    def from_dto(cls, c: BucketCheck) -> BucketCheckResponse:
        return cls(ok=c.ok, problems=c.problems, warnings=c.warnings)


@router.get("", response_model=BucketStatusResponse)
def get_bucket(ctx: AppContext = Depends(get_ctx)):
    """Where this project's files are kept: the bucket, or drives (`bucket` is
    null), what each holds, and whether that may change now."""
    return BucketStatusResponse.from_dto(ctx.bucket_svc.status())


@router.post("/check", response_model=BucketCheckResponse)
def check_bucket(body: BucketSettingsRequest, ctx: AppContext = Depends(get_ctx)):
    """Try a bucket without using it: reach it, write, read back and remove a
    small object, and make sure no other files are kept under the prefix.
    Nothing is saved."""
    return BucketCheckResponse.from_dto(ctx.bucket_svc.check(body.settings()))


@router.put("", response_model=BucketStatusResponse)
def use_bucket(body: BucketSettingsRequest, ctx: AppContext = Depends(get_ctx)):
    """Keep this project's files in a bucket, or change how the bucket is
    reached. Checked first (422 with the problems). Refused while the place
    being left holds files, since files are never moved between drives and a
    bucket. Saved in the project's settings; takes effect on the next request."""
    return BucketStatusResponse.from_dto(ctx.bucket_svc.use(body.settings()))


@router.delete("", response_model=BucketStatusResponse)
def stop_using_bucket(ctx: AppContext = Depends(get_ctx)):
    """Keep this project's files on drives again. Refused while the bucket
    holds any of them."""
    return BucketStatusResponse.from_dto(ctx.bucket_svc.stop_using())
