"""API contract tests for the archetype router (``api.routers.archetypes``).

These cover the parts that don't need the 5 GB TTS model: category listing,
filtering, pagination, lookup, 404s, and the preview *cache-hit* path (a
pre-existing cached WAV is served without invoking the model). The on-demand
render paths (``/preview`` cold, ``/use``) call the real inference pipeline and
are exercised by runtime/manual verification — they're structured to reuse
generation.py's proven ``_run_inference`` rather than re-implementing it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# conftest.py puts `backend/` on sys.path and points OMNIVOICE_DATA_DIR at a
# throwaway tmpdir before the router imports VOICES_DIR / OUTPUTS_DIR from
# the REAL core.config (the old sys.modules stub leaked at collection time).
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from core import archetypes  # noqa: E402
from api.routers import archetypes as arch_router  # noqa: E402


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(arch_router.router)
    return TestClient(app)


# ── Categories ────────────────────────────────────────────────────────────────
def test_categories_endpoint(client):
    r = client.get("/archetypes/categories")
    assert r.status_code == 200
    ids = {c["id"] for c in r.json()}
    assert ids == {
        "narration", "conversational", "characters",
        "social", "entertainment", "advertisement", "informative",
    }


# ── Listing + pagination ──────────────────────────────────────────────────────
def test_list_returns_paginated_envelope(client):
    r = client.get("/archetypes", params={"limit": 10})
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"total", "limit", "offset", "items"}
    assert body["total"] >= 250
    assert len(body["items"]) == 10


def test_list_offset_advances(client):
    first = client.get("/archetypes", params={"limit": 5, "offset": 0}).json()
    second = client.get("/archetypes", params={"limit": 5, "offset": 5}).json()
    assert first["total"] == second["total"]
    assert [i["id"] for i in first["items"]] != [i["id"] for i in second["items"]]


# ── Filters ───────────────────────────────────────────────────────────────────
def test_filter_featured(client):
    body = client.get("/archetypes", params={"featured": "true", "limit": 100}).json()
    assert body["items"]
    assert all(a["is_featured"] for a in body["items"])


def test_filter_use_case(client):
    body = client.get("/archetypes", params={"use_case": "narration", "limit": 20}).json()
    assert body["items"]
    assert all(a["use_case"] == "narration" for a in body["items"])


def test_filter_gender(client):
    body = client.get("/archetypes", params={"gender": "female", "limit": 20}).json()
    assert body["items"]
    assert all(a["facets"]["gender"] == "female" for a in body["items"])


def test_filter_language_chinese(client):
    body = client.get("/archetypes", params={"lang": "Chinese", "limit": 20}).json()
    assert body["items"]
    assert all(a["language"] == "Chinese" for a in body["items"])


# ── Free-text search (voice-picker gallery search) ────────────────────────────
def test_q_substring_search_by_name(client):
    """`q` reaches a featured voice by name — the gallery picker's search box."""
    body = client.get("/archetypes", params={"q": "librarian", "limit": 50}).json()
    assert body["items"]
    assert all("librarian" in a["name"].lower() for a in body["items"])


def test_q_matches_instruct_tokens(client):
    """`q` also matches instruct tokens (e.g. an accent) so typing narrows the
    several-hundred-voice catalog instead of only the loaded page."""
    body = client.get("/archetypes", params={"q": "british", "limit": 500}).json()
    assert body["items"]
    assert all("british" in a["instruct"].lower() or "british" in a["name"].lower()
               for a in body["items"])


def test_q_empty_is_noop(client):
    """A blank/whitespace `q` must not filter — it's the default picker state."""
    everything = client.get("/archetypes", params={"limit": 500}).json()["total"]
    blank = client.get("/archetypes", params={"q": "   ", "limit": 500}).json()["total"]
    assert blank == everything


# ── Lookup + 404s ─────────────────────────────────────────────────────────────
def test_get_single(client):
    sample = archetypes.list_archetypes(featured=True)[0]
    r = client.get(f"/archetypes/{sample['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == sample["id"]


def test_get_missing_404(client):
    assert client.get("/archetypes/nope-xyz").status_code == 404


def test_preview_missing_404(client):
    assert client.get("/archetypes/nope-xyz/preview").status_code == 404


def test_use_missing_404(client):
    assert client.post("/archetypes/nope-xyz/use").status_code == 404


# ── Preview cache-hit (no model needed) ───────────────────────────────────────
def test_preview_serves_cached_wav_without_model(client):
    sample = archetypes.list_archetypes(featured=True)[0]
    key = arch_router._preview_key(sample)
    cache_dir = Path(arch_router._PREVIEW_DIR)
    cache_dir.mkdir(parents=True, exist_ok=True)
    dummy = b"RIFF\x24\x00\x00\x00WAVEfmt cached-archetype-preview"
    (cache_dir / f"{key}.wav").write_bytes(dummy)

    r = client.get(f"/archetypes/{sample['id']}/preview")
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    assert r.content == dummy


# ── Materialize-on-use idempotency (dedup, no re-render) ───────────────────────
def test_use_is_idempotent_dedup(client, monkeypatch):
    """The 2nd `/use` of the same archetype reuses its one materialized profile
    and does NOT render again — the guarantee that materialize-on-select in any
    voice picker can't spawn duplicate rows on repeated picks.

    The render boundary (``_render_archetype_wav``) is mocked so no model/GPU is
    needed: it just drops a stub WAV where the row expects one.
    """
    from core.db import init_db

    init_db()  # ensure the voice_profiles table exists in the hermetic tmp DB

    render_calls = {"n": 0}

    async def _fake_render(a, out_path):
        render_calls["n"] += 1
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt stub")

    monkeypatch.setattr(arch_router, "_render_archetype_wav", _fake_render)

    sample = archetypes.list_archetypes(featured=True)[0]

    first = client.post(f"/archetypes/{sample['id']}/use")
    assert first.status_code == 200
    pid = first.json()["profile_id"]
    assert pid
    assert render_calls["n"] == 1

    second = client.post(f"/archetypes/{sample['id']}/use")
    assert second.status_code == 200
    assert second.json()["profile_id"] == pid  # same row reused
    assert render_calls["n"] == 1  # NOT re-rendered

    # Exactly one row exists for this archetype (no duplicate materialization).
    from core.db import db_conn
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT id FROM voice_profiles WHERE personality = ?", (sample["id"],)
        ).fetchall()
    assert len(rows) == 1
