"""MOGAS UAE e-invoicing: master-data readiness for Flick. READ-ONLY.

Lists the UAE companies' customers, items, item tax templates and modes of
payment that the Flick payload builder (providers/flick/sales_json.py) would
refuse, so they can be fixed before go-live. Safe on a production copy:
it only reads.

    cp docs/testing/mogas_readiness_check.py <bench>/apps/frappe/frappe/zz_uae_ready.py
    bench --site <site> execute frappe.zz_uae_ready.run
    bench --site <site> execute frappe.zz_uae_ready.run --kwargs "{'months': 6, 'csv_path': '/tmp/uae_ready.csv'}"
    rm <bench>/apps/frappe/frappe/zz_uae_ready.py

Scope: companies whose country is United Arab Emirates (or that already have
UAE e-invoicing enabled); customers / items on their submitted Sales Invoices
in the last ``months`` months.
"""

import csv

import frappe
from frappe.utils import add_months, nowdate


def _has(doctype, field):
	return frappe.get_meta(doctype).has_field(field)


def uae_companies():
	cos = set(frappe.get_all("Company", filters={"country": "United Arab Emirates"}, pluck="name"))
	if _has("Company", "custom_uae_einvoice_enabled"):
		cos |= set(frappe.get_all("Company", filters={"custom_uae_einvoice_enabled": 1}, pluck="name"))
	return sorted(cos)


def _address_for_customer(cust):
	name = cust.get("customer_primary_address")
	if not name:
		name = frappe.db.get_value(
			"Dynamic Link",
			{"link_doctype": "Customer", "link_name": cust.name, "parenttype": "Address"},
			"parent",
		)
	return frappe.db.get_value(
		"Address", name, ["name", "address_line1", "city", "emirate", "pincode", "country", "email_id", "phone"],
		as_dict=True,
	) if name and _has("Address", "emirate") else (
		frappe.db.get_value("Address", name, ["name", "address_line1", "city", "pincode", "country", "email_id", "phone"], as_dict=True)
		if name else None
	)


def check_customers(companies, since):
	names = frappe.db.sql_list(
		"""SELECT DISTINCT customer FROM `tabSales Invoice`
		WHERE docstatus = 1 AND company IN %(c)s AND posting_date >= %(s)s""",
		{"c": tuple(companies), "s": since},
	)
	fields = ["name", "customer_name", "tax_id", "customer_primary_address"]
	for f in ("custom_peppol_id", "custom_trade_license_number", "custom_legal_registration_identifier_type",
			  "custom_b2c", "custom_is_b2c_customer"):
		if _has("Customer", f):
			fields.append(f)
	rows = []
	for n in names:
		c = frappe.db.get_value("Customer", n, fields, as_dict=True)
		if not c:
			continue
		b2c = c.get("custom_b2c") or c.get("custom_is_b2c_customer")
		missing = []
		if not b2c:
			if not c.get("custom_peppol_id"):
				missing.append("PEPPOL ID")
			if not c.tax_id and not c.get("custom_trade_license_number"):
				missing.append("TRN (Tax ID) or Trade Licence")
			if c.get("custom_legal_registration_identifier_type") == "Commercial/Trade license" and not c.get("custom_trade_license_number"):
				missing.append("Trade Licence Number")
		a = _address_for_customer(c)
		if not a:
			missing.append("billing Address")
		else:
			for f, label in (("address_line1", "Address Line 1"), ("city", "City"), ("emirate", "Emirate"),
							 ("pincode", "Postal code"), ("country", "Country"), ("email_id", "Address email")):
				if f in a and not a.get(f):
					missing.append(label)
				if f == "emirate" and f not in a:
					missing.append("Emirate (Address field missing - uae_erpgulf installed?)")
		if missing:
			rows.append(("Customer", n, c.customer_name, "; ".join(missing)))
	return len(names), rows


