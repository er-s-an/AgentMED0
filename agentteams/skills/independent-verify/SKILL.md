---
name: independent-verify
description: Run Gate on the sealed candidate via scripts/run.sh. Never patch. Never rewrite REJECT as pass. Never see Builder chain-of-thought.
assign_when: A CandidateRevision is sealed and agent:verifier must score it without Builder context.
---

# independent-verify

**Verifier 永远不能看到 Builder chain-of-thought。** Kernel `verifier-context` 只给密封文件 + AcceptanceSpec + digest，不含 Builder 推理。禁止与 Builder 同房间、收 DM、或经 Lead 转发 CoT。

需要 Langfuse 时只用 `query-langfuse ... verifier`（eval/target only）。

## 输入

- `$CASE_ID`（有密封 candidate）
- Principal：`agent:verifier`
- 工具面：candidate digest、frozen EvaluationPlan、GateReport

## 输出

- Kernel JSON：`verdict`（`VERIFIED` | `REJECTED` | `INCONCLUSIVE` | `ERROR`）
- 回复 verdict。基础设施失败是 `ERROR`，未知外部结果是 UNKNOWN，不是 PASS

## 调用条件

候选已密封、Case `verifying`。只有 `agent:verifier` 可提交 Gate。

## 依赖

- `GET /v1/cases/{id}/verifier-context`
- `POST /v1/cases/{id}/verify`（Kernel 跑 pytest / frozen eval）

## 失败处理

- 无候选 → Kernel 错误，原样上报
- FAIL 不得改写为 PASS/VERIFIED
- 禁止为过闸去改 candidate 文件

## 安全边界

禁止：repo 写、merge、改 AcceptanceSpec、提候选、与 Builder 共享上下文、覆盖 FAIL。本 Worker 无 `propose-candidate`。

## 复用价值

GAN 判别器：独立闸门可挂任何 frozen eval。

## 哪个 Agent

**Verifier**（隔离 Worker）。

## 脚本

```bash
bash scripts/run.sh "$CASE_ID"
```

```bash
bash /root/.copaw-worker/verifier/skills/independent-verify/scripts/run.sh "$CASE_ID"
```
