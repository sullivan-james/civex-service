"""civex store bucket -- keep a project's files in an S3 bucket instead of on
drives, or on drives again (`BucketService`, the same calls as the app's
Settings → Storage)."""

from __future__ import annotations

from typing import Optional

import typer

from civex.cli.utils import format_bytes, get_ctx
from civex.console import console
from civex.domain.dtos import BucketStatus
from civex.domain.exceptions import CivexError
from civex.services.bucket_service import settings_of

bucket_app = typer.Typer(
    help="Keep this project's files in an S3 bucket instead of on drives",
    no_args_is_help=True,
)

_PREFIX = typer.Option("", "--prefix", help="A folder inside the bucket.")
_REGION = typer.Option(None, "--region", help="The bucket's region.")
_ENDPOINT = typer.Option(
    None,
    "--endpoint",
    help="A service speaking S3's API other than AWS, e.g. http://127.0.0.1:9000 "
    "for MinIO.",
)
_PROFILE = typer.Option(
    None,
    "--profile",
    help="An AWS profile to take credentials from. Without one, credentials come "
    "from the environment (AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY) or the "
    "machine's role; civex never saves them.",
)
_DIRECT = typer.Option(
    True,
    "--direct/--no-direct",
    help="Whether files go straight between a browser or device and the bucket, "
    "rather than through civex.",
)


def _show(s: BucketStatus) -> None:
    if s.bucket is None:
        console.print("Files are kept on drives on this computer.")
    else:
        where = s.bucket + (f"/{s.prefix}" if s.prefix else "")
        console.print(f"Files are kept in the bucket [bold]{where}[/bold].")
        if s.endpoint:
            console.print(f"  Endpoint: {s.endpoint}")
        if s.region:
            console.print(f"  Region: {s.region}")
        if s.profile:
            console.print(f"  Profile: {s.profile}")
        console.print(
            "  Files go straight to and from the bucket."
            if s.direct
            else "  Files go through civex."
        )
        console.print(
            f"  Holds {s.bucket_files:,} file(s), {format_bytes(s.bucket_bytes)}."
        )
        if s.left_on_drives:
            console.print(
                f"[warning]{s.left_on_drives:,} file(s) are recorded on drives, "
                "which a project using a bucket can't reach.[/warning]"
            )
    if s.blocked:
        console.print(f"[dim]{s.blocked}[/dim]")


@bucket_app.command("show")
def show(
    check: bool = typer.Option(
        False, "--check", help="Also try the bucket: reach it, write and read back."
    ),
) -> None:
    """Say where this project's files are kept: a bucket, or drives."""
    ctx = get_ctx()
    try:
        status = ctx.bucket_svc.status()
        _show(status)
        if check and status.bucket is not None:
            found = ctx.bucket_svc.check(
                settings_of(
                    status.bucket,
                    status.prefix,
                    status.region,
                    status.endpoint,
                    status.profile,
                    status.direct,
                )
            )
            _report(found.problems, found.warnings)
            if not found.ok:
                raise typer.Exit(1)
    finally:
        ctx.close()


def _report(problems: list[str], warnings: list[str]) -> None:
    for p in problems:
        console.print(f"[error]{p}[/error]")
    for w in warnings:
        console.print(f"[warning]{w}[/warning]")
    if not problems:
        console.print("[success]The bucket can be used.[/success]")


@bucket_app.command("check")
def check(
    bucket: str = typer.Argument(..., help="The bucket's name."),
    prefix: str = _PREFIX,
    region: Optional[str] = _REGION,
    endpoint: Optional[str] = _ENDPOINT,
    profile: Optional[str] = _PROFILE,
) -> None:
    """Try a bucket without using it: reach it, write, read back and remove a
    small object, and make sure no other files are kept under the prefix."""
    ctx = get_ctx()
    try:
        found = ctx.bucket_svc.check(
            settings_of(bucket, prefix, region, endpoint, profile)
        )
    except CivexError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1) from None
    finally:
        ctx.close()
    _report(found.problems, found.warnings)
    if not found.ok:
        raise typer.Exit(1)


@bucket_app.command("set")
def set_bucket(
    bucket: str = typer.Argument(..., help="The bucket's name."),
    prefix: str = _PREFIX,
    region: Optional[str] = _REGION,
    endpoint: Optional[str] = _ENDPOINT,
    profile: Optional[str] = _PROFILE,
    direct: bool = _DIRECT,
) -> None:
    """Keep this project's files in a bucket, or change how the bucket is
    reached.

    The bucket is tried first. Files are never moved between drives and a
    bucket, so this is refused while the project keeps files on its drives
    (or, to change bucket or prefix, in the bucket it uses). Works with AWS S3
    and anything speaking its API, such as MinIO or Cloudflare R2.
    """
    ctx = get_ctx()
    try:
        status = ctx.bucket_svc.use(
            settings_of(bucket, prefix, region, endpoint, profile, direct)
        )
    except CivexError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1) from None
    finally:
        ctx.close()
    _show(status)


@bucket_app.command("clear")
def clear() -> None:
    """Keep this project's files on drives again. Refused while the bucket
    holds any of them."""
    ctx = get_ctx()
    try:
        status = ctx.bucket_svc.stop_using()
    except CivexError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1) from None
    finally:
        ctx.close()
    _show(status)
