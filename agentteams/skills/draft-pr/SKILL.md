---
name: draft-pr
description: Materialize a local patch / draft PR from VerifiedCandidate. No merge, no push.
assign_when: Kernel has VerifiedCandidate / NOT DEPLOYED and a human-authorized WorkOrder requests a draft PR.
---

# draft-pr

Execute via `agentmed` CLI / Kernel API. Matrix chat is not source of truth.

## Purpose

Turn a verified candidate into a **local** patch or draft PR as execution evidence. This is not an upstream publish.

## Inputs

- `VerifiedCandidate` (`NOT DEPLOYED`)
- Authorized `WorkOrder`
- Target repo path (local)

## Outputs

- Local patch and/or draft PR artifact
- `ExternalOperation` receipt

## When to call

After Gate `VERIFIED`, when demo evidence needs a PR-shaped artifact. Lead may **request**; Controller **executes**.

## Dependencies

- Controller / Executor (deterministic Kernel path)
- Optional GitHub token; without it, keep a local patch only

## Failure handling

- Missing token → local patch only; do not claim a hosted PR
- Unverified candidate → refuse

## Security boundary

No merge, no `git push`, no production PR. Fresh authorization required. Workers do not hold GitHub PAT.

## Which Agent uses it

**Controller / Executor**. Quality officer may request only. Not Builder, not Verifier.
