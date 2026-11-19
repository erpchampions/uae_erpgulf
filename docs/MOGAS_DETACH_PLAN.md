# UAE E-Invoicing for MOGAS — Analysis & Solution Approach

Fork: `erpchampions/uae_erpgulf`, working branch `mogas-dev` (based on `main` @ `c3459de`).
Reference pattern: `erpchampions/burundi-compliance` @ `mogas-dev` (OBR Invoice Submission).

---

## 1. Findings

### 1.1 The upstream app is frozen — and refuses new installs

`main` @ `c3459de` (2026-10-27) is the **final** `uae_erpgulf` release. ERPGulf superseded it with
`einvoice_erpgulf` (multi-country, UAE + Oman). Consequences:

- `hooks.py` → `before_install = "uae_erpgulf.install.refuse_new_install"` **throws** on any new
  site install. We must remove this in the fork or MOGAS cannot install it at all.
- No more upstream fixes. That's acceptable: our fork diverges heavily anyway (same as Burundi),
  and a frozen base is a stable target. `einvoice_erpgulf` is ~3 weeks old and adds **27** Sales
  Invoice fields (more, not fewer), so moving to it would not avoid this work.

**Recommendation:** stay on the `uae_erpgulf` fork as planned.

### 1.2 What the app adds to Sales Invoice today

Fixture `custom_field.json` (filter `module = uae_erpgulf`) installs:

| Target | Fields | Kind |
|---|---|---|
| **Sales Invoice** | **21** | 9 inputs, 9 state/output, 3 layout breaks |
| **Sales Invoice Item** | **3** | `custom_item_type_codes`, `custom_hs_code_`, `custom_sac_code` |
| Purchase Invoice | 21 | (self-billing; same pattern) |
| Purchase Invoice Item | 3 | |
| Company | 5 | enable flag, ASP select, allow-CN-without-original |
| Customer / Supplier | 5 + 5 | PEPPOL id, trade licence, legal-reg type, FZ beneficiary |
| Item | 3 | item type / HS / SAC |
| Item Tax Template | 3 | VAT category, exemption reason, RCM nature |
| Address, Mode of Payment | 1 + 1 | emirate, payment-means code |

Sales Invoice fields split into:

- **Per-invoice inputs** (user-chosen, read by the payload builders):
  `custom_vat_category`, `custom_vat_exemption_reason_code`, `custom_rcm_nature_code`,
  `custom_invoice_transaction_type_code`, `custom_frequency_billing_code_list`,
  `custom_invoice_note`, `custom_credit_note_reason_code`,
  `custom_skip_validation_for_credit_note`, `custom_return_against_for_uae_einvoice`
- **State written back from the ASP:** `custom_uae_einvoice_status`, `custom_reporting_status`,
  `custom_document_id`, `custom_document_xml`, `custom_document_pdf`, `custom_submit_response`,
  `custom_document_status_response`, `custom_uae_einvoice_status_notification` (HTML badge)
- **Layout:** `custom_section_break_nx3ls`, `custom_column_break_dqzae`, `custom_integration_responses` (tab)

Only Sales Invoice / Sales Invoice Item are the stated constraint. Master doctypes (Company,
Customer, Item, Item Tax Template, Address, Mode of Payment) stay as they are.

### 1.3 Where those fields are touched (Sales side)

| Area | Files | Nature |
|---|---|---|
| Submit flow | `submit_sales.py`, `validation.py` (`block_cancel_if_reported`) | reads + `db_set` of state |
| Payload builders | `providers/pint.py`, `flick/sales_json.py`, `marmin/adapter.py`, `suntech/adapter.py`, `fynamics/adapter.py` | reads inputs + item codes; adapters `db_set` responses |
| Status / docs | `status_sync.py`, `verify_token.py`, `attach.py`, `webhook.py` | reads/writes state |
| Return override | `overrides/return_validation.py` | reads `custom_skip_validation_for_credit_note` |
| UI | `public/js/sales_invoice.js`, `badge_sales.js`, `tooltip.js`, `bulk_submit.js` | reads state / decorates input fields |
| Reporting | sales status report, dashboard page, workspace | filter/group on state columns |

16 `db_set`/`set_value` writes of `custom_*` state across Python; ~8 Sales Invoice queries in
reports/dashboard/sync.

### 1.4 Multi-country safety (important for MOGAS)

MOGAS runs many countries on one Sales Invoice doctype. Upstream already gates the server flow on
`Company.custom_uae_einvoice_enabled`, **but**:

