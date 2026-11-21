"""MOGAS UAE e-invoicing: checks on a RESTORED COPY of MOGAS production.

Never run on production. Every outbound HTTP call (any host other than
localhost) is blocked and recorded, so neither Flick nor another app's
integration (EFRIS, VFD, ...) is ever reached. The ASP is faked for the
submit flow; the real Flick payload builder is used for the dry run.

    cp docs/testing/mogas_uat_check.py <bench>/apps/frappe/frappe/zz_uae_uat.py
    bench --site <uat-site> execute frappe.zz_uae_uat.safety      # scheduler + email off (commits)
    bench --site <uat-site> execute frappe.zz_uae_uat.enable_uae  # UAE flags + fake Flick settings (commits)
    bench --site <uat-site> execute frappe.zz_uae_uat.run         # checks (creates and submits test invoices)
    rm <bench>/apps/frappe/frappe/zz_uae_uat.py
"""

import json
from collections import Counter
from urllib.parse import urlparse

import frappe
from frappe.utils import add_days, add_months, nowdate

RESULTS = []
BLOCKED = []
UAE_PID = "0235:TEST-ONLY"


def check(label, cond, detail=""):
	RESULTS.append((bool(cond), label, detail))
	print(("PASS " if cond else "FAIL ") + label + ("" if cond else f"  [{detail}]"), flush=True)


def note(label, detail):
	print(f"INFO {label}: {detail}", flush=True)


# ------------------------------------------------------------------ safety
def guard():
	"""Block every outbound HTTP request except localhost; record attempts."""
	import requests

	if getattr(requests.Session.request, "_uae_guard", False):
		return
	real = requests.Session.request

	def blocked(self, method, url, *a, **kw):
		host = (urlparse(url).hostname or "").lower()
		if host in ("localhost", "127.0.0.1"):
			return real(self, method, url, *a, **kw)
		BLOCKED.append(f"{method} {host}")
		raise requests.ConnectionError(f"UAT guard: outbound call to {host} blocked")

	blocked._uae_guard = True
	requests.Session.request = blocked


def uae_companies():
	return frappe.get_all("Company", filters={"country": "United Arab Emirates"}, pluck="name", order_by="name")


def safety():
	frappe.db.set_single_value("System Settings", "enable_scheduler", 0)
	for ea in frappe.get_all("Email Account", pluck="name"):
		frappe.db.set_value("Email Account", ea, {"enable_outgoing": 0, "enable_incoming": 0})
	frappe.db.commit()
	conf = frappe.get_site_config()
	print("scheduler off; email accounts disabled;", "mute_emails:", conf.get("mute_emails"),
		  "pause_scheduler:", conf.get("pause_scheduler"))


def enable_uae():
	for company in uae_companies():
		frappe.db.set_value("Company", company, {
			"custom_uae_einvoice_enabled": 1,
			"custom_accredited_service_providers": "Flick Network L.L.C",
		})
		if not frappe.db.exists("E-Invoice Provider Settings", {"company": company}):
			frappe.get_doc({
				"doctype": "E-Invoice Provider Settings", "provider_name": f"{company} Flick (UAT fake)",
				"company": company, "provider": "Flick Network L.L.C", "enabled": 1,
				"auth_type": "api_key", "api_key": "uat-fake", "participant_id": UAE_PID,
				"base_url": "http://127.0.0.1:9",
			}).insert(ignore_permissions=True)
	frappe.db.commit()
	print("UAE e-invoicing enabled (fake Flick, unreachable URL) for", uae_companies())


# ------------------------------------------------------------- fake ASP
class FakeAdapter:
	AUTO_FETCH_DOCUMENTS_ON_SUBMIT = False
	seen = []

	def __init__(self, settings=None):
		self.settings = settings

	def submit_invoice(self, doctype, doc, json_data=None):
		FakeAdapter.seen.append((doctype, doc.name, doc.get("custom_vat_category")))
		return 200, {"id": f"UAT-{doc.name}", "status": "success"}

	def parse_submit_response(self, status_code, response_data):
		from uae_erpgulf.uae_erpgulf.providers.base import BaseAdapter
		return BaseAdapter.parse_submit_response(self, status_code, response_data)

	def get_document_status(self, doctype, doc):
		return {"http_status": 200, "response": {"reporting_status": "reported"}, "reporting_status": "reported"}

	def get_status_from_document_status(self, body):
		return (body or {}).get("reporting_status")


