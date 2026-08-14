---
name: coordinate-loop
description: Drive one AgentMED Case as Team Leader. Dispatch Kernel-legal Worker tasks in order. Poll Kernel after every step. Do not ask the admin.
assign_when: Manager hands a GitHub signal or pending Case to quality-officer.
---

# coordinate-loop

Team Leader。YOLO：不要问 admin。Kernel HTTP 是真相源：`http://host.docker.internal:8088`。

Matrix 域名 `matrix-local.agentteams.io:18080`，@mention 用**完整** ID。

**永远不要把 Builder CoT 转给 Verifier。**

## 输入

- GitHub URL 或已有 `$CASE_ID`
- 各 Worker 的 Matrix ID

## 输出

- 轮询得到的 Case JSON（state、gate、ids）
- 调度指令（谁跑哪条 skill），自己不执行 ingest/investigate/candidates/verify/close

## 调用条件

Manager 把信号或 Case 交给 quality-officer。全程串行，每步后 poll Kernel。

## 依赖

- `scripts/run.sh` / `scripts/poll.sh`
- Worker skills：ingest-signal、ingest-langfuse、bind-version-snapshot、query-langfuse、connect-observability、attribute-skip、propose-candidate、independent-verify、release-observe-rollback、draft-pr、curate-regression-asset

## 失败处理

- 不信任聊天。Kernel 未变则重试调度，不跳过 Acceptance
- REJECT → 只把 GateReport 给 Builder 开新 revision
- Langfuse 必须先查。`investigate` 会 query + 复现失败查询并尝试写 target span。没有 target trace 记 missing，禁止伪造。Case 可以继续，但不得假装查过。

## 安全边界

禁止 Gate 覆盖、merge、push、生产发布、自己当 Verifier、自己提候选、持有 PAT。

## 复用价值

一条 Case 的标准编排；换信号源只换 Intake skill。

## 哪个 Agent

**quality-officer**（Team Leader / `agent:lead`）。

## 脚本

```bash
bash scripts/run.sh "$GITHUB_URL"
bash scripts/run.sh --case "$CASE_ID"
# equivalent:
bash scripts/poll.sh "$GITHUB_URL"
bash scripts/poll.sh --case "$CASE_ID"
```

```bash
bash /root/.copaw-worker/quality-officer/skills/coordinate-loop/scripts/run.sh --case "$CASE_ID"
```

## Sequence (serial)

每步先 `GET /v1/cases/$CASE_ID/next`，只派 `next[0]` 那一步。不要按记忆跳步。`closed` 时 `next` 为空，停。

1. @intake: `ingest-signal/scripts/run.sh <github-url>`（或 `ingest-langfuse/scripts/run.sh`）。可选 `provision-langfuse`（project/OTLP/密钥引用）。等到 `GET /v1/cases?source_ref=` 有 Case。
2. `next.role=human`：等到人类 CLI 确认 AcceptanceSpec。禁止跳过。
3. `next.skill=bind-version-snapshot`：@investigator 跑 `bind-version-snapshot`（Kernel 会查 Langfuse 并复现失败查询）。然后必须 `query-langfuse $CASE_ID investigator` 再读一遍。`provision-langfuse` 在本步之前跑一次。监控挂了只降级，禁止伪造。
4. `next.skill=attribute-skip`：@attribution；必须 `query-langfuse $CASE_ID attribution`。
5. `next.skill=propose-candidate`：@builder。Never forward Builder CoT to Verifier.
6. `next.skill=independent-verify`：@verifier。隔离。Langfuse 只用 `query-langfuse $CASE_ID verifier`（eval/target）。
7. REJECTED 后再 `GET .../next`：仍是 propose-candidate；只把 GateReport 给 Builder。禁止 patch 已密封候选。
8. `next.skill=release-observe-rollback`：你跑该 skill，再跑 `draft-pr/scripts/run.sh $CASE_ID`。
9. `next.skill=curate-regression-asset`：@curator。
