---
name: secall-opencode
description: Convert local OpenCode and ChatGPT sessions into seCall-compatible Markdown, generate grounded Chinese Issue Cards and QA candidates through the model configured in OpenCode, run the local frontend/API, diagnose the integration, review QA, and rebuild the seCall index. Use when importing OpenCode history or ChatGPT conversations.json into a seCall Vault, troubleshooting missing knowledge pages, operating the local Studio, or running the Session-to-knowledge pipeline without a direct LLM API.
---

# seCall OpenCode Adapter

Use the repository CLI. Keep raw Session files traceable and local, and treat
generated QA as review candidates rather than verified facts.

## Workflow

1. Run `secall-opencode doctor` and fix any failed required check.
2. For OpenCode, run `secall-opencode sessions list`. For ChatGPT, first run
   `secall-opencode chatgpt inspect <conversations.json>`.
3. Import ChatGPT with
   `secall-opencode chatgpt import <conversations.json> --project <name>`.
4. Preview with `secall-opencode pipeline --session <session-id> --dry-run` when the target
   Vault or generated files are uncertain.
5. Run `secall-opencode pipeline --session <session-id>` to export, convert, generate, and
   reindex.
6. Report the generated Session Markdown, Issue Card, number of new QA candidates,
   and index result.

## Individual Operations

- Convert an exported JSON file:
  `secall-opencode convert <export.json>`.
- Inspect converted facts before generation:
  `secall-opencode inspect <session.md>`.
- Generate knowledge:
  `secall-opencode generate <session.md>`.
- Rebuild only the index:
  `secall-opencode index`.
- Start the local frontend API:
  `secall-opencode serve`.
- Start the full local Studio from the repository:
  `powershell -ExecutionPolicy Bypass -File scripts\start-local.ps1`.
- Use `--json` before the subcommand when output will be consumed by another tool.

## Safety Rules

- Use the default unsanitized export for knowledge generation. OpenCode's
  `--sanitize` hides the evidence text and is only suitable for sharing or
  conversion diagnostics.
- Do not run write SQL through `raw db`; it is intentionally read-only.
- Do not overwrite a conflicting Session file without confirming the intended
  source. Use `--overwrite` only when replacement is expected.
- Do not describe generated QA as approved. The adapter writes
  `review_status: pending`.
- If generation parsing fails, preserve the raw Session and stop before indexing
  incomplete knowledge.
- Keep the API bound to `127.0.0.1`; do not expose imported ChatGPT data on a
  LAN or public host without explicit authorization.

## Missing Knowledge Diagnosis

Check, in order:

1. The OpenCode Session exists and can be exported.
2. The converted file exists below `raw/.sessions/YYYY-MM-DD/`.
3. Generation returned both Issue Card and QA markers.
4. The Issue Card exists below `wiki/issues/`.
5. `secall-opencode index` succeeds.
6. The Web UI is using the same Vault path configured for the adapter.
