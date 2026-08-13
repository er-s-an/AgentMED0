---
name: connect-observability
description: Optional enterprise-monitor connector. Script POSTs EvidenceReceipt; on any failure records receipt.missing. Never forge metrics. Not Aliyun CMS.
assign_when: Investigator needs extra telemetry from an existing enterprise stack; Kernel should only store a receipt.
---

# connect-observability

企业监控的**通用入口**。不要操作阿里云 CMS。MCP 是扩展点。Kernel 不内嵌监控产品，只存 `EvidenceReceipt`。

kotaemon #758 默认路径：**未配置站点** → `missing` receipt，**exit 0**，Case 继续。

## 输入

- `$CASE_ID`（必填）
- 可选 `MONITOR_URL`（HTTP 健康检查）
- 可选 `MONITOR_MCP_URL`（MCP 扩展）
- Principal 默认 `agent:investigator`

## 输出

- JSON：`status`（`degraded` / `connected_no_metrics`）+ `receipt` + `missing`
- Kernel `POST /v1/cases/{id}/evidence` 的 receipt（`kind,summary,artifacts,missing`）

## 调用条件

GitHub + Langfuse 不够、且组织已有监控时。#758 MVP 无站点时仍要跑脚本（写 missing），不要跳过成“文档-only”。

## 依赖

- Kernel `POST /v1/cases/{id}/evidence`
- 可选外部 MCP / HTTP。非 Case 推进硬依赖

## 失败处理

- 未配置 / 不可达 / 探测失败 → POST evidence，`missing` 含 `enterprise_monitor_station`（或 metrics）
- **禁止伪造指标**
- 降级 **exit 0**，让 Case 继续

## 安全边界

密钥只用引用。不把 Kernel 权限扩到云厂商控制台。Receipt 是证据，不是 Case 状态。禁止 Aliyun CMS 操作。

## 复用价值

任意企业监控（Datadog、自建 Prometheus、未来 MCP）同一入口；换厂商只换 MCP，不改 Kernel。

## 哪个 Agent

**Investigator**（典型）。其他 Worker 需要额外遥测时也可。不是 Kernel 内置依赖。

## 脚本

```bash
bash scripts/run.sh "$CASE_ID"
# optional:
MONITOR_URL="http://..." MONITOR_MCP_URL="http://..." bash scripts/run.sh "$CASE_ID"
```

```bash
bash /root/.copaw-worker/investigator/skills/connect-observability/scripts/run.sh "$CASE_ID"
```
