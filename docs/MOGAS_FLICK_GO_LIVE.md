# MOGAS UAE — Flick go-live checklist

Proposed ASP: **Flick Network L.L.C** (adapter `providers/flick/`). Status 2026-11-19: Flick's
payload builder verified against the fork on Frappe 15.108 / ERPNext 15.108.3 with a fake
transport; **no call to Flick's sandbox yet.**

## 1. Get from Flick (per UAE company — MOGAS has two)

| Item | Goes into *E-Invoice Provider Settings* |
|---|---|
| Sandbox base URL (e.g. `https://sb-ae-api.flick.network`), later the production URL | `base_url` |
| Auth: OAuth client id + secret **or** API key (`X-Flick-Auth-Key`) | `auth_type` = `oauth2` / `api_key`, credentials |
| Participant ID (PEPPOL, `0235:1xxxxxxxxxxxxx`) | `participant_id` |
| TRN of each company | `trn` + Company *Tax ID* |
| Confirmation whether MOGAS will **self-bill** (see §3) | — |

## 2. Configure in ERPNext

1. Company (each UAE one) → UAE E-Invoicing tab: *Enabled*, ASP = Flick Network L.L.C;
   *Allow credit note without original invoice* only if MOGAS needs it. Company Tax ID = TRN.
2. E-Invoice Provider Settings: one row per company (fields in §1) → *Verify Auth* →
   *Get Participant Details* → *Subscribe Webhook* (only if the site is reachable from the
   internet; otherwise the 5-minute status sync covers it — scheduler must be on).
3. Master data the Flick builder **refuses to send without** (found in testing):
   - Customer: Tax ID (TRN) for B2B, **PEPPOL ID**, *Legal Registration Identifier Type* and, for
     Commercial/Trade licence, **Trade License Number**; billing **Address** with Emirate.
   - Company address: phone + email (UAE supplier party).
   - Item: *Item Type Code* (Goods/Services/Both) + **HS code** (goods) / **SAC** (services).
   - Invoice must carry a **VAT tax row** (Sales Taxes and Charges template), and a due date.
   - Item Tax Template: *VAT Category* (+ exemption / RCM codes) for zero-rated, exempt and
     reverse-charge items — overrides the invoice-level category.
   - Mode of Payment: *Payment Means Code*.
4. B2C customers: tick *Is B2C Customer* on the Customer.

## 3. Risks to clear with Flick before production

| # | Risk | Why it matters | Proposed handling |
|---|---|---|---|
| 1 | **Self-billed Purchase Invoices go to Flick's `/v1/{participant}/simulate/incoming`** (upstream code). That is a sandbox simulation endpoint, not a real self-billing submission. | A ticked *Submit To FTA* PI would not actually be reported in production. | Keep *Submit To FTA* off for MOGAS until Flick confirms the self-billing endpoint; then change the URL in `flick/adapter.py`. |
| 2 | **Webhook listener is unauthenticated** (`allow_guest=True`, no check of the secret Flick returns on subscription). | Anyone who knows the URL could post a fake `reported` status for a known Document ID. | Ask Flick for their webhook signature header/algorithm and verify it with `webhook_secret`; until then, don't subscribe and rely on status sync (polls Flick directly). |
| 3 | Frequency of Billing is always sent (`DLY` default) because the builder requires it whenever posting + due date exist. Same as upstream. | Might be questioned for one-off invoices. | Confirm with Flick that `DLY` is acceptable, or which code to default to. |
| 4 | Submit is synchronous (HTTP to Flick inside the Submit click, 120 s timeout). Failures don't block the submit; status stays *Not Submitted* with a *Send Invoice* button. | Slow Flick = slow submit for UAE users. | Acceptable for go-live; can be moved to a background job later. |

## 4. Sandbox test run (once credentials arrive)

On a restored MOGAS UAT site (`bench-omc-v15`): follow `docs/TESTING_GUIDE.md` sections for
Flick (auth, participant, invoice 380, credit note 381, status, XML/PDF), plus the fork checks:
non-UAE company unaffected, two UAE companies independent, `tabSales Invoice` gets no new
columns.
