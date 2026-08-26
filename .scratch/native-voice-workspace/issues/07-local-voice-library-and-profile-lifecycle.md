# Local Voice Library and profile lifecycle

Type: task
Status: resolved
Blocked by: 02, 03, 05

## Question

How do local system, imported, cloned, and designed voices share a stable
profile contract, consent record, preview, tags, favourites, portable export,
and selection in every Galaxy workflow?

## Done when

Clone and Design become guided Voice Library actions rather than competing top
level tabs, with engine capability degradation visible to the user.

## Answer

- `VoiceProfileRecord` is the Galaxy-owned stable contract for system,
  imported, cloned, and designed voices. It carries a revision, engine-neutral
  selection, language, tags, notes, favourite state, capabilities, consent,
  managed assets, and stable-sample state.
- Existing OmniVoice profiles are projected into the catalogue without moving
  their prompt files. Imported references and designed definitions are owned by
  the local Voice Library repository. System voices remain engine-owned and
  cannot be deleted or exported.
- Clone creation requires an explicit consent confirmation. The consent basis,
  statement, timestamp, and source provenance travel with portable exports and
  project snapshots; secrets are never part of the record.
- One query contract feeds Studio, Batch, Longform, and Dubbing. Each result
  publishes per-workflow compatibility, so unsupported system/reference/design
  voices remain visible but cannot be selected accidentally.
- A reference or generated take can be promoted as the locked stable sample.
  Library edits increment the voice revision, while an explicit project pin
  writes a revisioned snapshot and copies required reference/prompt assets.
- Preview audio is served only through a voice ID. Safe delete reports Studio,
  Batch, workspace, and pinned-project usage; deletion requires a second forced
  action when references exist.
- `.galaxyvoice` is a Galaxy-owned ZIP64 bundle with a versioned manifest,
  consent and optional reference/prompt assets. Import validates archive paths,
  format version, and a 512 MiB expanded-size ceiling before copying assets.
- The native Voice Library merges saved voices and local Gallery access into
  one operational surface with search, source/language/favourite filters,
  guided audio import, guided design, metadata editing, preview, pin, stable
  sample, bundle import/export, and safe delete.
