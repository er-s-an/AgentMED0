# AgentMED 产品与技术 Spec

> 状态：已确认，施工中  
> 版本：0.1  
> 日期：2026-08-13  
> 仓库：`/Users/tencent_go/AgentMED`

---

## 1. 产品定义

**AgentMED** 让 AI 应用团队把一次坏结果，变成经过独立验证、可安全采用、并能防止复发的修复。

它不是通用多 Agent 聊天框架，也不是第二套可观测平台。它是质量事件的治理与执行闭环：

```text
异常 / 反馈
→ 有来源、可复现、经人确认的 bad case
→ 绑定当时的版本与证据
→ Agent Team 调查并生成候选修复
→ 独立验证：真的修好，且没有制造回归
→ VerifiedCandidate / Reject / 补证
→ 按需人工批准后发草稿 PR 或 Shadow 变更
→ 独立观察、对账、回滚
→ 沉淀为下一次自动拦截的回归资产
```

差异不在「Agent 更多」，而在于创造性工作被放进可复核的分工、证据、门禁和授权之下。

### 1.1 命名

| 对外 | 取值 |
|---|---|
| 产品名 | AgentMED |
| CLI / Python 包 | `agentmed` |
| 默认 Git 仓库 | `AgentMED` |
| 域名对象 | 仍用 Case / Signal / Gate 等治理对象，不把产品名塞进每个类型 |

不再使用 AgentMED 作为产品名、包名、CLI 或参赛作品名。

### 1.2 参赛约束

GOAI Agent Infra 赛道：

- **必须**以 AgentTeams 为多 Agent 协同设计基点（Manager–Team Leader–Worker）
- **必须**有 ≥3 个不同职能 Agent，并提交 Agent Identity 清单
- **必须**把关键能力做成可复用 Skill
- **必须**能讲清：验证、审批、回滚、审计、证据沉淀
- 可观测官方推荐 AgentLoop；允许替代，但要写清契约与迁移成本

AgentMED 的默认 runtime 就是 AgentTeams。治理内核保持可替换，参赛与默认部署不走第二套编排器。

---

## 2. 分层：三件事不要揉成一套系统

```text
┌─────────────────────────────────────────────────────────┐
│ 人类：确认 AcceptanceSpec、批准高风险动作、接管异常 Case │
└─────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────┐
│ AgentMED Kernel（确定性控制面）                         │
│ 状态机 / 权限 / 幂等 / Gate / 审计 / WorkOrder / 对账     │
│ HTTP + CLI 是权威入口；Agent 自报不算成功                │
└─────────────────────────────────────────────────────────┘
          │ typed Task                     │ OTEL / Prompt
          ▼                                ▼
┌──────────────────────────┐    ┌─────────────────────────┐
│ AgentTeams（概率性执行面）│    │ Langfuse（审查与诊断面） │
│ Manager 不改权威状态      │    │ 本系统 trace + 目标应用 │
│ TL = 质量官               │    │ prompt 版本可审计       │
│ Workers = 其余角色        │    │ 供其他 Agent 做诊断     │
│ Verifier 独立 Worker      │    └─────────────────────────┘
│ 产物走 MinIO / artifact   │
└──────────────────────────┘
          │
          ▼
   被治理 AI 应用 + GitHub / 飞书 Signal
```

原则：

1. **确定性控制面，概率性执行面。** Agent 理解、调查、起草；Kernel 拥有状态。
2. **AgentTeams 是执行与协同房间，不是数据库。** Matrix 聊天只是输入。
3. **Langfuse 不是权威存储。** Langfuse 挂了，Case 仍可推进，只是诊断降级。
4. **企业原有监控不进内核。** MCP + Skill 让 Agent 自己接；Kernel 只收 `EvidenceReceipt`。

---

## 3. 角色（1 个 Intake + 6 个稳定职责）

六个角色是产品职责，不是六个常驻进程。按 Case 激活。再加一个专门的 Intake Worker。

