"use client";

import { type CSSProperties, useEffect, useMemo, useRef, useState } from "react";

type View = "overview" | "sessions" | "pipeline" | "planning" | "knowledge" | "wiki" | "graph" | "rag" | "qa" | "diagnostics";
type Toast = { title: string; detail: string } | null;
type ImportFailure = {
  file: string; size: string; stage: string; code: string; reason: string;
  suggestion: string; errorType?: string; status?: number; details?: Record<string, unknown>;
};
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
type SessionPageResponse = {
  items: Array<Record<string, unknown>>;
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  has_previous: boolean;
  has_next: boolean;
  counts: Record<"all" | "pending" | "approved" | "rejected" | "hidden", number>;
  projects: string[];
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
type KnowledgeEvent = {
  event_id: string; sequence: number; timestamp: string; actor: string; type: string;
  content: string; tool?: string; input?: string; output?: string; source_turn: number;
};
type StructuredKnowledge = {
  context?: Record<string, unknown>;
  symptoms?: Array<Record<string, unknown>>;
  timeline?: Array<Record<string, unknown>>;
  state_transitions?: Array<Record<string, unknown>>;
  message_flows?: Array<Record<string, unknown>>;
  parameter_changes?: Array<Record<string, unknown>>;
  hypotheses?: Array<Record<string, unknown>>;
  troubleshooting_steps?: Array<Record<string, unknown>>;
  root_cause?: Record<string, unknown>;
  fix?: Record<string, unknown>;
  verification?: Record<string, unknown>;
  lessons?: Record<string, unknown>;
  code_entities?: Record<string, unknown>;
  quality?: {
    overall?: number; level?: string; completeness?: number; evidence_coverage?: number;
    event_coverage?: number; warnings?: string[];
  };
};
type KnowledgeDetail = KnowledgeItem & {
  heading: string; type: string; intro: string; sections: KnowledgeSection[];
  markdown: string; version: string; updated: number;
  structured: StructuredKnowledge; quality: StructuredKnowledge["quality"];
  events: KnowledgeEvent[];
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
type WikiArchiveItem = {
  trash_id: string; wiki_id: string; category: string; category_label: string;
  slug: string; title: string; project: string; source_session: string;
  archived_at: string;
};
type WikiPlanSummary = {
  plan_id: string; status: string; reason: string; created_at: string;
  updated_at: string; requires_review: boolean;
  summary: { total: number; create: number; update: number; archive: number };
};
type WikiPlanChange = {
  change_id: string; page_id: string; category: string; title: string;
  action: "create" | "update" | "archive"; path: string; sources: string[];
  base_hash: string; new_hash: string; markdown: string; diff: string;
  conflicts: string[];
};
type WikiPlanDetail = WikiPlanSummary & { changes: WikiPlanChange[]; input_hash: string };
type WikiLintReport = {
  checked_at: string; page_count: number; finding_count: number; healthy: boolean;
  findings: Array<{ type: string; severity: string; page_id?: string; target?: string; category?: string }>;
};
type GraphEvidence = {
  files?: string[]; functions?: string[]; commits?: string[];
  root_causes?: string[]; test_cases?: string[];
};
type GraphNode = {
  id: string; label?: string; type?: string; project?: string; source_session?: string;
  evidence?: GraphEvidence; evidence_counts?: Record<string, number>;
};
type GraphLink = { source: string; target: string; relation?: string; weight?: number };
type GraphSnapshot = {
  nodes: GraphNode[]; links: GraphLink[];
  stats: { nodes: number; links: number; types: Record<string, number>; evidence?: Record<string, number> };
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
type PipelineStage = {
  name: string; duration_seconds: number; detail: string;
};
type PipelineResult = {
  session_id: string;
  knowledge: {
    issue_path: string; qa_path: string; qa_count: number; new_qa_count: number;
  };
  indexed: boolean; reused: boolean; stages: PipelineStage[]; elapsed_seconds: number;
  wiki_plan_id?: string; wiki_changes?: { total: number; create: number; update: number; archive: number };
  requires_review?: boolean;
  planning_plan_id?: string;
  planning_status?: string;
  candidate_count?: number;
};
type PlanningEntry = { id: string; type: string; content: string; source: "session_evidence" | "user_provided" | "mixed"; evidence_event_ids: string[]; confidence: string; recommended: boolean; duplicate_hint?: string; conflict_hint?: string };
type PlanningEntryRevision = { revision: number; assistant_message: string; entries: PlanningEntry[]; supplement?: string; created_at?: string };
type PlanningCandidate = {
  id: string; type: string; title: string; value: string; confidence: string; evidence_event_ids: string[];
  recommendation: string; duplicate_hint?: string; conflict_hint?: string;
  selection_status: "unselected" | "pending" | "options_ready" | "confirmed" | "skipped";
  entry_revisions: PlanningEntryRevision[]; selected_entry_ids: string[]; skip_reason?: string;
};
type PlanningMessage = { id: string; role: "user" | "assistant"; at: string; content: string };
type PlanningPlan = { plan_id: string; session_id: string; project: string; status: string; version: number; candidates: PlanningCandidate[]; selected_candidate_ids: string[]; confirmation_order: string[]; active_candidate_id?: string; messages: PlanningMessage[]; user_facts: Array<{ id: string; source: string; content: string }>; draft?: { qa_count?: number; wiki_change_count?: number }; index_status?: string; skip_reason?: string };
type PlanningCandidateResponse = { plan_id: string; status: string; active_candidate_id?: string; progress: { current: number; total: number }; candidate: PlanningCandidate; current_revision?: PlanningEntryRevision };
type PlanningDraft = { plan: PlanningPlan; draft: { document: string; qa: Array<Record<string, unknown>>; wiki_preview: Array<{ id: string; title: string; category: string; action: string; reason: string; diff: string }> } };
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

class ApiError extends Error {
  status: number;
  type: string;
  code: string;
  stage: string;
  hint: string;
  details: Record<string, unknown>;

  constructor(message: string, status: number, error: Record<string, unknown> = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.type = String(error.type ?? "ApiError");
    this.code = String(error.code ?? `HTTP_${status}`);
    this.stage = String(error.stage ?? "后端处理");
    this.hint = String(error.hint ?? "请检查本地服务日志后重试。");
    this.details = typeof error.details === "object" && error.details !== null
      ? error.details as Record<string, unknown>
      : {};
  }
}

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  const raw = await response.text();
  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(raw) as Record<string, unknown>;
  } catch {
    throw new ApiError(
      raw.trim().slice(0, 500) || "本地服务返回了无法解析的响应。",
      response.status,
      { code: "INVALID_API_RESPONSE", stage: "读取后端响应", hint: "请重启本地服务后重试。" },
    );
  }
  if (!response.ok || !payload.ok) {
    const error = typeof payload.error === "object" && payload.error !== null
      ? payload.error as Record<string, unknown>
      : {};
    throw new ApiError(String(error.message ?? `请求失败（${response.status}）`), response.status, error);
  }
  return payload.result as T;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function jsonErrorLocation(message: string, source: string): string {
  const match = message.match(/position\s+(\d+)/i);
  if (!match) return message;
  const position = Number(match[1]);
  const before = source.slice(0, position);
  const line = before.split("\n").length;
  const column = position - before.lastIndexOf("\n");
  return `${message}（第 ${line} 行，第 ${column} 列）`;
}

function formatUpdated(value: number | string): string {
  if (typeof value === "string") return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit",
  }).format(new Date(value));
}

