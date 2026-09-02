# VoiceStudio to Galaxy Native Parity Matrix

## Scope and method

This report inventories the user-facing capability surface of the vendored
VoiceStudio 0.4.2 snapshot and maps it to the Galaxy-owned Voice Workspace.
It is a behavioural reference only. No VoiceStudio source is to be copied,
patched, or imported into Galaxy.

Primary evidence used:

- Shipped-feature claims: `vendor/voicestudio/README.md:119-144` and
  `vendor/voicestudio/README.md:422-446`.
- Registered backend surface: `vendor/voicestudio/tests/fixtures/api_routes.txt`
  and its regression guard at
  `vendor/voicestudio/tests/test_api_route_inventory.py:1-89`.
- Mounted backend modules:
  `vendor/voicestudio/backend/main.py:1239-1274`.
- Reachable frontend modes:
  `vendor/voicestudio/frontend/src/App.jsx:1344-1461` and
  `vendor/voicestudio/frontend/src/store/uiSlice.ts:16-151`.
- Galaxy baseline routes: `frontend/src/App.tsx:47-63`,
  `app/server/routers/omnivoice.py:203-353`, and
  `app/server/routers/omnivoice_workspaces.py:94-575`.

The route snapshot contains more than 180 guarded routes. It is the exhaustive
endpoint-level backstop; the tables below intentionally group those routes into
user workflows rather than duplicating every endpoint.

## Status vocabulary

| Status | Meaning |
| --- | --- |
| Native | Galaxy already has the essential workflow and data ownership. |
| Partial | Galaxy has useful implementation but is missing required parity. |
| Missing | No Galaxy-owned user workflow exists yet. |
| Disposition | Must be consciously implemented, deferred behind an extension seam, or rejected. |
| Out | Explicitly outside this effort; it must not block VoiceStudio retirement. |

## Shell, projects, and shared runtime

| Capability | VoiceStudio evidence | Galaxy now | Native destination and acceptance fixture |
| --- | --- | --- | --- |
| First-run hardware and storage preflight | `/setup/preflight`, `/setup/recommendations`, `/setup/status` | Partial: per-tool installers and runtime status | Shared Settings setup. Fixture: clean Windows user profile with CPU-only and CUDA variants. |
| Model catalogue, install, cancel, remove | `/models`, `/models/install`, `/models/install/cancel`, `DELETE /models/{repo_id}` | Partial: separate OmniVoice and audio-separation installers | Shared capability registry with size, license, platform, health and install state. Fixture: interrupted and resumed model download. |
| Engine catalogue, selection and self-test | `/engines/*`, `/engines/select`, `/engines/{engine_id}/selftest` | Partial: hard-coded OmniVoice model/device controls | Engine-neutral adapters; no silent CPU fallback. Fixture: supported GPU, unsupported GPU and missing binary. |
| CPU/GPU job scheduling | Batch and dubbing queues; README `:432`, `:443` | Partial: shared OmniVoice worker and task runner, no global resource queue | One Galaxy job scheduler serializes GPU-heavy work and permits safe CPU concurrency. Fixture: simultaneous Batch, ASR and Dubbing jobs. |
| Progress, cancellation and event refresh | `/jobs/*`, `/tasks/*`, `/ws/events` | Partial: task events and cancel endpoints exist | Stable job/event contract with reconnect and terminal state replay. Fixture: close/reopen UI during a running job. |
| Crash recovery and resumable work | `/audiobook/resume/{job_id}`, `/longform/jobs`; README `:428`, `:446` | Partial: Longform resume only | Project-scoped checkpoints for every long job. Fixture: kill process halfway, reopen and resume without duplicate output. |
| Project list, rename, save and reopen | `/projects` CRUD and `studio_projects` table | Partial: Longform project repository exists | Versioned Galaxy Project Bundle shared by all six workspaces. Fixture: move bundle to another folder and relink one missing source. |
| Generation and export history | `/history`, starred takes, `/export/history` | Partial: workspace history exists; Studio has no full take UI | Project-aware take and export history with star, reuse, reveal and retention. Fixture: regenerate from old take after restart. |
| Diagnostics and error journal | `/system/diagnose`, recent errors, log streams, diagnostic bundle | Partial: Galaxy file logging/process inspection | Scrubbed diagnostic bundle, actionable runtime health and disk/VRAM checks. Fixture: missing ffmpeg/model/driver errors contain a remedy. |
| Responsive desktop operation | README `:438`, `:441`, `:446` | Partial: React/pywebview and event hub exist | No main-thread media/model work; large lists virtualized. Fixture: 45-minute SRT and 500-item batch stay interactive. |

