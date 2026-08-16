/** Server message envelope (see app/server/ws.py). */
export type ServerEvent =
  | { type: 'event'; kind: string; payload?: unknown }
  | { type: 'progress'; task_id: string; message: string }
  | { type: 'task'; task_id: string; status: TaskStatus; result?: unknown; error?: string }
  | { type: 'ping' }

export type TaskStatus = 'running' | 'done' | 'failed' | 'cancelled'
