"""Invoice currency -> AED exchange rate for PINT-AE (cbc:ExchangeRate).

MOGAS fork. Upstream sent ``invoice.conversion_rate``, which ERPNext defines
as invoice currency -> *company* currency. That is only the AED rate when the
company's currency is AED. MOGAS's UAE companies keep their books in USD, so a
USD invoice would have gone out with rate 1.0 and every AED amount the FTA
receives would be wrong.
"""

from decimal import ROUND_HALF_UP, Decimal

import frappe
from frappe import _

# The UAE dirham is pegged to the US dollar by the Central Bank of the UAE
# (1 USD = 3.6725 AED). Used only when no Currency Exchange record exists.
USD_AED_PEG = 3.6725


def _currency_exchange_record(from_currency, to_currency, date, purpose):
	filters = {"from_currency": from_currency, "to_currency": to_currency, "date": ["<=", date]}
	if purpose == "selling":
		filters["for_selling"] = 1
	elif purpose == "buying":
		filters["for_buying"] = 1
	rate = frappe.db.get_value("Currency Exchange", filters, "exchange_rate", order_by="date desc")
	if rate:
		return float(rate)
	# inverse record
	filters.update({"from_currency": to_currency, "to_currency": from_currency})
	inverse = frappe.db.get_value("Currency Exchange", filters, "exchange_rate", order_by="date desc")
	return 1 / float(inverse) if inverse else None


def get_aed_rate(doc):
	"""AED per one unit of the invoice currency, or None for an AED invoice.
	Order: invoice's own rate (company currency is AED) -> rate via company
	currency (invoice rate x company->AED) -> USD peg."""
	currency = (doc.currency or "").upper()
	if currency == "AED":
		return None

	purpose = "buying" if doc.doctype == "Purchase Invoice" else "selling"
	company_currency = (frappe.get_cached_value("Company", doc.company, "default_currency") or "").upper()
	date = doc.posting_date

	if company_currency == "AED":
		rate = doc.conversion_rate
	else:
		company_to_aed = (
			USD_AED_PEG if company_currency == "USD"
			else _currency_exchange_record(company_currency, "AED", date, purpose)
		)
		if company_to_aed and doc.conversion_rate:
			rate = float(doc.conversion_rate) * float(company_to_aed)
		else:
			rate = _currency_exchange_record(currency, "AED", date, purpose) or (
				USD_AED_PEG if currency == "USD" else None
			)

	if not rate:
		frappe.throw(
			_("No {0} to AED exchange rate for {1}. Add a Currency Exchange record ({0} -> AED or {2} -> AED).").format(
				currency, date, company_currency
			)
		)
	return float(Decimal(str(rate)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))
