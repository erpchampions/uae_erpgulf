# Copyright (c) 2026, erpgulf.com / ERP Champions and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from uae_erpgulf.uae_erpgulf.einvoice_record import INPUT_FIELDS, SUPPORTED_DOCTYPES


class UAEEInvoiceSubmission(Document):
	"""UAE e-invoicing data for one Sales / Purchase Invoice.

	MOGAS fork: these used to be custom fields on the invoice itself. They live
	here so Sales Invoice / Purchase Invoice get no extra columns."""

	def validate(self):
		if self.reference_doctype not in SUPPORTED_DOCTYPES:
			frappe.throw(_("Invoice Type must be one of {0}").format(", ".join(SUPPORTED_DOCTYPES)))

		duplicate = frappe.db.get_value(
			self.doctype,
			{
				"reference_doctype": self.reference_doctype,
				"reference_name": self.reference_name,
				"name": ["!=", self.name],
			},
		)
		if duplicate:
			frappe.throw(
				_("{0} {1} already has a UAE E-Invoice Submission: {2}").format(
					_(self.reference_doctype), self.reference_name, duplicate
				)
			)

		if self.frequency_billing_code_list == "OTH" and not self.invoice_note:
			frappe.throw(_("Invoice Note is mandatory when Frequency Billing Code is OTH."))

		self._block_input_changes_after_success()

	def _block_input_changes_after_success(self):
		if self.is_new() or self.uae_einvoice_status != "Success":
			return
		before = self.get_doc_before_save()
		if not before:
			return
		changed = [f for f in INPUT_FIELDS if (self.get(f) or None) != (before.get(f) or None)]
		if changed:
			frappe.throw(
				_(
					"This invoice was already accepted by the ASP. E-invoice details can no longer be "
					"changed ({0}). Issue a credit note instead."
				).format(", ".join(changed))
			)
