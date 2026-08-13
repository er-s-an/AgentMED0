---
name: ingest-langfuse
description: Intake POST /v1/signals/ingest-langfuse. Low-score or failed eval becomes a Signal. Empty → needs_context; never invent a GitHub issue.
assign_when: Intake should open a Case from Langfuse low-score / failed evaluation rather than a GitHub URL.
---

# ingest-langfuse

GitHub ingest 用 `ingest-signal`。本 skill 只走 Langfuse 评测信号。官方 Langfuse SDK skill 不负责开 Case。

## 输入

- 可选 JSON 参数（窗口/过滤），默认 `{}`
- Principal：`agent:intake`
- Kernel：`http://host.docker.internal:8088`

## 输出

- 有低分/失败评测：Kernel JSON（`signal` + `case`）
- 空：`needs_context` / `NEEDS_CONTEXT`，不创建假 Issue

## 调用条件

Langfuse 出现低分或 failed eval，且没有对应 GitHub URL（或作为并行信号源）。kotaemon #758 主路径仍是 GitHub `ingest-signal`。

## 依赖

- Kernel `POST /v1/signals/ingest-langfuse`（Kernel 持 Langfuse 密钥）
- 密钥不进 Worker 聊天

## 失败处理

- HTTP 失败、空列表、`needs_context` → 打印 JSON，**exit 0**
- **禁止编造 GitHub issue 或假 Signal**

## 安全边界

不打印 API key。不把评测原文里的密钥带进 Matrix。不开第二套 Case 状态机。

## 复用价值

任意 Langfuse 项目的 failed eval → Signal 管道；与 `ingest-signal` 并列。

## 哪个 Agent

**Intake**（`agent:intake`）。Lead 不代替执行。

## 脚本

```bash
bash scripts/run.sh
bash scripts/run.sh '{"since":"2026-01-01"}'
```

```bash
bash /root/.copaw-worker/intake/skills/ingest-langfuse/scripts/run.sh
```