def _fake_asp(on=True):
	import uae_erpgulf.uae_erpgulf.send_purchase as sp
	import uae_erpgulf.uae_erpgulf.status_sync as ss
	import uae_erpgulf.uae_erpgulf.submit_sales as ssl
	from uae_erpgulf.uae_erpgulf import providers

	for mod in (sp, ss, ssl):
		mod.get_adapter = FakeAdapter if on else providers.get_adapter


# ----------------------------------------------------------------- checks
def coexistence():
	n = frappe.db.count("Custom Field", {"dt": ["in", ["Sales Invoice", "Purchase Invoice", "Sales Invoice Item",
		"Purchase Invoice Item"]], "module": "uae_erpgulf"})
	check("no uae_erpgulf custom fields on invoices", n == 0, n)
	added = frappe.db.sql("""SELECT dt, COUNT(*) FROM `tabCustom Field` WHERE module='uae_erpgulf' GROUP BY dt""")
	note("uae_erpgulf master-data custom fields", dict(added))
	for dt in ("Sales Invoice", "Purchase Invoice"):
		cols = [c for c in frappe.db.get_table_columns(dt) if "uae" in c.lower() or c in (
			"custom_vat_category", "custom_document_id", "custom_submit_to_fta")]
		check(f"no UAE columns on tab{dt}", not cols, cols)
		note(f"{dt} columns", len(frappe.db.get_table_columns(dt)))
	hooks = frappe.get_hooks("doc_events")
	for dt in ("Sales Invoice", "Purchase Invoice"):
		events = {}
		for key in ("*", dt):
			for ev, fns in (hooks.get(key) or {}).items():
				events.setdefault(ev, []).extend(fns if isinstance(fns, list) else [fns])
		note(f"{dt} on_submit hooks (all apps)", events.get("on_submit"))
	js = frappe.get_hooks("doctype_js")
	note("Sales Invoice doctype_js", js.get("Sales Invoice"))


def company_save():
	for co in frappe.get_all("Company", pluck="name"):
		try:
			frappe.get_doc("Company", co).save()
			ok, err = True, ""
		except Exception as e:
			ours = "uae_erpgulf" in frappe.get_traceback()
			ok, err = False, f"{type(e).__name__}: {e} | uae_erpgulf in traceback: {ours}"
		check(f"Company '{co}' saves", ok, err)
	frappe.db.rollback()


def dry_run(months=12, limit=300, inputs=None):
	"""Build the real Flick payload (no send) for MOGAS's own UAE invoices."""
	from uae_erpgulf.uae_erpgulf.einvoice_record import hydrate
	from uae_erpgulf.uae_erpgulf.providers.flick import sales_json

	since = add_months(nowdate(), -int(months))
	rows = frappe.get_all("Sales Invoice", filters={"company": ["in", uae_companies()], "docstatus": 1,
		"posting_date": [">=", since]}, fields=["name", "company", "currency", "is_return"],
		order_by="posting_date desc", limit=limit)
	errors, currencies, rates, ok = Counter(), Counter(), Counter(), 0
	from uae_erpgulf.uae_erpgulf import einvoice_record as er
	saved_defaults = {k: dict(v) for k, v in er.DEFAULTS.items()}
	if inputs:
		er.DEFAULTS["Sales Invoice"].update(inputs)
	for r in rows:
		currencies[(r.company, r.currency)] += 1
		try:
			payload = sales_json.build_uae_invoice_json(r.name)
			p = payload.get("document", payload) if isinstance(payload, dict) else {}
			rates[(r.currency, p.get("currency_exchange_rate"))] += 1
			ok += 1
		except Exception as e:
			msg = str(e).split("<br>")
			for m in msg:
				errors[m.strip()[:140]] += 1
		finally:
			frappe.local.message_log = []
	er.DEFAULTS.clear(); er.DEFAULTS.update(saved_defaults)
	frappe.db.rollback()
	print(f"\n=== Flick dry run with inputs {inputs or 'defaults (S - Standard rated)'} ===")
	note("dry-run invoices (company, currency)", dict(currencies))
	note("dry-run payloads built", f"{ok}/{len(rows)}")
	note("currency -> exchange rate sent", dict(rates))
	print("Blocking errors (count  message):")
	for m, n in errors.most_common(25):
		print(f"  {n:5}  {m}")
	return ok, len(rows), errors


