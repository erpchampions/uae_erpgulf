"""UAE E-Invoice Submission: per-invoice UAE data kept off the invoice doctypes.

MOGAS fork. Upstream stored ~20 custom fields on Sales Invoice and Purchase
Invoice (plus 3 on their item tables). MOGAS shares those doctypes across many
countries and cannot take more columns, so the data lives in the
"UAE E-Invoice Submission" doctype, one record per invoice.

The provider adapters still read ``doc.custom_<field>`` / ``item.custom_<field>``
exactly as upstream does. ``hydrate(doc)`` copies the record's values (and the
Item master's item codes) onto the in-memory invoice under those names before
an adapter sees it, so the payload builders stay untouched. Nothing is saved on
the invoice: the attributes are not in the invoice's meta, so Frappe never
writes them.

Writes that used to be ``doc.db_set("custom_x", v)`` go through ``set_state``.
"""

import frappe
from frappe import _

DOCTYPE = "UAE E-Invoice Submission"
SUPPORTED_DOCTYPES = ("Sales Invoice", "Purchase Invoice")
PREFIX = "custom_"

# user-chosen per invoice (record fieldname == upstream fieldname minus "custom_")
INPUT_FIELDS = (
	"submit_to_fta",
	"vat_category",
	"vat_exemption_reason_code",
	"rcm_nature_code",
	"invoice_transaction_type_code",
	"payment_means_codes",
	"frequency_billing_code_list",
	"invoice_note",
	"credit_note_reason_code",
	"return_against_for_uae_einvoice",
	"skip_validation_for_credit_note",
)

# written back from the ASP
STATE_FIELDS = (
	"uae_einvoice_status",
	"reporting_status",
	"document_id",
	"document_xml",
	"document_pdf",
	"submit_response",
	"document_status_response",
)

RECORD_FIELDS = INPUT_FIELDS + STATE_FIELDS

# read off the invoice's item rows by the adapters; taken from the Item master
ITEM_FIELDS = ("custom_item_type_codes", "custom_hs_code_", "custom_sac_code")

# Upstream's effective defaults, kept so payloads are unchanged. Upstream's
# Select custom fields had no blank option, so Frappe filled in the first
# one: VAT category "S" and frequency "DLY" were sent on every invoice (the
# Flick builder requires a frequency whenever posting + due date are set).
# Other Selects here have a blank option and stay empty unless chosen.
DEFAULTS = {
	"Sales Invoice": {
		"vat_category": "S - Standard rated",
		"frequency_billing_code_list": "DLY",
		"invoice_note": "Tax Invoice",
		"uae_einvoice_status": "Not Submitted",
	},
	"Purchase Invoice": {
		"vat_category": "S - Standard rated",
		"frequency_billing_code_list": "DLY",
		"invoice_note": "Tax Invoice Reporting",
		"uae_einvoice_status": "Not Submitted",
	},
}

PARTY_FIELD = {"Sales Invoice": "customer", "Purchase Invoice": "supplier"}


# --------------------------------------------------------------- company gate
def is_uae_company(company):
	return bool(company and frappe.get_cached_value("Company", company, "custom_uae_einvoice_enabled"))


def allows_credit_note_without_original(company):
	return bool(
		company
		and frappe.get_cached_value(
			"Company", company, "custom_allow_creditnote_without_original_invoice_in_the_system"
		)
	)


# ------------------------------------------------------------------- records
def get_record_name(doctype, name):
	if not (doctype and name):
		return None
	return frappe.db.get_value(DOCTYPE, {"reference_doctype": doctype, "reference_name": name})


def _header_values(doctype, name, doc=None):
	party_field = PARTY_FIELD[doctype]
	if doc is None:
		doc = frappe.db.get_value(
			doctype, name, ["company", "posting_date", "is_return", party_field], as_dict=True
		) or frappe._dict()
	return {
		"company": doc.get("company"),
		"posting_date": doc.get("posting_date"),
		"is_return": 1 if doc.get("is_return") else 0,
		"party": doc.get(party_field),
	}


def ensure_record(doctype, name, doc=None, direction=None):
	"""Return the record name for this invoice, creating it (with upstream
	defaults, or the inputs of the invoice it was amended from) if missing.
	Header fields (company, date, party, is_return) are refreshed from the
	invoice when ``doc`` is given."""
	if doctype not in SUPPORTED_DOCTYPES:
		frappe.throw(_("UAE e-invoicing is not supported for {0}").format(doctype))

	existing = get_record_name(doctype, name)
	if existing:
		if doc is not None:
			frappe.db.set_value(DOCTYPE, existing, _header_values(doctype, name, doc), update_modified=False)
		return existing

	header = _header_values(doctype, name, doc)

	values = dict(DEFAULTS.get(doctype, {}))
	amended_from = doc.get("amended_from") if doc is not None else frappe.db.get_value(doctype, name, "amended_from")
	if amended_from:
		source = get_record_name(doctype, amended_from)
		if source:
			values.update(
				{k: v for k, v in frappe.db.get_value(DOCTYPE, source, list(INPUT_FIELDS), as_dict=True).items() if v not in (None, "")}
			)

	record = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"reference_doctype": doctype,
			"reference_name": name,
			"direction": direction or "Outgoing",
			**header,
			**values,
		}
	)
	record.flags.ignore_permissions = True
	record.insert()
	return record.name


