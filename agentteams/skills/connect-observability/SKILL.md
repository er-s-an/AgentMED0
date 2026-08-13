---
name: connect-observability
description: Optional enterprise-monitor connector (MCP). Returns EvidenceReceipt; never part of Kernel.
assign_when: Any Worker needs extra telemetry from an existing enterprise stack and Kernel should only store a receipt.
---

# connect-observability

Execute via `agentmed` CLI / Kernel API. Matrix chat is not source of truth.

## Purpose

Let Agents attach to **existing** enterprise monitors (not a second observability product). Kernel does not embed these systems; it only accepts `EvidenceReceipt`.

This skill is **not** Kernel. Official review plane remains Langfuse; OTEL is the interchange; AgentLoop export is optional later.

## Inputs

- MCP / CLI equivalent for the enterprise monitor
- `case_id` and query window
- Credential **references** (never raw master keys in Worker soul)

## Outputs

- `EvidenceReceipt`
- Degradation note if the monitor is unreachable

## When to call

When GitHub + Langfuse are not enough and the org already has monitors. Skip in the kotaemon #758 MVP if unused.

## Dependencies

- External MCP (or CLI-equivalent contract; migrating to MCP is a protocol swap)
- Not required for Kernel Case progress

## Failure handling

- Unreachable → degrade; Kernel continues
- Do not forge metrics

## Security boundary

Secrets as references only. No Kernel privilege expansion. Receipts are evidence, not Case state.

## Which Agent uses it

Any **Worker** (typically Investigator). Never the Kernel / Controller as a built-in dependency.
