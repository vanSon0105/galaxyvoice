import type { TaskState } from '../ws/useTasks'

export function taskRecoveryRoute(task: TaskState): string {
  if (!task.recoveryRoute) return ''
  const [pathname, rawQuery = ''] = task.recoveryRoute.split('?', 2)
  const query = new URLSearchParams(rawQuery)
  if (task.projectId) query.set('project_id', task.projectId)
  if (task.workflowId) query.set('workflow_id', task.workflowId)
  const encoded = query.toString()
  return encoded ? `${pathname}?${encoded}` : pathname
}
