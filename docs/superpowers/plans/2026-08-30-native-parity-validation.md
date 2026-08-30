# Native Parity Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Galaxy-owned read-only VoiceStudio migration rehearsal and an evidence-gated native parity validation workspace that can produce deterministic reports without claiming acceptance before the real corpus and manual UAT pass.

**Architecture:** Add a deep `app.parity` domain module whose catalogue, corpus, migration, validation, persistence, and report services are independent of FastAPI. A thin typed router starts long-running runs through the existing `TaskRegistry`; a lazy Settings-owned React page consumes only that API. VoiceStudio remains an immutable, separately licensed reference and is never imported, patched, started, or written by this feature.

**Tech Stack:** Python 3.13, dataclasses, Pydantic/FastAPI, SQLite read-only URI, standard-library ZIP/WAV/JSON/hash tools, existing ffprobe and audio-postproduction helpers, React 19, TypeScript 6, TanStack Query, React Router, Vitest.

**Spec:** `docs/superpowers/specs/2026-08-30-native-parity-validation-design.md`

## Global Constraints

- Keep `tools/galaxy_ai_voice_subtitle_studio/vendor/voicestudio/` immutable and never import its application modules into Galaxy.
- Read only an explicitly selected copied VoiceStudio directory, database, or portable persona bundle.
- Never write to the selected source, a live VoiceStudio directory, Galaxy's real voice library, project graph, or history repositories.
- Open SQLite with `mode=ro`; protect ZIP inspection against path traversal, member-count, member-size, and total-uncompressed-size abuse.
- Make no network request and download no model or fixture from catalogue, inspection, execution, or UI code.
- Use exactly `pass`, `fail`, `blocked`, `manual_pending`, and `not_applicable` as check states.
- Treat missing reference measurements, blocked checks, and unanswered manual items as non-success.
- Store canonical JSON and deterministic Markdown atomically under Galaxy local application data with secrets, home paths, raw consent audio, and raw database payloads excluded.
- Run parity as TaskRegistry kind `native-parity-validation` with recovery route `/settings/parity` and cooperative cancellation.
- Keep `/settings/parity` lazy-loaded and Settings-owned; do not add it to top navigation or Voice workspace tabs.
- Commit `frontend/dist/` whenever frontend source changes.
- Issue 17 closes after its policy and dry-run tests pass; issue 15 remains open until a real unchanged corpus run is explicitly accepted by the user.

## File Structure

- `app/parity/models.py`: immutable domain records, statuses, thresholds, manifests, findings, runs, migration summaries, and acceptance records.
- `app/parity/catalogue.py`: fixed ordered validation catalogue and version.
- `app/parity/security.py`: approved-root path checks, fingerprints, report redaction, and bounded archive utilities.
- `app/parity/migration.py`: VoiceStudio copied-source inventory and sandbox-only normalization rehearsal.
- `app/parity/corpus.py`: versioned manifest loading, hashing, approved-root resolution, and per-asset readiness.
- `app/parity/validators.py`: output, subtitle, language/speaker, performance, cancellation, and recovery judges.
- `app/parity/repository.py`: atomic run/report persistence beneath local application data.
- `app/parity/reports.py`: canonical JSON and deterministic Markdown projections.
- `app/parity/service.py`: public facade, run orchestration, manual answers, and acceptance gating.
- `app/server/routers/parity.py`: typed HTTP request/response boundary only.
- `frontend/src/api/parity.ts`: parity API types and fetch functions.
- `frontend/src/pages/ParityPage.tsx`: readiness, rehearsal, run matrix, reports, manual UAT, and acceptance UI.

---

### Task 1: Typed Catalogue And Security Boundary

**Files:**
- Create: `tools/galaxy_ai_voice_subtitle_studio/app/parity/__init__.py`
- Create: `tools/galaxy_ai_voice_subtitle_studio/app/parity/models.py`
- Create: `tools/galaxy_ai_voice_subtitle_studio/app/parity/catalogue.py`
- Create: `tools/galaxy_ai_voice_subtitle_studio/app/parity/security.py`
- Create: `tools/galaxy_ai_voice_subtitle_studio/tests/parity/__init__.py`
- Create: `tools/galaxy_ai_voice_subtitle_studio/tests/parity/test_catalogue.py`
- Create: `tools/galaxy_ai_voice_subtitle_studio/tests/parity/test_security.py`

