import { useState, useEffect, useRef } from "react";
import { fetchTasks, fetchTraces, fetchArchive } from "./api";
import TrendChart from "./TrendChart";

export default function App() {
  const [tasks, setTasks] = useState({});
  const [traces, setTraces] = useState([]);
  const [archive, setArchive] = useState([]);
  const [output, setOutput] = useState("");
  const [report, setReport] = useState(null);
  const [running, setRunning] = useState("");
  const [traceModal, setTraceModal] = useState(null);
  const outputRef = useRef(null);

  useEffect(() => {
    fetchTasks().then(setTasks);
    fetchTraces().then(setTraces);
    fetchArchive("portfolio-review").then(setArchive);
  }, []);

  useEffect(() => {
    if (outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight;
    }
  }, [output]);

  function handleRun(name) {
    setRunning(name);
    setOutput("");
    setReport(null);
    const es = new EventSource(`/api/run/${name}`);

    es.onmessage = (e) => {
      setOutput((prev) => prev + e.data + "\n");
    };

    es.addEventListener("done", (e) => {
      const code = parseInt(e.data.split("=")[1] || "1");
      setOutput(
        (prev) => prev + `\n${code === 0 ? "✅ 完成" : `❌ 退出码: ${code}`}\n`,
      );
      es.close();
      setRunning("");
      fetchTraces().then(setTraces);
      fetchArchive("portfolio-review").then(setArchive);
      fetch(`/api/report/${name}`)
        .then((r) => r.json())
        .then(setReport);
    });

    es.onerror = () => {
      es.close();
      setOutput((prev) => prev + "\n❌ 连接断开\n");
      setRunning("");
    };
  }

  async function viewTrace(id) {
    try {
      const r = await fetch(`/api/traces?id=${id}`);
      if (!r.ok) throw new Error(r.status);
      setTraceModal(await r.json());
    } catch (e) {
      alert("无法加载日志: " + e.message);
    }
  }

  function verdictClass(v) {
    if (!v) return "";
    if (v.includes("PASS")) return "pass";
    if (v.includes("FAIL")) return "fail";
    return "partial";
  }

  return (
    <div className="app">
      <header className="header">
        <h1>📊 PSE Dashboard</h1>
      </header>

      <div className="grid">
        <div className={`card${running ? " full" : ""}`}>
          <h2>任务控制</h2>
          <div className="btn-row">
            {Object.entries(tasks).map(([name, info]) => (
              <button
                key={name}
                className="btn btn-primary"
                disabled={!!running}
                onClick={() => handleRun(name)}
              >
                {running === name ? "⏳" : "▶"} {info.label}
              </button>
            ))}
          </div>
          {running && (
            <p style={{ color: "#666", fontSize: "0.85em", marginBottom: 8 }}>
              ⏳ 运行中，日志实时输出...
            </p>
          )}
          {output && (
            <pre className="output" ref={outputRef}>
              {output}
            </pre>
          )}
        </div>

        <div className="card">
          <h2>资产趋势</h2>
          <div style={{ height: 250 }}>
            <TrendChart data={archive} />
          </div>
        </div>

        {report && (
          <div className="card full">
            <h2>
              最新报告{" "}
              <span className="subtitle">{report.file}</span>
            </h2>
            <div
              className="report-body"
              dangerouslySetInnerHTML={{ __html: report.html }}
            />
          </div>
        )}

        <div className="card full">
          <h2>执行历史</h2>
          <table>
            <thead>
              <tr>
                <th>时间</th>
                <th>判决</th>
                <th>循环</th>
                <th>Tokens</th>
                <th>日志</th>
              </tr>
            </thead>
            <tbody>
              {traces.map((t) => (
                <tr key={t.id}>
                  <td>{t.time}</td>
                  <td className={verdictClass(t.verdict)}>{t.verdict}</td>
                  <td>{t.cycles || "-"}</td>
                  <td>{(t.tokens || 0).toLocaleString()}</td>
                  <td>
                    <button
                      className="btn btn-sm"
                      onClick={() => viewTrace(t.id)}
                    >
                      📋
                    </button>
                  </td>
                </tr>
              ))}
              {!traces.length && (
                <tr>
                  <td colSpan={5} style={{ color: "#999" }}>
                    暂无记录
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {traceModal && (
        <div className="modal-overlay" onClick={() => setTraceModal(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>执行日志</h3>
              <button className="btn btn-sm" onClick={() => setTraceModal(null)}>
                ✕
              </button>
            </div>
            <div className="modal-body">
              <div className="trace-meta">
                <span>判决: <strong className={verdictClass(traceModal.verdict)}>{traceModal.verdict}</strong></span>
                <span>循环: {traceModal.total_cycles} 次</span>
                <span>Tokens: {traceModal.total_tokens?.toLocaleString()}</span>
                <span>时间: {traceModal.started_at?.slice(0,16)}</span>
              </div>
              {traceModal.cycles?.length > 0 ? (
                traceModal.cycles.map((c, i) => (
                  <details key={i} className="cycle-detail">
                    <summary>
                      第 {c.cycle} 次循环 - {c.outcome}
                      <span className="cycle-tokens">
                        {(c.token?.total_prompt || 0) + (c.token?.total_completion || 0)} tokens
                      </span>
                    </summary>
                    <pre className="verdict-text">{c.verdict_summary}</pre>
                    {c.messages?.length > 0 && (
                      <div className="msg-list">
                        <p className="msg-count">📜 完整对话 ({c.messages.length} 条)</p>
                        {c.messages.map((m, j) => (
                          <div key={j} className="msg-item">
                            <span className="msg-source">{m.source}</span>
                            <pre className="msg-body">{m.content}</pre>
                          </div>
                        ))}
                      </div>
                    )}
                    <div className="cycle-stats">
                      {c.token?.agents && Object.entries(c.token.agents).map(([name, s]) => (
                        <span key={name}>{name}: {s.rounds}r / {s.prompt_tokens + s.completion_tokens}t</span>
                      ))}
                    </div>
                  </details>
                ))
              ) : (
                <p style={{color:"#999"}}>无详细循环记录</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
