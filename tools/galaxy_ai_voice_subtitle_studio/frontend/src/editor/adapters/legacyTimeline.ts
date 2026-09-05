import type { EditorMedia } from '../../api/editor'
import { v5 as uuidV5 } from 'uuid'
import type {
  EditorTrack as LegacyTrack,
  TimelineMediaClip as LegacyMediaClip,
} from '../../components/timeline/tracks'
import {
  assertValidEditorProject,
  createEditorProject,
  frameRateFromNumber,
  mediaTimeToMilliseconds,
  mediaTimeToSeconds,
  millisecondsToMediaTime,
  secondsToMediaTime,
  StableIdSchema,
  type AssetFingerprint,
  type AssetOwnership,
  type AudioTrack,
  type EditorProject,
  type MainVideoTrack,
  type MediaClip,
  type MediaSource,
  type OverlayTrack,
  type OverlayVideoTrack,
  type SubtitleTrack,
} from '../core'

export interface LegacyTimelineMigrationOptions {
  project_id: string
  project_name?: string
  now?: string
  resolve_asset: (media: EditorMedia) => {
    asset_id: string
    ownership: AssetOwnership
    fingerprint: AssetFingerprint
  }
  resolve_manifest_asset_id?: (manifestPath: string) => string
}

export interface LegacyTimelineProjectionOptions {
  resolve_source_url: (source: MediaSource) => string
  resolve_manifest_path?: (manifestAssetId: string) => string
}

const LEGACY_RECORD_NAMESPACE = 'c3e6ad74-5f7f-4ed8-b64a-741ec7bf793c'

function stableRecordId(projectId: string, kind: string, legacyId: string): string {
  const existing = StableIdSchema.safeParse(legacyId)
  if (existing.success) return existing.data
  return uuidV5(`${StableIdSchema.parse(projectId)}:${kind}:${legacyId}`, LEGACY_RECORD_NAMESPACE)
}

function sourcesConflict(left: MediaSource, right: MediaSource): boolean {
  return left.kind !== right.kind
    || left.ownership !== right.ownership
    || left.fingerprint.algorithm !== right.fingerprint.algorithm
    || left.fingerprint.value !== right.fingerprint.value
    || left.fingerprint.byte_size !== right.fingerprint.byte_size
    || left.duration !== right.duration
    || left.width !== right.width
    || left.height !== right.height
    || left.frame_rate?.numerator !== right.frame_rate?.numerator
    || left.frame_rate?.denominator !== right.frame_rate?.denominator
    || left.has_audio !== right.has_audio
}

function sourceFromLegacy(
  media: EditorMedia,
  resolution: ReturnType<LegacyTimelineMigrationOptions['resolve_asset']>,
): MediaSource {
  return {
    asset_id: resolution.asset_id,
    kind: media.kind,
    name: media.name,
    ownership: resolution.ownership,
    path_hint: media.path,
    fingerprint: resolution.fingerprint,
    provenance: { origin: 'legacy', derived_from: [] },
    duration: secondsToMediaTime(media.duration_seconds),
    width: media.width,
    height: media.height,
    frame_rate: media.kind === 'video' && media.fps > 0 ? frameRateFromNumber(media.fps) : null,
    has_audio: media.has_audio,
  }
}

function clipFromLegacy(
  clip: LegacyMediaClip,
  projectId: string,
  addSource: (media: EditorMedia) => MediaSource,
  recordDerivation: (assetId: string, parentId: string) => void,
  resolveManifestAssetId?: (manifestPath: string) => string,
): MediaClip {
  const source = addSource(clip.media)
  const original = clip.replacement ? addSource(clip.replacement.original_media) : undefined
  if (original) recordDerivation(source.asset_id, original.asset_id)
  if (clip.replacement && !resolveManifestAssetId) {
    throw new Error('Legacy replacement migration requires a manifest asset resolver.')
  }
  return {
    id: stableRecordId(projectId, 'clip', clip.id),
    kind: 'media',
    asset_id: source.asset_id,
    timeline_start: millisecondsToMediaTime(clip.timeline_start_ms),
    source_in: millisecondsToMediaTime(clip.source_start_ms),
    source_out: millisecondsToMediaTime(clip.source_end_ms),
    enabled: true,
    gain: 1,
    ...(clip.replacement ? {
      replacement: {
        original_asset_id: original!.asset_id,
        original_source_in: millisecondsToMediaTime(clip.replacement.original_source_start_ms),
        original_source_out: millisecondsToMediaTime(clip.replacement.original_source_end_ms),
        manifest_asset_id: resolveManifestAssetId!(clip.replacement.manifest_path),
      },
    } : {}),
  }
}

