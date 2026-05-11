from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from google.api_core.exceptions import NotFound, PreconditionFailed
from google.cloud import storage


class ObjectNotFoundError(LookupError):
    pass


class ObjectTooLargeError(ValueError):
    pass


class PreconditionFailedError(RuntimeError):
    pass


@dataclass(frozen=True)
class ObjectStat:
    name: str
    size: int
    updated: str
    content_type: str | None
    md5_hash: str | None
    generation: int


@dataclass(frozen=True)
class ListEntry:
    name: str
    kind: str  # "file" or "prefix"
    size: int | None
    updated: str | None


class GcsBackend:
    def __init__(self, bucket_name: str, max_object_bytes: int, list_page_size: int) -> None:
        self._client = storage.Client()
        self._bucket = self._client.bucket(bucket_name)
        self._max_bytes = max_object_bytes
        self._page_size = list_page_size

    def stat(self, name: str) -> ObjectStat:
        blob = self._bucket.get_blob(name)
        if blob is None:
            raise ObjectNotFoundError(name)
        return ObjectStat(
            name=blob.name,
            size=int(blob.size or 0),
            updated=blob.updated.isoformat() if blob.updated else "",
            content_type=blob.content_type,
            md5_hash=blob.md5_hash,
            generation=int(blob.generation or 0),
        )

    def read(self, name: str) -> tuple[bytes, ObjectStat]:
        stat = self.stat(name)
        if stat.size > self._max_bytes:
            raise ObjectTooLargeError(
                f"object size {stat.size} exceeds limit {self._max_bytes}"
            )
        blob = self._bucket.blob(name)
        data = blob.download_as_bytes(if_generation_match=stat.generation)
        return data, stat

    def write(
        self,
        name: str,
        data: bytes,
        content_type: str | None,
        if_generation_match: int | None,
    ) -> ObjectStat:
        if len(data) > self._max_bytes:
            raise ObjectTooLargeError(
                f"payload size {len(data)} exceeds limit {self._max_bytes}"
            )
        blob = self._bucket.blob(name)
        try:
            blob.upload_from_string(
                data,
                content_type=content_type or "application/octet-stream",
                if_generation_match=if_generation_match,
            )
        except PreconditionFailed as e:
            raise PreconditionFailedError(str(e)) from e
        blob.reload()
        return ObjectStat(
            name=blob.name,
            size=int(blob.size or 0),
            updated=blob.updated.isoformat() if blob.updated else "",
            content_type=blob.content_type,
            md5_hash=blob.md5_hash,
            generation=int(blob.generation or 0),
        )

    def delete(self, name: str, if_generation_match: int | None) -> None:
        blob = self._bucket.blob(name)
        try:
            blob.delete(if_generation_match=if_generation_match)
        except NotFound as e:
            raise ObjectNotFoundError(name) from e
        except PreconditionFailed as e:
            raise PreconditionFailedError(str(e)) from e

    def list(self, prefix: str, recursive: bool) -> Iterator[ListEntry]:
        delimiter = None if recursive else "/"
        iterator = self._client.list_blobs(
            self._bucket,
            prefix=prefix or None,
            delimiter=delimiter,
            page_size=self._page_size,
        )
        for blob in iterator:
            yield ListEntry(
                name=blob.name,
                kind="file",
                size=int(blob.size or 0),
                updated=blob.updated.isoformat() if blob.updated else None,
            )
        for sub_prefix in getattr(iterator, "prefixes", ()) or ():
            yield ListEntry(name=sub_prefix, kind="prefix", size=None, updated=None)
