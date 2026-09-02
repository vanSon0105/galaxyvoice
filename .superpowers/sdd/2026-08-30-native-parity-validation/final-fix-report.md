# Phase 15 Final Fix Wave Report

## Status

DONE_WITH_CONCERNS

The automated implementation and repository verification are complete. Native
parity is not accepted: issue 15 remains `ready-for-human` until the unchanged
real corpus, matched VoiceStudio references, manual UAT, and explicit local
acceptance produce an Accepted Parity Report. Phase 16 must then separately
approve retirement.

## Commits

- Base: `eb7329ad810a162fed0bab5f8de6b855fb499ad3`
- Implementation, tests, production bundle, and documentation:
  `bfaa988` - `fix: close native parity integration gaps`
- This report is committed separately so it can record the implementation hash.

## Final Review Findings Closed

1. **Public typed run contract.** `POST /api/parity/runs` now accepts a strict,
   discriminated evidence schema and parses it server-side into domain evidence.
   Settings provides an evidence JSON editor/import surface. Missing evidence
   remains `blocked`; it is never inferred as passing.
2. **Behavioral evidence.** Project reopen, moved-directory portability, relink,
   handoff, and checkpoint checks require checksum-bound Galaxy artifact proofs.
   Migration checks execute the Galaxy-owned read-only rehearsal against
   explicitly confirmed copied sources. A generic `passed=true` value cannot
   satisfy a behavioral check.
3. **Recoverable acceptance.** Acceptance persists a retry identity, stages an
   immutable deterministic report revision, and publishes the acceptance overlay
   only after report staging succeeds. Failure injection leaves the run
   unaccepted and retryable without changing guarded input revisions.
4. **Shared archive policy.** Corpus and migration ZIP inspection share
   `archive_policy.py` and reject traversal, links, unsupported types, encryption,
   Windows reserved names/colon components/trailing aliases, Unicode-normalized
   duplicates, count/size excesses, and compression bombs before opening data.
5. **Bounded cancellation and terminal state.** Hashing, archive reads, media
   probes, case validation, migration rehearsal, and artifact reads call the
   cooperative cancellation hook. Media probes are polled with bounded waits.
   TaskRegistry terminalizes the run through a callback under the task guard, so
   a run cannot finish `completed` while its task commits `cancelled`.
6. **Performance provenance.** Native/reference samples retain hardware identity,
   resolved device, raw wall/RAM/VRAM values, response samples, ratios, and p95
   measurements in the deterministic report.
7. **Path redaction.** Persistence and report errors redact approved external
   roots, current-home paths, and remaining absolute Windows/POSIX paths with
   stable placeholders.
8. **Truthful documentation.** ADR 0015, `CONTEXT.md`, workspace map, issues
   15/17, and the parity matrix describe the typed/content-bound gate and retain
   the two separate retirement approvals. Issue 15 remains open for human work.

## Files And Boundaries

- Added Galaxy-owned domain modules:
  `app/parity/archive_policy.py` and `app/parity/evidence.py`.
- Updated parity corpus, migration, validators, security, repository, reports,
  service, API router, and TaskRegistry terminal callback support.
- Updated the typed React client and `/settings/parity` evidence controls, tests,
  styles, Vietnamese labels, and committed `frontend/dist`.
- Added `tests/parity/test_final_fix_wave.py` and extended parity/API regression
  coverage.
- Updated the domain/ADR/ticket/matrix documents named above.
- No file under `vendor/voicestudio` changed, and Galaxy still does not import or
  patch VoiceStudio application source.

## Red-Green Evidence

The final whole-branch review at `eb7329a` reported two Critical and six
Important defects, including an unusable public evidence contract, forgeable
behavioral passes, non-atomic accepted-report publication, divergent ZIP rules,
cancellation races, missing performance provenance, and external-path leakage.
Two replacement implementers wrote regression tests before and during the fix,
but both sessions ended at their usage limit before preserving their initial
failing command output. No failing count is invented here.

