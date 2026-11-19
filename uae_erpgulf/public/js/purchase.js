// Purchase Invoice - UAE e-invoicing (MOGAS fork).
// Status, ASP buttons and the "E-Invoice Details" dialog come from
// uae_einvoice_form.js; nothing here touches invoice fields, and every UAE
// button is limited to companies with UAE e-invoicing enabled.
frappe.ui.form.on("Purchase Invoice", {
    refresh(frm) {
        uae_erpgulf_einvoice.refresh(frm).then((info) => {
            if (info.enabled && frm.doc.docstatus !== 2) {
                const document_id = (info.values || {}).document_id;
                frm.add_custom_button(__('Match & Approve'), function () {
                    match_and_approve_fta(frm, document_id);
                }, __("UAE E-Invoice"));
                if (document_id) {
                    check_fta_match_status(frm, document_id);
                }
            }
        });

        // import of supplier invoices received through the ASP
        if (frm.doc.company) {
            frappe.db.get_value("Company", frm.doc.company, "custom_uae_einvoice_enabled").then((r) => {
                if (cint((r.message || {}).custom_uae_einvoice_enabled)) {
                    frm.add_custom_button(__('Get FTA Incoming Invoices'), function () {
                        get_fta_incoming_invoices(frm);
                    }, __('Get Items From'));
                }
            });
        }
    },
    before_submit(frm) {
        return uae_erpgulf_einvoice.before_submit(frm);
    },
});

function get_fta_incoming_invoices(frm) {
    frappe.call({
        method: 'uae_erpgulf.uae_erpgulf.get_purchase_inv.get_fta_incoming_invoices',
        freeze: true,
        freeze_message: __('Fetching FTA Incoming Invoices...'),
        callback: function (r) {
            console.log("FTA Invoices response:", r);
            if (r.message && r.message.length > 0) {
                show_fta_invoices_dialog(frm, r.message);
            } else {
                frappe.msgprint({
                    title: __('No Records Found'),
                    message: __('No FTA Incoming Invoices with status "Not Submitted" found.'),
                    indicator: 'orange'
                });
            }
        }
    });
}

function show_fta_invoices_dialog(frm, invoices) {
    console.log("Invoices received:", invoices);

    // Build simple HTML table instead of Frappe grid
    let table_rows = '';
    invoices.forEach((inv, idx) => {
        table_rows += `
            <tr>
                <td style="text-align:center; padding:8px;">
                    <input type="checkbox" class="fta-row-check" data-idx="${idx}" 
                           data-document_id="${inv.document_id || ''}" 
                           data-docname="${inv.name}"
                           style="width:16px; height:16px; cursor:pointer;">
                </td>
                <td style="padding:8px;">${inv.document_id || ''}</td>
                <td style="padding:8px; font-size:12px; color:#555;">${inv.incoming_invoice_file || ''}</td>
            </tr>
        `;
    });

    const table_html = `
        <div style="margin: 10px 0;">
            <p class="text-muted">${invoices.length} record(s) found with status <b>Not Submitted</b></p>
            <table class="table table-bordered" style="width:100%; border-collapse:collapse;">
                <thead style="background:#f5f5f5;">
                    <tr>
                        <th style="width:50px; text-align:center; padding:8px;">
                            <input type="checkbox" class="fta-select-all" style="width:16px; height:16px; cursor:pointer;">
                        </th>
                        <th style="padding:8px;">Document ID</th>
                        <th style="padding:8px;">Incoming Invoice File</th>
                    </tr>
                </thead>
                <tbody>
                    ${table_rows}
                </tbody>
            </table>
        </div>
        <div style="text-align:right; padding: 5px 0 10px 0;">
            <button class="btn btn-primary fta-import-btn">Import Selected</button>
        </div>
    `;

    const dialog = new frappe.ui.Dialog({
        title: __('FTA Incoming Invoices - Not Submitted'),
        fields: [
            {
                fieldtype: 'HTML',
                fieldname: 'fta_table_html',
                options: table_html
            }
        ]
    });

    // Remove this dialog from the page when closed, so old ones don't pile up
    dialog.onhide = function () {
        dialog.$wrapper.remove();
    };

    // Select All - only this dialog's checkboxes
    dialog.$wrapper.on('change', '.fta-select-all', function () {
        dialog.$wrapper.find('.fta-row-check').prop('checked', $(this).prop('checked'));
    });

    // Import button - only this dialog's button
    dialog.$wrapper.on('click', '.fta-import-btn', function () {
        console.log("=== IMPORT CLICKED ===");
        const btn = $(this);

        const selected_rows = [];
        dialog.$wrapper.find('.fta-row-check:checked').each(function () {
            selected_rows.push({
                document_id: $(this).attr('data-document_id'),
                docname: $(this).attr('data-docname')
            });
        });
        console.log("Selected rows:", selected_rows);

        if (selected_rows.length === 0) {
            frappe.msgprint({
                title: __('Nothing Selected'),
                message: __('Please select at least one invoice.'),
                indicator: 'red'
            });
            return;
        }

        btn.prop('disabled', true).text('Importing...');
        process_invoices_sequentially(selected_rows, 0, [], dialog, frm);
    });

    dialog.show();
}

