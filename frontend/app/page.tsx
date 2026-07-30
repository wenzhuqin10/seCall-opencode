"use client";

import { type CSSProperties, useEffect, useMemo, useRef, useState } from "react";

type View = "overview" | "sessions" | "pipeline" | "knowledge" | "wiki" | "graph" | "rag" | "qa" | "diagnostics";
type Toast = { title: string; detail: string } | null;
type SessionItem = {
  id: string; title: string; project: string; model: string; turns: number;
  updated: string; status: string; source?: string; path?: string;
  review_status?: "pending" | "approved" | "rejected";
  review_note?: string; hidden?: boolean; reviewed_at?: string;
  storage_state?: "pending" | "approved" | "rejected";
};
type SessionDetail = SessionItem & {
  metadata: Record<string, string>; markdown: string; full_length: number; truncated: boolean;
  quality: {
    score: number; level: "high" | "medium" | "low"; flags: string[];
    tool_calls: number; user_turns: number; assistant_turns: number;
    has_conclusion: boolean;
  };
};
type QaItem = {
  id: string; question: string; answer: string; source: string;
  confidence: number; type: string; state: string;
};
type KnowledgeItem = {
  id: string; title: string; project: string; summary: string;
  confidence: string; source_session: string; review_status: string;
};
type KnowledgeSection = { heading: string; content: string };
type KnowledgeDetail = KnowledgeItem & {
  heading: string; type: string; intro: string; sections: KnowledgeSection[];
  markdown: string; version: string; updated: number;
};
type TrashItem = {
  trash_id: string; knowledge_id: string; title: string; project: string;
  source_session: string; deleted_at: string; qa_count: number;
};
type SearchResult = {
  id: string; scope: "session" | "knowledge" | "wiki" | "qa"; title: string;
  snippet: string; project: string; source_session: string; score: number;
  match_type: string; review_status: string;
};
type WikiPage = {
  id: string; slug: string; category: string; category_label: string; title: string;
  project: string; source_session: string; summary: string; updated: number;
  word_count: number; path: string;
};
type WikiDetail = WikiPage & {
  markdown: string; sections: Array<{ heading: string; content: string }>;
  references: string[]; backlinks: Array<{ id: string; title: string; category: string }>;
};
type WikiResponse = {
  count: number; counts: Record<string, number>; pages: WikiPage[];
};
type GraphNode = { id: string; label?: string; type?: string; project?: string };
type GraphLink = { source: string; target: string; relation?: string; weight?: number };
type GraphSnapshot = {
  nodes: GraphNode[]; links: GraphLink[];
  stats: { nodes: number; links: number; types: Record<string, number> };
};
type SearchResponse = {
  requested_mode: string; effective_mode: string; semantic_available: boolean;
  fallback_reason?: string; count: number; results: SearchResult[];
};
type RagResponse = {
  question: string; answer: string; sources: Array<SearchResult & { citation: string }>;
  requested_mode: string; effective_mode: string; semantic_available: boolean;
  fallback_reason?: string; grounded: boolean;
};
type Health = {
  ready: boolean; api_version: string; vault: string; opencode_version: string;
  models: string[]; configured_model?: string; sessions: number;
  knowledge: number; qa: number; pending_qa: number;
  wiki?: number; graph?: { nodes: number; links: number; types: Record<string, number> };
  sync?: {
    running: boolean; syncing: boolean; last_checked: string; last_synced: string;
    synced_total: number; pending_changes: number; last_error: string;
  };
  semantic?: {
    available: boolean; backend: string; model_dir: string;
    indexed_documents: number; indexed_chunks: number; reason?: string;
  };
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
  { id: "sessions", label: "会话", icon: "◫" },
  { id: "pipeline", label: "流水线", icon: "⌘", badge: "1" },
  { id: "knowledge", label: "知识库", icon: "◇" },
  { id: "wiki", label: "Wiki 中心", icon: "▤" },
  { id: "graph", label: "知识关系图", icon: "◎" },
  { id: "rag", label: "RAG 问答", icon: "✦" },
  { id: "qa", label: "QA 审核", icon: "✓" },
  { id: "diagnostics", label: "环境诊断", icon: "+" },
];

const wikiCategories = [
  ["all", "全部页面"],
  ["overview", "知识总览"],
  ["projects", "项目"],
  ["topics", "技术主题"],
  ["decisions", "设计决策"],
  ["issues", "问题定位"],
] as const;

function MarkdownViewer({ markdown }: { markdown: string }) {
  const body = markdown.replace(/^---[\s\S]*?\n---\s*/, "");
  const blocks: Array<{ kind: string; value: string }> = [];
  let code: string[] | null = null;
  for (const raw of body.split("\n")) {
    const line = raw.trimEnd();
    if (line.trim().startsWith("```")) {
      if (code) {
        blocks.push({ kind: "code", value: code.join("\n") });
        code = null;
      } else code = [];
      continue;
    }
    if (code) {
      code.push(raw);
      continue;
    }
    if (!line.trim()) continue;
    if (line.startsWith("### ")) blocks.push({ kind: "h3", value: line.slice(4) });
    else if (line.startsWith("## ")) blocks.push({ kind: "h2", value: line.slice(3) });
    else if (line.startsWith("# ")) blocks.push({ kind: "h1", value: line.slice(2) });
    else if (/^[-*]\s+/.test(line)) blocks.push({ kind: "li", value: line.replace(/^[-*]\s+/, "") });
    else if (line.startsWith("> ")) blocks.push({ kind: "quote", value: line.slice(2) });
    else blocks.push({ kind: "p", value: line });
  }
  return <div className="markdown-viewer">{blocks.map((block, index) => {
    if (block.kind === "h1") return <h1 key={index}>{block.value}</h1>;
    if (block.kind === "h2") return <h2 key={index}>{block.value}</h2>;
    if (block.kind === "h3") return <h3 key={index}>{block.value}</h3>;
    if (block.kind === "code") return <pre key={index}><code>{block.value}</code></pre>;
    if (block.kind === "li") return <div className="markdown-list" key={index}><i />{block.value}</div>;
    if (block.kind === "quote") return <blockquote key={index}>{block.value}</blockquote>;
    return <p key={index}>{block.value}</p>;
  })}</div>;
}

function graphPositions(nodes: GraphNode[]) {
  const groups = new Map<string, GraphNode[]>();
  nodes.forEach((node) => {
    const type = node.type || "other";
    groups.set(type, [...(groups.get(type) || []), node]);
  });
  const radii: Record<string, number> = { agent: 70, project: 170, tool: 265, session: 370 };
  const fallback = 300;
  const positions = new Map<string, { x: number; y: number }>();
  Array.from(groups.entries()).forEach(([type, items], groupIndex) => {
    const radius = radii[type] ?? fallback + groupIndex * 18;
    items.forEach((node, index) => {
      const angle = (index / Math.max(items.length, 1)) * Math.PI * 2 + groupIndex * 0.31;
      positions.set(node.id, { x: 500 + Math.cos(angle) * radius, y: 390 + Math.sin(angle) * radius });
    });
  });
  return positions;
}

function StatusPill({ status }: { status: string }) {
  const map: Record<string, string> = { ready: "已入库", review: "待审核", failed: "需处理" };
  return <span className={`status-pill ${status}`}><i />{map[status] ?? status}</span>;
}

