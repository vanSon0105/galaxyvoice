import { z } from 'zod'

import { FrameRateSchema, MediaTimeSchema, frameRate, mediaTime } from './time'

export const EDITOR_PROJECT_SCHEMA_VERSION = 1 as const
export const EDITOR_WORKFLOW_TYPE = 'video-editor' as const

const COMPACT_UUID = /^[0-9a-f]{32}$/i
const CANONICAL_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

export const StableIdSchema = z.string().trim().transform((value, context) => {
  const expanded = COMPACT_UUID.test(value)
    ? `${value.slice(0, 8)}-${value.slice(8, 12)}-${value.slice(12, 16)}-${value.slice(16, 20)}-${value.slice(20)}`
    : value
  if (!CANONICAL_UUID.test(expanded)) {
    context.addIssue({ code: 'custom', message: 'Record identity must be a UUID.' })
    return z.NEVER
  }
  return expanded.toLowerCase()
})
const NonEmptyTextSchema = z.string().trim().min(1)
const NonNegativeMediaTimeSchema = MediaTimeSchema.refine((value) => value >= 0, 'Time cannot be negative.')

export const AssetOwnershipSchema = z.enum(['managed', 'linked'])
export type AssetOwnership = z.infer<typeof AssetOwnershipSchema>

export const AssetFingerprintSchema = z.object({
  algorithm: z.literal('sha256'),
  value: z.string().regex(/^[0-9a-f]{64}$/i, 'Fingerprint must be a SHA-256 value.').transform((value) => value.toLowerCase()),
  byte_size: z.number().int().nonnegative().safe(),
}).strict()
export type AssetFingerprint = z.infer<typeof AssetFingerprintSchema>

export const AssetProvenanceSchema = z.object({
  origin: z.enum(['imported', 'generated', 'legacy']),
  derived_from: z.array(StableIdSchema),
}).strict()
export type AssetProvenance = z.infer<typeof AssetProvenanceSchema>

export const MediaSourceSchema = z.object({
  asset_id: StableIdSchema,
  kind: z.enum(['video', 'audio']),
  name: NonEmptyTextSchema,
  ownership: AssetOwnershipSchema,
  path_hint: NonEmptyTextSchema,
  fingerprint: AssetFingerprintSchema,
  provenance: AssetProvenanceSchema,
  duration: NonNegativeMediaTimeSchema,
  width: z.number().int().nonnegative().safe(),
  height: z.number().int().nonnegative().safe(),
  frame_rate: FrameRateSchema.nullable(),
  has_audio: z.boolean(),
}).strict()
export type MediaSource = z.infer<typeof MediaSourceSchema>

export const ClipReplacementSchema = z.object({
  original_asset_id: StableIdSchema,
  original_source_in: NonNegativeMediaTimeSchema,
  original_source_out: NonNegativeMediaTimeSchema,
  manifest_asset_id: StableIdSchema,
}).strict()
export type ClipReplacement = z.infer<typeof ClipReplacementSchema>

export const MediaClipSchema = z.object({
  id: StableIdSchema,
  kind: z.literal('media'),
  asset_id: StableIdSchema,
  timeline_start: NonNegativeMediaTimeSchema,
  source_in: NonNegativeMediaTimeSchema,
  source_out: NonNegativeMediaTimeSchema,
  enabled: z.boolean(),
  gain: z.number().nonnegative().finite(),
  replacement: ClipReplacementSchema.optional(),
}).strict()
export type MediaClip = z.infer<typeof MediaClipSchema>

export const SubtitleCueSchema = z.object({
  id: StableIdSchema,
  kind: z.literal('subtitle'),
  start: NonNegativeMediaTimeSchema,
  end: NonNegativeMediaTimeSchema,
  text: NonEmptyTextSchema,
}).strict()
export type SubtitleCue = z.infer<typeof SubtitleCueSchema>

const TrackBaseShape = {
  id: StableIdSchema,
  name: NonEmptyTextSchema,
  enabled: z.boolean(),
  locked: z.boolean(),
}

export const MainVideoTrackSchema = z.object({
  ...TrackBaseShape,
  kind: z.literal('video'),
  role: z.literal('main'),
  clips: z.array(MediaClipSchema),
}).strict()
export type MainVideoTrack = z.infer<typeof MainVideoTrackSchema>

export const OverlayVideoTrackSchema = z.object({
  ...TrackBaseShape,
  kind: z.literal('video'),
  role: z.literal('overlay'),
  clips: z.array(MediaClipSchema),
}).strict()
export type OverlayVideoTrack = z.infer<typeof OverlayVideoTrackSchema>

export const SubtitleTrackSchema = z.object({
  ...TrackBaseShape,
  kind: z.literal('subtitle'),
  role: z.literal('overlay'),
  clips: z.array(SubtitleCueSchema),
}).strict()
export type SubtitleTrack = z.infer<typeof SubtitleTrackSchema>