def open_periods():
	"""Test-only: MOGAS's accounting periods are closed up to the end of the
	year; lift the lock in this process so copies can be posted today."""
	from erpnext.accounts import general_ledger
	from erpnext.accounts.doctype.accounting_period import accounting_period

	accounting_period.validate_accounting_period_on_doc_save = lambda *a, **k: None
	general_ledger.validate_accounting_period = lambda *a, **k: None


def _copy_invoice(doctype, company, user=None):
	src = frappe.get_all(doctype, filters={"company": company, "docstatus": 1, "is_return": 0},
		order_by="posting_date desc", limit=1, pluck="name")
	if not src:
		return None
	doc = frappe.copy_doc(frappe.get_doc(doctype, src[0]))
	doc.posting_date = nowdate()
	doc.set_posting_time = 1
	doc.due_date = add_days(nowdate(), 30)
	if doctype == "Purchase Invoice":
		doc.bill_no = f"UAT-{frappe.generate_hash(length=6)}"
	doc.update_stock = 0
	if doc.meta.has_field("workflow_state"):
		doc.workflow_state = "Draft"
	if doc.meta.has_field("custom_memo_type"):
		doc.custom_memo_type = "Tax Invoice"
	for row in doc.items:
		for f in ("sales_order", "so_detail", "delivery_note", "dn_detail", "purchase_order", "po_detail",
				  "purchase_receipt", "pr_detail"):
			if row.meta.has_field(f):
				row.set(f, None)
	for row in doc.get("payment_schedule") or []:
		row.due_date = doc.due_date
	return doc


def _through_workflow(doc, user):
	"""Walk MOGAS's approval workflow to a submitted document: the first step
	as ``user``, later approvals as Administrator (stand-in for the approvers)."""
	from frappe.model.workflow import apply_workflow, get_transitions

	if not frappe.get_meta(doc.doctype).has_field("workflow_state"):
		doc.submit()
		return doc
	steps = []
	for i in range(8):
		if doc.docstatus == 1:
			break
		frappe.set_user(user if i == 0 else "Administrator")
		actions = [t.action for t in get_transitions(doc) if t.action not in ("Reject", "Cancel")]
		if not actions:
			raise frappe.ValidationError(f"workflow stuck at {doc.workflow_state} after {steps}")
		steps.append(actions[0])
		doc = apply_workflow(doc, actions[0])
	frappe.set_user(user)
	note(f"{doc.name} workflow", " -> ".join(steps))
	return doc


def submit_flow(user=None):
	"""Copy a recent real UAE invoice, submit it as ``user`` with the fake ASP."""
	from uae_erpgulf.uae_erpgulf.einvoice_record import get_einvoice_info, get_state, save_inputs

	who = user or "Administrator"
	_fake_asp(True)
	frappe.flags.mute_messages = True
	try:
		for company in uae_companies():
			frappe.set_user("Administrator")
			si = _copy_invoice("Sales Invoice", company)
			if not si:
				note(f"{company}", "no submitted Sales Invoice to copy")
				continue
			frappe.set_user(who)
			try:
				si.insert()
				info = get_einvoice_info("Sales Invoice", si.name)
				check(f"[{who}] {company}: form info enabled", info["enabled"], info)
				save_inputs("Sales Invoice", si.name, {"vat_category": "Z - Zero rated", "invoice_transaction_type_code": "XXXXXXX1 : Export transaction"})
				before = len(BLOCKED)
				si = _through_workflow(si, who)
				st = get_state("Sales Invoice", si.name)
				check(f"[{who}] {company}: SI {si.name} submitted and sent", si.docstatus == 1 and st.uae_einvoice_status == "Success"
					  and st.document_id == f"UAT-{si.name}", dict(st))
				check(f"[{who}] {company}: no outbound calls from other apps on submit", len(BLOCKED) == before, BLOCKED[before:])
			except Exception as e:
				check(f"[{who}] {company}: SI submit flow", False, f"{type(e).__name__}: {e}")
			finally:
				frappe.local.message_log = []
	finally:
		frappe.set_user("Administrator")
		_fake_asp(False)


