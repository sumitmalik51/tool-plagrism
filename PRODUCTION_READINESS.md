# PlagiarismGuard — Production Readiness Checklist

> **Status legend:** ✅ done · ⚠️ partial · ❌ blocker · ➡️ in progress
>
> Updated **2026-04-19** after a deep code review. Findings annotated with
> file paths and line numbers point to the verified location of each issue.

Tracks everything that must be true before the SaaS can serve real paying customers.

---

## 🔴 Concrete code-level blockers (found in audit)

These are bugs / security issues with verified locations in the codebase.

- [x] **`/health` blocks the event loop on Azure SQL cold start** — ~~[app/main.py](app/main.py#L343-L362) calls sync `db.fetch_one("SELECT 1")` on every healthcheck.~~ **Fixed 2026-04-19:** `/health` is now a pure liveness probe (returns 200 with no I/O); a new `/health/ready` does the DB ping via `asyncio.to_thread` with a 5 s `wait_for` cap and returns 503 when unreachable so load balancers depool the instance. Verified live: `/health` = 0.45 s, `/health/ready` = 0.47 s when DB is warm.

- [x] **`PG_JWT_SECRET` auto-generation breaks multi-worker dev** — ~~[app/services/auth_service.py](app/services/auth_service.py#L60-L70) does `os.environ.setdefault("PG_JWT_SECRET", secrets.token_hex(32))`.~~ **Fixed 2026-04-19:** `_get_jwt_secret()` now refuses to mint tokens with an ephemeral secret outside `debug=True`, and dev mode caches a per-process secret with a loud warning. Production refuses to start without `PG_JWT_SECRET` thanks to the existing `_validate_production_secrets`.

- [x] **Sync `httpx.get` inside async LMS route** — ~~[app/routes/lms.py](app/routes/lms.py#L209) does `httpx.get(platform["jwks_uri"], timeout=10)` blocking the event loop for up to 10 s per LTI launch.~~ **Fixed 2026-04-19:** swapped to `async with httpx.AsyncClient(timeout=10) as _client: await _client.get(...)`.

- [x] **SSRF in web-search page fetcher** — ~~[app/tools/web_search_tool.py](app/tools/web_search_tool.py#L222-L250) `_fetch_one()` follows redirects and fetches arbitrary URLs returned by Bing/DDG without checking for private/internal IPs.~~ **Fixed 2026-04-19:** extracted the guard to [app/utils/ssrf.py](app/utils/ssrf.py) (rejects private, loopback, link-local, multicast, reserved, and unspecified addresses) and wired it into `_fetch_one`. `webhooks.py` now delegates to the same helper. Google Docs import in `upload.py` is unchanged — the URL is server-constructed against `docs.google.com` with no user-controlled host, so SSRF risk is nil.

- [ ] **Rotate every secret in `.env`** — even though `.env` is `.gitignore`d and was never committed (verified via `git ls-files`), the values have been exposed during local debugging:
  - [ ] `PG_AZURE_OPENAI_API_KEY` — regenerate in Azure Portal
  - [ ] `PG_SQL_CONNECTION_STRING` — change SQL admin password (`Malik@123` is weak)
  - [ ] `PG_JWT_SECRET` — generate fresh `openssl rand -base64 32`
  - [ ] `PG_ACS_CONNECTION_STRING` — regenerate in Azure Communication Services
  - [ ] `PG_RAZORPAY_KEY_SECRET` and `PG_STRIPE_SECRET_KEY` — regenerate in respective dashboards
- [ ] **Move secrets out of `.env` into Azure App Service Configuration → Key Vault references**
- [x] ~~Strip `.env` from git history~~ — verified `.env` is **not** in git; only `.env.example` is tracked.
- [x] ~~Add `.env` to `.gitignore`~~ — already present in `.gitignore` line 18.
- [ ] **Create a separate `plagiarism-db-dev` database** so local dev never touches production data
- [ ] **Set `PG_API_KEYS_RAW`** to a strong random key in production. **Critical**: [app/middleware.py](app/middleware.py#L91-L99) explicitly bypasses authentication when `settings.api_keys` is empty (dev mode). If this is unset in prod, every protected route is wide open.
- [ ] **Enable Azure SQL firewall** with strict allowlist (only App Service outbound IPs + admin IP)
- [x] ~~Restrict CORS~~ — [app/main.py](app/main.py#L77-L94) already pins to `https://plagiarismguard-jl6yu5wij5mu4.azurewebsites.net`. **Verify** the new Next.js frontend domain is added when deployed (currently missing).
- [x] ~~Add security headers~~ — [app/middleware.py SecurityHeadersMiddleware](app/middleware.py#L155-L260) sets CSP, X-Frame-Options, X-Content-Type-Options, HSTS (when HTTPS), Referrer-Policy, Permissions-Policy. **Carry-over:** CSP allows `'unsafe-inline'` for scripts (needed for Tailwind CDN + inline `<script>`s). TODO already in code at line 220 — migrate to nonce-based CSP after replacing the Tailwind CDN with a build-time CSS file.
- [x] ~~Rate limiting on auth~~ — [app/routes/auth.py `_AuthRateLimiter`](app/routes/auth.py#L55-L100) limits to 10 attempts / IP / 5 min on `/signup`, `/login`, `/google`, `/forgot-password`, `/reset-password`. ⚠️ In-memory only — **does not survive worker restarts and is per-worker** (gunicorn with N workers gives an attacker N×10 attempts). Move to Redis or DB-backed counter for a multi-worker prod.
- [ ] **OWASP Top 10 audit:**
  - [x] **A03 SQL injection** — verified safe: dynamic identifiers in [app/services/persistence.py:get_user_scans](app/services/persistence.py#L132-L185) use an allowlist (`allowed_sort_cols`); admin filters in [app/routes/admin.py](app/routes/admin.py#L160-L230) only interpolate static SQL fragments; `expires_in_days` cast to `int` in [app/routes/analyze.py](app/routes/analyze.py#L540-L555). All user values are bound via `?` parameters.
  - [x] **A02 Cryptographic failures** — PBKDF2-SHA256 @ 260k iters ([app/services/auth_service.py](app/services/auth_service.py#L25-L45)) is OWASP-compliant. JWT signed HS256 with 2 h access / 7 d refresh.
  - [ ] **A01 Broken access control** — `/api/v1/auth/*` is in `_PUBLIC_PREFIXES` ([app/middleware.py](app/middleware.py#L43-L48)), so middleware does **not** enforce auth on user-info endpoints under that prefix; each route must verify the JWT itself (`_get_user_id(authorization)`). This works but is fragile — any new endpoint added under `/api/v1/auth/` that forgets to call the helper is silently public. Consider moving "logged-in user" routes (`/me`, `/api-keys`, `/webhooks-pref`, …) to `/api/v1/users/` and removing the blanket prefix.
  - [ ] **A07 Auth failures** — fix the two issues above (auto-generated JWT secret, in-memory rate limit).
  - [ ] **A10 SSRF** — fix web_search & Google Docs import (above).
  - [ ] **A05 Security misconfiguration** — verify `PG_DEBUG=false` in App Service Configuration; debug mode exposes `/docs`, `/redoc`, `/openapi.json`.
  - [ ] **XSS in user content** — scan reports render flagged passages back to the browser; verify the React frontend uses safe interpolation (no `dangerouslySetInnerHTML` with user input). Found one usage in [frontend/src/app/layout.tsx:46](frontend/src/app/layout.tsx#L46) which only injects a static theme-init script (safe).

- [ ] **Frontend stores access + refresh JWT in `localStorage`** — [frontend/src/lib/stores/auth-store.ts](frontend/src/lib/stores/auth-store.ts#L34-L72) and [frontend/src/lib/api.ts:84](frontend/src/lib/api.ts#L84). Any successful XSS exfiltrates the refresh token. Best-practice fix: keep access token in memory (Zustand state, not persisted) and put **refresh** token in an `HttpOnly; Secure; SameSite=Lax` cookie issued by a backend `/refresh` route. Trade-off acknowledged; record decision either way.

---

## 🟡 Database & migrations

- [x] Migration runner tolerates "duplicate column / already exists" errors (fixed today)
- [ ] **Verify migration v6 is recorded in production `schema_migrations` table** — the prior buggy run added the column but failed before the INSERT
  ```sql
  SELECT * FROM schema_migrations ORDER BY version;
  -- if v6 missing:
  INSERT INTO schema_migrations (version, description) VALUES (6, 'Add stripe_customer_id column to users');
  ```
- [ ] **Document Azure SQL backup retention** (verify point-in-time restore window in Azure Portal)
- [ ] **Test restore from backup** at least once
- [ ] **Add database connection pooling** for pyodbc (pool size, recycle interval)
- [ ] **Index audit** — `usage_logs.user_id`, `usage_logs.created_at`, `documents.user_id`, `scans.user_id`, etc.

---

## 🟢 CI / CD & quality

- [ ] **GitHub Actions workflow** running on every push/PR:
  - [ ] `pytest` (you already have ~80 test files)
  - [ ] `ruff check` + `mypy` for Python
  - [ ] `npm run lint` + `npm run build` for frontend
  - [ ] Block merge on red
- [ ] **Staging slot** in Azure App Service for blue/green deploys
- [ ] **Release notes / changelog** auto-generated from PRs
- [ ] **Dependabot or Renovate** for dependency updates
- [ ] **`pip-audit` / `npm audit`** on every CI run

---

## 🟡 Observability

- [ ] **Application Insights** wired into FastAPI (request traces, exceptions, dependencies)
- [ ] **Structured logs** shipped to Log Analytics workspace
- [ ] **Frontend error tracking** — Sentry or Application Insights browser SDK
- [ ] **Uptime monitor** on `/health` and `/api/v1/auth/me` (e.g. Azure Monitor availability test)
- [ ] **Alert rules**:
  - [ ] HTTP 5xx rate > 1%
  - [ ] DB connection failures
  - [ ] Azure OpenAI throttling / quota exhaustion
  - [ ] Daily cost anomaly
- [ ] **Dashboard** — Azure Workbook or Grafana with: scans/min, p95 latency, error rate, agent cost

---

## 🟡 Payment & billing

- [ ] **Razorpay live keys** (currently using test keys?)
- [ ] **Stripe live keys + webhook endpoint registered**
- [ ] **Webhook signature verification tested end-to-end** for both gateways
- [ ] **Idempotency keys** so retried webhook deliveries don't double-credit
- [ ] **Failed-payment dunning emails** wired up
- [ ] **Refund flow** documented for support
- [ ] **Tax handling** — GST for India, VAT MOSS for EU? (consult accountant)
- [ ] **Invoice PDFs** generated and emailed automatically

---

## 🟢 Legal & compliance

- [ ] `/privacy` page reviewed by legal counsel
- [ ] `/terms` page reviewed by legal counsel
- [ ] **DPA (Data Processing Agreement)** template ready for B2B / education customers
- [ ] **Cookie consent banner** if serving EU traffic
- [ ] **GDPR data export & delete** endpoints (`/auth/me/export`, `/auth/me/delete`)
- [ ] **Document retention policy** — when do scan results / uploaded files get purged?
- [ ] **Sub-processor list** (Azure, OpenAI, Razorpay, Stripe, ACS) published

---

## 🟡 Reliability

- [ ] **Health endpoint** — currently returns 200 even when DB is down (catches the exception and reports `degraded` in body but status is still 200). Either return 503 on `db_status == "error"` so load balancers actually depool the instance, or split into `/health/live` (always 200) and `/health/ready` (503 on DB down).
- [x] ~~Graceful degradation~~ — verify in [app/services/orchestrator.py](app/services/orchestrator.py#L160-L230); per-agent `asyncio.wait_for(timeout=90)` and `return_exceptions=True` mean partial results survive single-agent failures. 4-min hard cap on the whole pipeline.
- [ ] **Retries with exponential backoff** for Azure OpenAI / external scholarly APIs (arXiv, OpenAlex). DB layer already retries transient errors ([app/services/database.py](app/services/database.py#L165-L195)).
- [x] ~~Timeouts everywhere~~ — verified: every `httpx` client has an explicit `timeout=` arg (audit grep clean). Two minor offenders to fix: `lms.py:209` sync `httpx.get`, `web_search_tool` SSRF guard.
- [ ] **Circuit breakers** on external dependencies (Azure OpenAI, Bing, S2)
- [ ] **Load test** — verify 50 concurrent scans don't OOM the App Service plan. Embedding model is preloaded ([app/main.py](app/main.py#L46-L52)) but pyodbc connections are per-thread (`threading.local()`); under high concurrency you may exhaust the asyncio default 40-thread executor. Consider sizing `--workers` and `anyio` thread limit explicitly.

---

## 🟢 SaaS UX completeness

- [x] Landing page clearly lists features (5 agents, AI fingerprinting, 50+ languages, Chrome extension, Word add-in, LMS, webhooks, teams) — added today
- [x] Pricing page shows full feature matrix across tiers — fixed today
- [x] Pricing page has FAQ + team/enterprise CTA — added today
- [x] Dashboard input card unified, Analyze button always confident — fixed today
- [x] Dashboard shows Recent Analyses — fixed today
- [ ] **Onboarding tour** on first dashboard visit (could use Driver.js / Shepherd)
- [ ] **Empty states** with sample-data CTAs everywhere (history, tools, research writer)
- [ ] **In-app changelog / what's new** popover
- [ ] **Customer-facing API docs** (you have `/api-docs` — verify it's complete and styled)
- [ ] **Status page** (e.g. Statuspage.io or GitHub-Pages clone) linked from footer

---

## 🟡 Marketing & conversion

- [ ] Landing page screenshots of dashboard + report
- [ ] Customer logos / social proof strip ("Used by 500+ universities")
- [ ] Comparison page vs Turnitin, Grammarly, Copyleaks
- [ ] Blog or content engine for SEO (target keywords: "free plagiarism checker", "AI detector", etc.)
- [ ] Open Graph / Twitter card metadata on every page
- [ ] `sitemap.xml` + `robots.txt`
- [ ] Google Analytics 4 + Search Console verified
- [ ] Email drip sequence for free signups → Pro upgrade

---

## 🟢 Operations

- [ ] **Runbook** for common incidents (DB down, OpenAI quota hit, payment webhook failing)
- [ ] **On-call rotation** if a team
- [ ] **Customer support inbox** monitored (`support@plagiarismguard.com`)
- [ ] **Helpdesk** — Crisp, Intercom, or just a `mailto:` is fine to start
- [ ] **Backup admin account** with separate credentials
- [ ] **Disaster recovery plan** (RTO / RPO documented)

---

## Recommended order of attack

1. ~~Today (1–2 h): apply the four code-level fixes~~ — **Done 2026-04-19.** `/health` split into liveness + readiness with `to_thread`; `_get_jwt_secret` refuses ephemeral secrets in prod; `lms.py` JWKS fetch is now async; new `app/utils/ssrf.py` guards `web_search_tool` and is shared with `webhooks.py`.
2. **This week:** rotate all secrets, move to Key Vault references, set `PG_API_KEYS_RAW`, fix migration v6 in prod, separate dev DB, add the new Next.js domain to CORS allowlist.
3. **Next week:** GitHub Actions CI (pytest + lint + npm build), Application Insights, Redis-backed auth rate limiter, refactor `/api/v1/auth/*` so user-info endpoints aren't a public prefix.
4. **Then:** load test (50 concurrent scans), payment webhook idempotency keys, legal pages reviewed, refresh-token migration to HttpOnly cookie.
5. **Then ship:** marketing polish (screenshots, comparison page, email drip).

Once every item in 🔴 is clear and CI is green, you're ready for soft launch with a small cohort. Public launch after legal + load test pass.

---

## Audit summary (2026-04-19)

**Verified safe / already done:** SQL injection (parameterized + allowlists), password hashing (PBKDF2 260k), security headers, CSRF check on state-changing requests, webhook signature verification (Razorpay HMAC + Stripe `construct_event`), webhook SSRF guard, request IDs, structured logging, `.env` not in git, gzip compression, per-agent timeouts in orchestrator.

**Verified broken / risky:** sync DB call in `/health`, sync `httpx.get` in LMS route, missing SSRF guard on `web_search_tool` and `upload.py` URL fetcher, JWT secret auto-gen race across workers, in-memory auth rate limiter doesn't scale, JWTs in `localStorage`, `/api/v1/auth/*` blanket public prefix, `/health` returns 200 even when DB is degraded, no Application Insights wiring, no CI pipeline.

**Carry-overs (already in code as TODOs):** CSP `'unsafe-inline'` (waiting on Tailwind build migration), Razorpay/Stripe live keys not yet rotated.
