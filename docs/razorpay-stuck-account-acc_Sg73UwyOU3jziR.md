# Razorpay Route — Stuck Account Diagnostic

**Account ID:** `acc_Sg73UwyOU3jziR`
**Product config ID:** `acc_prd_SgqeqTX9SkdRF7`
**Stakeholder ID:** `sth_Sgqj3MuPstQHup`
**Support ticket reference:** `#18850427`
**Document prepared:** 2026-04-29

---

## ⚠️ Security note on credential sharing

The support agent's request asked for the live `Key ID` and `Key Secret`. **We will not share these.** Reasoning:

1. Razorpay's internal admin already has full access to this account from `admin-dashboard.razorpay.com/admin/merchants/Sg73UwyOU3jziR` (visible in the screenshot the agent attached). Any state we can observe via the API, the agent can observe directly.
2. The Key Secret is the credential for the platform/merchant account — not for the linked account being investigated. Sharing it would expose the entire VoltLync merchant account, not just this single Route sub-account.
3. Razorpay's own security policy says merchant secret keys should never be shared over support channels.

If the agent specifically needs to replay an API call with our `X-Razorpay-Account` header set to this linked account, we can do that internally and provide the request/response pair — which is what this document does.

---

## TL;DR

- **All four mandatory onboarding steps were completed via API.** Live `GET` calls confirm: linked account created, stakeholder created with `kyc.pan`, product configuration created with `tnc_accepted: true`, and bank settlement details PATCHed onto the product config.
- **Razorpay's product config returns `activation_status: "needs_clarification"` with `requirements: []` (empty array).** Per Razorpay's own integration guide ("only those fields which are present in the requirements array … should be resent"), there is no documented way to clear this state because no field is being requested.
- **The internal admin's "Activation Form Progress: 10%" metric appears to track the dashboard hosted KYC form completion, not the API-driven submission.** We never used the dashboard form — we drove all four steps through the API. The 10% number is therefore inconsistent with the product configuration state, which shows complete submission.
- **This pattern is documented in `razorpay/razorpay-node` issue #427** (open since Jan 2025): linked accounts created via the SDK's standard 4-step flow get stuck without `requirements` ever being populated.

---

## 1. `POST /v2/accounts` — Create Linked Account

### Request body (current code, `franchisee_onboarding_service.py:create_linked_account`)

```json
{
  "email": "jeethjoseph@gmail.com",
  "phone": "7356894041",
  "type": "route",
  "reference_id": "franchisee_1",
  "legal_business_name": "Makara Tech",
  "customer_facing_business_name": "Makara Tech",
  "business_type": "individual",
  "contact_name": "Jeeth Joseph",
  "profile": {
    "category": "services",
    "subcategory": "service_stations",
    "addresses": {
      "registered": {
        "street1": "KRA 17",
        "street2": "TOG Pass Road, Kalamassery",
        "city": "Kochi",
        "state": "KERALA",
        "postal_code": "683104",
        "country": "IN"
      },
      "operational": {
        "street1": "KRA 17",
        "street2": "TOG Pass Road, Kalamassery",
        "city": "Kochi",
        "state": "KERALA",
        "postal_code": "683104",
        "country": "IN"
      }
    }
  },
  "notes": {
    "voltlync_franchisee_id": "1"
  }
}
```

> **Note:** the original create call (2026-04-21) was made by an earlier code revision. We do not have a logged copy of the exact bytes that went on the wire — what we know is what Razorpay echoes back in `GET /v2/accounts/{id}` (below). The current code's payload is shown above for reference and matches what we'd send today.

### Live response — `GET /v2/accounts/acc_Sg73UwyOU3jziR` (HTTP 200)

```json
{
  "id": "acc_Sg73UwyOU3jziR",
  "type": "route",
  "status": "created",
  "email": "jeethjoseph@gmail.com",
  "profile": {
    "category": "services",
    "subcategory": "service_stations",
    "addresses": {
      "registered": {
        "street1": "KRA 17",
        "street2": "TOG Pass Road, Kalamassery",
        "city": "Kochi",
        "state": "KERALA",
        "postal_code": "683104",
        "country": "IN"
      }
    }
  },
  "notes": {
    "voltlync_franchisee_id": "1"
  },
  "created_at": 1776767957,
  "phone": "+917356894041",
  "contact_name": "Jeeth Joseph",
  "reference_id": "franchisee_1",
  "business_type": "not_yet_registered",
  "legal_business_name": "Jeeth Joseph",
  "customer_facing_business_name": "Makara Tech"
}
```

### ❗ Anomaly 1: `business_type` mismatch

We send `business_type: "individual"` per our `_BUSINESS_TYPE_MAP[INDIVIDUAL]`. Razorpay stored `business_type: "not_yet_registered"`.

This silent downgrade is the main thing we'd like Razorpay to explain. Two possible causes we considered:

