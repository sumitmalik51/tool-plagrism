#!/bin/bash
# ---------------------------------------------------------------------------
# PlagiarismGuard — Azure App Service startup script
# Runs uvicorn with the correct settings for production on Azure
# ---------------------------------------------------------------------------

# Install dependencies (Azure Oryx build should handle this, but just in case)
pip install -r requirements.txt --quiet

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
