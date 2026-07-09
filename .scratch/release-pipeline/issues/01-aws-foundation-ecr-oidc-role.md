# AWS foundation: ECR repos + OIDC trust + scoped push role

Status: ready-for-human

Spec: [ADR 0019](../../../docs/adr/0019-release-pipeline-build-off-host.md) — Auth, Images sections.

## What to build

The one-time AWS-side trust + registry that lets GitHub Actions push images with no long-lived credentials. No application change — this is the foundation slices 02–06 build on.

- Three ECR repos in `ap-south-1`: `ocpp-backend`, `ocpp-frontend`, `ocpp-nginx`, each with a lifecycle policy retaining ~20 most-recent images.
- An IAM **OIDC identity provider** for `token.actions.githubusercontent.com` (audience `sts.amazonaws.com`).
- An IAM **role** assumable only via that provider, **trust scoped to `repo:jeethjoseph/ocpp-server:*`**, whose permission policy is limited to **ECR auth + push on the three `ocpp-*` repos and nothing else**.

*HITL: privileged AWS account change; the trust policy must be reviewed before merge (a loose `sub` condition would let other repos assume the role).*

## Acceptance criteria

- [ ] `ocpp-backend`, `ocpp-frontend`, `ocpp-nginx` ECR repos exist in `ap-south-1` with a lifecycle policy keeping ~20 images.
- [ ] IAM OIDC provider for `token.actions.githubusercontent.com` (aud `sts.amazonaws.com`) exists.
- [ ] IAM role trust policy restricts `sub` to `repo:jeethjoseph/ocpp-server:*` (no wildcard owner) and asserts the audience condition; permission policy grants only ECR auth/push on the three repos.
- [ ] A throwaway GHA job (`permissions: id-token: write`) using `aws-actions/configure-aws-credentials` assumes the role and successfully runs `aws ecr get-login-password` + `aws ecr describe-repositories`.
- [ ] No long-lived AWS access keys are stored anywhere in GitHub.
- [ ] Trust policy reviewed and approved by a human.

## Blocked by

None — can start immediately.
