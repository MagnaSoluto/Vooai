#!/usr/bin/env bash
# Deploy VooAI → https://vooai.magnasoluto.com.br (box EC2 + Caddy + ECR)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SDR="${SDR_ROOT:-$(cd "$ROOT/../SDR" && pwd)}"
TF="$SDR/infra/terraform/envs/prod-usest1"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
HOST="vooai.magnasoluto.com.br"
API_PUBLIC="https://${HOST}/api"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
ECR_API="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/vooai/api"
ECR_WEB="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/vooai/web"
TAG="${VOOAI_IMAGE_TAG:-$(date +%Y%m%d%H%M%S)}"

cd "$ROOT"

if [[ -z "${SERPAPI_API_KEY:-}" && -f "$ROOT/apps/api/.env" ]]; then
  set -a && source "$ROOT/apps/api/.env" && set +a
fi
if [[ -z "${SERPAPI_API_KEY:-}" ]]; then
  echo "✗ SERPAPI_API_KEY ausente"
  exit 1
fi

aws sts get-caller-identity --region "$REGION" >/dev/null
INSTANCE_ID="$(cd "$TF" && terraform output -raw postgres_instance_id)"
echo "→ instance=$INSTANCE_ID tag=$TAG"

echo "→ Bundle de dados runtime"
rm -rf deploy/box/data-bundle
mkdir -p deploy/box/data-bundle/SoT/SoT_aeroportos deploy/box/data-bundle/Spec
rsync -a "$ROOT/data/SoT/SoT_aeroportos/" deploy/box/data-bundle/SoT/SoT_aeroportos/
rsync -a --exclude='spec_resultados' "$ROOT/data/Spec/" deploy/box/data-bundle/Spec/
# garantir que COPY no Docker veja algo
test -f deploy/box/data-bundle/Spec/spec_modelos_risco/*.parquet || \
  test -n "$(find deploy/box/data-bundle/Spec/spec_modelos_risco -name '*.parquet' | head -1)"

echo "→ ECR repos"
for repo in vooai/api vooai/web; do
  aws ecr describe-repositories --repository-names "$repo" --region "$REGION" >/dev/null 2>&1 \
    || aws ecr create-repository --repository-name "$repo" --region "$REGION" \
         --image-tag-mutability MUTABLE --image-scanning-configuration scanOnPush=false >/dev/null
done

echo "→ Login ECR + build/push linux/amd64"
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"

docker buildx build --platform linux/amd64 --no-cache \
  -f deploy/box/Dockerfile.api \
  -t "${ECR_API}:${TAG}" -t "${ECR_API}:box" \
  --push .

docker buildx build --platform linux/amd64 \
  -f deploy/box/Dockerfile.web \
  --build-arg "VITE_API_URL=${API_PUBLIC}" \
  -t "${ECR_WEB}:${TAG}" -t "${ECR_WEB}:box" \
  --push .

CADDY_B64=$(base64 < "$SDR/infra/terraform/modules/ec2-box/Caddyfile.prod" | tr -d '\n')
COMPOSE_B64=$(base64 < "$ROOT/deploy/box/docker-compose.yml" | tr -d '\n')
# env file content
ENV_B64=$(printf 'SERPAPI_API_KEY=%s\n' "$SERPAPI_API_KEY" | base64 | tr -d '\n')

TMP="$(mktemp)"
python3 - "$TMP" "$CADDY_B64" "$COMPOSE_B64" "$ENV_B64" "$ECR_API" "$ECR_WEB" "$TAG" "$REGION" <<'PY'
import json, sys
out, caddy, compose, env_b64, ecr_api, ecr_web, tag, region = sys.argv[1:9]
registry = ecr_api.split("/")[0]
script = f"""set -euo pipefail
mkdir -p /opt/vooai
echo '{caddy}' | base64 -d > /opt/sdr/Caddyfile
echo '{compose}' | base64 -d > /opt/vooai/docker-compose.yml
echo '{env_b64}' | base64 -d > /opt/vooai/api.env
chmod 600 /opt/vooai/api.env
cat > /opt/vooai/.env <<EOF
VOOAI_API_IMAGE={ecr_api}:{tag}
VOOAI_WEB_IMAGE={ecr_web}:{tag}
EOF
aws ecr get-login-password --region {region} | docker login --username AWS --password-stdin {registry}
cd /opt/vooai
docker compose --env-file .env pull
docker compose --env-file .env up -d --force-recreate
cd /opt/sdr
docker compose restart caddy
sleep 8
docker ps --format 'table {{{{.Names}}}}\\t{{{{.Status}}}}' | grep -E 'vooai|caddy' || true
docker exec vooai-api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health').read().decode())"
"""
json.dump({"commands": [script]}, open(out, "w"))
print("ok", len(script))
PY

echo "→ SSM deploy"
CMD_ID=$(aws ssm send-command \
  --region "$REGION" \
  --instance-ids "$INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --comment "Deploy VooAI ${TAG}" \
  --timeout-seconds 1800 \
  --parameters "file://${TMP}" \
  --output text --query Command.CommandId)
rm -f "$TMP"
echo "   CommandId=$CMD_ID"
aws ssm wait command-executed --region "$REGION" --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" || true
aws ssm get-command-invocation --region "$REGION" --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" \
  --query '{Status:Status,Out:StandardOutputContent,Err:StandardErrorContent}' --output json

echo ""
echo "→ HTTPS"
for i in 1 2 3 4 5; do
  if curl -fsS "https://${HOST}/api/health"; then
    echo ""
    echo "OK https://${HOST}"
    exit 0
  fi
  sleep 5
done
echo "⚠ health ainda não OK — confira TLS/Caddy (DNS já aponta)"
exit 1
