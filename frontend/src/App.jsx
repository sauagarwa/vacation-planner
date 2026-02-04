import { useEffect, useMemo, useRef, useState } from "react";
import CrewAIPlanCard from "./components/CrewAIPlanCard";
import LangGraphPlanCard from "./components/LangGraphPlanCard";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

const calculateDays = (startDate, endDate) => {
  const start = new Date(startDate);
  const end = new Date(endDate);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
    return 0;
  }
  const diffMs = end.getTime() - start.getTime();
  return diffMs > 0 ? Math.ceil(diffMs / (1000 * 60 * 60 * 24)) : 0;
};

const taskLabels = {
  destination_research_task: "Destination research",
  itinerary_options_task: "Itinerary options",
  hotel_research_task: "Hotel research",
  flight_research_task: "Flight research",
};

const cleanLogLine = (line) =>
  line.replace(/\x1b\[[0-9;]*m/g, "").replace(/\s+$/g, "");

const useTaskState = (logs, result, jobDone) => {
  const taskOutputs = result?.tasks_output || [];
  const taskOutputMap = useMemo(() => {
    const map = {};
    taskOutputs.forEach((task) => {
      map[task.name] = task;
    });
    return map;
  }, [taskOutputs]);

  const taskData = useMemo(
    () =>
      Object.entries(taskLabels).map(([key, label]) => ({
        key,
        label,
        output: taskOutputMap[key],
      })),
    [taskOutputMap]
  );

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
  }, [cleanedLogs, jobDone]);

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

  return {
    taskOutputs,
    taskOutputMap,
    taskData,
    cleanedLogs,
    activeTaskKey,
    taskLogs,
  };
};

