# seCall OpenCode Adapter

将 OpenCode Session 转换为 seCall 可索引的 Markdown，并通过本机
OpenCode + GLM 生成中文 Issue Card 与候选 QA。框架不要求独立的 LLM API。

## 工作流程

```text
OpenCode Session
  → 本地导出
  → seCall Session Markdown
  → OpenCode/GLM 知识抽取
  → Issue Card + QA JSONL
  → seCall 重建索引
```

原始 Session 与生成知识分别写入：

```text
<vault>/raw/.sessions/YYYY-MM-DD/
<vault>/wiki/issues/
<vault>/knowledge/qa/candidates.jsonl
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
- 知识抽取提示词要求仅使用 Session 中的证据。
- 所有 QA 初始状态均为 `pending`，需人工审核后再用于正式知识库。
- 转换具有幂等性；内容冲突时必须显式使用 `--overwrite`。

架构和数据契约见 [docs/architecture.md](docs/architecture.md)。
