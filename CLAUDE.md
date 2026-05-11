# mcpfs — agent context

A remote MCP server that exposes filesystem semantics (`list` / `read` /
`write` / `delete` / `stat`) over a single private Google Cloud Storage bucket,
fronted by Cloud Run IAM. MIT licensed, solo-maintained, designed to pass a
SOC 2 Type II audit.

## Layout

| Path | Purpose |
|------|---------|
| `src/mcpfs/server.py` | FastMCP tools + Starlette app + identity middleware. |
| `src/mcpfs/gcs.py` | Thin wrapper over `google-cloud-storage`. |
| `src/mcpfs/paths.py` | Path validator (defense in depth behind Cloud Run IAM). |
| `src/mcpfs/identity.py` | Decodes the Cloud-Run-verified JWT for audit logging. |
| `src/mcpfs/config.py` | Pydantic settings, env prefix `MCPFS_`. |
| `src/mcpfs/logging.py` | structlog → JSON to stdout (Cloud Logging picks it up). |
| `Dockerfile` | Multi-stage, non-root UID 10001, tini PID 1, python:3.12-slim. |
| `deploy/deploy.sh` | Idempotent Cloud Shell provisioner. |
| `docs/ARCHITECTURE.md` | Request flow, storage model, non-goals. |
| `docs/SECURITY.md` | SOC 2 control mapping. |
| `tests/` | Pytest suite. |

## Conventions

- **Python ≥ 3.11** for tooling; the production container runs 3.12. Use modern
  syntax (`str | None`, `dict[str, X]`).
- **No app-level auth code.** Cloud Run IAM is the boundary. `identity.py` only
  *decodes* (without re-verifying) the already-validated JWT to attribute logs.
  Do not add token-verification code; it would just duplicate Cloud Run's edge
  enforcement and increase audit surface.
- **Path safety**: anything reaching GCS must go through `paths.normalize`. Do
  not stringly-concatenate object names from user input.
- **Optimistic concurrency**: writes and deletes accept `if_generation_match`.
  Preserve this in any new mutating tool.
- **Logging**: every tool emits one `log.info("fs.<op>", ...)` with caller and
  path context. Keep this for the audit trail.
- **No new runtime dependencies** without a clear need — every dep widens SOC 2
  scope.
- **Comments**: only where the *why* is non-obvious. Don't restate the code.

## Common commands

```bash
# Install for dev (also done by the SessionStart hook):
pip install --user -e '.[dev]'

# Lint:
ruff check src tests

# Type-check:
mypy src

# Tests:
pytest -q

# Deploy (from Cloud Shell with billing-enabled project):
./deploy/deploy.sh --project YOUR_PROJECT
```

## Where decisions are recorded

- **Why Cloud Run IAM, not OAuth 2.1**: `docs/SECURITY.md` ("Logical access").
- **Why Google-managed encryption, not CMEK**: `docs/SECURITY.md` ("Known
  limitations"). CMEK is a one-flag upgrade if needed.
- **Why minimal FS scope (no mkdir / move / ACL)**: keeps the audit surface
  small for v1. Revisit on user feedback, not speculatively.

## Don't

- Don't push to `main` directly; develop on a feature branch.
- Don't add `gh`/`hub` CLI calls — this environment uses MCP GitHub tools.
- Don't broaden the runtime SA's IAM beyond bucket-scoped `objectAdmin`.
- Don't introduce a database, cache, or queue. If you reach for one, the
  design is probably wrong.