export default function App() {
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      text: "Welcome to the vacation planner. I can help you plan your dream vacation.",
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
  const [error, setError] = useState("");
  const [agentMode, setAgentMode] = useState("crewai");

  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [jobId, setJobId] = useState("");
  const [logs, setLogs] = useState([]);
  const [logIndex, setLogIndex] = useState(0);
  const [showFullLog, setShowFullLog] = useState(false);
  const [expandedTasks, setExpandedTasks] = useState({});
  const [jobDone, setJobDone] = useState(false);
  const [completedTaskLogs, setCompletedTaskLogs] = useState({});

  const [langLoading, setLangLoading] = useState(false);
  const [langError, setLangError] = useState("");
  const [langResult, setLangResult] = useState(null);
  const [langJobId, setLangJobId] = useState("");
  const [langLogs, setLangLogs] = useState([]);
  const [langLogIndex, setLangLogIndex] = useState(0);
  const [langShowFullLog, setLangShowFullLog] = useState(false);
  const [langExpandedTasks, setLangExpandedTasks] = useState({});
  const [langJobDone, setLangJobDone] = useState(false);
  const [langCompletedTaskLogs, setLangCompletedTaskLogs] = useState({});

  const completionMessageSent = useRef(false);
  const langCompletionMessageSent = useRef(false);

  const formatResult = (value) => {
    if (!value) return "";
    if (typeof value === "string") return value;
    if (value.raw) return value.raw;
    return JSON.stringify(value, null, 2);
  };

  const sanitizeText = (value) => {
    if (!value) return "";
    return value
      .replace(/```json/gi, "")
      .replace(/```/g, "")
      .replace(/\u00c2/g, "")
      .replace(/\s+\n/g, "\n")
      .trim();
  };

  const crewTasks = useTaskState(logs, result, jobDone);
  const langTasks = useTaskState(langLogs, langResult, langJobDone);

  const appendMessage = (role, text) => setMessages((prev) => [...prev, { role, text }]);

  const toggleTask = (taskKey) => {
    setExpandedTasks((prev) => ({
      ...prev,
      [taskKey]: !prev[taskKey],
    }));
  };

  const resetCrewState = () => {
    setResult(null);
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
  };

  const resetLangState = () => {
    setLangResult(null);
    setLangLogs([]);
    setLangLogIndex(0);
    setLangJobId("");
    setLangShowFullLog(false);
    langCompletionMessageSent.current = false;
    setLangJobDone(false);
    setLangCompletedTaskLogs({});
    setLangExpandedTasks({
      destination_research_task: true,
      itinerary_options_task: true,
      hotel_research_task: true,
      flight_research_task: true,
    });
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    const isBusy = loading || langLoading;
    if (!draft.trim() || isBusy) return;

    appendMessage("user", draft);
    const text = draft.trim();
    setDraft("");
    setError("");
    setLangError("");

    if (agentMode === "crewai") {
      resetCrewState();
    } else {
      resetLangState();
    }

    const combinedText = tripText ? `${tripText}\n${text}` : text;
    setTripText(combinedText);

    if (agentMode === "crewai") setLoading(true);
    else setLangLoading(true);

    try {
      // 1) Parse the trip text
      const parseResponse = await fetch(`${API_BASE_URL}/parse`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: combinedText }),
      });

      if (!parseResponse.ok) {
        const detail = await parseResponse.json().catch(() => ({}));
        throw new Error(detail?.detail || "Failed to parse trip details.");
      }

      const parseData = await parseResponse.json();
      setParsed(parseData.parsed);

      if (parseData.missing_fields?.length) {
        appendMessage("assistant", `I still need: ${parseData.missing_fields.join(", ")}.`);
        appendMessage("assistant", "Please add those details, and I'll keep going.");
        return;
      }

      appendMessage("assistant", "Great. Let me research and build options for you.");

      const numDays =
        parseData.parsed.num_days ||
        calculateDays(parseData.parsed.start_date, parseData.parsed.end_date);

      // 2) Start the job
      const planUrl =
        agentMode === "crewai"
          ? `${API_BASE_URL}/plan/start`
          : `${API_BASE_URL}/langgraph/plan/start`;

      // ✅ recommended approach: do NOT send preferences as ""
      const requestBody = {
        destination: parseData.parsed.destination,
        start_date: parseData.parsed.start_date,
        end_date: parseData.parsed.end_date,
        num_days: numDays,
        origin: parseData.parsed.origin,
        budget: "mid-range",
        interests: parseData.parsed.interests || "suggest interesting places",
        cabin: parseData.parsed.cabin || "economy",
      };

      // Only send preferences if present
      if (parseData.parsed.preferences?.trim()) {
        requestBody.preferences = parseData.parsed.preferences.trim();
      }

      const response = await fetch(planUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody),
      });

      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail?.detail || "Failed to generate plan.");
      }

      const data = await response.json();
      if (agentMode === "crewai") setJobId(data.job_id);
      else setLangJobId(data.job_id);
    } catch (err) {
      const msg = err?.message || String(err);
      if (agentMode === "crewai") setError(msg);
      else setLangError(msg);
      appendMessage("assistant", `Something went wrong: ${msg}`);
    } finally {
      if (agentMode === "crewai") setLoading(false);
      else setLangLoading(false);
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
        if (!response.ok) return;

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
            appendMessage("assistant", "Here are your options. Let me know what to adjust!");
            completionMessageSent.current = true;
          }
          setLoading(false);
          setJobDone(true);
          setCompletedTaskLogs(crewTasks.taskLogs);
          setJobId("");
          setExpandedTasks({
            destination_research_task: false,
            itinerary_options_task: false,
            hotel_research_task: false,
            flight_research_task: false,
          });
        }
      } catch (err) {
        if (!cancelled) setError(err?.message || String(err));
      }
    };

    setLoading(true);
    const interval = setInterval(poll, 1500);
    poll();
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [API_BASE_URL, crewTasks.taskLogs, jobId, logIndex]);

  useEffect(() => {
    if (!langJobId) return undefined;

    let cancelled = false;
    const poll = async () => {
      try {
        const response = await fetch(
          `${API_BASE_URL}/langgraph/plan/status/${langJobId}?from_index=${langLogIndex}`
        );
        if (!response.ok) return;

        const data = await response.json();
        if (cancelled) return;

        if (data.logs?.length) {
          setLangLogs((prev) => [...prev, ...data.logs]);
          setLangLogIndex(data.next_index || langLogIndex + data.logs.length);
        }
        if (data.partial_result) {
          setLangResult(data.partial_result);
        }

        if (data.error) {
          setLangError(data.error);
          appendMessage("assistant", `Something went wrong: ${data.error}`);
        }

        if (data.done) {
          if (data.result && !langCompletionMessageSent.current) {
            setLangResult(data.result);
            appendMessage("assistant", "Here are your options. Let me know what to adjust!");
            langCompletionMessageSent.current = true;
          }
          setLangLoading(false);
          setLangJobDone(true);
          setLangCompletedTaskLogs(langTasks.taskLogs);
          setLangJobId("");
          setLangExpandedTasks({
            destination_research_task: false,
            itinerary_options_task: false,
            hotel_research_task: false,
            flight_research_task: false,
          });
        }
      } catch (err) {
        if (!cancelled) setLangError(err?.message || String(err));
      }
    };

    setLangLoading(true);
    const interval = setInterval(poll, 1500);
    poll();
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [API_BASE_URL, langJobId, langLogIndex, langTasks.taskLogs]);

  return (
    <div className="app">
      <header>
        <h1>Vacation Planner</h1>
        <p>Chat with the planner to build your itinerary.</p>
        <div className="mode-toggle">
          <label htmlFor="agent-mode">Agent Implementation</label>
          <select
            id="agent-mode"
            value={agentMode}
            onChange={(event) => setAgentMode(event.target.value)}
            disabled={loading || langLoading}
          >
            <option value="crewai">vacation-planner [CrewAI]</option>
            <option value="langgraph">vacation-planner [LangGraph]</option>
          </select>
        </div>
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
        {langError && <div className="error">{langError}</div>}

        {loading && (
          <div className="card">
            <div className="processing-header">
              <div>
                <h2>Processing (CrewAI)</h2>
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
              {crewTasks.taskData.map((task) => (
                <div key={task.key} className="task-card">
                  <div className="task-header">
                    <div className="task-title">
                      {crewTasks.activeTaskKey === task.key ? (
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
                          {crewTasks.taskLogs[task.key]?.length
                            ? crewTasks.taskLogs[task.key][
                                crewTasks.taskLogs[task.key].length - 1
                              ]
                            : crewTasks.activeTaskKey === task.key
                            ? "In progress..."
                            : "Queued..."}
                        </div>
                      )}
                      {expandedTasks[task.key] && (
                        <pre>
                          {crewTasks.taskLogs[task.key]?.length
                            ? crewTasks.taskLogs[task.key].join("\n")
                            : crewTasks.activeTaskKey === task.key
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
                {crewTasks.cleanedLogs.length
                  ? crewTasks.cleanedLogs.join("\n")
                  : "Waiting for logs..."}
              </pre>
            )}
          </div>
        )}

        {langLoading && (
          <div className="card">
            <div className="processing-header">
              <div>
                <h2>Processing (LangGraph)</h2>
                <p>Running tasks in order:</p>
              </div>
              <button
                type="button"
                className="task-toggle"
                onClick={() => setLangShowFullLog((prev) => !prev)}
              >
                {langShowFullLog ? "Hide Full Log" : "Show Full Log"}
              </button>
            </div>

            <div className="task-list">
              {langTasks.taskData.map((task) => (
                <div key={task.key} className="task-card">
                  <div className="task-header">
                    <div className="task-title">
                      {langTasks.activeTaskKey === task.key ? (
                        <span className="spinner" aria-hidden="true" />
                      ) : (
                        <span className="status-dot" aria-hidden="true" />
                      )}
                      <strong>{task.label}</strong>
                    </div>
                    <button
                      type="button"
                      className="task-toggle"
                      onClick={() =>
                        setLangExpandedTasks((prev) => ({
                          ...prev,
                          [task.key]: !prev[task.key],
                        }))
                      }
                    >
                      {langExpandedTasks[task.key] ? "Collapse" : "Expand"}
                    </button>
                  </div>

                  {task.output ? (
                    <pre>{formatResult(task.output)}</pre>
                  ) : (
                    <>
                      {!langExpandedTasks[task.key] && (
                        <div className="task-latest">
                          {langTasks.taskLogs[task.key]?.length
                            ? langTasks.taskLogs[task.key][
                                langTasks.taskLogs[task.key].length - 1
                              ]
                            : langTasks.activeTaskKey === task.key
                            ? "In progress..."
                            : "Queued..."}
                        </div>
                      )}
                      {langExpandedTasks[task.key] && (
                        <pre>
                          {langTasks.taskLogs[task.key]?.length
                            ? langTasks.taskLogs[task.key].join("\n")
                            : langTasks.activeTaskKey === task.key
                            ? "In progress..."
                            : "Queued..."}
                        </pre>
                      )}
                    </>
                  )}
                </div>
              ))}
            </div>

            {langShowFullLog && (
              <pre className="log-output">
                {langTasks.cleanedLogs.length
                  ? langTasks.cleanedLogs.join("\n")
                  : "Waiting for logs..."}
              </pre>
            )}
          </div>
        )}

        {parsed && agentMode === "crewai" && (
          <CrewAIPlanCard
            result={result}
            taskData={crewTasks.taskData}
            taskOutputs={crewTasks.taskOutputs}
            completedTaskLogs={completedTaskLogs}
            expandedTasks={expandedTasks}
            onToggleTask={toggleTask}
            formatResult={formatResult}
            sanitizeText={sanitizeText}
          />
        )}

        {parsed && agentMode === "langgraph" && (
          <LangGraphPlanCard
            result={langResult}
            taskData={langTasks.taskData}
            taskOutputs={langTasks.taskOutputs}
            completedTaskLogs={langCompletedTaskLogs}
            expandedTasks={langExpandedTasks}
            onToggleTask={(taskKey) =>
              setLangExpandedTasks((prev) => ({
                ...prev,
                [taskKey]: !prev[taskKey],
              }))
            }
            formatResult={formatResult}
            sanitizeText={sanitizeText}
          />
        )}

        <form onSubmit={handleSubmit} className="composer">
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Type your response..."
            disabled={loading || langLoading}
            rows={3}
          />
          <button type="submit" disabled={loading || langLoading}>
            Send
          </button>
        </form>
      </section>
    </div>
  );
}
