#!/usr/bin/env bash
# Deploy (or update) the API on Google Cloud Run from the image GitHub Actions published to ghcr.io.
#
#   ./deploy/cloudrun.sh            # deploys :latest
#   ./deploy/cloudrun.sh <git-sha>  # deploys that exact build
#
# Reads READER_DATABASE_URL and GROQ_API_KEY from .env. Needs gcloud logged in with a project selected.
set -euo pipefail

cd "$(dirname "$0")/.."
TAG="${1:-latest}"
SERVICE="${SERVICE:-coffee-explainer-api}"
REGION="${REGION:-europe-west1}"           # Belgium: close to Neon (Frankfurt)
IMAGE="ghcr.io/thecodix/coffee-explainer-api:${TAG}"

set -a; source .env; set +a
: "${READER_DATABASE_URL:?missing in .env}"
: "${GROQ_API_KEY:?missing in .env}"

# Env vars go through a temporary YAML file so the secrets never appear in the shell history or `ps`.
ENV_FILE="$(mktemp)"
trap 'rm -f "$ENV_FILE"' EXIT
cat > "$ENV_FILE" <<EOF
READER_DATABASE_URL: "${READER_DATABASE_URL}"
GROQ_API_KEY: "${GROQ_API_KEY}"
QA_ENABLED: "${QA_ENABLED:-true}"
PER_IP_PER_MINUTE: "5"
PER_IP_PER_DAY: "30"
DAILY_QUOTA: "300"
CORS_ORIGINS: "${CORS_ORIGINS:-http://localhost:5173}"
EOF

# max-instances=1: the rate-limit counters live in memory, and it caps the bill.
# min-instances=0: scale to zero when idle. CPU is only billed while a request runs (default).
gcloud run deploy "$SERVICE" \
  --image "$IMAGE" \
  --region "$REGION" \
  --allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 1 \
  --concurrency 20 \
  --timeout 60 \
  --cpu-boost \
  --env-vars-file "$ENV_FILE"

URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format 'value(status.url)')"
echo
echo "Deployed: $URL"
echo "Health:   $(curl -s "$URL/health")"