function process_invoices_sequentially(rows, index, results, dialog, frm) {
    console.log(`Processing ${index + 1} of ${rows.length}`);

    if (index >= rows.length) {
        dialog.hide();

        const success = results.filter(r => r.success);
        const failed = results.filter(r => !r.success);

        console.log("Done. Success:", success.length, "Failed:", failed.length);

        let msg = `<b>${success.length} Purchase Invoice(s) created:</b><br>`;
        success.forEach(r => {
            msg += `✅ <a href="/app/purchase-invoice/${r.purchase_invoice}" 
                        target="_blank">${r.purchase_invoice}</a> 
                        &nbsp;←&nbsp; Document ID: ${r.document_id}<br>`;
        });

        if (failed.length > 0) {
            msg += `<br><b>${failed.length} Failed:</b><br>`;
            failed.forEach(r => {
                msg += `❌ Document ID: ${r.document_id} — ${r.error}<br>`;
            });
        }

        frappe.msgprint({
            title: __('Import Complete'),
            message: msg,
            indicator: success.length > 0 ? 'green' : 'red'
        });

        // ✅ Navigate into the draft PI
        if (success.length === 1) {
            // Single invoice → open it directly
            frappe.set_route('Form', 'Purchase Invoice', success[0].purchase_invoice);
        } else if (success.length > 1) {
            // Multiple invoices → open list view filtered to show only created ones
            frappe.set_route('List', 'Purchase Invoice', {
                name: ['in', success.map(r => r.purchase_invoice)]
            });
        } else {
            // All failed → just reload current doc
            frm.reload_doc();
        }

        return;
    }

    const row = rows[index];
    const docname = row.docname;

    console.log("Calling API for docname:", docname);

    if (!docname) {
        console.error("No docname for row:", row);
        results.push({
            success: false,
            document_id: row.document_id,
            error: 'Could not resolve docname'
        });
        process_invoices_sequentially(rows, index + 1, results, dialog, frm);
        return;
    }

    frappe.call({
        method: 'uae_erpgulf.uae_erpgulf.get_purchase_inv.create_purchase_invoice_from_fta',
        args: { docname: docname },
        freeze: true,
        freeze_message: __("Importing {0}...", [row.document_id]),
        callback: function (r) {
            console.log("API response for", docname, ":", r);

            if (r.message && r.message.error) {
                console.error("Server error:", r.message.message);
                results.push({
                    success: false,
                    document_id: row.document_id,
                    error: r.message.message
                });
            } else if (r.message && r.message.purchase_invoice) {
                console.log("Created PI:", r.message.purchase_invoice);
                results.push({
                    success: true,
                    purchase_invoice: r.message.purchase_invoice,
                    document_id: row.document_id
                });
            } else {
                console.error("Unexpected response:", r);
                results.push({
                    success: false,
                    document_id: row.document_id,
                    error: 'Unexpected response — check console'
                });
            }
            process_invoices_sequentially(rows, index + 1, results, dialog, frm);
        },
        error: function (err) {
            console.error("Call error:", err);
            results.push({
                success: false,
                document_id: row.document_id,
                error: err.message || 'Server error'
            });
            process_invoices_sequentially(rows, index + 1, results, dialog, frm);
        }
    });
}













function match_and_approve_fta(frm, document_id) {
    if (!document_id) {
        frappe.msgprint({
            title: __('Missing Document ID'),
            message: __('This Purchase Invoice has no FTA Document ID to match against.'),
            indicator: 'orange'
        });
        return;
    }

    frappe.call({
        method: 'frappe.client.get_list',
        args: {
            doctype: 'UAE Incoming Invoices',
            filters: { document_id: document_id },
            fields: ['name', 'document_id', 'status']
        },
        callback: function (r) {
            if (r.message && r.message.length > 0) {
                let fta_doc = r.message[0];

                if (fta_doc.document_id === document_id) {
                    frm.dashboard.set_headline(
                        '<span class="indicator green">✅ Matched & Approved by FTA — Document ID: ' + document_id + '</span>'
                    );

                    frappe.show_alert({
                        message: __('✅ Matched! Purchase Invoice is approved by FTA. FTA Record: ' + fta_doc.name),
                        indicator: 'green'
                    }, 8);

                    if (frm.fields_dict['custom_fta_match_status']) {
                        frappe.call({
                            method: 'frappe.client.set_value',
                            args: {
                                doctype: 'Purchase Invoice',
                                name: frm.doc.name,
                                fieldname: 'custom_fta_match_status',
                                value: 'Matched & Approved'
                            },
                            callback: function () {
                                frm.reload_doc();
                            }
                        });
                    }

                } else {
                    frappe.show_alert({
                        message: __('❌ Document ID does not match any FTA record.'),
                        indicator: 'red'
                    }, 8);
                }

            } else {
                frappe.msgprint({
                    title: __('No FTA Match Found'),
                    message: __('No UAE Incoming Invoice found with Document ID: <b>' + document_id + '</b>'),
                    indicator: 'red'
                });
            }
        }
    });
}

function check_fta_match_status(frm, document_id) {
    frappe.call({
        method: 'frappe.client.get_list',
        args: {
            doctype: 'UAE Incoming Invoices',
            filters: { document_id: document_id },
            fields: ['name', 'document_id', 'status']
        },
        callback: function (r) {
            if (r.message && r.message.length > 0) {
                let fta_doc = r.message[0];
                if (fta_doc.document_id === document_id) {
                    frm.dashboard.set_headline(
                        '<span class="indicator green">✅ Matched & Approved by FTA — Document ID: ' + document_id + '</span>'
                    );
                }
            }
        }
    });
}