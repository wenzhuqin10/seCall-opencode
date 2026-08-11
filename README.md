# seCall OpenCode Adapter

将 OpenCode 与 ChatGPT Session 转换为 seCall 可索引的 Markdown，并通过本机
OpenCode 模型生成中文 Issue Card 与候选 QA。框架不要求独立的 LLM API。

## 一键启动本地前后端

首次安装后执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start-local.ps1
```

浏览器会打开 `http://localhost:3000`。本地 API 仅监听
`127.0.0.1:8765`，不会向局域网开放。

首次运行该脚本会注册 `secall-opencode://` 本地启动协议。此后前端左下角
“本地服务”卡片提供一键启动/重新连接按钮；后端意外停止时，页面也会每 5 秒
自动检测并恢复连接。该协议只执行本仓库的 `scripts/connect-local.ps1`，且服务仍
仅监听本机地址。

停止服务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\stop-local.ps1
```

在“研发会话”页面输入项目名称并选择 ChatGPT 官方导出的
`conversations.json`，即可预览并导入所有有效会话。

## 工作流程

```text
OpenCode Session
  → 本地导出
  → seCall Session Markdown
  → 可追溯 Event 事件流
  → OpenCode/GLM 结构化 SessionKnowledge
  → Issue Card + Runbook + QA JSONL
  → 质量评分与代码实体关联
  → Wiki 更新规划与 Markdown Diff
  → 前端审核后原子更新多张 Wiki 页面
  → seCall/BGE-M3 索引、变更日志、关系图与健康检查
```

ChatGPT 导入流程：

```text
ChatGPT conversations.json
  → 恢复 current_node 对应的有效对话分支
  → 统一 Session 事件格式
  → seCall Session Markdown
  → OpenCode 模型生成 Issue Card / QA
  → 人工审核与索引
```

原始 Session 与生成知识分别写入：

```text
<vault>/staging/sessions/YYYY-MM-DD/   # 自动同步、等待预审核
<vault>/raw/.sessions/YYYY-MM-DD/      # 预审核通过、正式 Vault
<vault>/staging/rejected/YYYY-MM-DD/   # 预审核拒绝、隔离保留
<vault>/wiki/issues/
<vault>/knowledge/qa/candidates.jsonl
<vault>/knowledge/events/{session-id}.json       # 确定性事件 sidecar
<vault>/knowledge/structured/{session-id}.json  # 结构化运行知识与质量评分
<vault>/knowledge/wiki-plans/{plan-id}.json     # 待审核/已应用 Wiki 更新计划
<vault>/wiki/.meta/page-registry.json           # 稳定页面 ID 与内容版本
<vault>/wiki/.meta/source-dependencies.json     # Session 到 Wiki 的来源依赖
```

## 安装

要求 Python 3.9+，并确保 `opencode` 与 `secall` 可在本机运行。

```powershell
python -m pip install -e . --no-build-isolation
secall-opencode init --vault "C:\Users\你的用户名\Documents\seCallVault"
secall-opencode doctor
```

若 seCall 不在 PATH 中：

```powershell
secall-opencode init `
  --vault "C:\Users\你的用户名\Documents\seCallVault" `
  --secall-command "C:\path\to\secall.exe" `
  --force
```

模型名称必须以 `opencode models` 的实际输出为准。若 OpenCode 已配置
GLM-5.1，可在初始化时加入 `--model <provider>/glm-5.1`，也可以在
`generate` 或 `pipeline` 命令中临时传入 `--model`。适配器不会直接调用
任何模型 API。

## 使用

查看 OpenCode Session：

```powershell
secall-opencode sessions list
```

检查与导入 ChatGPT 导出：

```powershell
secall-opencode --json chatgpt inspect conversations.json
secall-opencode --json chatgpt import conversations.json --project my-project --dry-run
secall-opencode --json chatgpt import conversations.json --project my-project
```

仅启动本地 API：

```powershell
secall-opencode serve
```

本地工作台支持：

