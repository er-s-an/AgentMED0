# AgentMED

[中文](README.md) · [English](README.en.md)

[![CI](https://github.com/er-s-an/AgentMED/actions/workflows/ci.yml/badge.svg)](https://github.com/er-s-an/AgentMED/actions/workflows/ci.yml)

Turn one failed AI-app outcome into an independently verified fix that is not deployed (`VerifiedCandidate / NOT DEPLOYED`), plus an evidence pack. The part after the slash is the point.

Callers are other agents. A human confirms what “fixed” means with `--accept` — agents may file, they may not nod along. Kernel owns state. [AgentTeams](https://github.com/agentscope-ai/AgentTeams) does the work. Langfuse keeps traces.

Outside, there are three moves: file a problem, read status, take the evidence. The contract is [`agentteams/agent-card.json`](agentteams/agent-card.json). Objects and the state machine live in [`docs/SPEC.md`](docs/SPEC.md).

## Install

Python 3.11+ (3.13 preferred) and Docker. A live loop also needs a model key.

```bash
git clone https://github.com/er-s-an/AgentMED.git
cd AgentMED
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Put `STEP_API_KEY` in `.env`.

```bash
REQUIRE_LIVE=false pytest -q
```

## Usage

```bash
./scripts/live-stack.sh
agentmed doctor
agentmed serve
```

`doctor` only checks that dependencies are up. Then:

```bash
agentmed run --signal https://github.com/Cinnamon/kotaemon/issues/758 --accept-adapter-defaults
agentmed case show CASE_ID
agentmed evidence export CASE_ID
```

`run` hands the Case to AgentTeams and waits on the Kernel. The export is an evidence pack, not a chat log. Do not merge or `git push` the governed repo.

The demo is [kotaemon #758](https://github.com/Cinnamon/kotaemon/issues/758): the user picked file A, the answer also read file B. We reproduce that one failure. Code is in `workloads/kotaemon-lightrag-scope/`.

## Layout

```text
src/agentmed/           Kernel, CLI, HTTP
agentteams/             team, workers, skills, agent-card.json
workloads/              evaluation adapters
docs/SPEC.md            objects and state machine
```

<details>
<summary>Setup briefing for agents (copy the whole block)</summary>

```text
You are operating AgentMED (https://github.com/er-s-an/AgentMED).
Turn one AI-app failure into VerifiedCandidate / NOT DEPLOYED plus an evidence pack.
You are the calling agent. A human confirms the acceptance spec. Do not treat a pass as shipped.

Work from the repo root. cp .env.example .env and set STEP_API_KEY. Do not commit .env.

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

Public skills are in agentteams/agent-card.json. Do not merge or git push the governed app.
Details: docs/SPEC.md
```

</details>

## License

Apache-2.0. See `LICENSE`.
