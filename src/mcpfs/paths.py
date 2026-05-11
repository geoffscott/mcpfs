from __future__ import annotations

_FORBIDDEN_SEGMENTS = {"", ".", ".."}


class PathError(ValueError):
    pass


def normalize(path: str) -> str:
    """Normalize a user-supplied path into a GCS object name.

    Rules (defense in depth — IAM is the primary boundary):
      * No NUL or control characters.
      * No backslashes (avoid Windows-style traversal surprises).
      * No empty / "." / ".." segments after splitting on "/".
      * Leading and trailing "/" are stripped.
      * Total length <= 1024 (GCS object-name limit).
    """
    if not isinstance(path, str):
        raise PathError("path must be a string")
    if "\x00" in path:
        raise PathError("path contains NUL")
    if any(ord(c) < 0x20 for c in path):
        raise PathError("path contains control characters")
    if "\\" in path:
        raise PathError("path contains backslash")

    stripped = path.strip("/")
    if not stripped:
        raise PathError("path is empty")

    segments = stripped.split("/")
    for seg in segments:
        if seg in _FORBIDDEN_SEGMENTS:
            raise PathError(f"invalid path segment: {seg!r}")

    name = "/".join(segments)
    if len(name.encode("utf-8")) > 1024:
        raise PathError("path exceeds 1024 bytes")
    return name


def normalize_prefix(prefix: str) -> str:
    """Normalize a listing prefix. Empty string means "root"."""
    if prefix in ("", "/"):
        return ""
    name = normalize(prefix)
    return name + "/"
