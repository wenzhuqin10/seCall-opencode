# OpenCode Session 知识抽取规则

分析附带的 seCall Session Markdown，生成一份可追溯、可审核的中文 Issue Card。

严格要求：

1. 只能使用 Session 中出现的事实，不得猜测。
2. 保留代码、命令、路径、错误信息与产品名原文。
3. 若 Session 没有形成明确问题或解决结论，必须标记“证据不足”，不得伪造根因。
4. frontmatter 必须包含：
   - `title`
   - `type: issue`
   - `source_session`
   - `project`
   - `confidence: high | medium | low`
   - `review_status: pending`
5. 正文使用以下结构：
   - 问题现象
   - 影响范围
   - 定位过程
   - 根因分析
   - 修复方案
   - 代码变更
   - 验证方法
   - 经验总结
   - 相关代码与文档
6. 生成 3～10 条高价值候选 QA，每条包括：
   - `question`
   - `answer`
   - `qa_type`
   - `evidence`
   - `confidence`
   - `review_status: pending`

输出格式必须完全遵循：

```text
<!-- SECALL_DOCUMENT_START -->
---
title: "..."
type: issue
source_session: "..."
project: "..."
confidence: medium
review_status: pending
---

# 标题

...

<!-- QA_JSON_START -->
[
  {
    "question": "...",
    "answer": "...",
    "qa_type": "troubleshooting",
    "evidence": "...",
    "confidence": "medium",
    "review_status": "pending"
  }
]
<!-- QA_JSON_END -->
<!-- SECALL_DOCUMENT_END -->
```

