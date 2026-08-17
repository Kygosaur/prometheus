import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";

type Source = { document: string; location: string; score: number };
type Intent = { general: boolean; rag: boolean; planning: boolean; method?: string };
type ScheduleTask = { task: string; start_time?: string; end_time?: string; workers: string[]; machine: string; vehicle?: string };
type ScheduleMeta = { id?: string; tasks: ScheduleTask[]; solver_status: string; makespan_hours: number; approval_status: string };
type Timing = Record<string, number>;
type Message = { id: string; role: "user" | "assistant"; content: string; sources?: Source[]; warnings?: string[]; intents?: Intent; schedule?: ScheduleMeta; timing?: Timing };
type Status = { ready: boolean; model: string; workspace: string; chunks: number; skipped: number; privacy: string };

const suggestions = [
  "Summarize the files available in this workspace.",
  "What safety requirements are stated for welding?",
  "Which machines and workers are available?",
];

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [status, setStatus] = useState<Status | null>(null);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { loadStatus(); }, []);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, stage]);

  async function loadStatus() {
    try {
      const response = await fetch("/api/status");
      if (!response.ok) throw new Error("The local service is unavailable.");
      setStatus(await response.json());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not reach the local service.");
    }
  }

  async function reindex() {
    setStage("Refreshing the local index");
    try {
      const response = await fetch("/api/reindex", { method: "POST" });
      if (!response.ok) throw new Error("Could not refresh the workspace.");
      await loadStatus();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not refresh the workspace.");
    } finally { setStage(""); }
  }

  async function ask(text = question) {
    const clean = text.trim();
    if (!clean || busy) return;
    const userMessage: Message = { id: crypto.randomUUID(), role: "user", content: clean };
    const prior = [...messages, userMessage];
    setMessages(prior);
    setQuestion("");
    setBusy(true);
    setError("");
    setElapsed(0);
    setStage("Searching local files");
    const started = performance.now();
    const timer = window.setInterval(() => setElapsed(Math.floor((performance.now() - started) / 1000)), 1000);
    try {
      const history = messages.slice(-8).map(({ role, content }) => ({ role, content }));
      const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: clean, history }),
      });
      if (!response.ok || !response.body) throw new Error("The assistant could not start this request.");
      await readEvents(response.body, (event, data) => {
        if (event === "status") setStage(data.message as string);
        if (event === "progress") setElapsed(data.elapsed_seconds as number);
        if (event === "complete") {
          setMessages(current => [...current, {
            id: crypto.randomUUID(), role: "assistant", content: data.answer as string,
            sources: data.sources as Source[], warnings: data.warnings as string[], intents: data.intents as Intent,
            schedule: data.schedule as ScheduleMeta | undefined, timing: data.timing as Timing,
          }]);
          setStage("");
        }
        if (event === "error") throw new Error(data.message as string);
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The local model could not answer.");
      setStage("");
    } finally {
      window.clearInterval(timer);
      setBusy(false);
      textareaRef.current?.focus();
    }
  }

  function submit(event: FormEvent) { event.preventDefault(); void ask(); }
  function keyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void ask(); }
  }

  return (
    <div className="app-shell">
      <button className="mobile-menu" onClick={() => setSidebarOpen(true)} aria-label="Open workspace panel">Menu</button>
      {sidebarOpen && <button className="scrim" onClick={() => setSidebarOpen(false)} aria-label="Close workspace panel" />}
      <aside className={sidebarOpen ? "sidebar open" : "sidebar"}>
        <div className="brand-row">
          <div className="brand-mark">W</div>
          <div><strong>Workshop</strong><span>Local planning intelligence</span></div>
          <button className="close-menu" onClick={() => setSidebarOpen(false)} aria-label="Close panel">×</button>
        </div>
        <section className="privacy-card">
          <div className="eyebrow"><span className="status-dot" /> Private session</div>
          <h2>Your work stays here.</h2>
          <p>Files are searched locally and sent only to the Kimi process on this machine.</p>
        </section>
        <section className="workspace-card">
          <div className="section-heading"><span>Workspace</span><button onClick={reindex} disabled={Boolean(stage)}>Refresh</button></div>
          <div className="workspace-name"><span className="folder-mark">▰</span><div><strong>{status?.workspace ?? "Starting…"}</strong><small>{status?.chunks ?? 0} indexed excerpts</small></div></div>
          {status && status.skipped > 0 && <p className="muted">{status.skipped} files safely skipped</p>}
        </section>
        <div className="model-row"><span>Local model</span><strong>{status?.model ?? "—"}</strong></div>
        <div className="sidebar-footer"><span className="lock-mark">●</span><span>Loopback only<br/><small>No cloud connection</small></span></div>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <div><span className="eyebrow">Read-only assistant</span><h1>Ask your workspace</h1></div>
          <div className="connection"><span className={status?.ready ? "status-dot" : "status-dot waiting"}/>{status?.ready ? "Ready" : "Starting"}</div>
        </header>

        <div className="conversation" aria-live="polite">
          {messages.length === 0 ? (
            <section className="welcome">
              <div className="welcome-orbit"><div className="brand-mark large">W</div></div>
              <p className="eyebrow">Private by design</p>
              <h2>What would you like to understand?</h2>
              <p className="welcome-copy">Ask about schedules, resources, SOPs, or anything in your approved workspace.</p>
              <div className="suggestions">
                {suggestions.map((item, index) => <button key={item} onClick={() => ask(item)}><span>0{index + 1}</span>{item}</button>)}
              </div>
            </section>
          ) : messages.map(message => (
            <article className={`message ${message.role}`} key={message.id}>
              <div className="message-label">{message.role === "user" ? "You" : "Kimi · local"}</div>
              <div className="message-body"><ReactMarkdown>{message.content}</ReactMarkdown></div>
              {message.schedule && <section className="schedule-card">
                <div className="metadata-heading"><strong>Draft schedule</strong><span>{message.schedule.approval_status}</span></div>
                {message.schedule.tasks.map(task => <div className="schedule-task" key={task.task}>
                  <div><strong>{task.task}</strong><span>{task.start_time ?? "Start pending"} – {task.end_time ?? "End pending"}</span></div>
                  <small>{task.workers.join(", ")} · {task.machine}{task.vehicle ? ` · ${task.vehicle}` : ""}</small>
                </div>)}
                <div className="schedule-summary">
                  <span>Solver <strong>{message.schedule.solver_status}</strong></span>
                  <span>Makespan <strong>{message.schedule.makespan_hours}h</strong></span>
                  <span>Approval <strong>{message.schedule.approval_status}</strong></span>
                </div>
              </section>}
              {message.sources && message.sources.length > 0 && <div className="sources">
                <span>Sources</span>{message.sources.map((source, index) => <span className="source-pill" key={`${source.document}-${source.location}-${index}`}>{source.document} · {source.location}</span>)}
              </div>}
              {message.warnings && message.warnings.length > 0 && <div className="warnings"><strong>Warnings</strong>{message.warnings.map(item => <span key={item}>{item}</span>)}</div>}
              {message.intents && <div className="intent-row">Routes: {(["general", "rag", "planning"] as const).filter(key => message.intents?.[key]).join(" + ")}</div>}
              {message.timing && <details className="timing"><summary>Completed in {message.timing.total_seconds.toFixed(1)} seconds</summary>
                <div>{Object.entries(message.timing).filter(([key]) => key !== "total_seconds").map(([key, value]) => <span key={key}>{key.replaceAll("_", " ")}: {value.toFixed(2)}s</span>)}</div>
              </details>}
            </article>
          ))}
          {busy && <div className="thinking-card"><div className="thinking-dots"><i/><i/><i/></div><div><strong>{stage}</strong><span>{elapsed >= 10 ? `Still working · ${elapsed}s elapsed` : "Working entirely on this machine"}</span></div></div>}
          {error && <div className="error-card"><strong>Something needs attention</strong><span>{error}</span><button onClick={() => setError("")}>Dismiss</button></div>}
          <div ref={bottomRef}/>
        </div>

        <div className="composer-wrap">
          <form className="composer" onSubmit={submit}>
            <textarea ref={textareaRef} rows={1} value={question} onChange={event => setQuestion(event.target.value)} onKeyDown={keyDown} placeholder="Ask about your local work files…" disabled={busy} aria-label="Question" />
            <button className="send" type="submit" disabled={busy || !question.trim()} aria-label="Send question">↑</button>
          </form>
          <p>Kimi can make mistakes. Verify critical planning and safety information.</p>
        </div>
      </main>
    </div>
  );
}

async function readEvents(stream: ReadableStream<Uint8Array>, onEvent: (event: string, data: Record<string, unknown>) => void) {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() || "";
    for (const block of blocks) {
      let event = "message"; let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (data) onEvent(event, JSON.parse(data));
    }
    if (done) break;
  }
}
