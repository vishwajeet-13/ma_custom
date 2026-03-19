frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		if (cint(frm.doc.docstatus) === 0 && !frm.doc.is_return) {
			frm.add_custom_button(
				__("Purchase Invoice"),
				function () {
					let d = erpnext.utils.map_current_doc({
						method: "ma_custom.api.sales_invoice.make_sales_invoice_from_purchase_invoice",
						source_doctype: "Purchase Invoice",
						target: frm,
						setters: {
							supplier: undefined,
						},
						get_query_filters: {
							docstatus: 1,
							company: frm.doc.company,
						},
						allow_child_item_selection: true,
						child_fieldname: "items",
						child_columns: ["item_code", "item_name", "qty", "amount"],
					});
					if (d && d.dialog) {
						d.dialog.$wrapper.find(".btn-secondary-dark").hide();
					}
				},
				__("Get Items From")
			);
		}
	},
});
