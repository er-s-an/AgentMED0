---
name: attribute-skip
description: Record a Kernel investigation without a factorial experiment when the Issue already names insert/query file_id leakage.
assign_when: Attribution is on-demand and kotaemon #758 already states root cause.
---

# attribute-skip

## 输入

- `$CASE_ID`
- Principal：`agent:attribution`
- 可选：Issue 已写明的假设（Kernel 默认 kotaemon #758 假设）

## 输出

- Kernel JSON：`conclusion`（`SUPPORTED` / `REFUTED` / `INCONCLUSIVE` / `CONFOUNDED`）
- Case 进入 `proposing`

## 调用条件

归因按需。Issue 已指向 insert/query `file_id` 泄漏时**跳过析因**。需要 traces 时先 `query-langfuse`，缺失则 missing，不编造。

## 依赖

- Kernel `POST /v1/cases/{id}/attribute`
- 不要依赖伪造的 Langfuse

## 失败处理

- Kernel 拒绝 → 打印错误，不把猜测写成事实
- traces 缺失 → 结论可 `INCONCLUSIVE` 或 Issue-supported，并声明 uncertainty

## 安全边界

不写补丁、不 verify。不把 Builder CoT 引入归因报告。

## 复用价值

“根因已在信号里写明”的短路径；重实验应用另开完整归因，而不是改这个脚本去猜。

## 哪个 Agent

**Attribution**（`agent:attribution`）。

## 脚本

```bash
bash scripts/run.sh "$CASE_ID"
```

```bash
bash /root/.copaw-worker/attribution/skills/attribute-skip/scripts/run.sh "$CASE_ID"
```
