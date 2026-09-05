import { describe, expect, it } from 'vitest'
import { v5 as uuidV5 } from 'uuid'

import type { EditorMedia } from '../../api/editor'
import type { EditorTrack as LegacyTrack } from '../../components/timeline/tracks'
import { migrateLegacyTimeline, projectToLegacyTimeline } from './legacyTimeline'

const PROJECT_ID = '30000000-0000-4000-8000-000000000001'
const ASSET_NAMESPACE = '30000000-0000-4000-8000-000000000002'
const MANIFEST_ID = '30000000-0000-4000-8000-000000000003'
const MANIFEST_PATH = 'D:/cleanup/manifest.json'

const assetId = (sourceId: string) => uuidV5(sourceId, ASSET_NAMESPACE)
const migrationOptions = {
  project_id: PROJECT_ID,
  now: '2026-09-05T00:00:00.000Z',
  resolve_asset: (source: EditorMedia) => ({
    asset_id: assetId(source.source_id),
    ownership: 'linked' as const,
    fingerprint: { algorithm: 'sha256' as const, value: '4'.repeat(64), byte_size: 1_024 },
  }),
  resolve_manifest_asset_id: (path: string) => {
    if (path !== MANIFEST_PATH) throw new Error(`Unknown manifest: ${path}`)
    return MANIFEST_ID
  },
}
const projectionOptions = {
  resolve_source_url: (source: { asset_id: string }) => `/api/editor/source/${source.asset_id}`,
  resolve_manifest_path: (assetIdValue: string) => {
    if (assetIdValue !== MANIFEST_ID) throw new Error(`Unknown manifest asset: ${assetIdValue}`)
    return MANIFEST_PATH
  },
}

const media = (id: string, kind: 'video' | 'audio', seconds: number): EditorMedia => ({
  source_id: id,
  kind,
  name: `${id}.${kind === 'video' ? 'mp4' : 'wav'}`,
  path: `D:/${id}.${kind === 'video' ? 'mp4' : 'wav'}`,
  url: `/api/editor/source/${id}`,
  duration_seconds: seconds,
  width: kind === 'video' ? 1_920 : 0,
  height: kind === 'video' ? 1_080 : 0,
  fps: kind === 'video' ? 29.97 : 0,
  has_audio: true,
})

