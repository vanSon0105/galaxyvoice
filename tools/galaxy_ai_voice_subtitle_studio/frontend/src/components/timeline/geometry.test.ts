import { describe, expect, it } from 'vitest'

import { cueOverviewIntervals, hitTestCue, msToPx, parseClock, pxToMs, rulerStepSeconds, snapMs, visibleCues, visibleTimeRange } from './geometry'

const cues = [
  { index: 1, start_ms: 0, end_ms: 1_000, text: 'Một' },
  { index: 2, start_ms: 5_000, end_ms: 7_000, text: 'Hai' },
  { index: 3, start_ms: 20_000, end_ms: 22_000, text: 'Ba' },
]

describe('timeline geometry', () => {
  it('converts milliseconds and pixels without drift', () => {
    expect(pxToMs(msToPx(12_345, 80), 80)).toBeCloseTo(12_345)
  })

  it('only materializes cues intersecting the viewport', () => {
    expect(visibleCues(cues, 4_000, 8_000).map((cue) => cue.index)).toEqual([2])
    expect(visibleTimeRange(8_088, 800, 80, 0)).toEqual([100_000, 110_000])
  })

  it('hit-tests cues and chooses readable ruler spacing', () => {
    expect(hitTestCue(cues, 5_500)).toBe(1)
    expect(hitTestCue(cues, 10_000)).toBeNull()
    expect(rulerStepSeconds(0.1)).toBe(900)
  })

  it('parses editor clock fields', () => {
    expect(parseClock('01:02.500')).toBe(62_500)
    expect(parseClock('01:02:03,250')).toBe(3_723_250)
  })

  it('snaps drag positions and merges dense cue overview blocks', () => {
    expect(snapMs(1_049)).toBe(1_000)
    expect(snapMs(1_051)).toBe(1_100)
    expect(cueOverviewIntervals(cues.slice(0, 2), 0.1)).toEqual([[0, 1]])
  })
})
