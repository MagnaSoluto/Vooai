#!/usr/bin/env bash
# Deploy VooAI → https://vooai.magnasoluto.com.br
# Isolado: só projeto vooai-box. NÃO sobrescreve /opt/sdr/Caddyfile nem compose do SDR.
#
# Modos (padrão Leads — build no GitHub Actions, não no Docker do Mac):
#   VOOAI_BUILD_ONLY=1  → só bundle + build/push ECR; sai
#   VOOAI_SKIP_BUILD=1  → só SSM pull/up na box (imagens já no ECR)
#   (sem flags)         → build + deploy (só use em CI / máquina com Docker ok)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SDR="${SDR_ROOT:-$(cd "$ROOT/../SDR" 2>/dev/null && pwd || true)}"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
HOST="vooai.magnasoluto.com.br"
API_PUBLIC="https://${HOST}/api"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
ECR_API="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/vooai/api"
ECR_WEB="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/vooai/web"
TAG="${VOOAI_IMAGE_TAG:-$(date +%Y%m%d%H%M%S)}"
INSTANCE_ID="${INSTANCE_ID:-i-0ce27df52519a2881}"
BUILD_ONLY="${VOOAI_BUILD_ONLY:-0}"
SKIP_BUILD="${VOOAI_SKIP_BUILD:-0}"

cd "$ROOT"

if [[ -z "${SERPAPI_API_KEY:-}" && -f "$ROOT/apps/api/.env" ]]; then
  set -a && source "$ROOT/apps/api/.env" && set +a
fi
if [[ -z "${SERPAPI_API_KEY:-}" ]]; then
  echo "✗ SERPAPI_API_KEY ausente"
  exit 1
fi

# Prefer explicit INSTANCE_ID; terraform só se disponível
if [[ -n "${SDR:-}" && -d "$SDR/infra/terraform/envs/prod-usest1" ]]; then
  TF_ID="$(cd "$SDR/infra/terraform/envs/prod-usest1" && terraform output -raw postgres_instance_id 2>/dev/null || true)"
  [[ -n "$TF_ID" ]] && INSTANCE_ID="$TF_ID"
fi

aws sts get-caller-identity --region "$REGION" >/dev/null
echo "→ instance=$INSTANCE_ID tag=$TAG build_only=$BUILD_ONLY skip_build=$SKIP_BUILD (alvo: só vooai-box)"

if [[ "$SKIP_BUILD" != "1" ]]; then
  echo "→ Bundle de dados runtime"
  rm -rf deploy/box/data-bundle
  mkdir -p deploy/box/data-bundle/SoT/SoT_aeroportos deploy/box/data-bundle/Spec
  rsync -a "$ROOT/data/SoT/SoT_aeroportos/" deploy/box/data-bundle/SoT/SoT_aeroportos/
  rsync -a --exclude='spec_resultados' "$ROOT/data/Spec/" deploy/box/data-bundle/Spec/
  test -n "$(find deploy/box/data-bundle/Spec/spec_modelos_risco -name '*.parquet' | head -1)"

  echo "→ ECR repos"
  for repo in vooai/api vooai/web; do
    aws ecr describe-repositories --repository-names "$repo" --region "$REGION" >/dev/null 2>&1 \
      || aws ecr create-repository --repository-name "$repo" --region "$REGION" \
           --image-tag-mutability MUTABLE --image-scanning-configuration scanOnPush=false >/dev/null
  done

  echo "→ Login ECR + build/push linux/amd64 (runner CI — não use Docker Desktop local)"
  aws ecr get-login-password --region "$REGION" \
    | docker login --username AWS --password-stdin "${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"

  # Prefer docker build (GHA) ; buildx se disponível
  if docker buildx version >/dev/null 2>&1; then
    docker buildx build --platform linux/amd64 --no-cache \
      -f deploy/box/Dockerfile.api \
      -t "${ECR_API}:${TAG}" -t "${ECR_API}:box" \
      --push .
    docker buildx build --platform linux/amd64 \
      -f deploy/box/Dockerfile.web \
      --build-arg "VITE_API_URL=${API_PUBLIC}" \
      -t "${ECR_WEB}:${TAG}" -t "${ECR_WEB}:box" \
      --push .
  else
    docker build --platform linux/amd64 --no-cache \
      -f deploy/box/Dockerfile.api \
      -t "${ECR_API}:${TAG}" -t "${ECR_API}:box" .
    docker build --platform linux/amd64 \
      -f deploy/box/Dockerfile.web \
      --build-arg "VITE_API_URL=${API_PUBLIC}" \
      -t "${ECR_WEB}:${TAG}" -t "${ECR_WEB}:box" .
    docker push "${ECR_API}:${TAG}"
    docker push "${ECR_API}:box"
    docker push "${ECR_WEB}:${TAG}"
    docker push "${ECR_WEB}:box"
  fi
