"""A bucket in memory, shaped like a boto3 S3 client, with an HTTP front for
the presigned URLs it hands out, so the direct-upload path (device → storage →
authority) runs end to end over real sockets without AWS or moto.

Only what `S3ObjectStore` calls is here. A presigned URL is
`http://127.0.0.1:<port>/<bucket>/<key>?op=...`; the front checks what S3
would: a whole-file PUT must carry the `x-amz-checksum-sha256` the URL was
signed with and the bytes must hash to it.
"""

from __future__ import annotations

import base64
import hashlib
import io
import threading
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class ClientError(Exception):
    """Shaped like botocore's: the code is in `response`."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.response = {"Error": {"Code": code, "Message": message}}


class _Body:
    def __init__(self, data: bytes) -> None:
        self._f = io.BytesIO(data)

    def read(self, size: int | None = None) -> bytes:
        return self._f.read(-1 if size is None else size)

    def close(self) -> None:
        self._f.close()

    def __enter__(self) -> _Body:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class _Paginator:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self._pages = pages

    def paginate(self, **_kwargs: Any) -> list[dict[str, Any]]:
        return self._pages


class FakeS3:
    def __init__(self, serve: bool = False, page_size: int = 2) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, datetime]] = {}
        self.uploads: dict[str, dict[str, Any]] = {}
        self.calls: list[str] = []
        self.page_size = page_size  # small, so paging is exercised
        self._server: ThreadingHTTPServer | None = None
        self.base = "http://s3.invalid"
        if serve:
            self._server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(self))
            threading.Thread(target=self._server.serve_forever, daemon=True).start()
            self.base = f"http://127.0.0.1:{self._server.server_port}"

    def close(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()

    # -- boto3 client shape ----------------------------------------------

    def put_object(
        self, Bucket: str, Key: str, Body: Any, ChecksumSHA256: str | None = None
    ) -> dict[str, Any]:
        self.calls.append("put_object")
        data = Body if isinstance(Body, bytes) else Body.read()
        if ChecksumSHA256 is not None and _b64sha(data) != ChecksumSHA256:
            raise ClientError("BadDigest", "The SHA256 you specified did not match")
        self.objects[(Bucket, Key)] = (data, _now())
        return {"ETag": _etag(data)}

    def upload_file(
        self, Filename: str, Bucket: str, Key: str, ExtraArgs: Any = None
    ) -> None:
        self.calls.append("upload_file")
        with open(Filename, "rb") as f:
            self.objects[(Bucket, Key)] = (f.read(), _now())

    def get_object(self, Bucket: str, Key: str, Range: str | None = None) -> dict:
        self.calls.append("get_object")
        data = self._get(Bucket, Key)
        if Range:
            start, _, end = Range.removeprefix("bytes=").partition("-")
            data = data[int(start) : (int(end) + 1) if end else None]
        return {"Body": _Body(data), "ContentLength": len(data)}

    def head_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        self.calls.append("head_object")
        data, modified = self._entry(Bucket, Key)
        return {"ContentLength": len(data), "LastModified": modified}

    def delete_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        self.calls.append("delete_object")
        self.objects.pop((Bucket, Key), None)
        return {}

    def list_objects_v2(
        self, Bucket: str, Prefix: str = "", MaxKeys: int = 1000
    ) -> dict[str, Any]:
        self.calls.append("list_objects_v2")
        items = [
            {"Key": key, "Size": len(data), "LastModified": modified}
            for (bucket, key), (data, modified) in sorted(self.objects.items())
            if bucket == Bucket and key.startswith(Prefix)
        ][:MaxKeys]
        return {"Contents": items, "KeyCount": len(items)} if items else {"KeyCount": 0}

    def get_paginator(self, name: str) -> _Paginator:
        if name == "list_objects_v2":
            items = [
                {"Key": key, "Size": len(data), "LastModified": modified}
                for (_, key), (data, modified) in sorted(self.objects.items())
            ]
            pages = [
                {"Contents": items[i : i + self.page_size]}
                for i in range(0, len(items), self.page_size)
            ] or [{}]
            return _Paginator(pages)
        if name == "list_multipart_uploads":
            uploads = [
                {"UploadId": uid, "Key": u["key"], "Initiated": u["initiated"]}
                for uid, u in self.uploads.items()
            ]
            return _Paginator([{"Uploads": uploads}] if uploads else [{}])
        raise ValueError(name)

    def create_multipart_upload(self, Bucket: str, Key: str) -> dict[str, Any]:
        self.calls.append("create_multipart_upload")
        upload_id = uuid.uuid4().hex
        self.uploads[upload_id] = {
            "bucket": Bucket,
            "key": Key,
            "parts": {},
            "initiated": _now(),
        }
        return {"UploadId": upload_id}

    def upload_part(
        self, Bucket: str, Key: str, UploadId: str, PartNumber: int, Body: Any
    ) -> dict[str, Any]:
        data = Body if isinstance(Body, bytes) else Body.read()
        self.uploads[UploadId]["parts"][int(PartNumber)] = data
        return {"ETag": _etag(data)}

    def complete_multipart_upload(
        self, Bucket: str, Key: str, UploadId: str, MultipartUpload: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append("complete_multipart_upload")
        upload = self.uploads.pop(UploadId)
        data = b""
        for part in sorted(MultipartUpload["Parts"], key=lambda p: p["PartNumber"]):
            stored = upload["parts"][int(part["PartNumber"])]
            if _etag(stored) != part["ETag"]:
                raise ClientError("InvalidPart", "ETag does not match")
            data += stored
        self.objects[(Bucket, Key)] = (data, _now())
        return {}

    def abort_multipart_upload(self, Bucket: str, Key: str, UploadId: str) -> dict:
        self.calls.append("abort_multipart_upload")
        self.uploads.pop(UploadId, None)
        return {}

    def generate_presigned_url(
        self,
        ClientMethod: str,
        Params: dict[str, Any],
        ExpiresIn: int = 3600,
        HttpMethod: str | None = None,
    ) -> str:
        query: dict[str, str] = {"X-Amz-Expires": str(ExpiresIn)}
        if ClientMethod == "put_object":
            query["op"] = "put"
            if "ChecksumSHA256" in Params:
                query["checksum"] = Params["ChecksumSHA256"]
        elif ClientMethod == "upload_part":
            query["op"] = "part"
            query["uploadId"] = Params["UploadId"]
            query["partNumber"] = str(Params["PartNumber"])
        elif ClientMethod == "get_object":
            query["op"] = "get"
            if "ResponseContentDisposition" in Params:
                query["response-content-disposition"] = Params[
                    "ResponseContentDisposition"
                ]
        else:
            raise ValueError(ClientMethod)
        path = f"/{Params['Bucket']}/{urllib.parse.quote(Params['Key'])}"
        return f"{self.base}{path}?{urllib.parse.urlencode(query)}"

    # -- for tests ----------------------------------------------------------

    def age_uploads(self, seconds: float) -> None:
        for upload in self.uploads.values():
            upload["initiated"] -= timedelta(seconds=seconds)

    def _entry(self, bucket: str, key: str) -> tuple[bytes, datetime]:
        try:
            return self.objects[(bucket, key)]
        except KeyError:
            raise ClientError("404", "Not Found") from None

    def _get(self, bucket: str, key: str) -> bytes:
        return self._entry(bucket, key)[0]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _etag(data: bytes) -> str:
    return '"' + hashlib.md5(data).hexdigest() + '"'


def _b64sha(data: bytes) -> str:
    return base64.b64encode(hashlib.sha256(data).digest()).decode("ascii")


def _handler(fake: FakeS3) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:  # quiet
            pass

        def _where(self) -> tuple[str, str, dict[str, str]]:
            url = urllib.parse.urlsplit(self.path)
            bucket, _, key = url.path.lstrip("/").partition("/")
            query = dict(urllib.parse.parse_qsl(url.query))
            return bucket, urllib.parse.unquote(key), query

        def _body(self) -> bytes:
            return self.rfile.read(int(self.headers.get("Content-Length", "0")))

        def _answer(self, status: int, body: bytes = b"", **headers: str) -> None:
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name.replace("_", "-"), value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_PUT(self) -> None:  # noqa: N802 - the stdlib's name
            bucket, key, query = self._where()
            data = self._body()
            if query.get("op") == "put":
                # S3 refuses an unsigned x-amz header and a wrong checksum.
                sent = self.headers.get("x-amz-checksum-sha256")
                if "checksum" in query and (
                    sent != query["checksum"] or _b64sha(data) != sent
                ):
                    return self._answer(400, b"BadDigest")
                if self.headers.get("Authorization"):
                    return self._answer(400, b"Only one auth mechanism allowed")
                fake.objects[(bucket, key)] = (data, _now())
                return self._answer(200, ETag=_etag(data))
            if query.get("op") == "part":
                etag = fake.upload_part(
                    bucket, key, query["uploadId"], int(query["partNumber"]), data
                )["ETag"]
                return self._answer(200, ETag=etag)
            self._answer(400, b"unknown operation")

        def do_GET(self) -> None:  # noqa: N802
            bucket, key, query = self._where()
            if self.headers.get("Authorization"):
                return self._answer(400, b"Only one auth mechanism allowed")
            try:
                data = fake._get(bucket, key)
            except ClientError:
                return self._answer(404, b"NoSuchKey")
            headers = {}
            if "response-content-disposition" in query:
                headers["Content_Disposition"] = query["response-content-disposition"]
            self._answer(200, data, **headers)

        do_HEAD = do_GET  # noqa: N815

    return Handler
