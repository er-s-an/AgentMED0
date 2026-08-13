# AgentMED

[中文](README.md) · [English](README.en.md)

[![CI](https://github.com/er-s-an/AgentMED/actions/workflows/ci.yml/badge.svg)](https://github.com/er-s-an/AgentMED/actions/workflows/ci.yml)

把 AI 应用的一次失败收成经过独立验证、默认不上线的修复候选（`VerifiedCandidate / NOT DEPLOYED`），并留下证据包。名字有点长，斜杠后面那半句才是重点。

调用方是别的 Agent（CLI 或 HTTP）。人用 `--accept` 确认验收标准——Agent 可以报案，不能替人点头。状态在 Kernel，执行在 [AgentTeams](https://github.com/agentscope-ai/AgentTeams)，trace 在 Langfuse。

对外合同见 [`agentteams/agent-card.json`](agentteams/agent-card.json)：报案、查状态、取证据。完整说明在 [`docs/SPEC.md`](docs/SPEC.md)。

## 安装

需要 Python 3.11+（推荐 3.13）、Docker。Live 还要 Step Plan key。

```bash
git clone https://github.com/er-s-an/AgentMED.git
cd AgentMED
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

编辑 `.env`，填 `STEP_API_KEY`。Base URL 必须是 `https://api.stepfun.com/step_plan/v1`，不要用 `/v1`。

```bash
REQUIRE_LIVE=false pytest -q
```

## 用法

先起依赖。`live-stack` 会拉起 Langfuse、Kernel（含 LLM 代理）和 AgentTeams：

```bash
./scripts/live-stack.sh    # Langfuse :3001，Kernel :8088，安装并 apply AgentTeams
agentmed doctor
# Kernel 已在 :8088；只有没跑 live-stack 时才需要 agentmed serve
```

`REQUIRE_LIVE=true` 时，`doctor` 会检查 AgentTeams、Langfuse、Step Plan、Gate、GitHub，缺一项就退出。它不治病，只告诉你哪台还没起来。

```bash
agentmed run --signal https://github.com/Cinnamon/kotaemon/issues/758 --accept
agentmed case show CASE_ID
agentmed evidence export CASE_ID
```

`run` 把 Case 交给 AgentTeams，然后等 Kernel。AgentTeams 的模型调用走 Kernel `POST /v1/chat/completions`，提示词进 Langfuse（`GET /v1/governance/prompts` 是静态目录）。`evidence export` 写出 JSON manifest。不要 merge，也不要 `git push` 被治理的仓库。

当前 workload 是 [kotaemon #758](https://github.com/Cinnamon/kotaemon/issues/758)：选了 file A，答案里混进 file B。我们只复现这一件，不陪整站一起熬。代码在 `workloads/kotaemon-lightrag-scope/`。

## 结构

```text
src/agentmed/           Kernel、CLI、HTTP
agentteams/             Team、Worker、Skill、agent-card.json
workloads/              被治理失败的 Adapter
docs/SPEC.md            对象和状态机
```

| 命令 / 路径 | 作用 |
|---|---|
| `agentmed run --signal URL` | 报案并跑闭环 |
| `agentmed case show ID` | 读 Case |
| `agentmed evidence export ID` | 导出证据 |
| `POST /v1/signals/ingest` | 同上，HTTP |
| `GET /v1/cases/{id}` | 状态 |
| `GET /v1/governance/prompts` | AgentMED 各角色静态提示词（审核） |
| `GET /v1/governance/traces` | AgentMED 自己的 LLM 调用（Verifier 看不到 Builder CoT） |

A2A JSON-RPC 还没挂到进程上。合同先印好了，门过两天再装。

<details>
<summary>给 Agent 的配置说明（整段复制）</summary>

```text
你在操作 AgentMED（https://github.com/er-s-an/AgentMED）。
把一次 AI 应用失败收成 VerifiedCandidate / NOT DEPLOYED，外加证据包。
你是调用方 Agent。人确认验收标准。不要当已经上线。
聊天记录不是证据，就像截图不是发票。

环境
- macOS / Linux，Python 3.11+（推荐 3.13），Docker Desktop
- 仓库根目录工作
- cp .env.example .env
- 必填 STEP_API_KEY（Step Plan，https://platform.stepfun.com/interface-key）
- OPENAI_BASE_URL=https://api.stepfun.com/step_plan/v1
- AGENTMED_MODEL=step-3.7-flash
- 不要把 Plan key 配到 https://api.stepfun.com/v1
- Langfuse 复用 ~/langfuse，UI http://localhost:3001
  LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY 见 .env.example
- DATABASE_URL=sqlite:///./data/agentmed.db
- KERNEL_API_HOST=127.0.0.1  KERNEL_API_PORT=8088
- GitHub 公开 Issue 可不填 token；私有仓库设 GITHUB_TOKEN
- 不要提交 .env

安装与自检
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
REQUIRE_LIVE=false pytest -q

Live（要跑闭环时）
./scripts/live-stack.sh
# Langfuse :3001  admin@example.com / changeme123
# Element http://127.0.0.1:18088
# Gateway http://127.0.0.1:18080
# Dashboard http://127.0.0.1:13000
agentmed doctor
# Kernel already on :8088 after live-stack; agentmed serve only if you skipped it

报案 / 查询
agentmed run --signal https://github.com/Cinnamon/kotaemon/issues/758 --accept
agentmed case show CASE_ID
agentmed evidence export CASE_ID

HTTP（Kernel :8088，Header: X-AgentMED-Principal）
POST /v1/signals/ingest          JSON {"url":"<github issue>"}   principal=agent:intake
POST /v1/cases/{id}/accept       principal 必须以 human: 开头
GET  /v1/cases/{id}
GET  /v1/cases/{id}/evidence
GET  /v1/governance/prompts      principal=agent:lead（Verifier 看不到 Builder 模板正文）
GET  /v1/governance/traces

合同与边界
- 外场技能见 agentteams/agent-card.json：report-quality-problem、get-case-status、fetch-verified-outcome
- 不要调用 Builder / Verifier 的内部 skill
- 不要 merge，不要 git push 被治理应用
- 不要伪造 Langfuse span；没有数据就 NEEDS_CONTEXT
- playbook / golden-patch 不算 live 成功
- 第一条 demo：kotaemon#758，workload=workloads/kotaemon-lightrag-scope
- 细节：docs/SPEC.md
```

</details>

## 许可

Apache-2.0，见 `LICENSE`。CI 在 Python 3.11 / 3.13 上跑 `REQUIRE_LIVE=false`。