## Studio

| Capability | VoiceStudio evidence | Galaxy now | Native destination and acceptance fixture |
| --- | --- | --- | --- |
| Text-to-speech generation | `/generate`, `/v1/audio/speech`, `/ws/tts` | Native basic generation | Studio owns one editable project/take surface. Fixture: Vietnamese and English short scripts. |
| Auto, clone and design methods | `uiSlice.ts:31-37`; `/design/describe`; profile generation routes | Native basic controls in `StudioPage.tsx:19-31` | Keep methods inside Studio, with engine capability badges and graceful degradation. |
| Reference-audio clone | README `:190`, `:430`; `/profiles` | Partial: audio, transcript and saved profile supported | Add trim/clean preview, transcript assistance, consent, reference validation and reusable profile. Fixture: clean WAV and noisy M4A. |
| Voice design | README `:191`, `:430`; `/design/describe`, `/archetypes` | Partial: gender, age, pitch, style, accent, dialect and custom instruction | Add natural-language describe, preview variants and save selected take. Fixture: deterministic mock engine returns three candidates. |
| Expressive controls and SSML-lite | README `:428`; pronunciation routes | Partial: speed/duration and OmniVoice instructions | Standard pause, emphasis, spell, rate and supported emotion tags; show unsupported controls. Fixture: mixed markup script. |
| Pronunciation dictionary | `/pronunciation` CRUD/import/export/test | Missing | Global and language-scoped dictionary shared by Studio/Longform/Dubbing. Fixture: Vietnamese name override and unsupported phoneme fallback. |
| Unlimited/chunked synthesis | README `:431`; streaming route | Partial: Batch and text splitting exist separately | Studio automatically chunks long text, preserves order and checkpoints. Fixture: 60-minute script with cancellation/resume. |
| Preview and global player | `VoicePreview`, `GlobalAudioPlayer`, `WaveformPlayer` frontend components | Missing in native Studio | Stable player with seek, waveform and output reveal. Fixture: swap among three takes without reloading media. |
| A/B comparison and take locking | README `:430`; `CompareModal`; profile lock/unlock routes | Missing | Compare two generated takes at matched loudness and promote one to output/profile. |
| Output formats and mastering | `/export`, effect presets | Partial: WAV/MP3 | Engine-neutral WAV/MP3 output, optional loudness normalization and metadata. Fixture: inspect sample rate, channels and loudness target. |

## Batch and queue

| Capability | VoiceStudio evidence | Galaxy now | Native destination and acceptance fixture |
| --- | --- | --- | --- |
| Batch TTS input | `/batch/enqueue`; `BatchQueue` | Partial: line or JSONL input in `BatchPage.tsx:19-30` | Table/import workflow with per-row text, voice, language, speed and output name. |
| Multi-language picker | README `:432`; `MultiLangPicker` | Partial: one global language plus JSONL overrides | Explicit per-item language and validation before queueing. Fixture: vi/en/zh rows. |
| Long-form split/combine | Existing Galaxy Batch controls | Native basic | Preserve as a quick Batch mode, while authored books use Longform. |
| Sequential GPU execution | README `:432`, `:443` | Missing globally | Use shared job scheduler and expose queued/running/retry states. Fixture: 50 mocked items with two injected failures. |
| Batch dubbing pipeline | README `:443`; `/batch/jobs/*` | Missing | Multiple media jobs run extract -> transcribe -> translate -> synth -> mix -> export, with per-stage checkpoints. |
| Partial success, retry and download | `/batch/jobs/{id}`, cancel/delete/download | Partial: manifest records completed items but UI lacks retry | Retry failed items without regenerating successful outputs; export a result index. |

## Local Voice Library

