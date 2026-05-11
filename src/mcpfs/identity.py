"""Extract caller identity from the Cloud Run-validated bearer token.

Cloud Run validates the incoming Google-issued ID token at the edge and rejects
unauthenticated requests when the service is deployed with `--no-allow-unauthenticated`.
The original `Authorization: Bearer <id-token>` header is forwarded to the
container unchanged. We decode (without re-verifying) the JWT payload here purely
to capture the caller's email / subject for application-level audit logging.

The security boundary is enforced by Cloud Run + IAM. This module never grants
access — it only attributes calls in our logs.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class Caller:
    sub: str
    email: str | None
    raw_iss: str | None

    def display(self) -> str:
        return self.email or self.sub


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def parse_caller(authorization_header: str | None) -> Caller | None:
    if not authorization_header:
        return None
    parts = authorization_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    segments = token.split(".")
    if len(segments) != 3:
        return None
    try:
        payload = json.loads(_b64url_decode(segments[1]))
    except (ValueError, json.JSONDecodeError):
        return None
    sub = payload.get("sub")
    if not isinstance(sub, str):
        return None
    email = payload.get("email")
    iss = payload.get("iss")
    return Caller(
        sub=sub,
        email=email if isinstance(email, str) else None,
        raw_iss=iss if isinstance(iss, str) else None,
    )
