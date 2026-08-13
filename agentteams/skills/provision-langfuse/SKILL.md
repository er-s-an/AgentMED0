---
name: provision-langfuse
description: Once-per-app Langfuse/Kernel health check. Prints project/OTLP/key references only. Unreachable → NEEDS_CONTEXT, exit 0. Not the official Langfuse SDK skill.
assign_when: Intake or Investigator must confirm Langfuse is reachable for an application before relying on traces.
---

# provision-langfuse

AgentMED 薄封装。官方 CLI/文档 skill 在 `agentteams/skills/langfuse/`（从 `npx skills add langfuse/skills --skill langfuse` 拷贝）。本脚本**不**复制 SDK，只检查健康并打印**引用**。

## 输入

- `LANGFUSE_HOST` 默认 `http://host.docker.internal:3001`
- `AGENTMED_KERNEL_URL` 默认 `http://host.docker.internal:8088`
- 环境中的 key **名称**（`LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`）；脚本不读取打印其值

## 输出

- 可达：JSON `status=ok` + `refs`（host / OTLP / key 环境变量名 / project 名）+ `governance.prompt_names`（AgentMED 各角色静态提示词目录，不含密钥）
- 不可达：`status=NEEDS_CONTEXT`，`needs_context=true`，**exit 0**。仍可能带上本地 `governance.prompt_names`。

Kernel 会把该目录 upsert 到 Langfuse Prompt Management（密钥仍只在 Kernel）。Worker 运行时的真实 messages 走 Kernel `POST /v1/chat/completions`，打 `agentmed-governance` tag。

## 调用条件

每个被治理应用**一次**（或栈重启后）。在 `query-langfuse` / `ingest-langfuse` 之前确认站点存在。

## 依赖

- Langfuse UI/API（:3001）或 Kernel `/health`
- 不要求官方 `langfuse-cli`

## 失败处理

不可达 → NEEDS_CONTEXT JSON，exit 0。不伪造 project、不编造 OTLP 已接通。

## 安全边界

**禁止打印 API key / secret。** 只打印 `LANGFUSE_PUBLIC_KEY` 这类引用名。密钥由 Kernel 持有。

## 复用价值

任何接入 Langfuse 的应用共用同一健康检查；换项目只换 Kernel/env 引用。

## 哪个 Agent

典型 **Intake** 或 **Investigator**，每个 app 一次。不是 Verifier。

## 脚本

```bash
bash scripts/run.sh
```

```bash
bash /root/.copaw-worker/investigator/skills/provision-langfuse/scripts/run.sh
```
