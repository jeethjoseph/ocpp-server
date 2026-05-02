# Razorpay Route Onboarding — Complete Request/Response Trace

**Account ID:** `acc_SjK7ZBzAfiA4QF`
**Stakeholder ID:** `sth_SjKGNaCKoRIqVS`
**Product config ID:** `acc_prd_SjKGpmHqQKAGSJ`
**Franchisee:** Ancy Thomas (franchisee_id=2 in our DB)
**Document prepared:** 2026-04-29

This document is generated from the platform's own outbound API audit log
(`razorpay_api_log` table). Every byte sent / received is logged at write
time with PII fields (PAN, account number, IFSC) masked to `***LAST4`.

---

## ⚠️ Security note on credential sharing

Razorpay support previously asked for live `Key ID` + `Key Secret` to
"replicate the issue internally" on the prior stuck account
(`acc_Sg73UwyOU3jziR`). **We will not share these.** Razorpay's internal
admin already has full access to all merchant accounts; the inline
request/response pairs below provide everything needed to replay any of
the four documented onboarding steps without our credentials.

---

## Summary

All four mandatory onboarding steps completed via API. The first PATCH on
the product config 400'd twice because we (incorrectly) sent
`settlements.account_type` — corrected and the third PATCH landed clean.
The product config response now shows the bank `active_configuration`
populated, but **`activation_status` remains `needs_clarification` with
empty `requirements[]`** — exactly the same stuck state observed on the
prior `acc_Sg73UwyOU3jziR`.

