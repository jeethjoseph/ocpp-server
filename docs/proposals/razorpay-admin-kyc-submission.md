# Admin-driven Razorpay Route KYC submission

## Context

We proved end-to-end on staging that a v2 linked account can be driven from `status=created` to `needs_clarification` (i.e. submitted to Razorpay for human review) entirely via API, without using Razorpay's KYC-Form UI. The three calls required were:

1. `client.product.requestProductConfiguration(account_id, {product_name: "route", tnc_accepted: True})` → returns `product_id`
2. `client.product.edit(account_id, product_id, {settlements: {...}})` → submit bank account
3. `client.stakeholder.create(account_id, {name, email, phone, relationship})` → clears the one outstanding `requirements[]` item

After these three calls, `GET /v2/accounts/{id}/products/{product_id}` showed `requirements: []` and `activation_status: needs_clarification`, meaning Razorpay has everything it needs and the account is waiting on their KYC team.

**Why this matters:** the Razorpay dashboard's KYC Form doesn't expose stakeholder management for proprietorship (`business_type: not_yet_registered`), so the "Submit Form" button stays permanently disabled. The API is the only path. Previously we did it via a one-off script; this proposal wires it into the admin UI.

**Intended outcome:**
- Admin clicks **Submit for KYC** on `/admin/franchisees/[id]` → backend runs the 3-call sequence → franchisee status advances and Razorpay review begins.
- Stakeholders are first-class in our data model (one franchisee → many stakeholders) with a UI to add them.
- Bank details (IFSC, account number, beneficiary name) are captured in the existing Business Details dialog.
- Existing account `acc_Sg73UwyOU3jziR` / product `acc_prd_SgqeqTX9SkdRF7` / stakeholder `sth_Sgqj3MuPstQHup` are back-reconciled, not duplicated.

**Non-goals:** KYC document upload (PAN card, cancelled cheque) — deferred; Razorpay's human review usually doesn't block on this for route accounts. Hosted/cobranded onboarding migration — separate track. Dashboard Access toggle automation — not exposed as API by Razorpay.

---

## Razorpay API surface we'll use (already in the installed SDK)

All under `client.product.*` and `client.stakeholder.*` — all v2:

| Purpose | SDK method | HTTP |
|---|---|---|
| Create product config (TnC accepted) | `product.requestProductConfiguration(account_id, {product_name, tnc_accepted, ip?})` | `POST /v2/accounts/{a}/products` |
| Update product config (bank/payment methods) | `product.edit(account_id, product_id, {settlements, payment_methods, refund, ...})` | `PATCH /v2/accounts/{a}/products/{p}` |
| Fetch product state + requirements | `product.fetch(account_id, product_id)` | `GET /v2/accounts/{a}/products/{p}` |
| Create stakeholder | `stakeholder.create(account_id, {name, email, phone, relationship, kyc?})` | `POST /v2/accounts/{a}/stakeholders` |
| Edit stakeholder | `stakeholder.edit(account_id, stakeholder_id, data)` | `PATCH /v2/accounts/{a}/stakeholders/{s}` |
| List stakeholders | `stakeholder.all(account_id)` | `GET /v2/accounts/{a}/stakeholders` |

`activation_status` lifecycle: `requested` → `needs_clarification` → `under_review` → `activated` (or → `rejected`, `suspended`).

---

## Changes

### 1. `backend/models.py`

**1a.** Add one column to `Franchisee`:
```python
razorpay_product_id = fields.CharField(max_length=50, null=True)  # acc_prd_XXX
```

**1b.** New table `FranchiseeStakeholder` (one-to-many with `Franchisee`):
```python
class FranchiseeStakeholder(Model):
    id = fields.IntField(pk=True)
    franchisee = fields.ForeignKeyField("models.Franchisee", related_name="stakeholders")
    razorpay_stakeholder_id = fields.CharField(max_length=50, unique=True, null=True)
    name = fields.CharField(max_length=255)
    email = fields.CharField(max_length=255)
    phone_primary = fields.CharField(max_length=20, null=True)
    relationship_director = fields.BooleanField(default=True)
    relationship_executive = fields.BooleanField(default=True)
    pan_number = fields.CharField(max_length=10, null=True)  # optional, for future KYC docs
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    class Meta:
        table = "franchisee_stakeholder"
```

### 2. Aerich migration