export const AudioTrackSchema = z.object({
  ...TrackBaseShape,
  kind: z.literal('audio'),
  role: z.literal('audio'),
  clips: z.array(MediaClipSchema),
}).strict()
export type AudioTrack = z.infer<typeof AudioTrackSchema>

export const OverlayTrackSchema = z.discriminatedUnion('kind', [
  OverlayVideoTrackSchema,
  SubtitleTrackSchema,
])
export type OverlayTrack = z.infer<typeof OverlayTrackSchema>
export type EditorTrack = OverlayTrack | MainVideoTrack | AudioTrack
export type TimelineItem = MediaClip | SubtitleCue

export const EditorTimelineSchema = z.object({
  /** Topmost visual track is first. All overlays render above the main track. */
  overlays: z.array(OverlayTrackSchema),
  main: MainVideoTrackSchema,
  audio: z.array(AudioTrackSchema),
}).strict()
export type EditorTimeline = z.infer<typeof EditorTimelineSchema>

export const EditorCanvasSchema = z.object({
  width: z.number().int().positive().safe(),
  height: z.number().int().positive().safe(),
  frame_rate: FrameRateSchema,
  background: NonEmptyTextSchema,
}).strict()
export type EditorCanvas = z.infer<typeof EditorCanvasSchema>

const EditorProjectBaseSchema = z.object({
  schema_version: z.literal(EDITOR_PROJECT_SCHEMA_VERSION),
  document_type: z.literal(EDITOR_WORKFLOW_TYPE),
  project_id: StableIdSchema,
  workflow_id: StableIdSchema,
  revision: z.number().int().nonnegative().safe(),
  name: NonEmptyTextSchema,
  created_at: z.iso.datetime(),
  updated_at: z.iso.datetime(),
  canvas: EditorCanvasSchema,
  sources: z.array(MediaSourceSchema),
  timeline: EditorTimelineSchema,
}).strict()

export const EditorProjectSchema = EditorProjectBaseSchema.superRefine((project, context) => {
  if (Date.parse(project.updated_at) < Date.parse(project.created_at)) {
    context.addIssue({
      code: 'custom',
      path: ['updated_at'],
      message: 'Project update time cannot precede its creation time.',
    })
  }
  const allIds = new Set<string>()
  const registerId = (id: string, path: PropertyKey[]) => {
    if (allIds.has(id)) context.addIssue({ code: 'custom', path, message: `Duplicate id: ${id}.` })
    allIds.add(id)
  }
  const sourceById = new Map<string, MediaSource>()
  project.sources.forEach((source, index) => {
    registerId(source.asset_id, ['sources', index, 'asset_id'])
    sourceById.set(source.asset_id, source)
    if (source.kind === 'video' && (source.width <= 0 || source.height <= 0 || !source.frame_rate)) {
      context.addIssue({
        code: 'custom',
        path: ['sources', index],
        message: 'Video assets require positive dimensions and a frame rate.',
      })
    }
    if (source.provenance.origin === 'generated' && source.ownership !== 'managed') {
      context.addIssue({
        code: 'custom',
        path: ['sources', index, 'ownership'],
        message: 'Generated assets must be managed by the project bundle.',
      })
    }
  })
  project.sources.forEach((source, sourceIndex) => {
    const seenParents = new Set<string>()
    source.provenance.derived_from.forEach((parentId, parentIndex) => {
      const path = ['sources', sourceIndex, 'provenance', 'derived_from', parentIndex]
      if (!sourceById.has(parentId)) {
        context.addIssue({ code: 'custom', path, message: 'Provenance asset does not exist.' })
      } else if (parentId === source.asset_id) {
        context.addIssue({ code: 'custom', path, message: 'An asset cannot derive from itself.' })
      } else if (seenParents.has(parentId)) {
        context.addIssue({ code: 'custom', path, message: 'Duplicate provenance asset.' })
      }
      seenParents.add(parentId)
    })
  })
  const validateMediaClip = (clip: MediaClip, track: EditorTrack, path: PropertyKey[]) => {
    registerId(clip.id, [...path, 'id'])
    const source = sourceById.get(clip.asset_id)
    if (!source) {
      context.addIssue({ code: 'custom', path: [...path, 'asset_id'], message: 'Clip asset does not exist.' })
      return
    }
    if (track.kind === 'video' && source.kind !== 'video') {
      context.addIssue({ code: 'custom', path: [...path, 'asset_id'], message: 'Video tracks require video assets.' })
    }
    if (track.kind === 'audio' && source.kind !== 'audio' && !source.has_audio) {
      context.addIssue({ code: 'custom', path: [...path, 'asset_id'], message: 'Audio tracks require an asset with audio.' })
    }
    if (clip.source_out <= clip.source_in) {
      context.addIssue({ code: 'custom', path, message: 'Media clip source range is invalid.' })
    } else if (clip.source_out > source.duration) {
      context.addIssue({ code: 'custom', path: [...path, 'source_out'], message: 'Clip exceeds its asset duration.' })
    }
    if (clip.replacement) {
      const original = sourceById.get(clip.replacement.original_asset_id)
      if (!original) {
        context.addIssue({ code: 'custom', path: [...path, 'replacement', 'original_asset_id'], message: 'Replacement asset does not exist.' })
      } else if (original.kind !== source.kind) {
        context.addIssue({ code: 'custom', path: [...path, 'replacement', 'original_asset_id'], message: 'Replacement assets must have the same media kind.' })
      } else if (
        clip.replacement.original_source_out <= clip.replacement.original_source_in
        || clip.replacement.original_source_out > original.duration
      ) {
        context.addIssue({ code: 'custom', path: [...path, 'replacement'], message: 'Replacement source range is invalid.' })
      }
    }
  }
  const validateTrack = (track: EditorTrack, path: PropertyKey[]) => {
    registerId(track.id, [...path, 'id'])
    track.clips.forEach((clip, index) => {
      const clipPath = [...path, 'clips', index]
      if (clip.kind === 'subtitle') {
        registerId(clip.id, [...clipPath, 'id'])
        if (clip.end <= clip.start) {
          context.addIssue({ code: 'custom', path: clipPath, message: 'Subtitle cue timing is invalid.' })
        }
      } else {
        validateMediaClip(clip, track, clipPath)
      }
    })
  }
  project.timeline.overlays.forEach((track, index) => validateTrack(track, ['timeline', 'overlays', index]))
  validateTrack(project.timeline.main, ['timeline', 'main'])
  project.timeline.audio.forEach((track, index) => validateTrack(track, ['timeline', 'audio', index]))
})
export type EditorProject = z.infer<typeof EditorProjectSchema>

