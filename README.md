# AgentMED

[中文](README.md) · [English](README.en.md)

[![CI](https://github.com/er-s-an/AgentMED/actions/workflows/ci.yml/badge.svg)](https://github.com/er-s-an/AgentMED/actions/workflows/ci.yml)

把 AI 应用的一次失败，收成经过独立验证、默认不上线的修复候选（`VerifiedCandidate / NOT DEPLOYED`），并留下证据包。斜杠后面那半句才是重点。

来报案的是别的 Agent。人用 `--accept` 确认怎样算修好——Agent 可以报案，不能替人点头。状态在 Kernel，活由 [AgentTeams](https://github.com/agentscope-ai/AgentTeams) 去干，trace 留在 Langfuse。

外面只做三件事：报案、查状态、取走证据。合同在 [`agentteams/agent-card.json`](agentteams/agent-card.json)。对象和状态机在 [`docs/SPEC.md`](docs/SPEC.md)。

## 安装

Python 3.11+（推荐 3.13）、Docker。跑闭环还要一份模型 key。

```bash
git clone https://github.com/er-s-an/AgentMED.git
cd AgentMED
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

编辑 `.env`，填上 `STEP_API_KEY`。

```bash
REQUIRE_LIVE=false pytest -q
```

## 用法

```bash
./scripts/live-stack.sh
agentmed doctor
agentmed serve
```

`doctor` 只看依赖齐不齐。齐了再跑：

```bash
agentmed run --signal https://github.com/Cinnamon/kotaemon/issues/758 --accept-adapter-defaults
agentmed case show CASE_ID
agentmed evidence export CASE_ID
```

`run` 把 Case 交给 AgentTeams，然后等 Kernel。导出的是证据包，不是聊天记录。不要 merge，也不要 `git push` 被治理的仓库。

现在用来演示的是 [kotaemon #758](https://github.com/Cinnamon/kotaemon/issues/758)：只选了 file A，答案里却混进 file B。我们只复现这一件。代码在 `workloads/kotaemon-lightrag-scope/`。

## 结构

```text
src/agentmed/           Kernel、CLI、HTTP
agentteams/             Team、Worker、Skill、agent-card.json
workloads/              被治理失败的 Adapter
docs/SPEC.md            对象和状态机
```

<details>
<summary>给 Agent 的配置说明（整段复制）</summary>

```text
你在操作 AgentMED（https://github.com/er-s-an/AgentMED）。
把一次 AI 应用失败收成 VerifiedCandidate / NOT DEPLOYED，外加证据包。
你是调用方 Agent。人确认验收标准。不要当已经上线。

仓库根目录工作。cp .env.example .env，填 STEP_API_KEY。不要提交 .env。

python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
REQUIRE_LIVE=false pytest -q

./scripts/live-stack.sh
agentmed doctor
agentmed serve

agentmed run --signal https://github.com/Cinnamon/kotaemon/issues/758 --accept-adapter-defaults
agentmed case show CASE_ID
agentmed evidence export CASE_ID

外场技能见 agentteams/agent-card.json。不要 merge，不要 git push 被治理的应用。
细节：docs/SPEC.md
```

</details>

## 许可

Apache-2.0，见 `LICENSE`。
