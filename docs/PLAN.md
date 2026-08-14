# AgentMED 落地 Plan

> 配套：`docs/SPEC.md`  
> 日期：2026-08-14  
> 仓库：https://github.com/er-s-an/AgentMED

初赛（约 8/13–8/16）不交代码。复赛（约 8/25–9/3）要能路演一条真实闭环。下面按这个时间排，不再按「先 playbook、复赛再挂 AgentTeams」写——那条已经做过了。

---

## 1. 现在在哪

骨架已经在仓库里，而且默认路径是 **AgentTeams 真跑，不是 golden playbook**：

- Kernel 状态机、权限、Gate、`VerifiedCandidate / NOT DEPLOYED`、Shadow / 回滚分列
- kotaemon #758 的失败模式 harness（不跑全站 UI）
- `agentteams/` Team / Worker / Skill，CLI `run` 只派活、盯 Kernel
- 开源仓库、双语 README、CI
- AgentMED 自己的提示词：静态目录 + Kernel LLM 代理（代码在；现有集群要重切 URL 才抓得到运行时）

过时的假设不要再跟：本地 playbook 当正式成功、复赛才第一次碰 AgentTeams、产品名还要改。

---

## 2. 叙事要成立的那句话

别的 Agent 交来一次坏结果。人确认怎样算修好。里面一队 Agent 去查、改、验。验过了也不上线，只交出 `VerifiedCandidate / NOT DEPLOYED` 和证据包。

评委伸手时，应该摸到三块，而不是一篇架构文：

1. **外面**：Card 上只有报案 / 查状态 / 取证据。GitHub Issue 是证据，不是入口身份。
2. **里面**：Manager → 质量官 → Workers；Kernel 改状态；Matrix 聊天不算数。
3. **出口**：Gate 过了仍是 `NOT DEPLOYED`；有本地草稿和回滚；Langfuse 能按角色看见提示词（挂了就写 missing）。

---

## 3. 和 SPEC §11 差在哪

| # | 验收 | 现在 | 评委伸手时 |
|---|---|---|---|
| 1 | 同 Issue 不重复立案 | Kernel 对未关闭 Case 幂等 | 够用 |
| 2 | AcceptanceSpec 有 `human:` | `--accept` 已记 | 够用 |
| 3 | base eval 稳定失败 | harness 单测在 | 够用 |
| 4 | 至少一个 `VERIFIED`，known-bad 拦截 | Gate 会跑三件套 | 够用；live Builder 质量看运气 |
| 5 | 草稿 PR 在、未 merge | 有 `draft-pr` Skill；上次 live 的 patch 像占位 | **要补**：导出必须是真 diff |
| 6 | Shadow desired / observed / receipt 分列 | Kernel 已记 | 够用 |
| 7 | 回滚后 observed 回到 base | 上次 live 做过 | 再录一次干净的 |
| 8 | RegressionAsset 可被后续 Gate 引用 | 关闭时会写资产 | **要补**：下一 Case 真读到它 |
| 9 | Langfuse 至少 Intake / Builder / Verifier 三条 | 代理和目录已写；现网 Worker 多半还直连模型 | **要补**：重切 LLM URL，截一张 UI |
| 10 | 未授权外部动作 = 0 | 策略在，没有上游 push | 够用 |

另外三件**叙事上要诚实、代码上先不做**：

- A2A `message/send`：Card 已写明「合同在、门还没装」。初赛讲契约，复赛也不必先做 JSON-RPC。
- 飞书 / 目标应用 live trace：SPEC 允许缺，标 `NEEDS_CONTEXT`。不要为了图好看去编 span。
- 质量官上次会卡住，要人在 Matrix 里催一刀。协同还不够「Kernel 说了算」。

**判断：** Langfuse 已是默认证据总线（retarget 开、investigate 必查、eval 写 target span）。P0–P4 已落到 Kernel / HTTP / review.html：验收草稿≠确认、双 surface Gate、LangGraph #7684、双 Gate + WorkOrder、Case Workspace + 薄 MCP + `agentmed init`。Shadow 永远不是发布。

---

## 4. 明确不做

- kotaemon 全量 UI
- 真飞书、多租户、HA
- 把 VerifiedCandidate 说成已上线
- 第二套编排器、AgentLoop 依赖
- 让质量官投票代替 Gate
- 为了 PPT 改 README 塞实现细节
- 改官方 `agentteams/skills/langfuse/`

---

## 5. 三波（初赛不交代码，时间够）

### A. 初赛只讲（现在 → 约 8/16）

不写新功能。PPT 直接搬 SPEC §3 角色、§7 Skill、§8 Team 图、§6 Langfuse 双层、§9 人批边界。

评委听完应能复述：

- 入口是 Agent，不是 Issue 机器人
- 执行在 AgentTeams，账本在 Kernel
- 出口是未部署的验证候选 + 证据包
- 审查在 Langfuse，挂了就降级

开源计划一句话：仓库已 public，Apache-2.0，欢迎在自己的 AgentTeams 上加载 `agentteams/`。

### B. 把 Demo 做成可再跑（约 8/17–8/24）

按这个顺序，做完一项再下一项：

1. **现网 LLM 走 Kernel 代理**  
   默认改写 AgentTeams 的 LLM URL 到 Kernel。`AGENTMED_RETARGET_LLM=0` 才跳过。重建 Worker 后，Langfuse 里应按 `agentmed-governance` 看到角色 generation；`investigate` 必须查过 Langfuse。没有就写 missing，不许造。

2. **质量官不再靠人催**  
   `coordinate-loop` 每步先 `GET /v1/cases/{id}/next`，只派那一步。Builder 该上场时必须 `@` 到人，不许停在调查完。

3. **抽 Workload Adapter**  
   Gate / Builder / Shadow 走 `AIApplication.slug` 对应的 adapter。kotaemon 仍是唯一真实 workload；换应用不必复制 `lightrag_store.py`。未知 slug 失败。

4. **草稿是真文件**  
   `draft-pr` 写出能 `diff` 的 `draft.patch`。export 里能指到它。仍然不 merge、不 push 上游。给人看的 kotaemon #758 包在 `workloads/kotaemon-lightrag-scope/upstream/`；人加 `--i-am-human` 才能开 PR。

5. **RegressionAsset 闭环**  
   关闭后的 probes 进入下一次 Gate 的 `evidence.prior_regression_assets`（引用，不改判定）。

6. **一条干净录像**  
   另一台机器：`git pull` → `.env` → `live-stack` → `serve` → `run --signal #758 --accept-adapter-defaults`。出口对得上 SPEC §11。卡住就修协同，不要切回 playbook 充数。

### C. 复赛路演（约 8/25–9/3）

材料是 B 的产物，不是新功能：

- 30 秒：坏结果进、人点头、队去干、出来未上线的候选
- 2 分钟：Kernel 状态机 + Builder/Verifier 隔离
- 1 分钟：Langfuse 双层（自己的提示词 / 目标应用可缺）
- 1 分钟：草稿 + Shadow + 回滚，强调 `NOT DEPLOYED`
- 备用：Gate `REJECTED` 也是闭环；对照补丁必须标明不是放水

---

## 6. 另一台机器怎么接

```bash
git pull origin main
```

先读本文件第 5 节，再动代码。SPEC 是合同，本文件是施工顺序。不要从阶段 0 改名重新来。
