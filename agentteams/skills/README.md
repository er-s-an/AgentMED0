# AgentTeams skills

`copy_skills()` copies every directory here into the AgentTeams worker-skills workspace.

## Official Langfuse skill

- **`langfuse/`** — vendored official skill (`npx skills add langfuse/skills --skill langfuse`). Review-plane how-to: instrumentation, traces, CLI, docs. Do not rewrite `SKILL.md` into an AgentMED client.
- Pin: repo-root `skills-lock.json`. Install cache `.agents/skills/langfuse/` is gitignored; the pack copy is what ships.

## AgentMED wrappers only

These talk to Kernel HTTP. Workers must not hold Langfuse master keys.

- **`provision-langfuse`** — register / provision the review-plane project via Kernel
- **`query-langfuse`** — read traces; declare missing instead of forging spans
- **`ingest-langfuse`** — ingest a low-score / trace signal through Kernel

## Boundaries

- Kernel is source of truth. Langfuse is not the Case DB.
- Verifier never gets Builder chain-of-thought (see `team.yaml` `denyPeerMentions` and `query-langfuse`).
- `connect-observability` is optional enterprise-monitor attachment later; do not invent Aliyun CMS or Nacos registration here.