**Interfaces:**
- Produces: `get_catalogue() -> ParityCatalogue`; `resolve_approved_path(path: Path, roots: Sequence[Path]) -> Path`; `fingerprint_source(path: Path) -> SourceFingerprint`; `redact_report_value(value: Any) -> Any`.
- Produces stable required case IDs in this order: `shared.project_portability`, `studio.short_tts`, `studio.long_expressive_tts`, `batch.fifty_items`, `library.noisy_clone_consent`, `transcripts.multilingual_video`, `dubbing.two_speaker`, `longform.story`, `longform.audiobook`, `reliability.interruption`, `migration.voicestudio_copy`.
- Consumes: no new module; use frozen dataclasses and tuples so callers cannot mutate catalogue state.

- [ ] **Step 1: Write failing catalogue and boundary tests**

```python
def test_catalogue_is_stable_required_and_immutable():
    catalogue = get_catalogue()
    assert tuple(case.case_id for case in catalogue.cases) == EXPECTED_CASE_IDS
    assert all(case.required for case in catalogue.cases)
    with pytest.raises(FrozenInstanceError):
        catalogue.version = "changed"

def test_approved_path_rejects_escape(tmp_path):
    root = tmp_path / "selected"
    root.mkdir()
    with pytest.raises(UnsafePathError):
        resolve_approved_path(root / ".." / "outside.db", (root,))
```

- [ ] **Step 2: Run the tests and observe missing `app.parity` failures**

Run: `cd tools/galaxy_ai_voice_subtitle_studio; python -m pytest tests/parity/test_catalogue.py tests/parity/test_security.py -q`

- [ ] **Step 3: Implement domain records, exact catalogue order, path confinement, deterministic fingerprints, and sensitive-value redaction**

`ParityCase` must carry `case_id`, `area`, `title`, `required`, ordered `fixture_roles`, ordered `checks`, ordered `manual_prompts`, and immutable `thresholds`. Fingerprints hash regular-file bytes and deterministic directory entries without following symlinks. Redaction removes sensitive-key values and replaces home-root prefixes in strings with `<home>`.

- [ ] **Step 4: Run the focused tests and verify green**

Run: `cd tools/galaxy_ai_voice_subtitle_studio; python -m pytest tests/parity/test_catalogue.py tests/parity/test_security.py -q`

- [ ] **Step 5: Commit**

```powershell
git add tools/galaxy_ai_voice_subtitle_studio/app/parity tools/galaxy_ai_voice_subtitle_studio/tests/parity
git commit -m "feat: define native parity catalogue"
```

### Task 2: VoiceStudio Migration Dry-Run And Issue 17

**Files:**
- Create: `tools/galaxy_ai_voice_subtitle_studio/app/parity/migration.py`
- Create: `tools/galaxy_ai_voice_subtitle_studio/tests/parity/test_migration.py`
- Modify: `.scratch/native-voice-workspace/issues/17-voicestudio-data-migration-policy.md`

**Interfaces:**
- Consumes: `resolve_approved_path`, `fingerprint_source`, and migration records from Task 1.
- Produces: `inspect_migration_source(source: Path, *, approved_roots: Sequence[Path], sandbox_root: Path | None = None) -> MigrationDryRun`.
- Produces candidate groups `voice_profiles`, `persona_bundles`, `generation_history`, `dub_history`, `studio_projects`, `export_history`, `glossary_terms`, `pronunciation_entries`, `discovered_documents`, plus `unsupported` and `warnings`.

- [ ] **Step 1: Write fixture builders and failing policy tests**

```python
def test_sqlite_rehearsal_is_read_only_and_downgrades_incomplete_consent(tmp_path):
    source = build_source_db(tmp_path, consent_text="I agree", consent_recording="missing.wav")
    before = fingerprint_source(source)
    report = inspect_migration_source(source, approved_roots=(tmp_path,))
    assert report.source_before == before == report.source_after
    assert report.voice_profiles[0].consent.confirmed is False
    assert "re-attestation" in report.voice_profiles[0].warnings

def test_bundle_blocks_traversal_and_cleans_sandbox(tmp_path):
    bundle = build_bundle(tmp_path, {"../../escape.wav": b"bad"})
    report = inspect_migration_source(bundle, approved_roots=(tmp_path,))
    assert report.assets[0].state == "unsafe"
    assert not list((tmp_path / "sandbox").glob("**/*"))
```

