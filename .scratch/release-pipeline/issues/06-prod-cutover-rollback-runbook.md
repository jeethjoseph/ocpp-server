# Prod cutover: `deploy`-branch build, prod override, `make prod-release`, rollback runbook

Status: ready-for-human

Spec: [ADR 0019](../../../docs/adr/0019-release-pipeline-build-off-host.md) — Release trigger & gating, Consequences sections.

## What to build

Extend the proven staging pipeline to **prod**, gated and human-triggered. A push to `deploy` builds images but **never auto-releases**; a human promotes a specific, staging-validated SHA.

- GHA builds + pushes SHA-tagged images on push to `deploy` (no release step). Confirm the OIDC trust permits the `deploy`-branch workflow.
- Prod compose override references all three images by SHA.
- `make prod-release SHA=<sha>` performs `pull → one-shot migrate → up` for the chosen SHA, run by a human over SSM.
- `prod-deploy` / `prod-rebuild` (build-on-host) deprecated.
- Rollback runbook: re-point prod to a prior SHA tag + `up -d` (seconds), with the expand/contract schema-safety note (the prior image always tolerates the current schema).

*HITL: prod cutover — explicit human gating, change review, and a watched first release.*

## Acceptance criteria

- [ ] Push to `deploy` builds + pushes SHA-tagged images and does **not** auto-release.
- [ ] OIDC role assumption works from the `deploy`-branch workflow.
- [ ] Prod override references all three CI images by SHA; `make prod-release SHA=<sha>` runs `pull → one-shot migrate → up` for a chosen SHA.
- [ ] `prod-deploy` / `prod-rebuild` (build-on-host) are deprecated with a notice pointing to `prod-release`.
- [ ] A prod release is performed and verified running the CI-built images at the expected SHA, with no `docker build` on the host.
- [ ] Rollback runbook documents retag-prior-SHA + `up -d`, with the schema-safety caveat; a rollback is rehearsed (e.g. on staging or a dry run).

## Blocked by

- [04 — nginx in CI + full staging cutover](04-nginx-and-full-staging-cutover.md)
- [05 — Migration step in the release flow + expand/contract checklist](05-migrate-step-expand-contract.md)
