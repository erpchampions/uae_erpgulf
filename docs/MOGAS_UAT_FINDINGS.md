# MOGAS UAE e-invoicing — UAT findings (2026-11-21)

Run on a local restore of the MOGAS production backup of 2026-10-28 (`bench-omc-v15`, Frappe
15.108.0 / ERPNext 15.108.3, same 11 apps as production), with `uae_erpgulf@mogas-dev` installed.
Every outbound HTTP call was blocked; the ASP was faked for submits; the real Flick payload
builder was used for dry runs. No call to Flick or any tax authority was made.

## 1. Results

| Area | Result |
|---|---|
| Install on the production copy | 14 s, no errors. **Sales / Purchase Invoice and their item tables: 0 new columns** (240 / 169 / 125 / 112, unchanged). Master data gained: Company +3, Customer +5, Item +3, Supplier +5 columns; Address `emirate` already existed. |
| Other apps' invoice hooks (EFRIS, VFD, regional) | Run on UAE invoices with **no outbound calls** (they are company-gated). |
| Non-UAE companies (Burundi, Kenya, Mauritius, Tanzania, Uganda, Kioga) | Draft invoices save and delete; no UAE record, no UAE UI. |
| Saving every Company | All save except **MOGAS Congo**: duplicate Cost Center "MOGAS Congo - CG". No `uae_erpgulf` code in the traceback; existing data issue, not caused by this app. |
| UAE submit through MOGAS's workflow | MOGAS International: *Submit* → Approved. MOGAS DMCC: invoices become Debit Memos → *Submit for Approval → Review → Approve*. Both reach the ASP (faked), as Administrator **and as a real MOGAS Accounts User**. |
| Browser, as an Accounts User | Workflow *Submit* opens the UAE E-Invoice Details dialog; choices saved; invoice Approved; send failure (no customer address) does not block it; indicator "Not Submitted to FTA". |
| Automated suites | Throwaway site 37/37; production copy 43/44 (the Congo item above). |

## 2. Fixed in the fork as a result

| # | Problem found | Fix |
|---|---|---|
| 1 | MOGAS submits invoices with **workflow actions**, which never fire `before_submit`, so the UAE dialog would never appear. | Dialog also opens on a workflow action that leads to a submitted state (`before_workflow_action`). |
| 2 | **Wrong AED exchange rate.** Both UAE companies keep books in **USD**; upstream sent ERPNext's `conversion_rate` (to company currency) = **1.0** for USD invoices, so every AED amount reported to the FTA would be wrong. | Invoice currency → AED rate: via company currency, USD peg 3.6725 for USD books, or Currency Exchange records (`aed_rate.py`). |
| 3 | Totals mixed company-currency and invoice-currency amounts when prices include tax. | Builders use invoice-currency totals only. |
| 4 | **No MOGAS UAE sales invoice has a tax row** (exports / out of scope). Upstream builder crashed (`IndexError`). | No tax row = 0 % VAT; a *Standard rated* line at 0 % is refused with a clear message. |
| 5 | Exports need a foreign **delivery address** (Flick / PINT-AE ibr-152-ae); upstream never sent one. | Export invoices carry `delivery` from the Shipping Address or the customer address; a UAE delivery address is refused. |
| 6 | Builder demanded Emirate, post code and email for **every** buyer (impossible for Tanzanian / Ugandan customers). | Emirate only for UAE addresses; post code and email optional (as in Flick's docs). |
| 7 | Buyer `vat_number` sent for foreign buyers (e.g. `"0"`); Flick requires a 15-digit UAE TRN there. | Sent only for UAE buyers. |
| 8 | Every invoice claimed a billing period "DLY" from posting to due date (e.g. 30 Sep–4 Dec "daily"). | Invoice period sent only if a Frequency of Billing is chosen, or for summary invoices (where upstream checked the wrong flag). |
| 9 | A failed send was only in the Error Log. | Reason also stored on the UAE E-Invoice Submission record (`submit_response`). |

## 3. What MOGAS must decide or fix (cannot be done by us)

**Tax treatment (MOGAS's tax advisor):** in the last 12 months the UAE companies issued ~112
sales invoices, **none with VAT**, mostly to customers in Tanzania / Uganda (incl. intra-group
management fees to MOGAS Uganda). For each kind of sale MOGAS must confirm: zero-rated export
(`Z` + Export), out of scope (`O`), or other — and whether e-invoicing applies to those
transactions at all under the UAE rollout. 9 DMCC invoices are in **UGX**.

**Master data** (`docs/testing/mogas_readiness_check.py`; detail CSV kept outside the repo):

| Gap | Count |
|---|---|
| Company TRN (Tax ID) — both UAE companies | 2 |
| Customers billed by UAE companies: PEPPOL ID | 7 of 7 |
| … TRN or trade licence (needed for credit notes and non-export) | 5 |
| … billing address missing / incomplete (~half of all UAE invoices have no customer address) | 3 + |
| Items sold: Item Type (Goods / Services) + HS or SAC code | 13 of 13 |
| Item Tax Templates of UAE companies: VAT Category | 6 |
| Modes of Payment: Payment Means Code | 64 |

Data-quality example seen: a MOGAS Uganda customer address with country *Tanzania*, city
*Uganda*; a management-fee item that is a service, not goods.

**Process:** decide who fills the UAE dialog (the workflow's final *Submit*/*Approve* step shows
it; inputs can also be set earlier with *E-Invoice Details*). DMCC Sales Invoices run the Debit
Memo approval chain.

## 4. Needed from Flick

See `MOGAS_FLICK_GO_LIVE.md` §1 and §5 (credentials and participant IDs; `/v1` vs `/v3`;
self-billing, export `metadata`/`flags` and `delivery` on `/v1`; webhook signature; PDF endpoint;
rate limits).
