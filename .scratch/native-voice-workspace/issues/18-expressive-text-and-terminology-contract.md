# Expressive text, pronunciation, and terminology contract

Type: grilling
Status: resolved
Blocked by: 01, 02, 03

## Question

What engine-neutral text model should Galaxy use for pauses, emphasis, spelling,
rate, supported emotion tags, pronunciation overrides, phoneme fallbacks, and
project translation glossaries across Studio, Dubbing, Stories, and Audiobooks?

## Done when

The canonical markup, validation, language scope, import/export format, engine
capability degradation, and preview/test behaviour are specified with fixtures
for Vietnamese, English, and Chinese content.

## Answer

Galaxy now compiles canonical expressive markup into engine-neutral speech and
pause directives before synthesis. Display text, spoken text, rate, emotion,
emphasis, spelling, pronunciation, and timing remain separate fields. Invalid
or unclosed markup blocks rendering; unsupported engine capabilities produce a
warning and deterministic fallback instead of silently dropping text.

Project pronunciation rules have stable IDs and optional language scope. The
same compiler feeds source parsing, the structured editor, line preview, final
render, subtitles, and manifests, so a preview cannot disagree with export.
The complete contract and degradation rules are recorded in
`research/expressive-text-contract.md`.

## Verification

- `python -m pytest -q` (426 tests, 60 subtests)
- `npm run test -- --run` (55 tests)
- `npm run typecheck`
- `npm run lint`
- `npm run build`