| Capability | VoiceStudio evidence | Galaxy now | Native destination and acceptance fixture |
| --- | --- | --- | --- |
| System/imported/cloned/designed categories | Profiles, Gallery, archetypes and personas routers | Partial: profiles and design archetypes are separate tabs | One local Voice Library with explicit source filters; Gallery merges into this surface. |
| Profile metadata and CRUD | `/profiles` CRUD, audio and usage routes | Partial: list/delete basic local profiles | Name, language, tags, notes, engine capability, preview, dates and safe delete usage report. |
| Consent and ownership record | `/profiles/{id}/consent` | Partial: Galaxy generation has a consent checkbox but profile data is limited | Persist consent state and reference provenance with clone profile. Fixture: clone cannot save without consent. |
| Stable/locked clone take | Profile lock/unlock routes | Missing | Promote a generated take/reference as the stable profile sample. |
| Local gallery search, tags and favourites | `/gallery/categories`, `/gallery/voices`, PATCH and preview | Partial: archetype search/filter only | Search all local voices, favourite, tag, preview and use in any picker. |
| Import local audio as a voice | `/gallery/upload`, save/to-profile | Partial: reference audio only during generation | Import wizard validates/cleans audio and creates a profile without first generating speech. |
| Portable persona bundle | `/personas/export`, import and inspect; README `:430` | Missing | Galaxy-owned versioned voice bundle with metadata, consent and optional reference assets. Never copy `.ovsvoice` schema blindly. |
| Voice available in every picker | README `:430`; `VoiceSelector` | Partial: profile selection exists in several native pages | One query contract feeds Studio, Batch, Longform and Dubbing. Fixture: newly saved profile appears everywhere through event invalidation. |
| Community and public marketplace | `/community/*`, `/marketplace/*` | Out by user decision | No network publishing/browsing. Local import/export remains supported. |

## Transcripts

| Capability | VoiceStudio evidence | Galaxy now | Native destination and acceptance fixture |
| --- | --- | --- | --- |
| Audio/video transcription | `/transcribe`, `/v1/audio/transcriptions` | Partial: existing video subtitle workflow is separate; native Transcripts accepts manual text only (`TranscriptsPage.tsx:14-17`) | Import media, choose language/model/device and create an editable transcript project. |
| ASR capability selection | `/engines/asr`, setup model catalogue; README `:434` | Partial: faster-whisper models in video workflow | Adapter-based ASR catalogue; parity is capability selection, not all 11 upstream engines. |
| Word and cue timestamps | Dubbing alignment implementation and README `:429` | Partial: cue timestamps only | Preserve word timing where available and derive editable cues without losing source timing. |
| Speaker diarization | README `:433`; diarization model in `backend/config/models.yaml:282-289` | Missing | Optional diarization stage with clear HF-token/license setup and manual correction. |
| Auto speaker clone extraction | README `:433` | Missing | Offer consent-aware reference candidates per detected speaker; never auto-save a profile. |
| Searchable transcript history | Transcriptions page and project/history routes | Partial: text search/history exists | Project list searches source name, text and speaker; opens full editor. |
| Transcript editing | `Transcriptions`, waveform timeline and segment rows | Missing in native Transcripts | Cue table + waveform/timeline editing, undo/redo and validation. Fixture: 1,000 cues remains responsive. |
| Transcript exports | Dubbing SRT/VTT/text endpoints | Partial: SRT export in video workflow | SRT, VTT and plain text, preserving edited timestamps and speaker labels. |
| Handoff to Dubbing/Longform | VoiceStudio launchpad/project handoffs | Partial: separate stores/routes | Handoff references one transcript artifact in the same Project Bundle; no destructive copy. |
| Recording/live capture | `/ws/transcribe`, capture routes | Missing | Deferred-capability seam shared with Dictation; not required for core file transcription unless disposition ticket promotes it. |

## Dubbing

