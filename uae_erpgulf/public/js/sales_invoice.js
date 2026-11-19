// Sales Invoice - UAE e-invoicing (MOGAS fork). Logic in uae_einvoice_form.js;
// nothing here touches invoice fields, and it is inert for non-UAE companies.
frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		uae_erpgulf_einvoice.refresh(frm);
	},
	before_submit(frm) {
		return uae_erpgulf_einvoice.before_submit(frm);
	},
});
