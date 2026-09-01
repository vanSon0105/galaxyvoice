# Task 6 Report: Settings-Owned Parity Workspace

## Status

DONE

## Commits

- `2d366fa520e79f55fedf8e75c7b103432dc5388e` - `feat: add native parity validation workspace`
- The report itself is committed separately after this implementation hash so the report can contain the exact implementation commit.

## Files Changed

Backend and backend tests:

- `tools/galaxy_ai_voice_subtitle_studio/app/parity/service.py`
- `tools/galaxy_ai_voice_subtitle_studio/app/server/routers/parity.py`
- `tools/galaxy_ai_voice_subtitle_studio/tests/parity/test_service.py`
- `tools/galaxy_ai_voice_subtitle_studio/tests/server/test_parity_api.py`

Frontend source and tests:

- `tools/galaxy_ai_voice_subtitle_studio/frontend/src/App.tsx`
- `tools/galaxy_ai_voice_subtitle_studio/frontend/src/App.test.tsx`
- `tools/galaxy_ai_voice_subtitle_studio/frontend/src/api/parity.ts`
- `tools/galaxy_ai_voice_subtitle_studio/frontend/src/api/parity.test.ts`
- `tools/galaxy_ai_voice_subtitle_studio/frontend/src/i18n/vi.ts`
- `tools/galaxy_ai_voice_subtitle_studio/frontend/src/index.css`
- `tools/galaxy_ai_voice_subtitle_studio/frontend/src/pages/ParityPage.tsx`
- `tools/galaxy_ai_voice_subtitle_studio/frontend/src/pages/ParityPage.test.tsx`
- `tools/galaxy_ai_voice_subtitle_studio/frontend/src/pages/SettingsPage.tsx`
- `tools/galaxy_ai_voice_subtitle_studio/frontend/src/pages/SettingsPage.test.tsx`

Production bundle:

- Regenerated `tools/galaxy_ai_voice_subtitle_studio/frontend/dist/index.html` and all content-hashed assets under `frontend/dist/assets/`.
- Added the isolated `ParityPage-K-_Le2Tf.js` chunk.
- Added current entry assets `index-CsZbDCUu.js` and `index-1qkcAd-q.css`.
- Replaced stale content-hashed chunks for AudioPostPanel, BatchPage, DubPage, DubbingPage, EditorPage, GalleryPage, RemovalPage, SeparationPage, SettingsPage, StudioPage, TaskButton, TranscriptsPage, VoiceLibraryPage, VoiceStudioPage, WorkspacesPage, settings, transcripts, voice, and voiceLibrary with the build outputs recorded in commit `2d366fa`.

This report:

- `.superpowers/sdd/2026-08-30-native-parity-validation/task-6-report.md`

## Behavior Delivered

- Added a lazy `/settings/parity` route and one Settings-owned navigation command.
- Added a typed parity API client for catalogue, corpus inspection, migration inspection, run list/detail/start, task cancellation, manual evidence, acceptance, and JSON/Markdown reports.
- Added corpus readiness totals and per-asset findings with explicit text statuses.
- Added read-only migration inspection with grouped importable, relink, unsupported, and warning totals.
- Added collapsed, keyboard-focusable native disclosures for per-case checks and measurements.
- Added run selection, start, cancel, refresh, and independently handled report download commands.
- Added manual pass/fail evidence controls with required notes and backend response refresh.
- Added final acceptance controls enabled exclusively by backend-projected `ready_for_acceptance`.
- Added a domain-service readiness projection that reuses the acceptance gate and matching terminal task check; the FastAPI router only serializes that service result.
- Preserved blocked and manual-pending outcomes as visibly non-successful states.

## Commands And Outcomes

- `npm test -- --run src/pages/ParityPage.test.tsx src/pages/SettingsPage.test.tsx src/App.test.tsx src/api/parity.test.ts`
  - Initial inherited state: exit 1; 3 failed, 15 passed.
  - Final: exit 0; 4 files passed, 18 tests passed.