| Capability | VoiceStudio evidence | Galaxy now | Native destination and acceptance fixture |
| --- | --- | --- | --- |
| Upload, local media and URL ingest | `/dub/upload`, `/dub/ingest-url` | Partial: other Galaxy tools pick local video; native Dubbing starts from pasted SRT | Dubbing starts with local media; URL ingest is optional and gated by yt-dlp availability. |
| Extract audio and vocal isolation | README `:431`; track/stem routes | Partial: Galaxy already has ffmpeg and audio separation as separate tools | Dubbing links or creates speech/background stems through shared media artifacts. |
| Transcribe and scene-aware split | `/dub/transcribe*`, README `:429` | Missing in native Dubbing | Use Transcript project, detect scene boundaries when useful, permit split/merge and cleanup. |
| Original/translated language tracks | `/dub/translate`, import SRT and parse subtitle text | Partial: translation provider stack exists in video subtitle workflow | Source and translated tracks remain separate, editable and checkpointed. External translations can be pasted/imported. |
| Project glossary | `/glossary/{project_id}` CRUD and auto-extract | Missing | Translation terminology list with source/target/note and preflight conflict checks. |
| Per-speaker voice assignment | README `:429`, `:433` | Partial: native SRT parser recognizes speaker labels and profiles | Assign default and per-speaker voices, preview mapping, preserve across retranscription. |
| Per-segment preview/regenerate/gain | Preview, segment audio, gain and export routes; README `:431` | Missing | Render/replace one cue, adjust gain, lock accepted cue and retain takes. |
| Streaming synthesis | README `:429`; `/ws/tts` | Missing | Optional incremental preview; final render remains checkpointed and deterministic. |
| Smart Fit duration | README `:429`; fit request types and rate-fit tool | Partial: Galaxy renderer force-fits WAV duration | Bounded, pitch-preserving rate fit with underrun/overrun policy and visible applied rate. |
| Audio lip-sync score and second-pass QC | README `:429`; `/dub/qc/{job_id}` | Missing | Score cue start/end/coverage; retry only failed cues and emit a quality report. Fixture: short, exact and overlong translated lines. |
| Mix and mux | `/dub/generate`, video/audio download routes | Missing in native Dubbing | Mix dub voice with retained background/original track controls and mux to source video. |
| Exports | Video, audio, MP3, SRT, VTT, segment and stem routes | Partial elsewhere | Selective outputs stay in the Project Bundle and preserve current Galaxy file forms where applicable. |
| History, abort and cleanup | `/dub/history`, `/dub/abort`, cleanup routes | Missing | Safe cancel/resume/delete; deleting history must not silently delete user exports. |

## Stories and Audiobooks

| Capability | VoiceStudio evidence | Galaxy now | Native destination and acceptance fixture |
| --- | --- | --- | --- |
| Shared long-form project | Stories and Audiobook frontend modes; shared longform renderer | Native foundation in `WorkspacesPage.tsx:45-76` | Keep one project model with Story and Audiobook authoring views. |
| Story script and multi-voice cast | README `:428`; `/stories/encode` | Partial: parse/edit/reorder/split and cast mapping exist | Add line preview, narrator semantics, per-line settings and validation. |
| EPUB/PDF/text import | `/audiobook/import`; README `:428` | Partial: text/EPUB import exists, PDF coverage must be verified | Import creates chapters and keeps source provenance. Fixture: text, EPUB and text-based PDF; scanned PDF reports OCR need. |
| Chapter planning and issue report | `/audiobook/plan` | Partial: Galaxy planner and issue list exist | Explicit chapter stats, unresolved voices, empty spans and unsupported markup before render. |
| Expressive per-span controls | README `:428` | Partial: pause, slow, fast, emphasis, spell and voice markup exist | Canonical markup shared with Studio pronunciation/prosody rules. |
| Sample/chapter preview | `/audiobook/preview` | Missing | Render selected line/chapter without committing full job. |
| Live per-chapter progress and stop | README `:428` | Partial: task-level progress/cancel | Chapter/span progress, remaining estimate and clean cancellation. |
| Crash-resume render | README `:428`; resume/jobs routes | Native foundation | Preserve and test signatures so edited spans invalidate only affected cached outputs. |
| Mastering | README `:428` | Partial: basic concatenation/format conversion | Two-pass loudness normalization and clipping checks with a master report. |
| Audiobook metadata and cover | `/audiobook/cover`; README `:428` | Partial: title, author, cover path and M4B controls exist | Chapter markers, title/author/cover and M4B validation. |
| WAV/MP3/M4B/stems export | README `:428`, `:431` | Partial to strong | Stable output layout plus selective chapter/stem export. |
| Cross-workspace conversion | VoiceStudio specs reference Story/Audiobook and Dub/Story handoffs | Missing as a stable data graph | Story <-> Audiobook and Dub -> Story reuse the same voice/cue/span records where representable. |

## Audio, UX, and reliability shared by all workspaces