- `doctype_js` for Sales Invoice (`sales_invoice.js`, `tooltip.js`, `badge_sales.js`) runs for
  **every** company — buttons/badges/tooltips must be gated by company too.
- `overrides/return_validation.py` monkey-patches ERPNext's `validate_returned_items` globally at
  import time. Harmless while the flag is off, but must key off the new record, not an SI field.
- `before_cancel` (`block_cancel_if_reported`) runs for every company; it reads state only, so it
  just needs to read from the new record.
- On-submit is **synchronous** (HTTP call to the ASP inside the SI submit). Failures are caught and
  don't block submit. We keep that behaviour (matches upstream; user sees the response popup).

### 1.5 Burundi pattern — what to reuse, what to do better

Burundi moved all OBR fields into a submittable **`OBR Invoice Submission`** doctype, created on SI
`on_submit`, and moved the API calls onto that doctype's events. Lessons:

- ✅ Keep: companion doctype 1:1 with the invoice; SI stays stock; status checked on the companion.
- ⚠️ Burundi rewrote every reader (`doc.custom_x` → companion field), duplicating the POS branch
  in each function. UAE has **4 adapters + PINT layer** reading those fields — rewriting each is
  large and error-prone.
- ⚠️ Burundi passes the user's prompt value via `doc.__payment_type` on submit — fragile.

---

## 2. Solution approach

### 2.1 New doctype: `UAE E-Invoice Submission`

Non-submittable, `autoname: format:UAE-EINV-{reference_name}` (one per invoice), track changes on.

| Field | Type | Notes |
|---|---|---|
| `reference_doctype` | Link → DocType | `Sales Invoice` now; leaves room for Purchase Invoice |
| `reference_name` | Dynamic Link | unique with doctype |
| `company`, `posting_date`, `customer`, `is_return` | Data/Link (read-only, copied) | for list filters & reports without joins |
| **Inputs** | | |
| `vat_category`, `vat_exemption_reason_code`, `rcm_nature_code` | Select | same options as upstream |
| `invoice_transaction_type_code`, `frequency_billing_code_list`, `invoice_note` | Select/Data | |
| `credit_note_reason_code` | Select | mandatory when `is_return` |
| `skip_validation_for_credit_note`, `return_against_for_uae_einvoice` | Check / Data | CN without original |
| **State** | | |
| `uae_einvoice_status`, `reporting_status`, `document_id` | Data | indexed (`search_index`) |
| `document_xml`, `document_pdf` | Data (file URL) | files stay attached to the **Sales Invoice** |
| `submit_response`, `document_status_response` | Long Text | |

Field names = upstream names **without the `custom_` prefix**, so the mapping is mechanical.

### 2.2 Keep adapters untouched: an "overlay" instead of rewriting readers

New module `uae_erpgulf/uae_erpgulf/einvoice_record.py`:

```python
INPUT_FIELDS = [...]          # 9 per-invoice inputs
STATE_FIELDS = [...]          # 7 state fields
ITEM_FIELDS  = ["custom_item_type_codes", "custom_hs_code_", "custom_sac_code"]

def get_record(doctype, name, create=False) -> Document | None
def hydrate(doc):
    """Copy record inputs + state onto the in-memory invoice as custom_* attributes,
    and item codes from the Item master onto each item row. Nothing is saved."""
def set_state(doctype, name, values: dict):
    """Replacement for doc.db_set('custom_x', v) — writes to the record."""
def get_state(doctype, name, fields) -> dict
```

- `doc.get("custom_vat_category")` in `pint.py` / adapters keeps working because `hydrate()` sets
  the attribute on the in-memory document → **payload builders need no logic changes**.
- Item codes come from the **Item** master (which already has the same three fields), so Sales
  Invoice Item needs no custom fields.
- Every `db_set("custom_…")` / `frappe.db.set_value(<invoice>, …, "custom_…")` on Sales Invoice is
  replaced by `set_state(...)` (16 call sites; Purchase Invoice paths left as-is).
- Every state read (`frappe.db.get_value("Sales Invoice", …, "custom_…")`) goes through `get_state`.
- Reports / dashboard / status-sync queries move from `tabSales Invoice.custom_*` to the
  `tabUAE E-Invoice Submission` table (it carries company/date/customer, so mostly no join).

Entry points call `hydrate(doc)` once: `generate_and_send_einvoice`, `bulk_send_invoices`,
`refresh_invoice_status`, `attach.get_document_xml/pdf`, `verify_token`, webhook handler.

### 2.3 Capturing per-invoice inputs (before submit)

