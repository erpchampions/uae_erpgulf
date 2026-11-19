import frappe
from erpnext.controllers import sales_and_purchase_return as spr


_original_validate_returned_items = spr.validate_returned_items


def _skip_return_item_validation(doc):
    """MOGAS fork: no custom field on Sales Invoice. A UAE credit note skips
    ERPNext's returned-item check when the Company allows credit notes
    without the original invoice and either no Return Against is set or the
    UAE E-Invoice Submission record asks for it."""
    if doc.doctype != "Sales Invoice" or not doc.get("is_return"):
        return False

    from uae_erpgulf.uae_erpgulf.einvoice_record import (
        allows_credit_note_without_original,
        get_state,
        is_uae_company,
    )

    if not (is_uae_company(doc.company) and allows_credit_note_without_original(doc.company)):
        return False
    if not doc.get("return_against"):
        return True
    if doc.name and not doc.is_new():
        return bool(get_state(doc.doctype, doc.name, ["skip_validation_for_credit_note"]).skip_validation_for_credit_note)
    return False


def custom_validate_returned_items(doc):
    if _skip_return_item_validation(doc):
        return

    return _original_validate_returned_items(doc)


spr.validate_returned_items = custom_validate_returned_items
