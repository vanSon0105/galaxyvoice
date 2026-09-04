import type { EditorCue, EditorMedia } from '../../api/editor'

export type EditorTrackKind = 'subtitle' | 'video' | 'audio'

export interface TimelineCue extends EditorCue {
  id: string
}

export interface TimelineMediaClip {
  id: string
  media: EditorMedia
  timeline_start_ms: number
  source_start_ms: number
  source_end_ms: number
  replacement?: {
    original_media: EditorMedia
    original_source_start_ms: number
    original_source_end_ms: number
    manifest_path: string
  }
}

interface TimelineTrackBase {
  id: string
  kind: EditorTrackKind
  name: string
  enabled: boolean
  locked: boolean
}

export interface SubtitleTrack extends TimelineTrackBase {
  kind: 'subtitle'
  cues: TimelineCue[]
}

export interface VideoTrack extends TimelineTrackBase {
  kind: 'video'
  clips: TimelineMediaClip[]
}

export interface AudioTrack extends TimelineTrackBase {
  kind: 'audio'
  clips: TimelineMediaClip[]
}

export type EditorTrack = SubtitleTrack | VideoTrack | AudioTrack

export interface TimelineSelection {
  trackId: string
  itemId: string
}

const makeId = (prefix: string) => `${prefix}:${crypto.randomUUID()}`

export function createTrack(kind: EditorTrackKind, ordinal = 1): EditorTrack {
  const base = {
    id: makeId(kind),
    kind,
    name: kind === 'subtitle' ? `Phụ đề ${ordinal}` : kind === 'video' ? `Video ${ordinal}` : `Audio ${ordinal}`,
    enabled: true,
    locked: false,
  }
  return kind === 'subtitle' ? { ...base, kind, cues: [] } : { ...base, kind, clips: [] }
}

export function createDefaultTracks(): EditorTrack[] {
  return [createTrack('subtitle'), createTrack('video'), createTrack('audio')]
}

export function cueWithId(cue: EditorCue): TimelineCue {
  return { ...cue, id: makeId('cue') }
}

export function mediaClip(media: EditorMedia, timelineStartMs = 0): TimelineMediaClip {
  return {
    id: makeId(media.kind),
    media,
    timeline_start_ms: Math.max(0, Math.round(timelineStartMs)),
    source_start_ms: 0,
    source_end_ms: Math.round(media.duration_seconds * 1000),
  }
}

export function replaceClipMedia(
  clip: TimelineMediaClip,
  media: EditorMedia,
  manifestPath: string,
): TimelineMediaClip {
  const original = clip.replacement ?? {
    original_media: clip.media,
    original_source_start_ms: clip.source_start_ms,
    original_source_end_ms: clip.source_end_ms,
    manifest_path: manifestPath,
  }
  const maximumEnd = Math.round(media.duration_seconds * 1000)
  return {
    ...clip,
    media,
    source_end_ms: Math.max(clip.source_start_ms, Math.min(clip.source_end_ms, maximumEnd)),
    replacement: {
      ...original,
      manifest_path: manifestPath,
    },
  }
}

export function restoreClipMedia(clip: TimelineMediaClip): TimelineMediaClip {
  if (!clip.replacement) return clip
  const { replacement, ...current } = clip
  const maximumEnd = Math.round(replacement.original_media.duration_seconds * 1000)
  return {
    ...current,
    media: replacement.original_media,
    source_start_ms: Math.min(replacement.original_source_start_ms, maximumEnd),
    source_end_ms: Math.min(replacement.original_source_end_ms, maximumEnd),
  }
}

export function clipDuration(clip: TimelineMediaClip): number {
  return Math.max(0, clip.source_end_ms - clip.source_start_ms)
}

export function clipEnd(clip: TimelineMediaClip): number {
  return clip.timeline_start_ms + clipDuration(clip)
}

export function editorDuration(tracks: EditorTrack[]): number {
  return tracks.reduce((maximum, track) => {
    if (track.kind === 'subtitle') {
      return Math.max(maximum, ...track.cues.map((cue) => cue.end_ms), 0)
    }
    return Math.max(maximum, ...track.clips.map(clipEnd), 0)
  }, 0)
}

export function reindexTrackCues(cues: TimelineCue[]): TimelineCue[] {
  return [...cues]
    .sort((left, right) => left.start_ms - right.start_ms || left.end_ms - right.end_ms)
    .map((cue, index) => ({ ...cue, index: index + 1 }))
}

export function clipsOverlap(left: TimelineMediaClip, right: TimelineMediaClip): boolean {
  return left.timeline_start_ms < clipEnd(right) && right.timeline_start_ms < clipEnd(left)
}

export function placeAudioClips(
  tracks: EditorTrack[],
  clips: TimelineMediaClip[],
  afterTrackId: string,
): { tracks: EditorTrack[]; placed: TimelineSelection[] } {
  const next = tracks.map((track) => track.kind === 'audio' ? { ...track, clips: [...track.clips] } : track)
  const laneStart = Math.max(0, next.findIndex((track) => track.id === afterTrackId) + 1)
  let insertionIndex = laneStart
  const placed: TimelineSelection[] = []

  for (const clip of [...clips].sort((left, right) => left.timeline_start_ms - right.timeline_start_ms)) {
    const lanes = next.slice(laneStart).findIndex((track) => track.kind !== 'audio')
    const laneEnd = lanes < 0 ? next.length : laneStart + lanes
    let target = next.slice(laneStart, laneEnd).find(
      (track): track is AudioTrack => track.kind === 'audio' && track.clips.every((current) => !clipsOverlap(current, clip)),
    )
    if (!target) {
      const ordinal = next.filter((track) => track.kind === 'audio').length + 1
      target = createTrack('audio', ordinal) as AudioTrack
      next.splice(insertionIndex, 0, target)
      insertionIndex += 1
    }
    target.clips.push(clip)
    target.clips.sort((left, right) => left.timeline_start_ms - right.timeline_start_ms)
    placed.push({ trackId: target.id, itemId: clip.id })
  }
  return { tracks: next, placed }
}

export function findTrack<T extends EditorTrackKind>(tracks: EditorTrack[], trackId: string, kind: T): Extract<EditorTrack, { kind: T }> | undefined {
  const track = tracks.find((candidate) => candidate.id === trackId)
  return track?.kind === kind ? track as Extract<EditorTrack, { kind: T }> : undefined
}
