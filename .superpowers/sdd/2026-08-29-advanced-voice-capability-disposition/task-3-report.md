# Task 3 Report: Settings Catalogue

## Status

Complete. Task 3 adds a read-only advanced capability catalogue to Settings.
No subagents were dispatched, and no files under `vendor/voicestudio` were
modified.

## Scope Delivered

- Added a typed client for `GET /api/extensions/capabilities`.
- Added a focused TanStack Query owned by the catalogue panel, independent of
  existing Settings loading and saving.
- Rendered explicit loading and error states plus text-and-colour labels for
  all four dispositions.
- Used native `details` and `summary` elements for keyboard-focusable detail
  disclosure of boundaries, constraints, and revisit triggers.
- Kept the catalogue read-only with no enable toggles or mutation controls.
- Added restrained responsive styling aligned with the existing Settings UI.
- Rebuilt and committed `frontend/dist/` for the desktop runtime.

## Files

- Created `tools/galaxy_ai_voice_subtitle_studio/frontend/src/api/extensions.ts`.
- Created
  `tools/galaxy_ai_voice_subtitle_studio/frontend/src/components/ExtensionCapabilitiesPanel.tsx`.
- Created
  `tools/galaxy_ai_voice_subtitle_studio/frontend/src/components/ExtensionCapabilitiesPanel.test.tsx`.
- Modified
  `tools/galaxy_ai_voice_subtitle_studio/frontend/src/pages/SettingsPage.tsx`.
- Modified `tools/galaxy_ai_voice_subtitle_studio/frontend/src/index.css`.
- Rebuilt `tools/galaxy_ai_voice_subtitle_studio/frontend/dist/`.

## TDD Evidence

### RED

After adding the component test file and a compile-only empty panel shell, the
focused command failed on all four intended user-visible behaviors:

```text
npm test -- src/components/ExtensionCapabilitiesPanel.test.tsx
```

Result: `1 failed` test file, `4 failed` tests. The failures reported the
missing loading status, missing error alert, missing disposition labels, and
missing native capability disclosure.

### GREEN

After implementing the API client and panel, the same command passed:

```text
Test Files  1 passed (1)
Tests       4 passed (4)
```

The focused Settings integration run also passed: `2` files and `5` tests.

## Supporting Verification

- `npm test`: `23` files and `70` tests passed.
- `npm run lint`: exited successfully with no findings.
- `npm run typecheck`: exited successfully.
- `npm run build`: TypeScript and Vite production build completed; `126`
  modules transformed.
- `git diff --check`: exited successfully.

## Self-Review

- **Requirements:** The panel consumes the approved response envelope and
  displays every catalogue entry with one of the four explicit disposition
  labels.
- **Isolation:** The panel owns `['extension-capabilities']`; its pending or
  error state does not gate editable Settings data or save mutations.
- **Accessibility:** The section has an associated heading, asynchronous states
  use `status` and `alert`, status meaning is visible as text, and each row uses
  native keyboard-focusable disclosure elements.
- **Read-only boundary:** The panel renders no checkbox, enable action, mutation,
  runtime probe, installation path, or model load.
- **Visual scope:** Styling reuses Galaxy tokens, existing section cards, compact
  rows, 3px status radii, and a single-column mobile layout.
- **Mutation check:** Tests fail for missing async states, missing or renamed
  disposition mappings, added checkbox controls, non-native disclosure markup,
  or omitted boundary/constraint/revisit details.
- **License and scope:** No VoiceStudio vendor files or unrelated Settings tests
  were changed.

## Concerns

None blocking. The production build refreshes hashed assets across lazy chunks,
which is expected for the repository's committed Vite output.
