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
   - Customer: **PEPPOL ID**; Tax ID (UAE TRN) or **Trade License Number** (TL always needed for
     credit notes); billing **Address** (Emirate only for UAE addresses). Exports: a Shipping
     Address (or customer address) outside the UAE.
   - Company address: phone + email (UAE supplier party).
   - Item: *Item Type Code* (Goods/Services/Both) + **HS code** (goods) / **SAC** (services).
   - Standard-rated invoices need a **VAT tax row**; zero-rated / exempt / out-of-scope invoices
     may have none (choose the category in the UAE dialog).
   - Non-AED invoices: nothing to do for USD (peg 3.6725); other currencies need a Currency
     Exchange record to AED (or to the company currency).
   - Item Tax Template: *VAT Category* (+ exemption / RCM codes) for zero-rated, exempt and
     reverse-charge items — overrides the invoice-level category.
   - Mode of Payment: *Payment Means Code*.
4. B2C customers: tick *Is B2C Customer* on the Customer.

## 3. Risks and what was done about them (updated 2026-11-21)

Sources: Flick's public UAE docs (https://docs.flick.network/global-einvoicing/uae-einvoicing) and
an unauthenticated probe of `sb-ae-api.flick.network` (no credentials, no data sent).

| # | Topic | Status |
|---|---|---|
| 1 | **Self-billed Purchase Invoices.** Upstream posted them to `/v1/{participant}/simulate/incoming`, a sandbox simulation. Flick's docs: self-billing is `document_type` 380/381 + `flags.is_selfbilled: true` on the normal documents endpoint; the supplier stays `issuing_party` (seller), the buyer is `receiving_party`, Flick swaps roles in the XML. | **Changed in the fork** (`flick/adapter.py`, `flick/purchase_json.py`): PI now goes to `/v1/{participant}/documents` with 380/381 + `is_selfbilled`, supplier as `issuing_party`, the UAE company as `receiving_party` (Peppol ID = provider settings participant ID, TRN = Company Tax ID, company address). Builder verified by e2e check; **needs one sandbox submit** before ticking *Submit To FTA* in production. |
| 2 | **Webhook listener is guest-accessible** and Flick's signature format is not public. | **Neutralised in the fork:** the listener no longer trusts the status in the body. It logs the call and queues an authenticated status pull from Flick (same as *Get Status* / status sync). A forged call can at most trigger a refresh. Bodies over 256 KB are rejected. Signature verification can be added later if Flick documents it; not required. |
| 3 | Frequency of Billing / invoice period. | **Changed:** no longer defaulted to `DLY`; `invoice_period` is sent only when a frequency is chosen or for summary invoices (Flick docs: optional otherwise). |
| 4 | Submit is synchronous (HTTP inside the Submit click, 120 s timeout). | Flick docs: validation errors return 400 synchronously; delivery is asynchronous (`status: processing`). So the submit call should be quick. Unchanged. |
| 5 | **API version.** The fork calls `/v1/...`; Flick's current public docs only show `/v3/...` (different JSON in places, e.g. `identifiers`). Probe: `/v1/auth/verify`, `/v1/oauth/token`, `/v1/webhooks/subscriptions` all exist in the sandbox (401/400, unknown paths 404). | `/v1` works today. **Ask Flick** whether `/v1` stays supported for go-live or a move to `/v3` is required. |
| 7 | **Exports / no-VAT invoices** (all MOGAS UAE sales so far). | **Changed:** builder handles invoices without a tax row, sends `metadata.is_export` and a foreign `delivery` address, relaxes buyer Emirate / post code / email for foreign buyers, sends buyer TRN only for UAE buyers. Ask Flick to confirm `delivery` and `metadata` on `/v1`. See `MOGAS_UAT_FINDINGS.md`. |
| 8 | **AED exchange rate** for USD-books companies. | **Fixed:** rate is invoice currency → AED (was → company currency = 1.0 for USD). |
| 6 | Not in public docs: webhook signing, OAuth details, PDF endpoint, rate limits. | Ask Flick (questions in §5). The fork does not depend on any of them (API key auth works; status sync polls). |

## 4. Sandbox test run (once credentials arrive)

On a restored MOGAS UAT site (`bench-omc-v15`): follow `docs/TESTING_GUIDE.md` sections for
Flick (auth, participant, invoice 380, credit note 381, status, XML/PDF), plus the fork checks:
non-UAE company unaffected, two UAE companies independent, `tabSales Invoice` gets no new
columns.

## 5. Questions to send Flick

1. Is `/v1` supported for production go-live, or must we move to `/v3`? Timeline for `/v1` retirement?
2. Self-billing on `/v1/{participant}/documents`: is `is_selfbilled` honoured (we send it in `metadata` and `flags`, with 380/381)?
3b. Exports on `/v1`: are `metadata.is_export` and the `delivery` block (as in the `/v3` export example) accepted?
3. Webhook deliveries: signature header and algorithm (we will verify if available).
4. PDF retrieval endpoint for a document (the fork calls `/v1/{participant}/documents/{id}/pdf`).
5. Rate limits for submit and status polling (status sync polls up to 50 documents every 5 minutes).
6. Sandbox: credentials + Participant ID for each of MOGAS's two UAE companies.