1. **The original create call (Apr 21) sent something other than `individual`.** Possible if the account was created via the dashboard form. We don't have proof either way.
2. **Razorpay's PAN-validation false-positive issue (`razorpay/razorpay-node` issue #404)** silently rejected the proprietor PAN and downgraded the classification.

`business_type` is **locked** post-create — `PATCH /v2/accounts/{id}` with `{"business_type": "individual"}` returns `BAD_REQUEST_ERROR: "business_type is/are not required and should not be sent"`. So we cannot self-correct this. **We need Razorpay to either: (a) update the account's business_type to `individual` internally, or (b) explain why our original `individual` request was downgraded.**

---

## 2. `POST /v2/accounts/{id}/stakeholders` — Create Stakeholder

### Request body (current code, `franchisee_onboarding_service.py:add_stakeholder`)

```json
{
  "name": "Jeeth Joseph",
  "email": "jeethjoseph@gmail.com",
  "phone": {
    "primary": "7356894041"
  },
  "kyc": {
    "pan": "BFIPJ6239L"
  },
  "relationship": {
    "director": false,
    "executive": true
  }
}
```

> **Note:** the existing stakeholder (`sth_Sgqj3MuPstQHup`) was created with `relationship.director: true` (visible in the live fetch below). For an INDIVIDUAL account this is semantically wrong — there is no "director" of an individual proprietorship. The current code now derives `(False, True)` for INDIVIDUAL/PROPRIETORSHIP via a `_relationship_defaults` helper. The PAN was added later via a separate `PATCH /v2/accounts/{id}/stakeholders/{sid}` call once we discovered the original create omitted it.

### Live response — `GET /v2/accounts/acc_Sg73UwyOU3jziR/stakeholders/sth_Sgqj3MuPstQHup` (HTTP 200)

```json
{
  "id": "sth_Sgqj3MuPstQHup",
  "entity": "stakeholder",
  "relationship": {
    "director": true,
    "executive": true
  },
  "phone": {
    "primary": "7356894041",
    "secondary": "7356894041"
  },
  "notes": [],
  "kyc": {
    "pan": "BFIPJ6239L"
  },
  "name": "Jeeth Joseph",
  "email": "jeethjoseph@gmail.com"
}
```

Per Razorpay's own KYC requirements table for `business_type: not_yet_registered`:

| Field | Required? |
|---|---|
| Stakeholder PAN | **Yes** ✅ (provided: `BFIPJ6239L`) |
| Business PAN | NA |
| Bank Account | **Yes** ✅ (see step 4) |
| GST | NA |

**All required KYC fields per the documented spec are present.**

---

## 3. `POST /v2/accounts/{id}/products` — Request Product Configuration

### Request body

```json
{
  "product_name": "route",
  "tnc_accepted": true
}
```

### Live response — `GET /v2/accounts/acc_Sg73UwyOU3jziR/products/acc_prd_SgqeqTX9SkdRF7` (HTTP 200)

```json
{
  "requested_configuration": [],
  "active_configuration": {
    "settlements": {
      "account_number": "31573863930",
      "beneficiary_name": "JEETH JOSEPH",
      "ifsc_code": "SBIN0010570"
    }
  },
  "requirements": [],
  "tnc": {
    "id": "tnc_SgqeqLdeDX5bVw",
    "accepted": true,
    "accepted_at": 1776928551
  },
  "id": "acc_prd_SgqeqTX9SkdRF7",
  "product_name": "route",
  "activation_status": "needs_clarification",
  "account_id": "acc_Sg73UwyOU3jziR",
  "requested_at": 1776928551
}
```

---

## 4. `PATCH /v2/accounts/{id}/products/{pid}` — Update Product Configuration (Bank)

### Request body (current code, `franchisee_onboarding_service.py:submit_bank_details`)

```json
{
  "settlements": {
    "account_number": "31573863930",
    "ifsc_code": "SBIN0010570",
    "beneficiary_name": "JEETH JOSEPH",
    "account_type": "savings"
  },
  "tnc_accepted": true
}
```

### Live response (same product config GET as step 3)

The `active_configuration.settlements` block confirms bank details are persisted:

```json
"active_configuration": {
  "settlements": {
    "account_number": "31573863930",
    "beneficiary_name": "JEETH JOSEPH",
    "ifsc_code": "SBIN0010570"
  }
}
```

`tnc.accepted: true`, `accepted_at: 1776928551` (2026-04-21 18:35 UTC) — terms accepted at the moment of the original PATCH.

---

## ❗ Anomaly 2: `needs_clarification` + empty `requirements[]`

**This is the core stuck state.** The product configuration's `activation_status` is `needs_clarification`, but `requirements` is `[]` (empty array).

Razorpay's own integration guide states:

> *"only those fields which are present in the `requirements` array in the Fetch Product Configuration API response should be resent."*