export interface CreateEditorProjectOptions {
  project_id: string
  workflow_id?: string
  name?: string
  now?: string
  id_factory?: () => string
  canvas?: Partial<EditorCanvas>
}

export interface ProjectValidationIssue {
  path: string
  message: string
}

function defaultIdFactory(): string {
  return crypto.randomUUID()
}

export function createEditorProject(options: CreateEditorProjectOptions): EditorProject {
  const now = options.now ?? new Date().toISOString()
  const idFactory = options.id_factory ?? defaultIdFactory
  return EditorProjectSchema.parse({
    schema_version: EDITOR_PROJECT_SCHEMA_VERSION,
    document_type: EDITOR_WORKFLOW_TYPE,
    project_id: options.project_id,
    workflow_id: options.workflow_id ?? idFactory(),
    revision: 0,
    name: options.name?.trim() || 'Untitled project',
    created_at: now,
    updated_at: now,
    canvas: {
      width: options.canvas?.width ?? 1_920,
      height: options.canvas?.height ?? 1_080,
      frame_rate: options.canvas?.frame_rate ?? frameRate(30),
      background: options.canvas?.background ?? '#000000',
    },
    sources: [],
    timeline: {
      overlays: [],
      main: {
        id: idFactory(),
        kind: 'video',
        role: 'main',
        name: 'Main video',
        enabled: true,
        locked: false,
        clips: [],
      },
      audio: [],
    },
  })
}

export function projectTracks(project: EditorProject): EditorTrack[] {
  return [...project.timeline.overlays, project.timeline.main, ...project.timeline.audio]
}

export function findProjectTrack(project: EditorProject, trackId: string): EditorTrack | undefined {
  return projectTracks(project).find((track) => track.id === trackId)
}

export function mediaClipEnd(clip: MediaClip) {
  return mediaTime(clip.timeline_start + clip.source_out - clip.source_in)
}

export function editorProjectDuration(project: EditorProject) {
  let maximum = mediaTime(0)
  for (const track of projectTracks(project)) {
    for (const clip of track.clips) {
      const end = clip.kind === 'subtitle' ? clip.end : mediaClipEnd(clip)
      if (end > maximum) maximum = end
    }
  }
  return maximum
}

export function validateEditorProject(project: EditorProject): ProjectValidationIssue[] {
  const result = EditorProjectSchema.safeParse(project)
  if (result.success) return []
  return result.error.issues.map((item) => ({
    path: item.path.map(String).join('.'),
    message: item.message,
  }))
}

export function assertValidEditorProject(project: EditorProject): void {
  const result = EditorProjectSchema.safeParse(project)
  if (!result.success) {
    throw new Error(result.error.issues.map((item) => `${item.path.map(String).join('.')}: ${item.message}`).join('\n'))
  }
}
