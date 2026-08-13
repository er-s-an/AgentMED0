# AgentTeams skills

`copy_skills()` copies every directory here into the AgentTeams worker-skills workspace.

## Official Langfuse skill

- **`langfuse/`** — vendored unmodified from `npx skills add langfuse/skills --skill langfuse`. Review-plane how-to: instrumentation, traces, CLI, docs. Do not rewrite `SKILL.md` into an AgentMED client.
- Workers must **not** be assigned the official `langfuse` skill as an executable Kernel client.
- Pin: repo-root `skills-lock.json`. Install cache `.agents/skills/langfuse/` is gitignored; the pack copy is what ships.

## AgentMED wrappers only

Thin wrappers talk to Kernel HTTP. Workers must not hold Langfuse master keys.

- **`provision-langfuse`** — register / provision the review-plane project via Kernel
- **`query-langfuse`** — read traces; declare missing instead of forging spans
- **`ingest-langfuse`** — ingest a low-score / trace signal through Kernel

## Boundaries

- Kernel is source of truth. Langfuse is not the Case DB.
- AgentMED's own prompts (worker soul / skills / live LLM messages) are captured for governance: static catalog via `provision-langfuse` / `GET /v1/governance/prompts`; live calls via Kernel `POST /v1/chat/completions`.
- Verifier never gets Builder chain-of-thought (see `team.yaml` `denyPeerMentions` and `query-langfuse`).
- **`connect-observability`** is the enterprise-monitor entry; Kernel only stores `EvidenceReceipt`. No Aliyun CMS. Nacos / cloud Skills portal are recommended, not required.
