export default function LangGraphPlanCard({
  result,
  taskData,
  taskOutputs,
  completedTaskLogs,
  expandedTasks,
  onToggleTask,
  formatResult,
  sanitizeText,
}) {
  const safeText = (value) => sanitizeText(formatResult(value));

  return (
    <div className="card">
      <h2>Plan Output (LangGraph)</h2>
      {result ? (
        <pre>{safeText(result)}</pre>
      ) : (
        <p>No LangGraph output yet.</p>
      )}
      {(taskOutputs.length > 0 || Object.keys(completedTaskLogs).length > 0) && (
        <>
          <h3>Task Outputs</h3>
          <div className="task-list">
            {taskData.map((task) => (
              <div key={task.key} className="task-card">
                <div className="task-header">
                  <div className="task-title">
                    <span
                      className={task.output ? "status-dot done" : "status-dot"}
                      aria-hidden="true"
                    />
                    <strong>{task.label}</strong>
                  </div>
                  <button
                    type="button"
                    className="task-toggle"
                    onClick={() => onToggleTask(task.key)}
                  >
                    {expandedTasks[task.key] ? "Collapse" : "Expand"}
                  </button>
                </div>
                {task.output && !expandedTasks[task.key] && (
                  <p>{sanitizeText(task.output.summary || "")}</p>
                )}
                {!task.output && completedTaskLogs[task.key] && <p>Completed</p>}
                {expandedTasks[task.key] && (
                  <pre>
                    {task.output
                      ? safeText(task.output)
                      : sanitizeText((completedTaskLogs[task.key] || []).join("\n"))}
                  </pre>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
