#!/bin/bash
# ---------------------------------------------------------------------------
# PlagiarismGuard — Azure App Service startup script
# Dependencies are pre-built and shipped in .python_packages/
# ---------------------------------------------------------------------------

set -e

# Add pre-built packages to Python path
export PYTHONPATH="/home/site/wwwroot/.python_packages/lib/site-packages:$PYTHONPATH"

# Create uploads directory outside wwwroot
mkdir -p /home/uploads

# Debug — verify packages are present (visible in Docker logs)
echo "[startup] pwd: $(pwd)"
echo "[startup] PYTHONPATH=$PYTHONPATH"
echo "[startup] Checking .python_packages..."
ls /home/site/wwwroot/.python_packages/lib/site-packages/ 2>&1 | head -20 || echo "[startup] WARNING: .python_packages not found!"
python -c "import uvicorn; print('[startup] uvicorn OK:', uvicorn.__file__)" 2>&1 || echo "[startup] WARNING: cannot import uvicorn"
python -c "import gunicorn; print('[startup] gunicorn OK:', gunicorn.__file__)" 2>&1 || echo "[startup] WARNING: cannot import gunicorn"

# Start the FastAPI app using python -m to respect PYTHONPATH
cd /home/site/wwwroot
exec python -m gunicorn app.main:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:${PORT:-8000} \
    --workers 2 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
