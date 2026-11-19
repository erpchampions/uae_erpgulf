// UAE E-Invoice Dashboard.
// MOGAS fork: UAE status lives on "UAE E-Invoice Submission" (not on the
// invoices), so counts and lists come from report_utils, filtered by company.
const UAE_DASH_API = "uae_erpgulf.uae_erpgulf.report_utils";

frappe.pages["uae-e-invoice-dashbo"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "UAE E-Invoice Dashboard",
		single_column: true,
	});

	const body = $(page.body);
	body.append(`<div id="dashboard-cards"></div>`);
	body.append(`<div id="reporting-chart" style="margin-top:40px;"></div>`);
	body.append(`<div id="sales-invoice-list" style="margin-top:40px;"></div>`);
	body.append(`<div id="purchase-invoice-list" style="margin-top:40px;"></div>`);

	const company_field = page.add_field({
		fieldname: "company",
		label: __("Company"),
		fieldtype: "Link",
		options: "Company",
		default: frappe.defaults.get_user_default("Company"),
		get_query: () => ({ filters: { custom_uae_einvoice_enabled: 1 } }),
		change: () => uae_dash_refresh(company_field.get_value()),
	});

	uae_dash_refresh(company_field.get_value());
};

function uae_dash_refresh(company) {
	frappe
		.call({ method: `${UAE_DASH_API}.get_dashboard_counts`, args: { company } })
		.then((r) => {
			const counts = r.message || {};
			uae_dash_render_cards(counts, company);
			uae_dash_render_chart(counts);
		});
	uae_dash_render_list("Sales Invoice", "#sales-invoice-list", __("Customer"), company);
	uae_dash_render_list("Purchase Invoice", "#purchase-invoice-list", __("Supplier"), company);
}

function uae_dash_render_cards(counts, company) {
	const container = $("#dashboard-cards");
	container.empty();

	const sections = [
		{ title: __("Reported From FTA"), key: "reported", status: "Reported", color: "#28a745" },
		{ title: __("Success From ASP"), key: "success", status: "Success", color: "#17a2b8" },
		{ title: __("Failed"), key: "failed", status: "Failed", color: "#dc3545" },
		{ title: __("Not Submitted"), key: "not_submitted", status: "Not Submitted", color: "#ffc107" },
		{ title: __("Cancelled"), key: "cancelled", status: "Cancelled", color: "#6c757d" },
	];

	for (let i = 0; i < sections.length; i += 3) {
		const row_div = $(`<div class="row" style="margin-bottom:30px;"></div>`);
		sections.slice(i, i + 3).forEach((section) => {
			const section_div = $(`
				<div class="col-lg-4">
					<h4 style="text-align:center;margin-top:25px;margin-bottom:20px;font-weight:600;">
						${section.title}
					</h4>
					<div class="row inner-row justify-content-center"></div>
				</div>
			`);
			const inner_row = section_div.find(".inner-row");

			["Sales Invoice", "Purchase Invoice"].forEach((doctype) => {
				const value = ((counts[doctype] || {})[section.key]) || 0;
				const report =
					doctype === "Sales Invoice"
						? "UAE E-Invoice Sales Status Report"
						: "UAE E-Invoice Purchase Status Report";
				const params = new URLSearchParams({ status: section.status });
				if (company) params.set("company", company);
				const url = `/app/query-report/${encodeURIComponent(report)}?${params.toString()}`;

				inner_row.append(`
					<div class="col-md-6">
						<a href="${url}" style="text-decoration:none;color:inherit;">
							<div style="background:var(--card-bg);padding:19px;border-radius:12px;
								box-shadow:0 2px 6px rgba(0,0,0,0.1);text-align:center;margin-bottom:15px;">
								<h5>${__(doctype)}</h5>
								<p>${section.title}</p>
								<h2 style="color:${section.color};">${value}</h2>
							</div>
						</a>
					</div>
				`);
			});
			row_div.append(section_div);
		});
		container.append(row_div);
	}
}

function uae_dash_render_chart(counts) {
	const s = counts["Sales Invoice"] || {};
	const p = counts["Purchase Invoice"] || {};
	$("#reporting-chart").empty();
	new frappe.Chart("#reporting-chart", {
		title: __("Reporting Status"),
		data: {
			labels: [__("Reported"), __("Failed")],
			datasets: [
				{ name: __("Sales"), values: [s.reported || 0, s.failed || 0] },
				{ name: __("Purchase"), values: [p.reported || 0, p.failed || 0] },
			],
		},
		type: "bar",
		height: 300,
	});
}

function uae_dash_render_list(doctype, selector, party_label, company) {
	frappe
		.call({ method: `${UAE_DASH_API}.get_dashboard_rows`, args: { doctype, company, limit: 20 } })
		.then((r) => {
			const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
			const rows = (r.message || [])
				.map(
					(row) => `
				<tr>
					<td><a href="/app/${frappe.router.slug(doctype)}/${encodeURIComponent(row.name)}">${esc(row.name)}</a></td>
					<td>${esc(row.party)}</td>
					<td>${esc(row.posting_date)}</td>
					<td>${esc(row.reporting_status || "-")}</td>
					<td>${esc(row.uae_einvoice_status)}</td>
					<td>${esc(row.grand_total)}</td>
				</tr>`
				)
				.join("");

			$(selector).html(`
				<h4>${__("{0} List", [__(doctype)])}</h4>
				<table class="table table-bordered">
					<thead>
						<tr>
							<th>${__("Invoice")}</th>
							<th>${party_label}</th>
							<th>${__("Date")}</th>
							<th>${__("Reporting")}</th>
							<th>${__("UAE Status")}</th>
							<th>${__("Total")}</th>
						</tr>
					</thead>
					<tbody>${rows}</tbody>
				</table>
			`);
		});
}