Also assert unknown tables/columns become forward-version warnings; missing, linked, managed, and unsafe assets are distinct; settings/tokens/jobs/logs/model caches are unsupported; bounded JSON rejects oversized `tracks`/`job_data`; no table or source file changes.

- [ ] **Step 2: Run the migration tests and observe missing implementation failures**

Run: `cd tools/galaxy_ai_voice_subtitle_studio; python -m pytest tests/parity/test_migration.py -q`

- [ ] **Step 3: Implement read-only SQLite, bounded persona inspection, explicit mappings, consent rules, asset classification, sandbox parse validation, and cleanup**

Use `sqlite3.connect(f"file:{quoted_path}?mode=ro", uri=True)`. Query only known columns that exist in `PRAGMA table_info`, inventory extras, parse bounded JSON before mapping, and use `TemporaryDirectory(dir=sandbox_root)` for normalized candidate validation. Do not invoke VoiceStudio code or Galaxy production repositories.

- [ ] **Step 4: Prove source immutability and policy coverage**

Run: `cd tools/galaxy_ai_voice_subtitle_studio; python -m pytest tests/parity/test_migration.py tests/parity/test_security.py -q`

- [ ] **Step 5: Record issue 17 resolution with commands and exact policy outcome, then commit**

```powershell
git add tools/galaxy_ai_voice_subtitle_studio/app/parity tools/galaxy_ai_voice_subtitle_studio/tests/parity .scratch/native-voice-workspace/issues/17-voicestudio-data-migration-policy.md
git commit -m "feat: rehearse VoiceStudio data migration"
```

### Task 3: Fixture Corpus And Deterministic Validators

**Files:**
- Create: `tools/galaxy_ai_voice_subtitle_studio/app/parity/corpus.py`
- Create: `tools/galaxy_ai_voice_subtitle_studio/app/parity/validators.py`
- Create: `tools/galaxy_ai_voice_subtitle_studio/tests/parity/test_corpus.py`
- Create: `tools/galaxy_ai_voice_subtitle_studio/tests/parity/test_validators.py`
- Create: `tools/galaxy_ai_voice_subtitle_studio/tests/fixtures/parity/manifest.json`
- Create: `tools/galaxy_ai_voice_subtitle_studio/tests/fixtures/parity/sample.srt`

**Interfaces:**
- Consumes: manifest, asset, threshold, status, and finding records from Task 1; `find_ffprobe()` from `app.common.ffmpeg`.
- Produces: `inspect_corpus(manifest_path: Path, *, approved_roots: Sequence[Path]) -> CorpusInspection`; `validate_case(case: ParityCase, assets: Mapping[str, Path], *, probe: MediaProbe, measurements: Mapping[str, Any]) -> CaseResult`.
- Produces pure judges `judge_duration`, `judge_subtitles`, `judge_identity_mapping`, `judge_loudness`, `judge_performance`, `judge_cancellation`, and `judge_recovery` returning `CheckResult`.

- [ ] **Step 1: Write failing manifest/readiness and threshold tests**

```python
def test_manifest_reports_each_asset_without_blocking_unrelated_cases(tmp_path):
    inspection = inspect_corpus(write_manifest_with_one_missing_asset(tmp_path), approved_roots=(tmp_path,))
    assert inspection.assets_by_role["short_tts"].status == "ready"
    assert inspection.assets_by_role["long_video"].status == "missing"

def test_missing_reference_metric_is_blocked():
    result = judge_performance(native=PerformanceSample(wall_seconds=1), reference=None)
    assert result.status == "blocked"
```

Pin SHA-256, byte-size, unsafe path, checksum mismatch, WAV metadata, exact subtitle order/count, duration `max(250 ms, 5%)`, exact normalized speaker/language IDs, default `-16 LUFS +/- 2`, ratios `<= 1.25`, response p95 `<= 200 ms`, CPU cancel `<= 2 s`, accelerator cancel `<= 5 s`, and interrupted recovery route behavior.

- [ ] **Step 2: Run focused tests and observe failures**

Run: `cd tools/galaxy_ai_voice_subtitle_studio; python -m pytest tests/parity/test_corpus.py tests/parity/test_validators.py -q`