export function migrateLegacyTimeline(
  tracks: LegacyTrack[],
  options: LegacyTimelineMigrationOptions,
): EditorProject {
  const videoTracks = tracks.filter((track) => track.kind === 'video')
  const legacyMain = videoTracks.at(-1)
  const legacyMainIndex = legacyMain ? tracks.findIndex((track) => track.id === legacyMain.id) : -1
  const unsupportedVisualTrack = legacyMainIndex >= 0
    ? tracks.slice(legacyMainIndex + 1).find((track) => track.kind !== 'audio')
    : undefined
  if (unsupportedVisualTrack) {
    throw new Error(`Legacy visual track cannot be placed below the main video: ${unsupportedVisualTrack.id}.`)
  }
  const project = createEditorProject({
    project_id: options.project_id,
    name: options.project_name,
    now: options.now,
  })
  const sources = new Map<string, MediaSource>()
  const sourceIds = new Map<string, string>()
  const addSource = (media: EditorMedia): MediaSource => {
    const existingAssetId = sourceIds.get(media.source_id)
    const existing = existingAssetId ? sources.get(existingAssetId) : undefined
    if (existing) {
      const candidate = sourceFromLegacy(media, {
        asset_id: existing.asset_id,
        ownership: existing.ownership,
        fingerprint: existing.fingerprint,
      })
      if (existing.path_hint !== media.path || sourcesConflict(existing, candidate)) {
        throw new Error(`Legacy source id points to conflicting media: ${media.source_id}.`)
      }
      return existing
    }
    const resolution = options.resolve_asset(media)
    const source = sourceFromLegacy(media, {
      ...resolution,
      asset_id: StableIdSchema.parse(resolution.asset_id),
    })
    const duplicate = sources.get(source.asset_id)
    if (duplicate && sourcesConflict(duplicate, source)) {
      throw new Error(`Resolved asset id has conflicting fingerprint or media metadata: ${source.asset_id}.`)
    }
    sourceIds.set(media.source_id, source.asset_id)
    if (!duplicate) sources.set(source.asset_id, source)
    return duplicate ?? source
  }
  const recordDerivation = (assetId: string, parentId: string) => {
    const source = sources.get(assetId)
    if (!source || source.provenance.derived_from.includes(parentId)) return
    sources.set(assetId, {
      ...source,
      provenance: { ...source.provenance, derived_from: [...source.provenance.derived_from, parentId] },
    })
  }
  const mediaClips = (track: Exclude<LegacyTrack, { kind: 'subtitle' }>) => (
    track.clips.map((clip) => clipFromLegacy(
      clip,
      project.project_id,
      addSource,
      recordDerivation,
      options.resolve_manifest_asset_id,
    ))
  )
  const overlays: OverlayTrack[] = []
  const audio: AudioTrack[] = []
  let main: MainVideoTrack = project.timeline.main

  for (const track of tracks) {
    if (track.kind === 'subtitle') {
      const subtitleTrack: SubtitleTrack = {
        id: stableRecordId(project.project_id, 'track', track.id),
        kind: 'subtitle',
        role: 'overlay',
        name: track.name,
        enabled: track.enabled,
        locked: track.locked,
        clips: track.cues.map((cue) => ({
          id: stableRecordId(project.project_id, 'cue', cue.id),
          kind: 'subtitle',
          start: millisecondsToMediaTime(cue.start_ms),
          end: millisecondsToMediaTime(cue.end_ms),
          text: cue.text,
        })),
      }
      overlays.push(subtitleTrack)
      continue
    }
    if (track.kind === 'audio') {
      audio.push({
        id: stableRecordId(project.project_id, 'track', track.id),
        kind: 'audio',
        role: 'audio',
        name: track.name,
        enabled: track.enabled,
        locked: track.locked,
        clips: mediaClips(track),
      })
      continue
    }
    if (track.id === legacyMain?.id) {
      main = {
        id: stableRecordId(project.project_id, 'track', track.id),
        kind: 'video',
        role: 'main',
        name: track.name,
        enabled: track.enabled,
        locked: track.locked,
        clips: mediaClips(track),
      }
      continue
    }
    const overlay: OverlayVideoTrack = {
      id: stableRecordId(project.project_id, 'track', track.id),
      kind: 'video',
      role: 'overlay',
      name: track.name,
      enabled: track.enabled,
      locked: track.locked,
      clips: mediaClips(track),
    }
    overlays.push(overlay)
  }

  const mainSource = main.clips[0] ? sources.get(main.clips[0].asset_id) : undefined
  const migrated: EditorProject = {
    ...project,
    canvas: mainSource?.kind === 'video' ? {
      ...project.canvas,
      width: mainSource.width || project.canvas.width,
      height: mainSource.height || project.canvas.height,
      frame_rate: mainSource.frame_rate ?? project.canvas.frame_rate,
    } : project.canvas,
    sources: [...sources.values()],
    timeline: { overlays, main, audio },
  }
  assertValidEditorProject(migrated)
  return migrated
}

