/** Server message envelope (see app/server/ws.py). */
export type ServerEvent =
  | { type: 'event'; kind: string; payload?: unknown }
  | { type: 'progress'; task_id: string; message: string; progress?: number }
  | { type: 'task'; task_id: string; status: TaskStatus; result?: unknown; error?: string }
  | { type: 'ping' }

export type TaskStatus =
  | 'queued'
  | 'running'
  | 'paused'
  | 'done'
  | 'failed'
  | 'cancelled'
  | 'interrupted'

export function isTaskActive(status: TaskStatus | undefined): boolean {
  return status === 'queued' || status === 'running' || status === 'paused'
}
