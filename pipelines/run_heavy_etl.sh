#!/usr/bin/env bash
# Rematerialização pesada SoR ANAC → SoT → Spec (notebooks 08/09).
# Só rode na box quando houver mês VRA novo e RAM ≥ 4–8 GB.
# NÃO é o caminho diário — o diário é collect_quotes + etl_quotes.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv-pipeline ]]; then
  python3 -m venv .venv-pipeline
  .venv-pipeline/bin/pip install -q -r pipelines/requirements.txt
  .venv-pipeline/bin/pip install -q jupyter nbconvert ipykernel
fi
# shellcheck disable=SC1091
source .venv-pipeline/bin/activate

export VOOAI_DATA_DIR="${VOOAI_DATA_DIR:-$ROOT/data}"
export VOOAI_SPEC_DIR="${VOOAI_SPEC_DIR:-$ROOT/data/Spec}"

echo "[heavy] notebook 08 ETL..."
jupyter nbconvert --to notebook --execute --ExecutePreprocessor.timeout=7200 \
  notebooks/08_etl_tabelas_sor_sot_spec.ipynb --output /tmp/08_executed.ipynb

echo "[heavy] notebook 09 modelagem..."
jupyter nbconvert --to notebook --execute --ExecutePreprocessor.timeout=14400 \
  notebooks/09_modelagem_risco.ipynb --output /tmp/09_executed.ipynb

echo "[heavy] publish + reload"
python -m pipelines.publish_spec
echo "[heavy] OK"