- [ ] **Step 3: Implement strict manifest parsing, per-asset readiness, injected media probing, and pure validators**

Tests must generate temporary deterministic WAV/JSON/SQLite/bundle files rather than commit large binaries. Media probing must be injectable so unit tests require neither model nor GPU; actual stream checks invoke the existing ffprobe locator only during a user run.

- [ ] **Step 4: Run corpus and validator tests**

Run: `cd tools/galaxy_ai_voice_subtitle_studio; python -m pytest tests/parity/test_corpus.py tests/parity/test_validators.py -q`

- [ ] **Step 5: Commit**

```powershell
git add tools/galaxy_ai_voice_subtitle_studio/app/parity tools/galaxy_ai_voice_subtitle_studio/tests/parity tools/galaxy_ai_voice_subtitle_studio/tests/fixtures/parity
git commit -m "feat: validate native parity corpus"
```

### Task 4: Persistent Runs, Reports, And Acceptance Gate

**Files:**
- Create: `tools/galaxy_ai_voice_subtitle_studio/app/parity/repository.py`
- Create: `tools/galaxy_ai_voice_subtitle_studio/app/parity/reports.py`
- Create: `tools/galaxy_ai_voice_subtitle_studio/app/parity/service.py`
- Create: `tools/galaxy_ai_voice_subtitle_studio/tests/parity/test_repository.py`
- Create: `tools/galaxy_ai_voice_subtitle_studio/tests/parity/test_reports.py`
- Create: `tools/galaxy_ai_voice_subtitle_studio/tests/parity/test_service.py`
- Modify: `tools/galaxy_ai_voice_subtitle_studio/app/runtime/jobs.py`

**Interfaces:**
- Consumes: Tasks 1-3 and `TaskRegistry.create/submit`, `TaskContext.report/check_cancelled/save_checkpoint`.
- Produces public facade `ParityService(catalogue, repository, task_registry)` with `list_catalogue`, `inspect_corpus`, `inspect_migration`, `start_run`, `list_runs`, `get_run`, `read_report`, `record_manual_item`, and `accept_run`.
- `start_run(request: StartParityRun) -> TaskRecord` creates kind `native-parity-validation`, resource keys `("cpu", "disk")`, recovery route `/settings/parity`, and serializes `{"run_id": run_id}`.

- [ ] **Step 1: Write failing lifecycle, persistence, cancellation, determinism, and acceptance tests**

```python
def test_acceptance_recomputes_readiness_and_rejects_blocked_run(service):
    run = service.store_completed_run(required_status="blocked")
    with pytest.raises(ParityNotReadyError):
        service.accept_run(run.run_id, note="reviewed")

def test_reports_are_deterministic_and_redacted(service):
    first = service.render_reports(FIXED_RUN)
    second = service.render_reports(FIXED_RUN)
    assert first.json_bytes == second.json_bytes
    assert first.markdown == second.markdown
    assert "secret-token" not in first.markdown
```

Assert independent cases continue after failure, completed automated results cannot be rewritten, manual answers and final acceptance are the only legal mutations, changed manifest/catalogue hashes invalidate acceptance, cancelled/interrupted tasks remain evidence but cannot be accepted, and atomic writes survive a simulated replace failure.

- [ ] **Step 2: Run lifecycle tests and observe failures**

Run: `cd tools/galaxy_ai_voice_subtitle_studio; python -m pytest tests/parity/test_repository.py tests/parity/test_reports.py tests/parity/test_service.py -q`

- [ ] **Step 3: Implement local state paths, atomic repository, deterministic reports, orchestration, and acceptance recomputation**

Add `_RECOVERY_DEFAULTS["native-parity-validation"] = ("/settings/parity", <Vietnamese recovery hint>)`. Persist one immutable run envelope plus separate manual/acceptance overlays or enforce equivalent field-level mutation rules. A case exception becomes a failed case result and execution proceeds; cancellation exits cooperatively through `TaskContext`.

- [ ] **Step 4: Run parity lifecycle and shared TaskRegistry tests**

Run: `cd tools/galaxy_ai_voice_subtitle_studio; python -m pytest tests/parity/test_repository.py tests/parity/test_reports.py tests/parity/test_service.py tests/runtime/test_jobs.py -q`