def check_items(companies, since):
	names = frappe.db.sql_list(
		"""SELECT DISTINCT sii.item_code FROM `tabSales Invoice Item` sii
		JOIN `tabSales Invoice` si ON si.name = sii.parent
		WHERE si.docstatus = 1 AND si.company IN %(c)s AND si.posting_date >= %(s)s AND IFNULL(sii.item_code,'') != ''""",
		{"c": tuple(companies), "s": since},
	)
	has = {f: _has("Item", f) for f in ("custom_item_type_codes", "custom_hs_code_", "custom_sac_code")}
	rows = []
	for n in names:
		i = frappe.db.get_value("Item", n, ["name", "item_name"] + [f for f, ok in has.items() if ok], as_dict=True)
		if not i:
			continue
		missing = []
		t = i.get("custom_item_type_codes")
		if not t:
			missing.append("Item Type (Goods/Services/Both)")
		if t in ("G - Goods", "B - Both") and not i.get("custom_hs_code_"):
			missing.append("HS code")
		if t in ("S - Services", "B - Both") and not i.get("custom_sac_code"):
			missing.append("SAC code")
		if missing:
			rows.append(("Item", n, i.item_name, "; ".join(missing)))
	return len(names), rows


def check_tax_templates(companies):
	rows = []
	if not _has("Item Tax Template", "custom_vat_category"):
		return 0, rows
	tpls = frappe.get_all("Item Tax Template", filters={"company": ["in", companies], "disabled": 0},
						  fields=["name", "title", "custom_vat_category"])
	for t in tpls:
		if not t.custom_vat_category:
			rows.append(("Item Tax Template", t.name, t.title, "VAT Category (falls back to invoice category)"))
	return len(tpls), rows


def check_modes_of_payment():
	rows = []
	if not _has("Mode of Payment", "custom_payment_means_codes"):
		return 0, rows
	mops = frappe.get_all("Mode of Payment", filters={"enabled": 1}, fields=["name", "custom_payment_means_codes"])
	for m in mops:
		if not m.custom_payment_means_codes:
			rows.append(("Mode of Payment", m.name, m.name, "Payment Means Code"))
	return len(mops), rows


def check_companies(companies):
	rows = []
	for co in companies:
		c = frappe.db.get_value("Company", co, ["name", "tax_id"], as_dict=True)
		missing = []
		if not c.tax_id:
			missing.append("Tax ID (TRN)")
		if _has("Company", "custom_uae_einvoice_enabled") and not frappe.db.get_value("Company", co, "custom_uae_einvoice_enabled"):
			missing.append("UAE e-invoicing not enabled yet")
		if not frappe.db.exists("E-Invoice Provider Settings", {"company": co}) if frappe.db.table_exists("E-Invoice Provider Settings") else True:
			missing.append("E-Invoice Provider Settings row (needs Flick credentials)")
		if missing:
			rows.append(("Company", co, co, "; ".join(missing)))
	return len(companies), rows


def run(months=12, csv_path=None):
	companies = uae_companies()
	print("UAE companies:", companies or "NONE FOUND")
	if not companies:
		return
	since = add_months(nowdate(), -int(months))
	summary, all_rows = [], []
	for label, fn in (
		("Companies", lambda: check_companies(companies)),
		(f"Customers invoiced since {since}", lambda: check_customers(companies, since)),
		(f"Items sold since {since}", lambda: check_items(companies, since)),
		("Item Tax Templates", lambda: check_tax_templates(companies)),
		("Modes of Payment", check_modes_of_payment),
	):
		total, rows = fn()
		summary.append((label, total, len(rows)))
		all_rows += rows

	print("\n%-45s %8s %10s" % ("Scope", "checked", "not ready"))
	for label, total, bad in summary:
		print("%-45s %8s %10s" % (label, total, bad))

	gaps = {}
	for r in all_rows:
		for g in r[3].split("; "):
			gaps[(r[0], g)] = gaps.get((r[0], g), 0) + 1
	print("\nMost common gaps:")
	for (dt, g), n in sorted(gaps.items(), key=lambda x: -x[1]):
		print(f"  {n:6}  {dt}: {g}")

	if csv_path:
		with open(csv_path, "w", newline="") as f:
			w = csv.writer(f)
			w.writerow(["Doctype", "Name", "Title", "Missing"])
			w.writerows(all_rows)
		print("\nDetail written to", csv_path)
	return {"summary": summary, "rows": len(all_rows)}
