// UAE e-invoicing on the Sales / Purchase Invoice form - MOGAS fork.
//
// The invoice has NO UAE custom fields: everything lives on a linked
// "UAE E-Invoice Submission" record. This file (shared by both forms) shows
// the FTA status, the ASP buttons and the "UAE E-Invoice Details" dialog,
// and only for companies with UAE e-invoicing enabled, so other countries
// sharing the same doctypes see nothing.
//
// Defines a namespace only; sales_invoice.js / purchase.js register the
// form events (this file is bundled into both form scripts).

window.uae_erpgulf_einvoice = window.uae_erpgulf_einvoice || (function () {
	const RECORD = "UAE E-Invoice Submission";
	const API = "uae_erpgulf.uae_erpgulf.einvoice_record";
	const STATUS_METHOD = {
		"Sales Invoice": "uae_erpgulf.uae_erpgulf.verify_token.get_document_status",
		"Purchase Invoice": "uae_erpgulf.uae_erpgulf.send_purchase.get_document_status",
	};
	const SEND_METHOD = {
		"Sales Invoice": "uae_erpgulf.uae_erpgulf.submit_sales.generate_and_send_einvoice",
		"Purchase Invoice": "uae_erpgulf.uae_erpgulf.send_purchase.generate_and_send_einvoice",
	};
	const GROUP = __("UAE E-Invoice");

	// field help (was tooltip.js / tooltip_pos.js on the invoice fields)
	const HELP = {
		vat_category: __("VAT treatment for the supply. A line's Item Tax Template VAT Category overrides this."),
		frequency_billing_code_list: __("Billing cycle for recurring / continuous supplies. OTH needs an Invoice Note."),
		invoice_note: __("Free text on the invoice. Mandatory when the Frequency Billing Code is OTH."),
		invoice_transaction_type_code: __("Flag-based code; each '1' position enables a special transaction type."),
		credit_note_reason_code: __("Why this credit note is issued."),
		submit_to_fta: __("Self-billed purchase invoice: send it to the ASP / FTA on submit."),
	};

	function get_info(frm) {
		if (frm.is_new() || !frm.doc.company) {
			return Promise.resolve({ enabled: false, values: {} });
		}
		return frappe
			.call({
				method: `${API}.get_einvoice_info`,
				args: { doctype: frm.doctype, name: frm.doc.name },
			})
			.then((r) => {
				frm.__uae_info = r.message || { enabled: false, values: {} };
				return frm.__uae_info;
			});
	}

	// ------------------------------------------------------------- dialog
	function dialog_fields(frm, info) {
		const is_pi = frm.doctype === "Purchase Invoice";
		const v = info.values || {};
		const df = (fieldname, extra) => {
			const src = frappe.meta.get_docfield(RECORD, fieldname) || {};
			return Object.assign(
				{
					fieldname,
					fieldtype: src.fieldtype,
					label: __(src.label),
					options: src.options,
					default: v[fieldname],
					description: HELP[fieldname] || "",
				},
				extra || {}
			);
		};
		const sent = is_pi ? "doc.submit_to_fta" : "1";
		const fields = [];
		if (is_pi) {
			fields.push(df("submit_to_fta"));
		}
		fields.push(
			df("vat_category", { depends_on: `eval:${sent}` }),
			df("vat_exemption_reason_code", {
				depends_on: `eval:${sent} && doc.vat_category=="E - Exempt from tax"`,
			}),
			df("rcm_nature_code", {
				depends_on: `eval:${sent} && doc.vat_category=="AE - VAT Reverse Charge"`,
			}),
			df("invoice_transaction_type_code", { depends_on: `eval:${sent}` }),
			{ fieldtype: "Column Break" },
			df("frequency_billing_code_list", { depends_on: `eval:${sent}` }),
			df("invoice_note", {
				depends_on: `eval:${sent}`,
				mandatory_depends_on: `eval:${sent} && doc.frequency_billing_code_list=="OTH"`,
			})
		);
		if (is_pi) {
			fields.push(df("payment_means_codes", { depends_on: `eval:${sent}` }));
		}
		if (frm.doc.is_return) {
			fields.push(
				{ fieldtype: "Section Break", label: __("Credit Note"), depends_on: `eval:${sent}` },
				df("credit_note_reason_code", {
					depends_on: `eval:${sent}`,
					mandatory_depends_on: `eval:${sent}`,
				})
			);
			if (info.allow_cn_without_original) {
				if (!frm.doc.return_against) {
					fields.push(df("return_against_for_uae_einvoice", { depends_on: `eval:${sent}` }));
				} else if (!is_pi) {
					fields.push(df("skip_validation_for_credit_note", { depends_on: `eval:${sent}` }));
				}
			}
		}
		return fields;
	}

	// resolves true when saved, false when the user closed the dialog
	function open_dialog(frm, info, primary_label) {
		return frappe.model.with_doctype(RECORD).then(
			() =>
				new Promise((resolve) => {
					let saved = false;
					const d = new frappe.ui.Dialog({
						title: __("UAE E-Invoice Details - {0}", [frm.doc.name]),
						fields: dialog_fields(frm, info),
						size: "large",
						primary_action_label: primary_label,
						primary_action(values) {
							frappe
								.call({
									method: `${API}.save_inputs`,
									args: { doctype: frm.doctype, name: frm.doc.name, values },
									freeze: true,
								})
								.then(() => {
									saved = true;
									d.hide();
									resolve(true);
								});
						},
					});
					d.onhide = () => {
						if (!saved) resolve(false);
					};
					d.show();
				})
		);
	}

	function before_submit(frm) {
		return get_info(frm).then((info) => {
			if (!info.enabled) return;
			return open_dialog(frm, info, __("Save & Submit")).then((ok) => {
				if (!ok) frappe.validated = false;
			});
		});
	}

	// ------------------------------------------------------------ refresh
	function status_badge(values) {
		const einvoice = (values.uae_einvoice_status || "").toUpperCase();
		const reporting = (values.reporting_status || "").toUpperCase();
		if (einvoice === "FAILED" || reporting === "FAILED" || reporting === "REJECTED") {
			return [reporting === "REJECTED" ? __("FTA Rejected") : __("FTA Failed"), "red"];
		}
		if (einvoice === "SUCCESS" && reporting === "REPORTED") return [__("FTA Reported"), "green"];
		if (einvoice === "SUCCESS" && reporting === "PENDING") return [__("FTA Pending"), "orange"];
		if (einvoice === "SUCCESS" && reporting === "NOT REPORTED") return [__("Not Reported"), "gray"];
		if (einvoice === "SUCCESS") return [__("Sent to ASP"), "blue"];
		return [__("Not Submitted to FTA"), "gray"];
	}

	// resolves with the info so a form script can add its own UAE-only bits
	function refresh(frm) {
		if (frm.is_new()) return Promise.resolve({ enabled: false, values: {} });
		return get_info(frm).then((info) => {
			add_form_ui(frm, info);
			return info;
		});
	}

	function add_form_ui(frm, info) {
		if (!info.enabled) return;
		const v = info.values || {};
		const is_pi = frm.doctype === "Purchase Invoice";
		const self_billed = !is_pi || cint(v.submit_to_fta);
		const status = v.uae_einvoice_status || "Not Submitted";
		const reported = (v.reporting_status || "").toLowerCase() === "reported";

		if (self_billed && frm.doc.docstatus > 0) {
			const [label, color] = status_badge(v);
			frm.dashboard.add_indicator(__("UAE E-Invoice: {0}", [label]), color);
		}

		// details: editable until the ASP accepted it
		if (frm.doc.docstatus < 2 && status !== "Success") {
			frm.add_custom_button(
				__("E-Invoice Details"),
				() => open_dialog(frm, info, __("Save")).then((ok) => ok && frm.reload_doc()),
				GROUP
			);
		}
		if (info.record) {
			frm.add_custom_button(
				__("Open E-Invoice Record"),
				() => frappe.set_route("Form", RECORD, info.record),
				GROUP
			);
		}

		if (frm.doc.docstatus !== 1 || !self_billed) return;

		if (status === "Not Submitted" || (v.reporting_status || "").toLowerCase() === "failed") {
			frm.add_custom_button(
				__("Send Invoice"),
				() =>
					frm.call({
						method: SEND_METHOD[frm.doctype],
						args: { doc: { doctype: frm.doctype, name: frm.doc.name } },
						freeze: true,
						freeze_message: __("Generating and sending UAE E-Invoice..."),
						callback(r) {
							if (!r.exc) frm.reload_doc();
						},
					}),
				GROUP
			);
		}

		if (status === "Not Submitted") return;

		if (!reported) {
			frm.add_custom_button(
				__("Get Document Status"),
				() =>
					frappe.call({
						method: STATUS_METHOD[frm.doctype],
						args: { invoice_name: frm.doc.name },
						freeze: true,
						freeze_message: __("Checking Document Status..."),
						callback(r) {
							if (r.message) {
								show_status_response(r.message);
								frm.reload_doc();
							}
						},
					}),
				GROUP
			);
		}

		// XML / PDF: only while not attached yet
		if (!v.document_xml) {
			frm.add_custom_button(__("Get XML"), () => fetch_document(frm, "xml"), GROUP);
		}
		if (!v.document_pdf) {
			frm.add_custom_button(__("Get PDF"), () => fetch_document(frm, "pdf"), GROUP);
		}
	}

	function fetch_document(frm, kind) {
		const label = kind.toUpperCase();
		frappe.call({
			method: `uae_erpgulf.uae_erpgulf.attach.get_document_${kind}`,
			args: { doctype: frm.doctype, invoice_name: frm.doc.name },
			freeze: true,
			freeze_message: __("Fetching Document {0}...", [label]),
			callback(r) {
				if (r.message && r.message.file_url) {
					frappe.msgprint({
						title: __("Document {0}", [label]),
						message: `<p>${__("{0} fetched and attached to this invoice.", [label])}</p>
							<p><a href="${encodeURI(r.message.file_url)}" target="_blank">${__("Open {0}", [label])}</a></p>`,
						indicator: "green",
					});
					frm.reload_doc();
				}
			},
			// attach.py throws the ASP's own reason; the default error dialog shows it
		});
	}

	// was badge_sales.js / badges_purchase.js
	function show_status_response(envelope) {
		const httpStatus =
			envelope && typeof envelope === "object" && "http_status" in envelope ? envelope.http_status : undefined;
		const res = envelope && typeof envelope === "object" && "response" in envelope ? envelope.response : envelope;
		const isArray = Array.isArray(res);
		const isObject = res && typeof res === "object" && !isArray;
		const primary = isArray ? res[res.length - 1] || {} : isObject ? res : {};
		const nested = primary && typeof primary === "object" && primary.data && typeof primary.data === "object" ? primary.data : {};

		const findKeyLike = (obj, patterns) => {
			if (!obj || typeof obj !== "object") return undefined;
			for (const p of patterns) {
				for (const key of Object.keys(obj)) {
					if (p.test(key) && obj[key] !== undefined && obj[key] !== null && obj[key] !== "") {
						return obj[key];
					}
				}
			}
			return undefined;
		};

		const documentId = findKeyLike(primary, [/^id$/i]) ?? findKeyLike(nested, [/^id$/i]) ?? "-";
		const status = findKeyLike(primary, [/status/i]) ?? findKeyLike(nested, [/status/i]) ?? "-";
		const esc = (x) => frappe.utils.escape_html(String(x));
		const isHttpSuccess = typeof httpStatus === "number" && httpStatus >= 200 && httpStatus < 300;

		frappe.msgprint({
			title: __("Document Status"),
			indicator: !isHttpSuccess ? "red" : status === "reported" ? "green" : "orange",
			wide: true,
			message: `
				<p><b>${__("HTTP Status")}:</b> ${esc(httpStatus ?? "-")}</p>
				<p><b>${__("Document ID")}:</b> ${esc(documentId)}</p>
				<p><b>${__("Status")}:</b> ${esc(status)}</p>
				<p style="margin-top:12px;"><b>${__("Response")}</b></p>
				<pre style="white-space:pre-wrap;background:var(--subtle-fg);padding:12px;border-radius:6px;max-height:400px;overflow:auto;font-size:12px;">${esc(
					JSON.stringify(res, null, 2)
				)}</pre>`,
		});
	}

	return { RECORD, get_info, before_submit, refresh, open_dialog };
})();
