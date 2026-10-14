// Copyright (c) 2026, BWH and contributors
// For license information, please see license.txt

frappe.ui.form.on("Quotation Markup", {
	refresh(frm) {
		frm.last_markup = frm.doc.markup_percentage;
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Import Items"), () => import_items(frm));
		}
		highlight_unmatched(frm);
	},

	markup_percentage(frm) {
		const apply = () => {
			frm.last_markup = frm.doc.markup_percentage;
			(frm.doc.items || []).forEach((row) => {
				row.markup_percentage = frm.doc.markup_percentage;
				calculate_row(row);
			});
			refresh_items(frm);
		};

		if ((frm.doc.items || []).some((row) => row.markup_percentage)) {
			frappe.confirm(
				__("This will overwrite the Markup % on all rows. Continue?"),
				apply,
				() => {
					frm.doc.markup_percentage = frm.last_markup;
					frm.refresh_field("markup_percentage");
				}
			);
		} else {
			apply();
		}
	},
});

frappe.ui.form.on("Quotation Markup Item", {
	qty: on_row_change,
	cost_rate: on_row_change,
	markup_percentage: on_row_change,
	item_code: (frm) => highlight_unmatched(frm),
	items_remove: (frm) => refresh_items(frm),
});

function on_row_change(frm, cdt, cdn) {
	calculate_row(locals[cdt][cdn]);
	refresh_items(frm);
}

function calculate_row(row) {
	row.selling_rate = flt(
		flt(row.cost_rate) * (1 + flt(row.markup_percentage) / 100),
		precision("selling_rate", row)
	);
	row.cost_amount = flt(flt(row.qty) * flt(row.cost_rate), precision("cost_amount", row));
	row.selling_amount = flt(flt(row.qty) * row.selling_rate, precision("selling_amount", row));
	row.profit = row.selling_amount - row.cost_amount;
}

function refresh_items(frm) {
	const items = frm.doc.items || [];
	frm.doc.total_cost = items.reduce((sum, row) => sum + flt(row.cost_amount), 0);
	frm.doc.total_selling_amount = items.reduce((sum, row) => sum + flt(row.selling_amount), 0);
	frm.doc.total_markup = frm.doc.total_selling_amount - frm.doc.total_cost;
	["items", "total_cost", "total_selling_amount", "total_markup"].forEach((field) =>
		frm.refresh_field(field)
	);
	highlight_unmatched(frm);
}

frappe.dom.set_style(
	".form-grid .qm-unmatched .grid-static-col { background-color: var(--red-100); }",
	"quotation-markup"
);

function highlight_unmatched(frm) {
	frm.fields_dict.items.grid.grid_rows.forEach((grid_row) => {
		grid_row.row?.toggleClass("qm-unmatched", !grid_row.doc.item_code);
	});
}

function import_items(frm) {
	new frappe.ui.FileUploader({
		as_dataurl: true,
		allow_multiple: false,
		restrictions: { allowed_file_types: [".xlsx"] },
		on_success(file) {
			frappe
				.call({
					method: "ma_custom.ma_customisations.doctype.quotation_markup.quotation_markup.get_items_from_excel",
					args: { file_content: file.dataurl },
					freeze: true,
				})
				.then(({ message: items }) => {
					frm.clear_table("items");
					items.forEach((item) => {
						const row = frm.add_child("items", {
							...item,
							markup_percentage: frm.doc.markup_percentage,
						});
						calculate_row(row);
					});
					frm.dirty();
					refresh_items(frm);

					const unmatched = items.filter((item) => !item.item_code).length;
					if (unmatched) {
						frappe.msgprint(
							__(
								"{0} item(s) could not be matched. Select the Item on the rows highlighted in red.",
								[unmatched]
							)
						);
					}
				});
		},
	});
}
