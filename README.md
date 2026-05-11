# mcpfs

A remote [Model Context Protocol](https://modelcontextprotocol.io) server that exposes
filesystem semantics (`list` / `read` / `write` / `delete` / `stat`) over a single
Google Cloud Storage bucket. Built for solo / small-team use on Google Cloud Run.

- **Auth**: Cloud Run IAM. Clients send a Google OIDC ID token; Google validates
  it before traffic reaches the container. No app-level auth code.
- **Backend**: one private GCS bucket per deployment. Uniform Bucket-Level Access,
  Public Access Prevention, object versioning, lifecycle for noncurrent versions.
- **Audit**: every tool invocation emits a structured Cloud Logging entry tagged
  with caller email and `sub`. Cloud Run admin activity and data access logs are
  captured by Cloud Audit Logs.
- **Concurrency**: optimistic. `fs_write` / `fs_delete` accept
  `if_generation_match` for safe concurrent updates.

## Deploy

Open Cloud Shell in a Google Cloud project that has billing enabled. You need
`roles/owner` (or an equivalent bundle granting Cloud Run admin, Storage admin,
Artifact Registry admin, Service Account admin, and Project IAM admin).

```bash
git clone https://github.com/geoffscott/mcpfs.git
cd mcpfs
./deploy/deploy.sh --project YOUR_PROJECT_ID --region us-central1
```

The script enables the required APIs, creates an Artifact Registry repo, builds
the container with Cloud Build, provisions a bucket and a least-privilege
service account, deploys to Cloud Run, and prints the service URL plus a
`gcloud` snippet for minting a token.

## Use

Get a token (valid for 1 hour):

```bash
gcloud auth print-identity-token \
  --audiences "$(gcloud run services describe mcpfs --region us-central1 --format='value(status.url)')"
```

Configure your MCP client to point at `<service-url>/mcp` with header
`Authorization: Bearer <token>`. Tokens expire after one hour and must be
refreshed by the client.

## Tools

| Tool | Description |
|------|-------------|
| `fs_list` | List under a prefix; non-recursive returns child prefixes too. |
| `fs_stat` | Object metadata (size, updated, generation, md5, content-type). |
| `fs_read` | Read object; utf-8 text when valid, else base64. |
| `fs_write` | Write object; optimistic concurrency via `if_generation_match`. |
| `fs_delete` | Delete object; bucket versioning keeps recovery window. |

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — design and request flow.
- [`docs/SECURITY.md`](docs/SECURITY.md) — control mapping for SOC 2 Type II.

## License

MIT. See [`LICENSE`](LICENSE).