def non_uae():
	from uae_erpgulf.uae_erpgulf.einvoice_record import get_einvoice_info, get_record_name

	frappe.flags.mute_messages = True
	others = [c for c in frappe.get_all("Company", pluck="name") if c not in uae_companies()]
	for company in others:
		si = _copy_invoice("Sales Invoice", company)
		if not si:
			continue
		try:
			si.insert()
			check(f"non-UAE {company}: draft saves, no UAE record", not get_record_name("Sales Invoice", si.name))
			check(f"non-UAE {company}: form info disabled", get_einvoice_info("Sales Invoice", si.name)["enabled"] is False)
			frappe.delete_doc("Sales Invoice", si.name)
			check(f"non-UAE {company}: draft deletes", not frappe.db.exists("Sales Invoice", si.name))
		except Exception as e:
			check(f"non-UAE {company}: draft insert/delete", False, f"{type(e).__name__}: {e}")
		finally:
			frappe.local.message_log = []
	frappe.db.rollback()


def accounts_user():
	"""A real MOGAS user with Accounts User (not System Manager) who may see a UAE company."""
	users = frappe.db.sql_list("""
		SELECT DISTINCT u.name FROM `tabUser` u
		JOIN `tabHas Role` r ON r.parent = u.name AND r.role = 'Accounts User'
		WHERE u.enabled = 1 AND u.user_type = 'System User' AND u.name NOT IN ('Administrator', 'Guest')
		  AND NOT EXISTS (SELECT 1 FROM `tabHas Role` s WHERE s.parent = u.name AND s.role = 'System Manager')
		ORDER BY u.last_login DESC""")
	for u in users:
		perms = frappe.get_all("User Permission", filters={"user": u, "allow": "Company"}, pluck="for_value")
		if not perms or set(perms) & set(uae_companies()):
			if all(frappe.has_permission("Sales Invoice", "submit", user=u) for _ in [0]):
				return u
	return None


def run(months=12):
	guard()
	open_periods()
	frappe.flags.mute_emails = True
	print("UAE companies:", uae_companies())
	coexistence()
	company_save()
	non_uae()
	submit_flow()
	u = accounts_user()
	note("Accounts User used", u)
	if u:
		submit_flow(u)
		from uae_erpgulf.uae_erpgulf import report_utils
		frappe.set_user(u)
		try:
			report_utils.get_data("Sales Invoice", {"company": uae_companies()[0]})
			check(f"[{u}] status report runs", True)
		except Exception as e:
			check(f"[{u}] status report runs", False, f"{type(e).__name__}: {e}")
		frappe.set_user("Administrator")
	dry_run(months)
	dry_run(months, inputs={"vat_category": "Z - Zero rated",
		"invoice_transaction_type_code": frappe.get_meta("UAE E-Invoice Submission").get_field(
			"invoice_transaction_type_code").options.split("\n")[-1]})
	note("outbound calls blocked", Counter(BLOCKED))
	failed = [x for x in RESULTS if not x[0]]
	print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
	for _, label, detail in failed:
		print("  FAILED:", label, detail)


