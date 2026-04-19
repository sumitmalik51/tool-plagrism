"""Background-job wrappers around the analysis endpoints.

Lets the frontend submit a scan and immediately receive a ``job_id`` so
the user can navigate away and come back. Progress streams over the
existing SSE channel at ``/api/v1/scan-progress/{document_id}``.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field

from app.dependencies.rate_limit import enforce_scan_limit, record_scan
from app.routes.analyze import AnalyzeTextRequest, _persist_scan
from app.services import progress as scan_progress
from app.services.ingestion import ingest_file
from app.services.job_manager import Job, get_manager
from app.services.orchestrator import run_pipeline
from app.services.persistence import save_document
from app.services.rate_limiter import PLAN_TO_TIER, UserTier, limiter
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_plan(user_id: int | None) -> str:
    if not user_id:
        return "free"
    from app.services.auth_service import get_user_by_id
    user = get_user_by_id(user_id)
    return (user or {}).get("plan_type", "free") if user else "free"


def _check_word_quota(user_id: int | None, plan_type: str, word_count: int, what: str) -> None:
    if not user_id:
        return
    tier = PLAN_TO_TIER.get(plan_type, UserTier.FREE)
    wq = limiter.check_word_quota(user_id, tier, word_count=word_count)
    if not wq["allowed"]:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "word_quota_exceeded",
                "message": (
                    f"Monthly word limit reached ({wq['limit']:,} words). "
                    f"Used {wq['used']:,}, this {what} has {word_count:,} words."
                ),
                "used": wq["used"],
                "limit": wq["limit"],
                "remaining": wq["remaining"],
                "upgrade_url": "/pricing",
            },
        )


def _serialize_job(job: Job, *, include_result: bool = True) -> dict[str, Any]:
    tracker = scan_progress.get(job.document_id)
    latest = tracker.events[-1] if tracker and tracker.events else None
    payload: dict[str, Any] = {
        "job_id": job.job_id,
        "document_id": job.document_id,
        "kind": job.kind,
        "label": job.label,
        "status": job.status,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "error": job.error,
        "progress": (
            {"stage": latest.stage, "message": latest.message, "percent": latest.percent}
            if latest
            else None
        ),
    }
    if include_result and job.status == "completed" and job.result is not None:
        payload["result"] = job.result
    return payload


# ---------------------------------------------------------------------------
# Submit: text
# ---------------------------------------------------------------------------

@router.post(
    "/analyze-text",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue a text-based plagiarism scan",
    dependencies=[Depends(enforce_scan_limit)],
)
async def submit_text_job(body: AnalyzeTextRequest, request: Request) -> dict[str, Any]:
    document_id = body.document_id or uuid.uuid4().hex
    user_id = getattr(request.state, "user_id", None)
    plan_type = _resolve_plan(user_id)

    word_count = len(body.text.split())
    request.state.scan_word_count = word_count
    _check_word_quota(user_id, plan_type, word_count, "text")

    # Prime the progress tracker so the SSE endpoint has something immediately.
    tracker = scan_progress.get_or_create(document_id)
    tracker.emit("queued", "Queued for analysis...", 1)

    try:
        save_document(
            document_id,
            user_id=user_id,
            filename=None,
            file_type="text",
            char_count=len(body.text),
            text_content=body.text[:50000],
        )
    except Exception as exc:
        logger.warning("document_save_failed", error=str(exc))

    record_scan(request)

    label = (body.text.strip().split("\n", 1)[0] or "Text scan")[:80]
    text_for_run = body.text
    excluded = body.excluded_domains or None
    use_gpt = body.use_gpt_ai_detection
    lang = body.language

    async def _run() -> dict[str, Any]:
        report = await run_pipeline(
            document_id=document_id,
            text=text_for_run,
            excluded_domains=excluded,
            use_gpt_ai_detection=use_gpt,
            language_override=lang,
            plan_type=plan_type,
        )
        _persist_scan(report, user_id)
        return report.model_dump(mode="json")

    job = get_manager().submit(
        user_id=user_id,
        document_id=document_id,
        kind="text",
        label=label,
        coro_factory=_run,
    )

    logger.info("text_job_submitted", job_id=job.job_id, document_id=document_id)
    return _serialize_job(job, include_result=False)


# ---------------------------------------------------------------------------
# Submit: file
# ---------------------------------------------------------------------------

@router.post(
    "/analyze-file",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue a file-based plagiarism scan",
    dependencies=[Depends(enforce_scan_limit)],
)
async def submit_file_job(
    file: UploadFile,
    request: Request,
    document_id: str | None = Form(None),
) -> dict[str, Any]:
    if file.filename is None:
        raise HTTPException(status_code=400, detail="Filename is required.")

    file_bytes = await file.read()
    user_id = getattr(request.state, "user_id", None)
    plan_type = _resolve_plan(user_id)

    effective_doc_id = document_id or uuid.uuid4().hex
    tracker = scan_progress.get_or_create(effective_doc_id)
    tracker.emit("upload", "Processing uploaded file...", 2)

    try:
        ingestion_result = await ingest_file(
            file.filename, file_bytes, plan_type=plan_type, document_id=effective_doc_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    word_count = len(ingestion_result["text"].split())
    request.state.scan_word_count = word_count
    _check_word_quota(user_id, plan_type, word_count, "document")

    try:
        save_document(
            ingestion_result["document_id"],
            user_id=user_id,
            filename=ingestion_result["filename"],
            file_type=ingestion_result["file_type"],
            char_count=ingestion_result["char_count"],
            text_content=ingestion_result["text"][:50000],
        )
    except Exception as exc:
        logger.warning("document_save_failed", error=str(exc))

    record_scan(request)

    doc_id = ingestion_result["document_id"]
    text_for_run = ingestion_result["text"]
    label = (ingestion_result.get("filename") or "File scan")[:80]

    async def _run() -> dict[str, Any]:
        report = await run_pipeline(
            document_id=doc_id,
            text=text_for_run,
            plan_type=plan_type,
        )
        _persist_scan(report, user_id)
        return report.model_dump(mode="json")

    job = get_manager().submit(
        user_id=user_id,
        document_id=doc_id,
        kind="file",
        label=label,
        coro_factory=_run,
    )

    logger.info("file_job_submitted", job_id=job.job_id, document_id=doc_id)
    return _serialize_job(job, include_result=False)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

@router.get("/{job_id}", summary="Get the status (and result, if complete) of a job")
async def get_job(job_id: str, request: Request) -> dict[str, Any]:
    job = get_manager().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    user_id = getattr(request.state, "user_id", None)
    # If the job has an owner, require a matching user.
    if job.user_id is not None and job.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not your job")
    return _serialize_job(job, include_result=True)


@router.get("", summary="List the current user's recent scan jobs")
async def list_jobs(request: Request, limit: int = 20) -> dict[str, Any]:
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        return {"jobs": []}
    jobs = get_manager().list_for_user(user_id, limit=limit)
    return {"jobs": [_serialize_job(j, include_result=False) for j in jobs]}
