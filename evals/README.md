# mcpfs evaluations

Ten read-only Q/A pairs that test whether an LLM can effectively drive the
mcpfs MCP server to answer realistic questions. Built per the Anthropic
`mcp-builder` skill's Phase 4 guidance.

## What's here

| File | Purpose |
|------|---------|
| `seed.sh` | Populates a bucket with the fixture data the questions reference. Idempotent. |
| `mcpfs_eval.xml` | The 10 `<qa_pair>` entries. Answers are exact-match strings. |

## Question design

Each question is:

- **Independent** — answerable without state from prior questions.
- **Read-only** — uses only `fs_list`, `fs_stat`, `fs_read`.
- **Multi-step** — most require at least two tool calls (list to discover the right path, then read; or read multiple files and aggregate).
- **Verifiable** — single deterministic answer suitable for string match.
- **Stable** — fixture is fixed; no time-varying data.

## How to run

```bash
# 1. Deploy mcpfs (one-time):
./deploy/deploy.sh --project YOUR_PROJECT_ID

# 2. Seed the fixture (against the same bucket the service uses):
./evals/seed.sh --bucket YOUR_PROJECT_ID-mcpfs

# 3. Point your evaluation harness or MCP-capable LLM at the service URL
#    and feed it the 10 questions from mcpfs_eval.xml. Score with simple
#    string equality on each <answer>.
```

A bare-bones scorer can be a few lines of any language: parse the XML, ask
the model to answer using the MCP tools, compare its final answer to
`<answer>` after stripping whitespace.

## Re-seeding / cleanup

`seed.sh` is idempotent — re-running overwrites the same paths. To remove the
fixture, `gcloud storage rm -r gs://<bucket>/README.txt gs://<bucket>/notes
gs://<bucket>/data gs://<bucket>/logs gs://<bucket>/config gs://<bucket>/archive`.
