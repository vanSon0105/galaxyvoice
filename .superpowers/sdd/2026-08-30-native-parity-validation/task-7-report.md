# Task 7 Report: Decision Records, Ticket State, And Full Verification

## Status

DONE_WITH_CONCERNS

The automated Phase 15 implementation phase is closed. Native parity is not
accepted: issue 15 remains `ready-for-human` for the unchanged real-corpus run,
manual UAT, and explicit user acceptance.

## Commit Range

- Base: `00844a0d7b3b1b44bebcf08404b6473b55604120`
- Range for the implemented Task 7 state:
  `00844a0d7b3b1b44bebcf08404b6473b55604120..d5bcafe1a65281a3fa8bcee0d4370131eba4253e`
- `d23c1d1c78781aa38cd2653c937cbd4cd3a77b0b` -
  `test: remove local path from parity fixture`
- `d5bcafe1a65281a3fa8bcee0d4370131eba4253e` -
  `docs: record native parity validation gate`
- This report is committed separately after the implementation commits so it
  can record their exact hashes.

## Files Changed

- `docs/adr/0015-native-parity-validation-is-evidence-gated.md`
- `CONTEXT.md`
- `.scratch/native-voice-workspace/map.md`
- `.scratch/native-voice-workspace/issues/15-native-parity-validation.md`
- `.scratch/native-voice-workspace/issues/17-voicestudio-data-migration-policy.md`
- `.scratch/native-voice-workspace/research/voicestudio-parity-matrix.md`
- `tools/galaxy_ai_voice_subtitle_studio/tests/server/test_parity_api.py`
- `.superpowers/sdd/2026-08-30-native-parity-validation/task-7-report.md`

The test-only change replaces a tracked machine-specific redaction fixture path
with a generic Windows-user fixture; test behavior is unchanged. The frontend
production bundle was rebuilt, and the deterministic build produced no tracked
`frontend/dist` change.

## Decision And Ticket State

- ADR 0015 makes automated framework completion explicitly distinct from
  native parity acceptance.
- An Accepted Parity Report is the canonical JSON report from an unchanged
  completed run after all required automated checks pass, all required manual
  items have positive answers and notes, and the user records final acceptance.
- Accepted Parity Reports are the sole valid Phase 16 retirement input.
- VoiceStudio remains installed and available through its separate loopback
  boundary for comparison until the evidence gate passes and Phase 16 is
  explicitly approved.
- Issue 17 remains `resolved` because its migration policy and fixture-backed,
  read-only dry-run evidence passed. It does not imply a production import,
  native parity, or retirement readiness.
- Issue 15 is `ready-for-human`, not resolved. Its remaining actions are the
  approved external corpus, matched VoiceStudio artifacts and measurements,
  one unchanged native run, resolution of required failures/blocks, all manual
  UAT answers, report review, and explicit acceptance.
- After interruption, Settings command `Mở đối chiếu parity` reopens the
  persistent workflow at `/settings/parity`.
- Wall time, peak RAM, and peak VRAM are intentionally `blocked` wherever
  matched VoiceStudio reference evidence is unavailable. Missing evidence is
  never treated as zero or as a pass.

## Commands And Outcomes

### Matrix discovery

- `rg -l "Phase 15|native parity" docs .scratch`
  - Exit 0. The case-sensitive scan located the Phase 15 design/plan and related
    decision/ticket files.
- `rg -n -i "phase 15|native parity|parity matrix|capability matrix|accepted report|settings/parity|phase 16" docs .scratch`
  - Exit 0. The case-insensitive follow-up identified the actual matrix as
    `.scratch/native-voice-workspace/research/voicestudio-parity-matrix.md`.

### Backend

Working directory: `tools/galaxy_ai_voice_subtitle_studio`

- `python -m pytest tests -q`
  - Initial full run: exit 0; `716 passed, 2 skipped, 1 warning, 60 subtests
    passed in 59.73s`.
  - Final full run after replacing the tracked local-path fixture: exit 0;
    `716 passed, 2 skipped, 1 warning, 60 subtests passed in 53.48s`.
  - Exact warning on both runs: `StarletteDeprecationWarning: Using httpx with
    starlette.testclient is deprecated; install httpx2 instead.`
- `python -m pytest tests/parity/test_security.py::test_approved_path_rejects_symlink_escape tests/parity/test_security.py::test_directory_fingerprint_does_not_follow_symlinks -q -rs`
  - Exit 0; `2 skipped in 0.26s`.
  - Both skips are the expected Windows `WinError 1314` result: the current
    account does not hold symlink-creation privilege.

### Frontend

Working directory: `tools/galaxy_ai_voice_subtitle_studio/frontend`

- `npm test`
  - Exit 0; `25 passed` test files and `90 passed` tests in `8.35s`.
  - Vitest detail: transform `3.77s`, setup `8.40s`, import `8.15s`, tests
    `19.03s`, environment `53.70s`.
