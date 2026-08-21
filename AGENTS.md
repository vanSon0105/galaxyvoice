## Agent skills

### Issue tracker

Issues are tracked as local markdown files under `.scratch/<feature>/`; external PRs are not a triage surface. See `docs/agents/issue-tracker.md`.

### Triage labels

Using the default five-label vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout: root `CONTEXT.md` plus ADRs in `docs/adr/`. See `docs/agents/domain.md`.

## Galaxy Studio architecture

- The desktop UI is the React build under `tools/galaxy_ai_voice_subtitle_studio/frontend/`, hosted by FastAPI and opened with pywebview. Do not add tkinter UI modules back to `app/`.
- Keep HTTP routers thin. Workflow behavior belongs in the existing domain service modules so CLI and web calls share the same implementation.
- Commit `frontend/dist/` after frontend changes because the desktop app serves that production build directly.

## VoiceStudio license boundary

- `tools/galaxy_ai_voice_subtitle_studio/vendor/voicestudio/` is an immutable AGPL-3.0-only snapshot with its upstream license files.
- Galaxy launches that snapshot as a separate loopback service and embeds its published frontend by URL. Do not copy, patch, or import its application source into Galaxy modules without an explicit license review.
- Galaxy-owned React and Python code must remain independently implemented. Integration with VoiceStudio goes through its local HTTP boundary.
