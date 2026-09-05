import { describe, expect, it } from 'vitest'

import { taskRecoveryRoute } from './taskRecovery'
import type { TaskState } from '../ws/useTasks'

describe('taskRecoveryRoute', () => {
  it('preserves the project and workflow checkpoint identity', () => {
    const task = {
      taskId: 'render-1', kind: 'workspace-render', status: 'interrupted', lines: [],
      canPause: false, canResume: false, canCancel: false, updatedAt: 1,
      recoveryRoute: '/voice/batch?tab=render', projectId: 'project 1', workflowId: 'batch-1',
    } satisfies TaskState

    expect(taskRecoveryRoute(task)).toBe(
      '/voice/batch?tab=render&project_id=project+1&workflow_id=batch-1',
    )
  })
})
