# AgentMED

[![CI](https://github.com/er-s-an/AgentMED/actions/workflows/ci.yml/badge.svg)](https://github.com/er-s-an/AgentMED/actions/workflows/ci.yml)

AgentMED turns one bad AI-app outcome into an independently verified, safely adoptable fix that can block recurrence.

**AgentMED** 让 AI 应用团队把一次坏结果，变成经过独立验证、可安全采用、并能防止复发的修复。它不是通用多 Agent 聊天框架，也不是第二套可观测平台：创造性工作（调查、起草候选）放在确定性 Kernel 的状态机、权限、Gate 和审计之下。

## Architecture

Three planes stay separate:

| Plane | System | Owns |
|---|---|---|
| Deterministic control | **Kernel** (`agentmed` CLI / HTTP) | Case state, gates, WorkOrders, audit. Agent self-report is not success. |
| Probabilistic execution | **AgentTeams** | Manager → quality officer (Team Leader) → Workers. Artifacts by reference (MinIO / `data/artifacts/`). |
| Review / diagnosis | **Langfuse** | Prompt versions and traces. Required in live mode (`REQUIRE_LIVE=true`). |

Enterprise monitors are **not** in Kernel. Agents attach them with the `connect-observability` Skill and Kernel only stores `EvidenceReceipt`.

CLI at most **dispatches** a GitHub signal over Matrix. AgentTeams then runs the loop; Kernel HTTP is the source of truth. The local playbook / golden-patch fallback is not a live success path.

## Roles (Intake + 6)

| AgentTeams | Role | Mission |
|---|---|---|
| Worker | Intake | GitHub / Feishu / low-score trace → Signal + Case draft |
| Team Leader | Quality officer | Triage, dispatch Kernel-legal Tasks, escalate. No Gate, no publish keys. |
| Worker | Investigator | Bind `VersionSnapshot`, evidence, reproduce bad case |
| Worker (on demand) | Attribution | Falsifiable investigation; skip when the Issue already states root cause |
| Worker | Builder | Minimal sealed `CandidateRevision`. Must not self-verify. |
| Worker (isolated) | Verifier | Frozen eval → `GateReport`. Never sees Builder CoT, never patches, never overrides FAIL. |
| Worker | Curator | After close, write `RegressionAsset` |

Controller / Executor is Kernel (not an LLM Worker): it writes authoritative state and runs authorized WorkOrders (`draft-pr`, local shadow, rollback).

## First demo

Governed app: [Cinnamon/kotaemon](https://github.com/Cinnamon/kotaemon) [issue #758](https://github.com/Cinnamon/kotaemon/issues/758) — LightRAG QA not scoped to the selected file.

MVP uses an Evaluation Adapter (`workloads/kotaemon-lightrag-scope`) rather than the full kotaemon UI. Snapshot still points at the kotaemon repo + commit + Issue URL. Success is `VerifiedCandidate / NOT DEPLOYED` plus local draft PR and rollback evidence — not production deploy.

## Quickstart

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # set STEP_API_KEY (Step Plan, not /v1)
REQUIRE_LIVE=false pytest -q
```

Live processes (all required when `REQUIRE_LIVE=true`):

```bash
# Langfuse + AgentTeams (needs STEP_API_KEY). Langfuse UI: http://localhost:3001
./scripts/live-stack.sh
agentmed doctor
agentmed serve   # Kernel HTTP on :8088
```

Then:

```bash
agentmed run --signal https://github.com/Cinnamon/kotaemon/issues/758 --accept
agentmed case show CASE_ID
agentmed evidence export CASE_ID
```

`--accept` records a human `AcceptanceSpec` (`human:` principal). `run` sends the request to the AgentTeams Manager (Matrix) and waits on Kernel Case state. Golden-patch fallback is disabled. `case show` prints Kernel state; `evidence export` writes the manifest (not a chat log).

CLI entrypoint: `agentmed` → `agentmed.cli:app`.

## Mapping to AgentTeams

Apply the pack in `agentteams/`:

- `team.yaml` — Team `agentmed-quality`, leader `quality-officer` (`role: team_leader`)
- `workers/*.yaml` — one Worker each
- `skills/*/SKILL.md` — reusable capabilities; effects go through Kernel HTTP
- `skills/README.md` — official `langfuse` vs AgentMED wrappers (`provision-langfuse`, `query-langfuse`, `ingest-langfuse`)

`scripts/live-stack.sh` installs a real AgentTeams cluster (controller + manager + workers) and applies `agentteams/`. Kernel owns state and Gate. AgentTeams owns execution. `agentmed doctor` fails unless AgentTeams, Langfuse, Step Plan, Gate, and GitHub intake are all live.

## CI

GitHub Actions runs unit tests and skill-script smoke tests on Python 3.11 and 3.13 with `REQUIRE_LIVE=false`. CI also checks that every first-party skill has an executable `scripts/run.sh` (Kernel HTTP + `X-AgentMED-Principal`) and that the official Langfuse skill stays an unmodified vendor copy. There is no deploy CD: the live stack is local Docker (AgentTeams + Langfuse + Kernel), not a hosted service.

## Safety (MVP)

Never merge, never `git push` the **governed app**, never production release, never irreversible cloud actions. Allowed: local patch, local shadow file replace, rollback drill, human `--accept`.

Secrets are references. Workers do not hold GitHub PAT or model master keys. Do not commit `.env`.

## License

Apache-2.0 (intent; see `LICENSE`).