fi

if [[ "$BUILD_ONLY" == "1" ]]; then
  echo "→ BUILD_ONLY: imagens ${TAG} no ECR — deploy fica no job seguinte"
  exit 0
fi

SNIPPET_B64=$(base64 < "$ROOT/deploy/box/caddy-vooai.caddy" | tr -d '\n')
COMPOSE_B64=$(base64 < "$ROOT/deploy/box/docker-compose.yml" | tr -d '\n')
SCHEMA_B64=$(base64 < "$ROOT/pipelines/sql/02_schema.sql" | tr -d '\n')

ADMIN_TOKEN="${VOOAI_ADMIN_TOKEN:-NEEDS_PRESERVE_OR_GENERATE}"
AUTH_SECRET="${VOOAI_AUTH_SECRET:-NEEDS_PRESERVE_OR_GENERATE}"

# Titan (MagnaSoluto / DataDriks): smtp.titan.email:465 SSL
SMTP_BLOCK=""
if [[ -n "${VOOAI_SMTP_HOST:-}" ]]; then
  SMTP_BLOCK=$(cat <<EOF
VOOAI_SMTP_HOST=${VOOAI_SMTP_HOST}
VOOAI_SMTP_PORT=${VOOAI_SMTP_PORT:-465}
VOOAI_SMTP_SSL=${VOOAI_SMTP_SSL:-1}
VOOAI_SMTP_USER=${VOOAI_SMTP_USER:-}
VOOAI_SMTP_PASSWORD=${VOOAI_SMTP_PASSWORD:-}
VOOAI_SMTP_FROM=${VOOAI_SMTP_FROM:-${VOOAI_SMTP_USER}}
VOOAI_SMTP_FROM_NAME=${VOOAI_SMTP_FROM_NAME:-VooAI}
EOF
)
fi

ENV_CONTENT=$(cat <<EOF
SERPAPI_API_KEY=${SERPAPI_API_KEY}
APP_ENV=prod
# Cobrança ligada em prod (preservado da box se já existir).
VOOAI_BILLING_ENABLED=${VOOAI_BILLING_ENABLED:-1}
VOOAI_SEARCH_REQUIRE_AUTH=1
VOOAI_ALLOW_TOPUP_STUB=0
VOOAI_QUOTE_CACHE_TTL_SEC=1200
VOOAI_SERPAPI_COST_BRL=0.08
VOOAI_ADMIN_TOKEN=${ADMIN_TOKEN}
VOOAI_AUTH_SECRET=${AUTH_SECRET}
VOOAI_CORS_ORIGINS=https://vooai.magnasoluto.com.br
VOOAI_COOKIE_PATH=/api
VOOAI_COOKIE_SECURE=1
VOOAI_RATE_LIMIT_PER_MIN=30
VOOAI_ACCESS_TTL_SEC=900
VOOAI_REFRESH_TTL_SEC=604800
${SMTP_BLOCK}
EOF
)
ENV_B64=$(printf '%s\n' "$ENV_CONTENT" | base64 | tr -d '\n')

