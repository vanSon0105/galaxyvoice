import { describe, expect, it } from 'vitest'

import {
  projectDuration,
  rippleDeleteCues,
  splitVideoSegment,
  timelineToSource,
  trimVideoSegment,
} from './segments'

const segments = [
  { id: 'a', source_start_ms: 1_000, source_end_ms: 4_000 },
  { id: 'b', source_start_ms: 8_000, source_end_ms: 10_000 },
]

describe('video timeline segments', () => {
  it('derives a ripple project duration from source ranges', () => {
    expect(projectDuration(segments)).toBe(5_000)
  })

  it('maps project time into the correct source segment', () => {
    expect(timelineToSource(segments, 3_500)).toMatchObject({
      index: 1,
      sourceMs: 8_500,
      timelineStartMs: 3_000,
    })
  })

  it('splits the selected segment at the project playhead', () => {
    const result = splitVideoSegment(segments, 1_750)
    expect(result?.segments).toEqual([
      { id: 'a-left', source_start_ms: 1_000, source_end_ms: 2_750 },
      { id: 'a-right', source_start_ms: 2_750, source_end_ms: 4_000 },
      segments[1],
    ])
    expect(result?.selectedIndex).toBe(1)
  })

  it('trims source edges while preserving a minimum clip length', () => {
    expect(trimVideoSegment(segments, 0, 'end', -1_800)[0]).toMatchObject({
      source_start_ms: 1_000,
      source_end_ms: 2_200,
    })
    expect(trimVideoSegment(segments, 0, 'start', 9_000)[0]).toMatchObject({
      source_start_ms: 3_900,
      source_end_ms: 4_000,
    })
  })

  it('removes subtitles inside a deleted clip and ripples later cues', () => {
    const cues = [
      { index: 1, start_ms: 500, end_ms: 1_500, text: 'before' },
      { index: 2, start_ms: 2_100, end_ms: 2_800, text: 'removed' },
      { index: 3, start_ms: 3_500, end_ms: 4_500, text: 'after' },
    ]
    expect(rippleDeleteCues(cues, 2_000, 1_000)).toEqual([
      cues[0],
      { ...cues[2], start_ms: 2_500, end_ms: 3_500 },
    ])
  })
})
