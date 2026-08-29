import { useEffect, useMemo, useReducer } from 'react'

import { apiFetch, apiJson } from '../api/client'
import { subscribeConnectionOpen, subscribeEvents } from './hub'
import { isTaskActive, type ServerEvent, type TaskStatus } from './types'

export interface TaskState {
  taskId: string
  kind: string
  status: TaskStatus
  lines: string[]
  progress?: number
  message?: string
  result?: unknown
  error?: string
  canPause: boolean
  canResume: boolean
  canCancel: boolean
  projectId?: string
  workflowId?: string
  recoveryRoute?: string
  recoveryHint?: string
  updatedAt: number
}

interface TaskSnapshot {
  task_id: string
  kind: string
  status: TaskStatus
  logs?: string[]
  progress?: number | null
  message?: string
  result?: unknown
  error?: string | null
  can_pause?: boolean
  can_resume?: boolean
  can_cancel?: boolean
  project_id?: string
  workflow_id?: string
  recovery_route?: string
  recovery_hint?: string
  updated_at?: number
}

type TasksEvent = ServerEvent | { type: 'snapshot'; tasks: TaskSnapshot[] }
const MAX_LINES = 100
const MAX_VISIBLE_TASKS = 50

function pruneTaskState(state: Record<string, TaskState>): Record<string, TaskState> {
  const tasks = Object.values(state)
  const active = tasks.filter((task) => isTaskActive(task.status))
  const terminal = tasks
    .filter((task) => !isTaskActive(task.status))
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .slice(0, Math.max(0, MAX_VISIBLE_TASKS - active.length))
  if (active.length + terminal.length === tasks.length) return state
  return Object.fromEntries([...active, ...terminal].map((task) => [task.taskId, task]))
}

function fromSnapshot(task: TaskSnapshot): TaskState {
  return {
    taskId: task.task_id,
    kind: task.kind,
    status: task.status,
    lines: (task.logs ?? []).slice(-MAX_LINES),
    progress: task.progress ?? undefined,
    message: task.message,
    result: task.result,
    error: task.error ?? undefined,
    canPause: Boolean(task.can_pause),
    canResume: Boolean(task.can_resume),
    canCancel: Boolean(task.can_cancel),
    projectId: task.project_id || undefined,
    workflowId: task.workflow_id || undefined,
    recoveryRoute: task.recovery_route,
    recoveryHint: task.recovery_hint,
    updatedAt: task.updated_at ?? Date.now() / 1000,
  }
}

export function tasksReducer(
  state: Record<string, TaskState>,
  event: TasksEvent,
): Record<string, TaskState> {
  if (event.type === 'snapshot') {
    const merged = { ...state }
    event.tasks.forEach((task) => {
      const incoming = fromSnapshot(task)
      const existing = merged[task.task_id]
      if (!existing) {
        merged[task.task_id] = incoming
        return
      }
      const existingActive = isTaskActive(existing.status)
      const incomingActive = isTaskActive(incoming.status)
      if (existingActive && !incomingActive) {
        merged[task.task_id] = incoming
        return
      }
      if (!existingActive && incomingActive) return
      if (incoming.updatedAt >= existing.updatedAt) {
        merged[task.task_id] = incoming
        return
      }
      // Task events arrive quickly but do not carry capability metadata. Merge
      // authoritative controls without allowing an older snapshot to roll status back.
      merged[task.task_id] = {
        ...existing,
        canPause: incoming.canPause,
        canResume: incoming.canResume,
        canCancel: incoming.canCancel,
        projectId: incoming.projectId || existing.projectId,
        workflowId: incoming.workflowId || existing.workflowId,
        recoveryRoute: incoming.recoveryRoute || existing.recoveryRoute,
        recoveryHint: incoming.recoveryHint || existing.recoveryHint,
      }
    })
    return pruneTaskState(merged)
  }
  if (event.type === 'progress') {
    const task = state[event.task_id]
    if (!task || !isTaskActive(task.status)) return state
    const lines = [...task.lines, event.message].slice(-MAX_LINES)
    return pruneTaskState({
      ...state,
      [event.task_id]: {
        ...task,
        lines,
        message: event.message,
        progress: event.progress ?? task.progress,
        updatedAt: Date.now() / 1000,
      },
    })
  }
  if (event.type === 'task') {
    const existing = state[event.task_id]
    if (!existing && !isTaskActive(event.status)) return state
    return pruneTaskState({
      ...state,
      [event.task_id]: {
        taskId: event.task_id,
        kind: existing?.kind ?? 'task',
        status: event.status,
        lines: existing?.lines ?? [],
        progress: event.status === 'done' ? 1 : existing?.progress,
        message: existing?.message,
        result: event.result,
        error: event.error,
        canPause: (event.status === 'running' || event.status === 'queued')
          ? (existing?.canPause ?? false)
          : false,
        canResume: event.status === 'paused'
          ? Boolean(existing?.canPause || existing?.canResume)
          : false,
        canCancel: isTaskActive(event.status),
        projectId: existing?.projectId,
        workflowId: existing?.workflowId,
        recoveryRoute: existing?.recoveryRoute,
        recoveryHint: existing?.recoveryHint,
        updatedAt: Date.now() / 1000,
      },
    })
  }
  return state
}

async function taskAction(taskId: string, action: 'pause' | 'resume' | 'cancel'): Promise<void> {
  await apiJson(`/api/tasks/${encodeURIComponent(taskId)}/${action}`, { method: 'POST' })
}

export interface UseTasksResult {
  tasks: TaskState[]
  pauseTask: (taskId: string) => Promise<void>
  resumeTask: (taskId: string) => Promise<void>
  cancelTask: (taskId: string) => Promise<void>
}

export function useTasks(): UseTasksResult {
  const [state, dispatch] = useReducer(tasksReducer, {})

  useEffect(() => {
    let mounted = true
    const fetchSnapshot = async (path: string): Promise<TaskSnapshot[]> => {
      const response = await apiFetch(path, {}, { retries: 0 })
      if (!response.ok) return []
      const payload = await response.json() as TaskSnapshot | TaskSnapshot[]
      return Array.isArray(payload) ? payload : [payload]
    }
    const reconcileSnapshot = () => void fetchSnapshot('/api/tasks')
      .then((tasks) => {
        if (mounted) dispatch({ type: 'snapshot', tasks })
      })
      .catch(() => undefined)
    reconcileSnapshot()
    const unsubscribeConnection = subscribeConnectionOpen(reconcileSnapshot)
    const unsubscribe = subscribeEvents((event) => {
      dispatch(event)
      if (event.type !== 'task' || !isTaskActive(event.status)) return
      void fetchSnapshot(`/api/tasks/${encodeURIComponent(event.task_id)}`)
        .then((tasks) => {
          if (mounted) dispatch({ type: 'snapshot', tasks })
        })
        .catch(() => undefined)
    })
    return () => {
      mounted = false
      unsubscribe()
      unsubscribeConnection()
    }
  }, [])

  const tasks = useMemo(
    () => Object.values(state).sort((a, b) => b.updatedAt - a.updatedAt).slice(0, MAX_VISIBLE_TASKS),
    [state],
  )
  return {
    tasks,
    pauseTask: (taskId) => taskAction(taskId, 'pause'),
    resumeTask: (taskId) => taskAction(taskId, 'resume'),
    cancelTask: (taskId) => taskAction(taskId, 'cancel'),
  }
}