def sample_payload(name=None):
	"""Build the Flick payload for one real MOGAS DMCC export invoice after
	filling ONLY its missing master data with placeholders. Rolled back."""
	from uae_erpgulf.uae_erpgulf import einvoice_record as er
	from uae_erpgulf.uae_erpgulf.providers.flick import sales_json

	guard()
	frappe.flags.mute_messages = True
	if not name:
		name = frappe.db.sql("""SELECT si.name FROM `tabSales Invoice` si JOIN tabAddress a ON a.name = si.customer_address
			WHERE si.company = 'MOGAS DMCC' AND si.docstatus = 1 AND si.is_return = 0 AND si.currency = 'USD'
			  AND a.country != 'United Arab Emirates' AND si.name NOT LIKE '2680DM001%%'
			ORDER BY si.posting_date DESC LIMIT 1""")[0][0]
	si = frappe.get_doc("Sales Invoice", name)
	filled = []
	for it in {i.item_code for i in si.items}:
		if not frappe.db.get_value("Item", it, "custom_item_type_codes"):
			frappe.db.set_value("Item", it, {"custom_item_type_codes": "G - Goods", "custom_hs_code_": "27101943"})
			filled.append(f"Item {it}: type G + HS 27101943 (placeholder)")
	c = frappe.db.get_value("Customer", si.customer, ["custom_peppol_id", "custom_trade_license_number"], as_dict=True)
	if not c.custom_peppol_id:
		frappe.db.set_value("Customer", si.customer, "custom_peppol_id", "9999:PLACEHOLDER")
		filled.append("Customer PEPPOL ID (placeholder)")
	if not c.custom_trade_license_number:
		frappe.db.set_value("Customer", si.customer, "custom_trade_license_number", "TL-PLACEHOLDER")
		filled.append("Customer trade licence (placeholder)")
	frappe.clear_cache()
	saved = {k: dict(v) for k, v in er.DEFAULTS.items()}
	er.DEFAULTS["Sales Invoice"].update({"vat_category": "Z - Zero rated",
		"invoice_transaction_type_code": "XXXXXXX1 : Export transaction"})
	try:
		p = sales_json.build_uae_invoice_json(name)
		p = p.get("document", p)
		print("invoice", name, si.currency, "company currency",
			  frappe.get_cached_value("Company", si.company, "default_currency"), "conversion_rate", si.conversion_rate)
		print("filled:", filled)
		show = {k: p.get(k) for k in ("document_type", "document_currency", "currency_exchange_rate", "metadata",
			"invoice_period", "delivery", "receiving_party", "legal_monetary_total", "invoice_totals")}
		show["first_line"] = (p.get("invoice_lines") or [None])[0]
		print(json.dumps(show, indent=1, default=str))
	except Exception as e:
		print("BUILD FAILED:", type(e).__name__, e, "| filled:", filled)
	finally:
		er.DEFAULTS.clear(); er.DEFAULTS.update(saved)
		frappe.db.rollback()


UI_USER = "uae.uat.tester@example.com"


def mk_ui_draft(company="MOGAS International"):
	"""Test-only user (roles copied from a real Accounts User, password
	'UatTest#2026') and a draft invoice in workflow state Draft."""
	open_periods()
	src_user = accounts_user()
	if not frappe.db.exists("User", UI_USER):
		u = frappe.get_doc({"doctype": "User", "email": UI_USER, "first_name": "UAE UAT Tester",
			"send_welcome_email": 0, "user_type": "System User"})
		u.insert(ignore_permissions=True)
	u = frappe.get_doc("User", UI_USER)
	u.set("roles", [])
	for r in frappe.get_roles(src_user):
		if r not in ("Guest", "All", "Administrator"):
			u.append("roles", {"role": r})
	u.new_password = "UatTest#2026"
	u.save(ignore_permissions=True)
	for up in frappe.get_all("User Permission", filters={"user": src_user}, fields=["allow", "for_value", "apply_to_all_doctypes"]):
		if not frappe.db.exists("User Permission", {"user": UI_USER, "allow": up.allow, "for_value": up.for_value}):
			frappe.get_doc({"doctype": "User Permission", "user": UI_USER, **up}).insert(ignore_permissions=True)
	si = _copy_invoice("Sales Invoice", company)
	si.owner = UI_USER
	si.insert(ignore_permissions=True)
	frappe.db.commit()
	print("UI_DRAFT", si.name, si.workflow_state, "roles from", src_user)
