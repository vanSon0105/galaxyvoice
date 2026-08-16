import { useEffect, useMemo, useReducer } from 'react'

import { subscribeEvents } from './hub'
import type { ServerEvent, TaskStatus } from './types'

export interface TaskState {
  taskId: string
  status: TaskStatus
  lines: string[]
  result?: unknown
  error?: string
}

const MAX_LINES = 100

export function tasksReducer(
  state: Record<string, TaskState>,
  event: ServerEvent,
): Record<string, TaskState> {
  if (event.type === 'progress') {
    const task = state[event.task_id]
    if (!task || task.status !== 'running') return state
    const lines = [...task.lines, event.message].slice(-MAX_LINES)
    return { ...state, [event.task_id]: { ...task, lines } }
  }
  if (event.type === 'task') {
    const existing = state[event.task_id]
    if (!existing && event.status !== 'running') return state
    const task: TaskState = {
      taskId: event.task_id,
      status: event.status,
      lines: existing?.lines ?? [],
      result: event.result,
      error: event.error,
    }
    return { ...state, [event.task_id]: task }
  }
  return state
}

async function cancelTask(taskId: string): Promise<void> {
  await fetch(`/api/tasks/${encodeURIComponent(taskId)}/cancel`, { method: 'POST' })
}

export interface UseTasksResult {
  tasks: TaskState[]
  cancelTask: (taskId: string) => Promise<void>
}

/** Subscribes to the app-wide event hub and maintains the task registry. */
export function useTasks(): UseTasksResult {
  const [state, dispatch] = useReducer(tasksReducer, {})

  useEffect(() => subscribeEvents(dispatch), [])

  const tasks = useMemo(
    () => Object.values(state).sort((a, b) => a.taskId.localeCompare(b.taskId)),
    [state],
  )
  return { tasks, cancelTask }
}
