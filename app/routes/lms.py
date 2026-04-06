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
        (state, nonce, iss, client_id, __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()),
    )

    # Determine platform auth endpoint
    platform = db.fetch_one(
        "SELECT auth_endpoint FROM lti_platforms WHERE issuer = ?", (iss,)
    )
    if not platform:
        raise HTTPException(status_code=400, detail="Unknown LTI platform issuer")
    auth_url = platform["auth_endpoint"]

    from urllib.parse import urlencode, quote
    query_params = urlencode({
        "scope": "openid",
        "response_type": "id_token",
        "response_mode": "form_post",
        "prompt": "none",
        "client_id": client_id,
        "redirect_uri": target_link_uri,
        "login_hint": login_hint,
        "state": state,
        "nonce": nonce,
        "lti_message_hint": lti_message_hint,
    }, quote_via=quote)
    redirect_url = f"{auth_url}?{query_params}"

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
    if not state:
        raise HTTPException(status_code=400, detail="Missing state parameter")

    # Validate state against stored lti_states (CSRF protection)
    db = get_db()
    state_row = db.fetch_one(
        "SELECT nonce, created_at FROM lti_states WHERE state = ?", (state,)
    )
    if not state_row:
        raise HTTPException(status_code=403, detail="Invalid or expired LTI state")
    expected_nonce = state_row["nonce"]
    # Delete the used state so it can't be replayed
    db.execute("DELETE FROM lti_states WHERE state = ?", (state,))
    # Clean up expired states older than 1 hour
    db.execute(
        "DELETE FROM lti_states WHERE created_at < ?",
        ((__import__("datetime").datetime.now(__import__("datetime").timezone.utc) - __import__("datetime").timedelta(hours=1)).isoformat(),),
    )

    # Decode JWT header to extract issuer for platform lookup
    import base64
    try:
        parts = id_token_str.split(".")
        if len(parts) != 3:
            raise ValueError("Invalid JWT structure")
        payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
        unverified_claims = json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id_token")

    # Validate JWT signature against platform JWKS when available
    issuer = unverified_claims.get("iss", "")
    claims = unverified_claims  # fallback if no platform registered

    platform = db.fetch_one(
        "SELECT jwks_uri, client_id FROM lti_platforms WHERE issuer = ?",
        (issuer,),
    )
    if platform and platform.get("jwks_uri"):
        import jwt
        import httpx

        try:
            resp = httpx.get(platform["jwks_uri"], timeout=10)
            resp.raise_for_status()
            jwks = resp.json()
            public_keys = {}
            for jwk in jwks.get("keys", []):
                kid = jwk.get("kid")
                if kid:
                    public_keys[kid] = jwt.algorithms.RSAAlgorithm.from_jwk(jwk)

            header_b64 = parts[0] + "=" * (4 - len(parts[0]) % 4)
            header = json.loads(base64.urlsafe_b64decode(header_b64))
            kid = header.get("kid")
            if kid not in public_keys:
                raise HTTPException(status_code=400, detail="Unknown signing key")

            claims = jwt.decode(
                id_token_str,
                key=public_keys[kid],
                algorithms=["RS256"],
                audience=platform["client_id"],
                issuer=issuer,
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("lti_jwt_verify_failed", error=str(exc)[:200])
            raise HTTPException(status_code=400, detail="JWT signature verification failed")
    else:
        logger.warning("lti_no_jwks", issuer=issuer,
                       detail="No JWKS URI registered — rejecting unverified token")
        raise HTTPException(status_code=400, detail="Platform JWKS not registered — cannot verify token")

    # Validate JWT nonce matches the one stored with the state (replay protection)
    jwt_nonce = claims.get("nonce", "")
    if not jwt_nonce or jwt_nonce != expected_nonce:
        raise HTTPException(status_code=403, detail="Invalid or replayed nonce")

    user_name = claims.get("name", "Student")
    user_email = claims.get("email", "")
    course = claims.get("https://purl.imsglobal.org/spec/lti/claim/context", {}).get("title", "Course")
    resource = claims.get("https://purl.imsglobal.org/spec/lti/claim/resource_link", {}).get("title", "Assignment")

    # Sanitize for safe HTML embedding
    import html as _html
    user_name = _html.escape(user_name)
    user_email = _html.escape(user_email)
    course = _html.escape(course)
    resource = _html.escape(resource)

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


# Simple IP-based rate limiter for unauthenticated LTI checks
_lti_check_counts: dict[str, list[float]] = {}
_LTI_CHECK_LIMIT = 10       # max checks per IP
_LTI_CHECK_WINDOW = 3600    # per hour (seconds)
_LTI_MAX_TEXT_LENGTH = 50000 # ~10K words


@router.post("/check")
async def lti_check(request: Request):
    """Quick plagiarism check for LMS submissions (launched from LTI)."""
    # --- IP-based rate limiting ------------------------------------------------
    import time as _time
    client_ip = request.client.host if request.client else "unknown"
    now = _time.time()
    hits = _lti_check_counts.get(client_ip, [])
    hits = [t for t in hits if now - t < _LTI_CHECK_WINDOW]
    if len(hits) >= _LTI_CHECK_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded — max {_LTI_CHECK_LIMIT} checks per hour.",
        )
    hits.append(now)
    _lti_check_counts[client_ip] = hits

    body = await request.json()
    text = body.get("text", "")
    if len(text) < 20:
        raise HTTPException(status_code=400, detail="Text too short")
    if len(text) > _LTI_MAX_TEXT_LENGTH:
        raise HTTPException(status_code=400, detail="Text too long (max 50 000 characters)")

    from app.services.orchestrator import run_pipeline
    from app.tools.content_extractor_tool import chunk_text

    chunks_result = chunk_text(text)
    chunks = chunks_result["chunks"]

    try:
        report = await run_pipeline(document_id="lti-check", text=text)
        return report.model_dump(mode="json")
    except Exception as exc:
        logger.error("lti_check_error", error=str(exc))
        raise HTTPException(status_code=500, detail="Analysis failed")