| Capability | VoiceStudio evidence | Galaxy now | Native destination and acceptance fixture |
| --- | --- | --- | --- |
| Global media player and waveform | VoiceStudio global player/waveform components | Partial: editor/removal have isolated preview implementations | Shared media session with play/pause/seek, waveform cache and no full decode of long media. |
| Vocal separation and stems | README `:431` | Native separate Audio Separation workspace | Link separator outputs into Dubbing/Longform rather than duplicate processing. |
| Normalization/effects presets | `/engines/effects/presets`, `/clean-audio` | Partial | Small engine-neutral post chain: trim silence, gain, normalize, fades and selected preset. |
| Drag/drop and file pickers | README `:438` | Partial | Shared drop zone validates media type and never blocks the UI. |
| Undo/redo and shortcuts | README `:438`; keyboard cheat sheet | Partial in video timeline, missing in voice editors | Command history for transcript, dub and longform edits; common shortcut reference. |
| Session persistence | README `:438`; persisted UI slice | Partial | Reopen last project safely, but never auto-resume compute without confirmation. |
| Storage management | Settings storage/temp/model routes | Partial | Show model/cache/project sizes and clear only explicitly selected recoverable data. |
| HF token and restricted-network mirrors | Settings HF token/mirror routes; README `:167-173` | Partial: VoiceStudio-only credential screen | Shared secure configuration only for adapters that require it; capability remains optional. |

## Advanced capability dispositions

These are real shipped surfaces in the snapshot, but they do not belong in the
six core tabs automatically. ADR 0014 records the binding Galaxy disposition.
The read-only catalogue is implemented, but none of the capability behaviors
or optional adapters in this table are implemented or enabled by Phase 14.

| Capability | VoiceStudio evidence | Final Galaxy disposition |
| --- | --- | --- |
| Global dictation widget, hotkey and auto-paste | `/dictation/*`, `/ws/transcribe`; README `:442` | Extension `dictation.live`, disabled and not implemented. It must reuse Transcript ASR; revisit after a supported capture/hotkey contract exists and demand justifies the workflow. |
| Local LLM transcript refinement | Settings LLM providers/skills and dictation refinement routes | Extension `transcripts.local_refinement`, disabled and not implemented. Core transcription cannot depend on it; revisit after structured local-provider edits and quality fixtures preserve timing. |
| OpenAI-compatible local TTS/STT API | `/v1/audio/speech`, `/transcriptions`, `/voices` | Extension `api.openai_audio`, disabled and not implemented. It must wrap stable Galaxy contracts and remain loopback-only by default; revisit after contract and compatibility fixtures exist. |
| MCP client voice bindings | `/api/mcp/bindings`; README `:444` | Extension `mcp.voice`, disabled and not implemented. It must use the authenticated local audio API without direct engine access; revisit after that API is stable and a client workflow has acceptance fixtures. |
| Remote backend and bearer auth | README `:445`, system network/Tailscale routes | Deferred `backend.remote`, disabled and not implemented. Revisit only after approval of the threat model, ownership, authentication, TLS, secret-storage, and revocation designs. |
| Audio watermark detection/settings | `/watermark/status`, detect/settings; README `:437` | Optional adapter `audio.watermarking`, disabled and not implemented. Revisit after license/compatibility review and approval of provenance and verification contracts. |
| Visual lip-sync | README roadmap `:416-418` | Optional adapter `video.visual_lip_sync`, disabled and not implemented; it is distinct from Audio Lip-Sync. Revisit after model quality/runtime/license review and isolated GPU scheduling are approved. |
| Video logo overlay | README `:437` | Prefer the Galaxy video editor/export path, not Voice Workspace core. |
| Media tool acquisition and repair | `/media-tools/*` | Implement only for tools Galaxy actually owns, through shared Settings. |
| Public marketplace/community | `/marketplace/*`, `/community/*` | Out by user decision; local Voice Library import/export replaces it. |
| Plugin marketplace | README roadmap `:416-418` | Non-goal `marketplace.plugins`, disabled and not implemented. It has no protected execution seam; only a new product decision can reopen it. |
| Cross-platform installers, updates, single-instance and tray | README `:441` | Galaxy remains Windows-first for this effort; package/update lifecycle is a separate release concern, not Voice workflow parity. |
| Docker and Colab deployment | README installation and Colab sections | No native desktop parity requirement; retain engine/service boundaries that do not prevent future headless use. |
| Analytics, donate, enterprise, contact and changelog surfaces | Frontend App modes and Settings routes | Product chrome, not creative workflow parity. Galaxy may supply its own About/Privacy/Updates UX. |

