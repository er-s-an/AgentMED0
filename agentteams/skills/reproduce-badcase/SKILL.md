---
name: reproduce-badcase
description: Record that the scoped-file failure is real via Kernel investigate. Do not fake a pass. Gate later proves the bad case.
assign_when: Investigator must record that the kotaemon #758 scoped-file failure is real.
---

# reproduce-badcase

MVP：Kernel `investigate` 已记录 Issue 证据。不要把聊天复述当成复现成功。

## 输入

- `$CASE_ID`
- Principal：`agent:investigator`

## 输出

- Kernel JSON（与 bind-version-snapshot 同源调用时可复用 snapshot）
- 不稳定复现 → `INCONCLUSIVE`，不是假 PASS

## 调用条件

Acceptance 之后、提出候选之前。必须证明坏例真实存在。

## 依赖

- Kernel `POST /v1/cases/{id}/investigate`
- 正式 Gate 在 Verifier 的 frozen eval，不在本 skill 里跑 pytest 冒充 PASS

## 失败处理

- 已跑过：GET Case 报告状态
- 无 Kernel JSON → 不得标记已复现

## 安全边界

不改代码、不跑 Builder、不宣布 VERIFIED。

## 复用价值

任意 bad case 的“记录复现”步骤；评测细节留给独立 Gate。

## 哪个 Agent

**Investigator**。

## 脚本

```bash
bash scripts/run.sh "$CASE_ID"
```

若 snapshot 已绑定，同一 Kernel 调用即可；或：

```bash
bash /root/.copaw-worker/investigator/skills/reproduce-badcase/scripts/run.sh "$CASE_ID"
```