function legacyMedia(source: MediaSource, options: LegacyTimelineProjectionOptions): EditorMedia {
  return {
    source_id: source.asset_id,
    kind: source.kind,
    name: source.name,
    path: source.path_hint,
    url: options.resolve_source_url(source),
    duration_seconds: mediaTimeToSeconds(source.duration),
    width: source.width,
    height: source.height,
    fps: source.frame_rate ? source.frame_rate.numerator / source.frame_rate.denominator : 0,
    has_audio: source.has_audio,
  }
}

function legacyClip(
  clip: MediaClip,
  sourceById: ReadonlyMap<string, MediaSource>,
  options: LegacyTimelineProjectionOptions,
): LegacyMediaClip {
  const source = sourceById.get(clip.asset_id)
  if (!source) throw new Error(`Clip asset does not exist: ${clip.asset_id}.`)
  const original = clip.replacement ? sourceById.get(clip.replacement.original_asset_id) : undefined
  if (clip.replacement && !original) throw new Error(`Replacement asset does not exist: ${clip.replacement.original_asset_id}.`)
  if (clip.replacement && !options.resolve_manifest_path) {
    throw new Error('Legacy replacement projection requires a manifest path resolver.')
  }
  return {
    id: clip.id,
    media: legacyMedia(source, options),
    timeline_start_ms: Math.round(mediaTimeToMilliseconds(clip.timeline_start)),
    source_start_ms: Math.round(mediaTimeToMilliseconds(clip.source_in)),
    source_end_ms: Math.round(mediaTimeToMilliseconds(clip.source_out)),
    ...(clip.replacement && original ? {
      replacement: {
        original_media: legacyMedia(original, options),
        original_source_start_ms: Math.round(mediaTimeToMilliseconds(clip.replacement.original_source_in)),
        original_source_end_ms: Math.round(mediaTimeToMilliseconds(clip.replacement.original_source_out)),
        manifest_path: options.resolve_manifest_path!(clip.replacement.manifest_asset_id),
      },
    } : {}),
  }
}

export function projectToLegacyTimeline(
  project: EditorProject,
  options: LegacyTimelineProjectionOptions,
): LegacyTrack[] {
  assertValidEditorProject(project)
  const sourceById = new Map(project.sources.map((source) => [source.asset_id, source]))
  const overlays: LegacyTrack[] = project.timeline.overlays.map((track) => track.kind === 'subtitle' ? {
    id: track.id,
    kind: 'subtitle',
    name: track.name,
    enabled: track.enabled,
    locked: track.locked,
    cues: track.clips.map((cue, index) => ({
      id: cue.id,
      index: index + 1,
      start_ms: Math.round(mediaTimeToMilliseconds(cue.start)),
      end_ms: Math.round(mediaTimeToMilliseconds(cue.end)),
      text: cue.text,
    })),
  } : {
    id: track.id,
    kind: 'video',
    name: track.name,
    enabled: track.enabled,
    locked: track.locked,
    clips: track.clips.map((clip) => legacyClip(clip, sourceById, options)),
  })
  const main: LegacyTrack = {
    id: project.timeline.main.id,
    kind: 'video',
    name: project.timeline.main.name,
    enabled: project.timeline.main.enabled,
    locked: project.timeline.main.locked,
    clips: project.timeline.main.clips.map((clip) => legacyClip(clip, sourceById, options)),
  }
  const audio: LegacyTrack[] = project.timeline.audio.map((track) => ({
    id: track.id,
    kind: 'audio',
    name: track.name,
    enabled: track.enabled,
    locked: track.locked,
    clips: track.clips.map((clip) => legacyClip(clip, sourceById, options)),
  }))
  return [...overlays, main, ...audio]
}
