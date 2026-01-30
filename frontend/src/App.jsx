import { useEffect, useMemo, useRef, useState } from "react";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

const calculateDays = (startDate, endDate) => {
  const start = new Date(startDate);
  const end = new Date(endDate);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
    return 0;
  }
  const diffMs = end.getTime() - start.getTime();
  return diffMs > 0 ? Math.ceil(diffMs / (1000 * 60 * 60 * 24)) : 0;
};

export default function App() {
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      text:
        "Welcome to the vacation planner. I can help you plan your dream vacation.",
    },
    {
      role: "assistant",
      text:
        "Tell me about your trip in your own words. Include dates, destination, where you're flying from, and your cabin class (economy, premium economy, business, or first). If you want suggestions, ask me to suggest interesting places.",
    },
  ]);
  const [draft, setDraft] = useState("");
  const [tripText, setTripText] = useState("");
  const [parsed, setParsed] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [jobId, setJobId] = useState("");
  const [logs, setLogs] = useState([]);
  const [logIndex, setLogIndex] = useState(0);
  const [showFullLog, setShowFullLog] = useState(false);
  const [expandedTasks, setExpandedTasks] = useState({});
  const [jobDone, setJobDone] = useState(false);
  const [completedTaskLogs, setCompletedTaskLogs] = useState({});
  const completionMessageSent = useRef(false);
  const taskSequence = [
    "Destination research",
    "Itinerary options",
    "Hotel research",
    "Flight research",
  ];

  const formatResult = (value) => {
    if (!value) return "";
    if (typeof value === "string") return value;
    if (value.raw) return value.raw;
    return JSON.stringify(value, null, 2);
  };

  const taskOutputs = result?.tasks_output || [];
  const taskOutputMap = useMemo(() => {
    const map = {};
    taskOutputs.forEach((task) => {
      map[task.name] = task;
    });
    return map;
  }, [taskOutputs]);
  const taskLabels = {
    destination_research_task: "Destination research",
    itinerary_options_task: "Itinerary options",
    hotel_research_task: "Hotel research",
    flight_research_task: "Flight research",
  };
  const taskData = useMemo(
    () =>
      Object.entries(taskLabels).map(([key, label]) => ({
        key,
        label,
        output: taskOutputMap[key],
      })),
    [taskOutputMap]
  );

  const cleanLogLine = (line) =>
    line.replace(/\x1b\[[0-9;]*m/g, "").replace(/\s+$/g, "");
  const cleanedLogs = useMemo(
    () => logs.map(cleanLogLine).filter((line) => line.trim().length > 0),
    [logs]
  );

  const activeTaskKey = useMemo(() => {
    if (jobDone) return "";
    const keys = Object.keys(taskLabels);
    for (let i = cleanedLogs.length - 1; i >= 0; i -= 1) {
      const line = cleanedLogs[i];
      const match = keys.find((key) => line.includes(key));
      if (match) return match;
      if (line.includes("Flight Research Specialist")) return "flight_research_task";
      if (line.includes("Hotel Research Specialist")) return "hotel_research_task";
      if (line.includes("Travel Research Specialist")) return "destination_research_task";
      if (line.toLowerCase().includes("itinerary option")) return "itinerary_options_task";
    }
    if (cleanedLogs.length) {
      return "destination_research_task";
    }
    return "";
  }, [cleanedLogs, jobDone, taskLabels]);

  const taskLogs = useMemo(() => {
    const map = {};
    taskData.forEach((task) => {
      map[task.key] = [];
    });
    const keys = taskData.map((task) => task.key);
    let currentTask = "";

    const matchTaskFromLine = (line) => {
      const directMatch = keys.find((key) => line.includes(key));
      if (directMatch) return directMatch;
      if (line.includes("Travel Research Specialist")) {
        if (line.toLowerCase().includes("itinerary")) {
          return "itinerary_options_task";
        }
        return "destination_research_task";
      }
      if (line.includes("Hotel Research Specialist")) {
        return "hotel_research_task";
      }
      if (line.includes("Flight Research Specialist")) {
        return "flight_research_task";
      }
      if (line.toLowerCase().includes("itinerary option")) {
        return "itinerary_options_task";
      }
      return "";
    };

    const pushLine = (taskKey, line) => {
      if (!taskKey) return;
      const taskLines = map[taskKey];
      const lastLine = taskLines[taskLines.length - 1];
      if (line !== lastLine) {
        taskLines.push(line);
      }
    };

    cleanedLogs.forEach((line) => {
      const matchingKey = matchTaskFromLine(line);
      if (matchingKey) {
        currentTask = matchingKey;
      }
      if (currentTask) {
        pushLine(currentTask, line);
      }
    });

    return map;
  }, [cleanedLogs, taskData]);

  const appendMessage = (role, text) =>
    setMessages((prev) => [...prev, { role, text }]);

  const toggleTask = (taskKey) => {
    setExpandedTasks((prev) => ({
      ...prev,
      [taskKey]: !prev[taskKey],
    }));
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!draft.trim() || loading) return;

    appendMessage("user", draft);
    const text = draft.trim();
    setDraft("");
    setError("");
    setResult("");
    setLogs([]);
    setLogIndex(0);
    setJobId("");
    setShowFullLog(false);
    completionMessageSent.current = false;
    setJobDone(false);
    setCompletedTaskLogs({});
    setExpandedTasks({
      destination_research_task: true,
      itinerary_options_task: true,
      hotel_research_task: true,
      flight_research_task: true,
    });

    const combinedText = tripText ? `${tripText}\n${text}` : text;
    setTripText(combinedText);

    setLoading(true);
    try {
      const parseResponse = await fetch(`${API_BASE_URL}/parse`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: combinedText }),
      });
      if (!parseResponse.ok) {
        const detail = await parseResponse.json();
        throw new Error(detail?.detail || "Failed to parse trip details.");
      }
      const parseData = await parseResponse.json();
      setParsed(parseData.parsed);

      if (parseData.missing_fields.length) {
        appendMessage(
          "assistant",
          `I still need: ${parseData.missing_fields.join(", ")}.`
        );
        appendMessage(
          "assistant",
          "Please add those details, and I'll keep going."
        );
        return;
      }

      appendMessage("assistant", "Great. Let me research and build options for you.");

      const numDays =
        parseData.parsed.num_days ||
        calculateDays(parseData.parsed.start_date, parseData.parsed.end_date);

      const response = await fetch(`${API_BASE_URL}/plan/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          destination: parseData.parsed.destination,
          start_date: parseData.parsed.start_date,
          end_date: parseData.parsed.end_date,
          num_days: numDays,
          origin: parseData.parsed.origin,
          budget: "mid-range",
          preferences: "",
          interests:
            parseData.parsed.interests || "suggest interesting places",
          cabin: parseData.parsed.cabin || "economy",
        }),
      });
      if (!response.ok) {
        const detail = await response.json();
        throw new Error(detail?.detail || "Failed to generate plan.");
      }
      const data = await response.json();
      setJobId(data.job_id);
    } catch (err) {
      setError(err.message);
      appendMessage("assistant", `Something went wrong: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!jobId) return undefined;

    let cancelled = false;
    const poll = async () => {
      try {
        const response = await fetch(
          `${API_BASE_URL}/plan/status/${jobId}?from_index=${logIndex}`
        );
        if (!response.ok) {
          return;
        }
        const data = await response.json();
        if (cancelled) return;
        if (data.logs?.length) {
          setLogs((prev) => [...prev, ...data.logs]);
          setLogIndex(data.next_index || logIndex + data.logs.length);
        }
        if (data.error) {
          setError(data.error);
          appendMessage("assistant", `Something went wrong: ${data.error}`);
        }
        if (data.done) {
          if (data.result && !completionMessageSent.current) {
            setResult(data.result);
            appendMessage(
              "assistant",
              "Here are your options. Let me know what to adjust!"
            );
            completionMessageSent.current = true;
          }
          setLoading(false);
          setJobDone(true);
          setCompletedTaskLogs(taskLogs);
          setJobId("");
          setExpandedTasks({
            destination_research_task: false,
            itinerary_options_task: false,
            hotel_research_task: false,
            flight_research_task: false,
          });
        }
      } catch (err) {
        if (!cancelled) {
          setError(err.message);
        }
      }
    };

    setLoading(true);
    const interval = setInterval(poll, 1500);
    poll();
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [API_BASE_URL, jobId, logIndex]);

  return (
    <div className="app">
      <header>
        <h1>Vacation Planner</h1>
        <p>Chat with the planner to build your itinerary.</p>
      </header>

      <section className="card chat">
        <div className="messages">
          {messages.map((message, index) => (
            <div key={index} className={`message ${message.role}`}>
              {message.text}
            </div>
          ))}
        </div>

        {error && <div className="error">{error}</div>}
        {loading && (
          <div className="card">
            <div className="processing-header">
              <div>
                <h2>Processing</h2>
                <p>Running tasks in order:</p>
              </div>
              <button
                type="button"
                className="task-toggle"
                onClick={() => setShowFullLog((prev) => !prev)}
              >
                {showFullLog ? "Hide Full Log" : "Show Full Log"}
              </button>
            </div>
            <div className="task-list">
              {taskData.map((task) => (
                <div key={task.key} className="task-card">
                  <div className="task-header">
                    <div className="task-title">
                      {activeTaskKey === task.key ? (
                        <span className="spinner" aria-hidden="true" />
                      ) : (
                        <span className="status-dot" aria-hidden="true" />
                      )}
                      <strong>{task.label}</strong>
                    </div>
                    <button
                      type="button"
                      className="task-toggle"
                      onClick={() => toggleTask(task.key)}
                    >
                      {expandedTasks[task.key] ? "Collapse" : "Expand"}
                    </button>
                  </div>
                  {task.output ? (
                    <pre>{formatResult(task.output)}</pre>
                  ) : (
                    <>
                      {!expandedTasks[task.key] && (
                        <div className="task-latest">
                          {taskLogs[task.key]?.length
                            ? taskLogs[task.key][taskLogs[task.key].length - 1]
                            : activeTaskKey === task.key
                            ? "In progress..."
                            : "Queued..."}
                        </div>
                      )}
                      {expandedTasks[task.key] && (
                        <pre>
                          {taskLogs[task.key]?.length
                            ? taskLogs[task.key].join("\n")
                            : activeTaskKey === task.key
                            ? "In progress..."
                            : "Queued..."}
                        </pre>
                      )}
                    </>
                  )}
                </div>
              ))}
            </div>
            {showFullLog && (
              <pre className="log-output">
                {cleanedLogs.length
                  ? cleanedLogs.join("\n")
                  : "Waiting for logs..."}
              </pre>
            )}
          </div>
        )}
        {parsed && (result || Object.keys(completedTaskLogs).length > 0) && (
          <div className="card">
            <h2>Plan Output</h2>
            {result && <pre>{formatResult(result)}</pre>}
            {(taskOutputs.length > 0 || Object.keys(completedTaskLogs).length > 0) && (
              <>
                <h3>Task Outputs</h3>
                <div className="task-list">
                  {taskData.map((task) => (
                    <div key={task.key} className="task-card">
                      <div className="task-header">
                        <div className="task-title">
                          <span
                            className={
                              task.output ? "status-dot done" : "status-dot"
                            }
                            aria-hidden="true"
                          />
                          <strong>{task.label}</strong>
                        </div>
                        <button
                          type="button"
                          className="task-toggle"
                          onClick={() => toggleTask(task.key)}
                        >
                          {expandedTasks[task.key] ? "Collapse" : "Expand"}
                        </button>
                      </div>
                      {task.output && <p>{task.output.summary}</p>}
                      {!task.output && completedTaskLogs[task.key] && (
                        <p>Completed</p>
                      )}
                      {task.output && !expandedTasks[task.key] && (
                        <div className="task-latest">
                          {formatResult(task.output).split("\n")[0]}
                        </div>
                      )}
                      {expandedTasks[task.key] && (
                        <pre>
                          {task.output
                            ? formatResult(task.output)
                            : (completedTaskLogs[task.key] || []).join("\n")}
                        </pre>
                      )}
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        )}

        <form onSubmit={handleSubmit} className="composer">
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Type your response..."
            disabled={loading}
            rows={3}
          />
          <button type="submit" disabled={loading}>
            Send
          </button>
        </form>
      </section>
    </div>
  );
}