- [ ] **Step 5: Commit**

```powershell
git add tools/galaxy_ai_voice_subtitle_studio/app/parity tools/galaxy_ai_voice_subtitle_studio/app/runtime/jobs.py tools/galaxy_ai_voice_subtitle_studio/tests/parity tools/galaxy_ai_voice_subtitle_studio/tests/runtime/test_jobs.py
git commit -m "feat: persist native parity evidence"
```

### Task 5: Typed Parity HTTP API

**Files:**
- Create: `tools/galaxy_ai_voice_subtitle_studio/app/server/routers/parity.py`
- Modify: `tools/galaxy_ai_voice_subtitle_studio/app/server/main.py`
- Create: `tools/galaxy_ai_voice_subtitle_studio/tests/server/test_parity_api.py`

**Interfaces:**
- Consumes: `ParityService` from Task 4 and shared `task_registry` from `app.server.tasks`.
- Produces the nine `/api/parity` endpoints exactly specified in the design, explicit Pydantic request/response models, HTTP 404 for unknown runs/reports, 409 for premature acceptance, and 422 for unsafe/unapproved paths.

- [ ] **Step 1: Write failing router and OpenAPI contract tests**

```python
def test_catalogue_and_run_contract(client):
    response = client.get("/api/parity/catalogue")
    assert response.status_code == 200
    assert response.json()["cases"][0]["case_id"] == "shared.project_portability"

def test_accept_rejects_incomplete_run(client, incomplete_run_id):
    response = client.post(f"/api/parity/runs/{incomplete_run_id}/accept", json={"note": "reviewed"})
    assert response.status_code == 409
```

Also pin report content types, manual answer validation, task ID response, path traversal rejection, list/detail response shapes, and no operation that starts VoiceStudio or applies migration.

- [ ] **Step 2: Run API tests and observe 404/import failures**

Run: `cd tools/galaxy_ai_voice_subtitle_studio; python -m pytest tests/server/test_parity_api.py -q`

- [ ] **Step 3: Implement thin router models and route registration**

Dependency construction may read application state paths and selected request paths, but all inspection, execution, report, and acceptance logic must delegate to `ParityService`.

- [ ] **Step 4: Run API and parity domain tests**

Run: `cd tools/galaxy_ai_voice_subtitle_studio; python -m pytest tests/server/test_parity_api.py tests/parity -q`

- [ ] **Step 5: Commit**

```powershell
git add tools/galaxy_ai_voice_subtitle_studio/app/server tools/galaxy_ai_voice_subtitle_studio/tests/server/test_parity_api.py
git commit -m "feat: expose native parity validation api"
```

### Task 6: Settings-Owned Parity Workspace

**Files:**
- Create: `tools/galaxy_ai_voice_subtitle_studio/frontend/src/api/parity.ts`
- Create: `tools/galaxy_ai_voice_subtitle_studio/frontend/src/pages/ParityPage.tsx`
- Create: `tools/galaxy_ai_voice_subtitle_studio/frontend/src/pages/ParityPage.test.tsx`
- Modify: `tools/galaxy_ai_voice_subtitle_studio/frontend/src/pages/SettingsPage.tsx`
- Modify: `tools/galaxy_ai_voice_subtitle_studio/frontend/src/pages/SettingsPage.test.tsx`
- Modify: `tools/galaxy_ai_voice_subtitle_studio/frontend/src/App.tsx`
- Modify: `tools/galaxy_ai_voice_subtitle_studio/frontend/src/App.test.tsx`
- Modify: `tools/galaxy_ai_voice_subtitle_studio/frontend/src/index.css`
- Modify: `tools/galaxy_ai_voice_subtitle_studio/frontend/src/i18n/vi.ts`
- Modify: `tools/galaxy_ai_voice_subtitle_studio/frontend/dist/`

**Interfaces:**
- Consumes: Task 5 JSON contracts and existing `apiJson`, React Query, task cancellation API, design tokens, section/card/disclosure patterns.
- Produces: lazy route `/settings/parity`, one Settings entry command, readiness and migration summaries, collapsed per-case findings, run/cancel/refresh/report commands, manual answer controls, and a backend-driven final acceptance gate.

- [ ] **Step 1: Write failing API and page interaction tests**

