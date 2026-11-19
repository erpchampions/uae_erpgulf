"""Shared query for the UAE E-Invoice Sales / Purchase Status reports.

MOGAS fork: UAE status lives on "UAE E-Invoice Submission", so the reports
join it onto the invoice. They are limited to one company (the report's
required Company filter, which upstream ignored), so other countries'
invoices never show up."""

import frappe
from frappe import _

from uae_erpgulf.uae_erpgulf.einvoice_record import DOCTYPE as RECORD_DOCTYPE

PARTY = {
	"Sales Invoice": ("customer_name", _("Customer")),
	"Purchase Invoice": ("supplier_name", _("Supplier")),
}


def get_columns(doctype):
	party_field, party_label = PARTY[doctype]
	return [
		{"fieldname": "name", "label": _("Inv. Number"), "fieldtype": "Link", "options": doctype, "width": 200},
		{"fieldname": "posting_date", "label": _("Date"), "fieldtype": "Date", "width": 140},
		{"fieldname": party_field, "label": party_label, "fieldtype": "Data", "width": 200},
		{"fieldname": "grand_total", "label": _("Total"), "fieldtype": "Currency", "width": 160},
		{"fieldname": "custom_reporting_status", "label": _("Reporting Status"), "fieldtype": "Data", "width": 160},
		{"fieldname": "custom_uae_einvoice_status", "label": _("UAE Status"), "fieldtype": "Data", "width": 180},
		{"fieldname": "document_id", "label": _("Document ID"), "fieldtype": "Data", "width": 220},
	]


def get_data(doctype, filters):
	party_field = PARTY[doctype][0]
	conditions = ["inv.docstatus < 2 OR %(status)s = 'Cancelled'"]
	params = {"doctype": doctype, "status": filters.get("status") or ""}

	if filters.get("company"):
		conditions.append("inv.company = %(company)s")
		params["company"] = filters.get("company")

	if filters.get("dt_from") and filters.get("dt_to"):
		conditions.append("inv.posting_date BETWEEN %(dt_from)s AND %(dt_to)s")
		params["dt_from"] = filters.get("dt_from")
		params["dt_to"] = filters.get("dt_to")

	if doctype == "Purchase Invoice":
		# only self-billed purchase invoices are reported to the FTA
		conditions.append("IFNULL(r.submit_to_fta, 0) = 1")

	status = filters.get("status")
	if status in ("Reported", "reported", "Reported From FTA"):
		conditions.append("LOWER(r.reporting_status) = 'reported'")
	elif status in ("Failed", "failed"):
		conditions.append("LOWER(r.reporting_status) = 'failed'")
	elif status in ("Success", "Success From ASP"):
		conditions.append("r.uae_einvoice_status = 'Success'")
	elif status == "Not Submitted":
		conditions.append(
			"(inv.docstatus = 0 OR IFNULL(r.uae_einvoice_status, '') IN ('', 'Not Submitted'))"
		)
	elif status == "Cancelled":
		conditions.append("inv.docstatus = 2")
	elif status:
		conditions.append("(r.reporting_status = %(status)s OR r.uae_einvoice_status = %(status)s)")

	where = " AND ".join(f"({c})" for c in conditions)
	return frappe.db.sql(
		f"""
		SELECT
			inv.name, inv.{party_field}, inv.posting_date, inv.grand_total, inv.docstatus,
			r.reporting_status AS custom_reporting_status,
			IFNULL(r.uae_einvoice_status, 'Not Submitted') AS custom_uae_einvoice_status,
			r.document_id
		FROM `tab{doctype}` inv
		LEFT JOIN `tab{RECORD_DOCTYPE}` r
			ON r.reference_doctype = %(doctype)s AND r.reference_name = inv.name
		WHERE {where}
		ORDER BY inv.posting_date DESC
		""",
		params,
		as_dict=True,
	)


@frappe.whitelist()
def get_dashboard_counts(company: str | None = None):
	"""Counts for the UAE E-Invoice Dashboard page, per invoice type."""
	out = {}
	for doctype in ("Sales Invoice", "Purchase Invoice"):
		frappe.has_permission(doctype, "read", throw=True)
		company_cond = "AND inv.company = %(company)s" if company else ""
		self_billed = "AND IFNULL(r.submit_to_fta, 0) = 1" if doctype == "Purchase Invoice" else ""
		row = frappe.db.sql(
			f"""
			SELECT
				SUM(LOWER(IFNULL(r.reporting_status, '')) = 'reported') AS reported,
				SUM(r.uae_einvoice_status = 'Success') AS success,
				SUM(LOWER(IFNULL(r.reporting_status, '')) = 'failed') AS failed,
				SUM(inv.docstatus < 2 AND IFNULL(r.uae_einvoice_status, 'Not Submitted') = 'Not Submitted') AS not_submitted,
				SUM(inv.docstatus = 2) AS cancelled
			FROM `tab{doctype}` inv
			INNER JOIN `tab{RECORD_DOCTYPE}` r
				ON r.reference_doctype = %(doctype)s AND r.reference_name = inv.name
			WHERE IFNULL(r.direction, 'Outgoing') = 'Outgoing' {company_cond} {self_billed}
			""",
			{"doctype": doctype, "company": company},
			as_dict=True,
		)[0]
		out[doctype] = {k: int(v or 0) for k, v in row.items()}
	return out


@frappe.whitelist()
def get_dashboard_rows(doctype: str, company: str | None = None, limit: int = 20):
	if doctype not in PARTY:
		frappe.throw(_("Invalid invoice type"))
	frappe.has_permission(doctype, "read", throw=True)
	party_field = PARTY[doctype][0]
	company_cond = "AND inv.company = %(company)s" if company else ""
	return frappe.db.sql(
		f"""
		SELECT inv.name, inv.{party_field} AS party, inv.posting_date, inv.grand_total,
			r.reporting_status, IFNULL(r.uae_einvoice_status, 'Not Submitted') AS uae_einvoice_status
		FROM `tab{doctype}` inv
		INNER JOIN `tab{RECORD_DOCTYPE}` r
			ON r.reference_doctype = %(doctype)s AND r.reference_name = inv.name
		WHERE IFNULL(r.direction, 'Outgoing') = 'Outgoing' {company_cond}
		ORDER BY inv.posting_date DESC, inv.creation DESC
		LIMIT %(limit)s
		""",
		{"doctype": doctype, "company": company, "limit": min(int(limit or 20), 200)},
		as_dict=True,
	)