- `npm test -- --run src/pages/ParityPage.test.tsx src/pages/SettingsPage.test.tsx src/App.test.tsx`
  - Exit 0; 3 files passed, 16 tests passed.
- `npm test`
  - Exit 0; 25 files passed, 87 tests passed.
- `npm run lint`
  - Exit 0; no warnings or errors after removing one unused type import.
- `npm run typecheck`
  - Exit 0; TypeScript emitted no diagnostics.
- `npm run build`
  - Exit 0; TypeScript build and Vite production build completed; 128 modules transformed; isolated parity chunk emitted at 13.92 kB (3.57 kB gzip).
- `python -m pytest tests/parity/test_service.py tests/server/test_parity_api.py`
  - Exit 0; 58 tests passed in 12.53 seconds; one third-party Starlette/httpx deprecation warning.
- `git diff --cached --check`
  - Exit 0; no whitespace errors.

## Self-Review Findings

- Reviewed every inherited uncommitted file against base `0cad63f3fdea516cbd563ffe8994934aaa483659`.
- Confirmed the backend additions are necessary because Task 6 requires the UI to consume a backend-driven final gate, while the Task 5 run response did not expose a readiness boolean.
- Confirmed acceptance logic was not duplicated in TypeScript: the UI trusts `ready_for_acceptance`, and the service projection reuses `_assert_ready` plus the existing task identity/status guard.
- Confirmed router changes remain thin and workflow behavior remains in `ParityService`.
- Confirmed `vendor/voicestudio` is untouched and integration remains across the existing HTTP boundary.
- Confirmed the production build contains a separate parity chunk, preserving lazy route isolation.
- Confirmed native `details`/`summary`, buttons, labels, text statuses, stable table dimensions, responsive layouts, and isolated query/mutation errors meet the accessibility and visual-system requirements.
- Fixed inherited patch issues found during review: Settings test DOM leakage, React Query v5 context leaking into start/cancel API mocks, a run-detail mock overwritten by its render helper, duplicate fallback case IDs when catalogue loading fails, and one unused type import.
- No unresolved correctness, architecture, security, or licensing findings remain.

## Concerns

- No task-blocking concerns.
- Focused backend tests emit an existing third-party `StarletteDeprecationWarning` about the `httpx` TestClient integration; it does not affect Task 6 behavior.

## Fix Round 1

### Status And Commits

- Status: DONE
- `881f884c1c419a5cc71d13af90421009e033bd27` - `fix: harden parity workspace state coherence`
- This Fix Round 1 report update is committed separately after the implementation hash so the report can record the exact implementation commit.

### Files Changed

Backend and backend tests:

- `tools/galaxy_ai_voice_subtitle_studio/app/parity/__init__.py`
- `tools/galaxy_ai_voice_subtitle_studio/app/parity/service.py`
- `tools/galaxy_ai_voice_subtitle_studio/app/server/routers/parity.py`
- `tools/galaxy_ai_voice_subtitle_studio/tests/parity/test_service.py`
- `tools/galaxy_ai_voice_subtitle_studio/tests/server/test_parity_api.py`

Frontend source and tests:

- `tools/galaxy_ai_voice_subtitle_studio/frontend/src/index.css`
- `tools/galaxy_ai_voice_subtitle_studio/frontend/src/pages/ParityPage.tsx`
- `tools/galaxy_ai_voice_subtitle_studio/frontend/src/pages/ParityPage.test.tsx`

Production bundle and report:

- Regenerated `tools/galaxy_ai_voice_subtitle_studio/frontend/dist/index.html` and its content-hashed assets; the updated lazy parity chunk is `ParityPage-DLl9ikLg.js`.
- `.superpowers/sdd/2026-08-30-native-parity-validation/task-6-report.md`

### Finding Resolutions