```tsx
it('keeps blocked and manual-pending results visibly non-successful', async () => {
  renderParityPage({ run: blockedRun })
  expect(await screen.findByText('Bị chặn')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Chấp nhận kết quả' })).toBeDisabled()
})

it('records manual evidence before enabling acceptance', async () => {
  renderParityPage({ run: readyAfterManualRun })
  await user.click(await screen.findByRole('button', { name: 'Đạt' }))
  expect(mockFetch).toHaveBeenCalledWith(expect.stringContaining('/manual-items/'), expect.anything())
})
```

Also test lazy route isolation, Settings navigation, keyboard-expandable cases, migration grouped totals, independent optional report-download error, cancel action, and final acceptance enabled only when the response says `ready_for_acceptance`.

- [ ] **Step 2: Run frontend tests and observe missing page failures**

Run: `cd tools/galaxy_ai_voice_subtitle_studio/frontend; npm test -- --run src/pages/ParityPage.test.tsx src/pages/SettingsPage.test.tsx src/App.test.tsx`

- [ ] **Step 3: Implement typed API client and the parity workspace using the existing Galaxy visual system**

Use explicit status text in addition to color, native buttons for commands, accessible disclosure controls, stable table/card dimensions, and isolated query error states. Do not duplicate validator or acceptance logic in TypeScript.

- [ ] **Step 4: Run frontend test, lint, typecheck, and production build**

Run: `cd tools/galaxy_ai_voice_subtitle_studio/frontend; npm test; npm run lint; npm run typecheck; npm run build`

- [ ] **Step 5: Commit source and production bundle**

```powershell
git add tools/galaxy_ai_voice_subtitle_studio/frontend/src tools/galaxy_ai_voice_subtitle_studio/frontend/dist
git commit -m "feat: add native parity validation workspace"
```

### Task 7: Decision Records, Ticket State, And Full Verification

**Files:**
- Create: `docs/adr/0015-native-parity-validation-is-evidence-gated.md`
- Modify: `CONTEXT.md`
- Modify: `.scratch/native-voice-workspace/map.md`
- Modify: `.scratch/native-voice-workspace/issues/15-native-parity-validation.md`
- Modify: `.scratch/native-voice-workspace/issues/17-voicestudio-data-migration-policy.md`
- Modify: project parity/capability matrix document identified by `rg -l "Phase 15|native parity" docs .scratch`

**Interfaces:**
- Consumes: all implemented behavior and observed verification output.
- Produces: binding evidence policy, issue 17 `resolved` with automated proof, issue 15 `ready-for-human` or equivalent open state pending real corpus/UAT, and a documented command for reopening `/settings/parity` after interruption.

- [ ] **Step 1: Write the ADR and update domain/ticket documents with only verified claims**

The ADR must state that automated framework completion is not native parity acceptance, accepted reports are the sole Phase 16 input, and VoiceStudio remains available for comparison until that gate passes. Issue 15 must list the external corpus/manual actions still required instead of marking them complete.

- [ ] **Step 2: Run the complete backend suite**

Run: `cd tools/galaxy_ai_voice_subtitle_studio; python -m pytest tests -q`

- [ ] **Step 3: Run complete frontend gates and rebuild committed output**

Run: `cd tools/galaxy_ai_voice_subtitle_studio/frontend; npm test; npm run lint; npm run typecheck; npm run build`

- [ ] **Step 4: Run source and repository hygiene gates**

Run: `cd tools/galaxy_ai_voice_subtitle_studio; python -m compileall -q app`

Run: `git diff --check`

Run: `git status --short`

Verify no file beneath `tools/galaxy_ai_voice_subtitle_studio/vendor/voicestudio/` changed and no generated parity reports, selected corpus media, copied database, API key, or local absolute path is tracked.

- [ ] **Step 5: Commit documentation and ticket state**

```powershell
git add docs/adr/0015-native-parity-validation-is-evidence-gated.md CONTEXT.md .scratch/native-voice-workspace
git add <the parity matrix document reported by rg>
git commit -m "docs: record native parity validation gate"
```

- [ ] **Step 6: Produce the user handoff**

Report the commit range, backend/frontend counts, the local `/settings/parity` route, issue 17 resolution, issue 15's remaining real-corpus/UAT gate, and any metric that is intentionally `blocked` until reference evidence is supplied.