TMP="$(mktemp)"
python3 - "$TMP" "$SNIPPET_B64" "$COMPOSE_B64" "$ENV_B64" "$SCHEMA_B64" "$ECR_API" "$ECR_WEB" "$TAG" "$REGION" <<'PY'
import json, sys
out, snippet_b64, compose, env_b64, schema_b64, ecr_api, ecr_web, tag, region = sys.argv[1:10]
registry = ecr_api.split("/")[0]
script = f"""set -euo pipefail
mkdir -p /var/lock /opt/vooai /opt/sdr/caddy-snippets
exec 9>/var/lock/fourdev-box-deploy.lock
flock -w 900 9
echo "→ lock fourdev-box-deploy acquired (vooai)"

# Apenas compose do projeto vooai-box — nunca /opt/sdr/compose.yml
echo '{compose}' | base64 -d > /opt/vooai/docker-compose.yml
echo '{env_b64}' | base64 -d > /opt/vooai/api.env.new
echo '{schema_b64}' | base64 -d > /opt/vooai/02_schema.sql
echo '{snippet_b64}' | base64 -d > /opt/sdr/caddy-snippets/vooai.caddy
chmod 600 /opt/vooai/api.env.new

# Preserva AUTH/ADMIN/billing já em uso na box
if [[ -f /opt/vooai/api.env ]]; then
  for key in VOOAI_AUTH_SECRET VOOAI_ADMIN_TOKEN VOOAI_BILLING_ENABLED \
             VOOAI_SMTP_HOST VOOAI_SMTP_PORT VOOAI_SMTP_SSL VOOAI_SMTP_USER \
             VOOAI_SMTP_PASSWORD VOOAI_SMTP_FROM VOOAI_SMTP_FROM_NAME; do
    old=$(grep "^${{key}}=" /opt/vooai/api.env | head -1 | cut -d= -f2- || true)
    cur=$(grep "^${{key}}=" /opt/vooai/api.env.new | head -1 | cut -d= -f2- || true)
    # Preserva se novo veio vazio / placeholder; billing sempre herda o da box.
    if [[ -n "$old" && ( -z "$cur" || "$cur" == "NEEDS_PRESERVE_OR_GENERATE" || "$key" == "VOOAI_BILLING_ENABLED" ) ]]; then
      if grep -q "^${{key}}=" /opt/vooai/api.env.new; then
        sed -i "s|^${{key}}=.*|${{key}}=${{old}}|" /opt/vooai/api.env.new
      else
        echo "${{key}}=${{old}}" >> /opt/vooai/api.env.new
      fi
    fi
  done
fi
for key in VOOAI_AUTH_SECRET VOOAI_ADMIN_TOKEN; do
  cur=$(grep "^${{key}}=" /opt/vooai/api.env.new | head -1 | cut -d= -f2- || true)
  if [[ "$cur" == "NEEDS_PRESERVE_OR_GENERATE" || -z "$cur" ]]; then
    sed -i "s|^${{key}}=.*|${{key}}=$(openssl rand -hex 32)|" /opt/vooai/api.env.new
  fi
done

if [[ -f /opt/sdr/postgres.env ]]; then
  DBPASS=$(grep '^POSTGRES_PASSWORD=' /opt/sdr/postgres.env | cut -d= -f2-)
  if [[ -n "$DBPASS" ]]; then
    docker run --rm --network sdr-box_default -e PGPASSWORD="$DBPASS" postgres:16-alpine \\
      psql -h postgres16 -U sdr -d postgres -v ON_ERROR_STOP=0 \\
      -c "CREATE DATABASE vooai OWNER sdr;" || true
    docker run --rm --network sdr-box_default -e PGPASSWORD="$DBPASS" \\
      -v /opt/vooai/02_schema.sql:/schema.sql:ro postgres:16-alpine \\
      psql -h postgres16 -U sdr -d vooai -v ON_ERROR_STOP=1 -f /schema.sql
    grep -v '^VOOAI_DATABASE_URL=' /opt/vooai/api.env.new > /opt/vooai/api.env.tmp || true
    mv /opt/vooai/api.env.tmp /opt/vooai/api.env.new
    echo "VOOAI_DATABASE_URL=postgresql://sdr:${{DBPASS}}@postgres16:5432/vooai" >> /opt/vooai/api.env.new
    echo "→ Postgres vooai OK"
  fi
fi

grep -vE '^(BILLING_API_URL|BILLING_API_TOKEN|VOOAI_WEBHOOK_TOKEN)=' /opt/vooai/api.env.new > /opt/vooai/api.env.tmp || true
mv /opt/vooai/api.env.tmp /opt/vooai/api.env.new
echo "BILLING_API_URL=http://billing-api:8080" >> /opt/vooai/api.env.new
BILLING_TOKEN=""
if [[ -f /opt/billing/app.env ]]; then
  BILLING_TOKEN=$(grep '^BILLING_API_TOKEN=' /opt/billing/app.env | head -1 | cut -d= -f2- || true)
  WH=$(grep '^VOOAI_WEBHOOK_TOKEN=' /opt/billing/app.env | head -1 | cut -d= -f2- || true)
  if [[ -n "$WH" ]]; then
    echo "VOOAI_WEBHOOK_TOKEN=${{WH}}" >> /opt/vooai/api.env.new
  fi
fi
if [[ -z "$BILLING_TOKEN" && -f /opt/vooai/api.env ]]; then
  BILLING_TOKEN=$(grep '^BILLING_API_TOKEN=' /opt/vooai/api.env | head -1 | cut -d= -f2- || true)
fi
if [[ -n "$BILLING_TOKEN" ]]; then
  echo "BILLING_API_TOKEN=${{BILLING_TOKEN}}" >> /opt/vooai/api.env.new
  echo "→ Billing API token OK"
else
  echo "⚠ BILLING_API_TOKEN ausente — topup PIX ficará 503 até configurar"
fi

mv /opt/vooai/api.env.new /opt/vooai/api.env
chmod 600 /opt/vooai/api.env

# Caddy: grava snippet + append idempotente do site se faltar. NUNCA overwrite do Caddyfile.
# (import /etc/caddy/snippets/*.caddy só após volume montado no compose do SDR)
CADDY=/opt/sdr/Caddyfile
NEED_RELOAD=0
if [[ -f "$CADDY" ]] && ! grep -q 'vooai.magnasoluto.com.br' "$CADDY"; then
  printf '\\n' >> "$CADDY"
  cat /opt/sdr/caddy-snippets/vooai.caddy >> "$CADDY"
  NEED_RELOAD=1
  echo "→ Caddy: site vooai anexado (idempotente)"
fi

cat > /opt/vooai/.env <<EOF
VOOAI_API_IMAGE={ecr_api}:{tag}
VOOAI_WEB_IMAGE={ecr_web}:{tag}
EOF
aws ecr get-login-password --region {region} | docker login --username AWS --password-stdin {registry}
cd /opt/vooai
docker compose --env-file .env pull vooai-redis vooai-api vooai-web
# Isolamento: redis sem recreate forçado; API/WEB com --no-deps (não toca irmãos)
docker compose --env-file .env up -d --no-recreate vooai-redis
docker compose --env-file .env up -d --no-deps --force-recreate vooai-api vooai-web

if [[ "$NEED_RELOAD" == "1" ]]; then
  caddy=$(docker ps --format '{{{{.Names}}}}' | awk '/caddy/ {{print; exit}}')
  if [[ -n "$caddy" ]]; then
    docker exec "$caddy" caddy reload --config /etc/caddy/Caddyfile \\
      || echo "⚠ caddy reload falhou — site novo pode precisar de reload manual"
    echo "→ caddy reloaded ($caddy; sem restart)"
  fi
fi

sleep 8
docker ps --format 'table {{{{.Names}}}}\\t{{{{.Status}}}}' | grep -E 'vooai|caddy' || true
docker ps --format '{{{{.Names}}}} {{{{.Status}}}}' | grep -E 'platform-api|billing-api|leads-api' || true
docker exec vooai-api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health').read().decode())"
docker exec vooai-api python -c "from app.db import db_label; print('db=', db_label())"
docker exec vooai-api python -c "from app.billing_client import billing_configured; print('billing_configured=', billing_configured())"
echo DONE_DEPLOY_VOOAI
"""
json.dump({"commands": [script]}, open(out, "w"))
print("ok", len(script))
PY

echo "→ SSM deploy (alvo vooai only)"
CMD_ID=$(aws ssm send-command \
  --region "$REGION" \
  --instance-ids "$INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --comment "Deploy VooAI ${TAG} (isolated)" \
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
