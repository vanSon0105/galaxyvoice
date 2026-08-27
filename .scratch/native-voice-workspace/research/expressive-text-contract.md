# Galaxy Expressive Text Contract

## Decision

Galaxy stores display text, spoken text, timing, and engine instructions as
separate project fields. Authoring markup is compiled before synthesis; engine
adapters never parse editor markup themselves.

## Canonical markup

| Markup | Meaning |
| --- | --- |
| `[pause 500ms]`, `[pause 1.2s]` | A silent timeline span; values must be within 0-10 seconds. |
| `[rate 0.9]...[/rate]` | Speech rate; values must be within 0.5-1.5. |
| `[slow]...[/slow]`, `[fast]...[/fast]` | Relative rate shortcuts. |
| `[emphasis]...[/emphasis]` | Engine-neutral emphasis intent. |
| `[spell]...[/spell]` | Read each non-space character separately. |
| `[emotion vui]...[/emotion]` | Named emotion intent passed through adapter capabilities. |
| `[pronounce "Doctor Smith"]Dr. Smith[/pronounce]` | Keep display text but replace spoken text. |
| `[phoneme "..."]...[/phoneme]` | Engine phoneme hint; falls back to project pronunciation or display text. |

OmniVoice non-verbal events already exposed by Galaxy, such as `[laughter]`
and `[sigh]`, are accepted as engine events. Unknown tags remain visible and
produce a warning instead of silently deleting user text.

## Validation and degradation

- Unclosed tags, invalid rates, invalid pauses, and missing required arguments
  are render-blocking errors.
- Unsupported emphasis, emotion, rate, or phoneme capabilities become explicit
  warnings. Text is still rendered with the nearest deterministic fallback.
- Subtitle output uses display text. Synthesis uses spoken text and the compiled
  instruction. This prevents pronunciation overrides from changing captions.
- The compiler is deterministic and has Vietnamese, English, and Chinese
  fixtures. Preview and final render use the same compiler and cast selection.

## Pronunciation and terminology

Pronunciation rules are project data with a stable ID, source, replacement,
optional language scope, case-sensitivity flag, and whole-word flag. Longest
source wins first. They are stored in the Longform document and exported with
the project bundle; secrets are never part of this data.

Translation terminology is a separate concern: Dubbing glossaries map source
terms to target-language terms before expressive compilation. A translation
glossary must not be reused as pronunciation data because its replacement is
visible text, while pronunciation replacement is spoken text only.

## Import and export

- Plain text and Markdown preserve canonical tags as text.
- EPUB and PDF imports produce display text; project rules are applied after
  import during planning.
- Editable project payloads store both the original display text and an
  optional explicit spoken-text override.
- Exported SRT contains display text. Workspace manifests include compiled
  spans, expressive issues, and non-secret pronunciation rules in the project
  document.

## Longform preview behaviour

A line preview checkpoints the current project, selects the same compiled span
sequence used by final render, and runs it through the same voice/profile adapter. The
preview artifact is temporary and never replaces the project's final result.