- 统一搜索会话、知识卡片和审核通过的 QA；
- 只读会话内容预览、辅助质量信号、预审核和低质会话拒绝；
- 研发会话采用服务端分页，每页 10 条；审核状态与项目筛选后重新统计总数，隐藏会话不会占用当前页名额；
- 不删除 OpenCode 原始数据的前端隐藏与恢复；
- OpenCode 会话后台增量监听、稳定窗口和手动立即同步；
- FTS5/BM25 关键词检索与中文字符二元组匹配；
- 知识卡片详情、结构化修改、软删除和回收站恢复；
- 知识写操作后自动同步 Wiki 卡片索引、关系图、关键词索引和向量索引；
- 删除知识卡片时同时移出候选与已审核 QA，并兼容旧版截断 Session ID；
- 持续演化 Wiki，按总览、项目、模块、主题、Issue、决策、运行手册和测试分类浏览；
- 所有模型生成的跨页面变更先展示来源证据和 Markdown Diff，再由用户逐项审核并原子应用；
- Wiki 页面注册表、来源依赖、处理缓存、知识目录和追加式变更日志均可由 Markdown 重建；
- Wiki 健康检查可识别失效来源、孤立页、断链、重复主题、低证据覆盖和缺失聚合页；
- 项目、主题和决策 Wiki 支持软归档、冲突安全恢复、二次确认永久删除和清空回收站；
- Wiki 总览也可归档且不会被同步任务自动重建；问题定位页仍由知识卡片统一管理；
- 关系图采用“核心实体 + 证据属性”两层模型：项目、知识卡片、模块、来源会话和 Wiki 页面作为节点；文件、函数、提交、根因与测试用例保留在知识卡片节点的证据面板，不再生成大量一次性叶子节点；
- 知识库提供“清空知识派生数据”操作：输入固定确认语句后永久清除知识卡片及回收站、Wiki、QA、结构化知识、关系图和知识检索索引，同时保留正式、待审核和拒绝的原始 Session；
- 知识卡片、来源会话、项目、工具与智能体的可交互知识关系图；
- 事件时间线、状态转换、诊断假设、无效尝试、根因证据和修复验证视图；
- Issue 与模块、文件、函数、Commit、根因和测试用例的双向关联；
- BGE-M3 ONNX 本地语义检索与 BM25 混合召回；
- 带 `[S1]` 来源引用的 OpenCode RAG 知识问答；
- `keyword`、`semantic`、`hybrid` 三种稳定搜索接口。

搜索接口示例：

```text
GET /api/search?q=断点续传&scope=all&mode=keyword&limit=20
```

可选筛选参数包括 `project`、`module`、`confidence`、`review_status` 和
`knowledge_type`，例如：

```text
GET /api/search?q=timeout&scope=knowledge&mode=hybrid&module=Scheduler&confidence=high
```

安装本地语义检索依赖：

```powershell
python -m pip install -e ".[semantic]"
```

在配置文件的 `semantic` 节中启用 BGE-M3：

```json
{
  "semantic": {
    "backend": "onnx",
    "model_dir": "D:/Models/bge-m3",
    "batch_size": 16,
    "chunk_size": 600,
    "chunk_overlap": 80
  }
}
```

运行 `secall-opencode index` 会同步建立关键词索引和 BGE-M3 向量索引。
Wiki、知识卡片与已审核 QA 使用 1024 维本地向量；原始 Session 继续使用
seCall/BM25，以避免大型工具输出导致首次索引耗时过长。`hybrid` 模式会融合
两类召回结果。

关键词索引对标题、诊断字段和代码实体分别加权；向量索引会同时消费结构化
根因、排查步骤、修复验证和代码关联信息。旧版知识卡片不会被修改，启动本地
API 时会为缺少 sidecar 的旧卡片生成低置信度兼容结构化记录。

固定检索测试集可以使用以下格式：

```json
[
  {
    "id": "harq-timeout",
    "question": "HARQ timeout 如何定位？",
    "expected_ids": ["wireless-baseband-ses_test_001"],
    "scope": "knowledge",
    "mode": "hybrid",
    "limit": 5
  }
]
```

运行 Benchmark：

```powershell
secall-opencode --json benchmark benchmark.json --mode hybrid --limit 5
```

