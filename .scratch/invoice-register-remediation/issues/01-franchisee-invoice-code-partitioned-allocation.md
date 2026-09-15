# Franchisee invoice code with partitioned allocation (foundation)

Status: done

## What to build

Give every **Franchisee** a stable, globally-unique `invoice_code` that is independent of its database primary key, and partition the code space so two databases can never mint the same code.

Today `InvoiceService.get_next_invoice_number` interpolates the raw `franchisee_id` primary key into the customer-facing GST Invoice number (`VL/F{franchisee_id}/...`). Primary keys are per-database autoincrements, so production and staging — which share one GSTIN — independently allocate the same IDs. This has already produced two duplicate invoice numbers (`VL/F2/QR/202627/00001` and `/00002`, issued to Muhammed Sadiq in production and Ancy Thomas in staging), and it is a live countdown: production is at franchisee 3, and its 5th franchisee will mint `F5`, colliding with Arunraj R's 878-invoice staging series.

Code format is `F` + 4 digits. Allocation blocks:

| Block | Register | Assigned |
|---|---|---|
| `F0000` | VoltLync-owned stations (`franchisee_id IS NULL`) | reserved |
| `F0001`–`F8999` | Production | F0001 R Shyam Shankar, F0002 Muhammed Sadiq, F0003 S K Consultancy Services |
| `F9000`–`F9999` | Staging — closed, no further allocation | F9002 Ancy Thomas, F9005 Arunraj R |

Staging's last digit deliberately mirrors its current primary key so an old `VL/F5/...` invoice and a new `F9005/...` invoice are visibly the same operator. Only the two staging franchisees that have ever issued a **GST Invoice** get a code; Makara Tech, Sanjana Joshy and Adwaith R Das have zero invoices and need none.

The block restriction must be enforced by the database, not by convention — the previous arrangement relied on nobody creating a colliding franchisee and failed silently for three months. Because Aerich migrations are shared across environments, the range predicate is built in the migration's `upgrade()` from a new `FRANCHISEE_CODE_BLOCK` environment variable (`production` | `staging`, defaulting to `production`). Per the env-var checklist in CLAUDE.md this variable must be added to `.env.example`, `.env.staging.example`, `.env.prod.example` **and** the `backend.environment:` block of all three compose files, or the container will not see it.

This slice does not change any invoice number. It only establishes the code and proves the constraint holds. Issue 02 consumes it.

## Acceptance criteria

- [ ] Aerich migration adds `Franchisee.invoice_code` (`CHAR(4)`, nullable, unique); `downgrade()` drops it cleanly
- [ ] Same migration adds a format CHECK (`^F[0-9]{4}$`) and an environment-specific range CHECK built from `FRANCHISEE_CODE_BLOCK` — production may only hold `F[0-8][0-9]{3}`, staging only `F9[0-9]{3}`
- [ ] `FRANCHISEE_CODE_BLOCK` added to all three `.env*.example` files and to `backend.environment:` in `docker-compose.yml`, `docker-compose.staging.yml`, `docker-compose.prod.yml`
- [ ] Migration backfills the three production codes; a documented one-off statement backfills the two staging codes (staging is a closed block and will never allocate again)
- [ ] Franchisee creation allocates the next free code within the configured block and fails loudly if the block is exhausted — never silently falls back
- [ ] Attempting to insert an out-of-block code is rejected by the database, verified by a test that asserts the `IntegrityError`
- [ ] Admin franchisee create/detail responses expose `invoice_code`; the admin UI shows it on the franchisee detail page
- [ ] Affected per-file pytest green (`docker exec ocpp-backend pytest`) — run per-file, not one bare `pytest`

## Blocked by

- None - can start immediately