describe('legacy timeline adapter', () => {
  it('makes the bottom video lane main and preserves upper visual layer order', () => {
    const tracks: LegacyTrack[] = [
      { id: 'sub', kind: 'subtitle', name: 'Phụ đề', enabled: true, locked: false, cues: [{ id: 'cue', index: 1, start_ms: 1_000, end_ms: 2_000, text: 'Xin chào' }] },
      { id: 'top', kind: 'video', name: 'Video trên', enabled: true, locked: false, clips: [{ id: 'top-clip', media: media('top-source', 'video', 5), timeline_start_ms: 2_000, source_start_ms: 500, source_end_ms: 4_000 }] },
      { id: 'voice', kind: 'audio', name: 'Voice', enabled: true, locked: false, clips: [{ id: 'voice-clip', media: media('voice-source', 'audio', 3), timeline_start_ms: 1_000, source_start_ms: 0, source_end_ms: 3_000 }] },
      { id: 'bottom', kind: 'video', name: 'Video chính', enabled: true, locked: false, clips: [{ id: 'main-clip', media: media('main-source', 'video', 10), timeline_start_ms: 0, source_start_ms: 0, source_end_ms: 10_000 }] },
    ]

    const project = migrateLegacyTimeline(tracks, migrationOptions)

    expect(project.timeline.main.name).toBe(tracks[3].name)
    expect(project.timeline.overlays.map((track) => track.name)).toEqual([tracks[0].name, tracks[1].name])
    expect(project.timeline.audio.map((track) => track.name)).toEqual([tracks[2].name])
    expect(project.canvas.frame_rate).toEqual({ numerator: 30_000, denominator: 1_001 })
    const restored = projectToLegacyTimeline(project, projectionOptions)
    expect(restored.map((track) => track.kind)).toEqual(['subtitle', 'video', 'video', 'audio'])
    expect(restored.map((track) => track.id)).toEqual([
      project.timeline.overlays[0].id,
      project.timeline.overlays[1].id,
      project.timeline.main.id,
      project.timeline.audio[0].id,
    ])
    expect(restored[0]).toMatchObject({
      kind: 'subtitle',
      name: tracks[0].name,
      cues: [{
        index: 1,
        start_ms: 1_000,
        end_ms: 2_000,
        text: tracks[0].kind === 'subtitle' ? tracks[0].cues[0].text : '',
      }],
    })
    expect(restored[1]).toMatchObject({
      name: tracks[1].name,
      clips: [{ timeline_start_ms: 2_000, source_start_ms: 500, source_end_ms: 4_000 }],
    })
    expect(restored[2]).toMatchObject({
      name: tracks[3].name,
      clips: [{ timeline_start_ms: 0, source_start_ms: 0, source_end_ms: 10_000 }],
    })
    expect(restored[3]).toMatchObject({
      kind: 'audio',
      name: 'Voice',
      clips: [{
        timeline_start_ms: 1_000,
        source_start_ms: 0,
        source_end_ms: 3_000,
        media: { source_id: assetId('voice-source'), path: 'D:/voice-source.wav' },
      }],
    })
  })

  it('preserves reversible subtitle-removal replacements', () => {
    const original = media('original', 'video', 20)
    const cleaned = media('cleaned', 'video', 20)
    const tracks: LegacyTrack[] = [{
      id: 'video',
      kind: 'video',
      name: 'Video',
      enabled: true,
      locked: false,
      clips: [{
        id: 'clip',
        media: cleaned,
        timeline_start_ms: 1_000,
        source_start_ms: 2_000,
        source_end_ms: 15_000,
        replacement: {
          original_media: original,
          original_source_start_ms: 2_000,
          original_source_end_ms: 15_000,
          manifest_path: MANIFEST_PATH,
        },
      }],
    }]

    const project = migrateLegacyTimeline(tracks, migrationOptions)

    expect(project.sources.map((source) => source.asset_id)).toEqual([assetId('cleaned'), assetId('original')])
    expect(project.sources[0].provenance.derived_from).toEqual([assetId('original')])
    expect(project.timeline.main.clips[0].replacement?.manifest_asset_id).toBe(MANIFEST_ID)
    expect(projectToLegacyTimeline(project, projectionOptions)[0]).toMatchObject({
      clips: [{
        timeline_start_ms: 1_000,
        source_start_ms: 2_000,
        source_end_ms: 15_000,
        replacement: {
          original_source_start_ms: 2_000,
          original_source_end_ms: 15_000,
          manifest_path: MANIFEST_PATH,
          original_media: { source_id: assetId('original'), path: 'D:/original.mp4' },
        },
      }],
    })
  })

  it('rejects a legacy subtitle lane below the main video instead of silently changing z-order', () => {
    const tracks: LegacyTrack[] = [
      { id: 'video', kind: 'video', name: 'Video', enabled: true, locked: false, clips: [] },
      { id: 'subtitle', kind: 'subtitle', name: 'Subtitle', enabled: true, locked: false, cues: [] },
    ]

    expect(() => migrateLegacyTimeline(tracks, migrationOptions))
      .toThrow('cannot be placed below the main video')
  })

  it('rejects conflicting media that resolve to one asset identity', () => {
    const first = media('first', 'audio', 3)
    const second = media('second', 'audio', 3)
    const tracks: LegacyTrack[] = [{
      id: 'audio',
      kind: 'audio',
      name: 'Audio',
      enabled: true,
      locked: false,
      clips: [
        { id: 'first-clip', media: first, timeline_start_ms: 0, source_start_ms: 0, source_end_ms: 3_000 },
        { id: 'second-clip', media: second, timeline_start_ms: 3_000, source_start_ms: 0, source_end_ms: 3_000 },
      ],
    }]

    expect(() => migrateLegacyTimeline(tracks, {
      ...migrationOptions,
      resolve_asset: (source) => ({
        asset_id: assetId('shared'),
        ownership: 'linked',
        fingerprint: {
          algorithm: 'sha256',
          value: source.source_id === 'first' ? '6'.repeat(64) : '7'.repeat(64),
          byte_size: 1_024,
        },
      }),
    })).toThrow('conflicting fingerprint or media metadata')
  })
})
