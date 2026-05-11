# Security & SOC 2 control mapping

This document describes the security posture of `mcpfs` and how each design
decision maps to common SOC 2 Type II controls. It is a starting point for an
audit, not a substitute for one. The Common Criteria reference numbers below
follow the AICPA's 2017 TSC.

## Trust boundary

```
+--- Untrusted ---------+--- Trusted (Google-validated) ---+--- Trusted (in-process) ---+
| Caller, public Internet| Cloud Run edge: TLS + IAM + token | mcpfs container + GCS SDK  |
+------------------------+-----------------------------------+----------------------------+
```

The only code path from "untrusted" to "trusted" is Cloud Run's managed
authentication. No application-layer secret is involved in authentication.

## Controls

### CC6.1 — Logical access: authentication

- Cloud Run service is deployed `--no-allow-unauthenticated`. Anonymous requests
  are rejected at the edge with HTTP 403, before any container code executes.
- Callers must hold `roles/run.invoker` on the service. The deploy script grants
  this binding only to principals supplied via `--invoker` (default: the
  deploying user).
- Authentication is performed by Google with Google-issued OIDC ID tokens
  bound to the service URL as audience. No shared secrets, no static API keys,
  no application-managed credential material.
- Tokens are short-lived (≤ 1 hour). Revocation propagates via Google's session
  management.

### CC6.1 — Logical access: authorization

- The container itself does no authorization beyond enforcing path validation
  and size limits — there is one authorization boundary (Cloud Run IAM) so
  there is only one source of truth to audit.
- The runtime service account holds exactly one role on exactly one bucket:
  `roles/storage.objectAdmin` on `gs://<project>-mcpfs`. It has no
  project-level roles.

### CC6.6 — Boundary protection

- Service is deployed with `--ingress all` but is non-anonymous; IAM is the
  boundary. For a stricter posture, redeploy with `--ingress internal-and-cloud-load-balancing`
  behind an external HTTPS LB with Cloud Armor (out of scope for v1).
- TLS terminated by Google Front Ends; minimum TLS 1.2; certs managed by
  Google.
- Container listens only on `$PORT` (Cloud Run's loopback ingress); no other
  ports are opened.

### CC6.7 — Data in transit

- All traffic in scope is HTTPS to `*.run.app`. The container has no outbound
  TLS-stripping proxy; calls to GCS use HTTPS via the official SDK.

### CC6.8 — Data at rest

- GCS objects are encrypted with Google-managed AES-256 keys by default.
- Bucket has Public Access Prevention enforced and Uniform Bucket-Level Access
  enabled, preventing accidental ACL-based exposure.
- Bucket has soft-delete (7d) and object versioning enabled; deletions are
  recoverable within the configured retention window.
- CMEK can be added without code changes if required for a stricter
  cryptographic-control narrative.

### CC7.1 — Detection of vulnerabilities

- Container builds from `python:3.12-slim-bookworm` and runs `apt-get upgrade`
  to apply current Debian security patches at build time.
- Application dependencies are pinned by minimum version in `pyproject.toml`;
  a lock file (`uv lock` or `pip-compile`) should be added for reproducible
  builds before production use.
- Artifact Registry supports container scanning; enable
  `containeranalysis.googleapis.com` to surface CVE findings.

### CC7.2 — System monitoring & logging

- Cloud Run produces request logs and the platform emits Admin Activity audit
  logs unconditionally.
- The container emits structured JSON to stdout. Every tool invocation logs:
  `event` (`fs.list` / `fs.stat` / `fs.read` / `fs.write` / `fs.delete`),
  `caller_email`, `caller_sub`, `path`, `generation`, `size`. Cloud Logging
  ingests stdout automatically.
- For long-term retention (SOC 2 expects ≥ 1 year for many control areas),
  configure a log sink from Cloud Logging to a dedicated logging bucket or
  BigQuery dataset with retention locks. This is intentionally not done by
  `deploy.sh` to avoid creating storage outside the operator's review.

### CC7.3 — Incident response inputs

- Caller identity is captured in every log line, enabling fast attribution.
- Object versioning + soft-delete provide a recovery window for accidental or
  malicious data destruction.

### CC8.1 — Change management

- All deploys flow through Cloud Build → Artifact Registry → Cloud Run.
  Cloud Build produces a provenance record per build.
- `deploy.sh` is idempotent and the only supported deployment path; ad-hoc
  `gcloud run deploy --source` is discouraged because it bypasses image
  provenance.

### CC9.2 — Vendor management

- The only third-party runtime dependency is Google Cloud. All other deps are
  open-source Python libraries declared in `pyproject.toml`.

## Hardening choices in the container

- Runs as non-root (UID 10001), no shell, no home directory, no setuid bits
  added.
- `tini` is PID 1 to reap zombies and forward signals cleanly.
- No build tools in the runtime image (multi-stage build).
- Only `ca-certificates` and `tini` installed beyond the Python base image.

## Hardening choices in the bucket

- Uniform Bucket-Level Access: object ACLs are disabled; only IAM grants
  access.
- Public Access Prevention: enforced; the bucket cannot be made public.
- Soft delete: 7 days.
- Object versioning: on.
- Lifecycle: noncurrent versions deleted after 30 days (configurable).
- Location: regional, matching the Cloud Run region for data-residency clarity.

## Path-validation hardening (defense in depth)

The IAM boundary is primary, but the server independently rejects:

- NUL bytes and ASCII control characters in object names.
- Backslashes (`\`).
- `.` or `..` path segments.
- Empty segments (`//`).
- Names longer than 1024 bytes UTF-8.

This protects against path-confusion bugs even if a future change widens the
trust boundary.

## Known limitations

- No CMEK in v1. (Decision: simpler control narrative weighed against minor
  extra cryptographic-key control; revisit if customer contracts require it.)
- No WAF (Cloud Armor). IAM is the only gate. Adequate for solo / small-team
  use; revisit for broad exposure.
- No automated dependency-update pipeline (Dependabot/Renovate). Should be
  added before production.
- No log sink for long-term retention. Operator must configure this in their
  log-management process.

## Reporting vulnerabilities

Please open a private security advisory on GitHub rather than a public issue.
