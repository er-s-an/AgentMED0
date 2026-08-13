---
name: query-langfuse
description: GET Kernel langfuse-traces for a Case role. If needs_context, POST evidence missing. Never invent spans. Verifier must not see Builder CoT.
assign_when: Investigator, Attribution, or Verifier wants traces and must not invent them.
---

# query-langfuse

通过 **Kernel** 读 Langfuse（Kernel 持有密钥）。Worker 不要直接用官方 SDK 去翻密钥。官方 Langfuse skill 在 `agentteams/skills/langfuse/`，本 skill 只做 Case 角色过滤查询。

**Verifier 永远不能看到 Builder chain-of-thought。** 角色必须原样传给 Kernel：`role=verifier` 只允许 eval/target traces。

kotaemon #758 Attribution 优先 `attribute-skip/scripts/run.sh`，不要做析因实验。

## 输入

- `$CASE_ID`
- 可选角色：`investigator` | `attribution` | `verifier`（默认按 `AGENTMED_PRINCIPAL`，否则 `investigator`）
- Kernel：`http://host.docker.internal:8088`

## 输出

- 有 traces：Kernel JSON（spans/traces）
- 缺失：`needs_context: true` + POST evidence `missing: ["target_app_langfuse_traces"]`，traces 为空数组

## 调用条件

需要目标应用 Langfuse 痕迹时。Verifier 仅在评测/目标相关查询时使用本 skill。

## 依赖

- `GET /v1/cases/{id}/langfuse-traces?role=...`
- 失败时 `POST /v1/cases/{id}/evidence`
- 密钥在 Kernel / Langfuse，不在 Worker 聊天里

## 失败处理

- HTTP 失败、空 traces、`needs_context` → POST missing evidence，**不编造 spans**，exit 0
- 不要把 Builder CoT 或候选推理转给 Verifier

## 安全边界

Verifier 工具面：eval/target only。禁止把 Builder 房间、diff 推理、CoT 塞进本查询。不打印 API key。

## 复用价值

三角色共用同一 Kernel 查询；角色过滤保证隔离。换 Langfuse 项目只需 Kernel 配置。

## 哪个 Agent

- Investigator、Attribution：诊断 traces
- **Verifier**：仅 eval/target；不得用于读取 Builder 过程

## 脚本

```bash
bash scripts/run.sh "$CASE_ID" [investigator|attribution|verifier]
```

```bash
bash /root/.copaw-worker/investigator/skills/query-langfuse/scripts/run.sh "$CASE_ID" investigator
bash /root/.copaw-worker/attribution/skills/query-langfuse/scripts/run.sh "$CASE_ID" attribution
bash /root/.copaw-worker/verifier/skills/query-langfuse/scripts/run.sh "$CASE_ID" verifier
```

`scripts/attribute.sh` 是 `attribute-skip` 的薄别名；归因请跑 `attribute-skip/scripts/run.sh`。
