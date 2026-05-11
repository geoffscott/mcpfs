# Architecture

## Components

```
┌───────────────┐    Authorization: Bearer <Google ID token>     ┌───────────────────┐
│   MCP client  │ ─────────────────────────────────────────────► │ Cloud Run (mcpfs) │
└───────────────┘            (Streamable HTTP)                   └─────────┬─────────┘
                                                                           │
                                                  Application Default      │
                                                  Credentials (runtime SA) │
                                                                           ▼
                                                                  ┌─────────────────┐
                                                                  │  GCS bucket     │
                                                                  │  (private, UBLA)│
                                                                  └─────────────────┘
```

Everything is one Cloud Run service, one bucket, one runtime service account,
one Artifact Registry repo. There is no database, no queue, no cache.

## Request flow

1. Client mints a Google OIDC ID token whose audience is the Cloud Run service
   URL (`gcloud auth print-identity-token --audiences <url>` or the SDK
   equivalent).
2. Client opens a Streamable-HTTP MCP connection to `<url>/mcp` with
   `Authorization: Bearer <id-token>`.
3. Cloud Run validates the token at the edge against `roles/run.invoker` for
   the service. Unauthenticated calls return 403 before any code runs.
4. The container's `IdentityMiddleware` decodes the JWT payload (signature
   already verified by Cloud Run) and binds caller email/sub into the
   structlog context. Every subsequent log line carries the caller.
5. FastMCP routes the JSON-RPC tool call to one of `fs_list`, `fs_stat`,
   `fs_read`, `fs_write`, `fs_delete`.
6. The tool normalizes the path (rejecting NUL, control chars, backslashes,
   `..` segments, oversized names), calls the GCS backend with the runtime
   SA's ADC, and returns a structured result.
7. Every tool emits a structured log line (`event=fs.<op>`) tagged with caller,
   path, generation, size. Cloud Logging ingests stdout automatically.

## Storage model

Object names are forward-slash separated. There is no "directory" concept on
the wire — `fs_list` synthesizes child prefixes from GCS's delimiter behavior.

Object versioning is enabled on the bucket. Every `fs_write` produces a new
generation; every `fs_delete` archives the prior generation as a noncurrent
version. A lifecycle rule deletes noncurrent versions after N days (30 by
default; configurable in `deploy.sh`).

All writes and deletes accept an `if_generation_match` parameter. Callers that
want lost-update protection pass the generation they last observed; the server
returns HTTP 412 / MCP tool error on mismatch.

## Encryption

- **In transit**: TLS 1.2+ terminated by Cloud Run's managed load balancer.
- **At rest**: Google-managed AES-256 on GCS. CMEK is not configured in v1 but
  can be added without code changes by setting a default KMS key on the bucket.

## Audit

Three independent log streams describe every action:

1. **Cloud Run request logs** — caller principal, latency, status; produced by
   the platform.
2. **Cloud Audit Logs** — admin activity (deploys, IAM changes) and data access
   (toggleable on the bucket; off by default for cost).
3. **Application logs** — structured stdout JSON from the container, including
   `caller_email`, `caller_sub`, `path`, `generation`, `size` for every tool
   invocation.

All three land in Cloud Logging with the project's default retention. For
long-term retention, configure a log sink to a separate logging bucket or BigQuery
dataset; this is out of scope for the deploy script to keep the blast radius
small.

## Non-goals (v1)

- Multi-tenant isolation. One service ⇒ one bucket ⇒ one team.
- Directory primitives beyond what `list` infers.
- Range reads or resumable uploads. Max object size is bounded by
  `MCPFS_MAX_OBJECT_BYTES` (default 10 MiB).
- Search / metadata queries.
- OAuth 2.1 MCP-spec authorization. Cloud Run IAM is the boundary.
