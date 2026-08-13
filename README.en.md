# AgentMED

[中文](README.md) · [English](README.en.md)

[![CI](https://github.com/er-s-an/AgentMED/actions/workflows/ci.yml/badge.svg)](https://github.com/er-s-an/AgentMED/actions/workflows/ci.yml)

Another agent hands AgentMED a bad outcome. A person confirms what “fixed” means. A team inside investigates, patches, and checks the patch. A pass still does not ship. What you get is a `VerifiedCandidate / NOT DEPLOYED` plus an evidence pack.

The caller is an A2A peer or an agent that can run a CLI. GitHub issues, low Langfuse scores, and Feishu messages are evidence, not the front door.

Objects, the state machine, and acceptance checks live in [`docs/SPEC.md`](docs/SPEC.md).

## Outside vs inside

Callers stay outside our rooms. They read [`agentteams/agent-card.json`](agentteams/agent-card.json) and do three things: file a problem, read case status, take the evidence pack. Builder and Verifier skills are not on the card.

Those three calls hit Kernel HTTP and the `agentmed` CLI today. `run --signal <GitHub URL>` is a shortcut — the issue link is stored as an evidence ref. A2A `message/send` is the same contract; the JSON-RPC server is not up yet.

A human only signs. `--accept` records a `human:` principal. The calling agent cannot sign for them and cannot write a Gate.

Inside, three pieces stay separate:

- **Kernel** (`:8088`) owns the Case, the Gate, and the audit log. An agent saying “done” does not count.
- **AgentTeams** does the work. The Manager hands a pending Case to the quality officer; Workers take steps the Kernel allows.
- **Langfuse** (`:3001`) keeps traces. If it is down the Case can still move. Missing data is `NEEDS_CONTEXT`; we do not invent spans.

Company monitors stay out of the Kernel. The `connect-observability` skill only files an `EvidenceReceipt`.

A Case looks like this:

```text
report → human confirms AcceptanceSpec → bind the version and evidence
→ Builder submits a sealed patch → Verifier runs isolated eval
→ on pass: VerifiedCandidate / NOT DEPLOYED
→ local draft patch, shadow, rollback (desired / observed / receipt kept apart)
→ Curator writes a RegressionAsset and we export the evidence
```

The Verifier needs all three: the old code still fails, the new code passes, and a known-bad patch is rejected. The quality officer does not vote the Gate through. After REJECT the Builder files a new revision; the sealed one stays sealed.

Roles wake up per Case. The team is [`agentteams/team.yaml`](agentteams/team.yaml); skills are under [`agentteams/skills/`](agentteams/skills/README.md). Every call sends `X-AgentMED-Principal`. Builder and Verifier cannot see each other’s rooms (`denyPeerMentions`).

| Who | Job |
|---|---|
| Intake | Turn a report into a Signal / Case |
| Quality officer | Dispatch from Kernel state; never write that state |
| Investigator | Bind the version, collect evidence |
| Attribution | Only claim what can be falsified; skip if the issue already names the cause |
| Builder | Smallest patch; no `eval/`, no self-verify |
| Verifier | Frozen tests only, then a GateReport |
| Kernel | State changes and authorized draft-PR / shadow / rollback |

## The first governed failure

[kotaemon #758](https://github.com/Cinnamon/kotaemon/issues/758): the user selected file A, LightRAG still mixed in file B. Commit `ffe766f24d4ef8a91f8c61871d2b5a1930aa204e`.

We do not run the full kotaemon UI. The failure is reproduced under `workloads/kotaemon-lightrag-scope/`. Tests live in `eval/`; the Builder cannot see them. The snapshot still points at the real repo, commit, and issue.

The live path is a real AgentTeams cluster. The in-repo playbook and golden-patch path do not count as a successful run.

## Run it

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # STEP_API_KEY is a Step Plan key, not /v1
REQUIRE_LIVE=false pytest -q
```

For a full loop, AgentTeams, Langfuse, Step Plan, Gate, and GitHub all need to be up:

```bash
./scripts/live-stack.sh       # Langfuse on :3001; applies agentteams/
agentmed doctor
agentmed serve                # Kernel on :8088
```

```bash
agentmed run --signal https://github.com/Cinnamon/kotaemon/issues/758 --accept
agentmed case show CASE_ID
agentmed evidence export CASE_ID
```

`run` hands the work to the AgentTeams Manager and waits on the Kernel Case. `evidence export` writes a manifest, not a chat log. The CLI entrypoint is `agentmed` → `agentmed.cli:app`.

With `REQUIRE_LIVE=true`, `doctor` checks those five dependencies and fails if any of them is down.

## Don’t

No merge, no `git push` of the governed repo, no pretending this is a production release. Local patches, a shadow apply plus rollback, and a human `--accept` are fine.

Keep secrets as references. Workers do not hold a GitHub PAT or the model master key. Do not commit `.env`.

Out of scope for now: the full kotaemon product, live Feishu, multi-tenant, AgentLoop as a dependency, auto-promoting a candidate to production.

Langfuse is the review plane. OTEL is the interchange format; we can export to AgentLoop later.

## CI and license

GitHub Actions runs `REQUIRE_LIVE=false` tests on Python 3.11 and 3.13. First-party skills need an executable `scripts/run.sh`. The official Langfuse skill stays an unmodified vendor copy. There is no deploy CD; the live stack is local Docker.

Apache-2.0. See `LICENSE`.
