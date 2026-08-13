---
name: curate-regression-asset
description: Close the Case with a RegressionAsset after rollback. Run scripts/run.sh.
assign_when: Case has Gate evidence and Curator must persist a reusable asset.
---

# curate-regression-asset

## 输入

- `$CASE_ID`
- 可选 summary（默认 kotaemon file-scope 回归说明）
- Principal：`agent:curator`

## 输出

- Kernel JSON：RegressionAsset `id` + closed Case
- 回复 asset `id`

## 调用条件

已有 Gate 证据且（通常）已 rollback。禁止在飞行中的 Case 上改写历史。

## 依赖

- Kernel `POST /v1/cases/{id}/close`

## 失败处理

- 缺 Gate 证据 → 拒绝，不编造资产
- Kernel 错误原样打印

## 安全边界

不改候选、不重跑 verify、不 merge。资产是只增版本。

## 复用价值

下一轮 Gate 拦截同类失败；换应用换 probes 列表即可。

## 哪个 Agent

**Curator**。

## 脚本

```bash
bash scripts/run.sh "$CASE_ID"
bash scripts/run.sh "$CASE_ID" "optional summary"
```

```bash
bash /root/.copaw-worker/curator/skills/curate-regression-asset/scripts/run.sh "$CASE_ID"
```