| AgentTeams 位置 | 角色 | 使命 | 允许 | 禁止 |
|---|---|---|---|---|
| Manager 旁路 / Kernel | Controller / Executor | 状态、权限、Gate、审计、执行 | 写权威状态、执行已授权 WorkOrder | 用 LLM「觉得过了」就放行 |
| Team Leader | 质量官 Case Lead | 分诊、协调、升级 | 派 Task、写摘要、请求升级 | 改 Case 权威状态；持有发布凭据；兼任守门员 |
| Worker | Intake | 接收飞书 / GitHub / 低分 trace，填 Signal 与 Case 草稿 | 去重、结构化字段、标记 `NEEDS_CONTEXT` | 归因、打补丁、宣布已修复 |
| Worker | 采集员 Investigator | 把 Signal 变成证据包 | 绑 VersionSnapshot、写 EvidenceReceipt | 编造缺失证据；改被治理系统 |
| Worker（按需） | 归因师 Attribution | 可证伪调查 | 假设、实验计划、`INCONCLUSIVE` | 把猜测写成事实 |
| Worker（Hermes 优先） | 修复师 Builder = GAN 的 G | 最小候选修复 | 提交 CandidateRevision | 改验收标准；改冻结测试；自行验证通过；发布 |
| Worker（独立容器 / 独立房间） | 守门员 Verifier = GAN 的 D | 反向寻找失败 | 跑冻结 EvaluationPlan、写 GateReport | 修候选；看见 Builder 思维链；把失败改成 PASS |
| Worker | 案例官 Curator | 关闭后沉淀 | 写 RegressionAsset | 改进行中 Case |

**GAN 只约束 Builder vs Verifier**，不要做成两套 Team。Intake 是信号面，不是第二套编排。

Verifier 硬隔离：

- 独立 Worker，独立凭据，独立房间或至少独立 context
- 工具白名单：读 candidate digest、跑冻结 eval、写 GateReport
- 没有 repo write、没有 merge、没有改 AcceptanceSpec
- REJECT 后 Builder 只拿到 `GateReport`，必须新建 revision，禁止原位改

Attribution 不是每个 Case 的强制步骤。kotaemon 这类根因已在 Issue 中写明的，MVP 可跳过重型实验，只留一句话说明。

---

## 4. MVP 闭环（必须整条跑通）

目标：一条真实 Signal 进系统后，走完整原始流程，出口不是聊天记录，而是可导出的证据包。

```text
GitHub Issue（kotaemon #758）
→ Intake 立案（幂等）
→ 人类确认 AcceptanceSpec
→ Investigator 绑定 VersionSnapshot + 证据
→ Builder 提交 CandidateRevision
→ Verifier 隔离评测
      base 稳定复现失败
      candidate fail-to-pass
      regression / 空选择仍为空
      known-bad 候选被拦截
→ VERIFIED → VerifiedCandidate / NOT DEPLOYED
→ 本地草稿 PR（不合入、不 push）
→ Shadow 应用到本地 target → 独立回读
→ 回滚 drill → 再回读
→ Curator 写 RegressionAsset
→ 导出 evidence manifest
```

`VerifiedCandidate / NOT DEPLOYED` 是完整产品结果。草稿 PR 与本地回滚是参赛 Demo 必做的执行证据，不是生产发布。

### 4.1 第一个被治理应用