On controller takeover, the inherited patch first passed the focused public API
and final-fix suite (`66 passed`) and then the complete parity suite
(`226 passed`). The final source subsequently passed all focused and full gates
below. The new tests directly cover forged boolean rejection, valid
content-bound artifacts, strict public JSON parsing, acceptance publication
failure/retry, Windows ZIP aliases, cancellation terminal races, performance
provenance, and non-home external-path redaction.

## Verification Commands And Outcomes

Working directory unless stated otherwise:
`tools/galaxy_ai_voice_subtitle_studio`.

- `python -m pytest tests/parity/test_final_fix_wave.py tests/server/test_parity_api.py -q`
  - Exit 0: `66 passed, 1 warning in 9.57s`.
- `python -m pytest tests/parity -q`
  - Exit 0: `226 passed in 33.01s`.
- `python -m pytest tests -q`
  - Exit 0: `751 passed, 1 warning, 60 subtests passed in 76.82s`.
- `python -m pytest tests/parity/test_migration.py tests/parity/test_security.py tests/parity/test_final_fix_wave.py -q -rs`
  - Exit 0: `85 passed in 12.29s`; no security test in this focused set skipped.
- `python -m compileall -q app`
  - Exit 0 with no output.

Working directory: `tools/galaxy_ai_voice_subtitle_studio/frontend`.

- `npm test -- --run src/pages/ParityPage.test.tsx src/api/parity.test.ts`
  - Exit 0: 2 files and 16 tests passed in 40.39s.
- `npm test`
  - Exit 0: 25 files and 92 tests passed in 13.43s.
- `npm run lint`
  - Exit 0; `oxlint src` emitted no warnings or errors.
- `npm run typecheck`
  - Exit 0; TypeScript emitted no diagnostics.
- `npm run build`
  - Exit 0; Vite 8.2.1 transformed 128 modules and built in 1.22s.
  - Lazy parity chunk: `ParityPage-BsBYoHd4.js`, 16.56 kB (4.27 kB gzip).

Repository gates:

- `git diff --check` and `git diff --cached --check`
  - Exit 0; only non-failing Windows LF-to-CRLF notices appeared.
- Vendor working-tree diff
  - No output; the immutable VoiceStudio snapshot is unchanged.
- Diff scans for `C:\Users\Rom`, the local repository path, private-key
  headers, high-confidence OpenAI/GitHub/Google token forms
  - No matches.
- Tracked evidence-extension scan
  - Only the pre-existing media/database fixtures inside immutable
  `vendor/voicestudio` matched. No generated parity report, selected corpus,
  copied database, or new media artifact is tracked.

The backend warning is the existing Starlette/httpx TestClient deprecation
warning. It does not affect parity behavior.

## Self-Review

- Verified public JSON is converted to typed evidence at the router boundary and
  domain validation remains outside React.
- Verified artifact pass decisions recompute content hashes and proof invariants;
  caller booleans have no passing route.
- Verified acceptance report staging precedes the immutable acceptance overlay
  and retry identity is stable.
- Verified archive validation occurs before member streams are opened and both
  corpus/migration use the same policy.
- Verified cancellation hooks reach file/archive/probe and per-case work, and
  task/run terminal status is committed through one guarded callback.
- Verified raw performance measurements and provenance survive persistence and
  report rendering.
- Verified external-path sanitization occurs before errors enter run evidence or
  exported reports.
- Verified frontend `dist` was rebuilt from the tested source and the parity route
  remains Settings-owned and lazy-loaded.

## Deferred Non-Blocking Minors

- Aggregate migration database/report work is still bounded per item rather than
  by one total row/byte budget.
- Migration policy remains a large module; the shared archive policy removes the
  security-critical duplication but not the broader maintainability debt.
- Generic non-string report mapping keys remain a theoretical redaction concern;
  normal persisted evidence rejects non-string keys before report generation.

## Remaining Human Gate

Use Settings -> `Mở đối chiếu parity` or `/settings/parity`. Select the unchanged
approved corpus, import the matched typed evidence bundle, resolve every required
`fail`/`blocked`, complete every required manual item, review both reports, and
explicitly accept that unchanged run. Until that happens, there is no Accepted
Parity Report and Phase 16 has no valid retirement input.