Generate via `docker exec ocpp-backend aerich migrate --name add_stakeholder_and_product_id`. Expected SQL:
```sql
ALTER TABLE "franchisee" ADD "razorpay_product_id" VARCHAR(50);
CREATE TABLE "franchisee_stakeholder" (
  "id" SERIAL PRIMARY KEY,
  "franchisee_id" INT NOT NULL REFERENCES "franchisee"("id") ON DELETE CASCADE,
  "razorpay_stakeholder_id" VARCHAR(50) UNIQUE,
  "name" VARCHAR(255) NOT NULL,
  "email" VARCHAR(255) NOT NULL,
  "phone_primary" VARCHAR(20),
  "relationship_director" BOOL NOT NULL DEFAULT true,
  "relationship_executive" BOOL NOT NULL DEFAULT true,
  "pan_number" VARCHAR(10),
  "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### 3. `backend/services/razorpay_service.py` — thin SDK wrappers

Add parallel to the existing `create_linked_account` / `fetch_linked_account`:

```python
def request_product_configuration(self, account_id, data): ...
def edit_product_configuration(self, account_id, product_id, data): ...
def fetch_product_configuration(self, account_id, product_id): ...
def create_stakeholder(self, account_id, data): ...
def list_stakeholders(self, account_id): ...
```

Each wraps the matching `self.client.product.*` / `self.client.stakeholder.*` call with `is_configured()` check + logger.error fallback. Same pattern as existing methods.

### 4. `backend/services/franchisee_onboarding_service.py` — new orchestration methods

**4a. `ensure_product_config(franchisee_id) -> product_id`**
If `franchisee.razorpay_product_id` is set, return it. Otherwise POST `product.requestProductConfiguration` with `{product_name: "route", tnc_accepted: True}`, persist the returned `id` on `franchisee.razorpay_product_id`, return it.

**4b. `submit_bank_details(franchisee_id) -> product_response`**
Require `franchisee.razorpay_product_id`, `bank_ifsc_code`, `bank_account_number`, `bank_account_name` to be set. PATCH `product.edit` with `{"settlements": {account_number, ifsc_code, beneficiary_name}}`. No local state change — bank info already persisted locally via the edit dialog.

**4c. `add_stakeholder(franchisee_id, payload) -> FranchiseeStakeholder`**
Build Razorpay payload from input (`{name, email, phone: {primary}, relationship: {director, executive}}`), POST via SDK, persist the returned `id` as `razorpay_stakeholder_id` on a new `FranchiseeStakeholder` row. Return the row.

**4d. `submit_kyc(franchisee_id) -> dict`** — orchestrator
1. Verify `franchisee.razorpay_account_id` exists (raise `RuntimeError` with a message otherwise).
2. Verify at least one stakeholder exists in our DB for this franchisee.
3. Verify bank fields are populated.
4. Call `ensure_product_config` → `submit_bank_details` → `fetch_product_configuration`.
5. Return `{product_id, activation_status, requirements, stakeholder_count}`.

**4e. Back-reconcile existing data** — one-time via an admin endpoint (see 5d below): for `franchisee_id=1`, store `razorpay_product_id = "acc_prd_SgqeqTX9SkdRF7"` and insert the existing stakeholder row with `razorpay_stakeholder_id = "sth_Sgqj3MuPstQHup"`. Keeps staging clean without creating duplicates.

### 5. `backend/routers/franchisees.py` — new admin endpoints

All under the existing `router = APIRouter(prefix="/api/admin/franchisees", tags=["Franchisee Management"])`.

**5a. `POST /{franchisee_id}/stakeholders`** — body: `{name, email, phone_primary?, relationship_director?, relationship_executive?, pan_number?}`. Calls `add_stakeholder`, returns the stored row.

**5b. `GET /{franchisee_id}/stakeholders`** — lists local stakeholders.

**5c. `POST /{franchisee_id}/submit-kyc`** — no body. Calls `submit_kyc`. Wrap Razorpay SDK exceptions to HTTP 400 the same way `onboard_to_razorpay` already does.

**5d. `POST /{franchisee_id}/reconcile-razorpay`** (admin-only) — optional endpoint to paste in an existing `razorpay_product_id` and stakeholder IDs into our DB. Covers the staging account we already pushed by hand. Accept body: `{razorpay_product_id?, razorpay_stakeholder_ids?: str[]}`.

### 6. `backend/routers/franchisees.py` — expose new fields in `FranchiseeResponse` + `FranchiseeUpdate`

- `FranchiseeResponse`: add `razorpay_product_id: Optional[str]`, `bank_account_number`, `bank_ifsc_code`, `bank_account_name`.
- `FranchiseeUpdate`: add `bank_account_number`, `bank_ifsc_code`, `bank_account_name` (model already has these columns, just not surfaced).
- `_franchisee_to_response`: include all new fields.

### 7. `frontend/types/api.ts`

```ts
// on Franchisee
razorpay_product_id?: string | null;
bank_account_number?: string | null;
bank_ifsc_code?: string | null;
bank_account_name?: string | null;

// on FranchiseeUpdate
bank_account_number?: string;
bank_ifsc_code?: string;
bank_account_name?: string;

