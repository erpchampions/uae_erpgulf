"""End-to-end checks for the uae_erpgulf MOGAS fork (no network: fake ASP).

THROWAWAY SITES ONLY - setup() creates companies, accounts, items, parties
and submits invoices. Never run on a client site.

    cp docs/testing/mogas_e2e_check.py <bench>/apps/frappe/frappe/zz_uae_test.py
    bench --site <test-site> execute frappe.zz_uae_test.setup
    bench --site <test-site> execute frappe.zz_uae_test.run      # expect 27/27
    bench --site <test-site> execute frappe.zz_uae_test.mk_drafts  # drafts for a manual UI check
    rm <bench>/apps/frappe/frappe/zz_uae_test.py

The ASP is faked (no HTTP); the Flick and Marmin payload builders run for real.
"""

import json

import frappe
from frappe.utils import add_days, nowdate

UAE1, UAE2, OTHER = "MOGAS UAE One", "MOGAS UAE Two", "MOGAS Other Country"
REC = "UAE E-Invoice Submission"
INVOICE_DTS = ("Sales Invoice", "Purchase Invoice", "Sales Invoice Item", "Purchase Invoice Item")
RESULTS = []


def check(label, cond, detail=""):
	RESULTS.append((bool(cond), label, detail))
	print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if detail and not cond else ""))


# ----------------------------------------------------------------- setup
def setup():
	for name, abbr, country, currency in ((UAE1, "MU1", "United Arab Emirates", "AED"), (UAE2, "MU2", "United Arab Emirates", "AED"), (OTHER, "MOC", "Burundi", "AED")):
		if not frappe.db.exists("Company", name):
			frappe.get_doc(
				{"doctype": "Company", "company_name": name, "abbr": abbr, "country": country,
				 "default_currency": currency, "chart_of_accounts": "Standard"}
			).insert()

	for company in (UAE1, UAE2):
		frappe.db.set_value("Company", company, {
			"custom_uae_einvoice_enabled": 1,
			"custom_accredited_service_providers": "Flick Network L.L.C",
			"custom_allow_creditnote_without_original_invoice_in_the_system": 1,
		})
		if not frappe.db.exists("E-Invoice Provider Settings", {"company": company}):
			frappe.get_doc({
				"doctype": "E-Invoice Provider Settings", "provider_name": f"{company} Flick",
				"company": company, "provider": "Flick Network L.L.C", "enabled": 1,
				"auth_type": "api_key", "participant_id": "TEST-PID", "base_url": "http://127.0.0.1:9",
			}).insert()

	for party_dt, name, group in (("Customer", "UAE Test Customer", "customer_group"), ("Supplier", "UAE Test Supplier", "supplier_group")):
		if not frappe.db.exists(party_dt, name):
			d = frappe.new_doc(party_dt)
			d.set(party_dt.lower() + "_name", name)
			d.set(group, frappe.db.get_value(party_dt + " Group", {"is_group": 0}, "name"))
			d.insert()

	if not frappe.db.exists("Item", "UAE-GOODS"):
		frappe.get_doc({
			"doctype": "Item", "item_code": "UAE-GOODS", "item_name": "UAE Goods", "is_stock_item": 0,
			"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"), "stock_uom": "Nos",
			"custom_item_type_codes": "G - Goods", "custom_hs_code_": "27101943",
		}).insert()
	for link_dt, link_name, title in (("Customer", "UAE Test Customer", "UAE Cust"), ("Supplier", "UAE Test Supplier", "UAE Supp"),
			("Company", UAE1, "UAE1 HQ"), ("Company", UAE2, "UAE2 HQ")):
		if not frappe.db.exists("Address", {"address_title": title}):
			a = frappe.get_doc({"doctype": "Address", "address_title": title, "address_type": "Billing",
				"address_line1": "Sheikh Zayed Rd 1", "city": "Dubai", "country": "United Arab Emirates",
				"emirate": "Dubai", "pincode": "00000", "is_primary_address": 1, "phone": "+971500000000", "email_id": "uae@example.com",
				"is_your_company_address": 1 if link_dt == "Company" else 0,
				"links": [{"link_doctype": link_dt, "link_name": link_name}]})
			a.insert()
			if link_dt == "Customer":
				frappe.db.set_value("Customer", link_name, "customer_primary_address", a.name)
			if link_dt == "Supplier":
				frappe.db.set_value("Supplier", link_name, "supplier_primary_address", a.name)
	frappe.db.set_value("Customer", "UAE Test Customer", {"tax_id": "100000000000003",
		"custom_peppol_id": "0235:1000000000", "custom_trade_license_number": "TL-12345",
		"custom_legal_registration_identifier_type": "Commercial/Trade license"})
	frappe.db.set_value("Company", UAE1, {"custom_peppol_id": "0235:1000000003"} if frappe.get_meta("Company").has_field("custom_peppol_id") else {})
	frappe.db.set_value("Company", UAE1, "tax_id", "100000000000003")
	for company, abbr in ((UAE1, "MU1"), (UAE2, "MU2")):
		if not frappe.db.exists("Account", f"VAT 5% - {abbr}"):
			frappe.get_doc({"doctype": "Account", "account_name": "VAT 5%", "company": company, "account_type": "Tax",
				"tax_rate": 5, "parent_account": frappe.db.get_value("Account", {"company": company, "account_name": "Duties and Taxes"})}).insert()
		# addresses already inserted before this fix: add phone
		for a in frappe.get_all("Address", filters={"address_title": ["like", "UAE%"]}, pluck="name"):
			frappe.db.set_value("Address", a, {"phone": "+971500000000", "email_id": "uae@example.com"})
	for company in (UAE1, UAE2, OTHER):
		frappe.db.set_value("Company", company, {
			"round_off_account": frappe.db.get_value("Account", {"company": company, "root_type": "Expense", "is_group": 0}),
			"round_off_cost_center": frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}),
		})
	frappe.db.commit()
	print("setup done")


