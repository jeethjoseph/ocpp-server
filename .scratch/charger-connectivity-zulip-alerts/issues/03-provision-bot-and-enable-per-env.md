# Slice 3 — Provision Zulip bot & enable alerts per environment

Status: ready-for-human
Type: HITL

## Parent

PRD: `.scratch/charger-connectivity-zulip-alerts/PRD.md`

## What to build

Operational rollout of the (dark-shipped) charger-connectivity alerts. No application code changes — this is provisioning the Zulip side and flipping the flag per environment.

1. In Zulip, create a **Generic bot**; capture its **bot email** and **API key**.
2. Note the Zulip **site URL** and create/choose the target **channel**; subscribe the bot to it.
3. Populate `ZULIP_SITE`, `ZULIP_BOT_EMAIL`, `ZULIP_BOT_API_KEY`, and set `ZULIP_ALERTS_ENABLED=true` in **staging** (`.env.staging`); redeploy backend; verify messages land in the `staging` topic on a real connect/disconnect.
4. Once staging is confirmed, repeat for **production** (`.env.prod`), verifying the `production` topic.

Roll out staging first, prod second. Retirement is the inverse: set `ZULIP_ALERTS_ENABLED=false` to silence immediately.

## Acceptance criteria

- [ ] A Generic Zulip bot exists and is subscribed to the target channel.
- [ ] Staging: credentials set, flag enabled, and a real charger connect/disconnect appears in the `staging` topic.
- [ ] Production: credentials set, flag enabled, and a real charger connect/disconnect appears in the `production` topic.
- [ ] Both environments post to the same channel, separated by topic.
- [ ] Team confirms they can mute the staging topic while watching production.

## Blocked by

- Slice 2 — `02-add-connect-and-reject-events.md`
