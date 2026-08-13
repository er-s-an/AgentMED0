# AgentMED

[中文](README.md) · [English](README.en.md)

[![CI](https://github.com/er-s-an/AgentMED/actions/workflows/ci.yml/badge.svg)](https://github.com/er-s-an/AgentMED/actions/workflows/ci.yml)

别的 Agent 把一次坏结果交给 AgentMED。人确认「怎样算修好」。里面一队 Agent 去查、改、验。验过了也不自动上线，只交出一份带证据的修复候选：`VerifiedCandidate / NOT DEPLOYED`。

来报案的是 A2A 对端，或会跑命令的 Agent。GitHub Issue、Langfuse 低分、飞书消息都只是证据，不是入口。

对象、状态机和验收写在 [`docs/SPEC.md`](docs/SPEC.md)。

## 外面怎么叫，里面怎么跑

外面的 Agent 不进我们的房间。它们读 [`agentteams/agent-card.json`](agentteams/agent-card.json)，只做三件事：报案、查状态、取走证据包。Builder / Verifier 的能力不写在 Card 上。

这三件事今天打到 Kernel HTTP 和 `agentmed` CLI。`run --signal <GitHub URL>` 只是图省事，Issue 链接按证据引用收。A2A 的 `message/send` 和 Card 是同一份合同，进程上还没挂 JSON-RPC。

人的位置只有签字：`--accept` 记 `human:`，报案的 Agent 不能代签，也不能写 Gate。

里面三块分开：

- **Kernel**（`:8088`）记 Case、过 Gate、写审计。Agent 自报不算数。
- **AgentTeams** 干活。Manager 把待办交给质量官，Worker 按 Kernel 允许的步骤走。
- **Langfuse**（`:3001`）留 trace。它挂了 Case 还能往下走，缺的证据标 `NEEDS_CONTEXT`，不要编 span。

企业自己的监控不进 Kernel，走 `connect-observability`，只收一张 `EvidenceReceipt`。

一条 Case 大致是：

```text
报案 → 人确认 AcceptanceSpec → 绑当时版本和证据
→ Builder 交密封补丁 → Verifier 隔离评测
→ 通过则 VerifiedCandidate / NOT DEPLOYED
→ 本地草稿 patch、Shadow、回滚（desired / observed / receipt 分开记）
→ 沉淀 RegressionAsset，导出 evidence
```

Verifier 要同时看到：旧代码稳定复现失败、新代码能过、故意写坏的 known-bad 过不了。质量官不投票代替 Gate。REJECT 之后只能交新 revision，不能改已经封住的那份。

角色按 Case 叫起来，不必六个常驻。Team 在 [`agentteams/team.yaml`](agentteams/team.yaml)，Skill 在 [`agentteams/skills/`](agentteams/skills/README.md)，调用都带 `X-AgentMED-Principal`。Builder 和 Verifier 互相看不到对方的房间（`denyPeerMentions`）。

| 谁 | 干什么 |
|---|---|
| Intake | 把报案收成 Signal / Case |
| 质量官 | 按 Kernel 状态派活，不改权威状态 |
| Investigator | 绑版本、收证据 |
| Attribution | 能证伪再下结论；Issue 里根因写明了就可以跳过 |
| Builder | 最小补丁；不碰 `eval/`，不自验 |
| Verifier | 只跑冻结测试，写 GateReport |
| Kernel | 改状态、跑已授权的草稿 PR / Shadow / 回滚 |

## 现在用来演示的那条

[kotaemon #758](https://github.com/Cinnamon/kotaemon/issues/758)：用户只选了 file A，LightRAG 仍混进 file B。commit 是 `ffe766f24d4ef8a91f8c61871d2b5a1930aa204e`。

整站 UI 我们没跑。复现放在 `workloads/kotaemon-lightrag-scope/`，测试在 `eval/`，Builder 拿不到测试文件。Snapshot 仍指向 kotaemon 的仓库、commit 和 Issue。

Live 路径是真实 AgentTeams。仓库里的 playbook / golden-patch 不算跑通。

## 怎么跑

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # STEP_API_KEY 用 Step Plan，不要填 /v1
REQUIRE_LIVE=false pytest -q
```

要跑通一整条，先把 AgentTeams、Langfuse、Step Plan、Gate、GitHub 都拉起来：

```bash
./scripts/live-stack.sh       # Langfuse :3001，并 apply agentteams/
agentmed doctor
agentmed serve                # Kernel :8088
```

```bash
agentmed run --signal https://github.com/Cinnamon/kotaemon/issues/758 --accept
agentmed case show CASE_ID
agentmed evidence export CASE_ID
```

`run` 把活交给 AgentTeams Manager，然后盯着 Kernel 的 Case。`evidence export` 写出的是 manifest，不是聊天记录。CLI 入口是 `agentmed` → `agentmed.cli:app`。

`REQUIRE_LIVE=true` 时 `doctor` 会查上面那五项，缺一项就失败。

## 别做的事

不要 merge，不要 `git push` 被治理的仓库，不要当生产已发布。可以留本地 patch、做一次 Shadow 再滚回去、用 `--accept` 签字。

密钥只放引用。Worker 不拿 GitHub PAT 和模型主密钥。`.env` 不要提交。

这次也不做：kotaemon 全量、真飞书、多租户、把 AgentLoop 当依赖、自动把候选晋升上线。

Langfuse 我们当审查面用。OTEL 是交换格式，以后可以再导到 AgentLoop。

## CI 和许可

GitHub Actions 在 Python 3.11 / 3.13 上跑 `REQUIRE_LIVE=false` 的测试。自有 skill 要有可执行的 `scripts/run.sh`；官方 Langfuse skill 保持原样。没有部署 CD，live 栈在本机 Docker。

Apache-2.0，见 `LICENSE`。