1. **Defaults from masters** (most invoices need no input): VAT category / exemption / RCM from the
   line's Item Tax Template (fields already exist there); transaction type blank by default.
2. **UAE details dialog on Submit**, only when `Company.custom_uae_einvoice_enabled`:
   SI JS intercepts `before_submit`, opens a dialog pre-filled from the record/defaults
   (credit-note reason required for returns), calls whitelisted
   `einvoice_record.save_inputs(sales_invoice, values)` which **upserts** the record, then lets
   the submit proceed. No `__payment_type`-style smuggling on the doc.
3. Also a **"UAE E-Invoice ▸ Details"** button on the draft/submitted SI to open/edit the record
   (e.g. before a Re-submit).

Server-side, `on_submit` calls `get_record(..., create=True)` so the record always exists even for
API / bulk / data-import submits (defaults applied).

### 2.4 Credit note without original (`return_validation.py`)

Patch keeps working but reads `skip_validation_for_credit_note` from the record
(`get_record("Sales Invoice", doc.name)`), and only when the company has
`custom_allow_creditnote_without_original_invoice_in_the_system`. Requires the SI to be saved once
(has a name) before the flag can be set — the dialog in 2.3 covers the submit path.

### 2.5 UI on Sales Invoice (no fields)

- `sales_invoice.js` / `badge_sales.js`: fetch state via `frappe.db.get_value("UAE E-Invoice
  Submission", …)` (or a small whitelisted `get_state`) and render with `frm.dashboard.set_headline`
  / `frm.page.set_indicator` instead of the HTML custom field. Buttons (Send, Get Status, Get
  XML/PDF) unchanged, all gated by a cached company-enabled check.
- `tooltip.js` dropped for SI (it decorated fields that no longer exist) — tooltips move to the
  record form.
- List view: `bulk_submit.js` stays on Sales Invoice list (bulk action, no fields). A UAE status
  column is available on the **UAE E-Invoice Submission** list (filters: company, status, reporting).
- Sales Invoice dashboard "Connections" link to the record (via `override_doctype_dashboards`).

### 2.6 Install / migrate

- Remove `before_install = refuse_new_install`.
- Delete the 21 Sales Invoice + 3 Sales Invoice Item entries from `fixtures/custom_field.json`.
- Patch `remove_sales_invoice_custom_fields`: deletes those Custom Fields if present (idempotent).
  MOGAS UAE is a fresh install, so **no data backfill** is needed (a backfill patch can be added
  later for non-MOGAS sites).
- `pyproject.toml`: declare `frappe >=15,<17` (MOGAS prod is Frappe 15.108).

### 2.7 Scope decision (2026-11-19)

- **Purchase Invoice is in scope** too (team decision): its 21 + 3 fields move to the same
  record. Only PIs with *Submit To FTA (Self-billed)* ticked are sent to the ASP.
- Master-data fields (Company, Customer, Supplier, Item, Item Tax Template, Address, MoP) unchanged.

Implemented on `mogas-dev`; see `docs/fork-architecture.md` for the as-built description.

---

## 3. Work plan & testing

| # | Step | Est. |
|---|---|---|
| 1 | Remove install guard; new doctype + `einvoice_record.py` | 0.5 d |
| 2 | Re-route submit / validation / status-sync / attach / webhook / verify_token | 1 d |
| 3 | Adapters: replace `db_set` writes; item codes via hydrate | 0.5 d |
| 4 | SI JS: dialog, indicator, buttons, company gating; drop tooltip | 1 d |
| 5 | Reports, dashboard page, workspace on the new table | 0.5 d |
| 6 | Fixtures cleanup + removal patch + `docs/fork-architecture.md` | 0.5 d |
| 7 | Test on a MOGAS prod-mirror site: install, 2 UAE companies + 1 non-UAE company; invoice, CN, CN-without-original, bulk, status sync, cancel block; confirm **0** new columns on `tabSales Invoice` | 1 d |

Test bench: `bench-omc-v15` (MOGAS prod mirror). Its `_mogas_uat` database is currently **missing**
on `mariadb-v15-ecl` — it needs a fresh restore from a recent MOGAS prod backup before step 7.

## 4. Open inputs needed from MOGAS / team

1. **Which ASP** the two UAE companies use (Flick, Marmin, Suntech; Fynamics is disabled upstream)
   and sandbox credentials — determines which adapter we test end-to-end.
2. Do they need **self-billed Purchase Invoices** (would bring PI into scope)?
3. Any UAE invoices already issued from ERPNext (would need a backfill)?
