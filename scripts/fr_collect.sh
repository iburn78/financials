#!/usr/bin/env bash
set -euo pipefail

financials="${HOME}/projects/financials"
tnp="${HOME}/projects/tnp"
data="${HOME}/projects/data"
mode="${1:-all}" # market | financial | all

mkdir -p "${financials}/collect/log"
exec >> "${financials}/collect/log/autorun.log" 2>&1
echo "[$(date '+%F %T %Z')] fr_collect mode=${mode} started"

source "${financials}/venv/bin/activate"
cd "${financials}/collect"

case "${mode}" in
  market)
    /usr/bin/flock -n /tmp/gen_market_dbs.lock python -m gen_market_dbs
    ;;
  financial)
    /usr/bin/flock -n /tmp/gen_financial_records.lock python -m gen_financial_records
    ;;
  all)
    /usr/bin/flock -n /tmp/gen_market_dbs.lock python -m gen_market_dbs
    /usr/bin/flock -n /tmp/gen_financial_records.lock python -m gen_financial_records
    ;;
  *)
    echo "Usage: $0 [market|financial|all]" >&2
    exit 2
    ;;
esac

# Synchronize generated artifacts only after successful collection.
if [[ "${mode}" != "financial" ]]; then
  rsync -ru "${financials}/collect/plots/" "${tnp}/public/data/"
fi
mkdir -p "${data}/market"
rsync -ru "${financials}/collect/data/" "${data}/market/"
echo "[$(date '+%F %T %Z')] fr_collect mode=${mode} finished"
