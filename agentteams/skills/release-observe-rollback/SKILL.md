---
name: release-observe-rollback
description: After Gate VERIFIED, shadow-apply locally, rollback, and keep a local draft patch. Never merge or git push.
assign_when: quality-officer sees Kernel verdict VERIFIED and must request Controller release.
---

# release-observe-rollback

## 输入

- `$CASE_ID`（Gate `VERIFIED`）
- Principal：`agent:lead`

## 输出

- Kernel JSON：shadow apply + rollback 证据；本地 draft patch 引用
- 成功仍是 `VerifiedCandidate / NOT DEPLOYED`，不是生产发布

## 调用条件

Verifier 已 `VERIFIED`。先 `GET /v1/cases/{id}/next`。没有人批准的 WorkOrder 就停，不要 POST `/release`。由 quality-officer **自己跑**本脚本（不要让 Builder/Verifier 发版）。draft PR 工件另跑 `draft-pr`。

## 依赖

- Kernel `GET /v1/cases/{id}/next`
- Kernel `POST /v1/cases/{id}/shadow`（`/release` 只是别名，无 Approval 会 409）
- Controller 在 Kernel 进程内执行

## 失败处理

- next 不是 `SHADOW_DRILL` → 停，把 next 打出来给人批
- 无候选 / 未验证 / 无 Approval → 打印 Kernel 错误
- 观察失败 → rollback 证据必须留下；禁止“算了直接上生产”

## 安全边界

禁止 `git push`、merge、生产 deploy。Worker 不持 PAT。不覆盖 Gate。

## 复用价值

任意已验证修复的本地 shadow+rollback 证据链。

## 哪个 Agent

**quality-officer**（`agent:lead`）。Controller 执行。

## 脚本

```bash
bash scripts/run.sh "$CASE_ID"
```

```bash
bash /root/.copaw-worker/quality-officer/skills/release-observe-rollback/scripts/run.sh "$CASE_ID"
```
