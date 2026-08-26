import { useT } from '../i18n/useT'
import { useTasks } from '../ws/useTasks'
import { isTaskActive } from '../ws/types'

/** Bottom panel listing running/recent tasks with progress tail + cancel. */
export function ProgressPanel() {
  const { tasks, cancelTask } = useTasks()
  const t = useT()
  if (tasks.length === 0) return null
  return (
    <footer className="progress-panel" aria-label="Tasks">
      {tasks.map((task) => (
        <div className="task-row" key={task.taskId}>
          <span className="task-status">{t(`task.${task.status}`)}</span>
          <span className="task-lines" title={task.lines.join('\n')}>
            {task.lines.length > 0 ? task.lines[task.lines.length - 1] : task.error ?? ''}
          </span>
          {isTaskActive(task.status) && (
            <button className="btn danger" onClick={() => void cancelTask(task.taskId)}>
              {t('task.cancel')}
            </button>
          )}
        </div>
      ))}
    </footer>
  )
}
