#!/bin/bash
# ---------------------------------------------------------------------------
# PlagiarismGuard — Azure App Service startup script
# Dependencies are pre-built and shipped in .python_packages/
# ---------------------------------------------------------------------------

# Add pre-built packages to Python path
export PYTHONPATH="/home/site/wwwroot/.python_packages/lib/site-packages:$PYTHONPATH"

# Create uploads directory if it doesn't exist
mkdir -p uploads

# Start the FastAPI app — Azure injects PORT env var
exec gunicorn app.main:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:${PORT:-8000} \
    --workers 2 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
