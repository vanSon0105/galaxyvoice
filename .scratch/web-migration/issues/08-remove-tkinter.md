# Phase 8: Remove tkinter

Status: resolved

## Scope

- Make the pywebview shell the default desktop entrypoint.
- Remove all tkinter GUI modules and Tk-only tests.
- Keep a pure Python palette contract synchronized with frontend CSS tokens.
- Remove the obsolete tkwry profile runtime from VoiceStudio.
- Update the Windows launcher and project documentation.
- Keep CLI behavior and service APIs unchanged.

## Acceptance criteria

- `python run.py` launches the web shell.
- No module under `app/` imports tkinter.
- VoiceStudio no longer installs or probes tkwry.
- Python and frontend test suites pass.
- The built frontend remains committed.

## Comments

- 2026-08-21: User signed off on phases 0-7 and requested phase 8.
- 2026-08-21: Implemented the web-only desktop shell, removed tkinter/tkwry,
  synchronized palette tokens, updated launcher/docs, and replaced Tk tests.
- 2026-08-21: Independent standards/spec review found a combined `--web` + CLI
  regression and incomplete launcher version checks; both were fixed and covered.
- 2026-08-21: Final verification: Python, frontend, CLI generation, and server
  smoke tests passed; VoiceStudio vendored source remained unchanged.