# ------------------------------------------------------------ fake ASP
class FakeAdapter:
	AUTO_FETCH_DOCUMENTS_ON_SUBMIT = True
	seen = []

	def __init__(self, settings=None):
		self.settings = settings

	def submit_invoice(self, doctype, doc, json_data=None):
		FakeAdapter.seen.append({
			"doctype": doctype, "name": doc.name,
			"vat_category": doc.get("custom_vat_category"),
			"invoice_note": doc.get("custom_invoice_note"),
			"credit_note_reason_code": doc.get("custom_credit_note_reason_code"),
			"submit_to_fta": doc.get("custom_submit_to_fta"),
			"hs": [i.get("custom_hs_code_") for i in doc.items],
			"type": [i.get("custom_item_type_codes") for i in doc.items],
		})
		return 200, {"id": f"DOC-{doc.name}", "status": "success"}

	def parse_submit_response(self, status_code, response_data):
		from uae_erpgulf.uae_erpgulf.providers.base import BaseAdapter
		return BaseAdapter.parse_submit_response(self, status_code, response_data)

	def get_document_xml(self, doctype, doc):
		assert doc.get("custom_submit_response"), "hydrate missing submit_response"
		return "<Invoice/>"

	def get_document_pdf(self, doctype, doc):
		from io import BytesIO
		from pypdf import PdfWriter
		w = PdfWriter(); w.add_blank_page(width=72, height=72); buf = BytesIO(); w.write(buf)
		return buf.getvalue()

	def get_document_status(self, doctype, doc):
		return {"http_status": 200, "response": {"id": doc.custom_document_id, "reporting_status": "reported"},
				"reporting_status": "reported"}

	def get_status_from_document_status(self, body):
		return (body or {}).get("reporting_status")


def _patch_adapters():
	import uae_erpgulf.uae_erpgulf.attach as attach
	import uae_erpgulf.uae_erpgulf.send_purchase as sp
	import uae_erpgulf.uae_erpgulf.status_sync as ss
	import uae_erpgulf.uae_erpgulf.submit_sales as ssl
	import uae_erpgulf.uae_erpgulf.verify_token as vt

	for mod in (attach, sp, ss, ssl, vt):
		mod.get_adapter = FakeAdapter
	frappe.flags.mute_messages = True  # keep output readable (throw still raises)


def _si(company, qty=1, is_return=0, return_against=None, submit=False):
	si = frappe.new_doc("Sales Invoice")
	si.company = company
	si.customer = "UAE Test Customer"
	si.posting_date = nowdate()
	si.due_date = add_days(nowdate(), 30)
	si.currency = "AED"
	si.debit_to = frappe.db.get_value("Account", {"company": company, "account_type": "Receivable", "is_group": 0})
	si.is_return = is_return
	si.return_against = return_against
	si.append("items", {
		"item_code": "UAE-GOODS", "qty": qty, "rate": 100,
		"income_account": frappe.db.get_value("Account", {"company": company, "root_type": "Income", "is_group": 0}),
		"cost_center": frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}),
	})
	vat = frappe.db.get_value("Account", {"company": company, "account_name": "VAT 5%"})
	if vat:
		si.append("taxes", {"charge_type": "On Net Total", "account_head": vat, "rate": 5, "description": "VAT 5%",
			"cost_center": frappe.db.get_value("Cost Center", {"company": company, "is_group": 0})})
	si.insert()
	if submit:
		si.submit()
	return si


