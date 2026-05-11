#!/usr/bin/env bash
# Seed the bucket with the fixture data referenced by evals/mcpfs_eval.xml.
#
# Usage:
#   ./evals/seed.sh --bucket BUCKET_NAME
#
# Requires: gcloud (or gsutil) authenticated against a principal with
# objectAdmin on the bucket. Re-running is idempotent — files are overwritten.

set -euo pipefail

BUCKET=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bucket) BUCKET="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$BUCKET" ]]; then
  echo "error: --bucket is required" >&2
  exit 2
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/notes" "$TMP/data" "$TMP/logs" "$TMP/config" "$TMP/archive"

# README.txt: exactly 31 bytes, no trailing newline. The eval asks for size.
printf 'Welcome to mcpfs. Version 1.0.0' > "$TMP/README.txt"

cat > "$TMP/notes/alpha.md" <<'EOF'
# Project alpha
Owner: alice
Status: in-progress
EOF

cat > "$TMP/notes/beta.md" <<'EOF'
# Project beta
Owner: bob
Status: shipped
EOF

cat > "$TMP/notes/gamma.md" <<'EOF'
# Project gamma
Owner: carol
Status: blocked
Blocker: needs review
EOF

cat > "$TMP/data/inventory.csv" <<'EOF'
sku,qty
A1,10
A2,25
B1,7
EOF

cat > "$TMP/data/orders.csv" <<'EOF'
order_id,sku,qty
101,A1,2
102,B1,5
103,A2,3
EOF

cat > "$TMP/logs/2024-01-01.log" <<'EOF'
ERROR x42
WARN x7
INFO x150
EOF

cat > "$TMP/logs/2024-01-02.log" <<'EOF'
ERROR x12
WARN x3
INFO x200
EOF

cat > "$TMP/config/app.json" <<'EOF'
{"feature_x": true, "max_users": 100, "region": "us-central1"}
EOF

# archive/old.bin: 10 bytes of non-utf-8 data so fs_read returns base64.
printf '\x00\x01\x02\xff\xfe\xfd\x80\x81\x82\x83' > "$TMP/archive/old.bin"

echo "Uploading fixture to gs://$BUCKET/ ..."
gcloud storage cp --recursive "$TMP"/* "gs://$BUCKET/" --quiet

cat <<EOF
Done. Seeded objects:
  README.txt                          (31 bytes)
  notes/{alpha,beta,gamma}.md         (3 files)
  data/{inventory,orders}.csv         (2 files)
  logs/2024-01-{01,02}.log            (2 files)
  config/app.json                     (1 file)
  archive/old.bin                     (10 bytes binary)

Now run the eval set in evals/mcpfs_eval.xml against your MCP client.
EOF