**Cinnamon/kotaemon**，真实 Issue：[#758 LightRAG the qa is not scoped](https://github.com/Cinnamon/kotaemon/issues/758)

现象：用户只选了 file A 做问答，LightRAG 仍混入 file B。

上游 commit：`ffe766f24d4ef8a91f8c61871d2b5a1930aa204e`

根因（Issue 作者已指出）：

- index 时 `insert(combined_doc)` 未带 file id
- query 只用 `file_ids[0]` 找 graph，查询时不再按选中文件过滤

MVP **不跑 kotaemon 全量 UI**。按 Adapter 原则，用可复现的失败模式做 Evaluation Adapter：

- `workloads/kotaemon-lightrag-scope/app/lightrag_store.py` 忠实复现「file_id 被忽略」
- 冻结 eval 在 `eval/`，Builder 工作区看不到测试文件
- VersionSnapshot 仍指向 kotaemon 的 repo + commit + Issue URL

这样 Gate 不依赖付费模型，也能证明 base fail → candidate pass → known-bad 拦截。

---

## 5. 权威对象与状态

Kernel 拥有这些对象。Agent 只能通过 typed Task 提交，Kernel 校验身份后再写。

| 对象 | 语义 |
|---|---|
| `AIApplication` | 被治理应用的轻量身份 |
| `Signal` | 飞书 / GitHub / Langfuse 低分 / 人工 |
| `Case` | 一次质量问题的权威工作空间 |
| `AcceptanceSpec` | 经人确认的预期、badcase、判定方式 |
| `VersionSnapshot` | 行为相关代码 / prompt / 模型 / 工具的不可变组合 |
| `EvidenceReceipt` | 来源、完整性、缺失项、digest |
| `InvestigationReport` | `SUPPORTED` / `REFUTED` / `INCONCLUSIVE` / `CONFOUNDED` |
| `CandidateRevision` | 绑定 exact base，密封后不可原位改 |
| `EvaluationPlan` / `GateReport` | 冻结验证与判定 |
| `VerifiedCandidate` | Gate `VERIFIED` 且明确 `NOT DEPLOYED` |
| `WorkOrder` / `ExternalOperation` | 草稿 PR、Shadow、回滚 |
| `Observation` | desired ≠ observed ≠ provider receipt |
| `RegressionAsset` | 关闭后的版本化资产 |

Case 状态（MVP）：

```text
awaiting_acceptance
→ investigating
→ proposing
→ verifying
→ verified | rejected | inconclusive
→ shadow_applied
→ rolled_back
→ closed
```

硬规则：

- 无人类 `AcceptanceSpec` 不得形成 VerifiedCandidate
- 只有 `agent:builder` 可提交 candidate
- 只有 `agent:verifier` 可提交 GateReport
- Builder 不得验证自己的 candidate
- required Gate 非 `PASS`/`VERIFIED` 时，任何角色不能把同一份失败改成通过
- 超时或未知外部结果记 `UNKNOWN`，先 reconcile，禁止盲重试

---

## 6. Langfuse（两件事，一张总线）

### 6.1 AgentMED 自身可审计

- 所有角色 prompt 进 Prompt Management，Attempt 带 prompt version
- 每次角色运行是一条 trace：工具、输入摘要、输出 artifact digest
- 人类能审查「当时质量官 / 修复师用的是哪一版提示词」

### 6.2 给其他 Agent 做诊断

没有目标应用（以及同伴 Agent）的 trace，Investigator / Attribution / Verifier 只能猜。

因此：

- AgentMED 各角色的 trace 可被后续角色查询（诊断同伴，而不是共享思维链全文）
- 被治理应用登记后自动创建 Langfuse project + OTLP 端点
- 若目标已有 OTEL：只改 exporter
- 若没有：由 Integrator / Intake 起草 instrumentation，人批后再合（MVP 对 kotaemon harness 直接埋点或跳过目标应用 live trace，用 Issue + 代码证据）

Langfuse 挂了：Kernel 继续工作；诊断工具返回 `NEEDS_CONTEXT`，不得伪造 span。

本机可复用已有栈：`~/langfuse`，UI `http://localhost:3001`。AgentMED 自己的 Postgres 不要占用 5433。

可观测对赛道是推荐项。方案写：Langfuse 为一等公民；OTEL 为交换格式；可再 export 到 AgentLoop。

---

## 7. Skill 清单（赛题必选项）

Skill 按可复用能力切，不按「一人一个空 Skill」。

| Skill | 谁用 | 输入 | 输出 | 失败 | 安全边界 |
|---|---|---|---|---|---|
| `ingest-signal` | Intake | URL / 飞书消息 / score | Signal + Case 草稿 | 源不可达 → `NEEDS_CONTEXT` | 不扩大权限 |
| `bind-version-snapshot` | Investigator | repo、commit、prompt 引用 | VersionSnapshot | 找不到 revision → 缺失字段公开 | 只读 |
| `query-langfuse` | Investigator / Attribution / Verifier | case_id、role、trace 过滤 | EvidenceReceipt | 无数据则声明缺失 | 只读；不把 Builder CoT 给 Verifier |
| `reproduce-badcase` | Investigator / Verifier | snapshot + spec | 复现记录 | 不稳定则 `INCONCLUSIVE` | 隔离目录 |
| `propose-candidate` | Builder | spec + snapshot + 源码 | CandidateRevision | 无法生成则停在 proposing | 不能碰 eval/ |
| `independent-verify` | Verifier | 密封 candidate | GateReport | 基建失败 → `ERROR` | 不能写 candidate |
| `draft-pr` | Controller 执行，Lead 只能请求 | VerifiedCandidate | 本地 patch / 草稿 PR | 无 token 则只留本地 patch | 不合入、不 push |
| `release-observe-rollback` | Controller | WorkOrder | Operation + Observation | 回读失败 → `UNKNOWN` | 需新鲜授权 |
| `curate-regression-asset` | Curator | 已关闭证据 | RegressionAsset | 缺 Gate 则拒绝 | 不改历史 |
| `connect-observability` | 任意 Worker，非内核 | 企业监控 MCP | EvidenceReceipt | 接不上则降级 | 密钥只存引用 |

MCP：GitHub 与 Langfuse 建议做成 MCP；MVP 可用 CLI 等价契约，文档写清迁 MCP 只需换协议。

---

## 8. AgentTeams 映射（评委要核验的那张图）

```yaml
# 逻辑结构，不是要求初赛就部署满集群
Team: agentmed-quality
  leader: quality-officer          # qwenpaw / openclaw
  workers:
    - intake                       # qwenpaw
    - investigator                 # qwenpaw
    - attribution                  # 按需
    - builder                      # hermes，可写代码
    - verifier                     # 独立 runtime / 独立房间
    - curator                      # qwenpaw
```

协同协议：

1. Manager 只把「有新 Signal / 有待办 Case」交给 Team Leader。
2. Leader 按 Kernel 返回的状态机派 Task，不自己 invent 下一步合法状态。
3. Worker 把产物写到共享文件系统（AgentTeams MinIO；本地 MVP 用 `data/artifacts/`），回传引用而非全文。
4. 成功以 Kernel 记录、Gate、或 target readback 为准。

本地开发可用 **同一套 Skill + 同一套 Kernel**，由确定性 playbook 按顺序唤醒各隔离角色。这是 Controller 的实现，不是绕过 AgentTeams。复赛交付把同一 Team YAML / Skill 包载入真实 AgentTeams。

---

## 9. 安全边界（MVP 也要成立）

始终人批或禁止：

- 生产发布、流量变更
- push / merge / 正式上游 PR
- 权限与凭据变更
- 钱、合规、未脱敏外发
- 不可逆动作

MVP 允许：

- 本地草稿 patch
- 本地 Shadow 文件替换 + 回滚 drill
- 人类 CLI `--accept` 确认 AcceptanceSpec

Secrets 只存引用。Worker 不持有 GitHub PAT / 模型主密钥；与 AgentTeams「工牌 token」模型对齐。

---

## 10. 非目标（MVP）

- 不跑 kotaemon 全量产品
- 不接真实飞书（Intake 接口预留，首条路径是 GitHub Issue）
- 不做 Trust Ledger 自动晋升
- 不做多租户 / HA
- 不把 AgentLoop 做成依赖
- 不让 Lead 投票代替 Gate
- 不把 VerifiedCandidate 说成已上线

---

## 11. 验收（First Verified Fix）

一次 `agentmed run --signal <kotaemon #758> --accept` 必须同时满足：

1. 同 Issue 重试不重复立案
2. AcceptanceSpec 有 `human:` principal
3. base eval 失败可复现
4. 至少一个 candidate `VERIFIED`，known-bad 被拦截
5. 草稿 PR 存在且未 merge
6. Shadow apply 的 desired / observed / receipt 分列
7. 回滚后 observed 回到 base
8. RegressionAsset 可被后续 Gate 引用
9. 全程 Langfuse 能看到至少 Intake / Builder / Verifier 三条角色 trace（Langfuse 不可用时明确降级，不假装有 trace）
10. 未经授权外部动作 = 0
