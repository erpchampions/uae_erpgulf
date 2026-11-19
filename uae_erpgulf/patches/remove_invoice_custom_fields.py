"""MOGAS fork: drop upstream's UAE custom fields from the invoice doctypes.

Their data lives on "UAE E-Invoice Submission". Fixtures no longer ship these
fields, but fixture sync never deletes, so a site that ever had them (an
upstream install, or an earlier build of this fork) is cleaned here.
Idempotent; a fresh install has nothing to remove.

Values still on those columns are NOT migrated - see docs/MOGAS_DETACH_PLAN.md
if a site needs a backfill first.
"""

import frappe

FIELDS = (
	("Purchase Invoice", "custom_column_break_6q5x3"),
	("Purchase Invoice", "custom_column_break_b0znq"),
	("Purchase Invoice", "custom_credit_note_reason_code"),
	("Purchase Invoice", "custom_document_id"),
	("Purchase Invoice", "custom_document_pdf"),
	("Purchase Invoice", "custom_document_status_response"),
	("Purchase Invoice", "custom_document_xml"),
	("Purchase Invoice", "custom_frequency_billing_code_list"),
	("Purchase Invoice", "custom_integration_responses"),
	("Purchase Invoice", "custom_invoice_note"),
	("Purchase Invoice", "custom_invoice_transaction_type_code"),
	("Purchase Invoice", "custom_payment_means_codes"),
	("Purchase Invoice", "custom_rcm_nature_code"),
	("Purchase Invoice", "custom_reporting_status"),
	("Purchase Invoice", "custom_submit_response"),
	("Purchase Invoice", "custom_submit_to_fta"),
	("Purchase Invoice", "custom_uae_einvoice_status"),
	("Purchase Invoice", "custom_uae_einvoice_status_notification"),
	("Purchase Invoice", "custom_uae_integration"),
	("Purchase Invoice", "custom_vat_category"),
	("Purchase Invoice", "custom_vat_exemption_reason_code"),
	("Purchase Invoice Item", "custom_hs_code_"),
	("Purchase Invoice Item", "custom_item_type_codes"),
	("Purchase Invoice Item", "custom_sac_code"),
	("Sales Invoice", "custom_column_break_dqzae"),
	("Sales Invoice", "custom_column_break_ear60"),
	("Sales Invoice", "custom_credit_note_reason_code"),
	("Sales Invoice", "custom_document_id"),
	("Sales Invoice", "custom_document_pdf"),
	("Sales Invoice", "custom_document_status_response"),
	("Sales Invoice", "custom_document_xml"),
	("Sales Invoice", "custom_frequency_billing_code_list"),
	("Sales Invoice", "custom_integration_responses"),
	("Sales Invoice", "custom_invoice_note"),
	("Sales Invoice", "custom_invoice_transaction_type_code"),
	("Sales Invoice", "custom_rcm_nature_code"),
	("Sales Invoice", "custom_reporting_status"),
	("Sales Invoice", "custom_return_against_for_uae_einvoice"),
	("Sales Invoice", "custom_section_break_nx3ls"),
	("Sales Invoice", "custom_skip_validation_for_credit_note"),
	("Sales Invoice", "custom_submit_response"),
	("Sales Invoice", "custom_uae_einvoice_status"),
	("Sales Invoice", "custom_uae_einvoice_status_notification"),
	("Sales Invoice", "custom_vat_category"),
	("Sales Invoice", "custom_vat_exemption_reason_code"),
	("Sales Invoice Item", "custom_hs_code_"),
	("Sales Invoice Item", "custom_item_type_codes"),
	("Sales Invoice Item", "custom_sac_code"),
)


def execute():
	for dt, fieldname in FIELDS:
		# only ours: MOGAS runs other country apps on the same doctypes
		name = frappe.db.get_value(
			"Custom Field", {"dt": dt, "fieldname": fieldname, "module": "uae_erpgulf"}
		)
		if name:
			frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
	frappe.clear_cache()
