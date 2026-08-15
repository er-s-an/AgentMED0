---
name: propose-candidate
description: Fetch builder-context, edit only allowed_files, then submit files with scripts/run.sh. Do not self-verify.
assign_when: Case is proposing and only agent:builder may emit a candidate.
---

# propose-candidate

## 输入

- `$CASE_ID`
- 提交时：一个文件、目录、或 `{相对路径: 全文}` JSON + 可选 summary
- Principal：`agent:builder`
- Kernel `GET /v1/cases/{id}/builder-context` 给出的 AcceptanceSpec、`files`、`allowed_files`、`instruction`

## 输出

- 仅 context：基线文件 + spec + 指令
- 提交后：密封 `CandidateRevision` JSON（`id` / digest）。此后不可原地改

## 调用条件

Case `proposing`。只有 `agent:builder` 可提交。REJECT 后开**新** revision，不 patch 已密封候选。

## 依赖

- `GET .../builder-context` 与 `POST .../candidates`
- 只改 `allowed_files`。多交的文件 Kernel 会 400
- 行为约束以 `instruction` 为准，不要假设一定是 `lightrag_store.py`

## 失败处理

- Kernel 拒绝 → 打印错误，不声称已验证
- 禁止为了“通过”去改 eval/

## 安全边界

禁止跑 pytest、调用 `/verify`、读 `eval/`、宣布 VERIFIED、merge/push。不要写 GateReport。本 Worker **没有** `independent-verify`。

## 复用价值

最小候选提交管道；换文件时仍走同一 Kernel 密封。

## 哪个 Agent

**Builder only**。

## 脚本

```bash
bash scripts/run.sh "$CASE_ID"
# then write the allowed file(s) and:
bash scripts/run.sh "$CASE_ID" /tmp/allowed-file.py "minimal fix"
```

```bash
bash /root/.copaw-worker/builder/skills/propose-candidate/scripts/run.sh "$CASE_ID"
bash /root/.copaw-worker/builder/skills/propose-candidate/scripts/run.sh \
  "$CASE_ID" /tmp/allowed-file.py "minimal fix"
```
