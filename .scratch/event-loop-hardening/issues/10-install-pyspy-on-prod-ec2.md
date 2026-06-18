Status: done

# Install py-spy on prod EC2 (parity with staging)

## Context

During the 2026-06-01 staging freeze incident, log analysis alone failed to identify the root cause of repeated 100–190s event-loop wedges. We installed py-spy on the staging EC2 host afterwards (memorialized in agent memory `[[pyspy-on-staging]]`) so the next freeze can be diagnosed via a one-shot stack dump.

Prod (`app.voltlync.com`) does not yet have py-spy installed. If the same kind of freeze ever happens on prod, we'd be in the same fly-blind position we were in for staging on 2026-06-01. Install it now, before incident, so the dump command is ready when needed.

py-spy is a Rust-based sampling profiler. It reads the target Python process's memory via `process_vm_readv`, walks the interpreter's frame structures, and dumps every thread's Python stack. Sub-millisecond pause on the target, zero memory inside the target, no code injection. Safe to install in advance and leave dormant.

## What to build

Install py-spy 0.4.2 (or latest) on the production EC2 host (`i-0df24c96c4d5e890a`, per the Makefile `prod-ssm` target). Install path: `/usr/local/bin/py-spy`. Verify with a sanity dump against the prod backend container.

Procedure mirrors what was done on staging:

```bash
# As root on the prod EC2 host (via aws ssm send-command with voltlync profile):
which pip3 || sudo yum install -y python3-pip
sudo pip3 install py-spy
which py-spy
py-spy --version

# Sanity dump (will print backend's current thread stacks, ~2s):
HOST_PID=$(docker inspect -f '{{.State.Pid}}' ocpp-backend-prod)
sudo py-spy dump --pid $HOST_PID | head -50
```

The sanity dump confirms py-spy can attach to the prod backend container's process from the host PID namespace (needs `CAP_SYS_PTRACE`, which sudo provides).

## What to change

This is an operational change, not a code change. No commit needed.

## Acceptance criteria

- [ ] `which py-spy` on the prod EC2 host returns `/usr/local/bin/py-spy`.
- [ ] `py-spy --version` returns `py-spy 0.4.2` (or later).
- [ ] Sanity dump completes without error and prints `MainThread` (asyncio event loop), Sentry threads, NR-Harvest-Thread, etc. Same structure as the staging dump.
- [ ] Update the existing memory `reference_pyspy_on_staging.md` to reflect both staging AND prod installations — rename to `reference_pyspy_on_ec2.md` and add the prod instance ID + container name. Or add a sibling note. Either way, future sessions should know it's available on both envs.

## Notes for the agent

This is a one-time install. Do not configure it to run on container start — py-spy is dormant on disk until invoked. No memory or CPU cost when not running.

Per CLAUDE.md, prod is on branch `deploy` with separate `.env.prod`. The container name inside docker-compose is `ocpp-backend-prod` (confirm against `docker-compose.prod.yml`).

Per `feedback_staging_prod_execution.md`, use `aws ssm send-command` directly with the voltlync profile — don't ask the user to copy-paste shell blocks.

## Blocked by

None — can start immediately. Independent of all other issues.