## Roadmap claims that are not snapshot parity

`vendor/voicestudio/README.md:412-418` lists the following under **Up Next**,
not under shipped features:

- Wav2Lip visual lip-sync v2.
- Hosted demo.
- Plugin marketplace.
- Real-time voice changer.

They must not block native retirement. The Phase 14 catalogue records visual
lip-sync as a disabled, unimplemented optional adapter that still requires
independent quality, runtime, and license review. Shipped Smart Fit and Audio
Lip-Sync QC remain required Dubbing parity.

## Parity acceptance contract

The automated Phase 15 framework is an evidence collector and gate, not native
parity acceptance. Issue 17 is resolved by its read-only migration policy and
fixture-backed dry-run proof. Issue 15 remains `ready-for-human` for the real
corpus, manual UAT, and explicit acceptance. After interruption, the Settings
command `Mở đối chiếu parity` reopens the workflow at `/settings/parity`.

The public run accepts a versioned, discriminated evidence JSON bundle. Missing
evidence stays `blocked`; a generic caller-supplied pass flag is never enough.
Repository behaviors are executed by Galaxy-owned ProjectGraph and Longform
probes in isolated sandboxes, migration behaviors execute Galaxy's read-only
dry-run, and performance comparisons retain each sample's app version, matched
hardware identity, resolved device, and raw native/reference values.

Retirement has two separate gates: an Accepted Parity Report must exist as the
sole Phase 16 input, and Phase 16 must separately and explicitly approve
retirement. VoiceStudio remains installed and available for comparison until
both gates pass. It may be retired only when all of the following are true:

1. Every row marked Native/Partial/Missing has a final disposition in its owning
   ticket and all required rows are implemented.
2. The same fixed media corpus has matched VoiceStudio reference artifacts and
   runs through native Galaxy while the reference remains available:
   short/long TTS, noisy clone audio, 50-item batch, 45-minute multilingual
   video, two-speaker dub, story script, EPUB and PDF audiobook.
3. Output assertions cover duration, cue count/order, language, speaker mapping,
   file formats, stream presence, loudness, project reopen and checkpoint resume.
4. Performance assertions cover UI responsiveness, peak RAM/VRAM, cancellation
   latency and recovery after forced shutdown.
5. Project Bundles reopen after moving directories, and missing external media
   offers relink rather than losing edits.
6. No native workflow imports or executes VoiceStudio application code.
7. Every required manual UAT item has a positive answer and note, and the user
   explicitly accepts the unchanged completed run.
8. The canonical JSON Accepted Parity Report from that run is supplied as the
   sole Phase 16 input. Automated suites, screenshots, verbal approval, and
   unaccepted or changed reports do not satisfy the retirement gate.
9. Phase 16 reviews that Accepted Parity Report and explicitly approves
   VoiceStudio retirement. Supplying the report does not itself grant that
   approval.

Any required `fail`, `blocked`, or `manual_pending` result prevents acceptance.
Wall time, peak RAM, and peak VRAM remain intentionally `blocked` when matched
VoiceStudio reference evidence is unavailable; missing values are never
treated as zero or as a pass.

## Resulting delivery ownership

| Native area | Owns |
| --- | --- |
| Shared foundation | Project Bundle, capability registry, model store, job scheduler, events, diagnostics, media player and audio post chain. |
| Studio | Single-script generation, clone/design entry, expressive controls, preview, comparison and takes. |
| Batch | Multi-item TTS and multi-media pipeline queue. |
| Voice Library | Local voice/profile lifecycle, previews, tags, consent and portable bundles. |
| Transcripts | ASR, timing, diarization, editing, search and subtitle/text exports. |
| Dubbing | Translation, speaker voices, segment generation, Smart Fit, QC, mixing and video/subtitle/audio export. |
| Truyen & Sach noi | Story and audiobook authoring over one long-form project/renderer. |
| Settings/extensions | Model/runtime setup plus the read-only advanced-capability catalogue. Future dictation, API/MCP, remote, provenance, and visual adapters remain disabled and unimplemented until their recorded triggers and constraints are satisfied. |

This ownership map is the binding input to the remaining wayfinding tickets.
