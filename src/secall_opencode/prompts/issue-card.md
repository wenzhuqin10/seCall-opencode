# OpenCode Session 结构化知识抽取规则

分析附带的 seCall Session Markdown，生成一份可追溯、可审核的中文
SessionKnowledge、Issue Card 和候选 QA。

## 事实与证据约束

1. 只能使用 Session 中出现的事实，不得依据常识补全。
2. 保留代码、命令、路径、错误信息、产品名和标识符原文。
3. 每个重要结论应引用事件编号。事件按 Session 内容出现顺序从
   `evt-0001` 开始编号：每段对话文本是一个事件，每个工具调用是一个事件。
4. 若无法确定事件编号，`evidence_event_ids` 使用空数组，不得伪造编号。
5. 没有明确问题、根因或验证结论时必须填写空值或“证据不足”。
6. 假设状态只能是 `confirmed`、`suspected` 或 `excluded`。

## SessionKnowledge 要求

先输出 `SESSION_KNOWLEDGE_JSON`，必须是有效 JSON 对象，包含：

- `context`：版本、分支、commit、硬件、配置、测试用例、协议和复现情况；
- `symptoms`：异常类型、组件、消息、影响及证据事件；
- `timeline`：关键事件、是否异常、时间间隔及证据；
- `state_transitions`：组件、前态、触发、预期态、实际态及证据；
- `message_flows`：发送方、接收方、消息、transaction_id、结果及证据；
- `parameter_changes`：参数、前值、当前值、预期范围、是否异常及证据；
- `hypotheses`：结论、状态、原因及证据；
- `troubleshooting_steps`：操作、命令、结果、是否有效、结论及证据；
- `root_cause`：结论、置信度和证据；
- `fix`：临时规避、正式修复、文件、函数和 commit；
- `verification`：测试用例、结果、回归情况和副作用；
- `lessons`：诊断规则、Runbook 步骤和预防措施；
- `code_entities`：`modules`、`files`、`functions`、`commits` 数组；
- `candidate_qa`：候选问答。

没有证据的数组使用 `[]`，对象字段使用空字符串，不要省略顶层字段。

## Issue Card 要求

frontmatter 必须包含：

- `title`
- `type: issue`
- `source_session`
- `project`
- `confidence: high | medium | low`
- `review_status: pending`

正文使用以下结构：

- 问题现象
- 运行上下文
- 事件时间线
- 状态与消息链
- 定位过程
- 已排除假设与无效尝试
- 根因分析
- 修复方案
- 代码变更
- 验证方法
- 经验总结
- 相关代码与文档

生成 3～10 条高价值候选 QA，每条包括：

- `question`
- `answer`
- `qa_type`
- `evidence`
- `evidence_event_ids`
- `related_files`
- `related_functions`
- `confidence`
- `review_status: pending`

输出必须完全遵循以下标记。不要输出标记以外的解释：

```text
<!-- SECALL_DOCUMENT_START -->
<!-- SESSION_KNOWLEDGE_JSON_START -->
{
  "context": {},
  "symptoms": [],
  "timeline": [],
  "state_transitions": [],
  "message_flows": [],
  "parameter_changes": [],
  "hypotheses": [],
  "troubleshooting_steps": [],
  "root_cause": {
    "conclusion": "",
    "confidence": "low",
    "evidence_event_ids": []
  },
  "fix": {},
  "verification": {},
  "lessons": {},
  "code_entities": {
    "modules": [],
    "files": [],
    "functions": [],
    "commits": []
  },
  "candidate_qa": []
}
<!-- SESSION_KNOWLEDGE_JSON_END -->
---
title: "..."
type: issue
source_session: "..."
project: "..."
confidence: medium
review_status: pending
---

# 标题

## 问题现象

...

<!-- QA_JSON_START -->
[
  {
    "question": "...",
    "answer": "...",
    "qa_type": "troubleshooting",
    "evidence": "...",
    "evidence_event_ids": ["evt-0001"],
    "related_files": [],
    "related_functions": [],
    "confidence": "medium",
    "review_status": "pending"
  }
]
<!-- QA_JSON_END -->
<!-- SECALL_DOCUMENT_END -->
```
