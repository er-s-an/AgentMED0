---
name: draft-pr
description: POST Kernel /v1/cases/{id}/draft-pr as agent:lead. Local draft only. No merge, no git push. Unverified → Kernel error, non-zero exit.
assign_when: Kernel has VerifiedCandidate / NOT DEPLOYED and quality-officer must request a draft PR WorkOrder.
---

# draft-pr

Kernel 是真相源。Matrix 聊天不是。

## 输入

- `$CASE_ID`（已 Gate `VERIFIED` 的 Case）
- Principal：`agent:lead`（可用 `AGENTMED_PRINCIPAL` 覆盖）
- Kernel：`AGENTMED_KERNEL_URL` 默认 `http://host.docker.internal:8088`

## 输出

- Kernel JSON：本地 patch / draft PR 工件引用 + `ExternalOperation` receipt
- 未验证：stderr 打印 Kernel 错误，**非零退出**

## 调用条件

Gate `VERIFIED` 之后，需要 PR 形状的执行证据（kotaemon #758 demo）。Lead **请求**；Controller **执行**。

## 依赖

- Kernel `POST /v1/cases/{id}/draft-pr`
- 可选 GitHub token 由 Kernel 持有；Worker 不持 PAT

## 失败处理

- Case 未验证 / 无 VerifiedCandidate → 打印 Kernel 错误并 `exit 1`
- Kernel 不可达 → `exit 1`
- 无 hosted PR token → 只保留本地 patch，不得声称已开上游 PR

## 安全边界

禁止 merge、`git push`、生产 PR。不把 GitHub PAT 写入 Worker soul。不覆盖 Gate。

## 复用价值

任意已验证 Case 的本地交付证据；与 `release-observe-rollback` 互补（shadow/rollback vs draft PR 工件）。

## 哪个 Agent

**quality-officer**（`agent:lead`）调用本脚本。Controller/Executor 在 Kernel 内执行。禁止 Builder / Verifier。

## 脚本

```bash
bash scripts/run.sh "$CASE_ID"
```

Worker 路径：

```bash
bash /root/.copaw-worker/quality-officer/skills/draft-pr/scripts/run.sh "$CASE_ID"
```
