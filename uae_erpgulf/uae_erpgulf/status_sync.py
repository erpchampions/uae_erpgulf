"""Common e-invoice status sync for every ASP."""

import json
import frappe
from uae_erpgulf.uae_erpgulf.provider_settings import get_active_provider_settings
from uae_erpgulf.uae_erpgulf.providers import get_adapter
from uae_erpgulf.uae_erpgulf.einvoice_record import DOCTYPE as RECORD_DOCTYPE, get_state, load_invoice, set_state

INVOICE_DOCTYPES = ("Sales Invoice", "Purchase Invoice")
DEFAULT_FINAL_STATUSES = ("reported", "rejected", "failed")
SYNC_LOOKBACK_DAYS = 7
SYNC_BATCH_SIZE = 50


def _flag(adapter, name, default):
    return getattr(adapter, name, default)


def _final_statuses(adapter):
    return tuple(s.lower() for s in _flag(adapter, "FINAL_REPORTING_STATUSES", DEFAULT_FINAL_STATUSES))


def _adapter_for(doc):
    return get_adapter(get_active_provider_settings(doc.company))


def attach_missing_documents(doctype, invoice_name):
    """Fetch only the XML / PDF this invoice doesn't have yet. attach.py
    logs failures to the Error Log; here they are swallowed (and their popup
    messages dropped) so a sync, poll or webhook is never interrupted."""
    from uae_erpgulf.uae_erpgulf.attach import get_document_pdf, get_document_xml

    current = get_state(doctype, invoice_name, ["document_xml", "document_pdf"])

    for attached_field, fetch_fn in (
        ("document_xml", get_document_xml),
        ("document_pdf", get_document_pdf),
    ):
        if current.get(attached_field):
            continue
        messages_before = len(frappe.local.message_log)
        try:
            fetch_fn(doctype, invoice_name)
        except Exception:
            del frappe.local.message_log[messages_before:]


def refresh_invoice_status(doctype, invoice_name):
    """Same steps as the Get Status button: ask the adapter, store the
    response, set custom_reporting_status. Once reported, attach any missing
    XML / PDF. Returns the status (lower case) or None."""
    doc = load_invoice(doctype, invoice_name)
    adapter = _adapter_for(doc)

    result = adapter.get_document_status(doctype, doc)
    if isinstance(result, dict) and "http_status" in result:
        body = result.get("response")
    else:
        body = result

    set_state(
        doctype, invoice_name, {"document_status_response": json.dumps(body, default=str)},
        doc=doc, update_modified=False,
    )

    status = result.get("reporting_status") if isinstance(result, dict) else None
    if not status:
        status = adapter.get_status_from_document_status(body)
    status = (status or "").strip().lower() or None

    if status and status != (doc.get("custom_reporting_status") or "").lower():
        set_state(doctype, invoice_name, {"reporting_status": status}, doc=doc)

    if status == "reported" and _flag(adapter, "ATTACH_DOCUMENTS_IN_SYNC", True):
        attach_missing_documents(doctype, invoice_name)

    frappe.db.commit()  # nosemgrep: frappe-manual-commit
    return status


def sync_pending_invoices():
    """Scheduled every 5 minutes (hooks.py). For every ASP: submitted
    invoices from the last SYNC_LOOKBACK_DAYS days that have a Document ID
    and are not final yet, or are still missing XML / PDF."""
    since = frappe.utils.add_days(frappe.utils.nowdate(), -SYNC_LOOKBACK_DAYS)

    for doctype in INVOICE_DOCTYPES:
        # MOGAS fork: state lives on UAE E-Invoice Submission. Incoming
        # (imported supplier) invoices are not ours to poll.
        rows = frappe.db.sql(
            f"""
            SELECT r.reference_name AS name, r.reporting_status AS custom_reporting_status
            FROM `tab{RECORD_DOCTYPE}` r
            INNER JOIN `tab{doctype}` inv ON inv.name = r.reference_name
            WHERE r.reference_doctype = %(doctype)s
              AND IFNULL(r.direction, 'Outgoing') = 'Outgoing'
              AND IFNULL(r.document_id, '') NOT IN ('', 'Not Submitted')
              AND inv.docstatus = 1
              AND inv.posting_date >= %(since)s
              AND (
                IFNULL(r.reporting_status, '') = ''
                OR LOWER(r.reporting_status) NOT IN %(final)s
                OR IFNULL(r.document_xml, '') = ''
                OR IFNULL(r.document_pdf, '') = ''
              )
            ORDER BY r.modified ASC
            LIMIT %(limit)s
            """,
            {"doctype": doctype, "since": since, "final": DEFAULT_FINAL_STATUSES, "limit": SYNC_BATCH_SIZE},
            as_dict=True,
        )

        for row in rows:
            try:
                doc = frappe.get_doc(doctype, row.name)
                adapter = _adapter_for(doc)
                if not _flag(adapter, "STATUS_SYNC_ENABLED", True):
                    continue

                status = (row.custom_reporting_status or "").lower()
                if status in _final_statuses(adapter):
                    # Final already. Only a reported invoice can still be
                    # waiting for its XML / PDF; rejected / failed never get one.
                    if status != "reported":
                        continue
                    if _flag(adapter, "ATTACH_DOCUMENTS_IN_SYNC", True):
                        attach_missing_documents(doctype, row.name)
                        frappe.db.commit()  # nosemgrep: frappe-manual-commit
                        continue
                    # This adapter attaches files inside get_document_status.

                refresh_invoice_status(doctype, row.name)
            except Exception:
                frappe.db.rollback()
                frappe.log_error(frappe.get_traceback(), f"E-Invoice Status Sync Error - {row.name}")
