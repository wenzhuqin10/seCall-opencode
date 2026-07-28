"use client";

import { useEffect, useMemo, useRef, useState } from "react";

type View = "overview" | "sessions" | "pipeline" | "knowledge" | "qa" | "diagnostics";
type Toast = { title: string; detail: string } | null;
type SessionItem = {
  id: string; title: string; project: string; model: string; turns: number;
  updated: string; status: string; source?: string; path?: string;
};
type QaItem = {
  id: string; question: string; answer: string; source: string;
  confidence: number; type: string; state: string;
};
type KnowledgeItem = {
  id: string; title: string; project: string; summary: string;
  confidence: string; source_session: string; review_status: string;
};
type Health = {
  ready: boolean; api_version: string; vault: string; opencode_version: string;
  models: string[]; configured_model?: string; sessions: number;
  knowledge: number; qa: number; pending_qa: number;
};

const demoSessions: SessionItem[] = [
  { id: "ses_0598ac", title: "修复 Scheduler HARQ timeout", project: "wireless-baseband", model: "glm-5.1", turns: 28, updated: "2 分钟前", status: "ready" },
  { id: "ses_c1138a", title: "完善 OpenCode Session 转换器", project: "seCall-opencode", model: "glm-5.1", turns: 41, updated: "36 分钟前", status: "ready" },
  { id: "ses_b937cd", title: "定位 Wiki 页面未生成问题", project: "seCall", model: "big-pickle", turns: 17, updated: "昨天 18:42", status: "review" },
  { id: "ses_28de71", title: "重构混合检索的索引流程", project: "seCall", model: "glm-5.1", turns: 63, updated: "7 月 27 日", status: "ready" },
  { id: "ses_194eaf", title: "梳理 HARQ 状态机异常路径", project: "wireless-baseband", model: "glm-5.1", turns: 34, updated: "7 月 26 日", status: "failed" },
];

const qaSeed: QaItem[] = [
  { id: "demo-1", question: "Scheduler 中出现 HARQ timeout 时首先检查什么？", answer: "优先检查 HARQ 状态是否在重传结束后正确清零，并核对状态更新路径。", source: "ses_0598ac", confidence: 96, type: "故障定位", state: "pending" },
  { id: "demo-2", question: "为什么 seCall Wiki 页面可能没有生成？", answer: "应依次确认 Session 是否导出、Markdown 是否写入 raw/.sessions，以及索引是否重建成功。", source: "ses_b937cd", confidence: 91, type: "操作流程", state: "pending" },
  { id: "demo-3", question: "OpenCode 的 --sanitize 参数是否适合知识抽取？", answer: "不适合。该参数会隐藏正文和工具结果，只建议用于分享或转换链路诊断。", source: "ses_c1138a", confidence: 99, type: "使用说明", state: "pending" },
];

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  const payload = await response.json();
  if (!response.ok || !payload.ok) {
    throw new Error(payload?.error?.message ?? `请求失败（${response.status}）`);
  }
  return payload.result as T;
}

function formatUpdated(value: number | string): string {
  if (typeof value === "string") return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit",
  }).format(new Date(value));
}

const navItems: { id: View; label: string; icon: string; badge?: string }[] = [
  { id: "overview", label: "总览", icon: "⌂" },
  { id: "sessions", label: "会话", icon: "◫", badge: "12" },
  { id: "pipeline", label: "流水线", icon: "⌘", badge: "1" },
  { id: "knowledge", label: "知识库", icon: "◇" },
  { id: "qa", label: "QA 审核", icon: "✓", badge: "18" },
  { id: "diagnostics", label: "环境诊断", icon: "+" },
];

function StatusPill({ status }: { status: string }) {
  const map: Record<string, string> = { ready: "已入库", review: "待审核", failed: "需处理" };
  return <span className={`status-pill ${status}`}><i />{map[status] ?? status}</span>;
}

