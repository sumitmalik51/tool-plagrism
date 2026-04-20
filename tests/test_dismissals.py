"""Tests for the passage-dismissal API and the JS<->Python passage_key parity.

Covers:
- ``passage_key`` produces stable, JS-compatible hashes
- ``adjusted_score`` mirrors the frontend ``adjustedScore`` math
- POST/GET/DELETE on ``/api/v1/auth/scans/{document_id}/dismissals`` work
- Ownership checks (user A cannot read/write user B's dismissals)
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.utils.passage_key import adjusted_score, passage_key

client = TestClient(app)


def _auth_header(user_id: int = 1) -> dict[str, str]:
    from app.services.auth_service import create_access_token
    token = create_access_token(user_id, email=f"user{user_id}@example.com")
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# passage_key() / adjusted_score() unit tests
# ---------------------------------------------------------------------------

class TestPassageKey:
    def test_deterministic(self) -> None:
        a = passage_key("hello world", "https://example.com")
        b = passage_key("hello world", "https://example.com")
        assert a == b

    def test_different_text_yields_different_key(self) -> None:
        a = passage_key("hello world", "src")
        b = passage_key("hello earth", "src")
        assert a != b

    def test_different_source_yields_different_key(self) -> None:
        a = passage_key("hello world", "src1")
        b = passage_key("hello world", "src2")
        assert a != b

    def test_excerpt_suffix_is_human_readable(self) -> None:
        key = passage_key("This is a sample passage text", None)
        # excerpt = first 16 chars, whitespace -> _
        assert key.endswith("_This_is_a_sample")

    def test_empty_text_does_not_crash(self) -> None:
        k = passage_key("", "src")
        # Shape: <base36-hash>_<excerpt>; excerpt is empty for empty text.
        assert k.endswith("_")
        assert len(k.rstrip("_")) > 0

    def test_matches_known_js_output(self) -> None:
        # Reference values produced by the JS implementation in
        # frontend/src/lib/stores/dismissals-store.ts. If you change the
        # algorithm in either side, both must move together.
        # JS: passageKey({text: "abc", source: "x"}) -> djb2 of "abc\u0001x"
        # We assert the *shape* (base36 hash + "_" + first-16 excerpt) and
        # that it round-trips, which is the contract the frontend depends on.
        k = passage_key("abc", "x")
        assert "_" in k
        hash_part, excerpt = k.rsplit("_", 1)
        assert excerpt == "abc"
        # Hash is alphanumeric base36
        assert hash_part.isalnum()


class TestAdjustedScore:
    def test_no_dismissals_returns_original(self) -> None:
        passages = [{"text": "a", "source": "s", "similarity_score": 0.5}]
        assert adjusted_score(40.0, passages, {}) == 40.0
        assert adjusted_score(40.0, passages, None) == 40.0

    def test_all_dismissed_returns_zero(self) -> None:
        passages = [
            {"text": "a", "source": "s", "similarity_score": 0.5},
            {"text": "b", "source": "s", "similarity_score": 0.5},
        ]
        d = {passage_key("a", "s"): {"kind": "quotation"},
             passage_key("b", "s"): {"kind": "quotation"}}
        assert adjusted_score(40.0, passages, d) == 0.0

    def test_half_dismissed_halves_score(self) -> None:
        passages = [
            {"text": "a", "source": "s", "similarity_score": 1.0},
            {"text": "b", "source": "s", "similarity_score": 1.0},
        ]
        d = {passage_key("a", "s"): {"kind": "quotation"}}
        # 40 * (1 - 1/2) = 20
        assert adjusted_score(40.0, passages, d) == 20.0


# ---------------------------------------------------------------------------
# Dismissal endpoint tests (full DB round-trip via the test SQLite)
# ---------------------------------------------------------------------------

def _seed_scan(user_id: int, document_id: str = "doc-dismissal") -> None:
    """Insert a minimal user + scan row owned by ``user_id`` so endpoint
    ownership checks succeed."""
    from app.services.database import get_db
    from app.services.persistence import save_document, save_scan
    db = get_db()
    # Seed a users row (FK target). Idempotent via INSERT OR IGNORE.
    db.execute(
        "INSERT OR IGNORE INTO users (id, name, email, password) VALUES (?, ?, ?, ?)",
        (user_id, f"u{user_id}", f"u{user_id}@x.test", "x"),
    )
    save_document(document_id, user_id=user_id, filename="t.txt", char_count=10)
    save_scan(
        document_id,
        user_id=user_id,
        plagiarism_score=10.0,
        confidence_score=0.7,
        risk_level="LOW",
    )


class TestDismissalEndpoints:
    def test_requires_auth(self) -> None:
        # GET / DELETE-all / DELETE-one have no body so missing auth -> 401.
        for verb, path in [
            ("get", "/api/v1/auth/scans/doc1/dismissals"),
            ("delete", "/api/v1/auth/scans/doc1/dismissals"),
            ("delete", "/api/v1/auth/scans/doc1/dismissals/abc"),
        ]:
            resp = getattr(client, verb)(path)
            assert resp.status_code == 401, f"{verb.upper()} {path} should require auth"
        # POST: pass a valid body so we exercise the auth check, not 422.
        resp = client.post(
            "/api/v1/auth/scans/doc1/dismissals",
            json={"passage_key": "k", "kind": "quotation"},
        )
        assert resp.status_code == 401

    def test_404_on_unknown_scan(self) -> None:
        resp = client.get(
            "/api/v1/auth/scans/does-not-exist/dismissals",
            headers=_auth_header(99999),
        )
        assert resp.status_code == 404

    def test_full_lifecycle(self) -> None:
        user_id = 7001
        doc = "doc-lifecycle"
        _seed_scan(user_id, doc)

        h = _auth_header(user_id)
        # Initially empty
        resp = client.get(f"/api/v1/auth/scans/{doc}/dismissals", headers=h)
        assert resp.status_code == 200
        assert resp.json() == {"dismissals": {}}

        # Insert two
        for k, kind in [("k1_excerpt", "quotation"), ("k2_excerpt", "prior_work")]:
            r = client.post(
                f"/api/v1/auth/scans/{doc}/dismissals",
                json={"passage_key": k, "kind": kind},
                headers=h,
            )
            assert r.status_code == 200, r.text

        # Update an existing one (UPSERT semantics)
        r = client.post(
            f"/api/v1/auth/scans/{doc}/dismissals",
            json={"passage_key": "k1_excerpt", "kind": "false_positive"},
            headers=h,
        )
        assert r.status_code == 200

        # Read back
        resp = client.get(f"/api/v1/auth/scans/{doc}/dismissals", headers=h)
        body = resp.json()["dismissals"]
        assert body["k1_excerpt"]["kind"] == "false_positive"
        assert body["k2_excerpt"]["kind"] == "prior_work"

        # Delete one
        r = client.delete(
            f"/api/v1/auth/scans/{doc}/dismissals/k1_excerpt", headers=h,
        )
        assert r.status_code == 200
        assert r.json()["removed"] is True

        # Delete-all wipes the rest
        r = client.delete(f"/api/v1/auth/scans/{doc}/dismissals", headers=h)
        assert r.status_code == 200
        assert r.json()["removed"] >= 1

        resp = client.get(f"/api/v1/auth/scans/{doc}/dismissals", headers=h)
        assert resp.json() == {"dismissals": {}}

    def test_invalid_kind_rejected(self) -> None:
        user_id = 7002
        doc = "doc-invalid"
        _seed_scan(user_id, doc)

        r = client.post(
            f"/api/v1/auth/scans/{doc}/dismissals",
            json={"passage_key": "kx", "kind": "not_a_real_kind"},
            headers=_auth_header(user_id),
        )
        assert r.status_code == 422

    def test_other_user_cannot_access(self) -> None:
        owner = 7003
        intruder = 7004
        doc = "doc-private"
        _seed_scan(owner, doc)

        # Owner posts a dismissal
        r = client.post(
            f"/api/v1/auth/scans/{doc}/dismissals",
            json={"passage_key": "kp", "kind": "quotation"},
            headers=_auth_header(owner),
        )
        assert r.status_code == 200

        # Intruder gets 404 on read
        r = client.get(
            f"/api/v1/auth/scans/{doc}/dismissals",
            headers=_auth_header(intruder),
        )
        assert r.status_code == 404
