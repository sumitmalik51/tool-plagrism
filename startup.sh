#!/bin/bash
# ---------------------------------------------------------------------------
# PlagiarismGuard — Azure App Service startup script
# Installs deps into a persistent venv at /home/site/venv/ (survives restarts).
# On first boot: creates venv + pip install (~5-8 min).
# On subsequent boots: reuses cached venv (instant).
# ---------------------------------------------------------------------------

set -e

VENV="/home/site/venv"
REQS="/home/site/wwwroot/requirements-prod.txt"
HASH_FILE="$VENV/.reqs_hash"

echo "[startup] =================================================="
echo "[startup] PlagiarismGuard starting at $(date -u +%H:%M:%S) UTC"
echo "[startup] =================================================="

# ---- Persistent venv with smart caching --------------------------------
REQS_HASH=$(md5sum "$REQS" 2>/dev/null | cut -d' ' -f1 || echo "none")
INSTALLED_HASH=$(cat "$HASH_FILE" 2>/dev/null || echo "")

if [ ! -d "$VENV/bin" ]; then
    echo "[startup] First run — creating venv and installing all deps..."
    python -m venv "$VENV"
    source "$VENV/bin/activate"

    echo "[startup] Installing CPU-only PyTorch..."
    pip install torch --index-url https://download.pytorch.org/whl/cpu --quiet --no-cache-dir

    echo "[startup] Installing production dependencies..."
    pip install -r "$REQS" --quiet --no-cache-dir

    echo "$REQS_HASH" > "$HASH_FILE"
    echo "[startup] Full install complete."

elif [ "$REQS_HASH" != "$INSTALLED_HASH" ]; then
    echo "[startup] Dependencies changed — incremental update..."
    echo "[startup] Requirements hash: $REQS_HASH (cached: $INSTALLED_HASH)"
    source "$VENV/bin/activate"

    # Incremental: pip installs only new/changed packages, skips existing
    pip install -r "$REQS" --quiet --no-cache-dir

    echo "$REQS_HASH" > "$HASH_FILE"
    echo "[startup] Incremental update complete."
else
    echo "[startup] Dependencies cached — skipping install."
    source "$VENV/bin/activate"
fi

# ---- Verify critical packages -------------------------------------------
echo "[startup] Python: $(python --version)"
python -c "import uvicorn; print('[startup] uvicorn OK:', uvicorn.__version__)" 2>&1 || { echo "[startup] FATAL: uvicorn not found!"; exit 1; }
python -c "import gunicorn; print('[startup] gunicorn OK:', gunicorn.__version__)" 2>&1 || { echo "[startup] FATAL: gunicorn not found!"; exit 1; }
python -c "import torch; print('[startup] torch OK:', torch.__version__)" 2>&1 || echo "[startup] WARN: torch not available"

# ---- Create uploads dir (outside wwwroot for write access) ---------------
mkdir -p /home/uploads

# ---- Start gunicorn with uvicorn workers --------------------------------
cd /home/site/wwwroot
echo "[startup] Starting gunicorn on port ${PORT:-8000}..."
exec gunicorn app.main:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:${PORT:-8000} \
    --workers 1 \
    --timeout 300 \
    --access-logfile - \
    --error-logfile -
