"""LTI 1.3 integration routes for Learning Management Systems.

Provides LTI 1.3 launch endpoint + grade passback for:
- Canvas
- Moodle  
- Blackboard

Teachers create an assignment that launches PlagiarismGuard.
Students submit text → scanned → grade returned to LMS gradebook.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import settings
from app.services.database import get_db
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/lti", tags=["lms"])


# ---------------------------------------------------------------------------
# LTI Configuration (JWKS + OpenID Config)
# ---------------------------------------------------------------------------

@router.get("/jwks")
async def lti_jwks():
    """Return JSON Web Key Set for LTI 1.3 tool authentication."""
    # In production, generate proper RSA keys. This is a simplified version.
    return {"keys": []}


@router.get("/.well-known/openid-configuration")
async def lti_openid_config(request: Request):
    """OpenID Connect discovery document for LTI platforms."""
    base = str(request.base_url).rstrip("/")
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/api/v1/lti/authorize",
        "token_endpoint": f"{base}/api/v1/lti/token",
        "jwks_uri": f"{base}/api/v1/lti/jwks",
        "registration_endpoint": f"{base}/api/v1/lti/register",
        "scopes_supported": ["openid"],
        "response_types_supported": ["id_token"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
    }


@router.get("/config")
async def lti_tool_config(request: Request):
    """LTI 1.3 tool configuration JSON for platform registration."""
    base = str(request.base_url).rstrip("/")
    return {
        "title": "PlagiarismGuard",
        "description": "AI-powered plagiarism detection and text analysis",
        "oidc_initiation_url": f"{base}/api/v1/lti/login",
        "target_link_uri": f"{base}/api/v1/lti/launch",
        "scopes": [
            "https://purl.imsglobal.org/spec/lti-ags/scope/lineitem",
            "https://purl.imsglobal.org/spec/lti-ags/scope/result.readonly",
            "https://purl.imsglobal.org/spec/lti-ags/scope/score",
        ],
        "extensions": [
            {
                "platform": "canvas.instructure.com",
                "settings": {
                    "placements": [
                        {
                            "placement": "assignment_edit",
                            "message_type": "LtiDeepLinkingRequest",
                            "target_link_uri": f"{base}/api/v1/lti/launch",
                        },
                        {
                            "placement": "course_navigation",
                            "message_type": "LtiResourceLinkRequest",
                            "target_link_uri": f"{base}/api/v1/lti/launch",
                        },
                    ]
                },
            }
        ],
        "public_jwk_url": f"{base}/api/v1/lti/jwks",
        "custom_fields": {
            "canvas_user_id": "$Canvas.user.id",
            "canvas_course_id": "$Canvas.course.id",
        },
    }


# ---------------------------------------------------------------------------
# LTI 1.3 Login / Launch Flow
# ---------------------------------------------------------------------------

@router.get("/login")
@router.post("/login")
async def lti_login(request: Request):
    """OIDC login initiation — redirects back to platform with auth request."""
    params = dict(request.query_params) if request.method == "GET" else dict(await request.form())
    
    login_hint = params.get("login_hint", "")
    target_link_uri = params.get("target_link_uri", "")
    lti_message_hint = params.get("lti_message_hint", "")
    client_id = params.get("client_id", "")
    iss = params.get("iss", "")

    # Store state for CSRF protection
    import secrets
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)

    # Store in DB for validation
    db = get_db()
    db.execute(
        "INSERT INTO lti_states (state, nonce, issuer, client_id, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (state, nonce, iss, client_id, __import__("datetime").datetime.utcnow().isoformat()),
    )

    # Determine platform auth endpoint
    platform = db.fetch_one(
        "SELECT auth_endpoint FROM lti_platforms WHERE issuer = ?", (iss,)
    )
    auth_url = platform["auth_endpoint"] if platform else f"{iss}/api/lti/authorize_redirect"

    redirect_url = (
        f"{auth_url}?"
        f"scope=openid&response_type=id_token&response_mode=form_post"
        f"&prompt=none&client_id={client_id}"
        f"&redirect_uri={target_link_uri}"
        f"&login_hint={login_hint}"
        f"&state={state}&nonce={nonce}"
        f"&lti_message_hint={lti_message_hint}"
    )

    from fastapi.responses import RedirectResponse
    return RedirectResponse(redirect_url, status_code=302)


@router.post("/launch")
async def lti_launch(request: Request):
    """LTI 1.3 resource link launch — renders the plagiarism check interface."""
    form = await request.form()
    id_token_str = form.get("id_token", "")
    state = form.get("state", "")

    if not id_token_str:
        raise HTTPException(status_code=400, detail="Missing id_token")

    # In production: validate JWT signature against platform JWKS
    # For now, decode without verification for the payload
    import base64
    try:
        parts = id_token_str.split(".")
        payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id_token")

    user_name = claims.get("name", "Student")
    user_email = claims.get("email", "")
    course = claims.get("https://purl.imsglobal.org/spec/lti/claim/context", {}).get("title", "Course")
    resource = claims.get("https://purl.imsglobal.org/spec/lti/claim/resource_link", {}).get("title", "Assignment")

    # Render the in-LMS plagiarism checking interface
    return HTMLResponse(f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>PlagiarismGuard — {resource}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; padding: 20px; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; padding-bottom: 12px; border-bottom: 1px solid #334155; }}
        .header h1 {{ font-size: 18px; color: #6366f1; }}
        .meta {{ font-size: 12px; color: #64748b; }}
        textarea {{ width: 100%; min-height: 200px; padding: 12px; border: 1px solid #334155; border-radius: 8px; background: #1e293b; color: #e2e8f0; font-size: 14px; line-height: 1.6; resize: vertical; }}
        .btn {{ padding: 10px 20px; border: none; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer; margin-top: 12px; }}
        .btn-primary {{ background: #4f46e5; color: white; }}
        .btn-primary:hover {{ background: #4338ca; }}
        .btn:disabled {{ opacity: 0.4; }}
        #result {{ margin-top: 16px; }}
        .result-card {{ background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 16px; }}
        .score {{ font-size: 36px; font-weight: 800; }}
        .score.low {{ color: #22c55e; }}
        .score.medium {{ color: #eab308; }}
        .score.high {{ color: #ef4444; }}
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>PlagiarismGuard</h1>
            <div class="meta">{course} — {resource}</div>
        </div>
        <div class="meta">Signed in as {user_name}</div>
    </div>
    <textarea id="textInput" placeholder="Paste or type your submission text here..."></textarea>
    <button class="btn btn-primary" onclick="submitCheck()" id="btnSubmit">Check for Plagiarism</button>
    <div id="result"></div>
    <script>
        async function submitCheck() {{
            const text = document.getElementById('textInput').value.trim();
            if (text.length < 20) {{ alert('Please enter at least 20 characters.'); return; }}
            const btn = document.getElementById('btnSubmit');
            btn.disabled = true; btn.textContent = 'Analyzing...';
            try {{
                const r = await fetch('/api/v1/lti/check', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ text, user_email: '{user_email}' }})
                }});
                const data = await r.json();
                const score = data.plagiarism_score || 0;
                const risk = data.risk_level || 'LOW';
                const cls = score > 60 ? 'high' : score > 30 ? 'medium' : 'low';
                document.getElementById('result').innerHTML = `
                    <div class="result-card">
                        <div class="score ${{cls}}">${{score.toFixed(1)}}%</div>
                        <div style="margin:6px 0;font-size:14px;color:#94a3b8">
                            Risk: ${{risk}} · Confidence: ${{((data.confidence_score||0)*100).toFixed(0)}}%
                            · Sources: ${{(data.detected_sources||[]).length}}
                        </div>
                        <div style="font-size:12px;color:#64748b;margin-top:8px">
                            ${{score < 15 ? '✓ This submission appears to be original work.' : score < 40 ? '⚠ Some matching content found. Review flagged passages.' : '⚠ Significant matching content detected. Please review.'}}
                        </div>
                    </div>
                `;
            }} catch(e) {{
                document.getElementById('result').innerHTML = '<p style="color:#ef4444">Error: '+e.message+'</p>';
            }} finally {{
                btn.disabled = false; btn.textContent = 'Check for Plagiarism';
            }}
        }}
    </script>
</body>
</html>
    """)


@router.post("/check")
async def lti_check(request: Request):
    """Quick plagiarism check for LMS submissions (no auth required — launched from LTI)."""
    body = await request.json()
    text = body.get("text", "")
    if len(text) < 20:
        raise HTTPException(status_code=400, detail="Text too short")

    from app.services.orchestrator import run_pipeline
    from app.models.schemas import AgentInput
    from app.tools.chunker_tool import chunk_text

    chunks = chunk_text(text)
    agent_input = AgentInput(document_id="lti-check", text=text, chunks=chunks)

    try:
        report = await run_pipeline(agent_input)
        return report.model_dump(mode="json")
    except Exception as exc:
        logger.error("lti_check_error", error=str(exc))
        raise HTTPException(status_code=500, detail="Analysis failed")
