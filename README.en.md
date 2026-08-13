# AgentMED

[中文](README.md) · [English](README.en.md)

[![CI](https://github.com/er-s-an/AgentMED/actions/workflows/ci.yml/badge.svg)](https://github.com/er-s-an/AgentMED/actions/workflows/ci.yml)

Turn one failed AI-app outcome into an independently verified fix that is not deployed (`VerifiedCandidate / NOT DEPLOYED`), plus an evidence pack. The name is a mouthful. The part after the slash is the point.

Callers are other agents (CLI or HTTP). A human confirms the acceptance spec with `--accept` — agents may file, they may not nod along. Kernel owns state. [AgentTeams](https://github.com/agentscope-ai/AgentTeams) runs the loop. Langfuse stores traces.

The public contract is [`agentteams/agent-card.json`](agentteams/agent-card.json): file a problem, read status, fetch evidence. The full object model is in [`docs/SPEC.md`](docs/SPEC.md).

## Install

Python 3.11+ (3.13 preferred) and Docker. A live run also needs a Step Plan key.

```bash
git clone https://github.com/er-s-an/AgentMED.git
cd AgentMED
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Set `STEP_API_KEY` in `.env`. The base URL must be `https://api.stepfun.com/step_plan/v1`, not `/v1`.

```bash
REQUIRE_LIVE=false pytest -q
```

## Usage

Start dependencies. `live-stack` brings up Langfuse, the Kernel (including the LLM proxy), and AgentTeams:

```bash
./scripts/live-stack.sh    # Langfuse on :3001; Kernel on :8088; install and apply AgentTeams
agentmed doctor
# Kernel is already on :8088; `agentmed serve` only if you skipped live-stack
```

With `REQUIRE_LIVE=true`, `doctor` checks AgentTeams, Langfuse, Step Plan, Gate, and GitHub, and exits if any of them is down. It does not heal anything. It just points at the process on the floor.

```bash
agentmed run --signal https://github.com/Cinnamon/kotaemon/issues/758 --accept
agentmed case show CASE_ID
agentmed evidence export CASE_ID
```

`run` hands the Case to AgentTeams and waits on the Kernel. AgentTeams model calls go through Kernel `POST /v1/chat/completions` so prompts land in Langfuse (`GET /v1/governance/prompts` is the static catalog). `evidence export` writes a JSON manifest. Do not merge or `git push` the governed repo.

The current workload is [kotaemon #758](https://github.com/Cinnamon/kotaemon/issues/758): the user picked file A, the answer also read file B. We reproduce that one trick, not the rest of the product. Code is in `workloads/kotaemon-lightrag-scope/`.

## Layout

```text
src/agentmed/           Kernel, CLI, HTTP
agentteams/             team, workers, skills, agent-card.json
workloads/              evaluation adapters
docs/SPEC.md            objects and state machine
```

| Command / path | What it does |
|---|---|
| `agentmed run --signal URL` | File a problem and run the loop |
| `agentmed case show ID` | Read the Case |
| `agentmed evidence export ID` | Export evidence |
| `POST /v1/signals/ingest` | Same, over HTTP |
| `GET /v1/cases/{id}` | Status |
| `GET /v1/governance/prompts` | AgentMED role prompt catalog (audit) |
| `GET /v1/governance/traces` | AgentMED’s own LLM calls (Verifier does not see Builder CoT) |

A2A JSON-RPC is not served yet. The contract is on the table. The door goes up later.

<details>
<summary>Setup briefing for agents (copy the whole block)</summary>

```text
You are operating AgentMED (https://github.com/er-s-an/AgentMED).
Turn one AI-app failure into VerifiedCandidate / NOT DEPLOYED plus an evidence pack.
You are the calling agent. A human confirms the acceptance spec. Do not treat a pass as shipped.
A chat log is not evidence, same as a screenshot is not a receipt.

Environment
- macOS / Linux, Python 3.11+ (3.13 preferred), Docker Desktop
- Work from the repo root
- cp .env.example .env
- Required: STEP_API_KEY (Step Plan, https://platform.stepfun.com/interface-key)
- OPENAI_BASE_URL=https://api.stepfun.com/step_plan/v1
- AGENTMED_MODEL=step-3.7-flash
- Do not point a Plan key at https://api.stepfun.com/v1
- Langfuse is ~/langfuse, UI http://localhost:3001
  LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are in .env.example
- DATABASE_URL=sqlite:///./data/agentmed.db
- KERNEL_API_HOST=127.0.0.1  KERNEL_API_PORT=8088
- Public GitHub issues work without a token; private repos need GITHUB_TOKEN
- Do not commit .env

Install and unit tests
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
REQUIRE_LIVE=false pytest -q

Live loop
./scripts/live-stack.sh
# Langfuse :3001  admin@example.com / changeme123
# Element http://127.0.0.1:18088
# Gateway http://127.0.0.1:18080
# Dashboard http://127.0.0.1:13000
agentmed doctor
# Kernel already on :8088 after live-stack; agentmed serve only if you skipped it

File / inspect
agentmed run --signal https://github.com/Cinnamon/kotaemon/issues/758 --accept
agentmed case show CASE_ID
agentmed evidence export CASE_ID

HTTP (Kernel :8088, header X-AgentMED-Principal)
POST /v1/signals/ingest          JSON {"url":"<github issue>"}   principal=agent:intake
POST /v1/cases/{id}/accept       principal must start with human:
GET  /v1/cases/{id}
GET  /v1/cases/{id}/evidence
GET  /v1/governance/prompts      principal=agent:lead (Verifier does not get Builder template bodies)
GET  /v1/governance/traces

Contract
- Public skills in agentteams/agent-card.json: report-quality-problem, get-case-status, fetch-verified-outcome
- Do not call internal Builder / Verifier skills
- Do not merge or git push the governed app
- Do not forge Langfuse spans; if data is missing, return NEEDS_CONTEXT
- playbook / golden-patch is not a live success
- First demo: kotaemon#758, workload=workloads/kotaemon-lightrag-scope
- Details: docs/SPEC.md
```

</details>

## License

Apache-2.0. See `LICENSE`. CI runs `REQUIRE_LIVE=false` on Python 3.11 and 3.13.