With `requirements: []`, there is **nothing for us to resend**. We've tried:

1. Re-PATCHing the product config with the same settlements (no-op nudge) — `activation_status` stayed `needs_clarification`.
2. Fetching with `?expand[]=requirements` and `?expand[]=resolution_url` query parameters — neither surfaced any additional fields.
3. PATCHing the stakeholder with `kyc.pan` (in case PAN was the implicit clarification) — `activation_status` stayed `needs_clarification`.
4. PATCHing the account with `legal_info.pan` — rejected: `"The company pan field is invalid for business type: not_yet_registered"`. Consistent with the KYC requirements table (Business PAN is "NA" for `not_yet_registered`).

Per Razorpay's own KYC requirements table, the only required fields for `business_type: not_yet_registered` are:

- Owner / Signatory PAN (on stakeholder) — ✅ provided (`BFIPJ6239L`)
- Bank Account — ✅ provided (SBIN0010570 / `31573863930` / JEETH JOSEPH)

There are no other documented required fields. The state is therefore inconsistent with the documented contract.

---

## ❗ Anomaly 3: "Activation Form Progress: 10%" in internal admin

The screenshot the support agent shared shows `Activation Form Progress: 10%` in the internal admin at `admin-dashboard.razorpay.com/admin/merchants/Sg73UwyOU3jziR`.

Our reading of this number: **it tracks dashboard hosted KYC Form completion, not the API-driven submission.** Evidence:

1. We never opened or filled the dashboard's hosted KYC Form (the form visible at `dashboard.razorpay.com/app/route/accounts/...`). All four steps were driven via the public Route APIs.
2. The product configuration entity returned by `GET /v2/accounts/{id}/products/{pid}` shows complete `active_configuration.settlements`, `tnc.accepted: true`, and an associated stakeholder with `kyc.pan` set. By the documented activation flow this is everything needed.
3. The dashboard's hosted KYC form has its own "Submit Form" button which we observed greyed out (`Complete the form to submit`) — consistent with the form thinking 10% was filled, but we never *needed* to use the form because the API path is what your integration guide recommends.

**Question to Razorpay:** is the 10% Activation Form Progress metric tracking the dashboard hosted form independently of the product configuration's API state? If yes, can you reconcile the two so accounts onboarded via the API path don't get blocked by an unrelated form-completion meter?

---

## Reproducible API call list (for Razorpay engineering)

A Razorpay engineer with admin access can replay the following four GETs against this account to verify the state. No customer credentials needed — Razorpay admin can read all merchant entities directly:

```
GET /v2/accounts/acc_Sg73UwyOU3jziR
GET /v2/accounts/acc_Sg73UwyOU3jziR/stakeholders
GET /v2/accounts/acc_Sg73UwyOU3jziR/stakeholders/sth_Sgqj3MuPstQHup
GET /v2/accounts/acc_Sg73UwyOU3jziR/products/acc_prd_SgqeqTX9SkdRF7
```

The full responses are inlined above (sections 1–4) and were captured at 2026-04-29 from a server that uses our live Key ID.

---

## Specific asks for Razorpay support

1. **Resolve the `needs_clarification` state.** Either populate `requirements[]` with the actual fields needing clarification, or advance the `activation_status` to `under_review` since all documented requirements are submitted.
2. **Fix the `business_type` from `not_yet_registered` to `individual`** internally. The proprietor's PAN (`BFIPJ6239L`) is on file via the stakeholder. The API doesn't allow merchants to PATCH this field, so this requires admin action.
3. **Explain the 10% Activation Form Progress** discrepancy. If it's a dashboard-form-only metric, please confirm so we can ignore it for API-onboarded accounts.
4. **Acknowledge `razorpay-node` issue #427.** This stuck-state pattern has been open in your public SDK tracker since January 2025 with multiple developers reporting identical symptoms (Route accounts stuck inactive, no `requirements` provided). Internal escalation to the Route engineering team would resolve a recurring class of partner issues, not just this single account.

---

## Reference data

- Linked account `created_at`: 1776767957 (2026-04-21 10:39 UTC)
- Product config `requested_at`: 1776928551 (2026-04-21 18:35 UTC) — both products and bank PATCH happened the same day
- TNC accepted at: 1776928551 (same)
- Days stuck in `needs_clarification` as of this document: 8

## Reference: `razorpay-node` issue #427 (extract)

> "Accounts get stuck in 'not activated' status. The user tested multiple account types — `private_limited`, `individual`, `LLP`, `not_yet_registered` — with identical results. When attempting to update account products via API, the system provides 'no requirement provided' feedback. The documentation explicitly states that 'missing fields / requirements will be mentioned here,' but this isn't occurring."

Source: https://github.com/razorpay/razorpay-node/issues/427 (open since January 2025; no maintainer response).
