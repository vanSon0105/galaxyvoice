# Map: Native Galaxy Voice Workspace

## Destination

Replace the embedded VoiceStudio experience gradually with a Galaxy-owned Voice
Workspace that covers the user-facing VoiceStudio workflows through Galaxy's
own engines and data model. VoiceStudio remains installed and usable as the
reference implementation until native parity is verified and retirement is
explicitly approved.

## Notes

- Implementation is independent: do not copy, import, or modify
  `vendor/voicestudio/`; use it only as a behaviour and acceptance reference.
- Parity means workflows, project data, controls, outputs, and recoverability;
  it does not require reproducing every upstream TTS/ASR engine.
- Galaxy Project Bundles are portable, versioned, and self-contained. They are
  the data boundary shared by Batch, Transcripts, Longform, and Dubbing.
- Voice Library is local-first. System, imported, cloned, and designed voices
  are separate local sources; community sharing is not part of this effort.
- Dubbing includes audio lip-sync quality controls, not visual face/mouth
  synthesis. A future visual lip-sync engine must be a separately licensed,
  optional adapter.
- The inventory ticket is the authoritative check that no VoiceStudio
  user-facing workflow is silently omitted.

## Decisions so far

- [VoiceStudio parity inventory and acceptance matrix](issues/01-voice-studio-parity-inventory.md) - The source-backed matrix assigns every shipped workflow to a native workspace, shared foundation, explicit extension disposition, or explicit non-goal; Wav2Lip remains roadmap-only.
- [Project Bundle and asset contract](issues/02-project-bundle-and-asset-contract.md) - Galaxy uses a directory-based Active Project with a versioned root index, independently versioned Workflow Documents, hybrid managed/linked assets, Pinned Voice Snapshots, staged migration, verified relink, and validated `.galaxybundle` transfer archives.
- [Native runtime, model, and job orchestration](issues/03-native-runtime-and-job-orchestration.md) - Galaxy owns lazy capability and model adapters, persistent cooperative jobs, structured preflight, and fair named-resource scheduling; engine internals remain behind adapters and GPU-heavy workflows share one accelerator queue.
- [Native Voice Workspace information architecture](issues/04-native-voice-navigation-and-design-system.md) - Galaxy exposes one top-level Voice workspace with six canonical `/voice/*` surfaces, one shared project context, Gallery inside Voice Library, reusable async states, legacy route redirects, and VoiceStudio isolated behind an explicit comparison action until cutover.
- [Native Studio and generation history](issues/05-studio-and-generation-history.md) - Studio records engine-neutral immutable takes with persistent history, secure preview/export, rerun lineage, A/B comparison, and one atomic Primary Studio Take per Active Project; expressive text remains parser-independent until issue 18 resolves its markup contract.
- [Batch and queue workflow](issues/06-batch-and-queue-workflow.md) - Batch imports plain text, long-form paragraphs, or JSONL into editable per-item jobs; it checkpoints partial success, shares the resource scheduler, supports pause/cancel/resume/failed-only retry, combines successful audio, and writes a portable relative-path manifest beside a private local resume sidecar.
- [Local Voice Library and profile lifecycle](issues/07-local-voice-library-and-profile-lifecycle.md) - One Galaxy-owned profile contract unifies system, imported, cloned, and designed voices with consent, stable samples, tags/favourites, compatibility-aware pickers, safe usage deletion, project pins, and validated `.galaxyvoice` bundles.
- [Transcripts, alignment, and speaker workflow](issues/08-transcripts-and-speaker-workflow.md) - Transcripts owns project-scoped documents with word-level timestamps, optional pyannote diarization, consent-aware speaker samples, virtualized cue editing (split/merge/move/delete), optimistic revision locking, multi-format export (SRT/VTT/TXT), and recorded handoffs to Dubbing or Longform.
- [Dubbing Smart Fit and quality control](issues/09-dubbing-smart-fit-and-quality-control.md) - Dubbing owns revisioned source/translation/cast checkpoints, virtualized segment editing, resumable synthesis, bounded pitch-preserving Smart Fit, deterministic two-pass QC, source/stem mix or sidechain ducking, and final audio/video/SRT preview and export.
- [Longform Stories and Audiobooks](issues/10-longform-stories-and-audiobooks.md) - One revisioned Longform Project serves story dialogue and chaptered books with import, cast, expressive line editing, cached previews, resumable rendering, mastering, and WAV/MP3/M4B exports.
- [Audio postproduction and export contract](issues/11-audio-postproduction-and-export-contract.md) - One Galaxy-owned post chain serves Studio, Batch, Dubbing, and Longform with waveform caching, source/stem selection, trim and gain automation, loudness mastering, metadata, multi-format export, and project-owned provenance manifests.
- [Expressive text and terminology contract](issues/18-expressive-text-and-terminology-contract.md) - Galaxy compiles canonical markup into separate display, spoken, timing, and engine-instruction fields with language-scoped pronunciation and explicit capability degradation.
- Native workflow parity over engine parity - Galaxy reimplements its own
  workflows while VoiceStudio remains a comparison reference until the final
  retirement gate.
- Portable project ownership - Galaxy Project Bundles own workflow state and
  outputs rather than relying on one shared runtime database.
- Local-first voice ownership - Voice Library has no community gallery or
  marketplace requirement in this effort.
- Revisioned voice selection - workflows select through one library contract;
  project pins isolate active work from later library edits.
- Dubbing quality boundary - timing/fit/QC is in scope; visual lip-sync is a
  separately evaluated optional capability.

## Not yet specified

- The exact model/engine adapters selected for speaker diarization, forced
  alignment, and visual lip-sync if it is later approved.
- Whether advanced auxiliary capabilities (global dictation, local OpenAI/MCP
  compatibility, provenance watermarking, remote backend) become first-class
  Galaxy tools after the core workspace is complete. They remain in the
  inventory and cannot disappear by accident.

## Out of scope

- Copying, modifying, or embedding VoiceStudio application source in Galaxy.
- A public voice marketplace, community publishing, or hosted Galaxy service.

## Planned delivery sequence

1. Inventory and specify parity before implementation.
2. Establish shared project, asset, job, and model-management foundations.
3. Deliver the six native workspace surfaces and their cross-workspace handoffs.
4. Add reliability, migration, and parity verification while VoiceStudio is
   still available for comparison.
5. Retire VoiceStudio only after the verified cutover gate passes.
