---
name: ingest-signal
description: Open a Kernel Signal+Case from a GitHub issue URL by running scripts/run.sh. Do not describe the HTTP call; execute it.
assign_when: A GitHub issue URL arrives and Intake must open or reuse a Case.
---

# ingest-signal

Kernel 是真相源。Matrix 聊天不是。Langfuse 评测信号请用 `ingest-langfuse`。

## 输入

- GitHub Issue URL（kotaemon #758：`https://github.com/Cinnamon/kotaemon/issues/758`）
- Principal：`agent:intake`
- Kernel：`http://host.docker.internal:8088`

## 输出

- JSON：`signal`、`case.id`、`case.state`（通常 `awaiting_acceptance`）
- 回复 Team Leader **只给 `case.id`**

## 调用条件

收到 GitHub Issue URL，需要开或复用 Case。同一 `source_ref` 不得开第二个 Case。

## 依赖

- Kernel `POST /v1/signals/ingest`
- GitHub 可达（token 在 Kernel）

## 失败处理

- GitHub/Kernel 失败 → 原样打印错误，标 NEEDS_CONTEXT，不编造 Issue
- Feishu 未接通时不要假装已跑

## 安全边界

禁止归因、打补丁、宣布修复、写 GateReport、越权改 Case 状态。不打印 GitHub PAT。

## 复用价值

任意 GitHub Issue → Signal+Case 的 Intake 入口。

## 哪个 Agent

**Intake**（`agent:intake`）。

## 脚本

```bash
bash scripts/run.sh "$GITHUB_ISSUE_URL"
```

```bash
bash /root/.copaw-worker/intake/skills/ingest-signal/scripts/run.sh \
  "https://github.com/Cinnamon/kotaemon/issues/758"
```
