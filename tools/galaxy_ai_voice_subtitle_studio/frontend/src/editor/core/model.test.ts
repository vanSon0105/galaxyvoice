import { describe, expect, it } from 'vitest'

import {
  createEditorProject,
  deserializeEditorProject,
  frameRate,
  serializeEditorProject,
  validateEditorProject,
} from './index'

const PROJECT_ID = '20000000-0000-4000-8000-000000000001'
const DUPLICATE_ID = '20000000-0000-4000-8000-000000000002'
const SOURCE_ID = '20000000-0000-4000-8000-000000000003'
const AUDIO_ID = '20000000-0000-4000-8000-000000000004'
const SUBTITLE_TRACK_ID = '20000000-0000-4000-8000-000000000005'
const CUE_ID = '20000000-0000-4000-8000-000000000006'
const CLIP_ID = '20000000-0000-4000-8000-000000000007'

describe('editor project schema', () => {
  it('creates a versioned project with one permanent main video track', () => {
    const project = createEditorProject({
      project_id: PROJECT_ID,
      name: 'Episode 1',
      now: '2026-09-05T00:00:00.000Z',
    })

    expect(project.schema_version).toBe(1)
    expect(project).toMatchObject({ document_type: 'video-editor', project_id: PROJECT_ID, revision: 0 })
    expect(project.timeline.main).toMatchObject({ kind: 'video', role: 'main', enabled: true })
    expect(project.timeline.overlays).toEqual([])
    expect(project.timeline.audio).toEqual([])
  })

  it('canonicalizes compact and uppercase UUID identity at the schema boundary', () => {
    const project = createEditorProject({ project_id: '20000000000040008000000000000001'.toUpperCase() })
    expect(project.project_id).toBe(PROJECT_ID)
  })

  it('round-trips a valid project through its persistence interface', () => {
    const project = createEditorProject({
      project_id: PROJECT_ID,
      now: '2026-09-05T00:00:00.000Z',
      canvas: { frame_rate: frameRate(30_000, 1_001) },
    })

    expect(deserializeEditorProject(serializeEditorProject(project))).toEqual(project)
  })

  it('reports duplicate entity ids before a malformed project reaches playback or export', () => {
    const project = createEditorProject({ project_id: PROJECT_ID, id_factory: () => DUPLICATE_ID })
    project.timeline.audio.push({
      id: DUPLICATE_ID,
      kind: 'audio',
      role: 'audio',
      name: 'Voice',
      enabled: true,
      locked: false,
      clips: [],
    })

    expect(validateEditorProject(project)).toContainEqual({
      path: 'timeline.audio.0.id',
      message: `Duplicate id: ${DUPLICATE_ID}.`,
    })
  })

  it('rejects malformed persisted data with a domain error', () => {
    expect(() => deserializeEditorProject(JSON.stringify({ schema_version: 1 })))
      .toThrow()

    const project = createEditorProject({ project_id: PROJECT_ID })
    const malformed = {
      ...project,
      timeline: {
        ...project.timeline,
        overlays: [{
          id: SUBTITLE_TRACK_ID,
          kind: 'subtitle',
          role: 'overlay',
          name: 'Subtitle',
          enabled: true,
          locked: false,
          clips: [{ id: CUE_ID, kind: 'subtitle' }],
        }],
      },
    }
    expect(() => deserializeEditorProject(JSON.stringify(malformed)))
      .toThrow()
  })

  it('rejects unknown discriminators and invalid video metadata at the persistence seam', () => {
    const project = createEditorProject({ project_id: PROJECT_ID })
    const invalidKind = {
      ...project,
      sources: [{
        asset_id: SOURCE_ID,
        kind: 'unknown',
        name: 'source.mp4',
        ownership: 'linked',
        path_hint: 'D:/source.mp4',
        fingerprint: { algorithm: 'sha256', value: '2'.repeat(64), byte_size: 1_024 },
        provenance: { origin: 'legacy', derived_from: [] },
        duration: 120_000,
        width: 1_920,
        height: 1_080,
        frame_rate: { numerator: 30, denominator: 1 },
        has_audio: true,
      }],
    }
    expect(() => deserializeEditorProject(JSON.stringify(invalidKind))).toThrow()

    const invalidVideo = {
      ...project,
      sources: [{ ...invalidKind.sources[0], kind: 'video', width: 0 }],
    }
    expect(() => deserializeEditorProject(JSON.stringify(invalidVideo)))
      .toThrow('Video assets require positive dimensions')
  })

  it('rejects clips and replacement metadata that reference incompatible assets', () => {
    const project = createEditorProject({ project_id: PROJECT_ID })
    const malformed = {
      ...project,
      sources: [{
        asset_id: AUDIO_ID,
        kind: 'audio',
        name: 'voice.wav',
        ownership: 'linked',
        path_hint: 'D:/voice.wav',
        fingerprint: { algorithm: 'sha256', value: '3'.repeat(64), byte_size: 512 },
        provenance: { origin: 'imported', derived_from: [] },
        duration: 120_000,
        width: 0,
        height: 0,
        frame_rate: null,
        has_audio: true,
      }],
      timeline: {
        ...project.timeline,
        main: {
          ...project.timeline.main,
          clips: [{
            id: CLIP_ID,
            kind: 'media',
            asset_id: SOURCE_ID,
            timeline_start: 0,
            source_in: 0,
            source_out: 120_000,
            enabled: true,
            gain: 1,
            replacement: {
              original_asset_id: AUDIO_ID,
              original_source_in: 0,
              original_source_out: 120_000,
              manifest_asset_id: '20000000-0000-4000-8000-000000000008',
            },
          }],
        },
      },
    }

    expect(() => deserializeEditorProject(JSON.stringify(malformed)))
      .toThrow('Clip asset does not exist')

    const incompatibleReplacement = {
      ...malformed,
      sources: [
        ...malformed.sources,
        {
          ...malformed.sources[0],
          asset_id: SOURCE_ID,
          kind: 'video',
          name: 'video.mp4',
          path_hint: 'D:/video.mp4',
          width: 1_920,
          height: 1_080,
          frame_rate: { numerator: 30, denominator: 1 },
        },
      ],
    }
    expect(() => deserializeEditorProject(JSON.stringify(incompatibleReplacement)))
      .toThrow('Replacement assets must have the same media kind')
  })

  it('rejects project timestamps that move backwards', () => {
    const project = createEditorProject({ project_id: PROJECT_ID, now: '2026-09-05T00:00:00.000Z' })
    expect(() => deserializeEditorProject(JSON.stringify({
      ...project,
      updated_at: '2026-09-04T23:59:59.000Z',
    }))).toThrow('Project update time cannot precede its creation time')
  })

  it('requires content fingerprints and valid provenance references', () => {
    const project = createEditorProject({ project_id: PROJECT_ID })
    const source = {
      asset_id: SOURCE_ID,
      kind: 'audio',
      name: 'voice.wav',
      ownership: 'managed',
      path_hint: 'assets/voice.wav',
      fingerprint: { algorithm: 'sha256', value: '5'.repeat(64), byte_size: 512 },
      provenance: { origin: 'generated', derived_from: [AUDIO_ID] },
      duration: 120_000,
      width: 0,
      height: 0,
      frame_rate: null,
      has_audio: true,
    }

    expect(() => deserializeEditorProject(JSON.stringify({ ...project, sources: [{ ...source, fingerprint: null }] })))
      .toThrow()
    expect(() => deserializeEditorProject(JSON.stringify({ ...project, sources: [source] })))
      .toThrow('Provenance asset does not exist')
    expect(() => deserializeEditorProject(JSON.stringify({
      ...project,
      sources: [{ ...source, ownership: 'linked', provenance: { origin: 'generated', derived_from: [] } }],
    }))).toThrow('Generated assets must be managed')
  })
})