// new type
export interface FranchiseeStakeholder {
  id: number;
  razorpay_stakeholder_id: string | null;
  name: string;
  email: string;
  phone_primary?: string | null;
  relationship_director: boolean;
  relationship_executive: boolean;
  pan_number?: string | null;
  created_at: string;
}

export interface StakeholderCreate {
  name: string;
  email: string;
  phone_primary?: string;
  relationship_director?: boolean;
  relationship_executive?: boolean;
  pan_number?: string;
}

export interface SubmitKYCResponse {
  product_id: string;
  activation_status: string;
  requirements: Array<{ field_reference: string; status: string; reason_code: string; resolution_url?: string }>;
  stakeholder_count: number;
}
```

### 8. `frontend/lib/api-services.ts` + `frontend/lib/queries/franchisees.ts`

Add to `franchiseeService`:
```ts
listStakeholders(id: number),
createStakeholder(id, body),
submitKYC(id),
```

Add TanStack Query hooks:
```ts
useFranchiseeStakeholders(id)
useCreateStakeholder(id)
useSubmitKYC()
```

### 9. `frontend/app/admin/franchisees/[id]/page.tsx` — UI additions

**9a. Business Details Edit Dialog** (existing): add 3 inputs to the grid — Bank Account Name, Bank IFSC, Bank Account Number.

**9b. Business Details display card**: show bank fields (masked account number `••••••1234`), plus a new row for `Razorpay Product ID`.

**9c. New Stakeholders card** (new section between Business Details and Assigned Stations):
- Lists existing stakeholders (name, email, phone, role badges)
- "Add Stakeholder" button → dialog with form
- Empty state: "No stakeholders yet. Razorpay requires at least one stakeholder to submit KYC."

**9d. New "Submit for KYC" button** on the header toolbar, next to "Start Razorpay onboarding":
- Visible only when `franchisee.razorpay_account_id` is set.
- Disabled when any of: no stakeholders, bank fields empty, status already `ACTIVE`.
- On click: calls `useSubmitKYC`. On success, shows a toast with `activation_status` and the number of outstanding `requirements`. On 400, shows the Razorpay message.

### 10. `docs/v1/llm-context-document.md` + `docs/razorpay-route-deployment.md`

Add a "Post-create KYC submission" subsection to the onboarding service entry describing the `ensure_product_config` → `submit_bank_details` → `add_stakeholder` → `submit_kyc` chain. Add a bullet to the deployment runbook: "After admin triggers Start Razorpay onboarding, they must also Add at least one stakeholder, fill bank details, and click Submit for KYC."

---

## Verification

1. **`npm run build`** passes (per CLAUDE.md frontend rule).
2. **Backend AST parse** on modified Python files.
3. **`docker exec ocpp-backend aerich migrate` + `upgrade`** adds columns + table cleanly.
4. **Unit test** for `FranchiseeOnboardingService.submit_kyc` with SDK mocked: verifies ordering, persistence, and error surfacing when bank or stakeholder is missing.
5. **Staging end-to-end against existing franchisee `id=1`:**
   1. Deploy: `make staging-pull && make staging-rebuild && make staging-migrate`.
   2. Call `POST /api/admin/franchisees/1/reconcile-razorpay` with `{razorpay_product_id: "acc_prd_SgqeqTX9SkdRF7", razorpay_stakeholder_ids: ["sth_Sgqj3MuPstQHup"]}` — back-reconciles without duplicating.
   3. Verify on admin page: stakeholders list shows Jeeth Joseph; bank fields editable.
   4. Click **Submit for KYC** again — should be idempotent (status stays `needs_clarification` since requirements already empty).
   5. For a NEW test franchisee: create it, fill address/state/city/pincode/bank/stakeholder → Start Razorpay onboarding → Submit for KYC → verify `activation_status` advances to `needs_clarification` with `requirements: []`.
6. **Webhook flow unchanged** — existing `handle_account_webhook` still receives state transitions from Razorpay's review and advances `franchisee.status` → `ACTIVE` once approved.

---

## What's explicitly out of scope (follow-ups)

- **KYC document uploads** (PAN card scan, cancelled cheque) via `account.uploadAccountDoc` / `stakeholder.uploadStakeholderDoc`. Razorpay's review may request these via new `requirements[]` entries; when that happens, we add an upload UI.
- **Multi-stakeholder support** for LLP/PrivateLimited — the data model supports it, but the UI only exposes "Add Stakeholder" (no edit/delete) to keep scope tight.
- **Auto-poll of `product.fetch`** to detect Razorpay review completion — we rely on the existing `account.activated` / `account.under_review` webhooks.
- **Hosted/cobranded onboarding** migration — separate initiative requiring Razorpay support ticket.