def get_state(doctype, name, fields=None):
	"""Record values (record fieldnames, no prefix) for this invoice.
	Missing record -> upstream defaults, so callers never get None."""
	fields = list(fields or RECORD_FIELDS)
	record = get_record_name(doctype, name)
	if record:
		return frappe._dict(frappe.db.get_value(DOCTYPE, record, fields, as_dict=True) or {})
	defaults = DEFAULTS.get(doctype, {})
	return frappe._dict({f: defaults.get(f) for f in fields})


def set_state(doctype, name, values, doc=None, update_modified=True):
	"""Replacement for ``invoice.db_set("custom_<field>", value)``.
	``values`` uses record fieldnames (no ``custom_`` prefix). If ``doc`` is
	given, the in-memory invoice is updated too, so later reads in the same
	request see the new value."""
	unknown = set(values) - set(RECORD_FIELDS)
	if unknown:
		frappe.throw(_("Unknown UAE e-invoice field(s): {0}").format(", ".join(sorted(unknown))))

	record = ensure_record(doctype, name)
	frappe.db.set_value(DOCTYPE, record, values, update_modified=update_modified)
	if doc is not None:
		for field, value in values.items():
			doc.set(PREFIX + field, value)
	return record


def find_invoice_by_document_id(doctype, document_id):
	"""Replacement for ``frappe.db.get_value(doctype, {"custom_document_id": x})``."""
	if not document_id:
		return None
	return frappe.db.get_value(
		DOCTYPE, {"reference_doctype": doctype, "document_id": document_id}, "reference_name"
	)


# ------------------------------------------------------------------- overlay
def hydrate(doc):
	"""Put the record's values on the in-memory invoice as ``custom_<field>``
	and the Item master's codes on each item row, the way upstream adapters
	expect them. Returns ``doc``. Safe to call more than once."""
	if doc is None or doc.doctype not in SUPPORTED_DOCTYPES:
		return doc

	state = get_state(doc.doctype, doc.name) if doc.name and not doc.is_new() else frappe._dict(
		DEFAULTS.get(doc.doctype, {})
	)
	for field in RECORD_FIELDS:
		value = state.get(field)
		# a site that still has upstream's custom fields keeps its own value
		# when this invoice has no record value
		if value is not None or doc.get(PREFIX + field) is None:
			doc.set(PREFIX + field, value)

	for item in doc.get("items") or []:
		missing = [f for f in ITEM_FIELDS if item.get(f) is None]
		master = (
			frappe.get_cached_value("Item", item.item_code, missing, as_dict=True)
			if missing and item.get("item_code")
			else None
		) or {}
		for f in missing:
			item.set(f, master.get(f))
	return doc


def load_invoice(doctype, name):
	"""``frappe.get_doc`` + ``hydrate``."""
	return hydrate(frappe.get_doc(doctype, name))


# ----------------------------------------------------------------- doc hooks
def on_invoice_trash(doc, method=None):
	"""A deleted draft takes its record with it (otherwise the Dynamic Link
	would block the delete). A record the ASP accepted is never removed."""
	record = get_record_name(doc.doctype, doc.name)
	if not record:
		return
	if frappe.db.get_value(DOCTYPE, record, "uae_einvoice_status") == "Success":
		return
	frappe.delete_doc(DOCTYPE, record, ignore_permissions=True, force=True)


# ------------------------------------------------------------- client calls
def _check_invoice_permission(doctype, name, ptype):
	if doctype not in SUPPORTED_DOCTYPES:
		frappe.throw(_("UAE e-invoicing is not supported for {0}").format(doctype))
	if not frappe.has_permission(doctype, ptype, name):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


@frappe.whitelist()
def get_einvoice_info(doctype: str, name: str | None = None, company: str | None = None):
	"""Everything the invoice form needs: is UAE on for this company, may a
	credit note skip the original, and the record values (if any)."""
	if name:
		_check_invoice_permission(doctype, name, "read")
		company = company or frappe.db.get_value(doctype, name, "company")
	enabled = is_uae_company(company)
	info = {
		"enabled": enabled,
		"allow_cn_without_original": allows_credit_note_without_original(company) if enabled else False,
		"record": None,
		"values": {},
	}
	if enabled and name:
		info["record"] = get_record_name(doctype, name)
		info["values"] = get_state(doctype, name)
	return info


@frappe.whitelist()
def save_inputs(doctype: str, name: str, values: dict | str):
	"""Upsert the per-invoice inputs (the dialog shown before Submit, or the
	"E-Invoice Details" button). Only INPUT_FIELDS are accepted."""
	_check_invoice_permission(doctype, name, "write")
	values = frappe.parse_json(values) if isinstance(values, str) else (values or {})
	clean = {k: v for k, v in values.items() if k in INPUT_FIELDS}

	record = frappe.get_doc(DOCTYPE, ensure_record(doctype, name))
	record.update(clean)
	record.flags.ignore_permissions = True
	record.save()
	return record.name
