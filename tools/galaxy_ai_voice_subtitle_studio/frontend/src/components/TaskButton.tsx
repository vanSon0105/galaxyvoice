import { useEffect, useRef, useState } from 'react'

import { useT } from '../i18n/useT'
import { useTasks } from '../ws/useTasks'
import type { TaskState } from '../ws/useTasks'

interface TaskButtonProps {
  label: string
  /** Starts the task and returns its task_id (from the POST response). */
  onStart: () => Promise<string>
  /** Called when the task reaches a terminal state. */
  onFinish?: (task: TaskState) => void
  disabled?: boolean
  variant?: 'accent' | 'tool' | 'danger'
  confirm?: string
}

/** Button that starts a server task and tracks it via the WS task registry. */
export function TaskButton({
  label,
  onStart,
  onFinish,
  disabled = false,
  variant = 'tool',
  confirm,
}: TaskButtonProps) {
  const t = useT()
  const { tasks } = useTasks()
  const [taskId, setTaskId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const finishedRef = useRef<string | null>(null)

  const task = taskId ? tasks.find((candidate) => candidate.taskId === taskId) : undefined
  const running = task?.status === 'running'

  useEffect(() => {
    if (!task || task.status === 'running') return
    const key = `${task.taskId}:${task.status}`
    if (finishedRef.current === key) return
    finishedRef.current = key
    onFinish?.(task)
  }, [task, onFinish])

  const handleClick = async () => {
    if (running || disabled) return
    if (confirm && !window.confirm(confirm)) return
    setError(null)
    try {
      const startedId = await onStart()
      setTaskId(startedId)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    }
  }

  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
      <button
        className={`btn${variant === 'accent' ? ' accent' : variant === 'danger' ? ' danger' : ''}`}
        onClick={() => void handleClick()}
        disabled={disabled || running}
      >
        {running ? t('task.running') : label}
      </button>
      {error && (
        <span style={{ color: 'var(--color-danger)', fontSize: 12 }} title={error}>
          {error}
        </span>
      )}
    </span>
  )
}