This is the second linked account on this merchant
(`SJuyD9rL8E3P2b`) to land in `needs_clarification + requirements: []`
— a state Razorpay's own integration guide says shouldn't occur
("only those fields which are present in the requirements array … should
be resent"). It matches the open issue
[razorpay-node #427](https://github.com/razorpay/razorpay-node/issues/427).

| # | Time (UTC) | Method | Endpoint | Status | Notes |
|---|---|---|---|---|---|
| 1 | 13:23:25 | POST | /v2/accounts | 200 | Account created. **`business_type` silently downgraded `individual` → `not_yet_registered`** (same as `acc_Sg73UwyOU3jziR`). |
| 2 | 13:31:32 | POST | /v2/accounts/{id}/stakeholders | 200 | Stakeholder created with PAN (***267A), residential address, `relationship: {director:false, executive:true}` per the documented INDIVIDUAL/PROPRIETORSHIP pattern. |
| 3 | 13:31:56 | POST | /v2/accounts/{id}/products | 200 | Product config created. Response immediately reports `requirements[]` listing the three bank fields — expected, the bank PATCH is the next step. |
| 4 | 13:31:57 | PATCH | /v2/accounts/{id}/products/{pid} | 400 | Rejected: `account_type is/are not required and should not be sent`. |
| 5 | 13:31:58 | PATCH | (same) | 400 | Same — admin re-clicked. |
| 6 | 14:10:21 | PATCH | (same) | 200 | After we removed `account_type` from the payload. Bank persisted; `requirements: []`; `activation_status: needs_clarification`. |

---

## Step 1 — Create Linked Account

`POST /v2/accounts`
Time: 2026-04-29 13:23:25 UTC

### Request body (logged at write time)

```json
{
  "type": "route",
  "email": "ancy653@gmail.com",
  "phone": "9744261367",
  "contact_name": "Ancy Thomas",
  "legal_business_name": "Ancy Thomas",
  "customer_facing_business_name": "Ancy Thomas",
  "business_type": "individual",
  "reference_id": "f_2_1777468989",
  "profile": {
    "category": "services",
    "subcategory": "service_stations",
    "addresses": {
      "registered": {
        "street1": "Cs9",
        "street2": "Yerik Garden apartment  IMG junction, Kakkanad kochi-682030",
        "city": "Kochi",
        "state": "KERALA",
        "postal_code": "682030",
        "country": "IN"
      }
    }
  },
  "notes": {
    "voltlync_franchisee_id": "2"
  }
}
```

### Response body

```json
{
  "id": "acc_SjK7ZBzAfiA4QF",
  "type": "route",
  "status": "created",
  "email": "ancy653@gmail.com",
  "phone": "+919744261367",
  "contact_name": "Ancy Thomas",
  "legal_business_name": "Ancy Thomas",
  "customer_facing_business_name": "Ancy Thomas",
  "business_type": "not_yet_registered",
  "reference_id": "f_2_1777468989",
  "profile": {
    "category": "services",
    "subcategory": "service_stations",
    "addresses": {
      "registered": {
        "street1": "Cs9",
        "street2": "Yerik Garden apartment  IMG junction, Kakkanad kochi-682030",
        "city": "Kochi",
        "state": "KERALA",
        "postal_code": "682030",
        "country": "IN"
      }
    }
  },
  "notes": {"voltlync_franchisee_id": "2"},
  "created_at": 1777468990
}
```

### ❗ Anomaly 1 (recurring): silent business_type downgrade

We sent `business_type: "individual"`. Razorpay echoed
`business_type: "not_yet_registered"`. Identical pattern to
`acc_Sg73UwyOU3jziR`. Field is not editable post-create
(PATCH `business_type` returns
`"business_type is/are not required and should not be sent"`).

**Question to Razorpay:** under what conditions does the create endpoint
silently downgrade `individual` → `not_yet_registered`? Is the
proprietor PAN (`BFKPT9267A`) being rejected by your internal validator
without surfacing an error?

---

## Step 2 — Create Stakeholder

`POST /v2/accounts/acc_SjK7ZBzAfiA4QF/stakeholders`
Time: 2026-04-29 13:31:32 UTC

### Request body (logged, PII masked)

```json
{
  "name": "Ancy Thomas",
  "email": "ancy653@gmail.com",
  "phone": {"primary": "9744261367"},
  "kyc": {"pan": "***267A"},
  "addresses": {
    "residential": {
      "street": "Cs9,Yerik Garden apartment  IMG junction, Kakkanad kochi-682030",
      "city": "Kochi",
      "state": "KERALA",
      "postal_code": "683104",
      "country": "IN"
    }
  },
  "relationship": {"director": false, "executive": true}
}
```

> Note on masking: the unmasked PAN is on file in our DB. Razorpay
> support (with privileged access) can read the unmasked value via the
> stakeholder fetch on their internal admin.

### Response body (PII echoed by Razorpay; masked at write time on our side)

```json
{
  "id": "sth_SjKGNaCKoRIqVS",
  "entity": "stakeholder",
  "name": "Ancy Thomas",
  "email": "ancy653@gmail.com",
  "phone": {"primary": "9744261367"},
  "kyc": {"pan": "***267A"},
  "notes": [],
  "relationship": {"executive": true}
}
```

Razorpay accepted PAN, residential address, and the executive-only
relationship in a single POST. No follow-up PATCH was needed (unlike
the previous account where the original create omitted the PAN).

---

## Step 3 — Request Product Configuration

`POST /v2/accounts/acc_SjK7ZBzAfiA4QF/products`
Time: 2026-04-29 13:31:56 UTC

### Request body

```json
{"product_name": "route", "tnc_accepted": true}
```

### Response body

```json
{
  "id": "acc_prd_SjKGpmHqQKAGSJ",
  "account_id": "acc_SjK7ZBzAfiA4QF",
  "product_name": "route",
  "tnc": {
    "id": "tnc_SjKGpePoe9N8BF",
    "accepted": true,
    "accepted_at": 1777469516
  },
  "requested_at": 1777469516,
  "activation_status": "needs_clarification",
  "active_configuration": {
    "settlements": {
      "ifsc_code": null,
      "account_number": null,
      "beneficiary_name": null
    }
  },
  "requested_configuration": [],
  "requirements": [
    {
      "status": "required",
      "reason_code": "field_missing",
      "resolution_url": "/accounts/acc_SjK7ZBzAfiA4QF/products/acc_prd_SjKGpmHqQKAGSJ",
      "field_reference": "settlements.beneficiary_name"
    },
    {
      "status": "required",
      "reason_code": "field_missing",
      "resolution_url": "/accounts/acc_SjK7ZBzAfiA4QF/products/acc_prd_SjKGpmHqQKAGSJ",
      "field_reference": "settlements.account_number"
    },
    {
      "status": "required",
      "reason_code": "field_missing",
      "resolution_url": "/accounts/acc_SjK7ZBzAfiA4QF/products/acc_prd_SjKGpmHqQKAGSJ",
      "field_reference": "settlements.ifsc_code"
    }
  ]
}
```

✅ Sensible: at this point bank details haven't been PATCHed yet, so
`requirements[]` correctly lists the three missing settlement fields.
This is exactly the contract Razorpay's docs describe.

---

## Step 4a — Update Product Configuration (first attempt — REJECTED)

`PATCH /v2/accounts/acc_SjK7ZBzAfiA4QF/products/acc_prd_SjKGpmHqQKAGSJ`
Time: 2026-04-29 13:31:57 UTC and 13:31:58 UTC (admin re-clicked)
HTTP **400**

### Request body (PII masked)

```json
{
  "settlements": {
    "ifsc_code": "***1161",
    "account_type": "savings",
    "account_number": "***1047",
    "beneficiary_name": "Ancy Thomas"
  },
  "tnc_accepted": true
}
```

### Response

```json
{
  "error": {
    "code": "BAD_REQUEST_ERROR",
    "description": "account_type is/are not required and should not be sent"
  }
}
```

**Diagnosis (from our side):** the platform code added `account_type`
on the assumption that the bank-account schema supports it (it does
elsewhere at Razorpay, e.g. on RazorpayX bank-account fund accounts).
For the Route product configuration update, Razorpay rejects it.
Removed from our payload; documented in the codebase
(`franchisee_onboarding_service.submit_bank_details`).

---

## Step 4b — Update Product Configuration (corrected — 200)

`PATCH /v2/accounts/acc_SjK7ZBzAfiA4QF/products/acc_prd_SjKGpmHqQKAGSJ`
Time: 2026-04-29 14:10:21 UTC

### Request body (PII masked)

```json
{
  "settlements": {
    "ifsc_code": "***1161",
    "account_number": "***1047",
    "beneficiary_name": "Ancy Thomas"
  },
  "tnc_accepted": true
}
```

### Response body

```json
{
  "id": "acc_prd_SjKGpmHqQKAGSJ",
  "account_id": "acc_SjK7ZBzAfiA4QF",
  "product_name": "route",
  "tnc": {
    "id": "tnc_SjKGpePoe9N8BF",
    "accepted": true,
    "accepted_at": 1777469516
  },
  "requested_at": 1777469516,
  "activation_status": "needs_clarification",
  "active_configuration": {
    "settlements": {
      "ifsc_code": "***1161",
      "account_number": "***1047",
      "beneficiary_name": "Ancy Thomas"
    }
  },
  "requested_configuration": [],
  "requirements": []
}
```

### ❗ Anomaly 2 (recurring): `needs_clarification` + empty `requirements[]`

Identical to `acc_Sg73UwyOU3jziR`:

- `active_configuration.settlements` shows the bank details persisted ✅
- `tnc.accepted = true` ✅
- Stakeholder with PAN attached ✅
- **Yet `activation_status: "needs_clarification"` and `requirements: []`**

Per Razorpay's own integration guide:

> *"only those fields which are present in the `requirements` array in
> the Fetch Product Configuration API response should be resent."*

With `requirements: []` we have nothing to resend. This is the same
state machine violation observed on the prior account 9+ days ago.

---

## Reproducible API call list (for Razorpay engineering)

A Razorpay engineer with admin access can replay the following GETs
against this account from their internal admin:

```
GET /v2/accounts/acc_SjK7ZBzAfiA4QF
GET /v2/accounts/acc_SjK7ZBzAfiA4QF/stakeholders
GET /v2/accounts/acc_SjK7ZBzAfiA4QF/stakeholders/sth_SjKGNaCKoRIqVS
GET /v2/accounts/acc_SjK7ZBzAfiA4QF/products/acc_prd_SjKGpmHqQKAGSJ
```

The full request/response bodies for the six write operations above
are inlined verbatim from our `razorpay_api_log` table (single source of
truth — captured at SDK call time, before any post-processing).

---

## Specific asks for Razorpay support

1. **Resolve the `needs_clarification` state** on `acc_prd_SjKGpmHqQKAGSJ`
   — populate `requirements[]` with the actual fields needing
   clarification, or advance the `activation_status` to `under_review`
   since all documented requirements are submitted.

2. **Fix the `business_type` from `not_yet_registered` to `individual`**
   internally on `acc_SjK7ZBzAfiA4QF`. The proprietor PAN (`BFKPT9267A`)
   is on the stakeholder. The API doesn't allow merchants to PATCH this
   field, so this requires admin action.

3. **Explain why `business_type` was silently downgraded** at create
   time. We sent `"individual"`; Razorpay stored `"not_yet_registered"`.
   Same on `acc_Sg73UwyOU3jziR`. This is the second occurrence on the
   same merchant; the pattern is reproducible and should be debuggable
   by your team.

4. **Acknowledge `razorpay-node` issue #427** and escalate this class
   of stuck-account behavior to the Route engineering team. This is
   our second affected account in 9 days; if not addressed, every
   future franchisee onboarded via the documented 4-step API flow will
   land in the same opaque `needs_clarification + empty requirements`
   state.

---

## Reference data

- Linked account `created_at`: 1777468990 (2026-04-29 13:23:10 UTC)
- Stakeholder created at: 2026-04-29 13:31:32 UTC
- Product config `requested_at` / `tnc.accepted_at`: 1777469516
  (2026-04-29 13:31:56 UTC)
- Bank PATCH succeeded at: 2026-04-29 14:10:21 UTC
- Time spent in `needs_clarification` (so far): see git/audit-log

## Source of all data above

`razorpay_api_log` table, rows 10–15, populated automatically by
`backend/services/razorpay_service._audit_call`. PII in request/response
bodies is masked (PAN → `***267A`, account_number → `***1047`,
ifsc_code → `***1161`) at write time — last-4 retention preserves
diagnostic value while limiting leak surface. Razorpay's internal admin
has read access to the unmasked entities.

---

## Resolution (2026-04-30)

After Razorpay support replied that `service_stations` is not a valid
SERVICES subcategory on their KYC side (despite being in the underlying
API enum), we ran three diagnostic PATCHes against `acc_SjK7ZBzAfiA4QF`
via `aws ssm send-command` against the staging EC2 (`docker exec -u app
ocpp-backend-staging python ...` calling
`razorpay_service.update_linked_account`). Audit-log writes were
swallowed because Tortoise ORM is not initialised outside the FastAPI
lifespan; the SDK calls themselves still went through.

### Test 1 — UPPERCASE same value (REJECTED)

`PATCH /v2/accounts/acc_SjK7ZBzAfiA4QF` body:

```json
{"profile": {"category": "SERVICES", "subcategory": "SERVICE_STATIONS"}}
```

Response: HTTP 400, `BadRequestError: Invalid business subcategory for
business category: SERVICES`. Razorpay's enum is **lowercase-strict** —
the support team's UPPERCASE listing was display formatting, not API
format.

### Test 2 — UPPERCASE different value (REJECTED)

`PATCH /v2/accounts/acc_SjK7ZBzAfiA4QF` body:

```json
{"profile": {"category": "SERVICES", "subcategory": "AUTOMOTIVE_SERVICE_SHOPS"}}
```

Response: HTTP 400, identical error. Confirms case is the gating
factor at this layer.

### Test 3 — lowercase `automotive_service_shops` (ACCEPTED, ACTIVATED)

`PATCH /v2/accounts/acc_SjK7ZBzAfiA4QF` body:

```json
{"profile": {"category": "services", "subcategory": "automotive_service_shops"}}
```

Response: HTTP 200. Profile echoed back with the new subcategory.
Stakeholder, settlements, and `reference_id` preserved — no recreate
needed.

Immediate refetch of the product config:

`GET /v2/accounts/acc_SjK7ZBzAfiA4QF/products/acc_prd_SjKGpmHqQKAGSJ`

```json
{
  "activation_status": "activated",
  "requirements": [],
  "active_configuration": {
    "settlements": {
      "account_number": "918010080721047",
      "beneficiary_name": "Ancy Thomas",
      "ifsc_code": "UTIB0001161"
    }
  },
  "requested_configuration": []
}
```

`activation_status` flipped from `needs_clarification` → **`activated`**.
The account is live for transfers.

### Conclusions

1. The opaque `needs_clarification + empty requirements[]` state on this
   account (and on the prior `acc_Sg73UwyOU3jziR`) was caused
   **entirely** by the rejected `service_stations` subcategory. Bank,
   PAN, stakeholder, and TnC data were correct from the start —
   Razorpay's KYC reviewer just had no way to surface "subcategory is
   wrong" through the documented `requirements[]` mechanism.
2. The fix for new onboardings is a one-line change in
   `backend/services/franchisee_onboarding_service.py:171` (`service_stations`
   → `automotive_service_shops`) plus an updated comment block.
3. The bank-account-name ↔ `beneficiary_name` ↔ `legal_business_name`
   equality requirement raised in support's email is not enforced in
   code yet. For Ancy Thomas all three already coincided
   (`"Ancy Thomas"`), so it did not block this account; the franchisee
   detail UI now carries an advisory note pending confirmation that
   the rule applies uniformly across all `business_type` values.

### Anomalies NOT resolved by this change

These remain open with Razorpay engineering and are independent of our
payload:

- **Silent `business_type` downgrade** at create time — we sent
  `individual`, Razorpay stored `not_yet_registered`. Field is not
  PATCH-able post-create. Same on `acc_Sg73UwyOU3jziR`.
- **`needs_clarification` returned with empty `requirements[]`** —
  Razorpay's own integration guide states `requirements[]` should
  enumerate the missing fields. Returning the state without populating
  the array is a state-machine violation and matches
  [razorpay-node #427](https://github.com/razorpay/razorpay-node/issues/427).
