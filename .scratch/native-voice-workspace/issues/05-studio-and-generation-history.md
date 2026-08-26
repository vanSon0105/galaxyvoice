# Native Studio and generation history

Type: task
Status: resolved
Blocked by: 02, 03, 04

## Question

Which Studio controls and supporting records are required for single-script
generation: voice source selection, language, pronunciation/prosody,
speed/format, preview, A/B comparison, history, rerun, output export, and
handoff into a Project Bundle?

## Done when

The Galaxy Studio workflow has an acceptance contract independent of any one
TTS engine and feeds the Voice Library and downstream workflows.

## Answer

- `StudioGenerationSpec` owns engine-neutral text, voice source, language,
  speed, requested formats, project identity, and an explicit engine-options
  extension. It never stores credentials.
- A voice source is `auto`, `profile`, `reference`, or `design`. Engine adapters
  map those sources to their native modes and reject unsupported requests.
- Each successful generation creates an immutable `StudioTake` with stable ID,
  generation-run link, artifact paths, engine identity, effective spec,
  warnings, and rerun lineage. Star and Primary annotations are stored outside
  that immutable record.
- Take history is persisted independently of the in-memory task registry and
  remains available after restarting Galaxy.
- Audio preview and export resolve through a take ID. The server only serves
  WAV/MP3 files recorded inside that take's generated project directory.
- A project can have at most one Primary Studio Take. Replacing it is atomic;
  starred and comparison selections do not alter the primary take.
- Rerun creates a new take from the saved spec and links it with `rerun_of`.
- The handoff payload exposes the selected generation run, primary audio, and
  voice profile reference for the future Galaxy Project Bundle implementation.
- Expressive text remains raw text plus an instruction field until issue 18
  defines canonical markup. History and adapters therefore do not depend on a
  temporary parser.
