#!/usr/bin/env bash
set -euo pipefail

# ── All County Lead Gen — GCP VM Deploy Script ───────────────────────────────
#
# Run this on your GCP VM after cloning the repo:
#   chmod +x deploy.sh && ./deploy.sh
#
# Prerequisites:
#   - Docker + Docker Compose installed on the VM
#   - server/.env file configured (copy from .env.example)
#
# What this does:
#   1. Builds the Docker image (frontend + API)
#   2. Starts Postgres + API server via docker-compose
#   3. Runs the initial pipeline (downloads data + scores leads)
#   4. Sets up a daily cron job (5 AM MT)

echo "═══════════════════════════════════════════════════════════════"
echo "  All County Lead Gen — Deploying"
echo "═══════════════════════════════════════════════════════════════"

# ── Check prerequisites ──────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    echo "[ERROR] Docker not found. Install it:"
    echo "  sudo apt-get update && sudo apt-get install -y docker.io docker-compose-plugin"
    exit 1
fi

if [ ! -f server/.env ]; then
    echo "[WARN] server/.env not found — copying from .env.example"
    cp server/.env.example server/.env
    echo "  → Edit server/.env with your API keys before running pipeline"
fi

# ── Set Postgres password ────────────────────────────────────────────────────
if ! grep -q "POSTGRES_PASSWORD" server/.env 2>/dev/null; then
    PG_PASS=$(openssl rand -base64 24 | tr -d '/+=' | head -c 20)
    echo "" >> server/.env
    echo "POSTGRES_PASSWORD=${PG_PASS}" >> server/.env
    echo "[OK] Generated Postgres password"
fi

# Export for docker-compose
export POSTGRES_PASSWORD=$(grep POSTGRES_PASSWORD server/.env | cut -d= -f2)

# ── Build and start ──────────────────────────────────────────────────────────
echo ""
echo "[1/4] Building Docker image (frontend + API)..."
docker compose build

echo ""
echo "[2/4] Starting services..."
docker compose up -d

echo ""
echo "[3/4] Waiting for Postgres to be ready..."
sleep 5

echo ""
echo "[4/4] Running initial pipeline (Boulder County)..."
docker compose exec app python -c "
import sys; sys.path.insert(0, '.')
from server.scraper import download_csv
from server.pipeline_db import run_pipeline

print('Downloading Boulder County records...')
dl = download_csv('boulder')
if dl['ok']:
    print(f'  Downloaded {dl[\"rows\"]:,} rows')
    print('Running pipeline...')
    result = run_pipeline('boulder')
    print(f'  Scored {result[\"leads_scored\"]} leads, {result[\"new_owners_found\"]} new owners')
else:
    print(f'  Download failed: {dl.get(\"error\")}')
"

# ── Set up daily cron ────────────────────────────────────────────────────────
CRON_CMD="0 12 * * * cd $(pwd) && docker compose exec -T app python -c \"import sys; sys.path.insert(0,'.'); from server.scraper import download_csv; from server.pipeline_db import run_pipeline; [run_pipeline(r['county']) for r in [download_csv('boulder')] if r.get('changed')]\" >> /var/log/allcounty-pipeline.log 2>&1"

# Check if cron already exists
if ! crontab -l 2>/dev/null | grep -q "allcounty-pipeline"; then
    (crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -
    echo ""
    echo "[OK] Daily cron installed (12:00 UTC / 5:00 AM MT)"
else
    echo ""
    echo "[OK] Daily cron already exists"
fi

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Deployment complete!"
echo ""
echo "  Dashboard:  http://$(hostname -I | awk '{print $1}'):8000"
echo "  API docs:   http://$(hostname -I | awk '{print $1}'):8000/docs"
echo ""
echo "  Useful commands:"
echo "    docker compose logs -f app     # Watch API logs"
echo "    docker compose exec app bash   # Shell into container"
echo "    docker compose down            # Stop everything"
echo "    docker compose up -d --build   # Rebuild + restart"
echo "═══════════════════════════════════════════════════════════════"
