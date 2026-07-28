# 架构与数据契约

## 组件

```text
┌─────────────────────────────────────────────────┐
│ OpenCode + GLM                                  │
│ Session 存储 / JSON 导出 / 已配置模型执行        │
└───────────────────────┬─────────────────────────┘
                        │ JSON
┌───────────────────────▼─────────────────────────┐
│ seCall OpenCode Adapter                         │
│ 1. OpenCode 发现 / ChatGPT 文件导入             │
│ 2. 标准化与 Markdown 转换                       │
│ 3. Issue Card / QA 输出校验                     │
│ 4. 本地 HTTP API / 流水线编排与诊断             │
└───────────────────────┬─────────────────────────┘
                        │ Vault
┌───────────────────────▼─────────────────────────┐
│ seCall                                          │
│ SQLite/FTS5 / Wiki / Web UI / MCP / 知识图谱    │
└─────────────────────────────────────────────────┘
```

适配器不直接访问 GLM API。生成阶段通过 `opencode run --format json`
复用 OpenCode 已配置的模型、认证和本地环境。

本地页面通过 Vite 将 `/api` 代理到 `127.0.0.1:8765`。API 只绑定
回环地址，负责 ChatGPT 导入、Session 列表、流水线运行、QA 审核与索引。

ChatGPT 官方导出的对话是带分支的树结构。适配器从 `current_node`
沿父节点回溯，仅恢复当前有效分支，再映射为统一的 user/assistant
消息序列；不会导入用户已经放弃的回答分支。

## 输入契约

兼容 `opencode export <session-id>` 的对象。可选择 `--sanitize`，但 OpenCode
会隐藏正文和工具结果，因此脱敏导出不适合生成知识：

```json
{
  "info": {
    "id": "ses_example",
    "title": "修复调度器问题",
    "directory": "D:/workspace/project",
    "time": {"created": 1785000000000, "updated": 1785000100000}
  },
  "messages": [
    {
      "info": {"role": "user"},
      "parts": [{"type": "text", "text": "问题描述"}]
    }
  ]
}
```

转换器保留文本、工具调用、工具状态与结果，其他结构以 JSON 代码块保留，
避免在格式转换时丢失证据。

## seCall Markdown 契约

```markdown
---
title: "修复调度器问题"
type: session
source: opencode
session_id: "ses_example"
project: "project"
created: "2026-07-28T00:00:00+00:00"
---

# 修复调度器问题

## 会话信息
...

## 对话记录
...
```

## 生成知识

GLM 输出由两类标记分隔：

```text
<!-- ISSUE_CARD_START -->
Markdown Issue Card
<!-- ISSUE_CARD_END -->
<!-- QA_JSON_START -->
[{"question":"...", "answer":"...", "evidence":["..."]}]
<!-- QA_JSON_END -->
```

解析通过后：

- Issue Card 写入 `wiki/issues/<session-id>.md`；
- QA 规范化为 JSONL，补充稳定 ID、来源、时间和 `pending` 状态；
- 相同 QA ID 不重复写入；
- 缺少来源证据的内容仍保留为候选项，不自动发布。

## 失败边界

- Session 不存在：停止，不生成空文档。
- OpenCode 或 seCall 不可运行：`doctor` 返回明确诊断。
- 目标文件已存在且内容不同：停止，需显式覆盖。
- 模型输出缺少标记或 JSON 非法：停止，不写入半成品。
- seCall 索引失败：保留已生成文件并返回失败，便于修复后重试。