def _pi(company, submit=False, self_billed=False):
	from uae_erpgulf.uae_erpgulf.einvoice_record import save_inputs

	pi = frappe.new_doc("Purchase Invoice")
	pi.company = company
	pi.supplier = "UAE Test Supplier"
	pi.posting_date = nowdate()
	pi.due_date = add_days(nowdate(), 30)
	pi.currency = "AED"
	pi.credit_to = frappe.db.get_value("Account", {"company": company, "account_type": "Payable", "is_group": 0})
	pi.append("items", {
		"item_code": "UAE-GOODS", "qty": 1, "rate": 50,
		"expense_account": frappe.db.get_value("Account", {"company": company, "root_type": "Expense", "is_group": 0}),
		"cost_center": frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}),
	})
	pi.insert()
	if self_billed:
		save_inputs("Purchase Invoice", pi.name, {"submit_to_fta": 1, "vat_category": "S - Standard rated"})
	if submit:
		pi.submit()
	return pi


def _rec(dt, name):
	r = frappe.db.get_value(REC, {"reference_doctype": dt, "reference_name": name}, "*", as_dict=True)
	return r or frappe._dict()


# ------------------------------------------------------------------- run
def run():
	frappe.flags.in_test = True
	_patch_adapters()
	from uae_erpgulf.uae_erpgulf import einvoice_record as er
	from uae_erpgulf.uae_erpgulf import report_utils, status_sync

	# 0. schema: no UAE columns on invoice doctypes
	n = frappe.db.count("Custom Field", {"dt": ["in", INVOICE_DTS], "module": "uae_erpgulf"})
	check("no uae_erpgulf custom fields on invoice doctypes", n == 0, n)
	cols = frappe.db.sql(
		"""select table_name, column_name from information_schema.columns where table_schema=database()
		and table_name in ('tabSales Invoice','tabPurchase Invoice','tabSales Invoice Item','tabPurchase Invoice Item')
		and column_name in ('custom_vat_category','custom_document_id','custom_uae_einvoice_status','custom_hs_code_','custom_submit_to_fta')"""
	)
	check("no UAE columns in invoice tables", not cols, cols)
	check("master-data fields still installed (Item, Company)",
		frappe.get_meta("Item").has_field("custom_hs_code_") and frappe.get_meta("Company").has_field("custom_uae_einvoice_enabled"))

	# 1. sales invoice submit -> record, hydrated payload, state stored
	si = _si(UAE1)
	er.save_inputs("Sales Invoice", si.name, {"vat_category": "Z - Zero rated", "invoice_transaction_type_code": "XXXXXXX1 : Export transaction",
		"uae_einvoice_status": "Success"})  # state key must be ignored
	r = _rec("Sales Invoice", si.name)
	check("save_inputs ignores state fields", r.uae_einvoice_status == "Not Submitted", r.uae_einvoice_status)
	si.reload(); si.submit()
	seen = FakeAdapter.seen[-1]
	check("adapter got record inputs on doc", seen["vat_category"] == "Z - Zero rated" and seen["invoice_note"] == "Tax Invoice", seen)
	check("adapter got item codes from Item master", seen["hs"] == ["27101943"] and seen["type"] == ["G - Goods"], seen)
	r = _rec("Sales Invoice", si.name)
	check("SI record state after submit", r.uae_einvoice_status == "Success" and r.document_id == f"DOC-{si.name}"
		and r.reporting_status == "pending" and r.company == UAE1 and r.party == "UAE Test Customer", dict(r))
	check("XML/PDF attached to invoice, URLs on record",
		r.document_xml and r.document_pdf and frappe.db.exists("File", {"attached_to_name": si.name, "file_url": r.document_xml}), r)

	# 2. inputs locked after success
	try:
		er.save_inputs("Sales Invoice", si.name, {"vat_category": "S - Standard rated"})
		check("inputs locked after Success", False)
	except frappe.ValidationError:
		frappe.db.rollback() if False else None
		check("inputs locked after Success", True)

	# 3. cancel blocked once sent
	try:
		frappe.get_doc("Sales Invoice", si.name).cancel()
		check("cancel blocked for reported invoice", False)
	except frappe.ValidationError as e:
		check("cancel blocked for reported invoice", "cannot be cancelled" in str(e), str(e))

	# 4. status sync -> reported (via record table)
	status_sync.sync_pending_invoices()
	check("status sync set reporting_status=reported", _rec("Sales Invoice", si.name).reporting_status == "reported")

	# 5. webhook-style lookup by document id
	check("find_invoice_by_document_id", er.find_invoice_by_document_id("Sales Invoice", f"DOC-{si.name}") == si.name)

	# 6. non-UAE company untouched
	before = len(FakeAdapter.seen)
	other = _si(OTHER, submit=True)
	check("non-UAE company: no record, no send", not _rec("Sales Invoice", other.name) and len(FakeAdapter.seen) == before)
	info = er.get_einvoice_info("Sales Invoice", other.name)
	check("non-UAE company: form info disabled", info["enabled"] is False)
	other.cancel()
	check("non-UAE company: cancel works", other.docstatus == 2)

	# 7. second UAE company works independently
	si2 = _si(UAE2, submit=True)
	check("second UAE company submit", _rec("Sales Invoice", si2.name).uae_einvoice_status == "Success")

	# 8. credit note without original invoice (company allows) -> skips ERPNext item check
	cn = _si(UAE1, qty=-1, is_return=1)
	er.save_inputs("Sales Invoice", cn.name, {"credit_note_reason_code": "DL8.61.1.A-Cancellation",
		"return_against_for_uae_einvoice": "OLD-INV-001"})
	cn.reload(); cn.submit()
	check("credit note w/o original submitted & sent", FakeAdapter.seen[-1]["credit_note_reason_code"] == "DL8.61.1.A-Cancellation"
		and _rec("Sales Invoice", cn.name).is_return == 1)

	# 9. purchase invoice: ordinary bill not sent; self-billed sent
	before = len(FakeAdapter.seen)
	bill = _pi(UAE1, submit=True)
	check("ordinary PI not sent to ASP", len(FakeAdapter.seen) == before and _rec("Purchase Invoice", bill.name).uae_einvoice_status == "Not Submitted")
	sb = _pi(UAE1, submit=True, self_billed=True)
	r = _rec("Purchase Invoice", sb.name)
	check("self-billed PI sent", FakeAdapter.seen[-1]["submit_to_fta"] == 1 and r.uae_einvoice_status == "Success", dict(r))

	# 10. bulk PI: draft self-billed sent exactly once
	draft = _pi(UAE1, self_billed=True)
	before = len(FakeAdapter.seen)
	import uae_erpgulf.uae_erpgulf.send_purchase as sp
	res = sp.bulk_send_invoices([draft.name, bill.name])
	check("PI bulk: draft sent once, ordinary skipped", len(FakeAdapter.seen) == before + 1
		and draft.name in res["success"] and bill.name in res["skipped"], (res, len(FakeAdapter.seen) - before))

	# 11. amend copies inputs; delete draft removes record
	d = _si(UAE1)
	er.save_inputs("Sales Invoice", d.name, {"vat_category": "E - Exempt from tax", "vat_exemption_reason_code": "DL8.46.3 - Bare land"})
	rec_name = er.get_record_name("Sales Invoice", d.name)
	frappe.delete_doc("Sales Invoice", d.name)
	check("deleting draft SI removes its record", not frappe.db.exists(REC, rec_name))

	# 12. reports / dashboard limited by company
	rows = report_utils.get_data("Sales Invoice", {"company": UAE1})
	names = {x.name for x in rows}
	check("sales report filtered to company", si.name in names and si2.name not in names and other.name not in names)
	rows = report_utils.get_data("Purchase Invoice", {"company": UAE1})
	names = {x.name for x in rows}
	check("purchase report shows only self-billed", sb.name in names and bill.name not in names)
	counts = report_utils.get_dashboard_counts(UAE1)
	check("dashboard counts", counts["Sales Invoice"]["success"] >= 2, counts)
	from frappe.desk.query_report import run as run_report
	out = run_report("UAE E-Invoice Sales Status Report", filters={"company": UAE1, "status": "Success"})
	check("query report runs", len(out["result"]) >= 2, len(out["result"]))

	# 13. real Flick payload builder sees hydrated values
	try:
		from uae_erpgulf.uae_erpgulf.providers.flick import sales_json
		payload = sales_json.build_uae_invoice_json(si.name)
		blob = json.dumps(payload, default=str)
		check("Flick builder: hydrated values in payload", "27101943" in blob, blob[:300])
	except Exception as e:
		check("Flick builder ran", False, f"{type(e).__name__}: {e}")

	# 14. real Marmin payload builder
	try:
		from uae_erpgulf.uae_erpgulf.providers.marmin.adapter import MarminAdapter
		settings = frappe.get_doc("E-Invoice Provider Settings", {"company": UAE1})
		payload = MarminAdapter(settings)._build_invoice_payload(er.load_invoice("Sales Invoice", si.name))
		blob = json.dumps(payload, default=str)
		check("Marmin builder: zero-rated category in payload", '"Z"' in blob or "Zero" in blob, blob[:300])
	except Exception as e:
		check("Marmin builder ran", False, f"{type(e).__name__}: {e}")

	frappe.db.rollback()
	failed = [x for x in RESULTS if not x[0]]
	print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
	for _, label, detail in failed:
		print("  FAILED:", label, detail)


def mk_drafts():
	frappe.flags.mute_messages = True
	a = _si(UAE1)
	b = _si(OTHER)
	frappe.db.commit()
	print("DRAFTS", a.name, b.name)
