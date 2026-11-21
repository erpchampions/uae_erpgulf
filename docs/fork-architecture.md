# uae_erpgulf — ERP Champions fork (`mogas-dev`)

> Supplements the upstream docs in this folder (`USER_GUIDE.md`, `DEVELOPER_GUIDE.md`,
> `TESTING_GUIDE.md`). Read those for the UAE / PINT-AE / ASP concepts; this page covers what is
> **different** in the fork. Same idea as `erpchampions/burundi-compliance@mogas-dev`.

## 1. Why the fork exists

MOGAS runs many countries on one ERPNext site, all sharing **Sales Invoice** and **Purchase
Invoice**. Those doctypes cannot take more custom fields. Upstream adds 21 fields to each invoice
and 3 to each invoice item table. This fork adds **none**.

Upstream `uae_erpgulf` is retired (superseded by `einvoice_erpgulf`) and refuses new installs.
The fork disables that guard (`hooks.py`, `before_install` commented out).

## 2. `UAE E-Invoice Submission`

One record per invoice (`reference_doctype` + `reference_name`, Dynamic Link). Not submittable,
so it never blocks cancelling or amending the invoice.

| Group | Fields (upstream name minus `custom_`) |
|---|---|
| Header (copied) | `company`, `posting_date`, `party`, `is_return`, `direction` (Outgoing / Incoming) |
| Inputs | `submit_to_fta`, `vat_category`, `vat_exemption_reason_code`, `rcm_nature_code`, `invoice_transaction_type_code`, `payment_means_codes`, `frequency_billing_code_list`, `invoice_note`, `credit_note_reason_code`, `return_against_for_uae_einvoice`, `skip_validation_for_credit_note` |
| State (from the ASP) | `uae_einvoice_status`, `reporting_status`, `document_id`, `document_xml`, `document_pdf`, `submit_response`, `document_status_response` |

The XML / PDF **files** are still attached to the invoice; the record holds their URLs.
Inputs are locked once `uae_einvoice_status` is `Success`.

## 3. How the code uses it (`uae_erpgulf/uae_erpgulf/einvoice_record.py`)

- `hydrate(doc)` / `load_invoice(doctype, name)` — copies the record onto the **in-memory**
  invoice as `custom_<field>`, and `custom_item_type_codes` / `custom_hs_code_` /
  `custom_sac_code` from the **Item master** onto each item row. The provider adapters
  (`providers/flick|marmin|suntech|fynamics`, `pint.py`) read those attributes exactly as upstream
  does, so their payload logic is unchanged. Nothing is written to the invoice.
- `set_state(doctype, name, {...})` — replaces every `invoice.db_set("custom_…")`.
- `get_state(...)`, `find_invoice_by_document_id(...)` — replace reads / webhook look-ups.
- `ensure_record(...)` — creates the record (upstream defaults, or the inputs of the invoice it
  was amended from). Called on submit, so API / bulk / import submits get one too.
- Whitelisted `get_einvoice_info`, `save_inputs` — used by the form script.

## 4. User flow

