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

if [ "$REQS_HASH" != "$INSTALLED_HASH" ]; then
    echo "[startup] Dependencies changed or first run — installing..."
    echo "[startup] Requirements hash: $REQS_HASH (cached: $INSTALLED_HASH)"

    # Create fresh venv
    rm -rf "$VENV"
    python -m venv "$VENV"
    source "$VENV/bin/activate"

    # Install CPU-only PyTorch first (saves ~1.5 GB vs CUDA)
    echo "[startup] Installing CPU-only PyTorch..."
    pip install torch --index-url https://download.pytorch.org/whl/cpu --quiet --no-cache-dir

    # Install remaining production deps
    echo "[startup] Installing production dependencies..."
    pip install -r "$REQS" --quiet --no-cache-dir

    # Save hash so next restart skips install
    echo "$REQS_HASH" > "$HASH_FILE"
    echo "[startup] Dependencies installed successfully."
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
    --workers 2 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