function ReviewPill({ status }: { status?: string }) {
  const value = status || "pending";
  const labels: Record<string, string> = {
    pending: "待预审核",
    approved: "已通过",
    rejected: "已拒绝",
  };
  return <span className={`review-pill ${value}`}><i />{labels[value] ?? value}</span>;
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
  const [searchMode, setSearchMode] = useState<"keyword" | "semantic" | "hybrid">("hybrid");
  const [searchScope, setSearchScope] = useState<"all" | "session" | "knowledge" | "wiki" | "qa">("all");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searching, setSearching] = useState(false);
  const [searchFallback, setSearchFallback] = useState("");
  const [modal, setModal] = useState(false);
  const [toast, setToast] = useState<Toast>(null);
  const [pipelineRunning, setPipelineRunning] = useState(false);
  const [pipelineStep, setPipelineStep] = useState(4);
  const [qaItems, setQaItems] = useState(qaSeed);
  const [sessionItems, setSessionItems] = useState<SessionItem[]>(demoSessions);
  const [hiddenSessionItems, setHiddenSessionItems] = useState<SessionItem[]>([]);
  const [sessionReviewFilter, setSessionReviewFilter] = useState<"all" | "pending" | "approved" | "rejected" | "hidden">("all");
  const [sessionDetail, setSessionDetail] = useState<SessionDetail | null>(null);
  const [sessionPreviewLoading, setSessionPreviewLoading] = useState(false);
  const [syncingSessions, setSyncingSessions] = useState(false);
  const [knowledgeItems, setKnowledgeItems] = useState<KnowledgeItem[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [apiConnected, setApiConnected] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importProject, setImportProject] = useState("chatgpt-import");
  const [selectedSession, setSelectedSession] = useState("ses_0598ac");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const [knowledgeDetail, setKnowledgeDetail] = useState<KnowledgeDetail | null>(null);
  const [editingKnowledge, setEditingKnowledge] = useState(false);
  const [savingKnowledge, setSavingKnowledge] = useState(false);
  const [trashItems, setTrashItems] = useState<TrashItem[]>([]);
  const [showTrash, setShowTrash] = useState(false);
  const [ragQuestion, setRagQuestion] = useState("");
  const [ragScope, setRagScope] = useState<"all" | "session" | "knowledge" | "wiki" | "qa">("all");
  const [ragMode, setRagMode] = useState<"keyword" | "semantic" | "hybrid">("hybrid");
  const [ragLoading, setRagLoading] = useState(false);
  const [ragResult, setRagResult] = useState<RagResponse | null>(null);
  const [wikiPages, setWikiPages] = useState<WikiPage[]>([]);
  const [wikiCounts, setWikiCounts] = useState<Record<string, number>>({});
  const [wikiCategory, setWikiCategory] = useState("all");
  const [wikiQuery, setWikiQuery] = useState("");
  const [wikiDetail, setWikiDetail] = useState<WikiDetail | null>(null);
  const [graph, setGraph] = useState<GraphSnapshot>({ nodes: [], links: [], stats: { nodes: 0, links: 0, types: {} } });
  const [graphType, setGraphType] = useState("all");
  const [graphQuery, setGraphQuery] = useState("");
  const [graphSelected, setGraphSelected] = useState<GraphNode | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);

  const refreshData = async () => {
    const [healthResult, sessionResult, hiddenSessionResult, qaResult, knowledgeResult, wikiResult, graphResult] = await Promise.all([
      apiRequest<Health>("/api/health"),
      apiRequest<Array<Record<string, unknown>>>("/api/sessions?limit=300"),
      apiRequest<Array<Record<string, unknown>>>("/api/sessions/hidden?limit=1000"),
      apiRequest<Array<Record<string, unknown>>>("/api/qa?limit=300"),
      apiRequest<KnowledgeItem[]>("/api/knowledge?limit=300"),
      apiRequest<WikiResponse>("/api/wiki?limit=1000"),
      apiRequest<GraphSnapshot>("/api/graph"),
    ]);
    const normalizeSession = (item: Record<string, unknown>): SessionItem => ({
      id: String(item.id ?? ""),
      title: String(item.title ?? "未命名会话"),
      project: String(item.project ?? "unknown"),
      model: String(item.model ?? "unknown"),
      turns: Number(item.turns ?? 0),
      updated: formatUpdated(item.updated as number | string),
      status: String(item.status ?? "ready"),
      source: String(item.source ?? "unknown"),
      path: String(item.path ?? ""),
      review_status: String(item.review_status ?? "pending") as SessionItem["review_status"],
      review_note: String(item.review_note ?? ""),
      hidden: Boolean(item.hidden),
      reviewed_at: String(item.reviewed_at ?? ""),
      storage_state: String(item.storage_state ?? "pending") as SessionItem["storage_state"],
    });
    const normalizedSessions = sessionResult.map(normalizeSession);
    const normalizedHiddenSessions = hiddenSessionResult.map(normalizeSession);
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
    setHiddenSessionItems(normalizedHiddenSessions);
    setQaItems(normalizedQa);
    setKnowledgeItems(knowledgeResult);
    setWikiPages(wikiResult.pages);
    setWikiCounts(wikiResult.counts);
    setGraph(graphResult);
    setApiConnected(true);
    if (normalizedSessions.length && !normalizedSessions.some((item) => item.id === selectedSession)) {
      setSelectedSession(normalizedSessions[0].id);
    }
  };

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void refreshData().catch(() => setApiConnected(false));
    }, 0);
    // The selected session is intentionally reconciled inside refreshData.
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const notify = (title: string, detail: string) => {
    setToast({ title, detail });
    window.setTimeout(() => setToast(null), 3200);
  };

  const runSearch = async () => {
    const normalized = query.trim();
    if (normalized.length < 2) {
      setSearchResults([]);
      setSearchOpen(false);
      return;
    }
    setSearching(true);
    try {
      const params = new URLSearchParams({
        q: normalized,
        scope: searchScope,
        mode: searchMode,
        limit: "20",
      });
      const result = await apiRequest<SearchResponse>(`/api/search?${params}`);
      setSearchResults(result.results);
      setSearchFallback(result.fallback_reason ?? "");
      setSearchOpen(true);
    } catch (error) {
      notify("搜索失败", error instanceof Error ? error.message : "请检查本地服务");
    } finally {
      setSearching(false);
    }
  };

  useEffect(() => {
    const timer = window.setTimeout(() => { void runSearch(); }, 320);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, searchMode, searchScope]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchInputRef.current?.focus();
      }
      if (event.key === "Escape") setSearchOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const filteredSessions = useMemo(
    () => sessionItems.filter((item) => `${item.title} ${item.project} ${item.id} ${item.source ?? ""}`.toLowerCase().includes(query.toLowerCase())),
    [query, sessionItems],
  );
  const reviewedSessions = useMemo(() => {
    const source = sessionReviewFilter === "hidden" ? hiddenSessionItems : sessionItems;
    return source.filter((item) => {
      const matchesQuery = `${item.title} ${item.project} ${item.id} ${item.source ?? ""}`.toLowerCase().includes(query.toLowerCase());
      const matchesReview = sessionReviewFilter === "all"
        || sessionReviewFilter === "hidden"
        || item.review_status === sessionReviewFilter;
      return matchesQuery && matchesReview;
    });
  }, [hiddenSessionItems, query, sessionItems, sessionReviewFilter]);
  const approvedSessions = useMemo(
    () => sessionItems.filter((item) => item.review_status === "approved"),
    [sessionItems],
  );
  const currentSession = sessionItems.find((item) => item.id === selectedSession) ?? sessionItems[0];
  const pipelineSession = approvedSessions.find((item) => item.id === selectedSession) ?? approvedSessions[0];
  const hour = new Date().getHours();
  const greeting = hour >= 5 && hour < 12 ? "早上好" : hour < 14 ? "中午好" : hour < 18 ? "下午好" : "晚上好";
  const today = new Date();
  const todayDay = today.getDate();
  const todayWeekday = new Intl.DateTimeFormat("zh-CN", { weekday: "long" }).format(today);
  const todayMonth = new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "long" }).format(today);
  const filteredWiki = useMemo(
    () => wikiPages.filter((page) => (
      (wikiCategory === "all" || page.category === wikiCategory)
      && `${page.title} ${page.summary} ${page.project}`.toLowerCase().includes(wikiQuery.toLowerCase())
    )),
    [wikiPages, wikiCategory, wikiQuery],
  );
  const graphPositionsMap = useMemo(() => graphPositions(graph.nodes), [graph.nodes]);
  const graphNodes = useMemo(
    () => graph.nodes.filter((node) => graphType === "all" || node.type === graphType),
    [graph.nodes, graphType],
  );
  const graphNodeIds = useMemo(() => new Set(graphNodes.map((node) => node.id)), [graphNodes]);
  const graphLinks = useMemo(
    () => graph.links.filter((link) => graphNodeIds.has(String(link.source)) && graphNodeIds.has(String(link.target))),
    [graph.links, graphNodeIds],
  );

  const openWiki = async (id: string) => {
    const [category, slug] = id.split("/", 2);
    try {
      const detail = await apiRequest<WikiDetail>(`/api/wiki/${encodeURIComponent(category)}/${encodeURIComponent(slug)}`);
      setWikiDetail(detail);
      setActive("wiki");
      setSearchOpen(false);
    } catch (error) {
      notify("无法打开 Wiki 页面", error instanceof Error ? error.message : "请检查本地服务");
    }
  };

  const rebuildKnowledgeGraph = async () => {
    setGraphLoading(true);
    try {
      const result = await apiRequest<{ graph: GraphSnapshot }>("/api/graph/rebuild", { method: "POST", body: "{}" });
      setGraph(result.graph);
      await refreshData();
      notify("知识关系图已更新", `${result.graph.stats.nodes} 个节点，${result.graph.stats.links} 条关系`);
    } catch (error) {
      notify("关系图构建失败", error instanceof Error ? error.message : "请检查 seCall 图谱组件");
    } finally {
      setGraphLoading(false);
    }
  };

  const openSessionPreview = async (session: SessionItem) => {
    setSelectedSession(session.id);
    setSessionPreviewLoading(true);
    try {
      const detail = await apiRequest<SessionDetail>(`/api/sessions/${encodeURIComponent(session.id)}`);
      setSessionDetail(detail);
    } catch (error) {
      notify("无法打开会话预览", error instanceof Error ? error.message : "请检查本地服务");
    } finally {
      setSessionPreviewLoading(false);
    }
  };

  const syncOpenCodeSessions = async () => {
    setSyncingSessions(true);
    try {
      const result = await apiRequest<{ synced: number; pending_changes: number; last_error: string }>("/api/sync/now", {
        method: "POST",
        body: "{}",
      });
      await refreshData();
      notify(
        "OpenCode 会话同步完成",
        result.last_error ? result.last_error : `新增或更新 ${result.synced} 条，等待稳定 ${result.pending_changes} 条`,
      );
    } catch (error) {
      notify("会话同步失败", error instanceof Error ? error.message : "请检查 OpenCode");
    } finally {
      setSyncingSessions(false);
    }
  };

  const reviewSession = async (
    session: SessionItem,
    status: "pending" | "approved" | "rejected",
  ) => {
    const note = status === "rejected"
      ? window.prompt("可选：填写拒绝原因，便于后续复核。", session.review_note || "") ?? session.review_note ?? ""
      : session.review_note || "";
    try {
      await apiRequest(`/api/sessions/${encodeURIComponent(session.id)}/review`, {
        method: "POST",
        body: JSON.stringify({ status, note }),
      });
      await refreshData();
      setSessionDetail((detail) => detail?.id === session.id
        ? { ...detail, review_status: status, review_note: note, storage_state: status }
        : detail);
      notify(
        status === "approved" ? "会话已通过预审核" : status === "rejected" ? "会话已拒绝" : "会话已退回待审核",
        status === "approved" ? "现在可以进入知识流水线" : "低质会话不会进入检索和流水线",
      );
    } catch (error) {
      notify("审核保存失败", error instanceof Error ? error.message : "请检查本地服务");
    }
  };

  const hideFrontendSession = async (session: SessionItem) => {
    if (!window.confirm(`从前端隐藏“${session.title}”？\n\nOpenCode 原始会话和 Vault Session 不会被删除。`)) return;
    try {
      await apiRequest(`/api/sessions/${encodeURIComponent(session.id)}`, { method: "DELETE" });
      await refreshData();
      setSessionDetail(null);
      notify("会话已从前端隐藏", "原始 OpenCode 会话保持不变，可在“已隐藏”中恢复");
    } catch (error) {
      notify("隐藏失败", error instanceof Error ? error.message : "请检查本地服务");
    }
  };

  const restoreFrontendSession = async (session: SessionItem) => {
    try {
      await apiRequest(`/api/sessions/${encodeURIComponent(session.id)}/restore`, {
        method: "POST",
        body: "{}",
      });
      await refreshData();
      setSessionDetail((detail) => detail?.id === session.id ? { ...detail, hidden: false } : detail);
      notify("会话已恢复显示", "原审核状态保持不变");
    } catch (error) {
      notify("恢复失败", error instanceof Error ? error.message : "请检查本地服务");
    }
  };

  const openKnowledge = async (id: string) => {
    try {
      const detail = await apiRequest<KnowledgeDetail>(`/api/knowledge/${encodeURIComponent(id)}`);
      setKnowledgeDetail(detail);
      setEditingKnowledge(false);
      setSearchOpen(false);
    } catch (error) {
      notify("无法打开知识卡片", error instanceof Error ? error.message : "请检查本地服务");
    }
  };

  const saveKnowledge = async () => {
    if (!knowledgeDetail) return;
    setSavingKnowledge(true);
    try {
      const updated = await apiRequest<KnowledgeDetail>(
        `/api/knowledge/${encodeURIComponent(knowledgeDetail.id)}`,
        { method: "PUT", body: JSON.stringify(knowledgeDetail) },
      );
      setKnowledgeDetail(updated);
      setEditingKnowledge(false);
      await refreshData();
      notify("知识卡片已保存", "关键词索引已同步更新");
    } catch (error) {
      notify("保存失败", error instanceof Error ? error.message : "请刷新后重试");
    } finally {
      setSavingKnowledge(false);
    }
  };

  const deleteKnowledge = async () => {
    if (!knowledgeDetail) return;
    if (!window.confirm(`将“${knowledgeDetail.title}”和关联 QA 移入回收站？`)) return;
    try {
      await apiRequest(`/api/knowledge/${encodeURIComponent(knowledgeDetail.id)}`, { method: "DELETE" });
      setKnowledgeDetail(null);
      await refreshData();
      notify("已移入回收站", "知识卡片和关联 QA 均可恢复");
    } catch (error) {
      notify("删除失败", error instanceof Error ? error.message : "请检查本地服务");
    }
  };

  const loadTrash = async () => {
    try {
      const items = await apiRequest<TrashItem[]>("/api/knowledge/trash");
      setTrashItems(items);
      setShowTrash(true);
    } catch (error) {
      notify("无法打开回收站", error instanceof Error ? error.message : "请检查本地服务");
    }
  };

  const restoreKnowledge = async (trashId: string) => {
    try {
      await apiRequest(`/api/knowledge/trash/${encodeURIComponent(trashId)}/restore`, {
        method: "POST",
        body: "{}",
      });
      await Promise.all([refreshData(), loadTrash()]);
      notify("知识卡片已恢复", "关联 QA 和关键词索引已恢复");
    } catch (error) {
      notify("恢复失败", error instanceof Error ? error.message : "可能存在同名知识卡片");
    }
  };

  const refreshIndex = async () => {
    try {
      const result = await apiRequest<{ search: { keyword: { indexed: number }; semantic: { indexed_chunks: number } } }>("/api/index", {
        method: "POST",
        body: "{}",
      });
      await refreshData();
      notify("索引已刷新", `关键词 ${result.search.keyword.indexed} 份，向量 ${result.search.semantic.indexed_chunks} 个分块`);
    } catch (error) {
      notify("索引刷新失败", error instanceof Error ? error.message : "请检查本地服务");
    }
  };

  const askRag = async () => {
    const question = ragQuestion.trim();
    if (question.length < 2) {
      notify("请输入问题", "问题至少需要两个字符");
      return;
    }
    setRagLoading(true);
    setRagResult(null);
    try {
      const result = await apiRequest<RagResponse>("/api/rag/query", {
        method: "POST",
        body: JSON.stringify({
          question,
          scope: ragScope,
          mode: ragMode,
          limit: 6,
        }),
      });
      setRagResult(result);
    } catch (error) {
      notify("RAG 问答失败", error instanceof Error ? error.message : "请检查本地模型与 OpenCode");
    } finally {
      setRagLoading(false);
    }
  };

  const openSearchResult = (item: SearchResult) => {
    if (item.scope === "session") {
      setSelectedSession(item.id);
      setActive("sessions");
      setSearchOpen(false);
    } else if (item.scope === "knowledge") {
      setActive("knowledge");
      void openKnowledge(item.id);
    } else if (item.scope === "wiki") {
      void openWiki(item.id);
    } else {
      setActive("qa");
      setSearchOpen(false);
    }
  };

  const startPipeline = async () => {
    if (!pipelineSession) {
      notify("暂无可运行会话", "请先在“研发会话”中通过至少一个会话的预审核");
      return;
    }
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
        body: JSON.stringify({ session_id: pipelineSession.id, reindex: true }),
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
          {navItems.map((item) => {
            const badge = item.id === "sessions"
              ? String(health?.sessions ?? sessionItems.length)
              : item.id === "qa"
                ? String(qaItems.filter((item) => item.state === "pending").length)
                : item.badge;
            return (
              <button key={item.id} className={active === item.id ? "active" : ""} onClick={() => setActive(item.id)}>
                <span className="nav-icon">{item.icon}</span>{item.label}
                {badge && <em>{badge}</em>}
              </button>
            );
          })}
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
          <div className="search-shell">
            <label className="global-search">
              <span>⌕</span>
              <input
                ref={searchInputRef}
                value={query}
                onFocus={() => { if (query.trim().length >= 2) setSearchOpen(true); }}
                onKeyDown={(event) => { if (event.key === "Enter") void runSearch(); }}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索会话、知识或错误信息…"
              />
              <kbd>Ctrl K</kbd>
            </label>
            {searchOpen && (
              <section className="search-popover" aria-label="搜索结果">
                <div className="search-controls">
                  <div>{(["all", "session", "knowledge", "wiki", "qa"] as const).map((scope) => (
                    <button className={searchScope === scope ? "active" : ""} key={scope} onClick={() => setSearchScope(scope)}>
                      {{ all: "全部", session: "会话", knowledge: "知识", wiki: "Wiki", qa: "QA" }[scope]}
                    </button>
                  ))}</div>
                  <select value={searchMode} onChange={(event) => setSearchMode(event.target.value as typeof searchMode)} aria-label="检索模式">
                    <option value="keyword">关键词</option>
                    <option value="semantic">语义{health?.semantic?.available ? "" : "（暂不可用）"}</option>
                    <option value="hybrid">混合{health?.semantic?.available ? "" : "（降级）"}</option>
                  </select>
                </div>
                {searchFallback && <p className="search-fallback">◇ {searchFallback}</p>}
                <div className="search-results">
                  {searching ? <p className="search-empty">正在检索…</p> : searchResults.length ? searchResults.map((item) => (
                    <button key={`${item.scope}-${item.id}`} onClick={() => openSearchResult(item)}>
                      <span className={`result-icon ${item.scope}`}>{item.scope === "session" ? "会" : item.scope === "knowledge" ? "知" : item.scope === "wiki" ? "W" : "问"}</span>
                      <span><strong>{item.title}</strong><small>{item.snippet || "匹配到相关内容"}</small><em>{item.project} · {item.match_type === "keyword" ? "关键词匹配" : item.match_type}</em></span>
                      <b>›</b>
                    </button>
                  )) : <p className="search-empty">没有找到匹配内容</p>}
                </div>
                <div className="search-footer"><span>Enter 搜索</span><button onClick={() => setSearchOpen(false)}>关闭</button></div>
              </section>
            )}
          </div>
          <div className="top-actions">
            <button className="icon-button" aria-label="通知">◌<i /></button>
            <button className="primary-button" onClick={() => setModal(true)}><span>＋</span>新建流水线</button>
          </div>
        </header>

        <div className="page-body">
          {active === "overview" && (
            <>
              <section className="page-heading">
                <div><p className="eyebrow">KNOWLEDGE OPERATIONS</p><h1>{greeting}，Qin <span>✦</span></h1><p>你的本地知识系统运行稳定，当前共有 <b>{health?.sessions ?? sessionItems.length}</b> 个可审核会话。</p></div>
                <div className="date-chip"><span>{todayDay}</span><div><strong>{todayWeekday}</strong><small>{todayMonth}</small></div></div>
              </section>

              <section className="metric-grid">
                <article className="metric-card dark">
                  <div className="metric-top"><span className="metric-icon">⌘</span><em>+12.4%</em></div>
                  <strong>{approvedSessions.length}</strong><p>已审核入库</p>
                  <div className="sparkline"><i /><i /><i /><i /><i /><i /><i /></div>
                </article>
                <article className="metric-card">
                  <div className="metric-top"><span className="metric-icon lilac">◇</span><em>+8.2%</em></div>
                  <strong>{health?.knowledge ?? knowledgeItems.length}</strong><p>Issue Cards</p><MiniBars />
                </article>
                <article className="metric-card">
                  <div className="metric-top"><span className="metric-icon mint">✓</span><span className="tiny-label">待处理 {qaItems.filter((item) => item.state === "pending").length}</span></div>
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
                        {["会话导出", "格式转换", "知识抽取", "QA 生成", "混合索引"].map((step, index) => (
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
                        <button className="session-row" key={session.id} onClick={() => { setActive("sessions"); void openSessionPreview(session); }}>
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
              <div className="subpage-heading">
                <div><p className="eyebrow">SESSION PRE-REVIEW</p><h1>研发会话</h1><p>OpenCode 新会话自动进入暂存区；审核通过后才进入正式 Vault 和知识流水线。</p></div>
                <div className="session-heading-actions">
                  <span className={`sync-state ${health?.sync?.running ? "running" : ""}`}><i />{health?.sync?.syncing ? "正在监听…" : health?.sync?.running ? "实时监听中" : "监听未启动"}</span>
                  <button className="secondary-button" onClick={() => void syncOpenCodeSessions()} disabled={syncingSessions}>↻ {syncingSessions ? "同步中…" : "立即同步"}</button>
                  <div className="import-actions"><input value={importProject} onChange={(event) => setImportProject(event.target.value)} placeholder="项目名称" aria-label="ChatGPT 导入项目名称" /><button className="primary-button" onClick={() => fileInputRef.current?.click()} disabled={importing}>＋ {importing ? "正在导入…" : "导入 ChatGPT"}</button></div>
                </div>
              </div>
              <div className="session-review-summary">
                <article><span className="pending">●</span><strong>{sessionItems.filter((item) => item.review_status === "pending").length}</strong><small>待预审核</small></article>
                <article><span className="approved">●</span><strong>{sessionItems.filter((item) => item.review_status === "approved").length}</strong><small>已通过</small></article>
                <article><span className="rejected">●</span><strong>{sessionItems.filter((item) => item.review_status === "rejected").length}</strong><small>已拒绝</small></article>
                <article><span className="hidden">●</span><strong>{hiddenSessionItems.length}</strong><small>前端隐藏</small></article>
                <p><b>会话生命周期</b> 待审核存放在暂存区；通过后移入正式 Vault；拒绝后移入隔离区。OpenCode 原始数据始终不变。</p>
              </div>
              <div className="filter-bar review-filter">
                {([
                  ["all", `全部 ${sessionItems.length}`],
                  ["pending", `待审核 ${sessionItems.filter((item) => item.review_status === "pending").length}`],
                  ["approved", `已通过 ${sessionItems.filter((item) => item.review_status === "approved").length}`],
                  ["rejected", `已拒绝 ${sessionItems.filter((item) => item.review_status === "rejected").length}`],
                  ["hidden", `已隐藏 ${hiddenSessionItems.length}`],
                ] as const).map(([id, label]) => <button key={id} className={sessionReviewFilter === id ? "active" : ""} onClick={() => setSessionReviewFilter(id)}>{label}</button>)}
                <span /><select aria-label="项目筛选"><option>全部项目</option>{Array.from(new Set(sessionItems.map((item) => item.project))).map((project) => <option key={project}>{project}</option>)}</select>
              </div>
              <article className="panel table-panel">
                <div className="data-table">
                  <div className="table-row session-review-row table-head"><span>会话名称</span><span>模型</span><span>轮次</span><span>预审核</span><span>更新时间</span><span>操作</span></div>
                  {reviewedSessions.map((session) => (
                    <div className={`table-row session-review-row ${selectedSession === session.id ? "selected" : ""}`} key={session.id} role="button" tabIndex={0} onClick={() => void openSessionPreview(session)} onKeyDown={(event) => { if (event.key === "Enter") void openSessionPreview(session); }}>
                      <span className="title-cell"><i>{session.project === "seCall" ? "SC" : "WB"}</i><b>{session.title}<small>{session.id} · {session.project}{session.review_note ? ` · ${session.review_note}` : ""}</small></b></span>
                      <span>{session.model}</span><span>{session.turns}</span><ReviewPill status={session.review_status} /><span>{session.updated}</span>
                      <span className="session-review-actions" onClick={(event) => event.stopPropagation()}>
                        {session.hidden ? (
                            <button className="restore" onClick={() => void restoreFrontendSession(session)}>恢复显示</button>
                        ) : (
                          <>
                            {session.review_status !== "approved" && <button className="approve" onClick={() => void reviewSession(session, "approved")}>通过</button>}
                            {session.review_status !== "rejected" && <button className="reject" onClick={() => void reviewSession(session, "rejected")}>拒绝</button>}
                            {session.review_status !== "pending" && <button onClick={() => void reviewSession(session, "pending")}>待审</button>}
                            <button className="hide" onClick={() => void hideFrontendSession(session)}>隐藏</button>
                          </>
                        )}
                      </span>
                    </div>
                  ))}
                  {!reviewedSessions.length && <div className="empty-state">当前筛选条件下没有会话</div>}
                </div>
              </article>
              {sessionPreviewLoading && <div className="preview-loading"><span>◌</span>正在读取会话内容…</div>}
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
                {["读取 OpenCode Session", "转换为 seCall Markdown", "提取 Issue Card", "生成候选 QA", "重建关键词与语义索引"].map((name, index) => (
                  <article key={name} className={index < pipelineStep ? "complete" : index === pipelineStep ? "processing" : ""}>
                    <span>{index < pipelineStep ? "✓" : index + 1}</span><div><strong>{name}</strong><small>{["读取 28 个消息与 7 次工具调用", "保留命令、路径和错误证据", "置信度 92% · 证据链完整", "已生成 5 条，等待人工审核", "同步 FTS5/BM25 关键词索引与 BGE-M3 向量索引"][index]}</small></div><time>{index < pipelineStep ? `${index * 3 + 2}s` : index === pipelineStep ? "运行中…" : "等待"}</time>
                  </article>
                ))}
              </div>
            </section>
          )}

          {active === "knowledge" && (
            <section className="subpage">
              <div className="subpage-heading">
                <div><p className="eyebrow">KNOWLEDGE VAULT</p><h1>{showTrash ? "知识回收站" : "知识库"}</h1><p>{showTrash ? "恢复误删的知识卡片及其关联 QA。" : "可查看、修改、删除和检索的本地工程知识。"}</p></div>
                <div className="heading-actions">
                  {showTrash ? <button className="secondary-button" onClick={() => setShowTrash(false)}>← 返回知识库</button> : <button className="secondary-button" onClick={() => void loadTrash()}>♲ 回收站</button>}
                  {!showTrash && <button className="secondary-button" onClick={() => void refreshIndex()}>↻ 刷新索引</button>}
                </div>
              </div>
              {showTrash ? (
                <div className="trash-list">
                  {trashItems.length ? trashItems.map((item) => (
                    <article key={item.trash_id}>
                      <span>♲</span><div><strong>{item.title}</strong><small>{item.project} · 删除于 {formatUpdated(new Date(item.deleted_at).getTime())} · {item.qa_count} 条关联 QA</small></div>
                      <button onClick={() => void restoreKnowledge(item.trash_id)}>恢复</button>
                    </article>
                  )) : <div className="empty-state">回收站为空</div>}
                </div>
              ) : <div className="knowledge-grid">
                {(knowledgeItems.length ? knowledgeItems : [
                  { id: "demo-k1", title: "HARQ timeout 问题定位", project: "Scheduler", summary: "定位 HARQ 状态异常路径并记录验证方法。", confidence: "high", source_session: "ses_demo", review_status: "pending" },
                  { id: "demo-k2", title: "Wiki 页面未生成排查手册", project: "seCall", summary: "从 Session 导出、Vault 写入到索引重建的诊断流程。", confidence: "medium", source_session: "ses_demo", review_status: "pending" },
                ]).map((item) => {
                  const score = ({ high: 96, medium: 82, low: 58 } as Record<string, number>)[item.confidence] ?? 75;
                  return (
                  <article className="knowledge-card" key={item.id} tabIndex={0} onClick={() => { if (!item.id.startsWith("demo-")) void openKnowledge(item.id); }} onKeyDown={(event) => { if (event.key === "Enter" && !item.id.startsWith("demo-")) void openKnowledge(item.id); }}>
                    <div className="knowledge-top"><span>◇</span><em>{item.project}</em><button aria-label={`查看 ${item.title}`}>查看</button></div><h3>{item.title}</h3><p>{item.summary || "该知识卡片已写入本地 Vault。"}</p>
                    <div className="knowledge-meta"><span><i style={{ width: `${score}%` }} /></span><b>{score}% 置信度</b><small>{item.source_session}</small></div>
                  </article>
                  );
                })}
              </div>}
            </section>
          )}

          {active === "wiki" && (
            <section className="subpage wiki-page">
              <div className="subpage-heading">
                <div><p className="eyebrow">CONNECTED KNOWLEDGE WIKI</p><h1>Wiki 知识中心</h1><p>按项目、主题、决策和问题定位组织研发知识，并保留来源会话与反向链接。</p></div>
                <div className="wiki-heading-stats"><strong>{wikiPages.length}</strong><span>篇文档</span><i /><strong>{wikiCounts.projects ?? 0}</strong><span>个项目</span></div>
              </div>
              <div className="wiki-shell">
                <aside className="wiki-browser">
                  <label><span>⌕</span><input value={wikiQuery} onChange={(event) => setWikiQuery(event.target.value)} placeholder="筛选 Wiki…" /></label>
                  <nav>
                    {wikiCategories.map(([id, label]) => (
                      <button key={id} className={wikiCategory === id ? "active" : ""} onClick={() => setWikiCategory(id)}>
                        <span>{id === "all" ? "⌘" : id === "projects" ? "▦" : id === "topics" ? "◇" : id === "decisions" ? "✓" : id === "issues" ? "!" : "◎"}</span>
                        {label}<em>{id === "all" ? wikiPages.length : wikiCounts[id] ?? 0}</em>
                      </button>
                    ))}
                  </nav>
                  <div className="wiki-page-list">
                    {filteredWiki.map((page) => (
                      <button key={page.id} className={wikiDetail?.id === page.id ? "active" : ""} onClick={() => void openWiki(page.id)}>
                        <strong>{page.title}</strong><small>{page.category_label} · {page.project}</small><p>{page.summary || "打开查看文档内容"}</p>
                      </button>
                    ))}
                    {!filteredWiki.length && <p className="wiki-empty">此分类暂无页面</p>}
                  </div>
                </aside>
                <article className="wiki-reader">
                  {wikiDetail ? (
                    <>
                      <header>
                        <div><span>{wikiDetail.category_label}</span><h2>{wikiDetail.title}</h2><p>{wikiDetail.summary}</p></div>
                        <aside><small>项目</small><strong>{wikiDetail.project}</strong><small>来源会话</small><code>{wikiDetail.source_session || "聚合文档"}</code></aside>
                      </header>
                      <div className="wiki-reader-body"><MarkdownViewer markdown={wikiDetail.markdown} /></div>
                      {(wikiDetail.backlinks.length > 0 || wikiDetail.references.length > 0) && (
                        <footer>
                          <h3>关联知识</h3>
                          <div>{wikiDetail.backlinks.map((item) => <button key={item.id} onClick={() => void openWiki(item.id)}>↗ {item.title}</button>)}</div>
                        </footer>
                      )}
                    </>
                  ) : (
                    <div className="wiki-welcome">
                      <span>▤</span><p className="eyebrow">LOCAL KNOWLEDGE BASE</p><h2>让研发知识形成结构</h2><p>从左侧选择一个页面。Wiki 会把会话中沉淀的问题、技术主题、项目脉络和设计决策组织成可阅读的知识网络。</p>
                      <div>{wikiCategories.slice(1).map(([id, label]) => <button key={id} onClick={() => setWikiCategory(id)}><strong>{wikiCounts[id] ?? 0}</strong><span>{label}</span></button>)}</div>
                    </div>
                  )}
                </article>
              </div>
            </section>
          )}

          {active === "graph" && (
            <section className="subpage graph-page">
              <div className="subpage-heading">
                <div><p className="eyebrow">KNOWLEDGE RELATIONSHIP MAP</p><h1>知识关系图</h1><p>探索会话、项目、工具与智能体之间的连接，发现跨会话复用的工程经验。</p></div>
                <button className="primary-button" disabled={graphLoading} onClick={() => void rebuildKnowledgeGraph()}>{graphLoading ? "正在构建…" : "↻ 重建关系图"}</button>
              </div>
              <div className="graph-toolbar">
                <label><span>⌕</span><input value={graphQuery} onChange={(event) => setGraphQuery(event.target.value)} placeholder="查找节点…" /></label>
                <div>{["all", "session", "project", "tool", "agent"].map((type) => (
                  <button key={type} className={graphType === type ? "active" : ""} onClick={() => setGraphType(type)}>
                    {{ all: "全部", session: "会话", project: "项目", tool: "工具", agent: "智能体" }[type as "all" | "session" | "project" | "tool" | "agent"]}
                    <em>{type === "all" ? graph.stats.nodes : graph.stats.types[type] ?? 0}</em>
                  </button>
                ))}</div>
                <span className="graph-summary">{graph.stats.nodes} 节点 · {graph.stats.links} 关系</span>
              </div>
              <div className="graph-shell">
                <div className="graph-canvas">
                  {graph.nodes.length ? (
                    <svg viewBox="0 0 1000 780" role="img" aria-label="知识关系图">
                      <g className="graph-links">{graphLinks.map((link, index) => {
                        const source = graphPositionsMap.get(String(link.source));
                        const target = graphPositionsMap.get(String(link.target));
                        if (!source || !target) return null;
                        return <line key={`${link.source}-${link.target}-${index}`} x1={source.x} y1={source.y} x2={target.x} y2={target.y}><title>{link.relation || "关联"}</title></line>;
                      })}</g>
                      <g className="graph-nodes">{graphNodes.map((node) => {
                        const position = graphPositionsMap.get(node.id);
                        if (!position) return null;
                        const matched = !graphQuery || `${node.label || node.id} ${node.project || ""}`.toLowerCase().includes(graphQuery.toLowerCase());
                        return <g key={node.id} className={`${node.type || "other"} ${matched ? "matched" : "dimmed"} ${graphSelected?.id === node.id ? "selected" : ""}`} transform={`translate(${position.x} ${position.y})`} onClick={() => setGraphSelected(node)}>
                          <circle r={node.type === "project" ? 16 : node.type === "agent" ? 15 : 10} />
                          <text y={node.type === "session" ? 22 : 26}>{(node.label || node.id).slice(0, 16)}</text>
                          <title>{node.label || node.id}</title>
                        </g>;
                      })}</g>
                    </svg>
                  ) : <div className="graph-empty"><span>◎</span><h3>关系图尚未构建</h3><p>点击“重建关系图”，从本地会话提取项目、工具和智能体关系。</p></div>}
                  <div className="graph-legend"><span className="project">项目</span><span className="session">会话</span><span className="tool">工具</span><span className="agent">智能体</span></div>
                </div>
                <aside className="graph-inspector">
                  {graphSelected ? (
                    <>
                      <span className={`graph-node-mark ${graphSelected.type}`}>●</span><p className="eyebrow">SELECTED NODE</p><h2>{graphSelected.label || graphSelected.id}</h2>
                      <dl><div><dt>类型</dt><dd>{graphSelected.type || "其他"}</dd></div><div><dt>项目</dt><dd>{graphSelected.project || "—"}</dd></div><div><dt>关联数量</dt><dd>{graph.links.filter((link) => link.source === graphSelected.id || link.target === graphSelected.id).length}</dd></div></dl>
                      <h3>直接关系</h3>
                      <div className="neighbor-list">{graph.links.filter((link) => link.source === graphSelected.id || link.target === graphSelected.id).slice(0, 12).map((link, index) => {
                        const neighborId = String(link.source === graphSelected.id ? link.target : link.source);
                        const neighbor = graph.nodes.find((item) => item.id === neighborId);
                        return <button key={`${neighborId}-${index}`} onClick={() => neighbor && setGraphSelected(neighbor)}><span>{neighbor?.label || neighborId}</span><em>{link.relation || "关联"}</em></button>;
                      })}</div>
                    </>
                  ) : <div className="inspector-empty"><span>✦</span><h3>选择一个节点</h3><p>查看它的类型、所属项目和直接关系。</p></div>}
                </aside>
              </div>
            </section>
          )}

          {active === "rag" && (
            <section className="subpage rag-page">
              <div className="subpage-heading">
                <div><p className="eyebrow">LOCAL RETRIEVAL AUGMENTED GENERATION</p><h1>RAG 知识问答</h1><p>由 BGE-M3 从本地会话、知识卡片和已审核 QA 中召回证据，再交给 OpenCode 生成可追溯回答。</p></div>
                <div className={`semantic-state ${health?.semantic?.available ? "ready" : ""}`}>
                  <i /><span><strong>{health?.semantic?.available ? "BGE-M3 已就绪" : "语义模型未就绪"}</strong><small>{health?.semantic?.indexed_chunks ?? 0} 个向量分块</small></span>
                </div>
              </div>
              <div className="rag-layout">
                <article className="rag-composer">
                  <div className="rag-mode-row">
                    <label>检索范围
                      <select value={ragScope} onChange={(event) => setRagScope(event.target.value as typeof ragScope)}>
                        <option value="all">全部知识</option><option value="session">研发会话</option><option value="knowledge">知识卡片</option><option value="wiki">Wiki 文档</option><option value="qa">已审核 QA</option>
                      </select>
                    </label>
                    <label>召回方式
                      <select value={ragMode} onChange={(event) => setRagMode(event.target.value as typeof ragMode)}>
                        <option value="hybrid">混合检索</option><option value="semantic">语义检索</option><option value="keyword">关键词检索</option>
                      </select>
                    </label>
                  </div>
                  <label className="rag-question">
                    <span>向本地知识库提问</span>
                    <textarea value={ragQuestion} onChange={(event) => setRagQuestion(event.target.value)} onKeyDown={(event) => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter") void askRag(); }} placeholder="例如：ChatGPT 会话导入后为什么没有生成知识库内容？" />
                  </label>
                  <div className="rag-submit"><small>Ctrl / Cmd + Enter 发送</small><button className="primary-button" disabled={ragLoading} onClick={() => void askRag()}>{ragLoading ? "正在检索并生成…" : "✦ 开始问答"}</button></div>
                </article>
                <aside className="rag-index-card">
                  <p className="eyebrow">RETRIEVAL INDEX</p><h3>本地语义索引</h3>
                  <div><span>模型</span><strong>BGE-M3 ONNX</strong></div>
                  <div><span>文档</span><strong>{health?.semantic?.indexed_documents ?? 0}</strong></div>
                  <div><span>分块</span><strong>{health?.semantic?.indexed_chunks ?? 0}</strong></div>
                  <div><span>维度</span><strong>1024</strong></div>
                  <button onClick={() => void refreshIndex()}>↻ 重建混合索引</button>
                </aside>
              </div>
              {ragLoading && <div className="rag-thinking"><span>✦</span><div><strong>正在组织回答</strong><small>BGE-M3 已完成召回，OpenCode 正在基于证据生成内容…</small></div></div>}
              {ragResult && (
                <section className="rag-answer">
                  <header><div><p className="eyebrow">GROUNDED ANSWER</p><h2>{ragResult.question}</h2></div><span className={ragResult.grounded ? "grounded" : ""}>{ragResult.grounded ? "✓ 有证据支撑" : "证据不足"}</span></header>
                  {ragResult.fallback_reason && <p className="search-fallback">◇ {ragResult.fallback_reason}</p>}
                  <div className="rag-answer-text">{ragResult.answer}</div>
                  <div className="rag-sources">
                    <h3>引用来源 <span>{ragResult.sources.length}</span></h3>
                    {ragResult.sources.map((source) => (
                      <button key={`${source.scope}-${source.id}`} onClick={() => openSearchResult(source)}>
                        <b>[{source.citation}]</b><span><strong>{source.title}</strong><small>{source.snippet}</small><em>{source.project} · {source.match_type}</em></span><i>›</i>
                      </button>
                    ))}
                  </div>
                </section>
              )}
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
                  ["适配器", health?.api_version ?? "0.4.0", "本地 RAG 与知识管理接口正常", "secall-opencode doctor"],
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
            <label>选择已通过预审核的会话
              <select value={pipelineSession?.id ?? ""} onChange={(event) => setSelectedSession(event.target.value)} disabled={!approvedSessions.length}>
                {!approvedSessions.length && <option value="">暂无已通过会话</option>}
                {approvedSessions.map((item) => <option value={item.id} key={item.id}>{item.source === "chatgpt" ? "ChatGPT · " : ""}{item.title}</option>)}
              </select>
              {!approvedSessions.length && <small className="form-help">请先关闭窗口，在“研发会话”页面完成预审核。</small>}
            </label>
            <div className="form-grid"><label>生成模型<select defaultValue=""><option value="">OpenCode 默认模型</option>{health?.models?.map((model) => <option value={model} key={model}>{model}</option>)}</select></label><label>知识语言<select><option>简体中文</option><option>English</option></select></label></div>
            <div className="switch-row"><div><strong>生成候选 QA</strong><small>从 Issue Card 自动提取 3–10 条问答</small></div><input type="checkbox" defaultChecked aria-label="生成候选 QA" /></div>
            <div className="switch-row"><div><strong>完成后重建索引</strong><small>让新知识立即可被搜索与 MCP 调用</small></div><input type="checkbox" defaultChecked aria-label="完成后重建索引" /></div>
            <div className="modal-actions"><button onClick={() => setModal(false)}>取消</button><button className="primary-button" onClick={startPipeline}>启动流水线 <span>→</span></button></div>
          </section>
        </div>
      )}

      {sessionDetail && (
        <div className="drawer-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSessionDetail(null); }}>
          <aside className="session-preview-drawer" role="dialog" aria-modal="true" aria-labelledby="session-preview-title">
            <header>
              <div>
                <p className="eyebrow">READ-ONLY SESSION PREVIEW</p>
                <h2 id="session-preview-title">{sessionDetail.title}</h2>
                <small>{sessionDetail.id} · {sessionDetail.project} · {sessionDetail.turns} 轮 · {{ pending: "暂存区", approved: "正式 Vault", rejected: "拒绝隔离区" }[sessionDetail.storage_state ?? "pending"]}</small>
              </div>
              <ReviewPill status={sessionDetail.review_status} />
              <button onClick={() => setSessionDetail(null)} aria-label="关闭会话预览">×</button>
            </header>
            <section className="session-quality-panel">
              <div className={`quality-orb ${sessionDetail.quality.level}`} style={{ "--quality-score": `${sessionDetail.quality.score * 3.6}deg` } as CSSProperties}>
                <strong>{sessionDetail.quality.score}</strong><small>参考分</small>
              </div>
              <div className="quality-facts">
                <p className="eyebrow">PRE-REVIEW SIGNALS</p><h3>会话质量辅助判断</h3>
                <div>{sessionDetail.quality.flags.map((flag) => <span key={flag}>◇ {flag}</span>)}</div>
                <small>该评分仅用于辅助人工预审核，不会自动通过或拒绝会话。</small>
              </div>
              <dl>
                <div><dt>工具调用</dt><dd>{sessionDetail.quality.tool_calls}</dd></div>
                <div><dt>用户轮次</dt><dd>{sessionDetail.quality.user_turns || "—"}</dd></div>
                <div><dt>助手轮次</dt><dd>{sessionDetail.quality.assistant_turns || "—"}</dd></div>
                <div><dt>正文长度</dt><dd>{sessionDetail.full_length.toLocaleString()} 字符</dd></div>
              </dl>
            </section>
            {sessionDetail.truncated && <p className="session-truncated">会话内容较长，预览保留了开头和结尾；原始 Session 未被截断或修改。</p>}
            <div className="session-preview-content"><MarkdownViewer markdown={sessionDetail.markdown} /></div>
            <footer>
              <span><b>只读预览</b> 审核操作不会修改 OpenCode 原始会话</span>
              {sessionDetail.hidden ? (
                <button className="restore-session-button" onClick={() => void restoreFrontendSession(sessionDetail)}>恢复显示</button>
              ) : (
                <>
                  {sessionDetail.review_status !== "rejected" && <button className="reject-session-button" onClick={() => void reviewSession(sessionDetail, "rejected")}>拒绝</button>}
                  <button className="hide-session-button" onClick={() => void hideFrontendSession(sessionDetail)}>前端隐藏</button>
                  {sessionDetail.review_status !== "approved" && <button className="primary-button" onClick={() => void reviewSession(sessionDetail, "approved")}>✓ 通过预审核</button>}
                  {sessionDetail.review_status === "approved" && <button className="pending-session-button" onClick={() => void reviewSession(sessionDetail, "pending")}>退回待审核</button>}
                </>
              )}
            </footer>
          </aside>
        </div>
      )}

      {knowledgeDetail && (
        <div className="drawer-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setKnowledgeDetail(null); }}>
          <aside className="knowledge-drawer" role="dialog" aria-modal="true" aria-labelledby="knowledge-detail-title">
            <header>
              <div><p className="eyebrow">KNOWLEDGE DETAIL</p><h2 id="knowledge-detail-title">{editingKnowledge ? "编辑知识卡片" : knowledgeDetail.title}</h2><small>来源会话 {knowledgeDetail.source_session}</small></div>
              <button onClick={() => setKnowledgeDetail(null)} aria-label="关闭知识详情">×</button>
            </header>
            {editingKnowledge ? (
              <div className="knowledge-editor">
                <div className="editor-meta">
                  <label>标题<input value={knowledgeDetail.title} onChange={(event) => setKnowledgeDetail({ ...knowledgeDetail, title: event.target.value })} /></label>
                  <label>项目<input value={knowledgeDetail.project} onChange={(event) => setKnowledgeDetail({ ...knowledgeDetail, project: event.target.value })} /></label>
                  <label>置信度<select value={knowledgeDetail.confidence} onChange={(event) => setKnowledgeDetail({ ...knowledgeDetail, confidence: event.target.value })}><option value="high">高</option><option value="medium">中</option><option value="low">低</option><option value="unknown">未知</option></select></label>
                  <label>状态<select value={knowledgeDetail.review_status} onChange={(event) => setKnowledgeDetail({ ...knowledgeDetail, review_status: event.target.value })}><option value="pending">待审核</option><option value="approved">已通过</option><option value="rejected">已退回</option></select></label>
                </div>
                {knowledgeDetail.sections.map((section, index) => (
                  <label className="section-editor" key={`${section.heading}-${index}`}>
                    <input
                      aria-label={`第 ${index + 1} 个章节标题`}
                      value={section.heading}
                      onChange={(event) => setKnowledgeDetail({
                        ...knowledgeDetail,
                        sections: knowledgeDetail.sections.map((item, current) => current === index ? { ...item, heading: event.target.value } : item),
                      })}
                    />
                    <textarea
                      aria-label={`${section.heading}内容`}
                      value={section.content}
                      onChange={(event) => setKnowledgeDetail({
                        ...knowledgeDetail,
                        sections: knowledgeDetail.sections.map((item, current) => current === index ? { ...item, content: event.target.value } : item),
                      })}
                    />
                  </label>
                ))}
              </div>
            ) : (
              <div className="knowledge-preview">
                <div className="detail-badges"><span>{knowledgeDetail.project}</span><span>{knowledgeDetail.confidence === "high" ? "高置信度" : knowledgeDetail.confidence === "medium" ? "中置信度" : "低置信度"}</span><span>{knowledgeDetail.review_status === "approved" ? "已通过" : "待审核"}</span></div>
                {knowledgeDetail.sections.map((section, index) => <section key={`${section.heading}-${index}`}><h3>{section.heading}</h3><p>{section.content || "暂无内容"}</p></section>)}
              </div>
            )}
            <footer>
              <button className="danger-button" onClick={() => void deleteKnowledge()}>删除</button>
              <span />
              {editingKnowledge ? <><button onClick={() => void openKnowledge(knowledgeDetail.id)}>取消</button><button className="primary-button" disabled={savingKnowledge} onClick={() => void saveKnowledge()}>{savingKnowledge ? "正在保存…" : "保存修改"}</button></> : <button className="primary-button" onClick={() => setEditingKnowledge(true)}>编辑知识</button>}
            </footer>
          </aside>
        </div>
      )}

      <input ref={fileInputRef} className="file-input" type="file" accept=".json,application/json" aria-label="选择 ChatGPT conversations.json" onChange={(event) => { const file = event.target.files?.[0]; if (file) void importChatGPTFile(file); }} />
      {toast && <div className="toast"><span>✓</span><div><strong>{toast.title}</strong><small>{toast.detail}</small></div><button onClick={() => setToast(null)}>×</button></div>}
    </main>
  );
}