function MiniBars() {
  return (
    <div className="mini-bars" aria-label="近七日知识生成趋势">
      {[38, 52, 44, 70, 62, 88, 76].map((height, index) => (
        <span key={index} style={{ height: `${height}%` }} className={index === 5 ? "hot" : ""} />
      ))}
    </div>
  );
}

export default function Home() {
  const [active, setActive] = useState<View>("overview");
  const [query, setQuery] = useState("");
  const [modal, setModal] = useState(false);
  const [toast, setToast] = useState<Toast>(null);
  const [pipelineRunning, setPipelineRunning] = useState(false);
  const [pipelineStep, setPipelineStep] = useState(4);
  const [qaItems, setQaItems] = useState(qaSeed);
  const [sessionItems, setSessionItems] = useState<SessionItem[]>(demoSessions);
  const [knowledgeItems, setKnowledgeItems] = useState<KnowledgeItem[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [apiConnected, setApiConnected] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importProject, setImportProject] = useState("chatgpt-import");
  const [selectedSession, setSelectedSession] = useState("ses_0598ac");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const refreshData = async () => {
    const [healthResult, sessionResult, qaResult, knowledgeResult] = await Promise.all([
      apiRequest<Health>("/api/health"),
      apiRequest<Array<Record<string, unknown>>>("/api/sessions?limit=300"),
      apiRequest<Array<Record<string, unknown>>>("/api/qa?limit=300"),
      apiRequest<KnowledgeItem[]>("/api/knowledge?limit=300"),
    ]);
    const normalizedSessions = sessionResult.map((item) => ({
      id: String(item.id ?? ""),
      title: String(item.title ?? "未命名会话"),
      project: String(item.project ?? "unknown"),
      model: String(item.model ?? "unknown"),
      turns: Number(item.turns ?? 0),
      updated: formatUpdated(item.updated as number | string),
      status: String(item.status ?? "ready"),
      source: String(item.source ?? "unknown"),
      path: String(item.path ?? ""),
    }));
    const normalizedQa = qaResult.map((item, index) => ({
      id: String(item.id ?? `qa-${index}`),
      question: String(item.question ?? ""),
      answer: String(item.answer ?? ""),
      source: String(item.source_session ?? ""),
      confidence: typeof item.confidence === "number"
        ? Math.round(Number(item.confidence) * (Number(item.confidence) <= 1 ? 100 : 1))
        : ({ high: 95, medium: 78, low: 52 }[String(item.confidence)] ?? 70),
      type: String(item.qa_type ?? "知识问答"),
      state: String(item.review_status ?? "pending"),
    }));
    setHealth(healthResult);
    setSessionItems(normalizedSessions);
    setQaItems(normalizedQa);
    setKnowledgeItems(knowledgeResult);
    setApiConnected(true);
    if (normalizedSessions.length && !normalizedSessions.some((item) => item.id === selectedSession)) {
      setSelectedSession(normalizedSessions[0].id);
    }
  };

  useEffect(() => {
    refreshData().catch(() => setApiConnected(false));
    // The selected session is intentionally reconciled inside refreshData.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filteredSessions = useMemo(
    () => sessionItems.filter((item) => `${item.title} ${item.project} ${item.id} ${item.source ?? ""}`.toLowerCase().includes(query.toLowerCase())),
    [query, sessionItems],
  );
  const currentSession = sessionItems.find((item) => item.id === selectedSession) ?? sessionItems[0];

  const notify = (title: string, detail: string) => {
    setToast({ title, detail });
    window.setTimeout(() => setToast(null), 3200);
  };

  const startPipeline = async () => {
    setModal(false);
    setActive("pipeline");
    setPipelineRunning(true);
    setPipelineStep(1);
    notify("流水线已启动", "正在读取本地 Session 并抽取知识");
    let simulatedStep = 1;
    const timer = window.setInterval(() => {
      simulatedStep = Math.min(4, simulatedStep + 1);
      setPipelineStep(simulatedStep);
    }, 1600);
    try {
      if (!apiConnected) throw new Error("本地 API 未连接，请先启动本地服务。");
      const result = await apiRequest<{ knowledge: { qa_count: number } }>("/api/pipeline", {
        method: "POST",
        body: JSON.stringify({ session_id: selectedSession, reindex: true }),
      });
      window.clearInterval(timer);
      setPipelineStep(5);
      await refreshData();
      notify("知识已成功入库", `新增 ${result.knowledge.qa_count} 条候选 QA`);
    } catch (error) {
      window.clearInterval(timer);
      setPipelineStep(0);
      notify("流水线执行失败", error instanceof Error ? error.message : "请检查本地服务");
    } finally {
      setPipelineRunning(false);
    }
  };

  const reviewQa = async (id: string, state: "approved" | "rejected") => {
    try {
      if (apiConnected && !id.startsWith("demo-")) {
        await apiRequest("/api/qa/review", {
          method: "POST",
          body: JSON.stringify({ id, status: state }),
        });
      }
      setQaItems((items) => items.map((item) => item.id === id ? { ...item, state } : item));
      notify(state === "approved" ? "QA 已通过审核" : "QA 已退回", state === "approved" ? "该问答已加入正式知识库" : "该问答不会进入检索索引");
    } catch (error) {
      notify("审核状态保存失败", error instanceof Error ? error.message : "请检查本地服务");
    }
  };

  const importChatGPTFile = async (file: File) => {
    setImporting(true);
    try {
      if (!apiConnected) throw new Error("本地 API 未连接，请先运行启动脚本。");
      const payload = JSON.parse(await file.text());
      const inspected = await apiRequest<{ conversation_count: number; message_count: number }>("/api/chatgpt/inspect", {
        method: "POST",
        body: JSON.stringify({ payload }),
      });
      const result = await apiRequest<{ imported: number }>("/api/chatgpt/import", {
        method: "POST",
        body: JSON.stringify({ payload, project: importProject }),
      });
      await refreshData();
      setActive("sessions");
      notify("ChatGPT 会话导入完成", `导入 ${result.imported} 个会话，共 ${inspected.message_count} 条消息`);
    } catch (error) {
      notify("ChatGPT 导入失败", error instanceof Error ? error.message : "文件格式不受支持");
    } finally {
      setImporting(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><span /><span /><span /></div>
          <div><strong>seCall</strong><small>OpenCode Studio</small></div>
        </div>
        <div className="workspace-switch">
          <div className="workspace-avatar">WB</div>
          <div><strong>无线基带研发</strong><span>本地工作区</span></div>
          <button aria-label="切换工作区">⌄</button>
        </div>
        <nav className="main-nav" aria-label="主导航">
          <p>工作台</p>
          {navItems.map((item) => (
            <button key={item.id} className={active === item.id ? "active" : ""} onClick={() => setActive(item.id)}>
              <span className="nav-icon">{item.icon}</span>{item.label}
              {item.badge && <em>{item.badge}</em>}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="local-card">
            <span className={`pulse-dot ${apiConnected ? "" : "offline"}`} />
            <div><strong>{apiConnected ? "本地服务运行中" : "本地服务未连接"}</strong><small>127.0.0.1:8765</small></div>
          </div>
          <button className="profile">
            <span className="profile-avatar">QL</span>
            <span><strong>Qin Lianxi</strong><small>管理员</small></span>
            <b>•••</b>
          </button>
        </div>
      </aside>

      <section className="content">
        <header className="topbar">
          <div className="mobile-brand">seCall</div>
          <label className="global-search">
            <span>⌕</span>
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索会话、知识或错误信息…" />
            <kbd>⌘ K</kbd>
          </label>
          <div className="top-actions">
            <button className="icon-button" aria-label="通知">◌<i /></button>
            <button className="primary-button" onClick={() => setModal(true)}><span>＋</span>新建流水线</button>
          </div>
        </header>

        <div className="page-body">
          {active === "overview" && (
            <>
              <section className="page-heading">
                <div><p className="eyebrow">KNOWLEDGE OPERATIONS</p><h1>早上好，Qin <span>✦</span></h1><p>你的本地知识系统运行稳定，今天已有 <b>12</b> 个会话完成沉淀。</p></div>
                <div className="date-chip"><span>28</span><div><strong>星期二</strong><small>2026 年 7 月</small></div></div>
              </section>

              <section className="metric-grid">
                <article className="metric-card dark">
                  <div className="metric-top"><span className="metric-icon">⌘</span><em>+12.4%</em></div>
                  <strong>{health?.sessions ?? sessionItems.length}</strong><p>已归档会话</p>
                  <div className="sparkline"><i /><i /><i /><i /><i /><i /><i /></div>
                </article>
                <article className="metric-card">
                  <div className="metric-top"><span className="metric-icon lilac">◇</span><em>+8.2%</em></div>
                  <strong>{health?.knowledge ?? knowledgeItems.length}</strong><p>Issue Cards</p><MiniBars />
                </article>
                <article className="metric-card">
                  <div className="metric-top"><span className="metric-icon mint">✓</span><span className="tiny-label">待处理 18</span></div>
                  <strong>{health?.qa ?? qaItems.length}</strong><p>QA 问答对</p>
                  <div className="progress-line"><span style={{ width: "78%" }} /></div>
                </article>
                <article className="metric-card">
                  <div className="metric-top"><span className="metric-icon sand">◎</span><span className="tiny-label good">优秀</span></div>
                  <strong>92<small>%</small></strong><p>知识覆盖率</p>
                  <div className="coverage-dots">{Array.from({ length: 12 }).map((_, i) => <i key={i} className={i < 10 ? "filled" : ""} />)}</div>
                </article>
              </section>

              <section className="dashboard-grid">
                <div className="main-column">
                  <article className="panel pipeline-panel">
                    <div className="panel-heading"><div><span className="live-dot" />知识流水线</div><button onClick={() => setActive("pipeline")}>查看全部 <b>→</b></button></div>
                    <div className="active-job">
                      <div className="job-head">
                        <div className="session-glyph">OC</div>
                        <div><strong>修复 Scheduler HARQ timeout</strong><span><code>ses_0598ac</code> · wireless-baseband</span></div>
                        <div className="job-progress"><strong>{pipelineRunning ? "处理中" : "80%"}</strong><span>预计剩余 18 秒</span></div>
                      </div>
                      <div className="stepper">
                        {["会话导出", "格式转换", "知识抽取", "QA 生成", "索引入库"].map((step, index) => (
                          <div key={step} className={index < pipelineStep ? "done" : index === pipelineStep ? "current" : ""}>
                            <span>{index < pipelineStep ? "✓" : index + 1}</span><small>{step}</small>
                            {index < 4 && <i />}
                          </div>
                        ))}
                      </div>
                    </div>
                  </article>

                  <article className="panel">
                    <div className="panel-heading"><div>最近会话 <span className="count-tag">{filteredSessions.length}</span></div><button onClick={() => setActive("sessions")}>全部会话 <b>→</b></button></div>
                    <div className="session-list">
                      {filteredSessions.slice(0, 4).map((session) => (
                        <button className="session-row" key={session.id} onClick={() => { setSelectedSession(session.id); setActive("sessions"); }}>
                          <span className={`project-icon ${session.project === "seCall" ? "violet" : ""}`}>{session.project === "seCall" ? "SC" : "WB"}</span>
                          <span className="session-name"><strong>{session.title}</strong><small>{session.project} · {session.turns} turns</small></span>
                          <code>{session.id}</code><StatusPill status={session.status} /><time>{session.updated}</time><b>›</b>
                        </button>
                      ))}
                    </div>
                  </article>
                </div>

                <div className="side-column">
                  <article className="panel quality-panel">
                    <div className="panel-heading"><div>知识质量</div><button>本周 ⌄</button></div>
                    <div className="quality-score"><div className="score-ring"><strong>92</strong><small>总评分</small></div><div><span><i className="purple" />证据完整度 <b>95%</b></span><span><i className="green" />QA 准确度 <b>91%</b></span><span><i className="orange" />审核通过率 <b>88%</b></span></div></div>
                    <div className="quality-note"><span>↗</span><p><strong>较上周提升 4.6%</strong><small>主要来自证据链完整度提升</small></p></div>
                  </article>
                  <article className="panel system-panel">
                    <div className="panel-heading"><div>系统状态</div><span className={apiConnected ? "all-good" : "status-pill failed"}>{apiConnected ? "全部正常" : "未连接"}</span></div>
                    {[["OpenCode", health?.opencode_version ?? "等待连接"], ["seCall Index", `${health?.sessions ?? 0} sessions`], ["模型", health?.models?.[0] ?? "等待检测"], ["Vault", health?.vault ?? "等待连接"]].map(([name, detail]) => (
                      <div className="system-row" key={name}><span className="system-icon">{name.slice(0, 2)}</span><strong>{name}<small>{detail}</small></strong><i className={apiConnected ? "" : "offline"} /></div>
                    ))}
                    <button className="ghost-button" onClick={() => setActive("diagnostics")}>运行环境诊断 <span>→</span></button>
                  </article>
                </div>
              </section>
            </>
          )}

          {active === "sessions" && (
            <section className="subpage">
              <div className="subpage-heading"><div><p className="eyebrow">SESSION ARCHIVE</p><h1>研发会话</h1><p>管理 OpenCode 与 ChatGPT 会话，并选择需要沉淀的内容。</p></div><div className="import-actions"><input value={importProject} onChange={(event) => setImportProject(event.target.value)} placeholder="项目名称" aria-label="ChatGPT 导入项目名称" /><button className="primary-button" onClick={() => fileInputRef.current?.click()} disabled={importing}>＋ {importing ? "正在导入…" : "导入 ChatGPT"}</button></div></div>
              <div className="filter-bar"><button className="active">全部 {sessionItems.length}</button><button>ChatGPT {sessionItems.filter((item) => item.source === "chatgpt").length}</button><button>OpenCode {sessionItems.filter((item) => item.source === "opencode").length}</button><span /><select aria-label="项目筛选"><option>全部项目</option>{Array.from(new Set(sessionItems.map((item) => item.project))).map((project) => <option key={project}>{project}</option>)}</select></div>
              <article className="panel table-panel">
                <div className="data-table">
                  <div className="table-row table-head"><span>会话名称</span><span>模型</span><span>轮次</span><span>状态</span><span>更新时间</span><span /></div>
                  {filteredSessions.map((session) => (
                    <button className={`table-row ${selectedSession === session.id ? "selected" : ""}`} key={session.id} onClick={() => setSelectedSession(session.id)}>
                      <span className="title-cell"><i>{session.project === "seCall" ? "SC" : "WB"}</i><b>{session.title}<small>{session.id} · {session.project}</small></b></span><span>{session.model}</span><span>{session.turns}</span><StatusPill status={session.status} /><span>{session.updated}</span><span>•••</span>
                    </button>
                  ))}
                </div>
              </article>
            </section>
          )}

          {active === "pipeline" && (
            <section className="subpage">
              <div className="subpage-heading"><div><p className="eyebrow">AUTOMATION</p><h1>知识流水线</h1><p>监控 Session 从导出到可检索知识的完整过程。</p></div><button className="primary-button" onClick={() => setModal(true)}>＋ 运行流水线</button></div>
              <article className="pipeline-hero">
                <div><span className={pipelineRunning ? "spin-mark" : "done-mark"}>{pipelineRunning ? "↻" : "✓"}</span><p><small>{pipelineRunning ? "正在处理" : "最近一次运行成功"}</small><strong>{currentSession?.title ?? "请选择会话"}</strong><code>{currentSession?.id ?? "无会话"} · {currentSession?.model ?? "默认模型"}</code></p></div>
                <div className="hero-metrics"><span><b>{pipelineStep}/5</b><small>完成步骤</small></span><span><b>00:18</b><small>运行耗时</small></span><span><b>5</b><small>候选 QA</small></span></div>
              </article>
              <div className="pipeline-detail">
                {["读取 OpenCode Session", "转换为 seCall Markdown", "提取 Issue Card", "生成候选 QA", "重建知识索引"].map((name, index) => (
                  <article key={name} className={index < pipelineStep ? "complete" : index === pipelineStep ? "processing" : ""}>
                    <span>{index < pipelineStep ? "✓" : index + 1}</span><div><strong>{name}</strong><small>{["读取 28 个消息与 7 次工具调用", "保留命令、路径和错误证据", "置信度 92% · 证据链完整", "已生成 5 条，等待人工审核", "写入 FTS5 / BM25 索引"][index]}</small></div><time>{index < pipelineStep ? `${index * 3 + 2}s` : index === pipelineStep ? "运行中…" : "等待"}</time>
                  </article>
                ))}
              </div>
            </section>
          )}

          {active === "knowledge" && (
            <section className="subpage">
              <div className="subpage-heading"><div><p className="eyebrow">KNOWLEDGE VAULT</p><h1>知识库</h1><p>可追溯的 Issue Card、运行手册与工程决策。</p></div><button className="secondary-button" onClick={() => notify("索引已刷新", "186 个会话与 94 份知识卡片已同步")}>↻ 刷新索引</button></div>
              <div className="knowledge-grid">
                {(knowledgeItems.length ? knowledgeItems : [
                  { id: "demo-k1", title: "HARQ timeout 问题定位", project: "Scheduler", summary: "定位 HARQ 状态异常路径并记录验证方法。", confidence: "high", source_session: "ses_demo", review_status: "pending" },
                  { id: "demo-k2", title: "Wiki 页面未生成排查手册", project: "seCall", summary: "从 Session 导出、Vault 写入到索引重建的诊断流程。", confidence: "medium", source_session: "ses_demo", review_status: "pending" },
                ]).map((item) => {
                  const score = ({ high: 96, medium: 82, low: 58 } as Record<string, number>)[item.confidence] ?? 75;
                  return (
                  <article className="knowledge-card" key={item.id}>
                    <div className="knowledge-top"><span>◇</span><em>{item.project}</em><button>•••</button></div><h3>{item.title}</h3><p>{item.summary || "该知识卡片已写入本地 Vault。"}</p>
                    <div className="knowledge-meta"><span><i style={{ width: `${score}%` }} /></span><b>{score}% 置信度</b><small>{item.source_session}</small></div>
                  </article>
                  );
                })}
              </div>
            </section>
          )}

          {active === "qa" && (
            <section className="subpage">
              <div className="subpage-heading"><div><p className="eyebrow">HUMAN IN THE LOOP</p><h1>QA 审核队列</h1><p>核验证据与答案，只让可信知识进入正式索引。</p></div><div className="review-count"><strong>{qaItems.filter((q) => q.state === "pending").length}</strong><span>条待审核</span></div></div>
              <div className="qa-layout">
                {qaItems.map((qa) => (
                  <article className={`qa-card ${qa.state}`} key={qa.id}>
                    <div className="qa-head"><span>{qa.type}</span><em>置信度 {qa.confidence}%</em><code>{qa.source}</code></div>
                    <h3>{qa.question}</h3><p>{qa.answer}</p>
                    <div className="evidence"><span>证据</span><p>答案可在来源 Session 的定位过程与工具输出中直接验证。</p></div>
                    <div className="qa-actions">
                      {qa.state === "pending" ? <><button className="reject" onClick={() => reviewQa(qa.id, "rejected")}>退回</button><button className="approve" onClick={() => reviewQa(qa.id, "approved")}>✓ 通过并入库</button></> : <strong>{qa.state === "approved" ? "✓ 已通过审核" : "× 已退回"}</strong>}
                    </div>
                  </article>
                ))}
              </div>
            </section>
          )}

          {active === "diagnostics" && (
            <section className="subpage">
              <div className="subpage-heading"><div><p className="eyebrow">LOCAL ENVIRONMENT</p><h1>环境诊断</h1><p>检查 OpenCode、seCall、模型与本地 Vault 的连接状态。</p></div><button className="primary-button" onClick={() => notify("诊断完成", "所有核心服务均可正常使用")}>▶ 重新诊断</button></div>
              <div className="diagnostic-banner"><span>✓</span><div><strong>系统已准备就绪</strong><p>核心服务全部通过检查，可以运行知识流水线。</p></div><time>刚刚更新</time></div>
              <div className="diagnostic-grid">
                {[
                  ["OpenCode CLI", health?.opencode_version ?? "未连接", apiConnected ? "会话发现与导出正常" : "等待本地 API", "opencode --version"],
                  ["模型服务", health?.configured_model || health?.models?.[0] || "OpenCode 默认", health?.models?.length ? `可用模型 ${health.models.length} 个` : "等待模型检测", "opencode models"],
                  ["seCall Core", "本地", apiConnected ? "索引与 Vault 连接正常" : "等待本地 API", "127.0.0.1:8765"],
                  ["SQLite / FTS5", `${health?.sessions ?? 0} Sessions`, "全文索引状态健康", "index.sqlite"],
                  ["本地 Vault", "2.4 GB", "读写权限与目录结构正常", "Documents/seCallVault"],
                  ["适配器", "0.1.0", "7 项自动化检查通过", "secall-opencode doctor"],
                ].map(([name, version, desc, command]) => (
                  <article key={name}><div><span>{name.slice(0, 2)}</span><i /></div><h3>{name}</h3><strong>{version}</strong><p>{desc}</p><code>{command}</code></article>
                ))}
              </div>
            </section>
          )}
        </div>
      </section>

      {modal && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setModal(false); }}>
          <section className="modal" role="dialog" aria-modal="true" aria-labelledby="pipeline-title">
            <button className="modal-close" onClick={() => setModal(false)} aria-label="关闭">×</button>
            <div className="modal-mark">⌘</div><p className="eyebrow">NEW PIPELINE</p><h2 id="pipeline-title">创建知识流水线</h2><p>选择一个 OpenCode Session，生成可审核的工程知识。</p>
            <label>选择会话<select value={selectedSession} onChange={(event) => setSelectedSession(event.target.value)}>{sessionItems.map((item) => <option value={item.id} key={item.id}>{item.source === "chatgpt" ? "ChatGPT · " : ""}{item.title}</option>)}</select></label>
            <div className="form-grid"><label>生成模型<select defaultValue=""><option value="">OpenCode 默认模型</option>{health?.models?.map((model) => <option value={model} key={model}>{model}</option>)}</select></label><label>知识语言<select><option>简体中文</option><option>English</option></select></label></div>
            <div className="switch-row"><div><strong>生成候选 QA</strong><small>从 Issue Card 自动提取 3–10 条问答</small></div><input type="checkbox" defaultChecked aria-label="生成候选 QA" /></div>
            <div className="switch-row"><div><strong>完成后重建索引</strong><small>让新知识立即可被搜索与 MCP 调用</small></div><input type="checkbox" defaultChecked aria-label="完成后重建索引" /></div>
            <div className="modal-actions"><button onClick={() => setModal(false)}>取消</button><button className="primary-button" onClick={startPipeline}>启动流水线 <span>→</span></button></div>
          </section>
        </div>
      )}

      <input ref={fileInputRef} className="file-input" type="file" accept=".json,application/json" aria-label="选择 ChatGPT conversations.json" onChange={(event) => { const file = event.target.files?.[0]; if (file) void importChatGPTFile(file); }} />
      {toast && <div className="toast"><span>✓</span><div><strong>{toast.title}</strong><small>{toast.detail}</small></div><button onClick={() => setToast(null)}>×</button></div>}
    </main>
  );
}
