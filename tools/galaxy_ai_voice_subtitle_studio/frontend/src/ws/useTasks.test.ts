import { describe, expect, it } from 'vitest'

import { tasksReducer } from './useTasks'
import type { TaskState } from './useTasks'

describe('tasksReducer', () => {
  it('ignores progress for unknown or finished tasks', () => {
    const state = tasksReducer({}, { type: 'progress', task_id: 'x', message: 'nope' })
    expect(state).toEqual({})
    const running: Record<string, TaskState> = {
      t1: { taskId: 't1', status: 'running', lines: [] },
    }
    const done = tasksReducer(running, { type: 'task', task_id: 't1', status: 'done' })
    const afterDone = tasksReducer(done, { type: 'progress', task_id: 't1', message: 'late' })
    expect(afterDone.t1.lines).toEqual([])
  })

  it('appends progress lines and caps them', () => {
    let state = tasksReducer({}, { type: 'task', task_id: 't1', status: 'running' })
    for (let i = 0; i < 105; i += 1) {
      state = tasksReducer(state, { type: 'progress', task_id: 't1', message: `line ${i}` })
    }
    expect(state.t1.lines).toHaveLength(100)
    expect(state.t1.lines[99]).toBe('line 104')
  })

  it('records terminal task status with result', () => {
    let state = tasksReducer({}, { type: 'task', task_id: 't1', status: 'running' })
    state = tasksReducer(state, {
      type: 'task',
      task_id: 't1',
      status: 'done',
      result: { wav: 'a.wav' },
    })
    expect(state.t1.status).toBe('done')
    expect(state.t1.result).toEqual({ wav: 'a.wav' })
  })

  it('keeps queued and paused tasks active for progress updates', () => {
    let state = tasksReducer({}, { type: 'task', task_id: 't1', status: 'queued' })
    state = tasksReducer(state, { type: 'progress', task_id: 't1', message: 'waiting' })
    state = tasksReducer(state, { type: 'task', task_id: 't1', status: 'paused' })
    state = tasksReducer(state, { type: 'progress', task_id: 't1', message: 'paused' })

    expect(state.t1.status).toBe('paused')
    expect(state.t1.lines).toEqual(['waiting', 'paused'])
  })

  it('ignores terminal events for unknown tasks', () => {
    const state = tasksReducer({}, { type: 'task', task_id: 't1', status: 'done' })
    expect(state).toEqual({})
  })

  it('does not mutate the previous state object', () => {
    const before = tasksReducer({}, { type: 'task', task_id: 't1', status: 'running' })
    tasksReducer(before, { type: 'progress', task_id: 't1', message: 'x' })
    expect(before.t1.lines).toEqual([])
  })
})