1. Added `ParityService.get_run_detail()` to project run evidence and `ready_for_acceptance` from one repository acceptance snapshot. The router now serializes this service-owned projection instead of independently reading run and readiness state. Final acceptance still takes and revalidates an acceptance snapshot, repository revisions, selected source, and terminal task state before commit.
2. Serialized manual submissions with one React Query mutation scope, disabled every manual command while a submission is pending, and stopped refetching over the authoritative mutation response. Final acceptance is disabled for the full manual pending period; the backend revision guard remains the final race defense.
3. Replaced page-global drafts with a selected-run keyed draft, keyed manual/acceptance/report errors to their originating run, and reset mutation/error state when selection changes. Existing answers from the newly selected run now win over any old local draft.
4. Bound successful corpus and migration results to the complete submitted request, including normalized path, approved roots, and copied-source confirmation. Results disappear immediately when any input changes, and corpus evidence labels use the inspected request's root rather than the current field value.
5. Added unsafe migration assets to grouped totals with explicit `không an toàn` text and the existing danger-status presentation. The page regression fixture and assertions cover unsafe assets and stale-result hiding.

### Commands And Exact Outcomes

- `npm test -- --run src/pages/ParityPage.test.tsx src/api/parity.test.ts`
  - Initial regression run: exit 1; 2 files ran, 4 tests failed and 10 passed, demonstrating all five inherited findings.
  - Final focused run: exit 0; 2 files passed, 14 tests passed.
- `npm test -- --run src/pages/ParityPage.test.tsx src/pages/SettingsPage.test.tsx src/App.test.tsx src/api/parity.test.ts`
  - Exit 0; 4 files passed, 21 tests passed.
- `npm test -- --run src/pages/ParityPage.test.tsx`
  - Exit 0; 1 file passed, 12 tests passed after the run-reset hook cleanup.
- `npm test`
  - Final exit 0; 25 files passed, 90 tests passed.
- `npm run lint`
  - Initial implementation exit 0 with one `react-hooks/exhaustive-deps` warning on the run-reset effect.
  - Final exit 0; no warnings or errors.
- `npm run typecheck`
  - Final exit 0; TypeScript emitted no diagnostics.
- `npm run build`
  - Final exit 0; TypeScript and Vite production builds completed, 128 modules transformed, and `ParityPage-DLl9ikLg.js` emitted at 15.23 kB (3.88 kB gzip).
- `python -m pytest tests/parity/test_service.py tests/server/test_parity_api.py -q` from `tools/galaxy_ai_voice_subtitle_studio`
  - Initial regression run: exit 1; 2 tests failed and 58 passed, demonstrating the mixed-revision response.
  - Final exit 0; 60 tests passed in 12.39 seconds with one existing third-party Starlette/httpx deprecation warning.
- `git diff --check`
  - Exit 0; no whitespace errors.
- `git diff --name-only 0cad63f3fdea516cbd563ffe8994934aaa483659 -- tools/galaxy_ai_voice_subtitle_studio/vendor/voicestudio`
  - Exit 0 with no output; the immutable vendor snapshot is untouched.

### Self-Review Findings

- Reviewed the complete Task 6 diff from base `0cad63f3fdea516cbd563ffe8994934aaa483659`, not only the Fix Round 1 patch.
- Confirmed successful run-detail responses derive evidence and readiness from the same repository snapshot; the reconciliation read is used only to repair terminal task state before that snapshot or to return a conservative false gate when snapshot integrity cannot be established.
- Confirmed `accept_run()` still performs server-side source, evidence revision, catalogue/manifest, and task-status revalidation under repository/task guards.
- Confirmed the router remains thin, acceptance behavior remains in `ParityService`/`ParityRepository`, and no validator or acceptance rule moved into TypeScript.
- Confirmed manual responses cannot replace each other out of order, acceptance is unavailable while manual work is pending, and cross-run late mutation errors remain hidden by run identity.
- Confirmed successful inspection evidence cannot be presented under changed request inputs and unsafe assets are visibly non-successful.
- Confirmed `frontend/dist` was regenerated from the verified source and the lazy parity route remains a separate production chunk.
- Removed one obsolete router type import during review. No unresolved correctness, architecture, security, or licensing findings remain.

### Concerns

- No task-blocking concerns.
- Focused backend tests continue to emit the pre-existing third-party `StarletteDeprecationWarning` about `httpx` with `starlette.testclient`.
