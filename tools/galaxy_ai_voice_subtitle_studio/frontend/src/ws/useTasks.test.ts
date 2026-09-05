import { cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { apiFetch } from '../api/client'
import { publishConnectionOpen } from './hub'
import { tasksReducer, useTasks } from './useTasks'
import type { TaskState } from './useTasks'

vi.mock('../api/client', () => ({ apiFetch: vi.fn(), apiJson: vi.fn() }))

describe('tasksReducer', () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue([]),
    } as unknown as Response)
  })
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('restores persisted diagnostics and recovery metadata', () => {
    const state = tasksReducer({}, {
      type: 'snapshot',
      tasks: [{
        task_id: 'old', kind: 'workspace-render', status: 'interrupted',
        logs: ['render 40%'], progress: 0.4, recovery_route: '/voice/batch',
        project_id: 'galaxy-1', workflow_id: 'book-1',
        recovery_hint: 'Tiếp tục từ checkpoint', updated_at: 12,
      }],
    })

    expect(state.old.lines).toEqual(['render 40%'])
    expect(state.old.progress).toBe(0.4)
    expect(state.old.recoveryRoute).toBe('/voice/batch')
    expect(state.old.projectId).toBe('galaxy-1')
    expect(state.old.workflowId).toBe('book-1')
  })

  it('does not let a stale bootstrap snapshot overwrite a newer websocket event', () => {
    const live = tasksReducer({}, { type: 'task', task_id: 'same', status: 'running' })
    const state = tasksReducer(live, {
      type: 'snapshot',
      tasks: [{ task_id: 'same', kind: 'test', status: 'queued', updated_at: 1 }],
    })

    expect(state.same.status).toBe('running')
  })

  it('merges task controls from an older active snapshot', () => {
    const live = tasksReducer({}, { type: 'task', task_id: 'same', status: 'running' })
    const state = tasksReducer(live, {
      type: 'snapshot',
      tasks: [{
        task_id: 'same', kind: 'test', status: 'running', updated_at: 1,
        can_pause: true, can_cancel: true,
      }],
    })

    expect(state.same.status).toBe('running')
    expect(state.same.canPause).toBe(true)
    expect(state.same.canCancel).toBe(true)
  })

  it('accepts a terminal snapshot even when its server timestamp is older', () => {
    const live = tasksReducer({}, { type: 'task', task_id: 'same', status: 'running' })
    const state = tasksReducer(live, {
      type: 'snapshot',
      tasks: [{
        task_id: 'same', kind: 'test', status: 'done', updated_at: 1,
        result: { wav: 'done.wav' },
      }],
    })

    expect(state.same.status).toBe('done')
    expect(state.same.result).toEqual({ wav: 'done.wav' })
  })

  it('ignores progress for unknown or finished tasks', () => {
    const state = tasksReducer({}, { type: 'progress', task_id: 'x', message: 'nope' })
    expect(state).toEqual({})
    const running: Record<string, TaskState> = {
      t1: {
        taskId: 't1', kind: 'test', status: 'running', lines: [],
        canPause: true, canResume: false, canCancel: true, updatedAt: 0,
      },
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

  it('prunes old terminal tasks while preserving every active task', () => {
    const terminal = Array.from({ length: 80 }, (_, index) => ({
      task_id: `done-${index}`, kind: 'test', status: 'done' as const, updated_at: index,
    }))
    const state = tasksReducer({}, {
      type: 'snapshot',
      tasks: [...terminal, { task_id: 'active', kind: 'test', status: 'running', updated_at: 0 }],
    })

    expect(Object.keys(state)).toHaveLength(50)
    expect(state.active.status).toBe('running')
    expect(state['done-79']).toBeDefined()
    expect(state['done-0']).toBeUndefined()
  })

  it('reconciles the task snapshot whenever the websocket opens again', async () => {
    renderHook(() => useTasks())
    await waitFor(() => expect(apiFetch).toHaveBeenCalledTimes(1))

    publishConnectionOpen()

    await waitFor(() => expect(apiFetch).toHaveBeenCalledTimes(2))
    expect(apiFetch).toHaveBeenLastCalledWith('/api/tasks', {}, { retries: 0 })
  })
})