- `npm run lint`
  - Exit 0; `oxlint src` emitted no warnings or errors.
- `npm run typecheck`
  - Exit 0; `tsc --noEmit` emitted no diagnostics.
- `npm run build`
  - Exit 0; TypeScript and Vite production build completed.
  - Vite `8.2.1` transformed `128 modules` and reported `built in 314ms`.
  - The isolated parity chunk remained
    `ParityPage-DLl9ikLg.js`, `15.23 kB` (`3.88 kB` gzip).
  - No tracked `frontend/dist` file changed.

### Compile And Repository Gates

- `python -m compileall -q app`
  - Exit 0 with no output.
- `git diff --check`
  - Exit 0 with no whitespace errors.
  - Git emitted six LF-to-CRLF working-copy conversion warnings: issues 15 and
    17, the workspace map, the parity matrix, `CONTEXT.md`, and the parity API
    test. These are line-ending notices, not diff-check failures.
- `git status --short`
  - Before commits, showed exactly the six required documentation files plus
    the test fixture hygiene edit.
  - After the two implementation commits, no short-status entries remained;
    branch status was `main...origin/main [ahead 8]`.
- `git diff --cached --check`
  - Exit 0 before the documentation commit; no whitespace errors.
- `git show --check --stat --oneline d23c1d1` and
  `git show --check --stat --oneline d5bcafe`
  - Exit 0; both committed patches passed Git's whitespace check.

## Hygiene Evidence

- `git diff --name-only 79801f2..HEAD -- tools/galaxy_ai_voice_subtitle_studio/vendor/voicestudio`
  and the corresponding working-tree check against `HEAD`
  - Exit 0 with no output. The immutable vendor snapshot was not changed.
- Tracked-file scans for `parity-runs`, parity report output directories,
  selected corpus paths, copied databases, and common database/media
  extensions
  - Expected exit 1 with no matches. No generated parity report, selected
    corpus media, copied database, or media/database artifact is tracked.
- Tracked-file scans for the actual workspace path and the local Windows user
  path, in slash and backslash forms
  - The initial scan found one machine-specific path in the parity API
    redaction test. That finding produced `d23c1d1`.
  - The corrected scan returned the expected exit 1 with no matches. No
    machine-specific local absolute path remains tracked.
- High-confidence credential scan for private-key headers and common OpenAI,
  Google, GitHub, and Slack token forms
  - No private key or live credential was found. The only `sk-` shaped matches
    are the deliberate `sk-abcdefghijklmnopqrstuvwxyz` redaction canaries in
    reliability/runtime tests, where assertions prove the value is removed.
- API-key assignment scan
  - The first complex regex attempt exited 1 with a PowerShell
    `TerminatorExpectedAtEndOfString` parser error and produced no audit
    evidence.
  - The corrected scan exited 0 and found only README placeholders such as
    `sk-...`, empty defaults, field names, and runtime forwarding code. No
    API-key value is tracked.
- The Task 7 diff contains no report payload, source media, copied VoiceStudio
  content, credential value, or machine-local evidence.

## Self-Review

- Reviewed the complete `00844a0..d5bcafe` diff, not only the final commit.
- Confirmed ADR 0015, `CONTEXT.md`, the map, issues 15/17, and the actual parity
  matrix use the same evidence definition and do not claim acceptance.
- Confirmed issue 15's external/manual actions remain unchecked and its status
  is `ready-for-human`.
- Confirmed issue 17's resolution is explicitly limited to migration policy and
  read-only rehearsal evidence.
- Confirmed the `/settings/parity` recovery route and exact Settings action are
  documented.
- Left the matrix's capability rows unchanged because no new real-corpus or UAT
  evidence exists. Only the verified acceptance contract was updated.
- Confirmed no router, service, frontend source, generated bundle, or vendor
  implementation changed in Task 7.
- No unresolved Task 7 correctness, scope, licensing, or hygiene finding remains.

## Remaining Human Gate

Issue 15 remains deliberately open as `ready-for-human`. A user must run the
approved real corpus with unchanged checksums, supply matched VoiceStudio
reference artifacts and measurements, complete every required manual UAT item,
review the generated reports, and explicitly accept that same unchanged run.
Until then there is no Accepted Parity Report, Phase 16 has no valid input, and
VoiceStudio must remain available for comparison.

## Concerns

- Two Windows symlink security probes are skipped because this account lacks
  symlink privilege (`WinError 1314`); privilege-free junction coverage and the
  rest of the suite pass.
- The backend suite emits one existing third-party Starlette/httpx deprecation
  warning.
- Git emits non-failing LF-to-CRLF conversion notices under the current Windows
  configuration.
- The real-corpus/manual acceptance gate remains intentionally incomplete; no
  native parity or VoiceStudio retirement acceptance is claimed.
