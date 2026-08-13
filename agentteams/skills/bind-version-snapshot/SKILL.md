---
name: bind-version-snapshot
description: Freeze VersionSnapshot + evidence on a Case by running scripts/run.sh. Execute the script; do not invent a commit.
assign_when: AcceptanceSpec is confirmed (Kernel state investigating) and Investigator must bind the kotaemon snapshot.
---

# bind-version-snapshot

## 输入

- `$CASE_ID`（Kernel `state=investigating`）
- Principal：`agent:investigator`

## 输出

- Kernel JSON：`snapshot`（含 `id` / digest）及已有则 `reused`
- 回复 `snapshot.id`。不打补丁、不 verify

## 调用条件

人类已确认 AcceptanceSpec。Investigator 必须绑定不可变快照后再采集。

## 依赖

- Kernel `POST /v1/cases/{id}/investigate`
- kotaemon #758：repo `Cinnamon/kotaemon`，commit `ffe766f24d4ef8a91f8c61871d2b5a1930aa204e`（Kernel 写入，禁止自造 SHA）

## 失败处理

- 重复绑定：GET `/v1/cases/$CASE_ID` 报告现态，不编造 commit
- Langfuse 缺失由 Kernel/query-langfuse 记 `missing`，不伪造 traces

## 安全边界

不修改被治理系统。不持有发布密钥。快照清单只记录已知 repo/commit/prompt 引用。

## 复用价值

任意 Case 的版本冻结步骤；换应用只换 Kernel 内 snapshot manifest。

## 哪个 Agent

**Investigator**。

## 脚本

```bash
bash scripts/run.sh "$CASE_ID"
```

```bash
bash /root/.copaw-worker/investigator/skills/bind-version-snapshot/scripts/run.sh "$CASE_ID"
```