1. Company → UAE E-Invoicing tab: enable, pick the ASP (unchanged from upstream).
2. Submit a Sales Invoice of a UAE company → a **UAE E-Invoice Details** dialog opens, pre-filled
   (VAT category defaults to Standard; a line's Item Tax Template VAT category still overrides).
   Credit notes must give a reason code. *Save & Submit* stores the record and submits; the
   invoice goes to the ASP on submit as upstream.
3. Purchase Invoice: the dialog asks **Submit To FTA (Self-billed)**. Only ticked invoices are
   sent. (Upstream sent every Purchase Invoice of a UAE company unless the ASP was Flick.)
4. On the invoice: an indicator *UAE E-Invoice: …* and a **UAE E-Invoice** button group (Send
   Invoice, Get Document Status, Get XML / PDF, E-Invoice Details, Open E-Invoice Record).
5. Status overview: the **UAE E-Invoice Submission** list, the two status reports and the
   dashboard page — all read the record and are limited to the chosen company.

Companies without UAE e-invoicing see no dialog, no buttons, no indicator.

## 5. Other behaviour changes vs upstream

| Area | Change |
|---|---|
| Credit note without original invoice | No per-invoice checkbox needed: if the Company allows it and Return Against is empty, ERPNext's returned-item check is skipped. With Return Against set, the record's `skip_validation_for_credit_note` still applies. |
| Purchase bulk send | Draft invoices were sent twice (submit hook + explicit send); fixed. Non-self-billed ones are skipped. |
| Form buttons | Upstream called `frm.clear_custom_buttons()` on every Sales / Purchase Invoice refresh (wiping other apps' buttons); removed. *Get FTA Incoming Invoices* and *Match & Approve* only show for UAE companies. |
| Status reports | Upstream ignored the required Company filter and listed every company's invoices; now filtered. |
| Status sync | Skips imported (Incoming) supplier invoices. |
| Imported supplier invoices | Document ID / status / payment means go on the record (`direction = Incoming`). |
| Tooltips / HTML ribbon | Removed with the fields; help text is on the dialog. |
| Creating a Company | Upstream validated the ASP on **every** Company; its Select has no blank option, so every new company (any country) got an ASP without an adapter and could not be saved. Now only validated when UAE e-invoicing is enabled on that company. |
| Flick webhook | Upstream stored whatever status the (unauthenticated) webhook body said. Now the body is only a trigger: an authenticated status pull is queued; bodies over 256 KB are refused. |
| Flick self-billed Purchase Invoice | Upstream posted to `/simulate/incoming` (sandbox simulation). Now `/documents` with 380/381 + `flags.is_selfbilled`, supplier as seller, company as buyer, per Flick's docs. Needs a sandbox confirmation. |
| Workflow submit | Invoices submitted through a workflow action (MOGAS) get the UAE dialog too (`before_workflow_action`). |
| Flick: currency | Exchange rate is invoice currency → AED (upstream: → company currency, wrong for USD-books companies). Totals no longer mix company-currency amounts. |
| Flick: no tax row / exports | Invoices without a tax row build at 0 % (Standard rated at 0 % is refused); exports send `metadata.is_export` + `delivery`; buyer Emirate only for UAE addresses, post code / email optional, buyer TRN only for UAE buyers. |
| Flick: invoice period | Sent only when a Frequency of Billing is chosen or for summary invoices; `DLY` no longer defaulted. |
| Failed send | Reason stored on the record's `submit_response` (prefixed `NOT SENT:`). |
| Select defaults | Upstream's invoice Selects had no blank option, so Frappe silently stored the first option (e.g. exemption reason *DL8.46.1*, credit-note reason *Cancellation*). On the record these are blank unless chosen; VAT category *S* stays the explicit default; frequency is blank unless chosen. |

## 6. Install / upgrade

```bash
bench get-app https://github.com/erpchampions/uae_erpgulf.git --branch mogas-dev
bench --site <site> install-app uae_erpgulf
bench --site <site> migrate
```

Patch `uae_erpgulf.patches.remove_invoice_custom_fields` deletes upstream's invoice custom fields
(only those owned by module `uae_erpgulf`) if a site ever had them. It does **not** migrate their
values: a site that already used upstream needs a backfill into `UAE E-Invoice Submission` first.
MOGAS is a fresh install, so none is needed.

Check after install: `SELECT COUNT(*) FROM tabCustom Field WHERE dt IN ('Sales Invoice','Purchase
Invoice','Sales Invoice Item','Purchase Invoice Item') AND module='uae_erpgulf'` → `0`.

## 7. Testing

`docs/testing/mogas_e2e_check.py`: 37 checks on a throwaway site (fake ASP, real Flick + Marmin
payload builders). Verified 2026-11-19 on Frappe 15.108.0 / ERPNext 15.108.3 (MOGAS prod
versions): 27/27; 37/37 after the 2026-11-21 changes, plus a browser run of the Submit dialog, indicator and buttons on a UAE company
and no UAE UI on a non-UAE company.


`docs/testing/mogas_readiness_check.py`: read-only master-data check for a real site (customers,
items, tax templates, modes of payment, companies the Flick builder would refuse).

`docs/testing/mogas_uat_check.py` + `mogas_uat_ui_check.py`: on a restored copy of MOGAS
production (outbound HTTP blocked, fake ASP, real workflow, real Accounts User); results in
`docs/MOGAS_UAT_FINDINGS.md`.
