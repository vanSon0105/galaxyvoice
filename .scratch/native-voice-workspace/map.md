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
- Phase 15 automation collects and guards parity evidence; it does not accept
  native parity. Retirement has two separate gates: an Accepted Parity Report
  must exist as the sole Phase 16 input, and Phase 16 must separately and
  explicitly approve retirement. VoiceStudio remains installed and available
  for comparison until both gates pass.
- Interrupted parity work is reopened from Settings with `Mở đối chiếu parity`
  or directly at `/settings/parity`.
- Parity evidence enters through a typed JSON contract. Behavioral passes must
  be bound to Galaxy artifacts or Galaxy-owned migration dry-runs; performance
  evidence retains matched hardware/device provenance, and exported diagnostics
  redact approved external roots and absolute paths.

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
- [Workspace handoffs and project graph](issues/12-workspace-handoffs-and-project-graph.md) - One non-destructive Active Project graph records workflow ownership, linked/generated artifacts, supported open-in routes, and reversible pending/opened/returned handoffs across native voice and media workspaces.
- [Reliability, diagnostics, and accessibility](issues/13-reliability-diagnostics-and-accessibility.md) - Persistent redacted task diagnostics, recovery routes, runtime/device audits, disk guards, keyboard semantics, and route-level loading provide one observable and recoverable contract across native workspaces.
- [Advanced VoiceStudio capability disposition](issues/14-advanced-voice-capability-disposition.md) - A read-only Galaxy catalogue records live dictation, local transcript refinement, the compatible local audio API, and MCP bindings as extensions; remote backend as deferred; watermarking and visual lip-sync as optional adapters; and plugin marketplace as a non-goal. All eight capability behaviors remain disabled and unimplemented until their recorded constraints and revisit triggers are satisfied.
- [Native parity validation evidence gate](../../docs/adr/0015-native-parity-validation-is-evidence-gated.md) - Automated Phase 15 completion is not native parity acceptance. An Accepted Parity Report from an unchanged real-corpus run is the sole Phase 16 input, but retirement still requires separate explicit Phase 16 approval; VoiceStudio remains available until both gates pass.
- [Native parity validation against VoiceStudio](issues/15-native-parity-validation.md) - The automated framework is implemented, but the ticket remains `ready-for-human` for the unchanged external-corpus run, matched reference evidence, manual UAT, and explicit acceptance. Completing that evidence gate supplies Phase 16 input; it does not authorize retirement.
- [VoiceStudio legacy data migration policy](issues/17-voicestudio-data-migration-policy.md) - The Galaxy-owned read-only migration policy and fixture-backed dry-run are verified, so issue 17 is resolved without implying a production import or native parity acceptance.
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
