import { Link } from 'react-router-dom'

import { useT } from '../i18n/useT'
import { useTasks } from '../ws/useTasks'
import { taskRecoveryRoute } from './taskRecovery'

export function ProgressPanel({ open }: { open: boolean }) {
  const { tasks, pauseTask, resumeTask, cancelTask } = useTasks()
  const t = useT()
  if (!open || tasks.length === 0) return null
  return (
    <footer id="task-progress-panel" className="progress-panel" aria-label="Tác vụ và tiến trình">
      {tasks.map((task) => (
        <details
          className="task-row"
          key={task.taskId}
          open={task.status === 'failed' || task.status === 'interrupted'}
        >
          <summary>
            <span className="task-kind">{task.kind}</span>
            <span className={`task-status ${task.status}`}>{t(`task.${task.status}`)}</span>
            <span className="task-lines">
              {task.message || task.lines.at(-1) || task.error || task.recoveryHint || ''}
            </span>
            {task.progress !== undefined && (
              <progress value={task.progress} max={1} aria-label={`Tiến trình ${task.kind}`} />
            )}
          </summary>
          <div className="task-detail">
            {task.lines.length > 0 && <pre>{task.lines.join('\n')}</pre>}
            {task.error && <p className="field-error" role="alert">{task.error}</p>}
            {task.recoveryHint && <p>{task.recoveryHint}</p>}
            <div className="task-actions">
              {task.canPause && (
                <button className="btn" onClick={() => void pauseTask(task.taskId)}>Tạm dừng</button>
              )}
              {task.canResume && (
                <button className="btn primary" onClick={() => void resumeTask(task.taskId)}>Tiếp tục</button>
              )}
              {task.canCancel && (
                <button className="btn danger" onClick={() => void cancelTask(task.taskId)}>
                  {t('task.cancel')}
                </button>
              )}
              {task.recoveryRoute && !task.canCancel && (
                <Link className="btn" to={taskRecoveryRoute(task)}>Mở nơi phục hồi</Link>
              )}
            </div>
          </div>
        </details>
      ))}
    </footer>
  )
}