输出包含 Hit@K、MRR、平均检索耗时、每条用例排名和实际检索模式。

Wiki 与关系图接口：

```text
GET  /api/wiki
GET  /api/wiki/{category}/{slug}
GET  /api/wiki/config
PUT  /api/wiki/config
POST /api/wiki/rebuild
GET  /api/wiki/plans?status=pending
GET  /api/wiki/plans/{plan_id}
POST /api/wiki/plans/{plan_id}/apply
POST /api/wiki/plans/{plan_id}/reject
POST /api/wiki/lint
GET  /api/wiki/lint/latest
GET  /api/graph
POST /api/graph/rebuild
```

会话审核与前端隐藏接口：

```text
POST   /api/sessions/{id}/review
GET    /api/sessions/{id}
DELETE /api/sessions/{id}
GET    /api/sessions/hidden
POST   /api/sessions/{id}/restore
```

会话必须通过预审核后才能运行知识流水线。被拒绝或隐藏的会话不会出现在
工作台检索与 RAG 会话召回中；这些操作不会删除 OpenCode 数据库或 Vault 中的
原始 Session Markdown。

流水线页面展示真实执行数据：运行耗时由前端实时计时并由后端结果校准，
候选 QA 数量来自当前来源会话，各阶段展示后端返回的实际耗时和执行说明。
对已经生成过 Issue Card 的会话，默认复用现有知识并刷新索引，避免重复 QA；
只有显式开启“重新生成并覆盖知识”时才会再次调用 OpenCode。

本地 API 启动后每 10 秒只读检查 OpenCode 会话更新时间。新增或发生变化的
会话在停止更新 20 秒后自动同步到暂存区；已通过会话再次发生变化时会退回
暂存区重新审核。可通过以下接口查看状态或立即同步：

```text
GET  /api/sync/status
POST /api/sync/now
```

RAG 问答接口：

```text
POST /api/rag/query
{
  "question": "ChatGPT 会话导入后为什么没有生成知识？",
  "scope": "all",
  "mode": "hybrid",
  "limit": 6
}
```

接口会先在本地检索证据，再通过已配置的 OpenCode 模型生成带来源编号的回答。
检索不到证据时不会调用生成模型。

执行完整流水线：

```powershell
secall-opencode pipeline --session <session-id>
```

分步执行：

```powershell
secall-opencode sessions export <session-id> --output session.json
secall-opencode convert session.json
secall-opencode generate <生成的-session.md>
secall-opencode index
```

仅预览，不写入文件或调用模型：

```powershell
secall-opencode pipeline --session <session-id> --dry-run
secall-opencode convert session.json --dry-run
secall-opencode generate session.md --dry-run
secall-opencode index --dry-run
```

机器可读输出：

```powershell
secall-opencode --json sessions list
secall-opencode --json pipeline --session <session-id>
```

读取 OpenCode 数据库仅开放只读 SQL：

```powershell
secall-opencode --json raw db "SELECT id, title FROM session ORDER BY time_updated DESC LIMIT 10"
```

## 安全与质量控制

- 默认保留 Session 正文，因为 OpenCode 的 `--sanitize` 会隐藏正文和工具结果；
  使用 `--sanitize` 的输出只适合分享或验证转换，不适合生成知识。
- 原始 Session 只写入本地 Vault；调用模型时仍遵循 OpenCode 自己的
  provider 与数据策略。
- 数据库查询只允许 `SELECT` 和 `PRAGMA`。
- 本地 API 默认仅绑定 `127.0.0.1`，并限制浏览器来源。
- ChatGPT 文件由浏览器读取后直接发送到本机 API，不经过云端站点。
- 解析 ChatGPT 分支时以 `current_node` 为准，避免把废弃回答分支混入知识库。
- 知识抽取提示词要求仅使用 Session 中的证据。
- 所有 QA 初始状态均为 `pending`，需人工审核后再用于正式知识库。
- 转换具有幂等性；内容冲突时必须显式使用 `--overwrite`。

架构和数据契约见 [docs/architecture.md](docs/architecture.md)。
