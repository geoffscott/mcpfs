#!/usr/bin/env bash
# mcpfs Cloud Run deploy script.
#
# Provisions, in an existing GCP project with billing enabled:
#   - required APIs
#   - Artifact Registry Docker repo
#   - GCS bucket (UBLA, PAP, versioning, lifecycle)
#   - dedicated service account with bucket-scoped IAM
#   - Cloud Run service (private, IAM-authenticated)
#
# Idempotent: re-running updates resources in place.
#
# Usage:
#   ./deploy/deploy.sh --project PROJECT_ID [options]
#
# Options:
#   --project PROJECT_ID      (required) Target GCP project.
#   --region   REGION         Cloud Run region (default: us-central1).
#   --service  NAME           Cloud Run service name (default: mcpfs).
#   --bucket   NAME           GCS bucket name (default: PROJECT_ID-mcpfs).
#   --repo     NAME           Artifact Registry repo (default: mcpfs).
#   --sa-name  NAME           Service account local part (default: mcpfs-runtime).
#   --invoker  PRINCIPAL      Principal to grant run.invoker (default: current gcloud user).
#                              Repeat for multiple. Format: user:..., group:..., serviceAccount:...
#   --max-object-bytes BYTES  Max read/write size in bytes (default: 10485760).
#   --noncurrent-days  DAYS   Retention for deleted/overwritten versions (default: 30).
#   --help                    Show this help.

set -euo pipefail

PROJECT=""
REGION="us-central1"
SERVICE="mcpfs"
BUCKET=""
REPO="mcpfs"
SA_NAME="mcpfs-runtime"
MAX_OBJECT_BYTES="10485760"
NONCURRENT_DAYS="30"
INVOKERS=()

usage() { sed -n '2,28p' "$0"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)            PROJECT="$2"; shift 2 ;;
    --region)             REGION="$2"; shift 2 ;;
    --service)            SERVICE="$2"; shift 2 ;;
    --bucket)             BUCKET="$2"; shift 2 ;;
    --repo)               REPO="$2"; shift 2 ;;
    --sa-name)            SA_NAME="$2"; shift 2 ;;
    --invoker)            INVOKERS+=("$2"); shift 2 ;;
    --max-object-bytes)   MAX_OBJECT_BYTES="$2"; shift 2 ;;
    --noncurrent-days)    NONCURRENT_DAYS="$2"; shift 2 ;;
    --help|-h)            usage; exit 0 ;;
    *) echo "unknown flag: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$PROJECT" ]]; then
  echo "error: --project is required" >&2
  usage >&2
  exit 2
fi

BUCKET="${BUCKET:-${PROJECT}-mcpfs}"
SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${SERVICE}:$(date -u +%Y%m%d-%H%M%S)"

if [[ ${#INVOKERS[@]} -eq 0 ]]; then
  CURRENT_USER="$(gcloud config get-value account 2>/dev/null || true)"
  if [[ -z "$CURRENT_USER" ]]; then
    echo "error: no --invoker provided and gcloud has no active account" >&2
    exit 2
  fi
  INVOKERS+=("user:${CURRENT_USER}")
fi

step() { printf "\n\033[1;34m==>\033[0m %s\n" "$*"; }
trace() { printf "    \033[2m%s\033[0m\n" "$*"; }

gcloud config set project "$PROJECT" >/dev/null
trace "project = $PROJECT"
trace "region  = $REGION"
trace "bucket  = $BUCKET"
trace "service = $SERVICE"
trace "image   = $IMAGE"
trace "sa      = $SA_EMAIL"

step "Enabling required APIs"
gcloud services enable \
  run.googleapis.com \
  storage.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  logging.googleapis.com \
  --project "$PROJECT" --quiet

step "Ensuring Artifact Registry repo '$REPO' in $REGION"
if ! gcloud artifacts repositories describe "$REPO" --location "$REGION" --project "$PROJECT" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$REPO" \
    --repository-format=docker \
    --location="$REGION" \
    --description="mcpfs container images" \
    --project "$PROJECT"
fi

step "Ensuring GCS bucket gs://$BUCKET"
if ! gcloud storage buckets describe "gs://$BUCKET" --project "$PROJECT" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://$BUCKET" \
    --project "$PROJECT" \
    --location "$REGION" \
    --uniform-bucket-level-access \
    --public-access-prevention \
    --soft-delete-duration=7d
fi
# Apply hardening that's safe to re-assert each run.
gcloud storage buckets update "gs://$BUCKET" \
  --project "$PROJECT" \
  --uniform-bucket-level-access \
  --public-access-prevention \
  --versioning

LIFECYCLE_JSON="$(mktemp)"
trap 'rm -f "$LIFECYCLE_JSON"' EXIT
cat > "$LIFECYCLE_JSON" <<EOF
{
  "lifecycle": {
    "rule": [
      {
        "action": { "type": "Delete" },
        "condition": { "daysSinceNoncurrentTime": ${NONCURRENT_DAYS} }
      }
    ]
  }
}
EOF
gcloud storage buckets update "gs://$BUCKET" \
  --project "$PROJECT" \
  --lifecycle-file="$LIFECYCLE_JSON"

step "Ensuring runtime service account $SA_EMAIL"
if ! gcloud iam service-accounts describe "$SA_EMAIL" --project "$PROJECT" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$SA_NAME" \
    --display-name="mcpfs Cloud Run runtime" \
    --description="Least-privilege identity for the mcpfs Cloud Run service" \
    --project "$PROJECT"
fi

step "Granting bucket-scoped IAM to $SA_EMAIL"
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --project "$PROJECT" \
  --member="serviceAccount:$SA_EMAIL" \
  --role="roles/storage.objectAdmin" >/dev/null

step "Building image with Cloud Build"
gcloud builds submit \
  --project "$PROJECT" \
  --tag "$IMAGE"

step "Deploying Cloud Run service '$SERVICE'"
gcloud run deploy "$SERVICE" \
  --project "$PROJECT" \
  --region "$REGION" \
  --image "$IMAGE" \
  --service-account "$SA_EMAIL" \
  --no-allow-unauthenticated \
  --ingress all \
  --cpu 1 \
  --memory 512Mi \
  --concurrency 20 \
  --min-instances 0 \
  --max-instances 5 \
  --timeout 60 \
  --execution-environment gen2 \
  --set-env-vars "MCPFS_BUCKET=$BUCKET,MCPFS_MAX_OBJECT_BYTES=$MAX_OBJECT_BYTES,MCPFS_LOG_LEVEL=INFO" \
  --quiet

step "Granting run.invoker to configured principals"
for principal in "${INVOKERS[@]}"; do
  trace "$principal"
  gcloud run services add-iam-policy-binding "$SERVICE" \
    --project "$PROJECT" \
    --region "$REGION" \
    --member="$principal" \
    --role="roles/run.invoker" >/dev/null
done

URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)')"

printf '\n\033[1;32mDeployed.\033[0m\n\n'
cat <<EOF
  Service URL : $URL
  MCP endpoint: $URL/mcp
  Health      : $URL/healthz   (unauthenticated)
  Bucket      : gs://$BUCKET
  Runtime SA  : $SA_EMAIL

Mint a token (valid 1h):

  TOKEN=\$(gcloud auth print-identity-token --audiences "$URL")
  curl -H "Authorization: Bearer \$TOKEN" "$URL/healthz"

Configure your MCP client to use:

  URL    : $URL/mcp
  Header : Authorization: Bearer <token from above>

EOF
