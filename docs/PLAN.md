# AgentMED 落地 Plan

> 配套文档：`docs/SPEC.md`  
> 状态：已确认，施工中。仓库 `/Users/tencent_go/AgentMED`。

---

## 1. 仓库形态（确认后执行）

```text
AgentMED/
  README.md
  pyproject.toml                 # package: agentmed, CLI: agentmed
  docker-compose.yml             # 仅 AgentMED Postgres；Langfuse 复用 ~/langfuse
  src/agentmed/                  # Kernel / CLI / API / team playbook
  agentteams/                    # 参赛用声明式资源
    team.yaml
    workers/*.yaml
    skills/*/SKILL.md
  workloads/kotaemon-lightrag-scope/
    app/lightrag_store.py        # 复现 #758
    eval/                        # 冻结测试，Builder 不可见
  docs/SPEC.md
  docs/PLAN.md
  tests/
```

技术选型（MVP）：

| 层 | 选择 | 原因 |
|---|---|---|
| Kernel | Python 3.13 + SQLAlchemy | 本机已有 3.13；Langfuse SDK 成熟 |
| API | FastAPI，薄封装 Kernel | PRD：HTTP 是 canonical |
| CLI | Typer | `agentmed run` / `case show` / `evidence export` |
| LLM | OpenAI 兼容，默认 `gpt-4o-mini` | 环境已有 `OPENAI_API_KEY` |
| 执行面 | AgentTeams YAML + Skill；本地用同一 Kernel 的确定性 playbook 唤醒隔离角色 | 复赛可加载真实 AgentTeams |
| 审查面 | Langfuse self-host `localhost:3001` | 审计 + 诊断 |
| 权威库 | SQLite 先跑通，`DATABASE_URL` 可换 Postgres | 十分钟本地闭环；compose 提供 Postgres |

不在 MVP 引入第二套 Agent 框架（LangGraph / Crew 等）。

---

## 2. 阶段

### 阶段 0 — 改名与冻结边界（0.5 天）

- 目录、包、CLI、环境变量、audit principal 全部改为 AgentMED / `agentmed`
- 删除或改写一切对外 AgentMED 字样
- 领域对象 `Case` 保留

### 阶段 1 — Kernel 可测（1 天）

单测覆盖：

- Signal 幂等
- 非人类不能确认 AcceptanceSpec
- 非 Builder 不能交 candidate
- 非 Verifier 不能交 Gate
- Builder 不能验证自己
- `VERIFIED` 才产生 `VerifiedCandidate.status = NOT_DEPLOYED`
- 回滚不删除 Shadow 的历史 Operation

交付：`pytest tests/test_kernel.py` 全绿。

### 阶段 2 — kotaemon Gate（0.5 天）

- base 源码使 `test_file_scope` 失败
- 正确 candidate 使它通过，且 `test_empty_selection` 仍过
- known-bad（只存 file_id、query 仍返回全部）必须失败
- Builder 工作区不含 `eval/`

交付：不调用 LLM 也能跑 Gate。

### 阶段 3 — 隔离角色 + Langfuse（1 天）

确定性 playbook 顺序唤醒：

1. Intake（LLM 结构化 Issue；失败则确定性 fallback 填字段）
2. 人类 `--accept`
3. Investigator
4. Attribution 跳过并写明原因
5. Builder（只得源码 + spec + Issue，不得测试文件）
6. Verifier（只得 candidate + 冻结 eval 结果，不得 Builder CoT）
7. REJECT 则 Builder 再来一轮，只得 GateReport
8. VERIFIED 后 Controller 做草稿 PR、Shadow、回滚
9. Curator

每角色独立 messages / 独立 tool 白名单 / 独立 Langfuse span。  
Playbook 是 Controller，不是「再做一个 Lead 来改状态」。

交付：Langfuse 里能按 role tag 把三条以上 trace 点开。

### 阶段 4 — CLI 与证据导出（0.5 天）

```text
agentmed run --signal https://github.com/Cinnamon/kotaemon/issues/758 --accept
agentmed case show <id>
agentmed evidence export <id>
```

`--accept` 表示人类确认 Intake 起草的 spec，principal 记 `human:cli`。

### 阶段 5 — AgentTeams 参赛包（0.5 天）

- `agentteams/team.yaml` + 各 Worker YAML（identity / soul / skills）
- 每个 Skill 的 `SKILL.md`：输入输出、调用条件、失败、安全边界
- README：如何用 `agt apply` 载入；本地无集群时 playbook 等价

初赛 PPT 用这份映射；复赛再要求集群里真跑。

### 阶段 6 — 一次真人 Demo 录像级跑通（0.5 天）

用真实 `OPENAI_API_KEY` 跑阶段 4。记录：

- 耗时、token、阻塞点
- Gate 是否拦住 known-bad
- 未授权外部动作是否为 0

若 Builder 模型改坏文件：允许一轮 REJECT→重试；仍失败则 Demo 展示 `REJECTED` 也算闭环（Spec 要求至少一个 VERIFIED，必要时用确定性正确补丁作为对照 candidate，但必须标明这是对照，不是 Verifier 放水）。

---

## 3. 建议的文件落地顺序（确认后）

1. 改名  
2. `kernel.py` 定稿 + 单测  
3. `workloads/...` + `gate.py`  
4. `team/playbook.py` + `llm.py` + `observability.py`  
5. `cli.py`  
6. `agentteams/`  
7. README 里的一键 Demo  

不要先做 Web Console、飞书、Nacos、Higress。

---

## 4. 与赛程的关系

| 日期 | 你 | 实现（Spec 确认后） |
|---|---|---|
| 8/13–8/16 初赛 | 你做 PPT | 若确认够早：阶段 1–2 可开始；初赛不强制代码 |
| PPT 内容 | 场景、Agent Identity、AgentTeams 映射、Skill 表、Langfuse 双层、审批回滚、开源计划 | Spec 第 3、7、8 节可直接搬 |
| 8/25–9/3 复赛 | 路演材料 | 阶段 3–6 必须可运行，并给出 AgentTeams 代码包 |

初赛可以没有可执行包。复赛没有 AgentTeams 映射会被扣「协同基点」分。

---

## 5. 风险

| 风险 | 处理 |
|---|---|
| kotaemon 全量跑不起来 | 已选择失败模式 harness，不跑全量 UI |
| AgentTeams 本机太重 | MVP 用 playbook + 同构 Skill；复赛再挂集群 |
| Langfuse 没起来 | 降级并在 evidence 里写 missing；不伪造 |
| Builder 改不出正确补丁 | 一轮重试；对照 candidate 仅用于证明 Gate 真能 PASS，展示时标明 |
| 产品名与目录不一致 | 阶段 0 先改名，避免 PPT 和仓库对不上 |

---

## 6. 请你拍板的点

1. **产品名 AgentMED** 是否还要对外解释全称？不解释就只当专有名。  
2. **仓库是否立即从 `AgentMED/` 改名为 `AgentMED/`？** 建议是。  
3. **首条 Signal 是否锁定 kotaemon #758？** 换 Issue 会改 Gate Adapter。  
4. **MVP 是否包含本地草稿 PR + 回滚 drill？** Spec 按「包含」写的。  
5. **飞书是否初赛只出现在架构图、复赛再接？** 建议是。  
6. **Spec 确认后是否按阶段 0 开始改名和 Kernel 单测？** 你点头我才动代码。

确认方式：直接回这 6 条的决定即可。在此之前不推进开发。