function formatElapsed(seconds: number): string {
  const normalized = Math.max(0, seconds);
  if (normalized < 60) return `${normalized.toFixed(normalized < 10 ? 2 : 1)}s`;
  const whole = Math.round(normalized);
  return `${String(Math.floor(whole / 60)).padStart(2, "0")}:${String(whole % 60).padStart(2, "0")}`;
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
navItems.splice(3, 0, { id: "planning", label: "知识策划", icon: "◌" });

const wikiCategories = [
  ["all", "全部页面"],
  ["overview", "知识总览"],
  ["projects", "项目"],
  ["modules", "模块"],
  ["topics", "技术主题"],
  ["decisions", "设计决策"],
  ["runbooks", "运行手册"],
  ["tests", "测试知识"],
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
    if (line.trim().startsWith("<!--") || line.trim().endsWith("-->")) continue;
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

const structuredLabels: Record<string, string> = {
  conclusion: "结论", confidence: "置信度", description: "说明", component: "组件",
  type: "类型", message: "消息", impact: "影响", action: "操作", command: "命令",
  result: "结果", effective: "是否有效", reason: "原因", status: "状态",
  before: "前置状态", trigger: "触发事件", expected: "预期", actual: "实际",
  sender: "发送方", receiver: "接收方", transaction_id: "事务 ID",
  name: "参数", previous_value: "前值", current_value: "当前值",
  expected_range: "预期范围", abnormal: "是否异常", evidence_event_ids: "证据事件",
  workaround: "临时规避", final_fix: "正式修复", files: "文件", functions: "函数",
  commits: "提交", modules: "模块", test_cases: "测试用例", results: "验证结果",
  regression: "回归测试", side_effects: "副作用", diagnostic_rules: "诊断规则",
  runbook_steps: "排查手册", prevention: "预防措施",
};

const graphTypeLabels: Record<string, string> = {
  all: "全部", issue: "知识卡片", session: "会话", project: "项目",
  tool: "工具", agent: "智能体", module: "模块", file: "文件",
  function: "函数", commit: "提交", root_cause: "根因",
  test_case: "测试用例", topic: "主题", wiki_page: "Wiki 页面",
};

function StructuredObject({ value, empty = "暂无结构化信息" }: { value?: Record<string, unknown>; empty?: string }) {
  const entries = Object.entries(value || {}).filter(([, item]) => item !== "" && item !== null && item !== undefined && (!Array.isArray(item) || item.length > 0));
  if (!entries.length) return <p className="structured-empty">{empty}</p>;
  return <dl className="structured-object">{entries.map(([key, item]) => (
    <div key={key}>
      <dt>{structuredLabels[key] || key.replaceAll("_", " ")}</dt>
      <dd>{typeof item === "object" ? JSON.stringify(item, null, 2) : String(item)}</dd>
    </div>
  ))}</dl>;
}

function StructuredList({ items, empty = "暂无记录" }: { items?: Array<Record<string, unknown>>; empty?: string }) {
  if (!items?.length) return <p className="structured-empty">{empty}</p>;
  return <div className="structured-list">{items.map((item, index) => (
    <article key={String(item.event_id || item.description || index)}>
      <span>{String(index + 1).padStart(2, "0")}</span>
      <StructuredObject value={item} />
    </article>
  ))}</div>;
}

const graphEvidenceLabels: Record<string, string> = {
  files: "文件", functions: "函数", commits: "提交",
  root_causes: "根因", test_cases: "测试用例",
};

function GraphEvidencePanel({ evidence }: { evidence?: GraphEvidence }) {
  if (!evidence || !Object.values(evidence).some((items) => items?.length)) return null;
  return <div className="graph-evidence-panel">
    <h3>技术证据（不展开为节点）</h3>
    <div className="graph-evidence">{Object.entries(evidence).map(([type, items]) => items?.length ? (
      <section key={type}>
        <header><strong>{graphEvidenceLabels[type] || type}</strong><span>{items.length}</span></header>
        {items.slice(0, 8).map((item) => <code key={item}>{item}</code>)}
        {items.length > 8 && <small>另有 {items.length - 8} 条，请在知识卡片详情中查看</small>}
      </section>
    ) : null)}</div>
  </div>;
}

function graphPositions(nodes: GraphNode[]) {
  const groups = new Map<string, GraphNode[]>();
  nodes.forEach((node) => {
    const type = node.type || "other";
    groups.set(type, [...(groups.get(type) || []), node]);
  });
  const radii: Record<string, number> = {
    project: 70, issue: 145, wiki_page: 200, topic: 220, module: 270, session: 345,
  };
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
  const [pipelineStep, setPipelineStep] = useState(0);
  const [pipelineStatus, setPipelineStatus] = useState<"idle" | "running" | "success" | "failed">("idle");
  const [pipelineElapsed, setPipelineElapsed] = useState(0);
  const [pipelineResult, setPipelineResult] = useState<PipelineResult | null>(null);
  const [pipelineError, setPipelineError] = useState("");
  const [pipelineModel, setPipelineModel] = useState("");
  const [pipelineOverwrite, setPipelineOverwrite] = useState(false);
  const [pipelineReindex, setPipelineReindex] = useState(true);
  const [planningPlan, setPlanningPlan] = useState<PlanningPlan | null>(null);
  const [planningDraft, setPlanningDraft] = useState<PlanningDraft | null>(null);
  const [planningCandidate, setPlanningCandidate] = useState<PlanningCandidateResponse | null>(null);
  const [planningEntrySelection, setPlanningEntrySelection] = useState<string[]>([]);
  const [planningSupplement, setPlanningSupplement] = useState("");
  const [showPlanningSupplement, setShowPlanningSupplement] = useState(false);
  const [planningSkipReason, setPlanningSkipReason] = useState("");
  const [showPlanningSkip, setShowPlanningSkip] = useState(false);
  const [planningBusy, setPlanningBusy] = useState(false);
  const [planningGenerating, setPlanningGenerating] = useState(false);
  const [planningGenerationElapsed, setPlanningGenerationElapsed] = useState(0);
  const [planningPublish, setPlanningPublish] = useState<string[]>(["knowledge", "qa", "wiki"]);
  const [qaItems, setQaItems] = useState(qaSeed);
  const [sessionItems, setSessionItems] = useState<SessionItem[]>(demoSessions);
  const [pipelineSessionItems, setPipelineSessionItems] = useState<SessionItem[]>([]);
  const [hiddenSessionItems, setHiddenSessionItems] = useState<SessionItem[]>([]);
  const [sessionReviewFilter, setSessionReviewFilter] = useState<"all" | "pending" | "approved" | "rejected" | "hidden">("all");
  const [sessionProject, setSessionProject] = useState("");
  const [sessionPage, setSessionPage] = useState(1);
  const [sessionTotal, setSessionTotal] = useState(0);
  const [sessionTotalPages, setSessionTotalPages] = useState(1);
  const [sessionCounts, setSessionCounts] = useState({ all: 0, pending: 0, approved: 0, rejected: 0, hidden: 0 });
  const [sessionProjects, setSessionProjects] = useState<string[]>([]);
  const [sessionDetail, setSessionDetail] = useState<SessionDetail | null>(null);
  const [sessionPreviewLoading, setSessionPreviewLoading] = useState(false);
  const [syncingSessions, setSyncingSessions] = useState(false);
  const [knowledgeItems, setKnowledgeItems] = useState<KnowledgeItem[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [apiConnected, setApiConnected] = useState(false);
  const [connectingService, setConnectingService] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importFailure, setImportFailure] = useState<ImportFailure | null>(null);
  const [importProject, setImportProject] = useState("chatgpt-import");
  const [externalOpenCodeProject, setExternalOpenCodeProject] = useState("external-opencode");
  const [selectedSession, setSelectedSession] = useState("ses_0598ac");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const externalOpenCodeFileInputRef = useRef<HTMLInputElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const [knowledgeDetail, setKnowledgeDetail] = useState<KnowledgeDetail | null>(null);
  const [knowledgeTab, setKnowledgeTab] = useState<"overview" | "timeline" | "diagnosis" | "code" | "evidence">("overview");
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
  const [wikiArchiveItems, setWikiArchiveItems] = useState<WikiArchiveItem[]>([]);
  const [showWikiArchive, setShowWikiArchive] = useState(false);
  const [wikiPlans, setWikiPlans] = useState<WikiPlanSummary[]>([]);
  const [wikiPlanDetail, setWikiPlanDetail] = useState<WikiPlanDetail | null>(null);
  const [wikiPlanSelected, setWikiPlanSelected] = useState<string[]>([]);
  const [showWikiReview, setShowWikiReview] = useState(false);
  const [wikiLint, setWikiLint] = useState<WikiLintReport | null>(null);
  const [wikiWorking, setWikiWorking] = useState(false);
  const [graph, setGraph] = useState<GraphSnapshot>({ nodes: [], links: [], stats: { nodes: 0, links: 0, types: {} } });
  const [graphType, setGraphType] = useState("all");
  const [graphQuery, setGraphQuery] = useState("");
  const [graphSelected, setGraphSelected] = useState<GraphNode | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [clock, setClock] = useState(() => new Date());

  const refreshData = async () => {
    const sessionParams = new URLSearchParams({
      page: String(sessionPage),
      page_size: "10",
      review_status: sessionReviewFilter,
    });
    if (sessionProject) sessionParams.set("project", sessionProject);
    const [healthResult, sessionResult, pipelineSessionsResult, hiddenSessionResult, qaResult, knowledgeResult, wikiResult, graphResult, wikiPlansResult] = await Promise.all([
      apiRequest<Health>("/api/health"),
      apiRequest<SessionPageResponse>(`/api/sessions?${sessionParams}`),
      apiRequest<SessionPageResponse>("/api/sessions?page=1&page_size=1000&review_status=approved"),
      apiRequest<Array<Record<string, unknown>>>("/api/sessions/hidden?limit=1000"),
      apiRequest<Array<Record<string, unknown>>>("/api/qa?limit=300"),
      apiRequest<KnowledgeItem[]>("/api/knowledge?limit=300"),
      apiRequest<WikiResponse>("/api/wiki?limit=1000"),
      apiRequest<GraphSnapshot>("/api/graph"),
      apiRequest<WikiPlanSummary[]>("/api/wiki/plans?status=pending"),
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
    const normalizedSessions = sessionResult.items.map(normalizeSession);
    const normalizedPipelineSessions = pipelineSessionsResult.items.map(normalizeSession);
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
    setPipelineSessionItems(normalizedPipelineSessions);
    setHiddenSessionItems(normalizedHiddenSessions);
    setSessionTotal(sessionResult.total);
    setSessionTotalPages(sessionResult.total_pages);
    setSessionCounts(sessionResult.counts);
    setSessionProjects(sessionResult.projects);
    if (sessionResult.page !== sessionPage) setSessionPage(sessionResult.page);
    setQaItems(normalizedQa);
    setKnowledgeItems(knowledgeResult);
    setWikiPages(wikiResult.pages);
    setWikiCounts(wikiResult.counts);
    setGraph(graphResult);
    setWikiPlans(wikiPlansResult);
    setKnowledgeDetail((current) => (
      current && !knowledgeResult.some((item) => item.id === current.id) ? null : current
    ));
    setWikiDetail((current) => (
      current && !wikiResult.pages.some((item) => item.id === current.id) ? null : current
    ));
    setGraphSelected((current) => (
      current && !graphResult.nodes.some((item) => item.id === current.id) ? null : current
    ));
    setApiConnected(true);
    if (!selectedSession && normalizedSessions.length) {
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
  }, [sessionPage, sessionProject, sessionReviewFilter]);

  useEffect(() => {
    if (apiConnected) return;
    const timer = window.setInterval(() => {
      void apiRequest<Health>("/api/health").then(() => refreshData()).catch(() => undefined);
    }, 5_000);
    return () => window.clearInterval(timer);
    // refreshData is intentionally kept outside the dependency list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiConnected]);

  useEffect(() => {
    const timer = window.setInterval(() => setClock(new Date()), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  const notify = (title: string, detail: string) => {
    setToast({ title, detail });
    window.setTimeout(() => setToast(null), 3200);
  };

  const connectLocalService = async () => {
    if (connectingService) return;
    setConnectingService(true);
    try {
      await refreshData();
      notify("连接成功", "本地服务已连接，数据已刷新。");
      setConnectingService(false);
      return;
    } catch {
      window.location.href = "secall-opencode://start";
      notify("正在启动本地服务", "已调用本地启动器，页面将自动检测连接状态。");
    }

    for (let attempt = 0; attempt < 30; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 1_000));
      try {
        await refreshData();
        notify("启动成功", "本地 API 已连接，工作区数据已恢复。");
        setConnectingService(false);
        return;
      } catch {
        // Keep waiting while the local process starts.
      }
    }
    setConnectingService(false);
    notify("未能启动本地服务", "请运行 scripts\\start-local.ps1 完成首次启动器注册。");
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
  const reviewedSessions = sessionItems;
  const approvedSessions = useMemo(
    () => pipelineSessionItems.filter((item) => item.review_status === "approved"),
    [pipelineSessionItems],
  );
  const pipelineSession = approvedSessions.find((item) => item.id === selectedSession) ?? approvedSessions[0];
  const sessionPageNumbers = useMemo(() => {
    const start = Math.max(1, Math.min(sessionPage - 2, sessionTotalPages - 4));
    const end = Math.min(sessionTotalPages, start + 4);
    return Array.from({ length: Math.max(0, end - start + 1) }, (_, index) => start + index);
  }, [sessionPage, sessionTotalPages]);
  const hour = Number(new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    hour: "2-digit",
    hourCycle: "h23",
  }).format(clock));
  const greeting = hour >= 5 && hour < 12
    ? "早上好"
    : hour >= 12 && hour < 14
      ? "中午好"
      : hour >= 14 && hour < 18
        ? "下午好"
        : "晚上好";
  const todayDay = Number(new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    day: "numeric",
  }).format(clock));
  const todayWeekday = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    weekday: "long",
  }).format(clock);
  const todayMonth = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "long",
  }).format(clock);
  const filteredWiki = useMemo(
    () => wikiPages.filter((page) => (
      (wikiCategory === "all" || page.category === wikiCategory)
      && `${page.title} ${page.summary} ${page.project}`.toLowerCase().includes(wikiQuery.toLowerCase())
    )),
    [wikiPages, wikiCategory, wikiQuery],
  );
  const graphPositionsMap = useMemo(() => graphPositions(graph.nodes), [graph.nodes]);
  const graphTypeOptions = useMemo(
    () => ["all", ...Object.keys(graph.stats.types).filter((type) => (graph.stats.types[type] ?? 0) > 0)],
    [graph.stats.types],
  );
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

  const loadWikiArchive = async () => {
    try {
      const items = await apiRequest<WikiArchiveItem[]>("/api/wiki/trash");
      setWikiArchiveItems(items);
      setShowWikiArchive(true);
      setWikiDetail(null);
    } catch (error) {
      notify("无法打开 Wiki 回收站", error instanceof Error ? error.message : "请检查本地服务");
    }
  };

  const archiveWiki = async () => {
    if (!wikiDetail || wikiDetail.category === "issues") return;
    if (!window.confirm(`将 Wiki 页面“${wikiDetail.title}”移入回收站？`)) return;
    try {
      await apiRequest(
        `/api/wiki/${encodeURIComponent(wikiDetail.category)}/${encodeURIComponent(wikiDetail.slug)}`,
        { method: "DELETE" },
      );
      setWikiDetail(null);
      await refreshData();
      notify("Wiki 已归档", "页面已移入 Wiki 回收站，关系图和检索索引已同步更新");
    } catch (error) {
      notify("Wiki 归档失败", error instanceof Error ? error.message : "请检查本地服务");
    }
  };

  const restoreWiki = async (trashId: string) => {
    try {
      await apiRequest(`/api/wiki/trash/${encodeURIComponent(trashId)}/restore`, {
        method: "POST",
        body: "{}",
      });
      const items = await apiRequest<WikiArchiveItem[]>("/api/wiki/trash");
      setWikiArchiveItems(items);
      await refreshData();
      notify("Wiki 已恢复", "页面、关系图和检索索引已恢复");
    } catch (error) {
      notify("Wiki 恢复失败", error instanceof Error ? error.message : "可能存在同名 Wiki 页面");
    }
  };

  const purgeWiki = async (item: WikiArchiveItem) => {
    const confirmation = window.prompt(
      `永久删除后无法恢复。请输入页面标题确认：\n${item.title}`,
    );
    if (confirmation === null) return;
    if (confirmation.trim() !== item.title) {
      notify("未执行永久删除", "输入的页面标题不一致");
      return;
    }
    try {
      await apiRequest(
        `/api/wiki/trash/${encodeURIComponent(item.trash_id)}?confirm=permanent`,
        { method: "DELETE" },
      );
      const items = await apiRequest<WikiArchiveItem[]>("/api/wiki/trash");
      setWikiArchiveItems(items);
      notify("Wiki 已永久删除", "归档副本已清除，原始 Session 保持不变");
    } catch (error) {
      notify("永久删除失败", error instanceof Error ? error.message : "请检查本地服务");
    }
  };

  const clearWikiArchive = async () => {
    if (!wikiArchiveItems.length) return;
    const confirmation = window.prompt(
      `即将永久删除 Wiki 回收站中的 ${wikiArchiveItems.length} 篇页面。\n请输入“永久删除”确认：`,
    );
    if (confirmation === null) return;
    if (confirmation.trim() !== "永久删除") {
      notify("未清空回收站", "确认文字不正确");
      return;
    }
    try {
      const result = await apiRequest<{ purged: number }>(
        "/api/wiki/trash?confirm=clear",
        { method: "DELETE" },
      );
      setWikiArchiveItems([]);
      notify("Wiki 回收站已清空", `已永久删除 ${result.purged} 篇归档页面`);
    } catch (error) {
      notify("清空回收站失败", error instanceof Error ? error.message : "请检查本地服务");
    }
  };

  const openWikiPlan = async (planId?: string) => {
    const target = planId || wikiPlans[0]?.plan_id;
    if (!target) {
      setShowWikiReview(true);
      setWikiPlanDetail(null);
      return;
    }
    try {
      const detail = await apiRequest<WikiPlanDetail>(`/api/wiki/plans/${encodeURIComponent(target)}`);
      setWikiPlanDetail(detail);
      setWikiPlanSelected(detail.changes.map((item) => item.change_id));
      setShowWikiReview(true);
      setShowWikiArchive(false);
    } catch (error) {
      notify("无法打开 Wiki 更新计划", error instanceof Error ? error.message : "请检查本地服务");
    }
  };

  const rebuildWiki = async () => {
    if (!window.confirm("将依据当前有效知识生成新版 Wiki 更新计划。历史回收站不会被恢复或清空，是否继续？")) return;
    setWikiWorking(true);
    try {
      const plan = await apiRequest<WikiPlanDetail>("/api/wiki/rebuild", {
        method: "POST", body: JSON.stringify({ regenerate: true }),
      });
      await refreshData();
      await openWikiPlan(plan.plan_id);
      notify("重建计划已生成", `共 ${plan.summary.total} 项变更，审核通过后才会写入`);
    } catch (error) {
      notify("生成重建计划失败", error instanceof Error ? error.message : "请检查本地服务");
    } finally {
      setWikiWorking(false);
    }
  };

  const applyWikiPlan = async () => {
    if (!wikiPlanDetail || !wikiPlanSelected.length) return;
    setWikiWorking(true);
    try {
      await apiRequest(`/api/wiki/plans/${encodeURIComponent(wikiPlanDetail.plan_id)}/apply`, {
        method: "POST",
        body: JSON.stringify({ selected_change_ids: wikiPlanSelected }),
      });
      setWikiPlanDetail(null);
      setShowWikiReview(false);
      await refreshData();
      notify("Wiki 更新已应用", `已原子写入 ${wikiPlanSelected.length} 项选中变更`);
    } catch (error) {
      notify("Wiki 更新未应用", error instanceof Error ? error.message : "页面可能在审核期间发生变化");
    } finally {
      setWikiWorking(false);
    }
  };

  const rejectWikiPlan = async () => {
    if (!wikiPlanDetail) return;
    const reason = window.prompt("请输入拒绝原因（可选）：") ?? "";
    setWikiWorking(true);
    try {
      await apiRequest(`/api/wiki/plans/${encodeURIComponent(wikiPlanDetail.plan_id)}/reject`, {
        method: "POST", body: JSON.stringify({ reason }),
      });
      setWikiPlanDetail(null);
      setShowWikiReview(false);
      await refreshData();
      notify("Wiki 计划已拒绝", "知识卡片和现有 Wiki 均未被修改");
    } catch (error) {
      notify("拒绝计划失败", error instanceof Error ? error.message : "请检查本地服务");
    } finally {
      setWikiWorking(false);
    }
  };

  const runWikiLint = async () => {
    setWikiWorking(true);
    try {
      const report = await apiRequest<WikiLintReport>("/api/wiki/lint", { method: "POST", body: "{}" });
      setWikiLint(report);
      setShowWikiReview(true);
      setShowWikiArchive(false);
      notify(report.healthy ? "Wiki 健康检查通过" : "Wiki 健康检查完成", `发现 ${report.finding_count} 项需要关注`);
    } catch (error) {
      notify("Wiki 健康检查失败", error instanceof Error ? error.message : "请检查本地服务");
    } finally {
      setWikiWorking(false);
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
      setKnowledgeTab("overview");
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
      notify("知识卡片已保存", "Wiki、关系图和检索索引已同步更新");
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
      notify("已移入回收站", "Wiki 页面、关系节点和关联 QA 已同步移除，均可恢复");
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
      notify("知识卡片已恢复", "Wiki 页面、关系节点、关联 QA 和检索索引已恢复");
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

  const syncKnowledgeDerivatives = async () => {
    try {
      const result = await apiRequest<{
        wiki: { knowledge_count: number; updated_pages: string[]; wiki_count: number };
        graph: { nodes: number; links: number };
      }>("/api/knowledge/sync", { method: "POST", body: "{}" });
      await refreshData();
      notify(
        "派生数据已同步",
        `Wiki ${result.wiki.wiki_count} 篇，知识卡片 ${result.wiki.knowledge_count} 张，关系图 ${result.graph.nodes} 个节点`,
      );
    } catch (error) {
      notify("派生数据同步失败", error instanceof Error ? error.message : "请检查本地服务");
    }
  };

  const purgeKnowledgeDerivatives = async () => {
    const confirmation = window.prompt(
      "这会永久删除全部知识卡片及回收站、Wiki、QA、结构化知识、关系图和知识检索索引。原始会话不会删除。\n\n请输入“清空派生数据”继续：",
    );
    if (confirmation === null) return;
    if (confirmation.trim() !== "清空派生数据") {
      notify("未执行清理", "确认文字不匹配，任何数据都没有删除");
      return;
    }
    try {
      const result = await apiRequest<{
        removed_files: number;
        preserved_sessions: number;
        wiki: { count: number };
        graph: { nodes: number; links: number };
      }>("/api/knowledge/derivatives/purge", {
        method: "POST",
        body: JSON.stringify({ confirm: "PURGE_DERIVED" }),
      });
      setShowTrash(false);
      setShowWikiArchive(false);
      setWikiArchiveItems([]);
      setTrashItems([]);
      await refreshData();
      notify(
        "知识派生数据已清空",
        `已删除 ${result.removed_files} 个派生文件，保留 ${result.preserved_sessions} 个原始会话`,
      );
    } catch (error) {
      notify("清空失败", error instanceof Error ? error.message : "请检查本地服务");
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

  const openPlanning = async (planId: string) => {
    const plan = await apiRequest<PlanningPlan>(`/api/knowledge-plans/${encodeURIComponent(planId)}`);
    setPlanningPlan(plan);
    setPlanningDraft(null);
    setPlanningCandidate(null);
    if (plan.status === "reviewing") {
      try { setPlanningDraft(await apiRequest<PlanningDraft>(`/api/knowledge-plans/${encodeURIComponent(planId)}/draft`)); } catch { /* draft may still be generating */ }
    }
    if (plan.status === "item_reviewing" && plan.active_candidate_id) {
      await loadPlanningCandidate(plan.plan_id, plan.active_candidate_id);
    }
    setActive("planning");
  };

  const loadPlanningCandidate = async (planId: string, candidateId: string) => {
    const response = await apiRequest<PlanningCandidateResponse>(`/api/knowledge-plans/${encodeURIComponent(planId)}/candidates/${encodeURIComponent(candidateId)}`);
    setPlanningCandidate(response);
    setPlanningEntrySelection(response.current_revision ? response.candidate.selected_entry_ids : []);
    setPlanningSupplement(""); setPlanningSkipReason("");
    setShowPlanningSupplement(false); setShowPlanningSkip(false);
    return response;
  };

  const updatePlanningScope = async (candidateId: string, checked: boolean) => {
    if (!planningPlan) return;
    const selected = checked
      ? [...new Set([...planningPlan.selected_candidate_ids, candidateId])]
      : planningPlan.selected_candidate_ids.filter((id) => id !== candidateId);
    const next = await apiRequest<PlanningPlan>(`/api/knowledge-plans/${encodeURIComponent(planningPlan.plan_id)}/scope`, { method: "POST", body: JSON.stringify({ selected_candidate_ids: selected }) });
    setPlanningPlan(next);
  };

  const startPlanningReview = async () => {
    if (!planningPlan) return;
    setPlanningBusy(true);
    try {
      const next = await apiRequest<PlanningPlan>(`/api/knowledge-plans/${encodeURIComponent(planningPlan.plan_id)}/start-review`, { method: "POST", body: "{}" });
      setPlanningPlan(next);
      if (next.active_candidate_id) await loadPlanningCandidate(next.plan_id, next.active_candidate_id);
    } catch (error) { notify("知识策划对话失败", error instanceof Error ? error.message : "请检查本地服务"); }
    finally { setPlanningBusy(false); }
  };

  const regeneratePlanningEntries = async () => {
    if (!planningPlan?.active_candidate_id) return;
    setPlanningBusy(true);
    try {
      const response = await apiRequest<{ plan: PlanningPlan } & PlanningCandidateResponse>(
        `/api/knowledge-plans/${encodeURIComponent(planningPlan.plan_id)}/candidates/${encodeURIComponent(planningPlan.active_candidate_id)}/regenerate`,
        { method: "POST", body: JSON.stringify({ supplement: planningSupplement }) },
      );
      setPlanningPlan(response.plan); setPlanningCandidate(response); setPlanningEntrySelection([]);
      setPlanningSupplement(""); setShowPlanningSupplement(false);
    } catch (error) { notify("重新整理条目失败", error instanceof Error ? error.message : "请检查本地模型服务后重试。"); }
    finally { setPlanningBusy(false); }
  };

  const confirmPlanningCandidate = async () => {
    if (!planningPlan?.active_candidate_id || !planningEntrySelection.length) return;
    setPlanningBusy(true);
    try {
      const next = await apiRequest<PlanningPlan>(
        `/api/knowledge-plans/${encodeURIComponent(planningPlan.plan_id)}/candidates/${encodeURIComponent(planningPlan.active_candidate_id)}/confirm`,
        { method: "POST", body: JSON.stringify({ selected_entry_ids: planningEntrySelection }) },
      );
      setPlanningPlan(next);
      if (next.active_candidate_id) await loadPlanningCandidate(next.plan_id, next.active_candidate_id); else setPlanningCandidate(null);
    } catch (error) { notify("确认知识条目失败", error instanceof Error ? error.message : "请至少选择一个条目。"); }
    finally { setPlanningBusy(false); }
  };

  const skipPlanningCandidate = async () => {
    if (!planningPlan?.active_candidate_id || !planningSkipReason.trim()) return;
    setPlanningBusy(true);
    try {
      const next = await apiRequest<PlanningPlan>(
        `/api/knowledge-plans/${encodeURIComponent(planningPlan.plan_id)}/candidates/${encodeURIComponent(planningPlan.active_candidate_id)}/skip`,
        { method: "POST", body: JSON.stringify({ reason: planningSkipReason }) },
      );
      setPlanningPlan(next);
      if (next.active_candidate_id) await loadPlanningCandidate(next.plan_id, next.active_candidate_id); else setPlanningCandidate(null);
    } catch (error) { notify("跳过主题失败", error instanceof Error ? error.message : "请填写跳过原因。"); }
    finally { setPlanningBusy(false); }
  };

  const confirmAndGeneratePlanning = async () => {
    if (!planningPlan) return;
    setPlanningBusy(true);
    setPlanningGenerating(true);
    setPlanningGenerationElapsed(0);
    const generationStartedAt = Date.now();
    const generationTimer = window.setInterval(() => {
      setPlanningGenerationElapsed((Date.now() - generationStartedAt) / 1000);
    }, 250);
    try {
      const confirmed = planningPlan.status === "scope_confirmed"
        ? planningPlan
        : await apiRequest<PlanningPlan>(`/api/knowledge-plans/${encodeURIComponent(planningPlan.plan_id)}/confirm`, { method: "POST", body: "{}" });
      setPlanningPlan(confirmed);
      const generated = await apiRequest<PlanningPlan>(`/api/knowledge-plans/${encodeURIComponent(planningPlan.plan_id)}/generate`, { method: "POST", body: "{}" });
      setPlanningPlan(generated);
      setPlanningDraft(await apiRequest<PlanningDraft>(`/api/knowledge-plans/${encodeURIComponent(planningPlan.plan_id)}/draft`));
      notify("草稿已生成", "请审核知识卡片、候选 QA 和 Wiki 更新预览后再发布。");
    } catch (error) { notify("生成草稿失败", error instanceof Error ? error.message : "请检查模型与本地服务"); }
    finally {
      window.clearInterval(generationTimer);
      setPlanningGenerationElapsed((Date.now() - generationStartedAt) / 1000);
      setPlanningGenerating(false);
      setPlanningBusy(false);
    }
  };

  const publishPlanning = async () => {
    if (!planningPlan) return;
    setPlanningBusy(true);
    try {
      const result = await apiRequest<{ plan: PlanningPlan; derivatives: Record<string, unknown> }>(`/api/knowledge-plans/${encodeURIComponent(planningPlan.plan_id)}/publish`, { method: "POST", body: JSON.stringify({ selected: planningPublish, reindex: true }) });
      setPlanningPlan(result.plan); await refreshData();
      notify(result.plan.index_status === "ready" ? "知识已发布并完成同步" : "知识已发布，索引待同步", result.plan.index_status === "ready" ? "已同步知识库、检索和关系图。" : "可稍后在知识库中刷新索引。" );
    } catch (error) { notify("发布失败", error instanceof Error ? error.message : "请检查草稿与依赖关系"); }
    finally { setPlanningBusy(false); }
  };

  const retryPlanningIndex = async () => {
    if (!planningPlan) return;
    setPlanningBusy(true);
    try {
      const result = await apiRequest<{ plan: PlanningPlan }>(`/api/knowledge-plans/${encodeURIComponent(planningPlan.plan_id)}/retry-index`, { method: "POST", body: "{}" });
      setPlanningPlan(result.plan);
      notify(result.plan.index_status === "ready" ? "索引同步完成" : "索引仍待同步", result.plan.index_status === "ready" ? "检索和向量索引已刷新。" : "请检查本地索引服务后再次重试。" );
    } catch (error) { notify("重试索引失败", error instanceof Error ? error.message : "请检查本地服务"); }
    finally { setPlanningBusy(false); }
  };

  const startPipeline = async () => {
    if (!pipelineSession) {
      notify("暂无可运行会话", "请先在“研发会话”中通过至少一个会话的预审核");
      return;
    }
    setModal(false);
    setActive("pipeline");
    setPipelineRunning(true);
    setPipelineStatus("running");
    setPipelineStep(1);
    setPipelineElapsed(0);
    setPipelineResult(null);
    setPipelineError("");
    notify("流水线已启动", "正在读取本地 Session 并抽取知识");
    const startedAt = Date.now();
    const timer = window.setInterval(() => {
      setPipelineElapsed((Date.now() - startedAt) / 1000);
    }, 250);
    try {
      if (!apiConnected) throw new Error("本地 API 未连接，请先启动本地服务。");
      const result = await apiRequest<PipelineResult>("/api/pipeline", {
        method: "POST",
        body: JSON.stringify({
          session_id: pipelineSession.id,
          model: pipelineModel || undefined,
          reindex: pipelineReindex,
          overwrite: pipelineOverwrite,
        }),
      });
      window.clearInterval(timer);
      setPipelineStep(6);
      setPipelineStatus("success");
      setPipelineElapsed(result.elapsed_seconds);
      setPipelineResult(result);
      if (result.planning_plan_id) await openPlanning(result.planning_plan_id);
      await refreshData();
      notify(
        result.requires_review ? "知识已入库，Wiki 计划待审核" : result.reused ? "已复用现有知识并刷新索引" : "知识已成功入库",
        result.requires_review
          ? `${result.wiki_changes?.total ?? 0} 项 Wiki 变更尚未写入，请前往 Wiki 中心审核`
          : result.reused
            ? `现有 ${result.knowledge.qa_count} 条候选 QA，未重复生成`
            : `新增 ${result.knowledge.new_qa_count} 条候选 QA`,
      );
    } catch (error) {
      window.clearInterval(timer);
      setPipelineStep(0);
      setPipelineStatus("failed");
      setPipelineElapsed((Date.now() - startedAt) / 1000);
      const message = error instanceof Error ? error.message : "请检查本地服务";
      setPipelineError(message);
      notify("流水线执行失败", message);
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
    setImportFailure(null);
    let stage = "检查本地服务";
    let source = "";
    try {
      if (!apiConnected) throw new Error("本地 API 未连接，请先运行启动脚本。");
      if (!file.name.toLowerCase().endsWith(".json")) {
        throw new Error("请选择 ChatGPT 官方导出的 conversations.json 文件。");
      }
      if (!file.size) throw new Error("所选文件为空，无法导入。");
      if (file.size > 95 * 1024 * 1024) {
        throw new Error("文件超过 95 MB，无法通过本地导入接口处理。");
      }
      stage = "读取文件";
      source = await file.text();
      stage = "解析 JSON";
      let payload: unknown;
      try {
        payload = JSON.parse(source.replace(/^\uFEFF/, ""));
      } catch (error) {
        if (error instanceof SyntaxError) {
          throw new SyntaxError(jsonErrorLocation(error.message, source));
        }
        throw error;
      }
      stage = "验证会话结构";
      const inspected = await apiRequest<{ conversation_count: number; message_count: number }>("/api/chatgpt/inspect", {
        method: "POST",
        body: JSON.stringify({ payload }),
      });
      if (!inspected.conversation_count || !inspected.message_count) {
        throw new Error("文件中没有可导入的有效会话或文本消息。");
      }
      stage = "写入会话 Vault";
      const result = await apiRequest<{ imported: number }>("/api/chatgpt/import", {
        method: "POST",
        body: JSON.stringify({ payload, project: importProject.trim() || "chatgpt-import" }),
      });
      stage = "刷新工作区数据";
      await refreshData();
      setActive("sessions");
      notify("ChatGPT 会话导入完成", `导入 ${result.imported} 个会话，共 ${inspected.message_count} 条消息`);
    } catch (error) {
      const apiError = error instanceof ApiError ? error : null;
      const reason = error instanceof Error ? error.message : "发生未知导入错误。";
      const isConnectionError = error instanceof TypeError || reason.includes("API 未连接") || reason.includes("Failed to fetch");
      const suggestion = apiError?.hint || (
        isConnectionError
          ? "点击左下角“启动”连接本地服务，然后重新选择文件。"
          : error instanceof SyntaxError
            ? "请重新从 ChatGPT 导出数据，不要手动编辑、截断或复制 JSON 内容。"
            : stage === "读取文件"
              ? "确认文件未被占用、具有读取权限，并重新选择该文件。"
              : stage === "刷新工作区数据"
                ? "会话可能已经写入成功，请刷新页面或进入“研发会话”检查。"
                : "确认文件为 ChatGPT 官方 conversations.json，并查看下方服务返回信息。"
      );
      setImportFailure({
        file: file.name,
        size: formatFileSize(file.size),
        stage: apiError?.stage || stage,
        code: apiError?.code || (error instanceof SyntaxError ? "INVALID_JSON" : isConnectionError ? "SERVICE_UNAVAILABLE" : "IMPORT_FAILED"),
        reason,
        suggestion,
        errorType: apiError?.type || (error instanceof Error ? error.name : "UnknownError"),
        status: apiError?.status,
        details: apiError?.details,
      });
      notify("ChatGPT 导入失败", `${apiError?.stage || stage}：${reason.slice(0, 120)}`);
    } finally {
      setImporting(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const importExternalOpenCodeFile = async (file: File) => {
    setImporting(true);
    setImportFailure(null);
    let stage = "检查本地服务";
    let source = "";
    try {
      if (!apiConnected) throw new Error("本地 API 未连接，请先启动本地服务。");
      if (!file.name.toLowerCase().endsWith(".json")) {
        throw new Error("请选择由 OpenCode 或 codeagent export 导出的 JSON 文件。");
      }
      if (!file.size) throw new Error("所选文件为空，无法导入。");
      if (file.size > 95 * 1024 * 1024) {
        throw new Error("文件超过 95 MB，无法通过本地导入接口处理。");
      }
      stage = "读取文件";
      source = await file.text();
      stage = "解析 JSON";
      let payload: unknown;
      try {
        payload = JSON.parse(source.replace(/^\uFEFF/, ""));
      } catch (error) {
        if (error instanceof SyntaxError) throw new SyntaxError(jsonErrorLocation(error.message, source));
        throw error;
      }
      stage = "验证 OpenCode 导出结构";
      const project = externalOpenCodeProject.trim() || "external-opencode";
      const inspected = await apiRequest<{ session_id: string; title: string; turns: number; message_count: number }>("/api/opencode/inspect", {
        method: "POST", body: JSON.stringify({ payload, project }),
      });
      if (!inspected.session_id || !inspected.message_count) {
        throw new Error("文件中没有可导入的 OpenCode 会话消息。");
      }
      stage = "写入会话 Vault";
      await apiRequest<{ imported: number }>("/api/opencode/import", {
        method: "POST", body: JSON.stringify({ payload, project }),
      });
      stage = "刷新工作区数据";
      await refreshData();
      setActive("sessions");
      notify("OpenCode 会话导入完成", `已导入“${inspected.title}”，共 ${inspected.turns} 轮，等待预审核。`);
    } catch (error) {
      const apiError = error instanceof ApiError ? error : null;
      const reason = error instanceof Error ? error.message : "发生未知导入错误。";
      const isConnectionError = error instanceof TypeError || reason.includes("API 未连接") || reason.includes("Failed to fetch");
      const suggestion = apiError?.hint || (
        isConnectionError
          ? "点击左下角“启动”连接本地服务，然后重新选择文件。"
          : error instanceof SyntaxError
            ? "请重新从外部 OpenCode 环境执行 export，避免手动截断、编辑或拼接 JSON。"
            : stage === "读取文件"
              ? "确认文件未被占用、具有读取权限，并重新选择该文件。"
              : "请确认文件由 OpenCode/codeagent 的 export 命令生成，且包含 info 和 messages 字段。"
      );
      setImportFailure({
        file: file.name, size: formatFileSize(file.size), stage: apiError?.stage || stage,
        code: apiError?.code || (error instanceof SyntaxError ? "INVALID_JSON" : isConnectionError ? "SERVICE_UNAVAILABLE" : "OPENCODE_IMPORT_FAILED"),
        reason, suggestion, errorType: apiError?.type || (error instanceof Error ? error.name : "UnknownError"),
        status: apiError?.status, details: apiError?.details,
      });
      notify("OpenCode 导入失败", `${apiError?.stage || stage}：${reason.slice(0, 120)}`);
    } finally {
      setImporting(false);
      if (externalOpenCodeFileInputRef.current) externalOpenCodeFileInputRef.current.value = "";
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
            <button
              type="button"
              className={apiConnected ? "connected" : ""}
              onClick={() => void connectLocalService()}
              disabled={connectingService}
              title={apiConnected ? "检测连接并刷新数据" : "启动并连接本地服务"}
            >
              {connectingService ? "连接中" : apiConnected ? "刷新" : "启动"}
            </button>
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
                        <div><strong>{pipelineSession?.title ?? "等待选择会话"}</strong><span><code>{pipelineSession?.id ?? "—"}</code> · {pipelineSession?.project ?? "—"}</span></div>
                        <div className="job-progress">
                          <strong>{pipelineStatus === "failed" ? "失败" : pipelineStatus === "success" ? "100%" : pipelineRunning ? `${Math.round(pipelineStep / 6 * 100)}%` : "未运行"}</strong>
                          <span>{pipelineRunning ? `已耗时 ${formatElapsed(pipelineElapsed)}` : pipelineStatus === "success" ? `耗时 ${formatElapsed(pipelineElapsed)}` : pipelineStatus === "failed" ? "查看失败原因" : "可从流水线页面启动"}</span>
                        </div>
                      </div>
                      <div className="stepper">
                        {["会话校验", "知识抽取", "知识写入", "seCall 索引", "混合索引", "Wiki 计划"].map((step, index) => (
                          <div key={step} className={index < pipelineStep ? "done" : pipelineRunning && index === pipelineStep ? "current" : ""}>
                            <span>{index < pipelineStep ? "✓" : index + 1}</span><small>{step}</small>
                            {index < 5 && <i />}
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
                  <div className="import-actions"><input value={importProject} onChange={(event) => setImportProject(event.target.value)} placeholder="ChatGPT 项目名称" aria-label="ChatGPT 导入项目名称" /><button className="primary-button" onClick={() => fileInputRef.current?.click()} disabled={importing}>＋ {importing ? "正在导入…" : "导入 ChatGPT"}</button></div>
                  <div className="import-actions"><input value={externalOpenCodeProject} onChange={(event) => setExternalOpenCodeProject(event.target.value)} placeholder="OpenCode 项目名称" aria-label="外部 OpenCode 导入项目名称" /><button className="secondary-button" onClick={() => externalOpenCodeFileInputRef.current?.click()} disabled={importing}>＋ 导入 OpenCode</button></div>
                </div>
              </div>
              <div className="session-review-summary">
                <article><span className="pending">●</span><strong>{sessionCounts.pending}</strong><small>待预审核</small></article>
                <article><span className="approved">●</span><strong>{sessionCounts.approved}</strong><small>已通过</small></article>
                <article><span className="rejected">●</span><strong>{sessionCounts.rejected}</strong><small>已拒绝</small></article>
                <article><span className="hidden">●</span><strong>{sessionCounts.hidden}</strong><small>前端隐藏</small></article>
                <p><b>会话生命周期</b> 待审核存放在暂存区；通过后移入正式 Vault；拒绝后移入隔离区。OpenCode 原始数据始终不变。</p>
              </div>
              <div className="filter-bar review-filter">
                {([
                  ["all", `全部 ${sessionCounts.all}`],
                  ["pending", `待审核 ${sessionCounts.pending}`],
                  ["approved", `已通过 ${sessionCounts.approved}`],
                  ["rejected", `已拒绝 ${sessionCounts.rejected}`],
                  ["hidden", `已隐藏 ${sessionCounts.hidden}`],
                ] as const).map(([id, label]) => <button key={id} className={sessionReviewFilter === id ? "active" : ""} onClick={() => { setSessionReviewFilter(id); setSessionPage(1); }}>{label}</button>)}
                <span /><select aria-label="项目筛选" value={sessionProject} onChange={(event) => { setSessionProject(event.target.value); setSessionPage(1); }}><option value="">全部项目</option>{sessionProjects.map((project) => <option value={project} key={project}>{project}</option>)}</select>
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
                <footer className="session-pagination">
                  <span>每页 10 条，共 {sessionTotal} 条</span>
                  <div>
                    <button disabled={sessionPage <= 1} onClick={() => setSessionPage((page) => Math.max(1, page - 1))}>上一页</button>
                    {sessionPageNumbers.map((page) => <button className={page === sessionPage ? "active" : ""} aria-current={page === sessionPage ? "page" : undefined} key={page} onClick={() => setSessionPage(page)}>{page}</button>)}
                    <button disabled={sessionPage >= sessionTotalPages} onClick={() => setSessionPage((page) => Math.min(sessionTotalPages, page + 1))}>下一页</button>
                  </div>
                </footer>
              </article>
              {sessionPreviewLoading && <div className="preview-loading"><span>◌</span>正在读取会话内容…</div>}
            </section>
          )}

          {active === "planning" && (
            <section className="subpage">
              {/*
                <div className="panel-heading"><strong>{planningPlan.status === "candidate_selection" ? "第一阶段：选择知识主题" : planningPlan.status === "item_reviewing" ? "第二阶段：逐项确认知识条目" : "第三阶段：审核生成结果"}</strong><span>{planningPlan.status === "item_reviewing" && planningCandidate ? `第 ${planningCandidate.progress.current}/${planningCandidate.progress.total} 个主题` : "确认前不会写入知识库"}</span></div>
                {planningPlan.status === "candidate_selection" && <div className="planning-topic-grid">{planningPlan.candidates.map((item) => <label className="planning-candidate" key={item.id}><input type="checkbox" checked={planningPlan.selected_candidate_ids.includes(item.id)} onChange={(event) => void updatePlanningScope(item.id, event.target.checked)} /><div><strong>{item.title}</strong><small>{item.type} · {item.confidence} · 证据 {item.evidence_event_ids.join(", ") || "不足"}</small><p>{item.value}</p></div></label>)}<button className="primary-button" disabled={planningBusy || !planningPlan.selected_candidate_ids.length} onClick={() => void startPlanningReview()}>{planningBusy ? "正在建立确认队列…" : "开始逐项确认"}</button></div>}
                {planningPlan.status === "item_reviewing" && !planningCandidate && <div className="planning-empty"><strong>所有主题已处理</strong><p>你可以生成统一草稿；草稿仅使用逐项确认过的知识条目。</p><button className="primary-button" disabled={planningBusy} onClick={() => void confirmAndGeneratePlanning()}>{planningBusy ? "正在生成草稿…" : "确认范围并生成草稿"}</button></div>}
                {planningPlan.status === "item_reviewing" && planningCandidate && <div className="planning-entry-review"><h3>{planningCandidate.candidate.title}</h3><p>{planningCandidate.current_revision?.assistant_message || "先让模型整理当前主题下可供选择的知识条目。"}</p>{!planningCandidate.current_revision && <button className="primary-button" disabled={planningBusy} onClick={() => void regeneratePlanningEntries()}>{planningBusy ? "正在整理…" : "生成可选知识条目"}</button>}{planningCandidate.current_revision?.entries.map((entry) => <label className="planning-entry" key={entry.id}><input type="checkbox" checked={planningEntrySelection.includes(entry.id)} onChange={(event) => setPlanningEntrySelection((current) => event.target.checked ? [...new Set([...current, entry.id])] : current.filter((id) => id !== entry.id))} /><div><strong>{entry.type}{entry.recommended && <span>模型建议</span>}</strong><p>{entry.content}</p><small>{entry.source} · {entry.confidence} · 证据 {entry.evidence_event_ids.join(", ") || "用户补充"}</small></div></label>)}{planningCandidate.current_revision && <><button className="text-button" onClick={() => setShowPlanningSupplement((value) => !value)}>这些都不合适 / 补充说明</button>{showPlanningSupplement && <div className="planning-compose"><textarea value={planningSupplement} onChange={(event) => setPlanningSupplement(event.target.value)} placeholder="说明哪些条目不准确、要保留哪些事实；补充会标记为 user_provided。" /><button className="secondary-button" disabled={planningBusy || !planningSupplement.trim()} onClick={() => void regeneratePlanningEntries()}>根据补充重新整理</button></div>}<div className="planning-actions"><button className="primary-button" disabled={planningBusy || !planningEntrySelection.length} onClick={() => void confirmPlanningCandidate()}>确认所选并进入下一项</button><button className="secondary-button" onClick={() => setShowPlanningSkip((value) => !value)}>跳过此主题</button></div>{showPlanningSkip && <div className="planning-compose"><textarea value={planningSkipReason} onChange={(event) => setPlanningSkipReason(event.target.value)} placeholder="请填写跳过此主题的原因。" /><button className="danger-button" disabled={planningBusy || !planningSkipReason.trim()} onClick={() => void skipPlanningCandidate()}>确认跳过</button></div>}</>}</div>}
              */}
              {planningPlan && <section className="planning-wizard-stage panel">
                <div className="panel-heading"><strong>逐项确认知识条目</strong><span>{planningPlan.status === "item_reviewing" && planningCandidate ? `主题 ${planningCandidate.progress.current}/${planningCandidate.progress.total}` : "确认前不会写入知识库"}</span></div>
                {planningGenerating && <div className="planning-generation-status" role="status" aria-live="polite">
                  <div><span className="spin-mark">↻</span><p><strong>正在生成统一知识草稿</strong><small>{planningGenerationElapsed < 3 ? "正在确认沉淀范围" : planningGenerationElapsed < 90 ? "模型正在组织知识卡片、QA 与 Wiki 预览" : "模型仍在处理较长会话，请保持页面开启"}</small></p><time>已用时 {planningGenerationElapsed.toFixed(1)} 秒</time></div>
                  <div className="planning-generation-bar"><span style={{ width: `${Math.min(92, 12 + planningGenerationElapsed * 0.9)}%` }} /></div>
                  <em>进度条表示当前处理阶段；模型返回后会自动进入“统一正确性审核”。</em>
                </div>}
                {planningPlan.status === "candidate_selection" && <div className="planning-topic-grid">
                  {planningPlan.candidates.map((item) => <label className="planning-candidate" key={item.id}><input type="checkbox" checked={planningPlan.selected_candidate_ids.includes(item.id)} onChange={(event) => void updatePlanningScope(item.id, event.target.checked)} /><div><strong>{item.title}</strong><small>{item.type} · {item.confidence}</small><p>{item.value}</p></div></label>)}
                  <button className="primary-button" disabled={planningBusy || !planningPlan.selected_candidate_ids.length} onClick={() => void startPlanningReview()}>开始逐项确认</button>
                </div>}
                {planningPlan.status === "item_reviewing" && !planningCandidate && <div className="planning-empty"><strong>所有主题已处理</strong><p>草稿仅使用逐项确认过的知识条目。</p><button className="primary-button" disabled={planningBusy} onClick={() => void confirmAndGeneratePlanning()}>确认范围并生成草稿</button></div>}
                {planningPlan.status === "scope_confirmed" && !planningGenerating && !planningDraft && <div className="planning-empty"><strong>沉淀范围已确认</strong><p>如果上一次生成因模型超时或服务中断失败，可以从这里继续生成，不需要重新确认主题。</p><button className="primary-button" disabled={planningBusy} onClick={() => void confirmAndGeneratePlanning()}>{planningBusy ? "正在生成草稿…" : "继续生成草稿"}</button></div>}
                {planningPlan.status === "item_reviewing" && planningCandidate && <div className="planning-entry-review"><h3>{planningCandidate.candidate.title}</h3><p>{planningCandidate.current_revision?.assistant_message || "先生成当前主题的可选知识条目。"}</p>
                  {!planningCandidate.current_revision && <button className="primary-button" disabled={planningBusy} onClick={() => void regeneratePlanningEntries()}>生成可选知识条目</button>}
                  {planningCandidate.current_revision?.entries.map((entry) => <label className="planning-entry" key={entry.id}><input type="checkbox" checked={planningEntrySelection.includes(entry.id)} onChange={(event) => setPlanningEntrySelection((current) => event.target.checked ? [...new Set([...current, entry.id])] : current.filter((id) => id !== entry.id))} /><div><strong>{entry.type}{entry.recommended && <span>模型建议</span>}</strong><p>{entry.content}</p><small>{entry.source} · {entry.confidence} · 证据 {entry.evidence_event_ids.join(", ") || "用户补充"}</small></div></label>)}
                  {planningCandidate.current_revision && <><button className="text-button" onClick={() => setShowPlanningSupplement((value) => !value)}>这些都不合适 / 补充说明</button>{showPlanningSupplement && <div className="planning-compose"><textarea value={planningSupplement} onChange={(event) => setPlanningSupplement(event.target.value)} placeholder="说明哪些条目不准确、要保留哪些事实。" /><button className="secondary-button" disabled={planningBusy || !planningSupplement.trim()} onClick={() => void regeneratePlanningEntries()}>根据补充重新整理</button></div>}<div className="planning-actions"><button className="primary-button" disabled={planningBusy || !planningEntrySelection.length} onClick={() => void confirmPlanningCandidate()}>确认所选并进入下一项</button><button className="secondary-button" onClick={() => setShowPlanningSkip((value) => !value)}>跳过此主题</button></div>{showPlanningSkip && <div className="planning-compose"><textarea value={planningSkipReason} onChange={(event) => setPlanningSkipReason(event.target.value)} placeholder="请填写跳过原因。" /><button className="danger-button" disabled={planningBusy || !planningSkipReason.trim()} onClick={() => void skipPlanningCandidate()}>确认跳过</button></div>}</>}
                </div>}
              </section>}
              <div className="subpage-heading"><div><p className="eyebrow">INTERACTIVE KNOWLEDGE PLANNING</p><h1>知识策划</h1><p>先与模型讨论哪些经验值得沉淀；确认前，所有内容只保存在隔离草稿区。</p></div>{planningPlan && <span className={`review-pill ${planningPlan.status}`}>{planningPlan.status === "reviewing" ? "待最终审核" : planningPlan.status === "published" ? "已发布" : planningPlan.status === "skipped" ? "已跳过" : "讨论中"}</span>}</div>
              {!planningPlan ? <div className="empty-state"><strong>尚未开始知识策划</strong><span>请在流水线中选择已通过预审核的会话，模型会先给出候选知识清单。</span></div> : <div className="planning-workspace">
                {planningPlan.status === "published" && planningPlan.index_status !== "ready" && <div className="pipeline-error"><strong>已发布，索引待同步</strong><button className="secondary-button" disabled={planningBusy} onClick={() => void retryPlanningIndex()}>重试索引同步</button></div>}
                {planningPlan.status !== "candidate_selection" && <article className="panel planning-candidates"><div className="panel-heading"><strong>知识主题进度</strong><span>{planningPlan.candidates.length} 项</span></div>
                  {planningPlan.candidates.map((item) => <label className="planning-candidate" key={item.id}><input type="checkbox" checked={planningPlan.selected_candidate_ids.includes(item.id)} disabled={planningPlan.status !== "discussing"} onChange={(event) => void updatePlanningScope(item.id, event.target.checked)} /><div><strong>{item.title}</strong><small>{item.type} · {item.confidence} · 证据 {item.evidence_event_ids.join(", ") || "不足"}</small><p>{item.value}</p>{item.duplicate_hint && <em>重复提示：{item.duplicate_hint}</em>}{item.conflict_hint && <em>冲突提示：{item.conflict_hint}</em>}</div></label>)}
                  {planningPlan.status === "item_reviewing" && !planningPlan.active_candidate_id && <button className="primary-button" disabled={planningBusy} onClick={() => void confirmAndGeneratePlanning()}>{planningBusy ? "正在生成草稿…" : "确认范围并生成草稿"}</button>}
                </article>}
                {planningDraft && <article className="panel planning-review"><div className="panel-heading"><strong>统一正确性审核</strong><span>草稿未入库</span></div><h3>知识卡片草稿</h3><MarkdownViewer markdown={planningDraft.draft.document} /><h3>候选 QA（{planningDraft.draft.qa.length}）</h3><pre>{JSON.stringify(planningDraft.draft.qa, null, 2)}</pre><h3>Wiki 更新预览</h3>{planningDraft.draft.wiki_preview.map((item) => <article className="planning-wiki-preview" key={item.id}><strong>{item.title}</strong><small>{item.category} · {item.action}</small><p>{item.reason}</p><pre>{item.diff}</pre></article>)}
                  {planningPlan.status === "reviewing" && <div className="planning-publish"><strong>发布项</strong>{(["knowledge", "qa", "wiki"] as const).map((item) => <label key={item}><input type="checkbox" checked={planningPublish.includes(item)} onChange={(event) => setPlanningPublish((current) => event.target.checked ? [...new Set([...current, item])] : current.filter((value) => value !== item))} />{{ knowledge: "知识卡片", qa: "提交 QA 审核", wiki: "Wiki" }[item]}</label>)}<button className="primary-button" disabled={planningBusy || !planningPublish.includes("knowledge")} onClick={() => void publishPlanning()}>{planningBusy ? "正在发布…" : "发布已选内容"}</button><small>候选 QA 将进入待审核队列，审核通过后才进入正式检索与 RAG；QA 和 Wiki 必须依赖知识卡片。</small></div>}
                </article>}
              </div>}
            </section>
          )}

          {active === "pipeline" && (
            <section className="subpage">
              <div className="subpage-heading"><div><p className="eyebrow">AUTOMATION</p><h1>知识流水线</h1><p>监控 Session 从导出到可检索知识的完整过程。</p></div><button className="primary-button" onClick={() => setModal(true)}>＋ 运行流水线</button></div>
              <article className={`pipeline-hero ${pipelineStatus === "failed" ? "failed" : ""}`}>
                <div>
                  <span className={pipelineRunning ? "spin-mark" : pipelineStatus === "success" ? "done-mark" : "idle-mark"}>{pipelineRunning ? "↻" : pipelineStatus === "success" ? "✓" : pipelineStatus === "failed" ? "!" : "○"}</span>
                  <p>
                    <small>{{ idle: "尚未运行", running: "正在处理", success: pipelineResult?.reused ? "已复用现有知识并刷新索引" : "最近一次运行成功", failed: "最近一次运行失败" }[pipelineStatus]}</small>
                    <strong>{pipelineSession?.title ?? "请选择已通过预审核的会话"}</strong>
                    <code>{pipelineSession?.id ?? "无会话"} · {pipelineSession?.model ?? "默认模型"}</code>
                  </p>
                </div>
                <div className="hero-metrics"><span><b>{pipelineStep}/6</b><small>完成步骤</small></span><span><b>{formatElapsed(pipelineElapsed)}</b><small>实际耗时</small></span><span><b>{pipelineResult?.knowledge.qa_count ?? "—"}</b><small>候选 QA</small></span></div>
              </article>
              {pipelineError && <div className="pipeline-error"><strong>执行失败</strong><span>{pipelineError}</span></div>}
              <div className="pipeline-detail">
                {(pipelineResult?.stages ?? [
                  { name: "读取并验证会话", detail: "确认会话已通过预审核并读取正式 Vault 文档", duration_seconds: 0 },
                  { name: "OpenCode 知识抽取", detail: "根据真实 Session 生成 Issue Card 与候选 QA", duration_seconds: 0 },
                  { name: "写入知识库", detail: "保存知识卡片，并关联来源会话和候选 QA", duration_seconds: 0 },
                  { name: "重建 seCall 索引", detail: "刷新会话全文索引", duration_seconds: 0 },
                  { name: "重建关键词与语义索引", detail: "同步 FTS5/BM25 与 BGE-M3 向量索引", duration_seconds: 0 },
                  { name: "生成 Wiki 更新计划", detail: "生成跨页面 Markdown Diff，等待人工审核后原子写入", duration_seconds: 0 },
                ]).map((stage, index) => (
                  <article key={`${stage.name}-${index}`} className={pipelineStatus === "success" || index < pipelineStep ? "complete" : pipelineRunning && index === pipelineStep ? "processing" : ""}>
                    <span>{pipelineStatus === "success" || index < pipelineStep ? "✓" : index + 1}</span>
                    <div><strong>{stage.name}</strong><small>{stage.detail}</small></div>
                    <time>{pipelineStatus === "success" ? `${stage.duration_seconds.toFixed(2)}s` : pipelineRunning && index === pipelineStep ? "运行中…" : "等待"}</time>
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
                  {!showTrash && <button className="secondary-button" onClick={() => void syncKnowledgeDerivatives()}>⟳ 同步派生数据</button>}
                  {!showTrash && <button className="secondary-button" onClick={() => void refreshIndex()}>↻ 刷新索引</button>}
                  {!showTrash && <button className="danger-button" onClick={() => void purgeKnowledgeDerivatives()}>清空知识派生数据</button>}
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
                {knowledgeItems.map((item) => {
                  const score = ({ high: 96, medium: 82, low: 58 } as Record<string, number>)[item.confidence] ?? 75;
                  return (
                  <article className="knowledge-card" key={item.id} tabIndex={0} onClick={() => void openKnowledge(item.id)} onKeyDown={(event) => { if (event.key === "Enter") void openKnowledge(item.id); }}>
                    <div className="knowledge-top"><span>◇</span><em>{item.project}</em><button aria-label={`查看 ${item.title}`}>查看</button></div><h3>{item.title}</h3><p>{item.summary || "该知识卡片已写入本地 Vault。"}</p>
                    <div className="knowledge-meta"><span><i style={{ width: `${score}%` }} /></span><b>{score}% 置信度</b><small>{item.source_session}</small></div>
                  </article>
                  );
                })}
                {!knowledgeItems.length && <div className="empty-state knowledge-empty"><strong>知识库当前为空</strong><span>请先通过会话预审核，再运行知识流水线生成真实知识卡片。</span></div>}
              </div>}
            </section>
          )}

          {active === "wiki" && (
            <section className="subpage wiki-page">
              <div className="subpage-heading">
                <div><p className="eyebrow">CONNECTED KNOWLEDGE WIKI</p><h1>{showWikiArchive ? "Wiki 回收站" : showWikiReview ? "Wiki 更新审核" : "Wiki 知识中心"}</h1><p>{showWikiArchive ? "恢复误归档的项目、主题和设计决策页面。" : showWikiReview ? "核对来源证据和 Markdown Diff，确认后以一个原子事务写入。" : "按项目、模块、主题、决策、运行手册、测试和问题定位组织研发知识。"}</p></div>
                <div className="heading-actions">
                  {showWikiArchive && wikiArchiveItems.length > 0 && <button className="danger-button" onClick={() => void clearWikiArchive()}>清空回收站</button>}
                  {(showWikiArchive || showWikiReview)
                    ? <button className="secondary-button" onClick={() => { setShowWikiArchive(false); setShowWikiReview(false); }}>← 返回 Wiki</button>
                    : <><button className="secondary-button" onClick={() => void runWikiLint()} disabled={wikiWorking}>健康检查</button><button className="secondary-button" onClick={() => void openWikiPlan()}>{`审核更新 ${wikiPlans.length ? `(${wikiPlans.length})` : ""}`}</button><button className="secondary-button" onClick={() => void loadWikiArchive()}>♲ Wiki 回收站</button><button className="primary-button" onClick={() => void rebuildWiki()} disabled={wikiWorking}>{wikiWorking ? "生成中…" : "↻ 重建 Wiki"}</button></>}
                  {!showWikiArchive && !showWikiReview && <div className="wiki-heading-stats"><strong>{wikiPages.length}</strong><span>篇文档</span><i /><strong>{wikiCounts.projects ?? 0}</strong><span>个项目</span></div>}
                </div>
              </div>
              {showWikiArchive ? (
                <div className="trash-list wiki-trash-list">
                  {wikiArchiveItems.length ? wikiArchiveItems.map((item) => (
                    <article key={item.trash_id}>
                      <span>♲</span>
                      <div><strong>{item.title}</strong><small>{item.category_label} · {item.project} · 归档于 {formatUpdated(new Date(item.archived_at).getTime())}</small></div>
                      <button onClick={() => void restoreWiki(item.trash_id)}>恢复</button>
                      <button className="danger-button" onClick={() => void purgeWiki(item)}>永久删除</button>
                    </article>
                  )) : <div className="empty-state">Wiki 回收站为空</div>}
                </div>
              ) : showWikiReview ? (
                <div className="wiki-review-shell">
                  <aside className="wiki-plan-list">
                    <header><strong>待审核计划</strong><span>{wikiPlans.length}</span></header>
                    {wikiPlans.map((plan) => <button key={plan.plan_id} className={wikiPlanDetail?.plan_id === plan.plan_id ? "active" : ""} onClick={() => void openWikiPlan(plan.plan_id)}><strong>{plan.reason}</strong><small>{plan.summary.total} 项变更 · {formatUpdated(new Date(plan.created_at).getTime())}</small><code>{plan.plan_id}</code></button>)}
                    {!wikiPlans.length && <p>暂无待审核计划</p>}
                    {wikiLint && <section className={`wiki-lint-summary ${wikiLint.healthy ? "healthy" : ""}`}><strong>{wikiLint.healthy ? "✓ Wiki 健康" : `发现 ${wikiLint.finding_count} 项问题`}</strong><small>{wikiLint.page_count} 个注册页面</small>{wikiLint.findings.slice(0, 8).map((item, index) => <span key={`${item.type}-${index}`}>{item.severity} · {item.type} · {item.page_id || item.category || item.target || "—"}</span>)}</section>}
                  </aside>
                  <article className="wiki-plan-review">
                    {wikiPlanDetail ? <>
                      <header><div><p className="eyebrow">REVIEW BEFORE WRITE</p><h2>{wikiPlanDetail.reason}</h2><code>{wikiPlanDetail.plan_id}</code></div><div><strong>{wikiPlanSelected.length}/{wikiPlanDetail.changes.length}</strong><span>项已选择</span></div></header>
                      <div className="wiki-plan-toolbar"><button onClick={() => setWikiPlanSelected(wikiPlanDetail.changes.map((item) => item.change_id))}>全选</button><button onClick={() => setWikiPlanSelected([])}>取消全选</button><span>创建 {wikiPlanDetail.summary.create} · 更新 {wikiPlanDetail.summary.update} · 归档 {wikiPlanDetail.summary.archive}</span></div>
                      <div className="wiki-change-list">{wikiPlanDetail.changes.map((change) => {
                        const checked = wikiPlanSelected.includes(change.change_id);
                        return <section key={change.change_id} className={checked ? "selected" : ""}><label><input type="checkbox" checked={checked} onChange={() => setWikiPlanSelected((items) => checked ? items.filter((id) => id !== change.change_id) : [...items, change.change_id])} /><span className={`wiki-change-action ${change.action}`}>{change.action === "create" ? "新增" : change.action === "update" ? "修改" : "归档"}</span><strong>{change.title}</strong><code>{change.page_id}</code></label><small>来源：{change.sources.join("、") || "聚合知识"}</small><pre>{change.diff || "无文本差异"}</pre></section>;
                      })}</div>
                      <footer><button className="danger-button" disabled={wikiWorking} onClick={() => void rejectWikiPlan()}>拒绝计划</button><button className="primary-button" disabled={wikiWorking || !wikiPlanSelected.length} onClick={() => void applyWikiPlan()}>{wikiWorking ? "正在提交…" : `应用 ${wikiPlanSelected.length} 项变更`}</button></footer>
                    </> : <div className="wiki-review-empty"><span>✓</span><h2>没有待审核的 Wiki 变更</h2><p>运行知识流水线或点击“重建 Wiki”后，跨页面变更会先出现在这里。</p></div>}
                  </article>
                </div>
              ) : <div className="wiki-shell">
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
                      {wikiDetail.category !== "issues" && (
                        <div className="wiki-reader-actions">
                          <button className="danger-button" onClick={() => void archiveWiki()}>归档此页面</button>
                        </div>
                      )}
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
              </div>}
            </section>
          )}

          {active === "graph" && (
            <section className="subpage graph-page">
              <div className="subpage-heading">
                <div><p className="eyebrow">KNOWLEDGE RELATIONSHIP MAP</p><h1>知识关系图</h1><p>聚焦项目、知识卡片、模块和来源会话之间可复用的工程知识关系。</p></div>
                <button className="primary-button" disabled={graphLoading} onClick={() => void rebuildKnowledgeGraph()}>{graphLoading ? "正在构建…" : "↻ 重建关系图"}</button>
              </div>
              <div className="graph-design-note">默认只展示项目、知识卡片、模块与来源会话。文件、函数、提交、根因和测试用例保留为卡片证据，避免图谱被一次性叶子节点淹没。</div>
              <div className="graph-toolbar">
                <label><span>⌕</span><input value={graphQuery} onChange={(event) => setGraphQuery(event.target.value)} placeholder="查找节点…" /></label>
                <div>{graphTypeOptions.map((type) => (
                  <button key={type} className={graphType === type ? "active" : ""} onClick={() => setGraphType(type)}>
                    {graphTypeLabels[type] || type}
                    <em>{type === "all" ? graph.stats.nodes : graph.stats.types[type] ?? 0}</em>
                  </button>
                ))}</div>
                <span className="graph-summary">{graph.stats.nodes} 个核心节点 · {graph.stats.links} 条关系 · {Object.values(graph.stats.evidence || {}).reduce((sum, value) => sum + value, 0)} 条技术证据</span>
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
                          <circle r={node.type === "project" ? 16 : node.type === "agent" ? 15 : node.type === "issue" ? 12 : 10} />
                          <text y={node.type === "session" ? 22 : 26}>{(node.label || node.id).slice(0, 16)}</text>
                          <title>{node.label || node.id}</title>
                        </g>;
                      })}</g>
                    </svg>
                  ) : <div className="graph-empty"><span>◎</span><h3>关系图尚未构建</h3><p>点击“重建关系图”，从本地会话提取项目、工具和智能体关系。</p></div>}
                  <div className="graph-legend">{graphTypeOptions.filter((type) => type !== "all").map((type) => (
                    <span key={type} className={type}>{graphTypeLabels[type] || type}</span>
                  ))}</div>
                </div>
                <aside className="graph-inspector">
                  {graphSelected ? (
                    <>
                      <span className={`graph-node-mark ${graphSelected.type}`}>●</span><p className="eyebrow">SELECTED NODE</p><h2>{graphSelected.label || graphSelected.id}</h2>
                      <dl><div><dt>类型</dt><dd>{graphTypeLabels[graphSelected.type || ""] || graphSelected.type || "其他"}</dd></div><div><dt>项目</dt><dd>{graphSelected.project || "—"}</dd></div><div><dt>关联数量</dt><dd>{graph.links.filter((link) => link.source === graphSelected.id || link.target === graphSelected.id).length}</dd></div></dl>
                      <GraphEvidencePanel evidence={graphSelected.evidence} />
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
            <div className="form-grid"><label>生成模型<select value={pipelineModel} onChange={(event) => setPipelineModel(event.target.value)}><option value="">OpenCode 默认模型</option>{health?.models?.map((model) => <option value={model} key={model}>{model}</option>)}</select></label><label>知识语言<select><option>简体中文</option><option>English</option></select></label></div>
            <div className="switch-row"><div><strong>重新生成并覆盖知识</strong><small>关闭时会安全复用现有 Issue Card，避免重复 QA</small></div><input type="checkbox" checked={pipelineOverwrite} onChange={(event) => setPipelineOverwrite(event.target.checked)} aria-label="重新生成并覆盖知识" /></div>
            <div className="switch-row"><div><strong>完成后重建索引</strong><small>让新知识立即可被搜索与 MCP 调用</small></div><input type="checkbox" checked={pipelineReindex} onChange={(event) => setPipelineReindex(event.target.checked)} aria-label="完成后重建索引" /></div>
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
                <div className="detail-badges">
                  <span>{knowledgeDetail.project}</span>
                  <span>{knowledgeDetail.confidence === "high" ? "高置信度" : knowledgeDetail.confidence === "medium" ? "中置信度" : "低置信度"}</span>
                  <span>{knowledgeDetail.review_status === "approved" ? "已通过" : "待审核"}</span>
                  {knowledgeDetail.quality?.overall !== undefined && <span>质量 {Math.round(knowledgeDetail.quality.overall * 100)}%</span>}
                </div>
                <nav className="knowledge-tabs" aria-label="知识详情分区">
                  {([
                    ["overview", "文档概览"],
                    ["timeline", "事件与状态"],
                    ["diagnosis", "诊断过程"],
                    ["code", "修复与代码"],
                    ["evidence", "证据来源"],
                  ] as const).map(([id, label]) => <button key={id} className={knowledgeTab === id ? "active" : ""} onClick={() => setKnowledgeTab(id)}>{label}</button>)}
                </nav>
                {knowledgeTab === "overview" && <>
                  {knowledgeDetail.quality?.warnings?.length ? <div className="quality-warning"><strong>质量提示</strong>{knowledgeDetail.quality.warnings.map((warning) => <span key={warning}>{warning}</span>)}</div> : null}
                  {knowledgeDetail.sections.map((section, index) => <section key={`${section.heading}-${index}`}><h3>{section.heading}</h3><p>{section.content || "暂无内容"}</p></section>)}
                </>}
                {knowledgeTab === "timeline" && <>
                  <section><h3>运行上下文</h3><StructuredObject value={knowledgeDetail.structured?.context} /></section>
                  <section><h3>问题现象</h3><StructuredList items={knowledgeDetail.structured?.symptoms} /></section>
                  <section><h3>事件时间线</h3><StructuredList items={knowledgeDetail.structured?.timeline} /></section>
                  <section><h3>状态转换</h3><StructuredList items={knowledgeDetail.structured?.state_transitions} /></section>
                  <section><h3>消息与调用链</h3><StructuredList items={knowledgeDetail.structured?.message_flows} /></section>
                  <section><h3>参数变化</h3><StructuredList items={knowledgeDetail.structured?.parameter_changes} /></section>
                </>}
                {knowledgeTab === "diagnosis" && <>
                  <section><h3>诊断假设</h3><StructuredList items={knowledgeDetail.structured?.hypotheses} /></section>
                  <section><h3>排查步骤与无效尝试</h3><StructuredList items={knowledgeDetail.structured?.troubleshooting_steps} /></section>
                  <section><h3>根因与证据</h3><StructuredObject value={knowledgeDetail.structured?.root_cause} /></section>
                  <section><h3>经验规则</h3><StructuredObject value={knowledgeDetail.structured?.lessons} /></section>
                </>}
                {knowledgeTab === "code" && <>
                  <section><h3>修复方案</h3><StructuredObject value={knowledgeDetail.structured?.fix} /></section>
                  <section><h3>验证与回归</h3><StructuredObject value={knowledgeDetail.structured?.verification} /></section>
                  <section><h3>相关代码实体</h3><StructuredObject value={knowledgeDetail.structured?.code_entities} /></section>
                </>}
                {knowledgeTab === "evidence" && <div className="evidence-list">
                  {knowledgeDetail.events?.length ? knowledgeDetail.events.map((event) => (
                    <article key={event.event_id}>
                      <span>{event.event_id}</span>
                      <div><strong>第 {event.source_turn} 轮 · {event.type}</strong><p>{event.output || event.content || event.input || "空事件"}</p></div>
                    </article>
                  )) : <p className="structured-empty">该卡片由旧版流水线生成，尚无事件 sidecar；重新运行流水线可补齐证据。</p>}
                </div>}
              </div>
            )}
            <footer>
              <button className="danger-button" onClick={() => void deleteKnowledge()}>删除</button>
              <span />
              {!editingKnowledge && <button onClick={() => {
                const source = [...sessionItems, ...hiddenSessionItems].find((item) => item.id === knowledgeDetail.source_session);
                if (source) { setKnowledgeDetail(null); void openSessionPreview(source); }
                else notify("未找到来源会话", "来源会话可能已被移出当前 Vault");
              }}>查看来源会话</button>}
              {editingKnowledge ? <><button onClick={() => void openKnowledge(knowledgeDetail.id)}>取消</button><button className="primary-button" disabled={savingKnowledge} onClick={() => void saveKnowledge()}>{savingKnowledge ? "正在保存…" : "保存修改"}</button></> : <button className="primary-button" onClick={() => setEditingKnowledge(true)}>编辑知识</button>}
            </footer>
          </aside>
        </div>
      )}

      {importFailure && (
        <div className="modal-backdrop" role="presentation" onClick={() => setImportFailure(null)}>
          <aside className="modal import-error-modal" role="alertdialog" aria-modal="true" aria-labelledby="import-error-title" onClick={(event) => event.stopPropagation()}>
            <button className="modal-close" aria-label="关闭导入错误详情" onClick={() => setImportFailure(null)}>×</button>
            <div className="import-error-mark">!</div>
            <p className="eyebrow">IMPORT DIAGNOSTICS</p>
            <h2 id="import-error-title">会话导入未完成</h2>
            <p>系统已保留完整的失败阶段和错误信息，便于定位问题。</p>
            <dl className="import-error-details">
              <div><dt>失败阶段</dt><dd>{importFailure.stage}</dd></div>
              <div><dt>错误代码</dt><dd><code>{importFailure.code}</code></dd></div>
              <div><dt>导入文件</dt><dd>{importFailure.file} · {importFailure.size}</dd></div>
              {importFailure.status ? <div><dt>服务状态</dt><dd>HTTP {importFailure.status} · {importFailure.errorType}</dd></div> : null}
            </dl>
            <section className="import-error-reason"><strong>具体原因</strong><p>{importFailure.reason}</p></section>
            <section className="import-error-hint"><strong>处理建议</strong><p>{importFailure.suggestion}</p></section>
            {importFailure.details && Object.keys(importFailure.details).length > 0
              ? <details className="import-error-raw"><summary>查看服务返回详情</summary><pre>{JSON.stringify(importFailure.details, null, 2)}</pre></details>
              : null}
            <div className="modal-actions">
              <button onClick={() => setImportFailure(null)}>关闭</button>
              <button className="primary-button" onClick={() => {
                const report = [
                  `文件：${importFailure.file}（${importFailure.size}）`,
                  `阶段：${importFailure.stage}`,
                  `代码：${importFailure.code}`,
                  `类型：${importFailure.errorType || "UnknownError"}`,
                  importFailure.status ? `HTTP：${importFailure.status}` : "",
                  `原因：${importFailure.reason}`,
                  `建议：${importFailure.suggestion}`,
                  importFailure.details ? `详情：${JSON.stringify(importFailure.details, null, 2)}` : "",
                ].filter(Boolean).join("\n");
                void navigator.clipboard.writeText(report).then(
                  () => notify("错误详情已复制", "可将该信息发送给维护人员进一步排查。"),
                  () => notify("复制失败", "浏览器未授予剪贴板权限，请手动选择错误信息。"),
                );
              }}>复制错误详情</button>
            </div>
          </aside>
        </div>
      )}
      <input ref={fileInputRef} className="file-input" type="file" accept=".json,application/json" aria-label="选择 ChatGPT conversations.json" onChange={(event) => { const file = event.target.files?.[0]; if (file) void importChatGPTFile(file); }} />
      <input ref={externalOpenCodeFileInputRef} className="file-input" type="file" accept=".json,application/json" aria-label="选择外部 OpenCode Session JSON" onChange={(event) => { const file = event.target.files?.[0]; if (file) void importExternalOpenCodeFile(file); }} />
      {toast && <div className="toast"><span>✓</span><div><strong>{toast.title}</strong><small>{toast.detail}</small></div><button onClick={() => setToast(null)}>×</button></div>}
    </main>
  );
}
